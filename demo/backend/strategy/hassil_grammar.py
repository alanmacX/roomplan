"""Declarative Chinese Intent-Slot Grammar Engine inspired by OHF-Voice/HassIL.

Implements HassIL-style expansion rules (`<rule>`), alternatives (`(a|b)`),
optionals (`[opt]`), dynamic entity slots (`{area}`, `{name}`, `{domain}`),
and `ignore_whitespace` Chinese template compilation for zero-latency (<5ms)
deterministic smart-home intent recognition and multi-turn slot completion.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

# Expansion rules modeled after `OHF-Voice/intents` (`sentences/zh-cn/_common.yaml`)
EXPANSION_RULES: dict[str, str] = {
    "polite_pre": r"(?:请|麻烦|你|帮我|给我|能不能|可不可以|劳驾|快去|赶紧|现在|立刻|马上|顺手)*",
    "polite_post": r"(?:一下|一点点|好吗|行吗|好不好|可以吗|行不行|谢谢|多谢|吧|呀|啊|哦|呗|啦)*",
    "ba": r"(?:把|将|给|让)",
    "turn_on": r"(?:打开|开启|开一下|点亮|亮起|启动|开开|开)",
    "turn_off": r"(?:关闭|关掉|关上|熄灭|灭掉|关一下|关了|停掉|熄灯|关)",
    "open_cover": r"(?:拉开|打开|升起|全开|敞开|开)",
    "close_cover": r"(?:拉上|关上|合上|闭合|遮光|全关|关掉|关)",
    "set_verb": r"(?:调到|调至|调成|设为|设成|设置到|设置为|开到|改成|改到|定在)",
    "up_verb": r"(?:调高|升高|上调|加高|增加|高|加|升)",
    "down_verb": r"(?:调低|降低|下调|减小|减少|低|减|降)",
    "brighter": r"(?:调亮|亮一点|再亮些|更亮|亮一些|加亮|提亮)",
    "dimmer": r"(?:调暗|暗一点|再暗些|压暗|更暗|暗一些|柔和一点|柔和些)",
}

POLITE_STRIP_PRE = re.compile(r"^\s*(?:请|麻烦|你|帮我|给我|能不能|可不可以|劳驾|快去|赶紧|现在|立刻|马上|顺手)+\s*")
POLITE_STRIP_POST = re.compile(r"\s*(?:好吗|行吗|好不好|可以吗|行不行|谢谢|多谢|吧|呀|啊|哦|呗|啦)+[。！!？?\s]*$")

# Interrogative A-not-A & sentence-final particles to prevent false imperative matches
INTERROGATIVE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"(开没开|关没关|亮没亮|拉没拉|亮不亮|暗不暗|热不热|冷不冷|闷不闷|潮不潮|高不高|低不低|有没有开|是不是开|是不是关)"),
    re.compile(r"(开了吗|关了吗|开着吗|关着吗|亮着吗|拉上了吗|拉开了吗|开了没|关了没|开着没|关着没|没关吗)[？?。！!]*$"),
    re.compile(r"(多少度|几度|多亮|什么温度|湿度多少|温度多少|照度多少|哪些.+开着|什么.+开着|还有.+没关|什么模式|哪个模式|状态怎么样)"),
)

NEGATION_GUARD_RE = re.compile(
    r"(?:千万)?(?:别|不要|不用|勿|先别|无需|不必)\s*(?:帮我|给我|去)?\s*(?:(?:把|将|给)[^，,。；;]{1,12}?)?\s*(?:开|打开|开启|关|关闭|关掉|熄|调|动|拉|合|改|设)"
)


@dataclass(frozen=True)
class CompiledTemplate:
    intent: str
    regex: re.Pattern
    meta: dict


def compile_hassil_pattern(template: str) -> re.Pattern:
    """Compile a compact HassIL-style Chinese template into an anchored regex (`ignore_whitespace`).

    Supported syntax:
      - `<rule>`   -> expands from `EXPANSION_RULES`
      - `[text]`   -> optional non-capturing group `(?:text)?`
      - `(a|b|c)`  -> non-capturing alternation `(?:a|b|c)`
      - `{slot}`   -> named slot group `(?P<slot>.+?)`
    """
    s = template.replace(" ", "")
    # 1. Replace `{slot}` placeholders temporarily
    slots: list[str] = []

    def _stash_slot(m: re.Match) -> str:
        idx = len(slots)
        slots.append(m.group(1))
        return f"__SLOT_{idx}__"

    s = re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", _stash_slot, s)

    # 2. Expand `<rule>` references
    for k, expr in EXPANSION_RULES.items():
        s = s.replace(f"<{k}>", f"__RULE_{k}__")

    # 3. Convert `[...]` optionals and `(...)` alternations safely
    out = []
    for ch in s:
        if ch == "[":
            out.append("(?:")
        elif ch == "]":
            out.append(")?")
        elif ch == "(":
            out.append("(?:")
        elif ch == ")":
            out.append(")")
        elif ch in ".+?*^$\\":
            out.append("\\" + ch)
        else:
            out.append(ch)
    compiled = "".join(out)

    for k, expr in EXPANSION_RULES.items():
        compiled = compiled.replace(f"__RULE_{k}__", expr)
    for idx, slot_name in enumerate(slots):
        if slot_name in ("value", "delta"):
            compiled = compiled.replace(f"__SLOT_{idx}__", rf"(?P<{slot_name}>\d+(?:\.\d+)?)")
        else:
            compiled = compiled.replace(f"__SLOT_{idx}__", rf"(?P<{slot_name}>.+?)")

    full = rf"^\s*{EXPANSION_RULES['polite_pre']}{compiled}{EXPANSION_RULES['polite_post']}[。！!？?\s]*$"
    return re.compile(full)


# Core HassIL Chinese Smart Home Sentence Templates
HASSIL_SENTENCES: list[tuple[str, str, dict]] = [
    # Turn On / Off (BA, VO, Topic-Comment)
    ("HassTurnOff", "<ba>{target}<turn_off>", {"op": "off"}),
    ("HassTurnOff", "<turn_off>{target}", {"op": "off"}),
    ("HassTurnOff", "{target}<turn_off>", {"op": "off"}),
    ("HassTurnOn", "<ba>{target}<turn_on>", {"op": "on"}),
    ("HassTurnOn", "<turn_on>{target}", {"op": "on"}),
    ("HassTurnOn", "{target}<turn_on>", {"op": "on"}),

    # Set Numeric Value (Temperature / Brightness / Curtain Position)
    ("HassSetValue", "[<ba>]{target}[的][亮度|温度|开合度|目标温度|目标湿度]<set_verb>{value}[%|度|℃]", {"op": "set"}),
    ("HassSetValue", "{target}[亮度|温度|开合度]{value}(%|度|℃)", {"op": "set"}),

    # Relative Up / Down with Optional Delta
    ("HassRelative", "[<ba>][{target}]<up_verb>{delta}[%|度|℃]", {"op": "up"}),
    ("HassRelative", "[<ba>][{target}]<down_verb>{delta}[%|度|℃]", {"op": "down"}),
    ("HassLightAdjust", "[<ba>][{target}]<brighter>", {"op": "brighter"}),
    ("HassLightAdjust", "[<ba>][{target}]<dimmer>", {"op": "dimmer"}),

    # Cover Open / Close
    ("HassCover", "[<ba>]{target}<open_cover>", {"op": "open_cover"}),
    ("HassCover", "[<ba>]{target}<close_cover>", {"op": "close_cover"}),
]

COMPILED_HASSIL: list[CompiledTemplate] = [
    CompiledTemplate(intent=intent, regex=compile_hassil_pattern(pat), meta=meta)
    for intent, pat, meta in HASSIL_SENTENCES
]


def strip_polite_wrappers(text: str) -> str:
    """Strip colloquial polite prefixes/suffixes while keeping core imperative semantics intact."""
    s = POLITE_STRIP_PRE.sub("", text.strip())
    s = POLITE_STRIP_POST.sub("", s).strip("。！!？? ")
    return s or text.strip()


def is_interrogative_sentence(text: str) -> bool:
    """Return True if sentence uses Chinese interrogative syntax rather than an imperative command."""
    t = text.strip()
    if any(p.search(t) for p in INTERROGATIVE_PATTERNS):
        if not any(w in t for w in ("调到", "设为", "帮我把", "请把", "麻烦把")):
            return True
    return False


def has_negation_guard(text: str) -> bool:
    """Return True if user explicitly asks NOT to perform an action ('别关灯', '不要开空调')."""
    return bool(NEGATION_GUARD_RE.search(text.strip()))


def match_hassil_templates(normalized_text: str) -> dict | None:
    """Match normalized Chinese sentence against compiled HassIL templates."""
    for tpl in COMPILED_HASSIL:
        m = tpl.regex.match(normalized_text)
        if m:
            slots = {k: v.strip() for k, v in m.groupdict().items() if v is not None}
            return {"intent": tpl.intent, "slots": slots, **tpl.meta}
    return None
