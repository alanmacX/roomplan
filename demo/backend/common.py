"""Common domain exceptions and pure geometry utilities."""
from __future__ import annotations

import json
import math
import re

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
SEASONS = ("春", "夏", "秋", "冬")
ZONE_TYPES = ("public", "rest", "work", "guest")


class Problem(Exception):
    def __init__(self, message: str, status: int = 400):
        self.status = status
        super().__init__(message)


def good_id(v: object) -> bool:
    return isinstance(v, str) and bool(ID_RE.fullmatch(v))


def good_name(v: object) -> bool:
    return isinstance(v, str) and 1 <= len(v.strip()) <= 70


def is_num(v: object, low: float, high: float) -> bool:
    return type(v) in (int, float) and math.isfinite(v) and low <= v <= high


def is_point(p: object) -> bool:
    return isinstance(p, list) and len(p) == 2 and all(is_num(x, -20000, 20000) for x in p)


def is_polygon(p: object) -> bool:
    return isinstance(p, list) and 3 <= len(p) <= 120 and all(is_point(x) for x in p)


def packed(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def point_in_poly(x: float, y: float, poly: list[list[float]]) -> bool:
    odd = False
    for (a, b), (c, d) in zip(poly, poly[1:] + poly[:1]):
        if ((b > y) != (d > y)) and x < (c - a) * (y - b) / (d - b) + a:
            odd = not odd
    return odd


def distance_to_edges(x: float, y: float, poly: list[list[float]]) -> float:
    distances = []
    for (a, b), (c, d) in zip(poly, poly[1:] + poly[:1]):
        dx, dy = c - a, d - b
        denom = dx * dx + dy * dy
        t = max(0.0, min(1.0, ((x - a) * dx + (y - b) * dy) / denom)) if denom else 0.0
        distances.append(math.hypot(x - a - t * dx, y - b - t * dy))
    return min(distances) if distances else 0.0


def segment_distance_to_box(a: list[float], b: list[float], cx: float, cy: float) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    denom = dx * dx + dy * dy
    t = max(0.0, min(1.0, ((cx - a[0]) * dx + (cy - a[1]) * dy) / denom)) if denom else 0.0
    return math.hypot(cx - (a[0] + t * dx), cy - (a[1] + t * dy))


def room_for_point(plan: dict, x: float, y: float) -> dict | None:
    for r in plan.get("rooms", []):
        if point_in_poly(x, y, r["p"]):
            return r
    return None


def room_for_item(plan: dict, item: dict) -> dict | None:
    return room_for_point(plan, item["x"], item["y"])
