"""Layer 2A: Strategy Layer — 5-Level Conflict Arbitration, Seasonal Hysteresis Climate,
and Ambient Lux Self-Excitation Compensation Engine (F5 + E1).

Translates high-level scenes and environmental events into standardized capability
instructions, delegating actual execution to ControlLayerService.
"""
from __future__ import annotations

import time
from backend.common import SEASONS, Problem, good_id, good_name, is_num, room_for_item
from backend.control.service import ControlLayerService
from backend.data.repository import IHomeRepository


PINNED_UNTIL = 9_999_999_999.0


class StrategyEngine:
    def __init__(self, repo: IHomeRepository, control: ControlLayerService):
        self.repo = repo
        self.control = control

    # --------------------------------------------------------------------------
    # Scene Management & Triggering (F5 + Custom Live Configuration)
    # --------------------------------------------------------------------------
    def upsert_scene(self, key: str, body: dict, role: str) -> dict:
        self.control.check_edit_permission(role)
        sid = body.get("id")
        name = body.get("name")
        if not good_id(sid) or not good_name(name):
            raise Problem("请输入合法的场景标识 ID 与场景中文名称。")
        existing = self.repo.read_scenes(key).get(sid, {})
        actions = body.get("actions", existing.get("actions", []))
        if not isinstance(actions, list) or len(actions) > 30:
            raise Problem("场景动作列表需为 0–30 项数组。")
        for a in actions:
            if not isinstance(a, dict) or not good_id(a.get("deviceId")) or not isinstance(a.get("capability"), str):
                raise Problem("场景动作需包含合法的 deviceId、capability 与 value。")

        spec = {
            **existing,
            "id": sid,
            "name": name.strip(),
            "builtin": bool(existing.get("builtin", False)),
            "description": str(body.get("description", existing.get("description", "自定义联动策略")))[:180],
            "enable_climate": bool(body.get("enable_climate", existing.get("enable_climate", False))),
            "corridor_light_level": int(body.get("corridor_light_level", existing.get("corridor_light_level", 25))),
            "entry_light_level": int(body.get("entry_light_level", existing.get("entry_light_level", 80))),
            "curtain_position": int(body.get("curtain_position", existing.get("curtain_position", 80))),
            "actions": actions,
        }
        self.repo.save_scene(key, sid, spec)
        self.repo.record_event(key, None, "ok", f"已保存场景配置：「{spec['name']}」（即时热生效）", source="strategy")
        return spec

    def trigger_scene(self, key: str, m: dict, mode: str, role: str = "admin") -> dict:
        scenes = self.repo.read_scenes(key)
        if mode != "normal" and mode not in scenes:
            raise Problem(f"未知的场景模式：{mode}", 400)

        now = time.time()
        pinned_overrides = (
            {} if mode in ("normal", "away")
            else {rid: exp for rid, exp in m.get("overrides", {}).items() if exp > now + 7200}
        )
        m.update(mode=mode, overrides=pinned_overrides, due={})
        if mode == "normal":
            expl = "已切换回「日常手动模式」，释放场景接管并保持各设备当前确认状态。"
            m["last_explanation"] = expl
            self.repo.record_event(key, None, "ok", expl, source="scene")
            self.repo.write_model(key, m)
            return {"mode": mode, "explanation": expl, "skipped": []}

        scene_cfg = scenes[mode]
        skipped_rooms: list[str] = []
        executed_count = 0

        if mode == "away":
            curtain_pos = int(scene_cfg.get("curtain_position", 0))
            for o in m["plan"]["items"]:
                if o["type"] in ("lamp", "switch", "ac") and o.get("power"):
                    if self.control.apply_state_internal(key, m, o, "power", False, "离家全屋节能关闭", source="scene"):
                        executed_count += 1
                elif o["type"] == "curtain" and o.get("position") != curtain_pos:
                    if self.control.apply_state_internal(key, m, o, "position", curtain_pos, "离家安防闭合窗帘", source="scene"):
                        executed_count += 1
            expl = f"已执行「离家模式」：共关闭/闭合 {executed_count} 台非安防设备与窗帘，清空临时接管计时。"

        elif mode == "home":
            entry_lvl = max(1, min(100, int(scene_cfg.get("entry_light_level", 80))))
            curtain_pos = max(0, min(100, int(scene_cfg.get("curtain_position", 85))))
            for o in m["plan"]["items"]:
                rm = room_for_item(m["plan"], o)
                # P1 Pinned Manual Hold & P2 Zone Sleep DND Lock protection:
                if rm and (
                    (rm.get("sleep") and rm.get("zone") == "rest")
                    or m.get("overrides", {}).get(rm["id"], 0) > now + 7200
                ):
                    if rm["name"] not in skipped_rooms:
                        skipped_rooms.append(rm["name"])
                    continue
                if o["type"] in ("lamp", "switch") and (rm is None or rm.get("id") in ("entry", "living", "scan-room")):
                    self.control.apply_state_internal(key, m, o, "power", True, "回家迎宾照明", source="scene")
                    if o["type"] == "lamp":
                        self.control.apply_state_internal(key, m, o, "level", entry_lvl, "回家舒适照度", source="scene")
                    executed_count += 1
                elif o["type"] == "curtain" and (rm is None or rm.get("zone") == "public"):
                    self.control.apply_state_internal(key, m, o, "position", curtain_pos, "回家拉开窗帘", source="scene")
                    executed_count += 1

            clim_expl = self.evaluate_climate(key, m, record=True, skip_sleep_locked=True)
            skip_note = f"；已跳过免打扰锁房间（{'、'.join(skipped_rooms)}）" if skipped_rooms else ""
            expl = f"已执行「回家模式」{skip_note}。{clim_expl}"

        elif mode == "sleep":
            for o in m["plan"]["items"]:
                rm = room_for_item(m["plan"], o)
                if o["type"] in ("lamp", "switch") and rm and rm.get("sleep"):
                    if o.get("power"):
                        self.control.apply_state_internal(key, m, o, "power", False, "分域睡眠关灯并锁止自动感应", source="scene")
                        executed_count += 1
                elif o["type"] == "curtain" and rm and rm.get("sleep"):
                    self.control.apply_state_internal(key, m, o, "position", 0, "睡眠遮光闭合窗帘", source="scene")

            clim_expl = self.evaluate_climate(key, m, record=True, skip_sleep_locked=False)
            self.evaluate_ambient_and_occupancy(key, m)
            expl = (
                f"已开启「分域睡眠模式」：睡眠域卧室已关灯并启用免打扰锁（保留房内手动控制），"
                f"公共通行域启用 {scene_cfg.get('corridor_light_level', 25)}% 柔和伴行感应。{clim_expl}"
            )

        else:
            # Custom user-created scene preset!
            for act in scene_cfg.get("actions", []):
                did = act.get("deviceId")
                item = next((x for x in m["plan"]["items"] if x["id"] == did), None)
                if not item:
                    continue
                rm = room_for_item(m["plan"], item)
                if rm and rm.get("sleep") and not act.get("force"):
                    if rm["name"] not in skipped_rooms:
                        skipped_rooms.append(rm["name"])
                    continue
                if self.control.apply_state_internal(key, m, item, act["capability"], act["value"], f"自定义场景:{scene_cfg['name']}", source="scene"):
                    executed_count += 1
            clim_expl = self.evaluate_climate(key, m, record=True) if scene_cfg.get("enable_climate") else ""
            skip_note = f"（已按免打扰锁跳过：{'、'.join(skipped_rooms)}）" if skipped_rooms else ""
            expl = f"已执行自定义场景「{scene_cfg['name']}」，生效 {executed_count} 项动作{skip_note}。{clim_expl}".strip()

        m["last_explanation"] = expl
        self.repo.record_event(key, None, "ok", expl, source="scene")
        self.repo.write_model(key, m)
        return {"mode": mode, "explanation": expl, "skipped": skipped_rooms}

    # --------------------------------------------------------------------------
    # Seasonal Multi-Objective Climate & ±1°C Hysteresis Calculator (F5 + E1)
    # --------------------------------------------------------------------------
    def evaluate_climate(self, key: str, m: dict, record: bool = False, skip_sleep_locked: bool = False) -> str:
        env = m["climate"]
        now = time.time()
        season = env.get("season", "夏")
        indoor = float(env.get("indoor", 30.0))
        outdoor = float(env.get("outdoor", 33.0))
        humidity = float(env.get("humidity", 65.0))
        is_stale = bool(env.get("stale_sim")) or (now - float(env.get("updated_ts", now)) > float(env.get("ttl", 300)))

        acs = [x for x in m["plan"]["items"] if x["type"] == "ac"]
        curtains = [x for x in m["plan"]["items"] if x["type"] == "curtain"]

        # Edge Case 1: Sensor Offline / Stale TTL fallback (Defense exam highlight!)
        if is_stale:
            safe_temp = 26.0 if season == "夏" else 20.0 if season == "冬" else 24.0
            safe_mode = "制冷" if season == "夏" else "制热" if season == "冬" else "送风"
            for ac in acs:
                rm = room_for_item(m["plan"], ac)
                if m.get("overrides", {}).get((rm or {}).get("id", ""), 0) > now:
                    continue
                self.control.apply_state_internal(key, m, ac, "mode", safe_mode, "传感失联安全降级", source="strategy")
                if safe_mode != "送风":
                    self.control.apply_state_internal(key, m, ac, "target", safe_temp, "传感失联默认安全温", source="strategy")
            expl = f"[传感陈旧降级告警] 温湿度传感器超期未更新 (>TTL)，拒绝使用旧读数盲算，已自动降级为{season}季安全默认策略（{safe_mode} {safe_temp}°C）。"
            if record:
                self.repo.record_event(key, None, "ok", expl, source="strategy")
            return expl

        # Edge Case 2: Spring/Autumn multi-objective conflict (Ventilation vs High-Humidity Dehumidification)
        if season in ("春", "秋"):
            if humidity > 75:
                for ac in acs:
                    rm = room_for_item(m["plan"], ac)
                    if m.get("overrides", {}).get((rm or {}).get("id", ""), 0) > now:
                        continue
                    self.control.apply_state_internal(key, m, ac, "power", True, "过渡季高湿防潮冲突裁决", source="strategy")
                    self.control.apply_state_internal(key, m, ac, "mode", "除湿", "高湿优先除湿", source="strategy")
                    self.control.apply_state_internal(key, m, ac, "target", 24, "除湿舒适基准温", source="strategy")
                for cur in curtains:
                    self.control.apply_state_internal(key, m, cur, "position", 20, "高湿防潮减少外湿侵入", source="strategy")
                expl = f"多目标冲突裁决：{season}季室温 {indoor}°C 适宜，但相对湿度达 {int(humidity)}% (>75%)，「防潮除湿」优先于「开窗通风」，已切换空调至除湿模式。"
            else:
                for ac in acs:
                    if ac.get("power"):
                        self.control.apply_state_internal(key, m, ac, "power", False, "过渡季自然通风节能停机", source="strategy")
                expl = f"{season}季过渡温控策略：当前室温 {indoor}°C、湿度 {int(humidity)}% 干爽宜人，优先建议自然通风并停用空调压缩机。"
            if record:
                self.repo.record_event(key, None, "ok", expl, source="strategy")
            return expl

        # Summer (24–28°C) & Winter (18–22°C) dynamic comfort calculation + humidity compensation + ±1°C hysteresis
        cooling = (season == "夏")
        base = 25.2 if cooling else 20.0
        raw_target = base + 0.12 * (indoor - base) + 0.08 * (outdoor - (30.0 if cooling else 8.0))
        if cooling and humidity >= 70:
            raw_target -= 0.5  # Humid summer feels warmer -> lower target slightly within [24, 28]
        if m.get("mode") == "sleep":
            raw_target += 0.5 if cooling else -0.5  # Gentle night sleep curve

        lo, hi = (24.0, 28.0) if cooling else (18.0, 22.0)
        # Round to nearest 0.5°C for realistic AC setpoint
        target = round(max(lo, min(hi, raw_target)) * 2) / 2
        desired_mode = "制冷" if cooling else "制热"
        desired_fan = "静音" if m.get("mode") == "sleep" else "自动"

        for ac in acs:
            rm = room_for_item(m["plan"], ac)
            rid = (rm or {}).get("id", "")
            # P1 Manual Override check
            if m.get("overrides", {}).get(rid, 0) > now:
                continue
            if skip_sleep_locked and rm and rm.get("sleep") and rm.get("zone") == "rest":
                continue

            room_target = min(28.0, target + 0.5) if (rm and "长辈" in rm.get("name", "") and cooling) else target
            self.control.apply_state_internal(key, m, ac, "mode", desired_mode, f"{season}季动态温控", source="strategy")
            self.control.apply_state_internal(key, m, ac, "target", room_target, f"{season}季舒适目标温", source="strategy")
            if "fan_speed" in ac:
                self.control.apply_state_internal(key, m, ac, "fan_speed", desired_fan, "场景风速匹配", source="strategy")

            # ±1°C Hysteresis band to prevent compressor short-cycling!
            currently_on = bool(ac.get("power"))
            if cooling:
                should_power = (indoor > room_target - 0.5) if currently_on else (indoor >= room_target + 1.0)
                band_txt = f"≥{room_target + 1.0:.1f}°C 启动制冷，≤{room_target - 0.5:.1f}°C 保冷待机"
            else:
                should_power = (indoor < room_target + 0.5) if currently_on else (indoor <= room_target - 1.0)
                band_txt = f"≤{room_target - 1.0:.1f}°C 启动制热，≥{room_target + 0.5:.1f}°C 保温待机"

            self.control.apply_state_internal(key, m, ac, "power", should_power, "±1°C 滞回防频繁启停", source="strategy")

        expl = (
            f"当前室温 {indoor}°C、室外 {outdoor}°C、湿度 {int(humidity)}%，"
            f"按{season}季舒适温湿策略设定目标温度 {target}°C（滞回带：{band_txt}）。"
        )
        if record:
            self.repo.record_event(key, None, "ok", expl, source="strategy")
        return expl

    # --------------------------------------------------------------------------
    # Multi-Modal Environment Sensing, Occupancy & Anti-Oscillation Lighting (E1)
    # --------------------------------------------------------------------------
    def update_environment(self, key: str, m: dict, body: dict) -> dict:
        now = time.time()
        notes: list[str] = []

        # 1. Room occupancy signal (from sensor panel OR 3D avatar walking across portals!)
        room_id = body.get("room")
        if room_id is not None:
            rooms_by_id = {r["id"]: r for r in m["plan"]["rooms"]}
            if not isinstance(room_id, str) or room_id not in rooms_by_id or type(body.get("occupied")) is not bool:
                raise Problem("房间标识或人员存在传感布尔值无效。")
            occ = body["occupied"]
            # If avatar entered a new room and exclusive_walk is set, mark previous walked rooms unoccupied
            if body.get("exclusive_walk") and occ:
                for rid_old in list(m["occupied"].keys()):
                    if rid_old != room_id and m["occupied"].get(rid_old):
                        m["occupied"][rid_old] = False
            m["occupied"][room_id] = occ
            r_obj = rooms_by_id[room_id]
            src_tag = "3D漫游跨门洞感应" if body.get("exclusive_walk") else "存在传感器"
            msg = f"{r_obj['name']} · {'检测到有人进入' if occ else '人员离开'}（{src_tag}）"
            self.repo.record_event(key, None, "ok", msg, source="sensor")
            notes.append(msg)

        # 2. Room sleep DND lock toggle
        if "toggle_sleep_room" in body:
            tr_id = body["toggle_sleep_room"]
            r_target = next((r for r in m["plan"]["rooms"] if r["id"] == tr_id), None)
            if not r_target:
                raise Problem("找不到要切换免打扰锁的房间。")
            r_target["sleep"] = not bool(r_target.get("sleep"))
            lock_msg = f"{r_target['name']} · 睡眠免打扰锁已{'开启（屏蔽自动感应与全屋群控）' if r_target['sleep'] else '解除'}"
            self.repo.record_event(key, None, "ok", lock_msg, source="strategy")
            notes.append(lock_msg)

        # 3. Climate, Humidity, Ambient Lux & Stale Sensor simulation
        if "hold_override" in body:
            hr_id = body["hold_override"]
            r_target = next((r for r in m["plan"]["rooms"] if r["id"] == hr_id), None)
            if not r_target:
                raise Problem("找不到要锁定手动模式的房间。")
            m["overrides"][hr_id] = PINNED_UNTIL
            m["due"].pop(hr_id, None)
            hold_msg = f"{r_target['name']} · 已固定手动控制（暂停传感器自动改写，可随时恢复自动）"
            self.repo.record_event(key, None, "ok", hold_msg, source="manual")
            notes.append(hold_msg)

        if "release_override" in body:
            rr_id = body["release_override"]
            if rr_id == "__all__":
                m["overrides"] = {}
                rel_msg = "全屋已恢复自动感知托管"
            else:
                r_target = next((r for r in m["plan"]["rooms"] if r["id"] == rr_id), None)
                if not r_target:
                    raise Problem("找不到要恢复自动控制的房间。")
                m["overrides"].pop(rr_id, None)
                rel_msg = f"{r_target['name']} · 已交还自动感知托管"
            self.repo.record_event(key, None, "ok", rel_msg, source="strategy")
            notes.append(rel_msg)
            if m.get("mode") in ("home", "sleep"):
                notes.append(self.evaluate_climate(key, m, record=False, skip_sleep_locked=(m.get("mode") == "home")))
        if "climate" in body:
            q = body["climate"]
            if not isinstance(q, dict):
                raise Problem("环境参数格式无效。")
            clim = m["climate"]
            if "season" in q:
                if q["season"] not in SEASONS:
                    raise Problem("季节必须为 春/夏/秋/冬。")
                clim["season"] = q["season"]
            if "indoor" in q:
                if not is_num(q["indoor"], -5, 48):
                    raise Problem("室内温度需在 -5–48°C 之间。")
                clim["indoor"] = round(float(q["indoor"]), 1)
            if "outdoor" in q:
                if not is_num(q["outdoor"], -30, 52):
                    raise Problem("室外温度需在 -30–52°C 之间。")
                clim["outdoor"] = round(float(q["outdoor"]), 1)
            if "humidity" in q:
                if not is_num(q["humidity"], 5, 100):
                    raise Problem("相对湿度需在 5–100% 之间。")
                clim["humidity"] = int(round(float(q["humidity"])))
            if "lux" in q:
                if not is_num(q["lux"], 0, 2000):
                    raise Problem("环境照度需在 0–2000 lx 之间。")
                clim["lux"] = int(round(float(q["lux"])))
            if "stale_sim" in q:
                clim["stale_sim"] = bool(q["stale_sim"])
            if not clim.get("stale_sim"):
                clim["updated_ts"] = now

            if m["mode"] in ("home", "sleep") or q.get("humidity", 0) > 75:
                notes.append(self.evaluate_climate(key, m, record=True))

        if "delay" in body:
            if not is_num(body["delay"], 1, 120):
                raise Problem("无人关灯延时需在 1–120 秒之间。")
            m["delay"] = int(body["delay"])
            m["due"] = {}

        if "override_ttl" in body and is_num(body["override_ttl"], 3, 600):
            m["override_ttl"] = int(body["override_ttl"])

        lux_note = self.evaluate_ambient_and_occupancy(key, m, now=now)
        if lux_note:
            notes.append(lux_note)
        if notes:
            m["last_explanation"] = notes[-1]
        self.repo.write_model(key, m)
        return m

    def evaluate_ambient_and_occupancy(self, key: str, m: dict, now: float | None = None) -> str | None:
        """Evaluate room-level E1 occupancy & anti-oscillation lighting rules."""
        now = now if now is not None else time.time()
        types = self.control.device_layer.get_types()
        clim = m.get("climate", {})
        total_lux = float(clim.get("lux", 110))

        # Estimate true natural ambient lux by deducting active artificial lamp gain!
        lamp_gain = sum(
            types.get(it.get("type"), {}).get("lumens_gain", 0) * (float(it.get("level", 100)) / 100.0)
            for it in m["plan"]["items"] if it.get("power")
        )
        natural_lux = max(0.0, total_lux - lamp_gain * 0.45)
        is_sleep_mode = (m.get("mode") == "sleep")
        scenes = self.repo.read_scenes(key)
        corridor_lvl = int(scenes.get("sleep", {}).get("corridor_light_level", 25))
        note = None

        rooms = m["plan"]["rooms"]
        for r in rooms:
            rid = r["id"]
            # P2: Sleep DND Lock room pauses automatic occupancy turn-on!
            if r.get("sleep") and is_sleep_mode:
                m["due"].pop(rid, None)
                continue

            # P1: Manual Override TTL lease yields automatic rule!
            if m["overrides"].get(rid, 0) > now:
                m["due"].pop(rid, None)
                continue
            m["overrides"].pop(rid, None)

            lamps = [
                o for o in m["plan"]["items"]
                if o["type"] in ("lamp", "switch") and (room_for_item(m["plan"], o) or {}).get("id") == rid
            ]
            if not lamps:
                continue

            occ = bool(m["occupied"].get(rid))
            # Anti-self-excitation dual-threshold hysteresis:
            # Turn ON if occupied AND (sleep mode OR natural ambient lux < 120 lx)
            # Turn OFF if (unoccupied for delay seconds) OR (daylight natural_lux > 260 lx in non-sleep mode)
            if occ and (is_sleep_mode or natural_lux < 120.0):
                m["due"].pop(rid, None)
                target_lvl = corridor_lvl if is_sleep_mode else 75
                for o in lamps:
                    if not o.get("power"):
                        self.control.apply_state_internal(
                            key, m, o, "power", True,
                            f"{'睡眠柔和伴行' if is_sleep_mode else f'低底光({natural_lux:.0f}lx<120lx)补光'}",
                            source="sensor"
                        )
                        if o["type"] == "lamp":
                            self.control.apply_state_internal(key, m, o, "level", target_lvl, "自适应分域亮度", source="sensor")
                        note = f"自适应照明：{r['name']}有人且自然底光 {natural_lux:.0f}lx（总照度 {total_lux:.0f}lx 已扣除灯具光增益防自激），已开启 {target_lvl}% 照明。"
            elif occ and not is_sleep_mode and natural_lux > 260.0 and any(o.get("power") for o in lamps):
                for o in lamps:
                    if o.get("power"):
                        self.control.apply_state_internal(key, m, o, "power", False, f"自然采光充足({natural_lux:.0f}lx>260lx)节能关灯", source="sensor")
                note = f"自适应节能：{r['name']}自然底光达 {natural_lux:.0f}lx (>260lx 滞回上限)，已自动关闭补光灯。"
            elif not occ and any(o.get("power") for o in lamps) and (is_sleep_mode or natural_lux < 200.0):
                due_ts = m["due"].setdefault(rid, now + float(m.get("delay", 6)))
                if due_ts <= now:
                    for o in lamps:
                        if o.get("power"):
                            self.control.apply_state_internal(key, m, o, "power", False, f"无人持续 {m.get('delay', 6)}s 延时熄灯", source="sensor")
                    m["due"].pop(rid, None)
                    note = f"自适应熄灯：{r['name']}无人持续达 {m.get('delay', 6)} 秒，已自动缓灭灯光。"
            else:
                m["due"].pop(rid, None)

        live_ids = {r["id"] for r in rooms}
        for field in ("due", "overrides"):
            m[field] = {k: v for k, v in m[field].items() if k in live_ids}
        return note

    def tick_background(self) -> None:
        """Periodic timer checking expiring occupancy off-timers & override leases."""
        now = time.time()
        for key in self.repo.list_plan_keys():
            m = self.repo.read_model(key)
            has_expired = any(ts <= now for ts in (*m.get("due", {}).values(), *m.get("overrides", {}).values()))
            if not has_expired:
                continue
            note = self.evaluate_ambient_and_occupancy(key, m, now=now)
            if note:
                m["last_explanation"] = note
            self.repo.write_model(key, m)
