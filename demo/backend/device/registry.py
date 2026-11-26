"""Layer 4: Device Layer (Matter-inspired Type Registry & Software Simulator).

Describes device capabilities, metadata, default geometry, and executes atomic
simulated commands without any awareness of rooms, users, or scenes.
"""
from __future__ import annotations

import time
from backend.common import Problem, good_id, good_name, is_num
from backend.data.repository import IHomeRepository


DEFAULT_DEVICE_TYPES: dict[str, dict] = {
    "lamp": {
        "name": "可调光吸顶灯",
        "matter": "Dimmable Light 0x0101",
        "category": "lighting",
        "mark": "☼",
        "w": 37,
        "h": 37,
        "height3d": 12,
        "color": "#f3e5b5",
        "lumens_gain": 220,
        "svg": "<circle cx='16' cy='16' r='10' fill='#fde68a' stroke='#475569' stroke-width='1.6'/><path d='M16 2v4M16 26v4M2 16h4M26 16h4' stroke='#475569' stroke-width='1.5'/>",
        "caps": {
            "power": [True, False],
            "level": [1, 100],
            "color_temp": ["暖白", "自然光", "冷白"],
        },
        "cap_meta": {
            "power": {"label": "电源开关", "kind": "bool", "default": False},
            "level": {"label": "调光亮度", "kind": "range", "min": 1, "max": 100, "unit": "%", "default": 65, "staged_when_off": True},
            "color_temp": {"label": "光色色温", "kind": "enum", "options": ["暖白", "自然光", "冷白"], "default": "暖白", "staged_when_off": True},
        },
    },
    "ac": {
        "name": "多模式房间空调",
        "matter": "Room Air Conditioner 0x0072",
        "category": "hvac",
        "mark": "≈",
        "w": 74,
        "h": 28,
        "height3d": 28,
        "color": "#bfd4de",
        "lumens_gain": 0,
        "svg": "<rect x='3' y='7' width='26' height='14' rx='3' fill='#dbeafe' stroke='#475569' stroke-width='1.6'/><path d='M8 25c2-2 4 2 6 0M17 25c2-2 4 2 6 0' stroke='#2563eb' stroke-width='1.4' fill='none'/>",
        "caps": {
            "power": [True, False],
            "mode": ["制冷", "制热", "除湿", "送风"],
            "target": [16, 30],
            "fan_speed": ["静音", "自动", "强风"],
        },
        "cap_meta": {
            "power": {"label": "空调电源", "kind": "bool", "default": False},
            "mode": {"label": "运行模式", "kind": "enum", "options": ["制冷", "制热", "除湿", "送风"], "default": "制冷"},
            "target": {"label": "目标温度", "kind": "range", "min": 16, "max": 30, "unit": "°C", "step": 0.5, "default": 26, "readonly_when": {"mode": "送风"}},
            "fan_speed": {"label": "风速档位", "kind": "enum", "options": ["静音", "自动", "强风"], "default": "自动"},
        },
    },
    "curtain": {
        "name": "电动遮阳窗帘",
        "matter": "Window Covering 0x0202",
        "category": "shade",
        "mark": "▥",
        "w": 110,
        "h": 20,
        "height3d": 210,
        "color": "#b4ccc9",
        "lumens_gain": 0,
        "svg": "<rect x='4' y='5' width='24' height='22' rx='2' fill='#ccfbf1' stroke='#475569' stroke-width='1.6'/><path d='M10 5v22M16 5v22M22 5v22' stroke='#0f766e' stroke-width='1.3'/>",
        "caps": {
            "position": [0, 100],
        },
        "cap_meta": {
            "position": {"label": "窗帘开合度", "kind": "range", "min": 0, "max": 100, "unit": "%", "default": 50},
        },
    },
    "switch": {
        "name": "墙壁开关灯",
        "matter": "On/Off Light 0x0100",
        "category": "lighting",
        "mark": "◉",
        "w": 34,
        "h": 34,
        "height3d": 10,
        "color": "#f0dfbb",
        "lumens_gain": 150,
        "svg": "<rect x='6' y='6' width='20' height='20' rx='5' fill='#fef3c7' stroke='#475569' stroke-width='1.6'/><circle cx='16' cy='16' r='4' fill='#d97706'/>",
        "caps": {
            "power": [True, False],
        },
        "cap_meta": {
            "power": {"label": "开关状态", "kind": "bool", "default": False},
        },
    },
    "sensor": {
        "name": "四维环境与存在传感器",
        "matter": "Occupancy & Climate 0x0107",
        "category": "sensor",
        "mark": "◎",
        "w": 28,
        "h": 28,
        "height3d": 12,
        "color": "#bdd4b8",
        "lumens_gain": 0,
        "svg": "<circle cx='16' cy='16' r='9' fill='#dcfce7' stroke='#15803d' stroke-width='1.6'/><circle cx='16' cy='16' r='3.5' fill='#15803d'/>",
        "caps": {},
        "cap_meta": {},
    },
    "sofa": {
        "name": "布艺沙发",
        "matter": "Furniture",
        "category": "furniture",
        "mark": "▰",
        "w": 150,
        "h": 65,
        "height3d": 78,
        "color": "#cfbaa6",
        "lumens_gain": 0,
        "svg": "<rect x='4' y='10' width='24' height='13' rx='3' fill='#e7e5e4' stroke='#57534e' stroke-width='1.6'/>",
        "caps": {},
        "cap_meta": {},
    },
    "table": {
        "name": "原木餐桌",
        "matter": "Furniture",
        "category": "furniture",
        "mark": "▱",
        "w": 115,
        "h": 68,
        "height3d": 75,
        "color": "#d6be9c",
        "lumens_gain": 0,
        "svg": "<rect x='5' y='8' width='22' height='16' rx='2' fill='#fef3c7' stroke='#78350f' stroke-width='1.5'/>",
        "caps": {},
        "cap_meta": {},
    },
    "bed": {
        "name": "舒适双人床",
        "matter": "Furniture",
        "category": "furniture",
        "mark": "▤",
        "w": 140,
        "h": 175,
        "height3d": 58,
        "color": "#c9c4b8",
        "lumens_gain": 0,
        "svg": "<rect x='5' y='5' width='22' height='22' rx='3' fill='#f1f5f9' stroke='#475569' stroke-width='1.5'/><line x1='5' y1='12' x2='27' y2='12' stroke='#475569' stroke-width='1.3'/>",
        "caps": {},
        "cap_meta": {},
    },
    "desk": {
        "name": "书房工作台",
        "matter": "Furniture",
        "category": "furniture",
        "mark": "▭",
        "w": 120,
        "h": 56,
        "height3d": 74,
        "color": "#cbd5e1",
        "lumens_gain": 0,
        "svg": "<rect x='4' y='9' width='24' height='14' rx='2' fill='#e2e8f0' stroke='#334155' stroke-width='1.5'/>",
        "caps": {},
        "cap_meta": {},
    },
}


class DeviceLayerService:
    """Manages configuration-driven device templates and simulated execution."""

    def __init__(self, repo: IHomeRepository):
        self.repo = repo

    def get_types(self) -> dict[str, dict]:
        return self.repo.read_types()

    def register_type(self, body: dict) -> dict:
        """Dynamic configuration-driven registration of a new device type (F2 OCP)."""
        code = body.get("code")
        name = body.get("name")
        if not good_id(code) or code == "scanned":
            raise Problem("设备类型编码需为 1–80 位字母、数字、下划线或连字符。")
        if not good_name(name):
            raise Problem("请输入有效的设备类型中文名称。")
        w = body.get("w", 46)
        h = body.get("h", 42)
        if not is_num(w, 12, 400) or not is_num(h, 12, 400):
            raise Problem("默认尺寸需在 12–400 厘米之间。")

        raw_caps = body.get("capabilities")
        if not isinstance(raw_caps, list) or len(raw_caps) > 8:
            raise Problem("能力定义列表需为 0–8 项数组。")

        caps: dict[str, list] = {}
        cap_meta: dict[str, dict] = {}
        for c in raw_caps:
            if not isinstance(c, dict) or not good_id(c.get("key")) or not good_name(c.get("label")):
                raise Problem("能力项需包含合法的键名 key 与显示名 label。")
            key = c["key"]
            kind = c.get("kind", "bool")
            if kind == "bool":
                caps[key] = [True, False]
                cap_meta[key] = {"label": c["label"], "kind": "bool", "default": bool(c.get("default", False))}
            elif kind == "range":
                lo, hi = c.get("min", 0), c.get("max", 100)
                if not is_num(lo, -50, 5000) or not is_num(hi, -50, 5000) or lo >= hi:
                    raise Problem(f"能力 {key} 的取值范围下限必须小于上限。")
                caps[key] = [int(lo) if float(lo).is_integer() else lo, int(hi) if float(hi).is_integer() else hi]
                cap_meta[key] = {
                    "label": c["label"], "kind": "range",
                    "min": caps[key][0], "max": caps[key][1],
                    "unit": str(c.get("unit", ""))[:12],
                    "default": c.get("default", caps[key][0]),
                }
            elif kind == "enum":
                opts = c.get("options")
                if not isinstance(opts, list) or not (2 <= len(opts) <= 8) or not all(good_name(x) for x in opts):
                    raise Problem(f"枚举能力 {key} 需提供 2–8 个有效选项。")
                caps[key] = [str(x).strip() for x in opts]
                cap_meta[key] = {
                    "label": c["label"], "kind": "enum",
                    "options": caps[key], "default": caps[key][0],
                }
            else:
                raise Problem(f"不支持的能力数据类型：{kind}")

        spec = {
            "name": name.strip(),
            "matter": str(body.get("matter", "Custom Matter Cluster"))[:48],
            "category": str(body.get("category", "appliance"))[:24],
            "mark": str(body.get("mark", "◈"))[:2] or "◈",
            "w": w,
            "h": h,
            "height3d": body.get("height3d", 55) if is_num(body.get("height3d", 55), 8, 260) else 55,
            "color": str(body.get("color", "#c7d9d8"))[:16],
            "lumens_gain": body.get("lumens_gain", 0) if is_num(body.get("lumens_gain", 0), 0, 800) else 0,
            "svg": "<rect x='5' y='5' width='22' height='22' rx='5' fill='#e0f2fe' stroke='#0369a1' stroke-width='1.6'/><circle cx='16' cy='16' r='4' fill='#0284c7'/>",
            "caps": caps,
            "cap_meta": cap_meta,
        }
        self.repo.save_type(code, spec)
        return {code: spec}

    @staticmethod
    def ensure_defaults(item: dict, type_spec: dict | None) -> None:
        if not type_spec:
            return
        meta_map = type_spec.get("cap_meta", {})
        for k, domain in type_spec.get("caps", {}).items():
            if k not in item:
                if k in meta_map and "default" in meta_map[k]:
                    item[k] = meta_map[k]["default"]
                elif isinstance(domain[0], bool):
                    item[k] = False
                else:
                    item[k] = domain[0]

    @staticmethod
    def valid_cap_value(domain: list, value: object) -> bool:
        if isinstance(domain[0], bool):
            return type(value) is bool
        if type(domain[0]) in (int, float):
            return is_num(value, domain[0], domain[1])
        return isinstance(value, str) and value in domain

    @staticmethod
    def simulate_latency(outcome: str) -> None:
        """Simulate realistic LAN IoT round-trip outside DB lock."""
        if outcome == "timeout":
            time.sleep(0.65)
        else:
            time.sleep(0.06)

    @staticmethod
    def execute_simulated(item: dict, capability: str, value: object, outcome: str = "ok") -> dict:
        """Execute atomic capability write on simulated device instance."""
        now_str = time.strftime("%H:%M:%S")
        desired = {**(item.get("desired") or {}), capability: value}
        item["desired"] = desired

        if outcome == "ok":
            item[capability] = value
            item["online"] = True
            item["last_status"] = "ok"
            item["updated_at"] = now_str
            return {"status": "ok", "staged": bool(capability != "power" and item.get("power") is False)}
        if outcome == "offline":
            item["online"] = False
            item["last_status"] = "offline"
            return {"status": "offline", "staged": False}
        if outcome == "timeout":
            item["last_status"] = "timeout"
            return {"status": "timeout", "staged": False}
        item["last_status"] = "fail"
        return {"status": "fail", "staged": False}
