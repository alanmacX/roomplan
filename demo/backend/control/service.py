"""Layer 3: Control Layer (RBAC, Whitelist & Mutex Validation, Orchestration).

Responsible for HOW commands and spatial asset mutations are safely validated,
dispatched, retried, and persisted. Contains NO climate formulas or NLP rules.
"""
from __future__ import annotations

import csv
import io
import json
import math
import secrets
import time

from backend.common import (
    ZONE_TYPES, Problem, distance_to_edges, good_id, good_name,
    is_num, is_point, is_polygon, point_in_poly, room_for_item, segment_distance_to_box
)
from backend.data.repository import IHomeRepository
from backend.device.registry import DeviceLayerService


ROLE_POLICIES = {
    "admin": {
        "label": "家庭管理员（户主夫妻）",
        "can_edit_layout": True,
        "can_manage_types": True,
        "can_import_export": True,
        "allowed_zones": {"public", "rest", "work", "guest"},
        "hide_private_occupancy": False,
    },
    "member": {
        "label": "普通成员（同住长辈）",
        "can_edit_layout": False,
        "can_manage_types": False,
        "can_import_export": False,
        "allowed_zones": {"public", "rest", "work", "guest"},
        "hide_private_occupancy": False,
    },
    "guest": {
        "label": "临时访客（限时受控视图）",
        "can_edit_layout": False,
        "can_manage_types": False,
        "can_import_export": False,
        "allowed_zones": {"public", "guest"},
        "hide_private_occupancy": True,
    },
}


class ControlLayerService:
    def __init__(self, repo: IHomeRepository, device_layer: DeviceLayerService, mount_origin: list[float]):
        self.repo = repo
        self.device_layer = device_layer
        self.mount_origin = mount_origin
        self.pending_confirms: dict[str, dict] = {}

    # --------------------------------------------------------------------------
    # Spatial RBAC & Desensitized Snapshot Projection
    # --------------------------------------------------------------------------
    def check_edit_permission(self, role: str) -> None:
        if not ROLE_POLICIES.get(role, ROLE_POLICIES["guest"])["can_edit_layout"]:
            raise Problem("当前角色无权修改户型结构或批量变更资产，请切换管理员身份。", 403)

    def check_room_access(self, role: str, plan: dict, item: dict) -> dict | None:
        room = room_for_item(plan, item)
        policy = ROLE_POLICIES.get(role, ROLE_POLICIES["guest"])
        zone = (room or {}).get("zone", "public")
        if zone not in policy["allowed_zones"]:
            raise Problem(f"权限拒绝：临时访客无权查看或控制私密区域（{room['name'] if room else zone}）的设备。", 403)
        return room

    def project_snapshot(self, key: str, role: str = "admin") -> dict:
        m = self.repo.read_model(key)
        policy = ROLE_POLICIES.get(role, ROLE_POLICIES["guest"])
        types = self.device_layer.get_types()
        scenes = self.repo.read_scenes(key)
        events = self.repo.query_events(key, limit=18)

        now = time.time()
        clim = m.get("climate", {})
        is_stale = bool(clim.get("stale_sim")) or (now - float(clim.get("updated_ts", now)) > float(clim.get("ttl", 300)))

        # Compute estimated ambient lux (deducting artificial lamp gain to prevent self-excitation)
        total_lux = float(clim.get("lux", 110))
        lamp_gain = 0.0
        for it in m["plan"]["items"]:
            tspec = types.get(it.get("type"), {})
            if it.get("power") and tspec.get("lumens_gain", 0) > 0:
                lvl = float(it.get("level", 100)) / 100.0
                lamp_gain += tspec["lumens_gain"] * lvl
        ambient_lux = round(max(0.0, total_lux - lamp_gain * 0.45), 1)

        plan_out = json.loads(json.dumps(m["plan"]))
        occupied_out = dict(m.get("occupied", {}))

        if policy["hide_private_occupancy"]:
            hidden_room_ids = {r["id"] for r in plan_out["rooms"] if r.get("zone") not in policy["allowed_zones"]}
            for r in plan_out["rooms"]:
                if r["id"] in hidden_room_ids:
                    r["restricted"] = True
            plan_out["items"] = [
                it for it in plan_out["items"]
                if (room_for_item(plan_out, it) or {}).get("id") not in hidden_room_ids
            ]
            for rid in hidden_room_ids:
                occupied_out.pop(rid, None)
            events = [ev for ev in events if "主卧" not in ev["message"] and "长辈" not in ev["message"]]

        active_overrides = {
            rid: max(0, int(round(exp - now)))
            for rid, exp in m.get("overrides", {}).items()
            if exp > now
        }
        active_due = {
            rid: max(0, int(round(exp - now)))
            for rid, exp in m.get("due", {}).items()
            if exp > now
        }

        return {
            "plan": plan_out,
            "rev": m["rev"],
            "seq": m["seq"],
            "mode": m["mode"],
            "occupied": occupied_out,
            "overrides": active_overrides,
            "due": active_due,
            "climate": {**clim, "is_stale": is_stale, "ambient_lux": ambient_lux},
            "delay": m.get("delay", 6),
            "override_ttl": m.get("override_ttl", 15),
            "last_explanation": m.get("last_explanation", ""),
            "scenes": scenes,
            "events": events,
            "mountOrigin": self.mount_origin,
            "role": role,
            "roleLabel": policy["label"],
            "permissions": {
                "canEditLayout": policy["can_edit_layout"],
                "canManageTypes": policy["can_manage_types"],
                "canImportExport": policy["can_import_export"],
                "allowedZones": sorted(policy["allowed_zones"]),
            },
        }

    # --------------------------------------------------------------------------
    # Command Validation, Cross-Attribute Mutex & Execution
    # --------------------------------------------------------------------------
    def apply_state_internal(self, key: str, m: dict, item: dict, cap: str, val: object,
                             reason: str, source: str = "strategy") -> bool:
        """Internal state write invoked by Strategy Layer after arbitration."""
        types = self.device_layer.get_types()
        tspec = types.get(item["type"], {})
        caps = tspec.get("caps", {})
        if cap not in caps or not self.device_layer.valid_cap_value(caps[cap], val):
            return False
        if item.get(cap) == val:
            return False
        self.device_layer.execute_simulated(item, cap, val, "ok")
        snapshot_state = {k: item[k] for k in caps if k in item}
        info = self._format_cap_change(item, cap, val)
        self.repo.record_event(key, item["id"], "ok", f"{item['name']} · {info}（{reason}）", snapshot_state, source=source)
        return True

    @staticmethod
    def _format_cap_change(item: dict, cap: str, val: object) -> str:
        if cap == "power":
            if item["type"] in ("lamp", "switch"):
                return "开灯" if val else "关灯"
            return "开机" if val else "关机"
        if cap == "level":
            return f"亮度 {val}%"
        if cap == "color_temp":
            return f"色温 {val}"
        if cap == "position":
            return f"窗帘开合 {val}%"
        if cap == "target":
            return f"目标温度 {val}°C"
        if cap == "mode":
            return f"模式 {val}"
        if cap == "fan_speed":
            return f"风速 {val}"
        return f"{cap}={val}"

    def dispatch_command(self, key: str, m: dict, device_id: str, body: dict,
                         role: str = "admin", on_manual_override=None) -> dict:
        item = self._find_item(m, device_id)
        room = self.check_room_access(role, m["plan"], item)

        cap = body.get("capability")
        val = body.get("value")
        types = self.device_layer.get_types()
        tspec = types.get(item["type"], {})
        caps = tspec.get("caps", {})
        cap_meta = tspec.get("cap_meta", {})

        if not isinstance(cap, str) or cap not in caps:
            raise Problem(f"白名单拦截：设备「{item['name']}」不支持能力项 {cap}。", 400)
        if not self.device_layer.valid_cap_value(caps[cap], val):
            raise Problem(f"参数值域越界：{cap} 允许范围为 {caps[cap]}，当前传入 {val}。", 400)

        # Cross-attribute mutex guard (e.g., AC Fan-Only mode locks target temperature)
        readonly_guard = cap_meta.get(cap, {}).get("readonly_when")
        if isinstance(readonly_guard, dict):
            for gk, gv in readonly_guard.items():
                if item.get(gk) == gv:
                    raise Problem(f"跨属性互斥拦截：当前处于「{gv}」模式，{cap_meta[cap]['label']}已锁定只读。", 400)

        outcome = body.get("outcome", "ok")
        if outcome not in ("ok", "offline", "fail", "timeout"):
            raise Problem("未知的回执模拟状态。", 400)

        exec_res = self.device_layer.execute_simulated(item, cap, val, outcome)
        if outcome == "ok":
            snapshot_state = {k: item[k] for k in caps if k in item}
            staged_suffix = " [关机预配置 Staged]" if exec_res["staged"] else ""
            info = self._format_cap_change(item, cap, val)
            self.repo.record_event(
                key, item["id"], "ok",
                f"{item['name']} · {info}{staged_suffix}（手动控制）",
                snapshot_state, source="manual"
            )
            # Issue P1 Manual Override Lease for room so E1 sensors yield!
            if room:
                ttl_sec = float(m.get("override_ttl", 15))
                m["overrides"][room["id"]] = time.time() + ttl_sec
                if on_manual_override:
                    on_manual_override(key, m)
        else:
            err_msg = {
                "offline": f"{item['name']} · 设备离线，命令未送达（请检查电源或点击重试）",
                "fail": f"{item['name']} · 执行异常，保持原确认状态不变",
                "timeout": f"{item['name']} · 响应超时 (>1s)，保留最后确认态并已发起状态对账",
            }[outcome]
            self.repo.record_event(key, item["id"], outcome, err_msg, None, source="manual")

        self.repo.write_model(key, m)
        return {"result": outcome, "staged": exec_res["staged"], "item": item}

    # --------------------------------------------------------------------------
    # High-Impact Action Secondary Confirmation Tokens (E3 Safety Guardrail)
    # --------------------------------------------------------------------------
    def create_confirm_token(self, key: str, actions: list[dict], explanation: str, tier_used: str) -> str:
        tok = secrets.token_urlsafe(16)
        now = time.time()
        self.pending_confirms = {k: v for k, v in self.pending_confirms.items() if v["exp"] > now}
        self.pending_confirms[tok] = {
            "key": key,
            "actions": actions,
            "explanation": explanation,
            "tier_used": tier_used,
            "exp": now + 180,
        }
        return tok

    def execute_confirmed_token(self, key: str, m: dict, token: str, role: str) -> dict:
        entry = self.pending_confirms.pop(token, None)
        if not entry or entry["key"] != key or entry["exp"] < time.time():
            raise Problem("确认令牌已过期或无效，请重新发起指令。", 400)
        applied = self.execute_action_batch(key, m, entry["actions"], role, source=entry["tier_used"], reason="二次确认执行")
        m["last_explanation"] = entry["explanation"]
        self.repo.write_model(key, m)
        return {"applied": applied, "explanation": entry["explanation"], "tier_used": entry["tier_used"]}

    def execute_action_batch(self, key: str, m: dict, actions: list[dict], role: str,
                             source: str, reason: str) -> list[dict]:
        types = self.device_layer.get_types()
        applied = []
        rejected = []
        for act in actions:
            dev_id = act.get("deviceId")
            cap = act.get("capability")
            val = act.get("value")
            try:
                item = self._find_item(m, dev_id)
            except Problem:
                rejected.append({"deviceId": dev_id, "error": f"白名单拦截：不存在设备 ID {dev_id}"})
                continue
            self.check_room_access(role, m["plan"], item)
            tspec = types.get(item["type"], {})
            caps = tspec.get("caps", {})
            if cap not in caps or not self.device_layer.valid_cap_value(caps[cap], val):
                rejected.append({"deviceId": dev_id, "error": f"白名单拦截：{item['name']} 参数 {cap}={val} 越界或不支持"})
                continue
            readonly_guard = tspec.get("cap_meta", {}).get(cap, {}).get("readonly_when")
            if isinstance(readonly_guard, dict) and any(item.get(gk) == gv for gk, gv in readonly_guard.items()):
                rejected.append({"deviceId": dev_id, "error": f"互斥拦截：{item['name']} 当前模式下 {cap} 不可调"})
                continue
            self.device_layer.execute_simulated(item, cap, val, "ok")
            snapshot_state = {k: item[k] for k in caps if k in item}
            info = self._format_cap_change(item, cap, val)
            self.repo.record_event(key, item["id"], "ok", f"{item['name']} · {info}（{reason}）", snapshot_state, source=source)
            applied.append({"deviceId": item["id"], "name": item["name"], "capability": cap, "value": val})

        if rejected and not applied:
            err_detail = "；".join(r["error"] for r in rejected)
            self.repo.record_event(key, None, "fail", err_detail, None, source=source)
            raise Problem(err_detail, 400)
        return applied

    # --------------------------------------------------------------------------
    # Spatial Layout Validation, Ceiling Mount & Atomic CSV/JSON Asset Management
    # --------------------------------------------------------------------------
    def replace_plan(self, key: str, m: dict, body: dict, role: str, on_after_change=None) -> str | None:
        self.check_edit_permission(role)
        p = body.get("plan")
        if body.get("rev") != m["rev"]:
            raise Problem("版本冲突 (409)：户型已在其他窗口更新，请刷新后再保存。", 409)
        if not isinstance(p, dict) or p.get("key") != key or not is_polygon(p.get("outline")):
            raise Problem("户型外边界多边形无效。")
        if not good_name(p.get("title")):
            raise Problem("请输入 1–70 字符的有效户型名称。")

        for field in ("walls", "doors", "windows"):
            segs = p.get(field)
            if not isinstance(segs, list) or len(segs) > 280 or any(
                not isinstance(w, dict) or not is_point(w.get("a")) or not is_point(w.get("b")) or w["a"] == w["b"]
                for w in segs
            ):
                raise Problem(f"空间线段数据 ({field}) 无效。")

        rooms = p.get("rooms")
        if not isinstance(rooms, list) or len(rooms) > 35:
            raise Problem("房间列表无效。")
        r_ids = set()
        clean_rooms = []
        for r in rooms:
            if (not isinstance(r, dict) or not good_id(r.get("id")) or r["id"] in r_ids
                    or not good_name(r.get("name")) or not is_polygon(r.get("p")) or not is_point(r.get("tag"))):
                raise Problem("房间编号、名称或多边形轮廓无效。")
            r_ids.add(r["id"])
            zone = r.get("zone") if r.get("zone") in ZONE_TYPES else ("rest" if r.get("sleep") else "public")
            clean_rooms.append({
                "id": r["id"],
                "name": r["name"].strip(),
                "p": r["p"],
                "tag": r["tag"],
                "zone": zone,
                "sleep": bool(r.get("sleep", zone == "rest")),
            })

        items = p.get("items")
        if not isinstance(items, list) or len(items) > 260:
            raise Problem("物品列表无效。")

        types = self.device_layer.get_types()
        old_items = {v["id"]: v for v in m["plan"]["items"]}
        new_ids = {v.get("id") for v in items if isinstance(v, dict)}

        # Referential integrity check when deleting items referenced by custom scenes
        removed_ids = set(old_items.keys()) - new_ids
        if removed_ids and not body.get("force"):
            self._check_scene_references(key, removed_ids, old_items)

        seen_ids = set()
        clean_items = []
        portal_warning = None

        for v in items:
            if (not isinstance(v, dict) or not good_id(v.get("id")) or v["id"] in seen_ids
                    or not good_name(v.get("name")) or not isinstance(v.get("type"), str)
                    or v["type"] not in (*types.keys(), "scanned")
                    or not all(is_num(v.get(k), lo, hi) for k, lo, hi in (
                        ("x", -15000, 15000), ("y", -15000, 15000),
                        ("w", 5, 2200), ("h", 5, 2200), ("angle", -3600, 3600)
                    ))):
                raise Problem("物品坐标、尺寸、类型或名称不合法。")
            seen_ids.add(v["id"])
            prev = old_items.get(v["id"])
            if prev and prev.get("mount") == "ceiling":
                clean_items.append({**prev, "name": v["name"].strip()})
                continue

            # Portal clearance warning check (deep domain 1: doorway blockage)
            if v["type"] not in ("lamp", "switch", "curtain", "sensor", "scanned"):
                for door in p["doors"]:
                    if segment_distance_to_box(door["a"], door["b"], v["x"], v["y"]) < max(18.0, min(v["w"], v["h"]) * 0.35):
                        portal_warning = f"提示：「{v['name']}」靠近门洞通行净空区，建议微调位置保障无障碍通行。"

            obj = {k: v[k] for k in ("id", "type", "name", "x", "y", "w", "h", "angle")}
            obj["name"] = obj["name"].strip()
            tspec = types.get(v["type"])
            if tspec:
                for ck, domain in tspec.get("caps", {}).items():
                    if prev and prev["type"] == v["type"] and ck in prev:
                        obj[ck] = prev[ck]
                    elif ck in v and self.device_layer.valid_cap_value(domain, v[ck]):
                        obj[ck] = v[ck]
                self.device_layer.ensure_defaults(obj, tspec)
            clean_items.append(obj)

        m["plan"] = {
            "key": key,
            "title": p["title"].strip(),
            "outline": p["outline"],
            "rooms": clean_rooms,
            "walls": p["walls"],
            "doors": p["doors"],
            "windows": p["windows"],
            "items": clean_items,
        }
        if body.get("replace"):
            m.update(mode="normal", occupied={}, overrides={}, due={})
        m["rev"] += 1
        msg = "已保存户型与空间资产布局" + (f"（{portal_warning}）" if portal_warning else "")
        self.repo.record_event(key, None, "ok", msg, source="layout")
        if on_after_change:
            on_after_change(key, m)
        self.repo.write_model(key, m)
        return portal_warning

    def _check_scene_references(self, key: str, removed_ids: set[str], old_items: dict[str, dict]) -> None:
        scenes = self.repo.read_scenes(key)
        for sid, sdata in scenes.items():
            for act in sdata.get("actions", []):
                did = act.get("deviceId")
                if did in removed_ids:
                    dname = old_items[did]["name"]
                    raise Problem(
                        f"引用完整性拦截：设备「{dname}」正被场景「{sdata.get('name', sid)}」引用，请先修改该场景或确认解绑删除。",
                        409
                    )

    def mount_ceiling_lamp(self, key: str, m: dict, data: dict, role: str, on_after_change=None) -> dict:
        self.check_edit_permission(role)
        u, v = data.get("u"), data.get("v")
        if key not in ("apple", "house") or not is_num(u, -25, 25) or not is_num(v, -25, 25):
            raise Problem("请在扫描客厅有效范围内选点安装吸顶灯。")
        if key == "house":
            origin = [816.2013, 825.0033]
            living_rm = next((r for r in m["plan"]["rooms"] if r["id"] == "living"), None)
            poly = living_rm["p"] if living_rm else m["plan"]["outline"]
        else:
            origin = self.mount_origin
            poly = m["plan"]["outline"]
        x, y = [100 * a + b for a, b in zip((u, v), origin)]
        if not point_in_poly(x, y, poly) or distance_to_edges(x, y, poly) < 16:
            raise Problem("边界阻断：安装点位于客厅外或距墙不足 16 厘米。")
        mounted = [o for o in m["plan"]["items"] if o.get("mount") == "ceiling"]
        if len(mounted) >= 4:
            raise Problem("样例客厅最多允许安装 4 盏吸顶灯。")
        if any(math.hypot(o["x"] - x, o["y"] - y) < 28 for o in mounted):
            raise Problem("间距阻断：安装点距已有吸顶灯不足 28 厘米。")

        n = 1 + max((o.get("n", 0) for o in mounted), default=0)
        obj = {
            "id": "bulb-" + secrets.token_hex(4),
            "type": "lamp",
            "mount": "ceiling",
            "n": n,
            "name": f"吸顶灯 {n}",
            "x": round(x, 4),
            "y": round(y, 4),
            "w": 18,
            "h": 18,
            "angle": 0,
            "power": False,
            "level": 65,
            "color_temp": "暖白",
        }
        m["plan"]["items"].append(obj)
        m["rev"] += 1
        self.repo.record_event(key, obj["id"], "ok", f"三维射线安装 {obj['name']}", {"power": False, "level": 65}, source="layout")
        if on_after_change:
            on_after_change(key, m)
        self.repo.write_model(key, m)
        return obj

    def remove_device(self, key: str, m: dict, device_id: str, role: str, force: bool = False, on_after_change=None) -> None:
        self.check_edit_permission(role)
        obj = self._find_item(m, device_id)
        if not force:
            self._check_scene_references(key, {device_id}, {device_id: obj})
        m["plan"]["items"].remove(obj)
        m["rev"] += 1
        self.repo.record_event(key, device_id, "ok", f"已移除资产 {obj['name']}", source="layout")
        if on_after_change:
            on_after_change(key, m)
        self.repo.write_model(key, m)

    def export_items_csv(self, key: str, role: str) -> str:
        if role == "guest":
            raise Problem("访客无权导出家庭资产清单。", 403)
        m = self.repo.read_model(key)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "name", "type", "room", "x", "y", "w", "h", "angle", "power", "level", "mode", "target", "position"])
        for it in m["plan"]["items"]:
            rm = room_for_item(m["plan"], it)
            writer.writerow([
                it["id"], it["name"], it["type"], rm["name"] if rm else "",
                round(it["x"], 2), round(it["y"], 2), round(it["w"], 2), round(it["h"], 2), round(it.get("angle", 0), 1),
                "" if "power" not in it else str(it["power"]).lower(),
                it.get("level", ""), it.get("mode", ""), it.get("target", ""), it.get("position", ""),
            ])
        return buf.getvalue()

    def import_items_batch(self, key: str, m: dict, body: dict, role: str) -> int:
        """Atomic CSV or JSON batch item import with all-or-nothing validation rollback (F1)."""
        self.check_edit_permission(role)
        fmt = body.get("format", "csv")
        raw_text = body.get("content", "")
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise Problem("导入文件内容为空。")

        types = self.device_layer.get_types()
        outline = m["plan"]["outline"]
        rows_to_apply: list[dict] = []

        if fmt == "csv":
            reader = csv.DictReader(io.StringIO(raw_text.strip()))
            required = {"id", "name", "type", "x", "y"}
            if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
                raise Problem("CSV 表头缺失必填列，需包含：id, name, type, x, y。")
            raw_list = list(reader)
        else:
            try:
                parsed = json.loads(raw_text)
                raw_list = parsed["items"] if isinstance(parsed, dict) and "items" in parsed else parsed
            except ValueError:
                raise Problem("JSON 格式解析失败。")
            if not isinstance(raw_list, list):
                raise Problem("JSON 资产文件需为物品数组。")

        if len(raw_list) == 0 or len(raw_list) > 200:
            raise Problem("单次批量导入条数需在 1–200 条之间。")

        seen = set()
        for idx, row in enumerate(raw_list, start=2 if fmt == "csv" else 1):
            prefix = f"第 {idx} 行校验失败（整批已原子回滚）："
            iid = str(row.get("id", "")).strip()
            iname = str(row.get("name", "")).strip()
            itype = str(row.get("type", "")).strip()
            if not good_id(iid) or iid in seen:
                raise Problem(f"{prefix}物品编号 '{iid}' 非法或重复。")
            seen.add(iid)
            if not good_name(iname):
                raise Problem(f"{prefix}物品名称无效。")
            if itype not in (*types.keys(), "scanned"):
                raise Problem(f"{prefix}未知的设备/家具类型 '{itype}'。")
            try:
                x = float(row["x"])
                y = float(row["y"])
                tspec = types.get(itype, {})
                w = float(row["w"]) if str(row.get("w", "")).strip() else float(tspec.get("w", 40))
                h = float(row["h"]) if str(row.get("h", "")).strip() else float(tspec.get("h", 40))
                ang = float(row["angle"]) if str(row.get("angle", "")).strip() else 0.0
            except (KeyError, ValueError, TypeError):
                raise Problem(f"{prefix}坐标或尺寸数值格式错误。")

            if not point_in_poly(x, y, outline):
                raise Problem(f"{prefix}坐标 ({x}, {y}) 越出当前户型外边界。")

            obj = {"id": iid, "name": iname, "type": itype, "x": x, "y": y, "w": w, "h": h, "angle": ang}
            if itype in types:
                self.device_layer.ensure_defaults(obj, types[itype])
                caps = types[itype].get("caps", {})
                if str(row.get("power", "")).strip().lower() in ("true", "1", "false", "0") and "power" in caps:
                    obj["power"] = str(row["power"]).strip().lower() in ("true", "1")
                for num_k in ("level", "target", "position"):
                    if num_k in caps and str(row.get(num_k, "")).strip() != "":
                        try:
                            nv = float(row[num_k])
                            nv = int(nv) if nv.is_integer() else nv
                        except ValueError:
                            raise Problem(f"{prefix}字段 {num_k} 不是有效数字。")
                        if not self.device_layer.valid_cap_value(caps[num_k], nv):
                            raise Problem(f"{prefix}字段 {num_k}={nv} 超出允许值域 {caps[num_k]}。")
                        obj[num_k] = nv
                if "mode" in caps and str(row.get("mode", "")).strip():
                    mv = str(row["mode"]).strip()
                    if not self.device_layer.valid_cap_value(caps["mode"], mv):
                        raise Problem(f"{prefix}不支持的运行模式 '{mv}'。")
                    obj["mode"] = mv
            rows_to_apply.append(obj)

        # Merge / upsert validated batch atomically
        by_id = {o["id"]: o for o in m["plan"]["items"]}
        for new_obj in rows_to_apply:
            by_id[new_obj["id"]] = new_obj
        m["plan"]["items"] = list(by_id.values())
        m["rev"] += 1
        self.repo.record_event(key, None, "ok", f"批量原子导入成功：共更新/新增 {len(rows_to_apply)} 件家居资产", source="import")
        self.repo.write_model(key, m)
        return len(rows_to_apply)

    @staticmethod
    def _find_item(m: dict, device_id: object) -> dict:
        if not isinstance(device_id, str):
            raise Problem("设备标识无效。")
        item = next((o for o in m["plan"]["items"] if o["id"] == device_id), None)
        if item is None:
            raise Problem(f"找不到设备 '{device_id}'。", 404)
        return item
