"""Layer 2B: Strategy Layer — Edge Home Hub Multimodal & Deterministic NLU Engine (E3 + E4).

Architecture:
  - Primary Multimodal Path (Edge Home Hub VLM via `ILlmProvider`):
      Connects to a local/edge OpenAI-compatible VLM (`HOME_VLM_BASE_URL`, e.g. Ollama Qwen2.5-VL)
      for indoor room camera visual understanding and open-ended natural language.
  - Deterministic Intent-Slot & Dialogue State Engine (`IntentSlotEngine`):
      Comprehensive Chinese smart-home grammar engine supporting:
        1) Mandatory slot disambiguation for unqualified bare commands ("关灯", "开灯", "开空调", "调到24度")
           with state-aware candidate ranking + multi-turn `pending_intent` slot completion (user can reply "客厅" or "全部")
        2) Explicit pronoun/continuation anaphora ("把它关了", "再暗一点", "再高两度") & topic-switch ellipsis ("那书房呢")
        3) Multi-room conjunctions ("把客厅和走廊的灯关了"), exclusions ("除了主卧其他灯全关"), & compound clauses ("打开客厅灯，顺便把空调调到25度")
        4) Negation & cancellation guards ("别关客厅灯", "不要开灯", "算了")
        5) Full Chinese numeral/quantifier parsing, comfort scenes ("看书", "观影", "起夜", "有点闷"), & rich Home Q&A
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import urllib.request
from typing import Protocol

from PIL import Image

from backend.common import Problem, room_for_item
from backend.control.service import ControlLayerService
from backend.strategy.engine import StrategyEngine
from backend.strategy.harness import HomeAgentHarness, compute_room_environments, needs_agent_harness
from backend.strategy.hassil_grammar import (
    has_negation_guard,
    is_interrogative_sentence,
    match_hassil_templates,
    strip_polite_wrappers,
)


class ILlmProvider(Protocol):
    def infer_multimodal(self, text: str, plan: dict, climate: dict,
                         camera_b64: str | None, camera_room: str | None,
                         focus: dict) -> dict: ...


# ------------------------------------------------------------------------------
# Rich Synonym Lexicons & Spoken Chinese Numeral Normalization
# ------------------------------------------------------------------------------
ROOM_SYNONYMS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("玄关", "门厅", "门口", "入户", "过厅"), ("entry",)),
    (("走廊", "过道", "通道", "长廊"), ("hall", "entry")),
    (("客厅", "大厅", "起居室", "外间", "前厅"), ("living", "scan-room")),
    (("餐厅", "饭厅", "餐桌"), ("dining",)),
    (("长辈房", "老人房", "长辈次卧", "爸妈房", "父母房", "次卧", "长辈", "老人", "卧室二"), ("elder", "bed2", "room")),
    (("主卧", "大卧", "夫妻房", "主人房", "卧室一"), ("master", "bed")),
    (("书房", "工作室", "阅读室", "学习室", "办公间", "卧室三"), ("study", "bed3")),
    (("客房", "客卧", "卧室四"), ("bed4",)),
    (("主卫", "公共卫浴", "公卫", "大卫", "卫生间", "洗手间", "卫浴", "浴室", "厕所"), ("bath",)),
    (("次卫", "小卫", "客卫"), ("bath2", "bath")),
    (("厨房", "灶台", "料理台"), ("kitchen",)),
]

DEVICE_SYNONYMS: list[tuple[tuple[str, ...], tuple[str, ...], str]] = [
    (("空调", "冷气", "暖气", "温控"), ("ac",), "空调"),
    (("窗帘", "百叶窗", "遮阳帘", "纱帘", "帘子", "卷帘"), ("curtain",), "窗帘"),
    (("灯", "吸顶灯", "主灯", "柔光灯", "护眼灯", "伴行灯", "镜前灯", "台灯", "筒灯", "射灯", "照明", "灯光", "灯泡"), ("lamp", "switch"), "灯"),
    (("插座", "墙壁开关", "电源开关"), ("switch",), "开关"),
]

VISUAL_CUES = ("你看", "看看", "看一眼", "看下", "画面", "镜头", "摄像头", "监控", "照片")
FUZZY_CUES = ("太暗", "有点暗", "看不清", "看书", "刺眼", "太亮", "有点冷", "太冷", "有点热", "太热", "好闷", "有点闷", "潮湿")

DEICTIC_WORDS = ("这里", "这儿", "这间", "这个房间", "当前房间", "本房间", "屋里")
ANAPHORIC_PRONOUNS = ("把它", "将它", "关掉它", "打开它", "把这个", "关了这个", "开了这个", "这盏", "那盏", "这台", "那台")
CONTINUATION_CUES = ("再", "又", "继续", "还要", "多调", "少调")
UNIVERSAL_WORDS = ("全屋", "所有", "全部", "全都", "统统", "家里所有", "全关", "全开", "都关", "都开", "一起关", "一起开")
CANCEL_WORDS = ("算了", "不用了", "取消", "没事了", "不关了", "不开了", "不调了", "不要了")

_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def normalize_chinese_numbers(text: str) -> str:
    """Convert spoken Chinese numerals ('二十五', '六十五', '八成', '一半', '两度') into digits."""
    t = text
    t = t.replace("百分之百", "100%").replace("一百", "100")
    t = t.replace("一半", "50%").replace("半开", "50%").replace("全满", "100%").replace("拉满", "100%")

    # e.g. 八成 -> 80%
    def _cheng(m: re.Match) -> str:
        d = _CN_DIGITS.get(m.group(1), 5)
        return f"{d * 10}%"
    t = re.sub(r"([一二三四五六七八九])成", _cheng, t)

    # e.g. 百分之八十五 -> 85%
    def _pct(m: re.Match) -> str:
        return _parse_cn_int(m.group(1)) + "%"
    t = re.sub(r"百分之([零一二两三四五六七八九十]+)", _pct, t)

    # e.g. 二十五点五 / 二十六 / 十五
    def _parse_cn_int(s: str) -> str:
        if s == "十":
            return "10"
        if "十" in s:
            parts = s.split("十")
            tens = _CN_DIGITS.get(parts[0], 1) if parts[0] else 1
            ones = _CN_DIGITS.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
            return str(tens * 10 + ones)
        if len(s) == 1 and s in _CN_DIGITS:
            return str(_CN_DIGITS[s])
        return s

    def _num_repl(m: re.Match) -> str:
        whole = _parse_cn_int(m.group(1))
        dec = m.group(2)
        if dec and dec in _CN_DIGITS:
            return f"{whole}.{_CN_DIGITS[dec]}"
        return whole

    t = re.sub(r"([一二两三四五六七八九]?十[一二三四五六七八九]?)(?:点([零一二三四五六七八九]))?", _num_repl, t)
    t = re.sub(r"([零一二两三四五六七八九])(?:点([零一二三四五六七八九]))?(?=\s*[度%℃档盏台个倍])", _num_repl, t)
    return t


def format_device_card(plan: dict, it: dict) -> dict:
    rm = room_for_item(plan, it)
    rname = rm["name"] if rm else "全屋"
    t = it.get("type", "")
    if t == "lamp":
        on = bool(it.get("power"))
        state = f"{it.get('level', 65)}% · {it.get('color_temp', '暖白')}" if on else "已关闭"
    elif t == "ac":
        on = bool(it.get("power"))
        if not on:
            state = "已关闭"
        elif it.get("mode") == "送风":
            state = f"送风 · {it.get('fan_speed', '自动')}"
        else:
            state = f"{it.get('mode', '制冷')} · {it.get('target', 26)}°C"
    elif t == "curtain":
        pos = int(it.get("position", 0))
        on = pos > 5
        state = "已闭合" if pos <= 3 else ("全开" if pos >= 97 else f"开启 {pos}%")
    else:
        on = bool(it.get("power"))
        extra_keys = [k for k in it.keys() if k not in ("id", "name", "type", "x", "y", "w", "h", "angle", "power", "online", "desired", "last_status", "updated_at", "mount")]
        if on and extra_keys:
            state = f"开启 · {it[extra_keys[0]]}"
        else:
            state = "已开启" if on else "已关闭"
    return {
        "id": it["id"],
        "name": it["name"],
        "room": rname,
        "type": t,
        "on": on,
        "state": state,
    }


# ------------------------------------------------------------------------------
# Comprehensive Deterministic Intent-Slot & Dialogue Engine
# ------------------------------------------------------------------------------
class IntentSlotEngine:
    """Comprehensive Chinese smart-home NLU with mandatory slot clarification & multi-turn memory."""

    FOCUS_TTL_SEC = 90.0

    def parse(self, text: str, plan: dict, climate: dict, session: dict,
              active_room: str | None = None, allow_fuzzy: bool = False,
              device_types: dict | None = None) -> dict | None:
        raw_t = text.strip()
        if not raw_t:
            return None

        now = time.time()
        types_map = device_types or {}

        # 0. Cancellation / Abort ("算了", "不用了", "取消")
        if any(raw_t == w or raw_t.startswith(w) for w in CANCEL_WORDS):
            session["pending_intent"] = None
            return {
                "matched": True, "query_only": True, "actions": [], "cards": [],
                "reply": "好的，已取消。",
                "explanation": "用户取消当前待定指令。",
            }

        # 1. Check if user is answering a previous slot-clarification question (`pending_intent`)!
        pending = session.get("pending_intent")
        if pending and (now - pending.get("ts", 0) < 120.0):
            resolved_text = self._try_complete_pending(raw_t, plan, pending, active_room)
            if resolved_text:
                session["pending_intent"] = None
                raw_t = resolved_text
            elif not self._has_action_or_query_verb(raw_t):
                # Keep pending alive if unrecognizable fragment
                pass
            else:
                # User moved on to a brand-new full command
                session["pending_intent"] = None

        # 2. Check Topic-Switch Ellipsis ("那书房呢？", "主卧的呢", "走廊呢")
        last_tpl = session.get("last_template")
        if last_tpl and (now - last_tpl.get("ts", 0) < 120.0):
            m_ell = re.match(r"^(?:那|那么|还有)?(.{1,6}?)(?:的)?呢[？?。！!]?$", raw_t)
            if m_ell:
                frag = m_ell.group(1).strip()
                rms = self._extract_rooms(frag, plan, include_restricted=True)
                if rms:
                    if any(r.get("restricted") for r in rms):
                        return self._rbac_denied_reply()
                    r_names = "和".join(r["name"] for r in rms)
                    raw_t = last_tpl["pattern"].replace("{room}", r_names)

        # Escalate visual/fuzzy phrases to VLM ONLY if an external VLM is configured (`allow_fuzzy=False`)
        if not allow_fuzzy and (any(c in raw_t for c in VISUAL_CUES) or any(c in raw_t for c in FUZZY_CUES)):
            return None

        # 3. Handle Multi-Clause Compound Sentences ("打开客厅灯，顺便把空调调到25度")
        clauses = self._split_compound_clauses(raw_t)
        if len(clauses) > 1:
            return self._execute_compound_clauses(clauses, plan, climate, session, active_room, types_map)

        return self._parse_single_clause(raw_t, plan, climate, session, active_room, types_map)

    # --------------------------------------------------------------------------
    # Core Single-Clause NLU
    # --------------------------------------------------------------------------
    def _parse_single_clause(self, raw_t: str, plan: dict, climate: dict, session: dict,
                             active_room: str | None, types_map: dict) -> dict | None:
        now = time.time()
        t_norm = normalize_chinese_numbers(raw_t)
        hassil_hit = match_hassil_templates(t_norm)
        t = strip_polite_wrappers(t_norm)

        # A. Polite Greeting / Capability Inquiry
        if t in ("你好", "嗨", "在吗", "哈喽", "你能做什么", "帮助", "怎么用", "功能"):
            return {
                "matched": True, "query_only": True, "actions": [], "cards": [],
                "options": [
                    {"label": "打开客厅灯", "text": "打开客厅灯"},
                    {"label": "客厅空调 25 度", "text": "把客厅空调调到 25 度"},
                    {"label": "家里现在多少度", "text": "家里现在多少度"},
                    {"label": "哪些灯还开着", "text": "哪些灯还开着"},
                ],
                "reply": "我在。你可以让我开关各房间的灯光、空调与窗帘，询问温湿度和设备状态，或者下达多步指令。",
                "explanation": "语音助手能力引导。",
            }

        # B. Negation / Prohibition Guard ("别关客厅灯", "不要开灯", "先不用关空调")
        if has_negation_guard(t_norm) or re.search(r"(别|不要|不用|勿|先别|千万别)\s*(开|打开|开启|关|关闭|关掉|调|动|拉)", t):
            return {
                "matched": True, "query_only": True, "actions": [], "cards": [],
                "reply": "好的，保持当前状态不变。",
                "explanation": "识别到否定/保持指令，不执行状态变更。",
            }

        # C. RBAC Check on Restricted Private Rooms (e.g. Guest asking about 主卧 / 长辈次卧)
        all_mentioned_rooms = self._extract_rooms(t, plan, include_restricted=True)
        if all_mentioned_rooms and any(r.get("restricted") for r in all_mentioned_rooms):
            return self._rbac_denied_reply()
        explicit_rooms = [r for r in all_mentioned_rooms if not r.get("restricted")]

        # C2. Auto / Manual Cooperative Control Balance Voice Intents
        # ("恢复客厅自动控制", "解除客厅手动接管", "锁定客厅手动模式", "暂停书房自动感应")
        if re.search(r"(?:恢复|切回|开启|交还|改回).*自动|(?:解除|取消|退出).*手动", t):
            target_r = explicit_rooms[0] if explicit_rooms else (
                next((r for r in plan["rooms"] if r["id"] == active_room and not r.get("restricted")), None) if active_room else None
            )
            rid_val = target_r["id"] if target_r else "__all__"
            r_label = target_r["name"] if target_r else "全屋"
            return {
                "matched": True,
                "override_op": ("release", rid_val),
                "actions": [],
                "reply": f"好的，{r_label}已恢复自动感知托管。",
                "explanation": f"释放{r_label}手动接管租约，交还传感器自适应策略。",
            }
        if re.search(r"(?:固定|锁定|保持).*手动|(?:暂停|关闭|停用).*自动|不要自动", t):
            target_r = explicit_rooms[0] if explicit_rooms else (
                next((r for r in plan["rooms"] if r["id"] == active_room and not r.get("restricted")), None) if active_room else None
            )
            if not target_r:
                opts = [{"label": r["name"], "text": f"锁定{r['name']}手动模式"} for r in plan["rooms"] if not r.get("restricted")][:5]
                return {
                    "matched": True, "query_only": True, "actions": [], "cards": [], "options": opts,
                    "reply": "请问要将哪个房间固定为手动控制？",
                    "explanation": "锁定手动控制缺少目标房间，发起澄清追问。",
                }
            return {
                "matched": True,
                "override_op": ("hold", target_r["id"]),
                "actions": [],
                "reply": f"好的，已将{target_r['name']}固定为手动控制，传感器不会自动改写设备。",
                "explanation": f"为{target_r['name']}设置常驻手动接管锁。",
            }
        m_excl = re.search(
            r"(?:除了|除开|只留)(.+?)(?:以外|之外|外|[，,\s]+|(?=其他|其余|别的|剩下|所有|全部|的?灯|的?空调|的?窗帘))(?:其他|其余|别的|剩下|所有|全部)?(.+)",
            t,
        )
        if m_excl:
            excl_rooms = self._extract_rooms(m_excl.group(1), plan, include_restricted=False)
            rest_phrase = m_excl.group(2)
            if excl_rooms and any(w in rest_phrase for w in ("关", "开", "熄")):
                return self._handle_exclusion_command(excl_rooms, rest_phrase, plan)

        # E. Home Status Queries (Q&A: temperature, humidity, lux, scene mode, running devices)
        if self._is_status_question(t):
            res = self._handle_status_query(t, plan, climate, explicit_rooms, active_room)
            if explicit_rooms:
                if "灯" in t:
                    session["last_template"] = {"pattern": "{room}的灯开着吗", "ts": now}
                elif "度" in t or "温" in t:
                    session["last_template"] = {"pattern": "{room}现在多少度", "ts": now}
            return res

        # F. Explicit Scene Triggers
        scene_res = self._match_scene_intent(t)
        if scene_res:
            return scene_res

        # G. Extract Device Type / Specific Item Slot
        explicit_item = self._find_explicit_item(t, plan)
        dev_types, dev_noun = self._extract_device_types(t, types_map)

        # Infer device category from domain-specific action/attribute words if noun omitted
        if not dev_types and not explicit_item:
            if any(w in t for w in ("度", "℃", "制冷", "制热", "冷风", "暖风", "除湿", "抽湿", "送风", "通风",
                                     "有点冷", "太冷", "好冷", "冻死", "有点热", "太热", "好热", "热死", "凉快", "暖和", "好闷", "有点闷", "风速", "静音风", "强风")):
                dev_types, dev_noun = ("ac",), "空调"
            elif any(w in t for w in ("亮度", "调暗", "调亮", "暗一点", "亮一点", "再暗", "再亮", "太暗", "有点暗", "看不清",
                                       "太亮", "刺眼", "看书", "阅读", "观影", "看电影", "夜灯", "起夜", "最亮", "最暗",
                                       "暖白", "冷白", "自然光", "暖光", "白光", "冷光", "色温")):
                dev_types, dev_noun = ("lamp", "switch"), "灯"
            elif any(w in t for w in ("拉开", "拉上", "合上", "遮光", "透光", "留条缝")):
                dev_types, dev_noun = ("curtain",), "窗帘"

        # H. Universal / Collective Commands ("关掉所有灯", "把全部空调关了", "把全屋电器都关掉", "打开公共区域的灯")
        is_universal = any(w in t for w in UNIVERSAL_WORDS) or ("公共" in t and "灯" in t)
        if is_universal and not explicit_rooms and not explicit_item:
            return self._handle_collective_command(t, plan, dev_types, dev_noun)

        # I. Deictic Resolution ("把这里的灯关了" -> uses `active_room`)
        is_deictic = any(w in t for w in DEICTIC_WORDS)
        if is_deictic and not explicit_rooms and not explicit_item:
            if active_room:
                rm = next((r for r in plan["rooms"] if not r.get("restricted") and r["id"] == active_room), None)
                if rm:
                    explicit_rooms = [rm]
            if not explicit_rooms:
                opts = [{"label": r["name"], "text": raw_t.replace("这里", r["name"]).replace("这间", r["name"])}
                        for r in plan["rooms"] if not r.get("restricted")][:6]
                session["pending_intent"] = {"template": "{room}" + raw_t, "dev_types": dev_types, "ts": now}
                return {
                    "matched": True, "query_only": True, "actions": [], "cards": [], "options": opts,
                    "reply": "请问你现在在哪个房间？",
                    "explanation": "指示代词「这里」缺少激活房间上下文，发起房间追问。",
                }

        # J. Strict Anaphora vs Mandatory Slot Clarification!
        # Bare commands like "关灯", "开灯", "关空调", "开空调", "拉开窗帘" MUST NOT silently guess a room!
        focus_fresh = (now - session.get("focus_ts", 0)) <= self.FOCUS_TTL_SEC
        has_pronoun = any(p in t for p in ANAPHORIC_PRONOUNS) or ("它" in t)
        has_cont = any(c in t for c in CONTINUATION_CUES)

        # A bare open/close command (e.g. "关灯", "把灯关了", "开空调") is NOT an elliptical parameter tweak!
        is_bare_power_toggle = bool(re.search(r"(开|关|熄|亮灯|开灯|关灯|拉上|拉开|合上)", t)) and not has_pronoun and not has_cont and not any(
            w in t for w in ("调亮", "调暗", "亮一", "暗一", "太亮", "太暗", "有点暗", "刺眼")
        )
        is_param_refinement = (not is_bare_power_toggle) and any(
            w in t for w in ("度", "%", "调高", "调低", "高一", "低一", "亮一", "暗一", "调亮", "调暗",
                             "太亮", "太暗", "有点暗", "刺眼", "柔和", "有点冷", "太冷", "有点热", "太热", "有点闷", "好闷",
                             "暖白", "自然光", "冷白", "暖光", "冷光", "白光", "制冷", "制热", "除湿", "送风", "静音", "强风")
        )

        used_anaphora = False
        if not explicit_item and not explicit_rooms:
            if has_pronoun and focus_fresh and session.get("device_id"):
                focused_it = next((it for it in plan["items"] if it["id"] == session["device_id"]), None)
                if focused_it:
                    explicit_item = focused_it
                    used_anaphora = True
            elif (has_cont or is_param_refinement) and focus_fresh and session.get("device_id"):
                focused_it = next((it for it in plan["items"] if it["id"] == session["device_id"]), None)
                if focused_it and (not dev_types or focused_it["type"] in dev_types):
                    explicit_item = focused_it
                    used_anaphora = True

        # K. Gather Candidate Devices
        candidates: list[dict] = []
        if explicit_item:
            candidates = [explicit_item]
        elif explicit_rooms:
            rids = {r["id"] for r in explicit_rooms}
            for it in plan["items"]:
                rm = room_for_item(plan, it)
                it_rid = rm["id"] if rm else ("living" if it.get("mount") == "ceiling" else None)
                if it_rid not in rids:
                    continue
                if dev_types and it["type"] not in dev_types:
                    continue
                if not dev_types and not self._is_controllable(it, types_map):
                    continue
                candidates.append(it)
            # If user named a room + device type that doesn't exist in that room (e.g. "打开厨房空调")
            if not candidates and dev_noun:
                r_str = "、".join(r["name"] for r in explicit_rooms)
                all_of_type = [it for it in plan["items"] if dev_types and it["type"] in dev_types
                               and not (room_for_item(plan, it) or {}).get("restricted")]
                opts = [{"label": x["name"], "text": f"打开{x['name']}"} for x in all_of_type[:4]]
                return {
                    "matched": True, "query_only": True, "actions": [], "cards": [], "options": opts,
                    "reply": f"{r_str}里没有安装{dev_noun}。",
                    "explanation": f"房间「{r_str}」内不存在{dev_noun}设备。",
                }
        else:
            # NO room specified and NO valid anaphora -> Disambiguate across the home!
            all_Pool = [
                it for it in plan["items"]
                if not (room_for_item(plan, it) or {}).get("restricted")
                and ((dev_types and it["type"] in dev_types) or (not dev_types and self._is_controllable(it, types_map)))
            ]
            # If the entire home only has 1 device of that category (e.g. sole living-room curtain), control it directly!
            if len(all_Pool) == 1 and dev_types:
                candidates = all_Pool
            elif len(all_Pool) >= 1 and (dev_types or self._has_action_verb(t)):
                return self._build_disambiguation(raw_t, t, plan, all_Pool, dev_types, dev_noun, session)
            else:
                return None

        if not candidates:
            return None

        # L. Generate Actions across Selected Candidate(s) (supports multi-room e.g. 客厅和走廊!)
        all_actions: list[dict] = []
        spoken_items: list[str] = []
        already_notes: list[str] = []
        high_risk = False
        primary = candidates[0]

        # If explicit_rooms matched multiple items in one room without dev_types (e.g. "把客厅关了"), prefer lamps+ACs that are ON
        if not explicit_item and not dev_types and len(candidates) > 1:
            if any(w in t for w in ("关", "熄")):
                on_cands = [c for c in candidates if self._item_is_active(c)]
                if on_cands:
                    candidates = on_cands
            else:
                lamp_cands = [c for c in candidates if c["type"] in ("lamp", "switch")]
                if lamp_cands:
                    candidates = lamp_cands[:1]

        # When single room has e.g. ceiling mounted extra bulbs + main lamp, target primary or all if "都"
        if len(explicit_rooms) == 1 and len(candidates) > 1 and "都" not in t and "全" not in t and not explicit_item:
            candidates = candidates[:1]

        for target_it in candidates:
            rm_obj = room_for_item(plan, target_it)
            if rm_obj and rm_obj.get("sleep") and any(w in t for w in ("开灯", "打开", "开启", "调亮", "最亮", "100")):
                high_risk = True
            act_res = self._compile_device_actions(t, target_it, types_map, hassil_hit=hassil_hit)
            if act_res is None:
                continue
            if act_res.get("already"):
                already_notes.append(act_res["reply"])
            else:
                all_actions.extend(act_res["actions"])
                spoken_items.append(act_res["reply"])

        if not all_actions and already_notes:
            return {
                "matched": True, "query_only": True, "actions": [],
                "cards": [format_device_card(plan, c) for c in candidates[:3]],
                "reply": "；".join(already_notes),
                "explanation": "目标设备已处于请求状态，无需重复下发指令。",
            }

        if not all_actions:
            return None

        primary = candidates[0]
        p_room = room_for_item(plan, primary)
        spoken = "；".join(spoken_items)
        if not spoken.endswith("。"):
            spoken += "。"
        if len(spoken_items) == 1 and not spoken.startswith("好的"):
            spoken = "好的，" + spoken

        if high_risk and p_room:
            spoken = f"{p_room['name']}当前处于睡眠免打扰状态，确认要继续操作{primary['name']}吗？"

        # Save multi-turn focus & topic-switch template
        if len(candidates) == 1:
            session["room_id"] = p_room["id"] if p_room else None
            session["device_id"] = primary["id"]
            session["focus_ts"] = now
            if p_room and p_room["name"] in raw_t:
                session["last_template"] = {"pattern": raw_t.replace(p_room["name"], "{room}"), "ts": now}
            elif explicit_rooms:
                # Replace matched synonym word with {room}
                pat = self._replace_room_word_with_slot(raw_t)
                if "{room}" in pat:
                    session["last_template"] = {"pattern": pat, "ts": now}

        anaphora_note = f"（延续上文焦点：{primary['name']}）" if used_anaphora else ""
        return {
            "matched": True,
            "high_risk": high_risk,
            "focus_update": {"room_id": p_room["id"] if p_room else None, "device_id": primary["id"]},
            "actions": all_actions,
            "reply": spoken,
            "explanation": f"意图槽位引擎解析执行{anaphora_note}：{spoken}",
        }

    # --------------------------------------------------------------------------
    # Smart State-Aware Slot Disambiguation & Pending Intent Completion
    # --------------------------------------------------------------------------
    def _build_disambiguation(self, raw_t: str, t: str, plan: dict, pool: list[dict],
                              dev_types: tuple[str, ...] | None, dev_noun: str,
                              session: dict) -> dict:
        now = time.time()
        wants_off = any(w in t for w in ("关", "熄", "拉上", "合上", "闭合"))
        wants_on = any(w in t for w in ("开", "亮", "点亮", "拉开"))

        # Check active vs inactive devices in pool!
        active_devs = [it for it in pool if self._item_is_active(it)]
        inactive_devs = [it for it in pool if not self._item_is_active(it)]
        noun = dev_noun or "设备"

        # Build action template preserving user's exact parameter (e.g. "把{dev}调到24度", "关掉{dev}", "把{dev}调暗一点")
        action_tpl = self._make_device_action_template(t, wants_off, wants_on, dev_types)

        # Case 1: User wants to TURN OFF (e.g. "关灯", "把空调关了", "拉上窗帘")
        if wants_off and not wants_on:
            if not active_devs:
                # Zero devices of that type are currently ON!
                open_opts = [{"label": f"打开{it['name']}", "text": f"打开{it['name']}"} for it in pool[:4]]
                return {
                    "matched": True, "query_only": True, "actions": [], "cards": [],
                    "options": open_opts,
                    "reply": f"目前家里的{noun}都已经关着了。",
                    "explanation": f"检测到缺省房间的关闭指令，经核查当前全屋无开启中的{noun}。",
                }

            # Only offer currently-ON devices when asking which one to turn OFF!
            if len(active_devs) >= 2:
                opts = [{"label": it["name"], "text": action_tpl.format(dev=it["name"])} for it in active_devs[:5]]
                opts.append({"label": f"全部关掉 ({len(active_devs)})", "text": f"关掉所有{noun}"})
                on_names = "、".join(x["name"] for x in active_devs[:4])
                prompt = f"目前有 {len(active_devs)} 处{noun}开着（{on_names}），请问你要关哪一个？"
            else:
                only_on = active_devs[0]
                opts = [
                    {"label": f"关掉{only_on['name']}", "text": f"关掉{only_on['name']}"},
                    {"label": "不用了", "text": "不用了"},
                ]
                prompt = f"目前只有{only_on['name']}开着，需要把它关掉吗？"

            session["pending_intent"] = {
                "action_tpl": action_tpl, "dev_types": dev_types, "noun": noun, "verb": "off", "ts": now
            }
            return {
                "matched": True, "query_only": True, "actions": [],
                "cards": [format_device_card(plan, x) for x in active_devs[:2]],
                "options": opts,
                "reply": prompt,
                "explanation": f"指令未指明房间，已检索当前开启的{noun}并发起槽位澄清追问。",
            }

        # Case 2: User wants to ADJUST / TURN ON (e.g. "开灯", "开空调", "调到24度", "调暗一点")
        is_dim_or_adj = any(w in t for w in ("暗", "亮", "色温", "暖白", "冷白", "自然光")) and not wants_on
        ordered = (active_devs + inactive_devs) if is_dim_or_adj else (inactive_devs + active_devs)
        if not ordered:
            ordered = pool

        opts = [{"label": it["name"], "text": action_tpl.format(dev=it["name"])} for it in ordered[:6]]
        if wants_on and dev_types == ("lamp", "switch"):
            opts.append({"label": "公共区域灯光", "text": "打开公共区域的灯"})

        verb_desc = self._describe_pending_verb(t, wants_on, noun)
        session["pending_intent"] = {
            "action_tpl": action_tpl, "dev_types": dev_types, "noun": noun, "verb": "on", "ts": now
        }
        return {
            "matched": True, "query_only": True, "actions": [], "cards": [],
            "options": opts,
            "reply": f"请问你要{verb_desc}？",
            "explanation": f"指令缺省目标房间槽位，列出 {len(opts)} 个候选{noun}等待用户确认。",
        }

    def _try_complete_pending(self, reply_raw: str, plan: dict, pending: dict,
                              active_room: str | None) -> str | None:
        r_clean = reply_raw.strip("。！!？?，, ")
        noun = pending.get("noun", "灯")
        verb = pending.get("verb", "on")
        tpl = pending.get("action_tpl", "打开{dev}")
        dev_types = pending.get("dev_types")

        # "全部" / "都关了" / "所有"
        if r_clean in ("全部", "所有", "全都", "都关", "都关了", "都开", "都打开", "一起", "全关", "全开"):
            return f"{'关掉' if verb == 'off' else '打开'}所有{noun}"

        # "这里" / "这间"
        if any(w in r_clean for w in DEICTIC_WORDS) and active_room:
            rm = next((r for r in plan["rooms"] if r["id"] == active_room and not r.get("restricted")), None)
            if rm:
                r_clean = rm["name"]

        # Exact item name mentioned in short reply (e.g. "客厅灯")
        it_exact = self._find_explicit_item(r_clean, plan)
        if it_exact and not self._has_action_verb(r_clean):
            return tpl.format(dev=it_exact["name"])

        # Room name(s) mentioned in short reply (e.g. "客厅", "主卧的", "客厅和走廊")
        if not self._has_action_verb(r_clean):
            rms = self._extract_rooms(r_clean, plan, include_restricted=False)
            if rms:
                matched_devs = []
                rids = {r["id"] for r in rms}
                for it in plan["items"]:
                    rm = room_for_item(plan, it)
                    it_rid = rm["id"] if rm else ("living" if it.get("mount") == "ceiling" else None)
                    if it_rid in rids and (not dev_types or it["type"] in dev_types):
                        matched_devs.append(it)
                if len(matched_devs) == 1:
                    return tpl.format(dev=matched_devs[0]["name"])
                if len(rms) >= 1:
                    r_join = "和".join(r["name"] for r in rms)
                    return tpl.format(dev=f"{r_join}的{noun}")
        return None

    @staticmethod
    def _make_device_action_template(t: str, wants_off: bool, wants_on: bool,
                                     dev_types: tuple[str, ...] | None) -> str:
        num_m = re.search(r"(\d+(?:\.\d+)?)", t)
        num_s = num_m.group(1) if num_m else None
        if wants_off and not wants_on:
            return "关掉{dev}"
        if dev_types == ("ac",):
            if any(w in t for w in ("闷", "潮", "除湿", "抽湿")):
                return "把{dev}设为除湿模式"
            for m in ("制冷", "制热", "除湿", "送风"):
                if m in t and num_s:
                    return f"把{{dev}}设为{m}{num_s}度"
                if m in t:
                    return f"把{{dev}}设为{m}模式"
            if num_s:
                if any(w in t for w in ("高", "加", "升")) and "调到" not in t:
                    return f"把{{dev}}调高{num_s}度"
                if any(w in t for w in ("低", "减", "降")) and "调到" not in t:
                    return f"把{{dev}}调低{num_s}度"
                return f"把{{dev}}调到{num_s}度"
            if any(w in t for w in ("冷", "凉快", "太热", "有点热")):
                return "把{dev}调低一点"
            if any(w in t for w in ("暖", "太冷", "有点冷")):
                return "把{dev}调高一点"
            return "打开{dev}"
        if dev_types == ("curtain",):
            if num_s:
                return f"把{{dev}}开到{num_s}%"
            return "拉开{dev}"
        # Lamp / generic
        for ct in ("暖白", "自然光", "冷白", "暖光", "冷光", "白光"):
            if ct in t:
                return f"把{{dev}}设为{ct}"
        if any(w in t for w in ("调暗", "暗一点", "太亮", "刺眼")):
            return f"把{{dev}}调暗{num_s + '%' if num_s else '一点'}"
        if any(w in t for w in ("调亮", "亮一点", "太暗", "有点暗", "看书")):
            return f"把{{dev}}调亮{num_s + '%' if num_s else '一点'}"
        if num_s:
            return f"把{{dev}}亮度调到{num_s}%"
        return "打开{dev}"

    @staticmethod
    def _describe_pending_verb(t: str, wants_on: bool, noun: str) -> str:
        num_m = re.search(r"(\d+(?:\.\d+)?)", t)
        num_s = num_m.group(1) if num_m else None
        if noun == "空调" and num_s:
            return f"把哪一间的空调调到 {num_s}°C"
        if any(w in t for w in ("调暗", "暗一点", "太亮", "刺眼")):
            return f"调暗哪一间的{noun}"
        if any(w in t for w in ("调亮", "亮一点", "太暗", "有点暗")):
            return f"调亮哪一间的{noun}"
        if wants_on:
            return f"打开哪里的{noun}"
        return f"控制哪一间的{noun}"

    # --------------------------------------------------------------------------
    # Atomic Device Capability Compiler (Lamp, AC, Curtain, Switch, Custom OCP)
    # --------------------------------------------------------------------------
    def _compile_device_actions(self, t: str, item: dict, types_map: dict,
                                hassil_hit: dict | None = None) -> dict | None:
        ptype = item["type"]
        pname = item["name"]
        h_op = (hassil_hit or {}).get("op")
        h_slots = (hassil_hit or {}).get("slots", {})
        slot_num_s = h_slots.get("value") or h_slots.get("delta")
        num_m = re.search(r"(\d+(?:\.\d+)?)", slot_num_s or t)
        num_val = float(num_m.group(1)) if num_m else None
        actions: list[dict] = []

        if ptype == "ac":
            mode_hit = next((m for m in ("制冷", "制热", "除湿", "送风") if m in t), None)
            if not mode_hit:
                if "冷风" in t or ("冷气" in t and any(w in t for w in ("切", "改", "换"))):
                    mode_hit = "制冷"
                elif "暖风" in t or "暖气" in t or "制暖" in t:
                    mode_hit = "制热"
                elif "抽湿" in t or "去湿" in t or "回南天" in t or "潮湿" in t or "有点闷" in t or "好闷" in t:
                    mode_hit = "除湿"
                elif "通风" in t or "吹风" in t or "透透气" in t:
                    mode_hit = "送风"

            fan_hit = None
            ac_fans = types_map.get("ac", {}).get("caps", {}).get("fan_speed", ["静音", "自动", "强风"])
            if any(w in t for w in ("静音", "微风", "睡眠风", "小风", "低风", "风小一点", "最小风")):
                fan_hit = "静音" if "静音" in ac_fans else ac_fans[0]
            elif any(w in t for w in ("强风", "大风", "高风", "最大风", "风大一点", "猛一点")):
                fan_hit = "强风" if "强风" in ac_fans else ac_fans[-1]
            elif "自动风" in t or ("自动" in t and "风" in t):
                fan_hit = "自动" if "自动" in ac_fans else ac_fans[0]

            is_ac_off = h_op == "off" or (
                any(w in t for w in ("关掉", "关闭", "关机", "关空调", "关了", "关上", "关一下", "停掉", "关"))
                and not any(w in t for w in ("打开", "开启", "开空调", "开一下", "开到"))
            )
            if is_ac_off:
                if not item.get("power"):
                    return {"already": True, "reply": f"{pname}已经是关闭状态了。"}
                return {
                    "actions": [{"deviceId": item["id"], "capability": "power", "value": False}],
                    "reply": f"已关闭{pname}",
                }

            cur_t = float(item.get("target", 26))
            eff_mode = mode_hit or item.get("mode", "制冷")
            spoken_bits = []

            if mode_hit:
                actions.append({"deviceId": item["id"], "capability": "mode", "value": mode_hit})
                spoken_bits.append(f"设为{mode_hit}模式")
            if fan_hit:
                actions.append({"deviceId": item["id"], "capability": "fan_speed", "value": fan_hit})
                spoken_bits.append(f"{fan_hit}风速")

            if eff_mode != "送风":
                if "最高温" in t or ("调到最高" in t):
                    num_val = 30.0
                elif "最低温" in t or ("调到最低" in t):
                    num_val = 16.0

                if num_val is not None and any(w in t for w in ("高", "上调", "加", "升")) and not any(w in t for w in ("调到", "设为", "开到")):
                    new_t = min(30.0, round(cur_t + num_val, 1))
                    v_out = int(new_t) if new_t.is_integer() else new_t
                    actions.append({"deviceId": item["id"], "capability": "target", "value": v_out})
                    spoken_bits.append(f"温度调高至 {v_out}°C")
                elif num_val is not None and any(w in t for w in ("低", "下调", "减", "降")) and not any(w in t for w in ("调到", "设为", "开到")):
                    new_t = max(16.0, round(cur_t - num_val, 1))
                    v_out = int(new_t) if new_t.is_integer() else new_t
                    actions.append({"deviceId": item["id"], "capability": "target", "value": v_out})
                    spoken_bits.append(f"温度调低至 {v_out}°C")
                elif num_val is not None and 16 <= num_val <= 30:
                    v_out = int(num_val) if num_val.is_integer() else num_val
                    actions.append({"deviceId": item["id"], "capability": "target", "value": v_out})
                    spoken_bits.append(f"设为 {v_out}°C")
                elif num_val is not None and (num_val < 16 or num_val > 30):
                    raise Problem(f"空调温度支持范围为 16°C–30°C（当前请求 {num_val:g}°C 超出安全范围）。")
                elif any(w in t for w in ("调高", "高一点", "暖一点", "暖和", "有点冷", "太冷", "好冷", "冻死")):
                    step = 2 if any(w in t for w in ("太冷", "好冷", "冻死", "有点冷")) else 1
                    new_t = int(min(30, round(cur_t + step)))
                    actions.append({"deviceId": item["id"], "capability": "target", "value": new_t})
                    spoken_bits.append(f"调高至 {new_t}°C")
                elif any(w in t for w in ("调低", "低一点", "凉快", "冷一点", "有点热", "太热", "好热", "热死")):
                    if not item.get("power"):
                        new_t = 24
                        if not mode_hit:
                            actions.append({"deviceId": item["id"], "capability": "mode", "value": "制冷"})
                    else:
                        step = 2 if any(w in t for w in ("太热", "好热", "热死", "有点热")) else 1
                        new_t = int(max(16, round(cur_t - step)))
                    actions.append({"deviceId": item["id"], "capability": "target", "value": new_t})
                    spoken_bits.append(f"调至 {new_t}°C")

            if actions or any(w in t for w in ("打开", "开启", "开空调", "开机", "开一下", "开")):
                if not actions and item.get("power"):
                    return {"already": True, "reply": f"{pname}本来就是开着的（当前 {item.get('target', 26)}°C）。"}
                actions.insert(0, {"deviceId": item["id"], "capability": "power", "value": True})
                desc = "、".join(spoken_bits) if spoken_bits else "已开启"
                return {"actions": actions, "reply": f"{pname}{desc}"}
            return None

        if ptype == "curtain":
            cur_pos = int(item.get("position", 0))
            if any(w in t for w in ("关", "闭合", "拉上", "合上", "遮光", "全关")) and not any(w in t for w in ("打开", "拉开")):
                if cur_pos <= 2:
                    return {"already": True, "reply": f"{pname}已经是合上的了。"}
                return {
                    "actions": [{"deviceId": item["id"], "capability": "position", "value": 0}],
                    "reply": f"已合上{pname}",
                }
            if "留条缝" in t or "透点光" in t:
                pos = 25
            elif num_val is not None:
                pos = int(max(0, min(100, num_val)))
            elif any(w in t for w in ("打开", "拉开", "全开", "开")):
                pos = 100
            else:
                return None
            if abs(cur_pos - pos) <= 2:
                return {"already": True, "reply": f"{pname}当前已经在 {cur_pos}% 位置了。"}
            return {
                "actions": [{"deviceId": item["id"], "capability": "position", "value": pos}],
                "reply": f"已将{pname}{'完全拉开' if pos >= 98 else f'开至 {pos}%'}",
            }

        if ptype in ("lamp", "switch"):
            is_lamp_off = h_op == "off" or (
                any(w in t for w in ("关掉", "关闭", "关灯", "熄灭", "关了", "关上", "灭掉", "熄灯", "关一下", "关"))
                and not any(w in t for w in ("打开", "开启", "开灯", "开一下", "开关"))
            )
            if is_lamp_off:
                if not item.get("power"):
                    return {"already": True, "reply": f"{pname}已经是关着的了。"}
                return {
                    "actions": [{"deviceId": item["id"], "capability": "power", "value": False}],
                    "reply": f"已关掉{pname}",
                }

            ct_hit = None
            if ptype == "lamp":
                if any(w in t for w in ("暖白", "暖光", "黄光", "温馨", "助眠")):
                    ct_hit = "暖白"
                elif any(w in t for w in ("自然光", "自然", "中性光")):
                    ct_hit = "自然光"
                elif any(w in t for w in ("冷白", "冷光", "白光", "正白")):
                    ct_hit = "冷白"

            lvl_target: int | None = None
            if ptype == "lamp":
                cur_lvl = int(item.get("level", 65)) if item.get("power") else 60
                if any(w in t for w in ("最亮", "全亮", "拉满", "最大亮度")):
                    lvl_target = 100
                elif any(w in t for w in ("最暗", "微光", "夜灯", "起夜", "小夜灯", "最低亮度")):
                    lvl_target = 15
                    ct_hit = ct_hit or "暖白"
                elif any(w in t for w in ("看电影", "观影", "看电视", "氛围")):
                    lvl_target = 25
                    ct_hit = ct_hit or "暖白"
                elif any(w in t for w in ("看书", "阅读", "写字", "学习", "办公", "工作")):
                    lvl_target = 85
                    ct_hit = ct_hit or "自然光"
                elif any(w in t for w in ("调暗", "暗一点", "再暗", "压暗", "太亮", "刺眼", "柔和", "低一点")):
                    delta = int(num_val) if (num_val is not None and num_val <= 90) else 25
                    lvl_target = max(10, cur_lvl - delta)
                elif any(w in t for w in ("调亮", "亮一点", "再亮", "太暗", "有点暗", "看不清", "高一点")):
                    delta = int(num_val) if (num_val is not None and num_val <= 90) else 25
                    lvl_target = min(100, max(75, cur_lvl + delta))
                elif num_val is not None:
                    lvl_target = int(max(1, min(100, num_val)))

            spoken_bits = []
            if lvl_target is not None:
                actions.append({"deviceId": item["id"], "capability": "level", "value": lvl_target})
                spoken_bits.append(f"亮度调至 {lvl_target}%")
            if ct_hit:
                actions.append({"deviceId": item["id"], "capability": "color_temp", "value": ct_hit})
                spoken_bits.append(f"设为{ct_hit}")

            if actions or any(w in t for w in ("打开", "开启", "开灯", "亮灯", "点亮", "开一下", "开")):
                if not actions and item.get("power"):
                    lvl_note = f"（当前亮度 {item.get('level', 65)}%）" if ptype == "lamp" else ""
                    return {"already": True, "reply": f"{pname}本来就是开着的{lvl_note}。"}
                actions.insert(0, {"deviceId": item["id"], "capability": "power", "value": True})
                if spoken_bits:
                    return {"actions": actions, "reply": f"已将{pname}" + "并".join(spoken_bits)}
                return {"actions": actions, "reply": f"已打开{pname}"}
            return None

        # Dynamic Custom Registered Matter Device (F2 OCP!)
        tspec = types_map.get(ptype, {})
        caps = tspec.get("caps", {})
        if any(w in t for w in ("关", "停")) and "power" in caps:
            return {"actions": [{"deviceId": item["id"], "capability": "power", "value": False}], "reply": f"已关闭{pname}"}
        for ck, dom in caps.items():
            if ck == "power":
                continue
            if isinstance(dom[0], (int, float)) and num_val is not None:
                v = int(max(dom[0], min(dom[1], num_val)))
                u = tspec.get("cap_meta", {}).get(ck, {}).get("unit", "")
                if "power" in caps:
                    actions.append({"deviceId": item["id"], "capability": "power", "value": True})
                actions.append({"deviceId": item["id"], "capability": ck, "value": v})
                return {"actions": actions, "reply": f"已将{pname}设为 {v}{u}"}
        if "power" in caps and any(w in t for w in ("开", "启")):
            return {"actions": [{"deviceId": item["id"], "capability": "power", "value": True}], "reply": f"已打开{pname}"}
        return None

    # --------------------------------------------------------------------------
    # Collective, Exclusion, Compound Clauses & Status Q&A Helpers
    # --------------------------------------------------------------------------
    def _handle_collective_command(self, t: str, plan: dict,
                                   dev_types: tuple[str, ...] | None, dev_noun: str) -> dict | None:
        wants_off = any(w in t for w in ("关", "断电", "熄", "拉上", "合上"))
        wants_on = any(w in t for w in ("开", "亮", "点亮", "拉开"))
        public_only = "公共" in t

        pool = []
        for it in plan["items"]:
            rm = room_for_item(plan, it)
            if rm and rm.get("restricted"):
                continue
            if public_only and rm and rm.get("zone") != "public":
                continue
            if dev_types and it["type"] not in dev_types:
                continue
            if not dev_types and it["type"] not in ("lamp", "switch", "ac", "curtain"):
                continue
            pool.append(it)

        if wants_off and not wants_on:
            actions = []
            touched_names = []
            for it in pool:
                if it["type"] in ("lamp", "switch", "ac") and it.get("power"):
                    actions.append({"deviceId": it["id"], "capability": "power", "value": False})
                    touched_names.append(it["name"])
                elif it["type"] == "curtain" and int(it.get("position", 0)) > 3:
                    actions.append({"deviceId": it["id"], "capability": "position", "value": 0})
                    touched_names.append(it["name"])
            noun = dev_noun or "电器设备"
            if not actions:
                return {
                    "matched": True, "query_only": True, "actions": [], "cards": [],
                    "reply": f"家里的{noun}目前都已经关好了。",
                    "explanation": f"全屋批量关闭核查：当前无开启中的{noun}。",
                }
            # Whole-home all-appliance shutdown or >=4 devices asks confirmation
            if not dev_types or len(actions) >= 4:
                return {
                    "matched": True, "high_risk": True, "actions": actions,
                    "reply": f"确认要关闭全屋正在运行的 {len(actions)} 台{noun}吗？",
                    "explanation": f"全屋批量关闭指令（涉及 {len(actions)} 台{noun}），请求二次确认。",
                }
            return {
                "matched": True, "high_risk": False, "actions": actions,
                "reply": f"好的，已关闭{'、'.join(touched_names)}。",
                "explanation": f"批量关闭 {len(actions)} 台{noun}。",
            }

        if wants_on:
            actions = []
            touched_names = []
            for it in pool:
                rm = room_for_item(plan, it)
                if rm and rm.get("sleep") and not public_only:
                    continue  # Respect sleep DND rooms during collective turn-on!
                if it["type"] in ("lamp", "switch") and not it.get("power"):
                    actions.append({"deviceId": it["id"], "capability": "power", "value": True})
                    touched_names.append(it["name"])
                elif it["type"] == "curtain" and int(it.get("position", 0)) < 95:
                    actions.append({"deviceId": it["id"], "capability": "position", "value": 100})
                    touched_names.append(it["name"])
            if not actions:
                return {
                    "matched": True, "query_only": True, "actions": [], "cards": [],
                    "reply": "对应的设备都已经开启了（睡眠免打扰卧室已自动跳过）。",
                    "explanation": "批量开启核查：无待开启设备。",
                }
            if len(actions) >= 5:
                return {
                    "matched": True, "high_risk": True, "actions": actions,
                    "reply": f"确认要同时开启 {len(actions)} 处{dev_noun or '设备'}吗？（睡眠免打扰房间已自动跳过）",
                    "explanation": f"批量开启 {len(actions)} 处设备，请求确认。",
                }
            return {
                "matched": True, "high_risk": False, "actions": actions,
                "reply": f"好的，已为你开启{'、'.join(touched_names[:4])}{'等设备' if len(touched_names) > 4 else ''}。",
                "explanation": f"批量开启 {len(actions)} 处设备。",
            }
        return None

    def _handle_exclusion_command(self, excl_rooms: list[dict], rest_phrase: str, plan: dict) -> dict:
        excl_ids = {r["id"] for r in excl_rooms}
        excl_names = "、".join(r["name"] for r in excl_rooms)
        dev_types, dev_noun = self._extract_device_types(rest_phrase, {})
        if not dev_types:
            dev_types, dev_noun = ("lamp", "switch"), "灯"
        wants_off = any(w in rest_phrase for w in ("关", "熄"))
        actions = []
        names = []
        for it in plan["items"]:
            if it["type"] not in dev_types:
                continue
            rm = room_for_item(plan, it)
            if rm and (rm.get("restricted") or rm["id"] in excl_ids):
                continue
            if wants_off and it.get("power"):
                actions.append({"deviceId": it["id"], "capability": "power", "value": False})
                names.append(it["name"])
            elif not wants_off and not it.get("power") and not (rm and rm.get("sleep")):
                actions.append({"deviceId": it["id"], "capability": "power", "value": True})
                names.append(it["name"])
        if not actions:
            return {
                "matched": True, "query_only": True, "actions": [], "cards": [],
                "reply": f"除{excl_names}外，其余{dev_noun}目前已经是{'关闭' if wants_off else '开启'}状态了。",
                "explanation": "排除式群控检查：其余设备状态已满足。",
            }
        return {
            "matched": True, "high_risk": False, "actions": actions,
            "reply": f"好的，已保留{excl_names}不变，并将其余 {len(actions)} 处{dev_noun}（{'、'.join(names[:3])}）{'关闭' if wants_off else '开启'}。",
            "explanation": f"排除{excl_names}后批量控制其余 {len(actions)} 处{dev_noun}。",
        }

    def _split_compound_clauses(self, raw_t: str) -> list[str]:
        parts = [p.strip() for p in re.split(r"[，,；;]|并且|同时|顺便|然后|再把", raw_t) if p.strip()]
        if len(parts) <= 1:
            return [raw_t]
        # Only treat as multi-clause if at least 2 parts look like actionable clauses
        valid = [p for p in parts if self._has_action_verb(p) or any(k in p for k in ("度", "%", "光", "模式", "风"))]
        return parts if len(valid) >= 2 else [raw_t]

    def _execute_compound_clauses(self, clauses: list[str], plan: dict, climate: dict,
                                  session: dict, active_room: str | None, types_map: dict) -> dict | None:
        combined_actions: list[dict] = []
        replies: list[str] = []
        carry_rooms: list[dict] = []

        for cl in clauses:
            rms = self._extract_rooms(cl, plan, include_restricted=False)
            if rms:
                carry_rooms = rms
            elif carry_rooms and not any(w in cl for w in UNIVERSAL_WORDS):
                dtypes, _ = self._extract_device_types(cl, types_map)
                chosen = carry_rooms[0]
                if dtypes:
                    for cr in carry_rooms:
                        if any(it["type"] in dtypes and (room_for_item(plan, it) or {}).get("id") == cr["id"] for it in plan["items"]):
                            chosen = cr
                            break
                cl = chosen["name"] + cl

            sub = self._parse_single_clause(cl, plan, climate, session, active_room, types_map)
            if sub and sub.get("actions"):
                combined_actions.extend(sub["actions"])
                r_txt = sub.get("reply", "").removeprefix("好的，").rstrip("。")
                if r_txt:
                    replies.append(r_txt)

        if not combined_actions:
            return None
        reply_joined = "好的，" + "，并".join(replies) + "。"
        return {
            "matched": True,
            "high_risk": False,
            "actions": combined_actions,
            "reply": reply_joined,
            "explanation": f"复合多子句指令拆解执行：{reply_joined}",
        }

    def _handle_status_query(self, t: str, plan: dict, climate: dict,
                             explicit_rooms: list[dict], active_room: str | None) -> dict:
        target_room = explicit_rooms[0] if explicit_rooms else None

        # Scene / Mode query
        if any(w in t for w in ("什么模式", "哪个模式", "什么场景", "睡眠锁", "免打扰")):
            dnd_rooms = [r["name"] for r in plan["rooms"] if r.get("sleep") and not r.get("restricted")]
            dnd_str = f"，当前开启睡眠免打扰的房间有：{'、'.join(dnd_rooms)}" if dnd_rooms else ""
            return {
                "matched": True, "query_only": True, "actions": [], "cards": [],
                "reply": f"家庭系统运行正常{dnd_str}。",
                "explanation": "查询场景与分域免打扰状态。",
            }

        # Temperature / Humidity / Lux query (with live per-room micro-climate!)
        if any(w in t for w in ("度", "温", "湿", "热吗", "冷吗", "热不热", "冷不冷", "潮不潮", "闷不闷", "照度", "亮不亮")):
            indoor = float(climate.get("indoor", 26.0))
            hum = int(climate.get("humidity", 55))
            lux = int(climate.get("lux", 120))
            if target_room:
                room_envs = {
                    e["room_id"]: e
                    for e in compute_room_environments({"plan": plan, "climate": climate, "occupied": {}})
                }
                r_env = room_envs.get(target_room["id"])
                if r_env:
                    indoor = r_env["temp_c"]
                    hum = r_env["humidity_pct"]
                    lux = r_env["lux"]
            r_prefix = target_room["name"] if target_room else "室内"
            acs = [it for it in plan["items"] if it["type"] == "ac"
                   and not (room_for_item(plan, it) or {}).get("restricted")
                   and (not target_room or (room_for_item(plan, it) or {}).get("id") == target_room["id"])]
            cards = [format_device_card(plan, acs[0])] if acs else []
            if "照度" in t or "亮不亮" in t:
                return {
                    "matched": True, "query_only": True, "actions": [], "cards": [],
                    "reply": f"{r_prefix}当前环境照度约 {lux} lx。",
                    "explanation": f"环境照度查询：{lux} lx。",
                }
            ac_note = f"，{acs[0]['name']}正在以 {acs[0].get('target', 26)}°C 运行" if (acs and acs[0].get("power")) else ""
            return {
                "matched": True, "query_only": True, "actions": [], "cards": cards,
                "reply": f"{r_prefix}目前 {indoor:.1f}°C，相对湿度 {hum}%{ac_note}。",
                "explanation": f"状态查询：{indoor:.1f}°C / 湿度 {hum}%。",
            }

        vis_items = [
            it for it in plan["items"]
            if it["type"] in ("lamp", "switch", "ac", "curtain")
            and not (room_for_item(plan, it) or {}).get("restricted")
            and (not target_room or (room_for_item(plan, it) or {}).get("id") == target_room["id"])
        ]

        if "灯" in t:
            lamps = [it for it in vis_items if it["type"] in ("lamp", "switch")]
            on_lamps = [it for it in lamps if it.get("power")]
            if target_room and lamps:
                lp = lamps[0]
                st = f"是开着的（亮度 {lp.get('level', 65)}%）" if lp.get("power") else "是关闭的"
                return {
                    "matched": True, "query_only": True, "actions": [],
                    "cards": [format_device_card(plan, lp)],
                    "reply": f"{lp['name']}目前{st}。",
                    "explanation": f"查询{lp['name']}状态。",
                }
            if not on_lamps:
                return {
                    "matched": True, "query_only": True, "actions": [], "cards": [],
                    "reply": "目前家里的灯都已经关闭了。",
                    "explanation": "全屋照明查询：0 盏开启。",
                }
            names = "、".join(f"{x['name']}（{x.get('level', 65)}%）" for x in on_lamps[:4])
            return {
                "matched": True, "query_only": True, "actions": [],
                "cards": [format_device_card(plan, x) for x in on_lamps[:3]],
                "options": [{"label": "全部关掉", "text": "关掉所有灯"}],
                "reply": f"目前有 {len(on_lamps)} 盏灯开着：{names}。",
                "explanation": f"全屋照明查询：{len(on_lamps)} 盏开启。",
            }

        if "空调" in t:
            acs = [it for it in vis_items if it["type"] == "ac"]
            on_acs = [it for it in acs if it.get("power")]
            if target_room and acs:
                ac = acs[0]
                st = f"正在运行（{ac.get('mode', '制冷')} {ac.get('target', 26)}°C）" if ac.get("power") else "处于关闭状态"
                return {
                    "matched": True, "query_only": True, "actions": [],
                    "cards": [format_device_card(plan, ac)],
                    "reply": f"{ac['name']}目前{st}。",
                    "explanation": f"查询{ac['name']}状态。",
                }
            if not on_acs:
                return {
                    "matched": True, "query_only": True, "actions": [], "cards": [],
                    "reply": "目前家里的空调都是关闭的。",
                    "explanation": "全屋空调查询：0 台开启。",
                }
            names = "、".join(f"{x['name']}（{x.get('target', 26)}°C）" for x in on_acs[:3])
            return {
                "matched": True, "query_only": True, "actions": [],
                "cards": [format_device_card(plan, x) for x in on_acs[:3]],
                "reply": f"目前有 {len(on_acs)} 台空调开着：{names}。",
                "explanation": f"全屋空调查询：{len(on_acs)} 台开启。",
            }

        running = [it for it in vis_items if self._item_is_active(it)]
        if not running:
            return {
                "matched": True, "query_only": True, "actions": [], "cards": [],
                "reply": "目前家里没有正在运行的灯光或空调。",
                "explanation": "全屋设备状态检查：全部待机。",
            }
        names = "、".join(x["name"] for x in running[:4])
        return {
            "matched": True, "query_only": True, "actions": [],
            "cards": [format_device_card(plan, x) for x in running[:3]],
            "reply": f"目前共有 {len(running)} 处设备开启：{names}。",
            "explanation": f"全屋设备状态检查：{len(running)} 处开启。",
        }

    # --------------------------------------------------------------------------
    # Lexical Match Utilities
    # --------------------------------------------------------------------------
    @staticmethod
    def _extract_rooms(t: str, plan: dict, include_restricted: bool = False) -> list[dict]:
        found: list[tuple[int, dict]] = []
        seen: set[str] = set()
        for r in plan["rooms"]:
            if not include_restricted and r.get("restricted"):
                continue
            pos = t.find(r["name"])
            if pos >= 0 and r["id"] not in seen:
                found.append((pos, r))
                seen.add(r["id"])
        for words, rids in ROOM_SYNONYMS:
            hit_positions = [t.find(w) for w in words if w in t]
            if hit_positions:
                pos = min(hit_positions)
                for r in plan["rooms"]:
                    if not include_restricted and r.get("restricted"):
                        continue
                    if r["id"] in rids and r["id"] not in seen:
                        found.append((pos, r))
                        seen.add(r["id"])
                        break
        found.sort(key=lambda pair: pair[0])
        return [r for _, r in found]

    @staticmethod
    def _replace_room_word_with_slot(raw_t: str) -> str:
        for words, _ in ROOM_SYNONYMS:
            for w in sorted(words, key=len, reverse=True):
                if w in raw_t:
                    return raw_t.replace(w, "{room}", 1)
        return raw_t

    @staticmethod
    def _find_explicit_item(t: str, plan: dict) -> dict | None:
        # Match full item names sorted longest-first (e.g. "客厅阳台窗帘", "过厅灯", "客厅灯")
        candidates = sorted(
            [it for it in plan["items"] if not (room_for_item(plan, it) or {}).get("restricted")],
            key=lambda x: len(x.get("name", "")),
            reverse=True,
        )
        for it in candidates:
            if len(it.get("name", "")) >= 2 and it["name"] in t:
                return it
        return None

    @staticmethod
    def _extract_device_types(t: str, types_map: dict) -> tuple[tuple[str, ...] | None, str]:
        for words, dtypes, noun in DEVICE_SYNONYMS:
            if any(w in t for w in words):
                return dtypes, noun
        for code, spec in types_map.items():
            if code in ("lamp", "ac", "curtain", "switch", "sensor", "sofa", "table", "bed", "desk"):
                continue
            sname = spec.get("name", "")
            if sname and sname in t:
                return (code,), sname
        return None, ""

    @staticmethod
    def _is_controllable(it: dict, types_map: dict) -> bool:
        if it["type"] in ("lamp", "ac", "curtain", "switch"):
            return True
        return bool(types_map.get(it["type"], {}).get("caps"))

    @staticmethod
    def _item_is_active(it: dict) -> bool:
        if "power" in it:
            return bool(it.get("power"))
        if it.get("type") == "curtain":
            return int(it.get("position", 0)) > 5
        return False

    @staticmethod
    def _has_action_verb(t: str) -> bool:
        return any(w in t for w in (
            "开", "关", "熄", "亮", "灭", "调", "设", "改", "换", "拉", "合", "升", "降", "加", "减"
        ))

    def _has_action_or_query_verb(self, t: str) -> bool:
        return self._has_action_verb(t) or self._is_status_question(t) or bool(self._match_scene_intent(t))

    @staticmethod
    def _is_status_question(t: str) -> bool:
        if is_interrogative_sentence(t):
            return True
        has_q = any(q in t for q in (
            "多少度", "几度", "湿度多少", "温度多少", "照度", "开了吗", "关了吗", "开着吗", "关着吗",
            "没关", "哪些", "什么灯", "什么设备", "什么电器", "什么模式", "哪个模式", "热吗", "冷吗",
            "热不热", "冷不冷", "亮不亮", "状态", "检查一下"
        ))
        has_imperative = any(w in t for w in ("调到", "设为", "调高", "调低", "调亮", "调暗", "帮我开", "帮我关", "请打开", "请关闭", "麻烦把"))
        return has_q and not has_imperative

    @staticmethod
    def _match_scene_intent(t: str) -> dict | None:
        if any(w in t for w in ("回家模式", "我回来了", "到家了", "刚到家", "开启回家")):
            return {
                "matched": True, "scene": "home", "actions": [],
                "reply": "欢迎回家，已为你开启回家场景。",
                "explanation": "命中场景槽位：触发「回家模式」并执行当季动态温控。",
            }
        if any(w in t for w in ("离家模式", "我出门了", "出门了", "我要走了", "上班去了", "全员外出", "开启离家")):
            return {
                "matched": True, "scene": "away", "actions": [],
                "reply": "好的，已切换为离家模式，家中非必要设备已关闭。",
                "explanation": "命中场景槽位：触发「离家模式」。",
            }
        if any(w in t for w in ("睡眠模式", "我要睡了", "准备睡了", "睡觉了", "晚安", "开启睡眠", "分域睡眠")):
            return {
                "matched": True, "scene": "sleep", "actions": [],
                "reply": "晚安，睡眠模式已开启，卧室已设为免打扰。",
                "explanation": "命中场景槽位：触发「分域睡眠模式」。",
            }
        if any(w in t for w in ("日常模式", "恢复日常", "退出睡眠", "起床了", "早上好", "早安")):
            return {
                "matched": True, "scene": "normal", "actions": [],
                "reply": "早安，已切回日常模式。" if any(w in t for w in ("早", "起床")) else "好的，已切回日常模式。",
                "explanation": "命中场景槽位：恢复「日常模式」。",
            }
        return None

    @staticmethod
    def _rbac_denied_reply() -> dict:
        return {
            "matched": True, "query_only": True, "actions": [], "cards": [],
            "reply": "抱歉，当前访客身份无权查看或控制私密卧室区域。",
            "explanation": "空间级 RBAC 拦截：访客无权操作私密睡眠域。",
        }


# ------------------------------------------------------------------------------
# Indoor Room Camera Visual Analysis & Local Home Hub VLM Gateway
# ------------------------------------------------------------------------------
def analyze_frame_luminance(camera_b64: str | None) -> dict | None:
    """Compute center-weighted indoor luminance from a room-interior camera frame."""
    if not camera_b64 or not isinstance(camera_b64, str):
        return None
    try:
        payload = camera_b64.split(",", 1)[-1]
        raw = base64.b64decode(payload)
        with Image.open(io.BytesIO(raw)) as img:
            rgb = img.convert("RGB").resize((64, 64))
            pixels = list(rgb.getdata())
            total_w = 0.0
            weighted_luma = 0.0
            for idx, (r, g, b) in enumerate(pixels):
                x, y = idx % 64, idx // 64
                w = 1.35 if (12 <= x <= 52 and 16 <= y <= 58) else 0.75
                lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
                weighted_luma += lum * w
                total_w += w
            luma = round(weighted_luma / max(1.0, total_w), 1)
            return {
                "luma_0_255": luma,
                "perceived": "偏暗" if luma < 112 else ("适中" if luma < 178 else "明亮"),
                "size": f"{img.width}x{img.height}",
            }
    except Exception:
        return None


class EdgeVisualButlerProvider:
    """Local Edge Home Hub VLM adapter (calls `HOME_VLM_BASE_URL` if configured,
    otherwise uses indoor room-camera pixel analysis + spatial-context reasoning)."""

    def infer_multimodal(self, text: str, plan: dict, climate: dict,
                         camera_b64: str | None, camera_room: str | None,
                         focus: dict) -> dict:
        base_url = os.environ.get("HOME_VLM_BASE_URL", "").strip()
        if base_url:
            res = self._call_openai_compatible(base_url, text, plan, climate, camera_b64, camera_room)
            if res is not None:
                return res

        vis = analyze_frame_luminance(camera_b64)
        rooms_by_id = {r["id"]: r for r in plan["rooms"] if not r.get("restricted")}
        target_room = rooms_by_id.get(camera_room or "") or rooms_by_id.get(focus.get("room_id", ""))
        if not target_room:
            for r in plan["rooms"]:
                if not r.get("restricted") and r["name"] in text:
                    target_room = r
                    break
        if not target_room:
            for words, rids in ROOM_SYNONYMS:
                if any(w in text for w in words):
                    target_room = next((r for r in plan["rooms"] if not r.get("restricted") and r["id"] in rids), None)
                    if target_room:
                        break
        if not target_room and plan["rooms"]:
            target_room = next((r for r in plan["rooms"] if r["id"] in ("living", "study", "bed3")), plan["rooms"][0])

        rname = target_room["name"] if target_room else "客厅"
        rid = target_room["id"] if target_room else None

        room_lamps = [it for it in plan["items"] if it["type"] in ("lamp", "switch")
                      and (not rid or (room_for_item(plan, it) or {}).get("id") == rid)]
        if not room_lamps:
            room_lamps = [it for it in plan["items"] if it["type"] in ("lamp", "switch")][:1]

        room_acs = [it for it in plan["items"] if it["type"] == "ac"
                    and (not rid or (room_for_item(plan, it) or {}).get("id") == rid)]
        if not room_acs:
            room_acs = [it for it in plan["items"] if it["type"] == "ac"][:1]

        actions: list[dict] = []
        reasons: list[str] = []
        spoken_parts: list[str] = []

        if vis:
            reasons.append(f"视觉帧像素解析（{rname}室内摄像头平均亮度 {vis['luma_0_255']}/255，光线{vis['perceived']}）")

        pure_inspect = vis and any(w in text for w in ("关了没", "关了吗", "开了吗", "开着吗", "怎么样")) and not any(w in text for w in ("太暗", "有点暗", "调", "帮我开", "帮我关"))
        if pure_inspect and room_lamps:
            lp = room_lamps[0]
            if lp.get("power"):
                reply_txt = f"从{rname}室内镜头看，室内光线{vis['perceived']}，{lp['name']}目前开着（亮度 {lp.get('level', 65)}%）。"
                opts = [{"label": f"关掉{lp['name']}", "text": f"关掉{lp['name']}"}]
            else:
                reply_txt = f"从{rname}室内镜头看，目前室内光线{vis['perceived']}，{lp['name']}已关闭。"
                opts = [{"label": f"打开{lp['name']}", "text": f"打开{lp['name']}"}]
            return {
                "query_only": True,
                "actions": [],
                "cards": [format_device_card(plan, lp)],
                "options": opts,
                "camera_summary": {"room": rname, **vis},
                "focus_update": {"room_id": rid, "device_id": lp["id"]},
                "reply": reply_txt,
                "explanation": "；".join(reasons) + "：" + reply_txt,
            }

        wants_off = any(w in text for w in ("关灯", "关掉", "关闭", "太亮了关"))
        wants_dim = any(w in text for w in ("刺眼", "太亮", "休息", "看电影", "观影", "柔和", "暗一点")) and not wants_off
        wants_climate = any(w in text for w in ("冷", "热", "闷", "潮", "舒服", "温度", "空调"))
        wants_light = any(w in text for w in ("暗", "看书", "阅读", "工作", "看不清", "灯", "亮", "补光", "你看", "看看", "画面"))

        if wants_off and room_lamps:
            lp = room_lamps[0]
            actions.append({"deviceId": lp["id"], "capability": "power", "value": False})
            spoken_parts.append(f"已为你关闭{lp['name']}")
            reasons.append(f"关闭「{lp['name']}」")
        elif wants_dim and room_lamps:
            lp = room_lamps[0]
            actions.append({"deviceId": lp["id"], "capability": "power", "value": True})
            if lp["type"] == "lamp":
                actions.append({"deviceId": lp["id"], "capability": "level", "value": 30})
                if "color_temp" in lp:
                    actions.append({"deviceId": lp["id"], "capability": "color_temp", "value": "暖白"})
            spoken_parts.append(f"已将{lp['name']}调柔和至 30% 暖白光")
            reasons.append(f"将「{lp['name']}」调至 30% 暖白柔光")
        elif (wants_light or (vis and not wants_climate)) and room_lamps:
            lp = room_lamps[0]
            is_bright_already = vis and vis["luma_0_255"] >= 168 and lp.get("power") and int(lp.get("level", 0)) >= 75 and "亮" not in text and "看书" not in text
            if is_bright_already:
                return {
                    "query_only": True,
                    "actions": [],
                    "cards": [format_device_card(plan, lp)],
                    "camera_summary": {"room": rname, **vis} if vis else None,
                    "focus_update": {"room_id": rid, "device_id": lp["id"]},
                    "reply": f"从{rname}室内画面看目前光线充足，{lp['name']}已处于 {lp.get('level', 75)}% 照明状态。",
                    "explanation": "；".join(reasons) + "，当前照明充足无需额外补光。",
                }
            rec_lvl = 85 if ("看书" in text or "工作" in text or rid in ("study", "bed3")) else 80
            ct = "自然光" if ("看书" in text or rid in ("study", "bed3")) else "暖白"
            actions.append({"deviceId": lp["id"], "capability": "power", "value": True})
            if lp["type"] == "lamp":
                actions.append({"deviceId": lp["id"], "capability": "level", "value": rec_lvl})
                if "color_temp" in lp:
                    actions.append({"deviceId": lp["id"], "capability": "color_temp", "value": ct})
            prefix = f"从{rname}室内镜头看光线偏暗，" if (vis and vis["luma_0_255"] < 125) else f"结合{rname}当前光线，"
            spoken_parts.append(f"{prefix}已为你打开{lp['name']}并调至 {rec_lvl}%")
            reasons.append(f"开启「{lp['name']}」并调至 {rec_lvl}% {ct}")

        if wants_climate and room_acs:
            ac = room_acs[0]
            season = climate.get("season", "夏")
            hum = int(climate.get("humidity", 60))
            if "冷" in text:
                new_t = min(28, round(float(ac.get("target", 25)) + 2))
                actions.extend([
                    {"deviceId": ac["id"], "capability": "power", "value": True},
                    {"deviceId": ac["id"], "capability": "target", "value": new_t},
                ])
                spoken_parts.append(f"已将{ac['name']}调高至 {new_t}°C")
                reasons.append(f"上调「{ac['name']}」至 {new_t}°C")
            elif hum > 75 and ("潮" in text or "闷" in text):
                actions.extend([
                    {"deviceId": ac["id"], "capability": "power", "value": True},
                    {"deviceId": ac["id"], "capability": "mode", "value": "除湿"},
                    {"deviceId": ac["id"], "capability": "target", "value": 24},
                ])
                spoken_parts.append(f"室内湿度偏高，已开启{ac['name']}除湿模式")
                reasons.append(f"开启「{ac['name']}」除湿模式")
            else:
                rec_t = 25 if season == "夏" else 21
                rec_m = "制冷" if season == "夏" else "制热"
                actions.extend([
                    {"deviceId": ac["id"], "capability": "power", "value": True},
                    {"deviceId": ac["id"], "capability": "mode", "value": rec_m},
                    {"deviceId": ac["id"], "capability": "target", "value": rec_t},
                ])
                spoken_parts.append(f"已开启{ac['name']}（{rec_m} {rec_t}°C）")
                reasons.append(f"将「{ac['name']}」设为 {rec_m} {rec_t}°C")

        if not actions and room_lamps:
            lp = room_lamps[0]
            next_on = not bool(lp.get("power"))
            actions.append({"deviceId": lp["id"], "capability": "power", "value": next_on})
            spoken_parts.append(f"已为你{'打开' if next_on else '关闭'}{lp['name']}")
            reasons.append(f"切换「{lp['name']}」状态")

        primary_dev = actions[0]["deviceId"] if actions else None
        reply_str = "，".join(spoken_parts) + "。"
        return {
            "actions": actions,
            "high_risk": False,
            "camera_summary": {"room": rname, **vis} if vis else None,
            "focus_update": {"room_id": rid, "device_id": primary_dev},
            "reply": reply_str,
            "explanation": "端侧家庭中枢多模态推理：" + "；".join(reasons) + "。",
        }

    @staticmethod
    def _call_openai_compatible(base_url: str, text: str, plan: dict, climate: dict,
                                camera_b64: str | None, camera_room: str | None) -> dict | None:
        api_key = os.environ.get("HOME_VLM_API_KEY", "ollama")
        model_name = os.environ.get("HOME_VLM_MODEL", "qwen2.5-vl")
        schema_items = [
            {"id": it["id"], "name": it["name"], "type": it["type"],
             "room": (room_for_item(plan, it) or {}).get("name", "")}
            for it in plan["items"] if it["type"] in ("lamp", "ac", "curtain", "switch")
        ]
        sys_prompt = (
            "你是运行在家庭本地边缘中枢的智能家居语音与视觉助手。请仅输出严格 JSON："
            '{"actions":[{"deviceId":"...","capability":"power|level|target|mode|position","value":...}],'
            '"reply":"简短自然的口语回复","explanation":"决策依据","high_risk":false}。'
            f"当前设备表：{json.dumps(schema_items, ensure_ascii=False)}；环境：{json.dumps(climate, ensure_ascii=False)}；"
            f"室内摄像头所在房间：{camera_room or '未知'}。"
        )
        user_content: list[dict] = [{"type": "text", "text": text}]
        if camera_b64:
            url_val = camera_b64 if camera_b64.startswith("data:") else f"data:image/jpeg;base64,{camera_b64}"
            user_content.append({"type": "image_url", "image_url": {"url": url_val}})

        req_body = json.dumps({
            "model": model_name,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,
        }).encode("utf-8")
        req = urllib.request.Request(
            base_url.rstrip("/") + "/chat/completions",
            data=req_body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=3.4) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
                content = raw["choices"][0]["message"]["content"]
                m = re.search(r"\{.*\}", content, re.S)
                if m:
                    return json.loads(m.group(0))
        except Exception:
            return None
        return None


# ------------------------------------------------------------------------------
# Unified Home Hub Router
# ------------------------------------------------------------------------------
class HomeHubButlerRouter:
    def __init__(self, control: ControlLayerService, strategy: StrategyEngine,
                 vlm_provider: ILlmProvider | None = None):
        self.control = control
        self.strategy = strategy
        self.slot_engine = IntentSlotEngine()
        self.vlm_provider = vlm_provider or EdgeVisualButlerProvider()
        self.harness = HomeAgentHarness(control, strategy, analyze_frame_luminance)
        self.sessions: dict[str, dict] = {}

    def handle_chat(self, key: str, m: dict, body: dict, role: str, session_key: str) -> dict:
        t0 = time.perf_counter()
        text = str(body.get("text", "")).strip()
        camera_b64 = body.get("camera_frame")
        camera_room = body.get("camera_room")
        active_room = body.get("active_room")
        router_mode = body.get("router_mode", "auto")

        if not text and not camera_b64:
            raise Problem("请输入语音指令或点击相机附带室内画面。")

        session = self.sessions.setdefault(
            session_key,
            {"room_id": None, "device_id": None, "focus_ts": 0.0, "pending_intent": None, "last_template": None},
        )
        # Project visible plan for RBAC role so guest cannot see private bedrooms!
        vis_plan = self.control.project_snapshot(key, role)["plan"]
        # Sync live item states from `m["plan"]` onto `vis_plan`
        live_by_id = {it["id"]: it for it in m["plan"]["items"]}
        for it in vis_plan["items"]:
            if it["id"] in live_by_id:
                it.update(live_by_id[it["id"]])

        types_map = self.control.repo.read_types()

        if router_mode == "inject_hallucination":
            ac = next((x for x in m["plan"]["items"] if x["type"] == "ac"), m["plan"]["items"][0])
            hallucinated = [{"deviceId": ac["id"], "capability": "target", "value": 45}]
            self.control.execute_action_batch(key, m, hallucinated, role, source="local_vlm", reason="幻觉注入测试")

        # Spatial RBAC guard before multi-step or single-step execution
        mentioned_all = self.slot_engine._extract_rooms(text, vis_plan, include_restricted=True)
        if mentioned_all and any(r.get("restricted") for r in mentioned_all):
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            den = self.slot_engine._rbac_denied_reply()
            return {
                "tier_used": "slot_engine",
                "latency_ms": elapsed_ms,
                "requires_confirm": False,
                "applied": [],
                "cards": [],
                "reply": den["reply"],
                "explanation": den["explanation"],
            }

        # Path 1: Bounded Multi-Step Smart Home Agent Harness (`HomeAgentHarness`)
        has_pending = bool(session.get("pending_intent")) and (time.time() - session["pending_intent"].get("ts", 0) < 120.0)
        is_cancel = any(text == w or text.startswith(w) for w in CANCEL_WORDS)
        if not has_pending and not is_cancel and router_mode != "force_offline" and needs_agent_harness(text):
            h_res = self.harness.run(
                key, m, vis_plan, text, role,
                camera_b64=camera_b64,
                camera_room=camera_room,
                room_Normalizer=self.slot_engine._extract_rooms,
            )
            if h_res is not None:
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
                by_id = {it["id"]: it for it in m["plan"]["items"]}
                cards = [format_device_card(m["plan"], by_id[did]) for did in h_res["touched_ids"] if did in by_id]
                if h_res["touched_ids"]:
                    last_did = h_res["touched_ids"][-1]
                    last_rm = room_for_item(m["plan"], by_id[last_did]) if last_did in by_id else None
                    session["device_id"] = last_did
                    session["room_id"] = last_rm["id"] if last_rm else session.get("room_id")
                    session["focus_ts"] = time.time()
                m["last_explanation"] = h_res["explanation"]
                self.control.repo.write_model(key, m)
                return {
                    "tier_used": "home_harness",
                    "latency_ms": elapsed_ms,
                    "requires_confirm": False,
                    "applied": h_res["actions_applied"],
                    "cards": cards,
                    "trace": h_res["trace"],
                    "focus": {"room_id": session.get("room_id"), "device_id": session.get("device_id")},
                    "reply": h_res["reply"],
                    "explanation": h_res["explanation"],
                }

        has_visual = bool(camera_b64)
        vlm_configured = bool(os.environ.get("HOME_VLM_BASE_URL", "").strip())
        tier_used = "slot_engine"
        parsed = None

        if not has_visual and router_mode != "force_vlm":
            parsed = self.slot_engine.parse(
                text, vis_plan, m["climate"], session,
                active_room=active_room,
                allow_fuzzy=(not vlm_configured or router_mode == "force_offline"),
                device_types=types_map,
            )
            if parsed and router_mode == "force_offline":
                tier_used = "fallback"

        if parsed is None:
            if router_mode == "force_offline":
                tier_used = "fallback"
                parsed = self.slot_engine.parse(
                    text, vis_plan, m["climate"], session,
                    active_room=active_room, allow_fuzzy=True, device_types=types_map
                )
            elif has_visual or vlm_configured:
                tier_used = "local_vlm"
                parsed = self.vlm_provider.infer_multimodal(text, vis_plan, m["climate"], camera_b64, camera_room, session)

        if parsed is None:
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            return {
                "tier_used": "fallback",
                "latency_ms": elapsed_ms,
                "requires_confirm": False,
                "applied": [],
                "cards": [],
                "options": [
                    {"label": "打开客厅灯", "text": "打开客厅灯"},
                    {"label": "客厅空调 25 度", "text": "把客厅空调调到 25 度"},
                    {"label": "哪些灯还开着", "text": "哪些灯还开着"},
                ],
                "reply": "抱歉，我没能理解这个指令。你可以试试说“关掉客厅灯”、“把主卧空调调到 25 度”或“家里现在多少度”。",
                "explanation": "未命中控制或查询语法，返回语音引导建议。",
            }

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

        if parsed.get("query_only"):
            if parsed.get("focus_update"):
                session.update({k: v for k, v in parsed["focus_update"].items() if v})
                session["focus_ts"] = time.time()
            return {
                "tier_used": tier_used,
                "latency_ms": elapsed_ms,
                "requires_confirm": False,
                "applied": [],
                "cards": parsed.get("cards", []),
                "options": parsed.get("options", []),
                "camera_summary": parsed.get("camera_summary"),
                "reply": parsed.get("reply", ""),
                "explanation": parsed.get("explanation", ""),
            }

        if parsed.get("override_op"):
            op_kind, rid_val = parsed["override_op"]
            env_body = {"release_override": rid_val} if op_kind == "release" else {"hold_override": rid_val}
            self.strategy.update_environment(key, m, env_body)
            return {
                "tier_used": tier_used,
                "latency_ms": elapsed_ms,
                "requires_confirm": False,
                "applied": [{"name": "控制权移交", "capability": op_kind, "value": rid_val}],
                "cards": [],
                "reply": parsed.get("reply", ""),
                "explanation": parsed.get("explanation", ""),
            }

        if parsed.get("scene"):
            s_res = self.strategy.trigger_scene(key, m, parsed["scene"], role=role)
            return {
                "tier_used": tier_used,
                "latency_ms": elapsed_ms,
                "requires_confirm": False,
                "applied": [{"name": f"场景：{parsed['scene']}", "capability": "scene", "value": parsed["scene"]}],
                "cards": [],
                "reply": parsed.get("reply") or s_res["explanation"],
                "explanation": f"{parsed['explanation']} {s_res['explanation']}",
            }

        actions = parsed.get("actions", [])
        explanation = parsed.get("explanation", "已完成意图解析。")
        reply_text = parsed.get("reply") or explanation

        if parsed.get("high_risk"):
            tok = self.control.create_confirm_token(key, actions, explanation, tier_used)
            return {
                "tier_used": tier_used,
                "latency_ms": elapsed_ms,
                "requires_confirm": True,
                "confirm_token": tok,
                "proposed_actions": actions,
                "cards": [],
                "reply": reply_text,
                "explanation": explanation,
            }

        applied = self.control.execute_action_batch(
            key, m, actions, role=role, source=tier_used,
            reason="确定性槽位引擎" if tier_used in ("slot_engine", "fallback") else "端侧多模态中枢"
        )
        if parsed.get("focus_update"):
            session.update({k: v for k, v in parsed["focus_update"].items() if v})
            session["focus_ts"] = time.time()

        touched_ids = []
        for a in actions:
            did = a.get("deviceId")
            if did and did not in touched_ids:
                touched_ids.append(did)
        by_id = {it["id"]: it for it in m["plan"]["items"]}
        cards = [format_device_card(m["plan"], by_id[did]) for did in touched_ids if did in by_id]

        m["last_explanation"] = explanation
        self.control.repo.write_model(key, m)
        return {
            "tier_used": tier_used,
            "latency_ms": elapsed_ms,
            "requires_confirm": False,
            "applied": applied,
            "cards": cards,
            "camera_summary": parsed.get("camera_summary"),
            "focus": {"room_id": session.get("room_id"), "device_id": session.get("device_id")},
            "reply": reply_text,
            "explanation": explanation,
        }
