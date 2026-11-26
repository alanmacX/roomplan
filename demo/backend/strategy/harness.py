"""Smart Home Agent Harness — Bounded Multi-Step ReAct Tool-Calling Orchestrator.

Handles complex, multi-step, comparative, conditional, and cross-room natural
language instructions (e.g., "找到最亮的灯关掉，再看看哪个房间最冷把空调关了",
"把所有没人房间的灯关掉，再把最热的房间空调开到25度") via a domain-scoped
toolset (`get_home_environment`, `query_devices`, `inspect_room_camera`,
`control_device`, `trigger_scene`).

Supports BOTH:
  1) External OpenAI-compatible / Ollama function-calling LLMs (`HOME_LLM_BASE_URL`)
  2) Built-in deterministic symbolic multi-step planner (100% functional offline/local)
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

from backend.common import room_for_item
from backend.control.service import ControlLayerService
from backend.strategy.engine import StrategyEngine

# Natural spatial micro-climate offsets per room archetype (so rooms have realistic thermal/light gradients)
_ROOM_THERMAL_OFFSET: dict[str, tuple[float, int, float]] = {
    # room_id -> (temp_delta_C, humidity_delta_pct, window_lux_factor)
    "living": (0.4, 0, 1.15),
    "scan-room": (0.4, 0, 1.15),
    "dining": (0.2, 2, 0.95),
    "kitchen": (1.5, 4, 0.85),
    "master": (-0.6, -2, 1.0),
    "bed": (-0.6, -2, 1.0),
    "elder": (-0.2, 0, 0.95),
    "bed2": (-0.2, 0, 0.95),
    "study": (-1.8, -4, 0.88),
    "bed3": (-1.8, -4, 0.88),
    "bed4": (-0.9, -2, 0.85),
    "entry": (-0.4, 0, 0.55),
    "hall": (-0.5, 0, 0.50),
    "bath": (0.7, 12, 0.45),
    "bath2": (0.5, 10, 0.45),
}

HARNESS_TRIGGER_CUES: tuple[str, ...] = (
    "最亮的", "最暗的", "哪盏灯最亮", "哪盏灯最暗", "哪个灯最亮", "哪个灯最暗", "开得最亮",
    "最冷", "最热", "最凉", "最暖", "最潮", "最闷",
    "温度最高", "温度最低", "湿度最高", "湿度最低", "亮度最高", "亮度最低",
    "一样亮", "一样暗", "一样高", "一样低", "相同亮度", "相同温度",
    "如果", "要是", "假如", "当", "超过", "高于", "低于", "大于", "小于", "不足",
    "没人", "无人", "空着", "有人在", "没人的房间", "有人的房间",
    "找到", "找出", "排查", "巡检", "看看哪个", "哪个房间", "哪间房", "哪盏灯",
)


def needs_agent_harness(text: str) -> bool:
    """Determine whether an instruction requires multi-step tool-calling orchestration."""
    t = text.strip()
    # Single-device max/min level commands like "把客厅灯调到最亮" belong to fast slot engine
    if re.search(r"(?:调到|调至|设为|开到|调成)(?:最亮|最暗|最高温|最低温)", t) and "然后" not in t and "再" not in t:
        return False
    if any(cue in t for cue in HARNESS_TRIGGER_CUES):
        return True
    # Multi-step sequential connectors across heterogeneous targets
    steps = [p.strip() for p in re.split(r"[，,；;。]|然后|接着|之后|再看看|再去|顺便看看", t) if p.strip()]
    if len(steps) >= 2 and any(w in t for w in ("然后", "接着", "之后", "先", "再看看")):
        return True
    return False


def compute_room_environments(m: dict) -> list[dict]:
    """Compute live per-room temperature, humidity, illuminance, and occupancy."""
    clim = m.get("climate", {})
    base_t = float(clim.get("indoor", 27.5))
    base_rh = int(clim.get("humidity", 60))
    base_lux = float(clim.get("lux", 110))
    plan = m["plan"]
    occupied_map = m.get("occupied", {})

    out: list[dict] = []
    for r in plan.get("rooms", []):
        if r.get("restricted"):
            continue
        rid = r["id"]
        dt, drh, w_fac = _ROOM_THERMAL_OFFSET.get(rid, (0.0, 0, 0.85))
        room_t = base_t + dt
        room_rh = max(20, min(98, base_rh + drh))

        room_items = [
            it for it in plan.get("items", [])
            if (room_for_item(plan, it) or {}).get("id") == rid
            or (rid == "living" and it.get("mount") == "ceiling")
        ]
        # Active AC shifts room micro-climate realistically toward its setpoint
        acs_on = [it for it in room_items if it.get("type") == "ac" and it.get("power")]
        for ac in acs_on:
            mode = ac.get("mode", "制冷")
            tgt = float(ac.get("target", 25))
            if mode == "制冷":
                room_t = round(tgt + 0.4, 1)
                room_rh = max(35, room_rh - 6)
            elif mode == "制热":
                room_t = round(tgt - 0.3, 1)
                room_rh = max(30, room_rh - 8)
            elif mode == "除湿":
                room_t = round(min(room_t, tgt + 0.6), 1)
                room_rh = max(38, room_rh - 18)

        # Active lamps + curtain aperture affect room illuminance
        curtains = [it for it in room_items if it.get("type") == "curtain"]
        shade_factor = (sum(float(c.get("position", 70)) for c in curtains) / (100.0 * len(curtains))) if curtains else 0.75
        lamp_lux = sum(
            (float(it.get("level", 75)) * 2.4 if it["type"] == "lamp" else 140.0)
            for it in room_items if it["type"] in ("lamp", "switch") and it.get("power")
        )
        room_lux = int(round(base_lux * w_fac * (0.35 + 0.65 * shade_factor) + lamp_lux))

        out.append({
            "room_id": rid,
            "name": r["name"],
            "zone": r.get("zone", "public"),
            "temp_c": round(room_t, 1),
            "humidity_pct": int(room_rh),
            "lux": room_lux,
            "occupied": bool(occupied_map.get(rid, False)),
            "sleep_dnd": bool(r.get("sleep", False)),
            "ac_on": bool(acs_on),
        })
    return out


class HomeToolset:
    """Domain-scoped read & action tools exposed to the Home Agent Harness."""

    def __init__(self, key: str, m: dict, vis_plan: dict, role: str,
                 control: ControlLayerService, strategy: StrategyEngine,
                 analyze_cam_fn):
        self.key = key
        self.m = m
        self.vis_plan = vis_plan
        self.role = role
        self.control = control
        self.strategy = strategy
        self.analyze_cam_fn = analyze_cam_fn
        self.applied_actions: list[dict] = []
        self.touched_ids: list[str] = []
        self.trace: list[dict] = []

    def _sync_vis(self) -> None:
        live = {it["id"]: it for it in self.m["plan"]["items"]}
        for it in self.vis_plan["items"]:
            if it["id"] in live:
                it.update(live[it["id"]])

    def get_home_environment(self) -> list[dict]:
        self._sync_vis()
        envs = compute_room_environments({"plan": self.vis_plan, "climate": self.m["climate"], "occupied": self.m.get("occupied", {})})
        return envs

    def query_devices(self, room_id: str | None = None, category: str | None = None,
                      only_on: bool = False) -> list[dict]:
        self._sync_vis()
        cat_map = {
            "lighting": ("lamp", "switch"),
            "lamp": ("lamp", "switch"),
            "hvac": ("ac",),
            "ac": ("ac",),
            "shade": ("curtain",),
            "curtain": ("curtain",),
        }
        allowed_types = cat_map.get(category or "", None)
        res = []
        for it in self.vis_plan["items"]:
            if it["type"] not in ("lamp", "switch", "ac", "curtain"):
                continue
            if allowed_types and it["type"] not in allowed_types:
                continue
            rm = room_for_item(self.vis_plan, it)
            rid = rm["id"] if rm else ("living" if it.get("mount") == "ceiling" else None)
            if room_id and rid != room_id:
                continue
            is_on = bool(it.get("power")) if "power" in it else (int(it.get("position", 0)) > 5)
            if only_on and not is_on:
                continue
            res.append({
                "id": it["id"],
                "name": it["name"],
                "type": it["type"],
                "room_id": rid,
                "room_name": rm["name"] if rm else "客厅",
                "on": is_on,
                "level": int(it.get("level", 65)) if it["type"] == "lamp" else (100 if is_on and it["type"] == "switch" else 0),
                "color_temp": it.get("color_temp"),
                "target": it.get("target"),
                "mode": it.get("mode"),
                "fan_speed": it.get("fan_speed"),
                "position": it.get("position"),
            })
        return res

    def inspect_room_camera(self, room_id: str, camera_b64: str | None = None) -> dict:
        envs = {e["room_id"]: e for e in self.get_home_environment()}
        env = envs.get(room_id) or next(iter(envs.values()), {"room_id": room_id, "name": "客厅", "lux": 95})
        vis = self.analyze_cam_fn(camera_b64) if camera_b64 else None
        luma = vis["luma_0_255"] if vis else round(min(235.0, max(28.0, env["lux"] * 0.55)), 1)
        perceived = "偏暗" if luma < 112 else ("适中" if luma < 178 else "明亮")
        lamps = self.query_devices(room_id=env["room_id"], category="lighting")
        return {
            "room_id": env["room_id"],
            "room_name": env["name"],
            "luma": luma,
            "perceived": perceived,
            "lamps": lamps,
        }

    def control_device(self, device_id: str, capability: str, value: object, reason_label: str = "") -> dict:
        batch = [{"deviceId": device_id, "capability": capability, "value": value}]
        applied = self.control.execute_action_batch(
            self.key, self.m, batch, role=self.role, source="home_harness",
            reason=reason_label or "家居智能体多步编排"
        )
        self.applied_actions.extend(applied)
        if device_id not in self.touched_ids:
            self.touched_ids.append(device_id)
        self._sync_vis()
        it = next((x for x in self.vis_plan["items"] if x["id"] == device_id), None)
        rm = room_for_item(self.vis_plan, it) if it else None
        return {
            "ok": True,
            "device_id": device_id,
            "name": it["name"] if it else device_id,
            "room_id": rm["id"] if rm else None,
            "capability": capability,
            "value": value,
        }

    def add_trace(self, kind: str, title: str, detail: str,
                  room_id: str | None = None, device_id: str | None = None) -> None:
        self.trace.append({
            "step": len(self.trace) + 1,
            "kind": kind,  # "probe" | "act" | "guard"
            "title": title,
            "detail": detail,
            "room_id": room_id,
            "device_id": device_id,
        })


class HomeAgentHarness:
    """Multi-step ReAct Tool-Calling Orchestrator for complex Smart Home instructions."""

    MAX_STEPS = 8

    def __init__(self, control: ControlLayerService, strategy: StrategyEngine, analyze_cam_fn):
        self.control = control
        self.strategy = strategy
        self.analyze_cam_fn = analyze_cam_fn

    def run(self, key: str, m: dict, vis_plan: dict, text: str, role: str,
            camera_b64: str | None = None, camera_room: str | None = None,
            room_Normalizer=None) -> dict | None:
        tools = HomeToolset(key, m, vis_plan, role, self.control, self.strategy, self.analyze_cam_fn)

        # 1. Try external OpenAI-compatible Tool-Calling LLM if configured (`HOME_LLM_BASE_URL`)
        llm_url = os.environ.get("HOME_LLM_BASE_URL", "").strip()
        if llm_url:
            llm_res = self._run_external_llm_loop(llm_url, tools, text, camera_b64, camera_room)
            if llm_res is not None:
                return llm_res

        # 2. Built-in Symbolic Multi-Step Tool-Calling Planner (100% functional offline/local)
        return self._run_symbolic_planner(tools, text, camera_b64, camera_room, room_Normalizer)

    # --------------------------------------------------------------------------
    # Built-in Multi-Step Symbolic Planner (Executes Real Tool Calls Step-by-Step)
    # --------------------------------------------------------------------------
    def _run_symbolic_planner(self, tools: HomeToolset, text: str,
                              camera_b64: str | None, camera_room: str | None,
                              room_extractor) -> dict | None:
        # Split sequential sub-goals while keeping "如果...就..." conditional pairs together!
        raw_clauses = self._split_goal_steps(text)
        summaries: list[str] = []
        last_matched_room: dict | None = None

        for clause in raw_clauses:
            if len(tools.trace) >= self.MAX_STEPS:
                break
            step_note, last_matched_room = self._execute_goal_step(
                tools, clause, camera_b64, camera_room, room_extractor, last_matched_room
            )
            if step_note:
                summaries.append(step_note)

        if not tools.trace and not summaries:
            return None

        reply = "；".join(summaries)
        if not reply.endswith(("。", "？", "！")):
            reply += "。"
        return {
            "tier_used": "home_harness",
            "actions_applied": tools.applied_actions,
            "touched_ids": tools.touched_ids,
            "trace": tools.trace,
            "reply": reply,
            "explanation": f"家居智能体多步编排（共执行 {len(tools.trace)} 步工具调用）：{reply}",
        }

    @staticmethod
    def _split_goal_steps(text: str) -> list[str]:
        # Protect conditional "如果A，就B" from splitting in the middle of the condition
        protected = re.sub(r"(如果|要是|假如|当)([^，,；;。]+)[，,]\s*(就|则|那|便|把|将|请)", r"\1\2__COND_THEN__\3", text)
        # Also merge "看看哪个房间最冷，把那里的空调关了" where clause 2 refers to "那里/它/那个房间"
        raw_parts = [p.strip() for p in re.split(r"[；;。]|然后|接着|之后|再看看|再去|同时|并且|[，,](?=\s*(?:再|顺便|另外|找到|找出|看看|检查|哪|把所有|如果|要是))", protected) if p.strip()]
        # Further split on comma ONLY when second half doesn't depend on an unresolved superlative in first half
        refined: list[str] = []
        for p in raw_parts:
            p = p.replace("__COND_THEN__", "，就")
            sub = [x.strip() for x in re.split(r"[，,]", p) if x.strip()]
            if len(sub) >= 2:
                # Merge if sub[0] is a pure superlative/query ("看看哪个房间最冷") and sub[1] acts on it ("把那里的空调关了" / "关掉空调")
                merged: list[str] = []
                i = 0
                while i < len(sub):
                    cur = sub[i]
                    if i + 1 < len(sub) and any(k in cur for k in ("哪个", "哪间", "哪盏", "最冷", "最热", "最亮", "最暗", "最高", "最低")) and not any(v in cur for v in ("关", "开", "调", "设", "拉", "合")):
                        merged.append(cur + "，" + sub[i + 1])
                        i += 2
                    else:
                        merged.append(cur)
                        i += 1
                refined.extend(merged)
            else:
                refined.append(p)
        return refined or [text]

    def _execute_goal_step(self, tools: HomeToolset, clause: str,
                           camera_b64: str | None, camera_room: str | None,
                           room_extractor, prev_room: dict | None) -> tuple[str | None, dict | None]:
        c = clause.strip()
        num_m = re.search(r"(\d+(?:\.\d+)?)", c)
        num_val = float(num_m.group(1)) if num_m else None

        # ----------------------------------------------------------------------
        # Pattern 1: Conditional Guard ("如果客厅超过28度就把空调开到25度")
        # ----------------------------------------------------------------------
        m_cond = re.search(r"(?:如果|要是|假如|当)(.+?)(?:，就|就|则|便|那么)(.+)", c)
        if m_cond:
            cond_part, act_part = m_cond.group(1), m_cond.group(2)
            envs = tools.get_home_environment()
            rms = room_extractor(cond_part, tools.vis_plan) if room_extractor else []
            target_env = next((e for e in envs if rms and e["room_id"] == rms[0]["id"]), envs[0] if envs else None)
            if target_env:
                cond_ok, cond_desc = self._eval_condition(cond_part, target_env, tools, camera_b64)
                tools.add_trace("probe" if cond_ok else "guard", f"核查{target_env['name']}条件", cond_desc, room_id=target_env["room_id"])
                if not cond_ok:
                    return f"{target_env['name']}{cond_desc}，无需触发后续动作", target_env
                # Condition satisfied -> execute consequent on target_env!
                if room_extractor and not room_extractor(act_part, tools.vis_plan):
                    act_part = target_env["name"] + act_part
                sub_note, _ = self._execute_goal_step(tools, act_part, camera_b64, target_env["room_id"], room_extractor, target_env)
                return f"{target_env['name']}{cond_desc}，{sub_note or '已执行调节'}", target_env

        # ----------------------------------------------------------------------
        # Pattern 2: Superlative Lamp Brightness ("找到最亮的灯关掉" / "把最暗的灯调到80%")
        # ----------------------------------------------------------------------
        if any(k in c for k in ("最亮", "亮度最高", "开得最亮", "最暗", "亮度最低")) and ("灯" in c or "照明" in c or "亮" in c or "暗" in c):
            want_brightest = any(k in c for k in ("最亮", "亮度最高", "开得最亮"))
            wants_off = any(w in c for w in ("关", "熄", "灭"))
            lamps = tools.query_devices(category="lighting", only_on=want_brightest or wants_off)
            if not lamps and not want_brightest:
                lamps = tools.query_devices(category="lighting", only_on=False)
            if not lamps:
                tools.add_trace("probe", "检索全屋灯具", "当前无开启中的灯具")
                return "当前家里没有开着的灯", prev_room

            ranked = sorted(lamps, key=lambda x: x["level"] if x["on"] else 0, reverse=want_brightest)
            chosen = ranked[0]
            top_preview = " · ".join(f"{x['name']} {x['level']}%" for x in ranked[:3])
            tag = "最亮" if want_brightest else "最暗"
            tools.add_trace(
                "probe", "检索灯具亮度", f"{top_preview} → {tag}：{chosen['name']}",
                room_id=chosen["room_id"], device_id=chosen["id"]
            )

            if wants_off:
                tools.control_device(chosen["id"], "power", False, f"关闭{tag}灯具")
                tools.add_trace("act", f"关闭{chosen['name']}", f"{chosen['level']}% → 已关闭", room_id=chosen["room_id"], device_id=chosen["id"])
                return f"已找到{tag}的{chosen['name']}（{chosen['level']}%）并关闭", {"room_id": chosen["room_id"], "name": chosen["room_name"]}
            if any(w in c for w in ("调", "设", "开", "亮", "暗")):
                new_lvl = int(num_val) if num_val is not None else (40 if want_brightest else 80)
                tools.control_device(chosen["id"], "power", True, f"开启{chosen['name']}")
                if chosen["type"] == "lamp":
                    tools.control_device(chosen["id"], "level", new_lvl, f"调节{tag}灯具亮度")
                tools.add_trace("act", f"调节{chosen['name']}", f"亮度 → {new_lvl}%", room_id=chosen["room_id"], device_id=chosen["id"])
                return f"已定位{tag}的{chosen['name']}并调至 {new_lvl}%", {"room_id": chosen["room_id"], "name": chosen["room_name"]}
            return f"目前家里{tag}的是{chosen['name']}（{chosen['level']}%）", {"room_id": chosen["room_id"], "name": chosen["room_name"]}

        # ----------------------------------------------------------------------
        # Pattern 3: Superlative Room Climate ("哪个房间最冷关掉空调" / "最热的房间开空调25度" / "哪个房间最暗开灯")
        # ----------------------------------------------------------------------
        if any(k in c for k in ("最冷", "最凉", "温度最低", "最热", "最暖", "温度最高", "最潮", "最闷", "湿度最高", "最暗的房间", "哪个房间最暗")):
            envs = tools.get_home_environment()
            if not envs:
                return None, prev_room

            if any(k in c for k in ("最冷", "最凉", "温度最低")):
                metric_lbl = "温度最低"
                # Prefer rooms with active AC when breaking close ties on "最冷...关空调"
                ranked_env = sorted(envs, key=lambda e: (e["temp_c"] - (0.15 if e["ac_on"] else 0.0)))
                val_fmt = lambda e: f"{e['temp_c']}°C"
            elif any(k in c for k in ("最热", "最暖", "温度最高")):
                metric_lbl = "温度最高"
                ranked_env = sorted(envs, key=lambda e: e["temp_c"], reverse=True)
                val_fmt = lambda e: f"{e['temp_c']}°C"
            elif any(k in c for k in ("最潮", "最闷", "湿度最高")):
                metric_lbl = "湿度最高"
                ranked_env = sorted(envs, key=lambda e: e["humidity_pct"], reverse=True)
                val_fmt = lambda e: f"{e['humidity_pct']}%"
            else:
                metric_lbl = "照度最低"
                ranked_env = sorted(envs, key=lambda e: e["lux"])
                val_fmt = lambda e: f"{e['lux']} lx"

            best_rm = ranked_env[0]
            env_preview = " · ".join(f"{e['name']} {val_fmt(e)}" for e in ranked_env[:3])
            tools.add_trace(
                "probe", "比对各房环境", f"{env_preview} → {metric_lbl}：{best_rm['name']}",
                room_id=best_rm["room_id"]
            )

            # Determine action requested on that winning room!
            wants_off = any(w in c for w in ("关", "停", "熄"))
            wants_on = any(w in c for w in ("开", "调", "设", "补光", "除湿", "制冷", "制热"))
            target_ac = ("空调" in c or "冷气" in c or "除湿" in c or "温度" in metric_lbl or "湿度" in metric_lbl) and "灯" not in c
            target_lamp = ("灯" in c or "照明" in c or "照度" in metric_lbl)

            if target_ac and (wants_off or wants_on):
                acs = tools.query_devices(room_id=best_rm["room_id"], category="ac")
                if not acs:
                    # Fallback: check coldest/hottest room that actually has an AC!
                    acs_all = tools.query_devices(category="ac", only_on=wants_off)
                    if acs_all:
                        ac_rids = {a["room_id"] for a in acs_all}
                        sub_ranked = [e for e in ranked_env if e["room_id"] in ac_rids]
                        if sub_ranked:
                            best_rm = sub_ranked[0]
                            acs = [a for a in acs_all if a["room_id"] == best_rm["room_id"]]
                if not acs:
                    return f"{best_rm['name']}当前{metric_lbl}（{val_fmt(best_rm)}），该房间未安装空调", best_rm
                ac = acs[0]
                if wants_off:
                    if not ac["on"]:
                        tools.add_trace("guard", f"核查{ac['name']}", "当前已是关闭状态", room_id=best_rm["room_id"], device_id=ac["id"])
                        return f"{best_rm['name']}{metric_lbl}（{val_fmt(best_rm)}），{ac['name']}本就处于关闭状态", best_rm
                    tools.control_device(ac["id"], "power", False, f"关闭{metric_lbl}房间空调")
                    tools.add_trace("act", f"关闭{ac['name']}", f"{best_rm['name']} ({val_fmt(best_rm)}) → 空调已关", room_id=best_rm["room_id"], device_id=ac["id"])
                    return f"{best_rm['name']}{metric_lbl}（{val_fmt(best_rm)}），已关闭{ac['name']}", best_rm
                else:
                    mode = "除湿" if ("除湿" in c or "湿度" in metric_lbl) else ("制热" if "制热" in c or "最冷" in c else "制冷")
                    tgt = int(num_val) if (num_val and 16 <= num_val <= 30) else (24 if mode == "除湿" else (23 if mode == "制热" else 25))
                    tools.control_device(ac["id"], "power", True, f"开启{ac['name']}")
                    tools.control_device(ac["id"], "mode", mode, f"设为{mode}")
                    tools.control_device(ac["id"], "target", tgt, f"设温{tgt}°C")
                    tools.add_trace("act", f"调控{ac['name']}", f"{mode} · {tgt}°C", room_id=best_rm["room_id"], device_id=ac["id"])
                    return f"{best_rm['name']}{metric_lbl}（{val_fmt(best_rm)}），已开启{ac['name']}并设为{mode} {tgt}°C", best_rm

            if target_lamp and (wants_off or wants_on):
                lamps = tools.query_devices(room_id=best_rm["room_id"], category="lighting")
                if lamps:
                    lp = lamps[0]
                    if best_rm.get("sleep_dnd") and wants_on:
                        tools.add_trace("guard", f"跳过{lp['name']}", f"{best_rm['name']}处于睡眠免打扰", room_id=best_rm["room_id"])
                        return f"{best_rm['name']}处于睡眠免打扰状态，已跳过开灯", best_rm
                    if wants_off:
                        tools.control_device(lp["id"], "power", False, "关闭照明")
                        tools.add_trace("act", f"关闭{lp['name']}", "已关闭", room_id=best_rm["room_id"], device_id=lp["id"])
                        return f"已关闭{best_rm['name']}的{lp['name']}", best_rm
                    lvl = int(num_val) if (num_val and 1 <= num_val <= 100) else 80
                    tools.control_device(lp["id"], "power", True, "补光开启")
                    if lp["type"] == "lamp":
                        tools.control_device(lp["id"], "level", lvl, "调节亮度")
                    tools.add_trace("act", f"开启{lp['name']}", f"亮度 → {lvl}%", room_id=best_rm["room_id"], device_id=lp["id"])
                    return f"{best_rm['name']}{metric_lbl}（{val_fmt(best_rm)}），已开启{lp['name']}至 {lvl}%", best_rm

            return f"目前{metric_lbl}的是{best_rm['name']}（{val_fmt(best_rm)}）", best_rm

        # ----------------------------------------------------------------------
        # Pattern 4: Occupancy-Filtered Sweep ("把所有没人房间的灯和空调关掉" / "有人的房间开灯")
        # ----------------------------------------------------------------------
        if any(k in c for k in ("没人", "无人", "空着", "有人")):
            want_unoccupied = any(k in c for k in ("没人", "无人", "空着"))
            wants_off = any(w in c for w in ("关", "熄", "停"))
            envs = tools.get_home_environment()
            matched_rooms = [e for e in envs if (not e["occupied"] if want_unoccupied else e["occupied"])]
            rids = {e["room_id"] for e in matched_rooms}
            tag = "无人房间" if want_unoccupied else "有人房间"
            tools.add_trace("probe", f"排查{tag}", f"共 {len(matched_rooms)} 间（{'、'.join(e['name'] for e in matched_rooms[:4])}）")

            cat = "ac" if ("空调" in c and "灯" not in c) else ("lighting" if ("灯" in c and "空调" not in c) else None)
            devs = [d for d in tools.query_devices(category=cat, only_on=wants_off) if d["room_id"] in rids]
            if wants_off:
                if not devs:
                    return f"目前{tag}内没有未关闭的设备", prev_room
                closed_names = []
                for d in devs:
                    tools.control_device(d["id"], "power", False, f"{tag}节能关闭")
                    closed_names.append(d["name"])
                tools.add_trace("act", f"关闭{tag}设备", "、".join(closed_names[:4]), device_id=devs[0]["id"], room_id=devs[0]["room_id"])
                return f"已将{tag}内的 {len(closed_names)} 台设备（{'、'.join(closed_names[:3])}）全部关闭", prev_room
            else:
                opened = []
                for rm_e in matched_rooms:
                    if rm_e["sleep_dnd"]:
                        continue
                    lps = tools.query_devices(room_id=rm_e["room_id"], category="lighting")
                    if lps and not lps[0]["on"]:
                        tools.control_device(lps[0]["id"], "power", True, f"{tag}开启照明")
                        opened.append(lps[0]["name"])
                if opened:
                    tools.add_trace("act", f"开启{tag}照明", "、".join(opened[:4]))
                    return f"已为{tag}开启{'、'.join(opened[:3])}", prev_room
                return f"{tag}的照明已处于开启状态", prev_room

        # ----------------------------------------------------------------------
        # Pattern 5: Cross-Device Reference Sync ("把走廊灯调到跟客厅灯一样亮")
        # ----------------------------------------------------------------------
        m_same = re.search(r"把?(.+?)(?:调到|设为|改成)?(?:跟|和|与)(.+?)(?:一样|相同)(亮|暗|温度|高|低)?", c)
        if m_same and room_extractor:
            rms_dst = room_extractor(m_same.group(1), tools.vis_plan)
            rms_src = room_extractor(m_same.group(2), tools.vis_plan)
            if rms_dst and rms_src:
                is_ac = "空调" in c or "温度" in (m_same.group(3) or "")
                src_devs = tools.query_devices(room_id=rms_src[0]["id"], category="ac" if is_ac else "lighting")
                dst_devs = tools.query_devices(room_id=rms_dst[0]["id"], category="ac" if is_ac else "lighting")
                if src_devs and dst_devs:
                    s_dev, d_dev = src_devs[0], dst_devs[0]
                    if is_ac:
                        tgt = s_dev["target"] or 25
                        tools.add_trace("probe", f"读取{s_dev['name']}", f"目标温度 {tgt}°C", room_id=s_dev["room_id"], device_id=s_dev["id"])
                        tools.control_device(d_dev["id"], "power", True)
                        tools.control_device(d_dev["id"], "target", tgt)
                        tools.add_trace("act", f"同步{d_dev['name']}", f"设为 {tgt}°C", room_id=d_dev["room_id"], device_id=d_dev["id"])
                        return f"已将{d_dev['name']}同步设为与{s_dev['name']}一致的 {tgt}°C", {"room_id": d_dev["room_id"], "name": d_dev["room_name"]}
                    else:
                        lvl = s_dev["level"] or 70
                        tools.add_trace("probe", f"读取{s_dev['name']}", f"当前亮度 {lvl}%", room_id=s_dev["room_id"], device_id=s_dev["id"])
                        tools.control_device(d_dev["id"], "power", True)
                        if d_dev["type"] == "lamp":
                            tools.control_device(d_dev["id"], "level", lvl)
                        tools.add_trace("act", f"同步{d_dev['name']}", f"亮度 → {lvl}%", room_id=d_dev["room_id"], device_id=d_dev["id"])
                        return f"已将{d_dev['name']}亮度同步调至 {lvl}%", {"room_id": d_dev["room_id"], "name": d_dev["room_name"]}

        # ----------------------------------------------------------------------
        # Pattern 6: Direct / Anaphoric Room Step inside a Multi-Step Chain
        # ----------------------------------------------------------------------
        rms = room_extractor(c, tools.vis_plan) if room_extractor else []
        target_rid = rms[0]["id"] if rms else (prev_room.get("room_id") if prev_room else camera_room)
        if not target_rid and rms:
            target_rid = rms[0]["id"]

        if camera_b64 and any(w in c for w in ("镜头", "画面", "看看", "太暗", "太亮")):
            rid_cam = target_rid or camera_room or "living"
            cam_info = tools.inspect_room_camera(rid_cam, camera_b64)
            tools.add_trace("probe", f"分析{cam_info['room_name']}镜头", f"画面亮度 {cam_info['luma']} ({cam_info['perceived']})", room_id=rid_cam)
            if cam_info["lamps"] and (cam_info["perceived"] == "偏暗" or "暗" in c):
                lp = cam_info["lamps"][0]
                lvl = int(num_val) if (num_val and 1 <= num_val <= 100) else 80
                tools.control_device(lp["id"], "power", True)
                if lp["type"] == "lamp":
                    tools.control_device(lp["id"], "level", lvl)
                tools.add_trace("act", f"开启{lp['name']}", f"补光至 {lvl}%", room_id=rid_cam, device_id=lp["id"])
                return f"{cam_info['room_name']}室内画面{cam_info['perceived']}，已开启{lp['name']}至 {lvl}%", {"room_id": rid_cam, "name": cam_info["room_name"]}

        if target_rid:
            wants_off = any(w in c for w in ("关", "合上", "拉上", "熄"))
            if "窗帘" in c or "帘" in c:
                curs = tools.query_devices(room_id=target_rid, category="curtain")
                if not curs:
                    curs = tools.query_devices(category="curtain")
                if curs:
                    pos = 0 if wants_off else (int(num_val) if num_val is not None else 100)
                    tools.control_device(curs[0]["id"], "position", pos)
                    tools.add_trace("act", f"{'闭合' if pos == 0 else '拉开'}{curs[0]['name']}", f"开合度 → {pos}%", room_id=curs[0]["room_id"], device_id=curs[0]["id"])
                    return f"已将{curs[0]['name']}{'合上' if pos == 0 else f'开至 {pos}%'}", {"room_id": target_rid, "name": curs[0]["room_name"]}
            if "空调" in c or "度" in c or "制冷" in c or "制热" in c or "除湿" in c:
                acs = tools.query_devices(room_id=target_rid, category="ac")
                if acs:
                    ac = acs[0]
                    if wants_off:
                        tools.control_device(ac["id"], "power", False)
                        tools.add_trace("act", f"关闭{ac['name']}", "已关闭", room_id=target_rid, device_id=ac["id"])
                        return f"已关闭{ac['name']}", {"room_id": target_rid, "name": ac["room_name"]}
                    tgt = int(num_val) if (num_val and 16 <= num_val <= 30) else 25
                    mode = "除湿" if "除湿" in c else ("制热" if "制热" in c else "制冷")
                    tools.control_device(ac["id"], "power", True)
                    tools.control_device(ac["id"], "mode", mode)
                    tools.control_device(ac["id"], "target", tgt)
                    tools.add_trace("act", f"设定{ac['name']}", f"{mode} · {tgt}°C", room_id=target_rid, device_id=ac["id"])
                    return f"已将{ac['name']}设为{mode} {tgt}°C", {"room_id": target_rid, "name": ac["room_name"]}
            if "灯" in c or wants_off or "开" in c or "亮" in c:
                lps = tools.query_devices(room_id=target_rid, category="lighting")
                if lps:
                    lp = lps[0]
                    if wants_off:
                        tools.control_device(lp["id"], "power", False)
                        tools.add_trace("act", f"关闭{lp['name']}", "已关闭", room_id=target_rid, device_id=lp["id"])
                        return f"已关闭{lp['name']}", {"room_id": target_rid, "name": lp["room_name"]}
                    lvl = int(num_val) if (num_val and 1 <= num_val <= 100) else 80
                    tools.control_device(lp["id"], "power", True)
                    if lp["type"] == "lamp":
                        tools.control_device(lp["id"], "level", lvl)
                    tools.add_trace("act", f"开启{lp['name']}", f"亮度 → {lvl}%", room_id=target_rid, device_id=lp["id"])
                    return f"已开启{lp['name']}（{lvl}%）", {"room_id": target_rid, "name": lp["room_name"]}

        return None, prev_room

    @staticmethod
    def _eval_condition(cond_str: str, env: dict, tools: HomeToolset, camera_b64: str | None) -> tuple[bool, str]:
        num_m = re.search(r"(\d+(?:\.\d+)?)", cond_str)
        thr = float(num_m.group(1)) if num_m else None
        if "暗" in cond_str or "镜头" in cond_str:
            cam = tools.inspect_room_camera(env["room_id"], camera_b64)
            ok = cam["luma"] < 118
            return ok, f"画面亮度 {cam['luma']} ({cam['perceived']})"
        if "湿度" in cond_str or "潮" in cond_str:
            t_rh = thr if thr is not None else 70
            ok = env["humidity_pct"] > t_rh if any(w in cond_str for w in ("超", "高", "大")) else env["humidity_pct"] < t_rh
            return ok, f"当前湿度 {env['humidity_pct']}%"
        if "没人" in cond_str or "无人" in cond_str:
            return (not env["occupied"]), ("当前无人" if not env["occupied"] else "当前有人")
        if "有人" in cond_str:
            return env["occupied"], ("当前有人" if env["occupied"] else "当前无人")
        t_deg = thr if thr is not None else 27.0
        if any(w in cond_str for w in ("低", "小", "冷", "不足")):
            return env["temp_c"] < t_deg, f"室温 {env['temp_c']}°C"
        return env["temp_c"] > t_deg, f"室温 {env['temp_c']}°C"

    # --------------------------------------------------------------------------
    # External OpenAI-Compatible Tool-Calling Loop (`HOME_LLM_BASE_URL`)
    # --------------------------------------------------------------------------
    def _run_external_llm_loop(self, base_url: str, tools: HomeToolset, text: str,
                               camera_b64: str | None, camera_room: str | None) -> dict | None:
        api_key = os.environ.get("HOME_LLM_API_KEY", os.environ.get("OPENAI_API_KEY", "ollama"))
        model = os.environ.get("HOME_LLM_MODEL", "qwen2.5-7b-instruct")
        tool_schemas = [
            {
                "type": "function",
                "function": {
                    "name": "get_home_environment",
                    "description": "获取所有房间的实时温度、湿度、照度、是否有人及睡眠免打扰状态",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "query_devices",
                    "description": "按房间或类别查询智能设备实时状态（开关、亮度、温度、开合度）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "room_id": {"type": "string"},
                            "category": {"type": "string", "enum": ["lighting", "ac", "curtain"]},
                            "only_on": {"type": "boolean"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "control_device",
                    "description": "控制单个智能设备能力参数",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "device_id": {"type": "string"},
                            "capability": {"type": "string", "enum": ["power", "level", "color_temp", "mode", "target", "fan_speed", "position"]},
                            "value": {},
                        },
                        "required": ["device_id", "capability", "value"],
                    },
                },
            },
        ]
        messages: list[dict] = [
            {"role": "system", "content": "你是家庭智能体编排中枢。对多步指令，先调用查询工具核实设备或各房环境数据，再调用控制工具执行，最后用一句简短自然的中文总结结果。"},
            {"role": "user", "content": text},
        ]
        try:
            for _ in range(6):
                req = urllib.request.Request(
                    base_url.rstrip("/") + "/chat/completions",
                    data=json.dumps({"model": model, "messages": messages, "tools": tool_schemas, "temperature": 0.1}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    msg = json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]
                messages.append(msg)
                tcalls = msg.get("tool_calls") or []
                if not tcalls:
                    reply = (msg.get("content") or "已完成多步控制。").strip()
                    return {
                        "tier_used": "home_harness",
                        "actions_applied": tools.applied_actions,
                        "touched_ids": tools.touched_ids,
                        "trace": tools.trace,
                        "reply": reply,
                        "explanation": f"外部大模型工具编排完成：{reply}",
                    }
                for tc in tcalls:
                    fn = tc["function"]["name"]
                    args = json.loads(tc["function"].get("arguments") or "{}")
                    if fn == "get_home_environment":
                        obs = tools.get_home_environment()
                        tools.add_trace("probe", "读取各房环境", f"共 {len(obs)} 个房间传感快照")
                    elif fn == "query_devices":
                        obs = tools.query_devices(**args)
                        tools.add_trace("probe", "检索家庭设备", f"匹配 {len(obs)} 台设备")
                    elif fn == "control_device":
                        obs = tools.control_device(args["device_id"], args["capability"], args["value"])
                        tools.add_trace("act", f"调节{obs['name']}", f"{args['capability']} → {args['value']}", room_id=obs["room_id"], device_id=obs["device_id"])
                    else:
                        obs = {"error": "unknown_tool"}
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(obs, ensure_ascii=False)})
        except Exception:
            return None
        return None
