# -*- coding: utf-8 -*-
"""Automated End-to-End Verification Suite covering RTM Test Cases TC01–TC14."""
from __future__ import annotations

import ast
import base64
import io
from pathlib import Path
import sys
import tempfile
import time
import unittest

from PIL import Image

DEMO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO_ROOT))

from backend.api.http_server import SmartHomeApp
from backend.common import Problem


class TestSmartHomeRTM(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test_home.sqlite3"
        self.app = SmartHomeApp(root=DEMO_ROOT, db_path=self.db_path)

    def tearDown(self) -> None:
        self.app.repo.db.close()
        self.tmp.cleanup()

    def test_tc01_tc02_asset_crud_csv_atomic_rollback_and_ref_integrity(self) -> None:
        ctrl = self.app.control_layer
        strat = self.app.strategy_layer
        with self.app.repo.lock, self.app.repo.db:
            csv_out = ctrl.export_items_csv("apartment", "admin")
            self.assertIn("living-lamp", csv_out)

            # Dirty CSV row #3 (out of bounds x=99999) must roll back entire batch!
            m_before = self.app.repo.read_model("apartment")
            count_before = len(m_before["plan"]["items"])
            bad_csv = "id,name,type,x,y\ngood-1,新台灯,lamp,300,200\nbad-2,越界灯,lamp,99999,200\n"
            with self.assertRaises(Problem) as ctx:
                ctrl.import_items_batch("apartment", m_before, {"format": "csv", "content": bad_csv}, "admin")
            self.assertIn("第 3 行校验失败", str(ctx.exception))
            m_after = self.app.repo.read_model("apartment")
            self.assertEqual(len(m_after["plan"]["items"]), count_before)

            # Valid CSV batch import succeeds atomically
            ok_csv = "id,name,type,x,y,power,level\nstudy-aux,书房辅灯,lamp,850,420,true,70\n"
            imported = ctrl.import_items_batch("apartment", m_after, {"format": "csv", "content": ok_csv}, "admin")
            self.assertEqual(imported, 1)

            # Referential integrity: create scene referencing study-aux, then try deleting without force -> 409!
            strat.upsert_scene("apartment", {
                "id": "study_focus",
                "name": "专注模式",
                "actions": [{"deviceId": "study-aux", "capability": "power", "value": True}]
            }, "admin")
            m_cur = self.app.repo.read_model("apartment")
            with self.assertRaises(Problem) as del_ctx:
                ctrl.remove_device("apartment", m_cur, "study-aux", "admin", force=False)
            self.assertEqual(del_ctx.exception.status, 409)

    def test_tc03_dynamic_device_type_registration_ocp(self) -> None:
        with self.app.repo.lock, self.app.repo.db:
            self.app.device_layer.register_type({
                "code": "dehumidifier",
                "name": "智能新风除湿机",
                "w": 45, "h": 40,
                "capabilities": [
                    {"key": "power", "label": "开关", "kind": "bool", "default": False},
                    {"key": "target_rh", "label": "目标湿度", "kind": "range", "min": 35, "max": 75, "unit": "%"},
                ]
            })
            types = self.app.device_layer.get_types()
            self.assertIn("dehumidifier", types)
            # Add an instance via batch import and control its custom capability!
            m = self.app.repo.read_model("apartment")
            self.app.control_layer.import_items_batch(
                "apartment", m,
                {"format": "csv", "content": "id,name,type,x,y\ndehum-1,客厅除湿机,dehumidifier,420,300\n"},
                "admin"
            )
            m = self.app.repo.read_model("apartment")
            res = self.app.control_layer.dispatch_command(
                "apartment", m, "dehum-1", {"capability": "target_rh", "value": 50}, role="admin"
            )
            self.assertEqual(res["result"], "ok")
            self.assertEqual(res["item"]["target_rh"], 50)

    def test_tc04_tc05_tc06_layout_mutex_and_async_faults(self) -> None:
        ctrl = self.app.control_layer
        with self.app.repo.lock, self.app.repo.db:
            # Blank custom floorplan build & persistence
            m_cust = self.app.repo.read_model("custom")
            new_plan = {
                **m_cust["plan"],
                "rooms": [{"id": "r1", "name": "自建客厅", "zone": "public", "p": [[20, 20], [420, 20], [420, 320], [20, 320]], "tag": [220, 60]}],
                "walls": [{"a": [20, 20], "b": [420, 20]}],
                "items": [{"id": "c-lamp", "name": "自建灯", "type": "lamp", "x": 180, "y": 160, "w": 36, "h": 36, "angle": 0}],
            }
            ctrl.replace_plan("custom", m_cust, {"plan": new_plan, "rev": m_cust["rev"]}, "admin")
            reloaded = self.app.repo.read_model("custom")
            self.assertEqual(len(reloaded["plan"]["items"]), 1)

            # Cross-attribute mutex: AC in '送风' mode locks 'target' temperature!
            m_apt = self.app.repo.read_model("apartment")
            ctrl.dispatch_command("apartment", m_apt, "living-ac", {"capability": "mode", "value": "送风"}, "admin")
            m_apt = self.app.repo.read_model("apartment")
            with self.assertRaises(Problem) as mutex_ctx:
                ctrl.dispatch_command("apartment", m_apt, "living-ac", {"capability": "target", "value": 23}, "admin")
            self.assertIn("锁定只读", str(mutex_ctx.exception))

            # Timeout & Offline fault injection preserve last confirmed Reported state!
            m_apt = self.app.repo.read_model("apartment")
            prev_lvl = next(x for x in m_apt["plan"]["items"] if x["id"] == "living-lamp")["level"]
            res_to = ctrl.dispatch_command("apartment", m_apt, "living-lamp", {"capability": "level", "value": 15, "outcome": "timeout"}, "admin")
            self.assertEqual(res_to["result"], "timeout")
            self.assertEqual(res_to["item"]["level"], prev_lvl)
            self.assertEqual(res_to["item"]["desired"]["level"], 15)

    def test_tc07_tc08_tc09_tc10_arbitration_climate_stale_and_anti_oscillation(self) -> None:
        strat = self.app.strategy_layer
        with self.app.repo.lock, self.app.repo.db:
            # TC07 + TC08: Home scene skips elder sleeping DND room & calculates summer hysteresis target
            m = self.app.repo.read_model("apartment")
            res_home = strat.trigger_scene("apartment", m, "home", "admin")
            self.assertIn("长辈次卧", res_home["skipped"])
            self.assertIn("滞回带", res_home["explanation"])

            # Spring + High Humidity (85%) conflict -> Dehumidify instead of natural ventilation!
            m = self.app.repo.read_model("apartment")
            strat.update_environment("apartment", m, {"climate": {"season": "春", "indoor": 23, "outdoor": 22, "humidity": 85}})
            m = self.app.repo.read_model("apartment")
            ac = next(x for x in m["plan"]["items"] if x["id"] == "living-ac")
            self.assertEqual(ac["mode"], "除湿")

            # TC09: Stale sensor fallback
            strat.update_environment("apartment", m, {"climate": {"season": "夏", "indoor": 39, "stale_sim": True}})
            m = self.app.repo.read_model("apartment")
            self.assertIn("传感陈旧降级告警", m["last_explanation"])

            # TC10: Anti-lux self-excitation! Study has low lux (90 lx) -> occupied turns lamp ON (level 75% -> adds lamp gain).
            # Even if total sensor lux rises to 190 lx because the lamp turned on, ambient_lux stays < 260 lx so lamp MUST NOT turn off!
            m = self.app.repo.read_model("apartment")
            strat.update_environment("apartment", m, {"climate": {"stale_sim": False, "lux": 90}, "room": "study", "occupied": True})
            m = self.app.repo.read_model("apartment")
            study_lamp = next(x for x in m["plan"]["items"] if x["id"] == "study-lamp")
            self.assertTrue(study_lamp["power"])
            strat.update_environment("apartment", m, {"climate": {"lux": 190}})
            m = self.app.repo.read_model("apartment")
            study_lamp_after = next(x for x in m["plan"]["items"] if x["id"] == "study-lamp")
            self.assertTrue(study_lamp_after["power"], "Lamp must not oscillate off from its own light gain!")

    def test_tc11_tc12_tc13_tc14_multimodal_butler_rbac_and_layers(self) -> None:
        butler = self.app.butler_router
        ctrl = self.app.control_layer
        with self.app.repo.lock, self.app.repo.db:
            # TC11: Deterministic IntentSlotEngine < 50ms + E4 multi-turn focus anaphora + status Q&A
            m = self.app.repo.read_model("apartment")
            r1 = butler.handle_chat("apartment", m, {"text": "把客厅空调调到二十五度"}, "admin", "sess-test")
            self.assertEqual(r1["tier_used"], "slot_engine")
            self.assertLess(r1["latency_ms"], 50.0)
            self.assertIn("25", r1["reply"])
            self.assertEqual(len(r1["cards"]), 1)

            m = self.app.repo.read_model("apartment")
            r2 = butler.handle_chat("apartment", m, {"text": "再调高 1.5 度"}, "admin", "sess-test")
            self.assertEqual(r2["tier_used"], "slot_engine")
            self.assertEqual(r2["applied"][-1]["value"], 26.5)

            m = self.app.repo.read_model("apartment")
            r_qa = butler.handle_chat("apartment", m, {"text": "客厅现在多少度"}, "admin", "sess-test")
            self.assertEqual(r_qa["applied"], [])
            self.assertIn("°C", r_qa["reply"])

            # Ambiguous bare commands ("开灯" / "关灯") ALWAYS clarify even when active_room or prior focus exists!
            m = self.app.repo.read_model("apartment")
            r_amb_on = butler.handle_chat("apartment", m, {"text": "开灯", "active_room": "living"}, "admin", "sess-test")
            self.assertEqual(r_amb_on["applied"], [])
            self.assertGreaterEqual(len(r_amb_on.get("options", [])), 2)

            # Turn on 2 lamps, then say bare "关灯": must ask which light AND support typing "客厅" on next turn!
            m = self.app.repo.read_model("apartment")
            butler.handle_chat("apartment", m, {"text": "打开客厅和书房的灯"}, "admin", "sess-clarify")
            m = self.app.repo.read_model("apartment")
            r_amb_off = butler.handle_chat("apartment", m, {"text": "关灯", "active_room": "living"}, "admin", "sess-clarify")
            self.assertEqual(r_amb_off["applied"], [])
            self.assertIn("关哪", r_amb_off["reply"])
            self.assertGreaterEqual(len(r_amb_off.get("options", [])), 2)

            # Complete pending slot by typing just the room name "书房"!
            m = self.app.repo.read_model("apartment")
            r_fill = butler.handle_chat("apartment", m, {"text": "书房"}, "admin", "sess-clarify")
            self.assertEqual(len(r_fill["applied"]), 1)
            self.assertFalse(r_fill["applied"][0]["value"])

            # Topic-switch ellipsis ("那客厅呢") + Negation guard ("别开书房灯") + Compound clause + Exclusion!
            m = self.app.repo.read_model("apartment")
            r_ell = butler.handle_chat("apartment", m, {"text": "那客厅呢"}, "admin", "sess-clarify")
            self.assertEqual(len(r_ell["applied"]), 1)
            self.assertFalse(r_ell["applied"][0]["value"])

            m = self.app.repo.read_model("apartment")
            r_neg = butler.handle_chat("apartment", m, {"text": "别打开书房灯"}, "admin", "sess-clarify")
            self.assertEqual(r_neg["applied"], [])

            m = self.app.repo.read_model("apartment")
            r_cmp = butler.handle_chat("apartment", m, {"text": "打开客厅和走廊的灯，顺便把空调调到24度"}, "admin", "sess-cmp")
            self.assertGreaterEqual(len(r_cmp["applied"]), 3)

            m = self.app.repo.read_model("apartment")
            r_exc = butler.handle_chat("apartment", m, {"text": "除了客厅，其他灯全关掉"}, "admin", "sess-cmp")
            self.assertEqual(len(r_exc["applied"]), 1)

            # TC12a: Multimodal Indoor Room Camera frame analysis (dark frame -> turns on study lamp!)
            dark_img = Image.new("RGB", (64, 64), (35, 38, 44))
            buf = io.BytesIO()
            dark_img.save(buf, format="JPEG")
            b64_frame = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

            m = self.app.repo.read_model("apartment")
            r_vlm = butler.handle_chat(
                "apartment", m,
                {"text": "你看我现在看书是不是太暗了？", "camera_frame": b64_frame, "camera_room": "study"},
                "admin", "sess-vlm"
            )
            self.assertEqual(r_vlm["tier_used"], "local_vlm")
            self.assertIn("视觉帧像素解析", r_vlm["explanation"])

            # TC12b: Offline fallback to IntentSlotEngine
            m = self.app.repo.read_model("apartment")
            r_fb = butler.handle_chat(
                "apartment", m,
                {"text": "打开客厅主灯", "router_mode": "force_offline"},
                "admin", "sess-fb"
            )
            self.assertIn(r_fb["tier_used"], ("slot_engine", "fallback"))

            # TC12c: Hallucination 45°C blocked by Control Layer Whitelist!
            m = self.app.repo.read_model("apartment")
            with self.assertRaises(Problem) as hal_ctx:
                butler.handle_chat("apartment", m, {"text": "调温", "router_mode": "inject_hallucination"}, "admin", "sess-hal")
            self.assertIn("白名单拦截", str(hal_ctx.exception))

            # TC12d: High-risk whole-home power-off requires secondary confirmToken
            m = self.app.repo.read_model("apartment")
            r_risk = butler.handle_chat("apartment", m, {"text": "把全屋所有电器都关掉"}, "admin", "sess-risk")
            self.assertTrue(r_risk["requires_confirm"])
            m = self.app.repo.read_model("apartment")
            c_res = ctrl.execute_confirmed_token("apartment", m, r_risk["confirm_token"], "admin")
            self.assertGreater(len(c_res["applied"]), 0)

            # TC13: Guest Spatial RBAC hides private bedrooms & blocks unauthorized control!
            snap_guest = ctrl.project_snapshot("apartment", "guest")
            guest_item_ids = {x["id"] for x in snap_guest["plan"]["items"]}
            self.assertNotIn("master-lamp", guest_item_ids)
            self.assertNotIn("elder-lamp", guest_item_ids)
            m = self.app.repo.read_model("apartment")
            with self.assertRaises(Problem) as rbac_ctx:
                ctrl.dispatch_command("apartment", m, "master-lamp", {"capability": "power", "value": True}, role="guest")
            self.assertEqual(rbac_ctx.exception.status, 403)

    def test_tc15_hassil_grammar_robustness_and_disambiguation_matrix(self) -> None:
        butler = self.app.butler_router
        with self.app.repo.lock, self.app.repo.db:
            # 1. Polite wrappers + BA / VO / Topic-Comment / Quantifier Chinese word-order matrix
            variants = [
                ("麻烦帮我把客厅主灯关一下好吗？", "living-lamp", "power", False),
                ("客厅灯打开吧谢谢", "living-lamp", "power", True),
                ("劳驾关掉客厅的灯", "living-lamp", "power", False),
                ("能不能帮我把客厅灯开启好不好", "living-lamp", "power", True),
                ("把客厅灯调到八成", "living-lamp", "level", 80),
                ("客厅主灯亮度一半", "living-lamp", "level", 50),
                ("客厅阳台窗帘拉开一半", "living-curtain", "position", 50),
                ("把客厅空调关一下", "living-ac", "power", False),
                ("客厅空调二十四度", "living-ac", "target", 24),
                ("把客厅空调调低两度", "living-ac", "target", 22),
            ]
            for idx, (utt, dev_id, cap, expected_val) in enumerate(variants):
                m = self.app.repo.read_model("apartment")
                res = butler.handle_chat("apartment", m, {"text": utt}, "admin", f"sess-var-{idx}")
                self.assertEqual(res["tier_used"], "slot_engine", utt)
                m_after = self.app.repo.read_model("apartment")
                dev = next(x for x in m_after["plan"]["items"] if x["id"] == dev_id)
                self.assertEqual(dev[cap], expected_val, utt)

            # 2. A-not-A & particle interrogatives MUST NOT toggle devices!
            interrogatives = ["客厅灯开没开？", "客厅主灯关没关", "客厅空调有没有开？", "客厅阳台窗帘拉上了吗？", "书房现在冷不冷"]
            for q in interrogatives:
                m_before = self.app.repo.read_model("apartment")
                res_q = butler.handle_chat("apartment", m_before, {"text": q}, "admin", "sess-interrog")
                self.assertEqual(res_q["applied"], [], f"Interrogative mutated state: {q}")

            # 3. Negation guards MUST NOT execute actions!
            for neg in ["先别关客厅灯", "千万不要把客厅空调关了", "不用打开玄关灯"]:
                m_n = self.app.repo.read_model("apartment")
                res_n = butler.handle_chat("apartment", m_n, {"text": neg}, "admin", "sess-neg")
                self.assertEqual(res_n["applied"], [], f"Negation mutated state: {neg}")

            # 4. Bare-command disambiguation + multi-turn slot completion + abort ("不用了")
            m = self.app.repo.read_model("house")
            r_bare = butler.handle_chat("house", m, {"text": "把灯关掉", "active_room": "living"}, "admin", "sess-house-bare")
            self.assertEqual(r_bare["applied"], [])
            self.assertIn("关哪", r_bare["reply"])
            m = self.app.repo.read_model("house")
            r_cancel = butler.handle_chat("house", m, {"text": "不用了"}, "admin", "sess-house-bare")
            self.assertEqual(r_cancel["applied"], [])

            # 5. Per-room micro-climate Q&A differentiates cold AC room vs warm room
            m_h = self.app.repo.read_model("house")
            q_study = butler.handle_chat("house", m_h, {"text": "书房现在多少度"}, "admin", "sess-temp")
            q_kitch = butler.handle_chat("house", m_h, {"text": "厨房现在多少度"}, "admin", "sess-temp")
            self.assertIn("21.4°C", q_study["reply"])
            self.assertNotEqual(q_study["reply"], q_kitch["reply"])

    def test_tc16_home_agent_harness_multistep_orchestration(self) -> None:
        butler = self.app.butler_router
        with self.app.repo.lock, self.app.repo.db:
            # 1. Superlative chain on 11-room Apple RoomPlan (`house`):
            #    "找到最亮的灯关掉，然后看看哪个房间最冷，把那里的空调关了"
            #    Initial house state: living-lamp=85% ON, bed-lamp=45% ON; scan-ac-bed3 (书房空调)=21°C ON (21.4°C coldest)
            m = self.app.repo.read_model("house")
            res1 = butler.handle_chat(
                "house", m,
                {"text": "找到最亮的灯关掉，然后看看哪个房间最冷，把那里的空调关了"},
                "admin", "sess-harness-1",
            )
            self.assertEqual(res1["tier_used"], "home_harness")
            self.assertGreaterEqual(len(res1.get("trace", [])), 4)
            m_after = self.app.repo.read_model("house")
            liv_lp = next(x for x in m_after["plan"]["items"] if x["id"] == "living-lamp")
            bed_lp = next(x for x in m_after["plan"]["items"] if x["id"] == "bed-lamp")
            study_ac = next(x for x in m_after["plan"]["items"] if x["id"] == "scan-ac-bed3")
            self.assertFalse(liv_lp["power"], "Brightest lamp (living-lamp 85%) should be turned off")
            self.assertTrue(bed_lp["power"], "Dimmer lamp (bed-lamp 45%) should remain untouched")
            self.assertFalse(study_ac["power"], "Coldest room AC (scan-ac-bed3) should be turned off")

            # 2. Cross-room brightness sync + conditional check on `apartment`:
            m_apt = self.app.repo.read_model("apartment")
            res2 = butler.handle_chat(
                "apartment", m_apt,
                {"text": "把玄关的灯调到跟客厅灯一样亮，如果厨房超过30度就把最热的房间空调开到24度"},
                "admin", "sess-harness-2",
            )
            self.assertEqual(res2["tier_used"], "home_harness")
            self.assertGreaterEqual(len(res2.get("trace", [])), 3)
            m_apt_after = self.app.repo.read_model("apartment")
            entry_lp = next(x for x in m_apt_after["plan"]["items"] if x["id"] == "entry-lamp")
            self.assertTrue(entry_lp["power"])
            self.assertEqual(entry_lp["level"], 80)

            # 3. Occupancy-filtered sweep ("把所有没人房间的灯关掉")
            m_occ = self.app.repo.read_model("apartment")
            m_occ["occupied"] = {"living": True, "entry": False}
            self.app.repo.write_model("apartment", m_occ)
            m_occ = self.app.repo.read_model("apartment")
            res3 = butler.handle_chat(
                "apartment", m_occ,
                {"text": "把所有没人房间的灯关掉"},
                "admin", "sess-harness-3",
            )
            self.assertEqual(res3["tier_used"], "home_harness")
            m_occ_after = self.app.repo.read_model("apartment")
            self.assertTrue(next(x for x in m_occ_after["plan"]["items"] if x["id"] == "living-lamp")["power"])
            self.assertFalse(next(x for x in m_occ_after["plan"]["items"] if x["id"] == "entry-lamp")["power"])

    def test_tc17_auto_manual_cooperative_control_balance(self) -> None:
        ctrl = self.app.control_layer
        strat = self.app.strategy_layer
        butler = self.app.butler_router
        with self.app.repo.lock, self.app.repo.db:
            # 1. Auto occupancy turns ON study lamp when dark (lux=85) and occupied
            m = self.app.repo.read_model("apartment")
            strat.update_environment("apartment", m, {"climate": {"lux": 85}, "room": "study", "occupied": True})
            m = self.app.repo.read_model("apartment")
            self.assertTrue(next(x for x in m["plan"]["items"] if x["id"] == "study-lamp")["power"])

            # 2. User manually turns OFF study lamp (e.g. watching projector) -> issues Override Lease!
            ctrl.dispatch_command("apartment", m, "study-lamp", {"capability": "power", "value": False}, role="admin")
            snap = ctrl.project_snapshot("apartment", "admin")
            self.assertIn("study", snap["overrides"])
            self.assertGreater(snap["overrides"]["study"], 0)

            # While override lease is active, new occupancy/lux sensor reports MUST NOT turn lamp back ON!
            m = self.app.repo.read_model("apartment")
            strat.update_environment("apartment", m, {"climate": {"lux": 60}, "room": "study", "occupied": True})
            m = self.app.repo.read_model("apartment")
            self.assertFalse(next(x for x in m["plan"]["items"] if x["id"] == "study-lamp")["power"])

            # 3. Pin manual hold on living room -> survives 'home' scene without overwriting manual state!
            ctrl.dispatch_command("apartment", m, "living-lamp", {"capability": "power", "value": False}, role="admin")
            m = self.app.repo.read_model("apartment")
            butler.handle_chat("apartment", m, {"text": "锁定客厅手动模式"}, "admin", "sess-bal")
            snap_pin = ctrl.project_snapshot("apartment", "admin")
            self.assertEqual(snap_pin["overrides"].get("living"), -1)

            m = self.app.repo.read_model("apartment")
            res_home = strat.trigger_scene("apartment", m, "home", "admin")
            self.assertIn("客厅餐厅", res_home["skipped"])
            m = self.app.repo.read_model("apartment")
            self.assertFalse(next(x for x in m["plan"]["items"] if x["id"] == "living-lamp")["power"])

            # 4. One-click / voice release back to Auto immediately resumes occupancy lighting!
            butler.handle_chat("apartment", m, {"text": "恢复书房自动控制"}, "admin", "sess-bal")
            m_after = self.app.repo.read_model("apartment")
            self.assertNotIn("study", ctrl.project_snapshot("apartment", "admin")["overrides"])
            self.assertTrue(next(x for x in m_after["plan"]["items"] if x["id"] == "study-lamp")["power"])

    def test_tc14_unidirectional_five_layer_architecture(self) -> None:
        allowed = {
            "data": {"common", "data"},
            "device": {"common", "data", "device"},
            "control": {"common", "data", "device", "control"},
            "strategy": {"common", "data", "device", "control", "strategy"},
            "api": {"common", "data", "device", "control", "strategy", "api"},
        }
        for layer, ok_deps in allowed.items():
            for py in (DEMO_ROOT / "backend" / layer).glob("*.py"):
                tree = ast.parse(py.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("backend."):
                        dep = node.module.split(".")[1]
                        self.assertIn(dep, ok_deps, f"Illegal reverse/cross-layer import: {layer} -> {dep}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
