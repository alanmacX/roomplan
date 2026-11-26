"""Layer 5: Data Layer (Repository interfaces & SQLite WAL implementation).

Strictly handles persistence, transactions, schema initialization, and queries.
Contains ZERO business strategy or device protocol rules.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import threading
import time
from datetime import datetime
from typing import Protocol

from backend.common import Problem, packed


class IHomeRepository(Protocol):
    def list_plan_keys(self) -> list[str]: ...
    def read_model(self, key: str) -> dict: ...
    def write_model(self, key: str, model: dict) -> None: ...
    def read_types(self) -> dict[str, dict]: ...
    def save_type(self, code: str, spec: dict) -> None: ...
    def read_scenes(self, key: str) -> dict[str, dict]: ...
    def save_scene(self, key: str, scene_id: str, spec: dict) -> None: ...
    def record_event(self, key: str, device_id: str | None, status: str,
                     message: str, state: dict | None = None, source: str = "system") -> None: ...
    def query_events(self, key: str, device_id: str | None = None, limit: int = 35) -> list[dict]: ...


def _build_multigen_apartment() -> dict:
    """120m² Multi-generational 3-bedroom spatial zone floorplan (upgraded from narrow two-room demo)."""
    def rect(x: float, y: float, w: float, h: float) -> list[list[float]]:
        return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]

    def seg(a: list[float], b: list[float]) -> dict:
        return {"a": a, "b": b}

    return {
        "key": "apartment",
        "title": "多代际同住 · 三室两厅分域户型 (120㎡)",
        "outline": rect(0, 0, 1180, 720),
        "rooms": [
            {"id": "entry", "name": "玄关走廊", "zone": "public", "sleep": False, "p": rect(0, 0, 250, 290), "tag": [125, 72]},
            {"id": "living", "name": "客厅餐厅", "zone": "public", "sleep": False, "p": rect(250, 0, 480, 720), "tag": [490, 98]},
            {"id": "elder", "name": "长辈次卧", "zone": "rest", "sleep": True, "p": rect(0, 290, 250, 430), "tag": [125, 340]},
            {"id": "master", "name": "主卧", "zone": "rest", "sleep": True, "p": rect(730, 0, 450, 340), "tag": [955, 94]},
            {"id": "study", "name": "书房", "zone": "work", "sleep": False, "p": rect(730, 340, 450, 195), "tag": [955, 378]},
            {"id": "bath", "name": "公共卫浴", "zone": "public", "sleep": False, "p": rect(730, 535, 450, 185), "tag": [955, 578]},
        ],
        "walls": [
            seg([0, 0], [1180, 0]), seg([1180, 0], [1180, 720]),
            seg([1180, 720], [0, 720]), seg([0, 720], [0, 190]), seg([0, 90], [0, 0]),
            # Entry / Elder divider
            seg([0, 290], [250, 290]),
            # Left column to Living wall (with doors to entry & elder)
            seg([250, 0], [250, 130]), seg([250, 220], [250, 350]), seg([250, 440], [250, 720]),
            # Right column to Living wall (with doors to master, study, bath)
            seg([730, 0], [730, 190]), seg([730, 280], [730, 390]),
            seg([730, 475], [730, 580]), seg([730, 665], [730, 720]),
            # Horizontal dividers on right
            seg([730, 340], [1180, 340]),
            seg([730, 535], [1180, 535]),
        ],
        "doors": [
            seg([0, 90], [0, 190]),
            seg([250, 130], [250, 220]),
            seg([250, 350], [250, 440]),
            seg([730, 190], [730, 280]),
            seg([730, 390], [730, 475]),
            seg([730, 580], [730, 665]),
        ],
        "windows": [
            seg([340, 0], [640, 0]),
            seg([840, 0], [1090, 0]),
            seg([40, 720], [200, 720]),
            seg([1180, 380], [1180, 495]),
        ],
        "items": [
            {"id": "entry-lamp", "type": "lamp", "name": "玄关伴行灯", "x": 122, "y": 152, "w": 36, "h": 36, "angle": 0, "power": False, "level": 40, "color_temp": "暖白"},
            {"id": "living-lamp", "type": "lamp", "name": "客厅主灯", "x": 495, "y": 215, "w": 42, "h": 42, "angle": 0, "power": True, "level": 80, "color_temp": "自然光"},
            {"id": "living-ac", "type": "ac", "name": "客厅空调", "x": 490, "y": 42, "w": 76, "h": 28, "angle": 0, "power": True, "mode": "制冷", "target": 26, "fan_speed": "自动"},
            {"id": "living-curtain", "type": "curtain", "name": "客厅阳台窗帘", "x": 490, "y": 14, "w": 150, "h": 18, "angle": 0, "position": 70},
            {"id": "elder-lamp", "type": "lamp", "name": "长辈房柔光灯", "x": 115, "y": 450, "w": 36, "h": 36, "angle": 0, "power": False, "level": 35, "color_temp": "暖白"},
            {"id": "elder-ac", "type": "ac", "name": "长辈房空调", "x": 120, "y": 692, "w": 72, "h": 28, "angle": 0, "power": False, "mode": "制冷", "target": 27, "fan_speed": "静音"},
            {"id": "master-lamp", "type": "lamp", "name": "主卧吸顶灯", "x": 960, "y": 170, "w": 38, "h": 38, "angle": 0, "power": False, "level": 60, "color_temp": "暖白"},
            {"id": "master-ac", "type": "ac", "name": "主卧空调", "x": 965, "y": 38, "w": 72, "h": 28, "angle": 0, "power": False, "mode": "制冷", "target": 26, "fan_speed": "静音"},
            {"id": "study-lamp", "type": "lamp", "name": "书房护眼灯", "x": 945, "y": 435, "w": 36, "h": 36, "angle": 0, "power": False, "level": 75, "color_temp": "冷白"},
            {"id": "study-ac", "type": "ac", "name": "书房空调", "x": 965, "y": 362, "w": 70, "h": 26, "angle": 0, "power": True, "mode": "制冷", "target": 22, "fan_speed": "静音"},
            {"id": "bath-lamp", "type": "switch", "name": "公卫镜前灯", "x": 965, "y": 635, "w": 34, "h": 34, "angle": 0, "power": False},
            {"id": "living-sensor", "type": "sensor", "name": "客厅四维传感器", "x": 310, "y": 110, "w": 28, "h": 28, "angle": 0},
            {"id": "study-sensor", "type": "sensor", "name": "书房环境传感器", "x": 815, "y": 495, "w": 28, "h": 28, "angle": 0},
            {"id": "sofa-main", "type": "sofa", "name": "转角沙发", "x": 490, "y": 355, "w": 185, "h": 68, "angle": 0},
            {"id": "dining-tbl", "type": "table", "name": "六人餐桌", "x": 490, "y": 565, "w": 135, "h": 76, "angle": 0},
            {"id": "elder-bed", "type": "bed", "name": "长辈双人床", "x": 122, "y": 565, "w": 135, "h": 165, "angle": 0},
            {"id": "master-bed", "type": "bed", "name": "主卧大床", "x": 1030, "y": 175, "w": 150, "h": 185, "angle": 0},
            {"id": "study-desk", "type": "desk", "name": "升降书桌", "x": 1035, "y": 438, "w": 120, "h": 56, "angle": 0},
        ],
    }


def _enrich_house_scan(house: dict) -> dict:
    """Add spatial zones and representative smart devices to the 11-room Apple RoomPlan scan."""
    zone_map = {
        "living": ("public", False),
        "dining": ("public", False),
        "kitchen": ("public", False),
        "hall": ("public", False),
        "entry": ("public", False),
        "bath": ("public", False),
        "bath2": ("public", False),
        "bed": ("rest", True),      # 主卧
        "bed2": ("rest", True),     # 长辈次卧
        "bed3": ("work", False),    # 书房/工作间
        "bed4": ("guest", False),   # 客房
    }
    name_map = {
        "living": "客厅", "dining": "餐厅", "kitchen": "厨房",
        "hall": "走廊一", "entry": "玄关走廊", "bed": "主卧",
        "bed2": "长辈次卧", "bed3": "书房", "bed4": "客房",
        "bath": "公共卫浴", "bath2": "次卫",
    }
    for r in house.get("rooms", []):
        z, slp = zone_map.get(r["id"], ("public", False))
        r["zone"] = z
        r["sleep"] = slp
        if r["id"] in name_map:
            r["name"] = name_map[r["id"]]

    existing_ids = {o["id"] for o in house.get("items", [])}
    has_any_lamp = any(o.get("type") in ("lamp", "switch") for o in house.get("items", []))
    rename_lamps = {"卧室三灯": "书房灯", "卧室四灯": "客房灯", "过厅灯": "玄关灯", "卫生间一灯": "主卫灯", "卫生间二灯": "次卫灯"}
    lamp_seed_levels = {"living-lamp": 85, "bed-lamp": 45, "hall-lamp": 35, "entry-lamp": 40, "bed3-lamp": 75}
    for o in house.get("items", []):
        if o.get("name") in rename_lamps:
            o["name"] = rename_lamps[o["name"]]
        if o.get("type") == "lamp":
            o.setdefault("color_temp", "暖白")
            if o.get("id") in lamp_seed_levels:
                o["level"] = lamp_seed_levels[o["id"]]
            else:
                o.setdefault("level", 65)
        elif o.get("type") == "ac":
            o.setdefault("fan_speed", "自动")
            o.setdefault("mode", "制冷")
            o.setdefault("target", 26)

    from backend.common import room_for_item
    ac_Labels = {"living": "客厅空调", "bed": "主卧空调", "bed2": "次卧空调", "bed3": "书房空调"}
    for r in house.get("rooms", []):
        rid = r["id"]
        tx, ty = r["tag"]
        lamp_id = f"scan-lamp-{rid}"
        if not has_any_lamp and lamp_id not in existing_ids:
            house["items"].append({
                "id": lamp_id, "type": "lamp", "name": f"{r['name']}主灯",
                "x": round(tx, 2), "y": round(ty + 24, 2), "w": 34, "h": 34, "angle": 0,
                "power": rid == "living", "level": 85 if rid == "living" else 50, "color_temp": "自然光"
            })
        if rid in ac_Labels and f"scan-ac-{rid}" not in existing_ids:
            room_has_ac = any(
                o.get("type") == "ac" and (room_for_item(house, o) or {}).get("id") == rid
                for o in house.get("items", [])
            )
            if not room_has_ac:
                is_study_cool = (rid == "bed3")
                house["items"].append({
                    "id": f"scan-ac-{rid}", "type": "ac", "name": ac_Labels[rid],
                    "x": round(tx + 30, 2), "y": round(ty - 14, 2), "w": 68, "h": 26, "angle": 0,
                    "power": is_study_cool, "mode": "制冷",
                    "target": 21 if is_study_cool else 26,
                    "fan_speed": "静音" if is_study_cool else "自动",
                })
    house["title"] = "Apple RoomPlan · 11 房间同源扫描户型"
    return house


DEFAULT_SCENES = {
    "home": {
        "id": "home",
        "name": "回家模式",
        "builtin": True,
        "description": "亮起玄关与客厅照明、拉开公共区窗帘，并按季节与室内外温湿度动态计算舒适空调温度（自动跳过睡眠免打扰房间）。",
        "entry_light_level": 80,
        "curtain_position": 85,
        "enable_climate": True,
    },
    "away": {
        "id": "away",
        "name": "离家模式",
        "builtin": True,
        "description": "一键关闭全屋非安防照明与空调设备，闭合遮阳窗帘，清空临时接管计时以实现节能安防。",
        "curtain_position": 0,
        "enable_climate": False,
    },
    "sleep": {
        "id": "sleep",
        "name": "分域睡眠",
        "builtin": True,
        "description": "私密睡眠域关灯并启用睡眠免打扰锁（保留房内手动控制）；公共通行域启用 25% 柔和伴行感应与无人延时熄灯；空调执行夜间睡眠温区微调。",
        "corridor_light_level": 25,
        "enable_climate": True,
    },
}


class SQLiteRepository:
    def __init__(self, db_path: Path, seed_file: Path, house_file: Path, default_types: dict[str, dict]):
        self.db_path = db_path
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()

        seed = json.loads(seed_file.read_text(encoding="utf-8"))
        house_raw = json.loads(
            house_file.read_text(encoding="utf-8")
            .removeprefix("window.ROOMPLAN_PROJECTED = ")
            .strip()
            .removesuffix(";")
        )["house"]

        self.mount_origin: list[float] = seed["mountOrigin"]
        apple_plan = seed["apple"]
        for r in apple_plan.get("rooms", []):
            r.setdefault("zone", "public")
            r.setdefault("sleep", False)
        for o in apple_plan.get("items", []):
            if o.get("type") == "lamp":
                o.setdefault("color_temp", "暖白")

        custom_plan = seed["custom"]
        custom_plan["title"] = "空白自建户型（支持画房间/画墙/导JSON）"

        initial_plans = {
            "apartment": _build_multigen_apartment(),
            "house": _enrich_house_scan(house_raw),
            "apple": apple_plan,
            "custom": custom_plan,
        }
        self._plan_keys = list(initial_plans.keys())

        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS plans(
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS device_types(
                code TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scenes(
                plan TEXT NOT NULL,
                scene_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (plan, scene_id)
            );
            CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan TEXT NOT NULL,
                device TEXT,
                ts REAL NOT NULL,
                status TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'system',
                message TEXT NOT NULL,
                state TEXT
            );
            CREATE INDEX IF NOT EXISTS event_lookup ON events(plan, device, id);
        """)

        # Ensure 'source' column exists if upgrading an older demo.sqlite3
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(events)")}
        if "source" not in cols:
            self.db.execute("ALTER TABLE events ADD COLUMN source TEXT NOT NULL DEFAULT 'system'")

        now = time.time()
        with self.db:
            for code, spec in default_types.items():
                self.db.execute("INSERT OR IGNORE INTO device_types VALUES (?, ?)", (code, packed(spec)))

            for key, plan in initial_plans.items():
                row = self.db.execute("SELECT payload FROM plans WHERE id=?", (key,)).fetchone()
                if row is None:
                    model = self._default_model(plan, now)
                    self.db.execute("INSERT INTO plans VALUES (?, ?)", (key, packed(model)))
                else:
                    # Migrate legacy apartment or missing fields non-destructively
                    existing = json.loads(row[0])
                    changed = False
                    if key == "apartment" and existing.get("plan", {}).get("title") == "双职工家庭 · 两居室":
                        existing = self._default_model(plan, now)
                        changed = True
                    elif key == "house" and not any(r.get("zone") for r in existing.get("plan", {}).get("rooms", [])):
                        existing["plan"] = plan
                        changed = True
                    else:
                        changed = self._ensure_model_fields(existing, now)
                    if changed:
                        self.db.execute("UPDATE plans SET payload=? WHERE id=?", (packed(existing), key))

                for sid, sdata in DEFAULT_SCENES.items():
                    self.db.execute(
                        "INSERT OR IGNORE INTO scenes VALUES (?, ?, ?)",
                        (key, sid, packed(sdata))
                    )

    @staticmethod
    def _default_model(plan: dict, now: float) -> dict:
        return {
            "plan": plan,
            "rev": 1,
            "seq": 1,
            "mode": "normal",
            "occupied": {},
            "overrides": {},
            "due": {},
            "climate": {
                "season": "夏",
                "indoor": 32.0,
                "outdoor": 34.0,
                "humidity": 75,
                "lux": 95,
                "updated_ts": now,
                "ttl": 300,
                "stale_sim": False,
            },
            "delay": 6,
            "override_ttl": 15,
            "last_explanation": "系统就绪：当前处于日常手动模式，五级冲突仲裁引擎在线。",
        }

    @staticmethod
    def _ensure_model_fields(m: dict, now: float) -> bool:
        changed = False
        clim = m.setdefault("climate", {})
        for k, v in (("season", "夏"), ("indoor", 31.0), ("outdoor", 33.0),
                     ("humidity", 72), ("lux", 110), ("updated_ts", now),
                     ("ttl", 300), ("stale_sim", False)):
            if k not in clim:
                clim[k] = v
                changed = True
        for r in m.get("plan", {}).get("rooms", []):
            if "zone" not in r:
                r["zone"] = "rest" if r.get("sleep") else "public"
                changed = True
        for k, v in (("override_ttl", 15), ("delay", 6),
                     ("last_explanation", "系统就绪：五级控制权冲突仲裁在线。")):
            if k not in m:
                m[k] = v
                changed = True
        return changed

    def list_plan_keys(self) -> list[str]:
        return list(self._plan_keys)

    def read_model(self, key: str) -> dict:
        row = self.db.execute("SELECT payload FROM plans WHERE id=?", (key,)).fetchone()
        if not row:
            raise Problem("找不到请求的户型方案。", 404)
        return json.loads(row[0])

    def write_model(self, key: str, model: dict) -> None:
        model["seq"] = int(model.get("seq", 1)) + 1
        self.db.execute("UPDATE plans SET payload=? WHERE id=?", (packed(model), key))

    def read_types(self) -> dict[str, dict]:
        rows = self.db.execute("SELECT code, payload FROM device_types ORDER BY rowid ASC").fetchall()
        return {r["code"]: json.loads(r["payload"]) for r in rows}

    def save_type(self, code: str, spec: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO device_types VALUES (?, ?)", (code, packed(spec)))

    def read_scenes(self, key: str) -> dict[str, dict]:
        rows = self.db.execute("SELECT scene_id, payload FROM scenes WHERE plan=? ORDER BY rowid ASC", (key,)).fetchall()
        return {r["scene_id"]: json.loads(r["payload"]) for r in rows}

    def save_scene(self, key: str, scene_id: str, spec: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO scenes VALUES (?, ?, ?)", (key, scene_id, packed(spec)))

    def record_event(self, key: str, device_id: str | None, status: str,
                     message: str, state: dict | None = None, source: str = "system") -> None:
        state_json = packed(state) if state is not None else None
        self.db.execute(
            "INSERT INTO events(plan, device, ts, status, source, message, state) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (key, device_id, time.time(), status, source, message, state_json),
        )

    def query_events(self, key: str, device_id: str | None = None, limit: int = 35) -> list[dict]:
        if device_id:
            rows = self.db.execute(
                "SELECT id, ts, device, status, source, message, state FROM events WHERE plan=? AND device=? ORDER BY id DESC LIMIT ?",
                (key, device_id, limit),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT id, ts, device, status, source, message, state FROM events WHERE plan=? ORDER BY id DESC LIMIT ?",
                (key, limit),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "ts": round(r["ts"], 2),
                "time": datetime.fromtimestamp(r["ts"]).strftime("%H:%M:%S"),
                "device": r["device"],
                "status": r["status"],
                "source": r["source"],
                "message": r["message"],
                "state": json.loads(r["state"]) if r["state"] else None,
            }
            for r in rows
        ]
