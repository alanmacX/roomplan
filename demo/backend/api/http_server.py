"""Layer 1 (Backend): Presentation HTTP Adapter & Static Asset Gateway.

Wires together the 5 unidirectional layers:
    HTTP Handler -> Strategy (StrategyEngine / ButlerRouter)
                 -> Control (ControlLayerService)
                 -> Device (DeviceLayerService)
                 -> Data (SQLiteRepository)
"""
from __future__ import annotations

import argparse
import hmac
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from backend.common import Problem, packed
from backend.control.service import ControlLayerService
from backend.data.repository import SQLiteRepository
from backend.device.registry import DEFAULT_DEVICE_TYPES, DeviceLayerService
from backend.strategy.butler import HomeHubButlerRouter
from backend.strategy.engine import StrategyEngine


class SmartHomeApp:
    """Dependency-injected container assembling the strict 5-layer architecture."""

    def __init__(self, root: Path, db_path: Path, admin_pin: str = "2468"):
        self.root = root
        self.repo = SQLiteRepository(
            db_path=db_path,
            seed_file=root / "data/seed.json",
            house_file=root / "assets/apple-roomplan/projected.js",
            default_types=DEFAULT_DEVICE_TYPES,
        )
        self.device_layer = DeviceLayerService(self.repo)
        self.control_layer = ControlLayerService(self.repo, self.device_layer, self.repo.mount_origin)
        self.strategy_layer = StrategyEngine(self.repo, self.control_layer)
        self.butler_router = HomeHubButlerRouter(self.control_layer, self.strategy_layer)

        self.pins = {
            admin_pin: "admin",
            "1357": "member",
            "0000": "guest",
        }
        self.sessions: dict[str, dict] = {}
        self.session_lock = threading.Lock()


class SmartHomeHTTPHandler(BaseHTTPRequestHandler):
    server_version = "SmartHome5Layer/2.0"

    def log_message(self, *args) -> None:
        if getattr(self.server, "verbose", False):
            super().log_message(*args)

    def send_json(self, data: object, status: int = 200, headers: tuple = ()) -> None:
        pay = packed(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(pay)))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(pay)

    def send_text(self, text: str, content_type: str = "text/csv; charset=utf-8", filename: str | None = None) -> None:
        pay = text.encode("utf-8-sig")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(pay)))
        self.end_headers()
        self.wfile.write(pay)

    def current_session(self) -> tuple[str | None, str]:
        app: SmartHomeApp = self.server.app
        try:
            c = SimpleCookie(self.headers.get("Cookie", ""))
            tok = c["home_demo"].value
        except (KeyError, ValueError):
            return None, "guest"
        with app.session_lock:
            sess = app.sessions.get(tok)
            if sess and sess["exp"] > time.time():
                return tok, sess["role"]
        return None, "guest"

    def read_json_body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if not (0 < n <= 6 * 1024 * 1024):
                raise Problem("请求体大小无效。")
            data = json.loads(self.rfile.read(n))
            if isinstance(data, dict):
                return data
        except (ValueError, OverflowError):
            pass
        raise Problem("JSON 请求格式不正确。")

    def dispatch(self, method: str) -> None:
        app: SmartHomeApp = self.server.app
        parsed_url = urlsplit(self.path)
        path = unquote(parsed_url.path)
        query = parse_qs(parsed_url.query)

        try:
            if not path.startswith("/api/"):
                if method != "GET":
                    raise Problem("页面不存在。", 404)
                return self.serve_static(path)

            if method != "GET":
                origin = self.headers.get("Origin")
                if origin and urlsplit(origin).netloc != self.headers.get("Host"):
                    raise Problem("无效的跨站请求来源。", 403)

            tok, role = self.current_session()

            if path == "/api/status" and method == "GET":
                return self.send_json({
                    "service": "smart-home-demo",
                    "architecture": "5-layer",
                    "signedIn": tok is not None,
                    "role": role if tok else None,
                })

            if path in ("/api/login", "/api/auth/login") and method == "POST":
                body = self.read_json_body()
                provided = str(body.get("pin", body.get("passcode", ""))).strip()
                matched_role = None
                for pin_val, r_name in app.pins.items():
                    if hmac.compare_digest(provided, pin_val):
                        matched_role = r_name
                        break
                if not matched_role:
                    raise Problem("口令不正确（管理员: 2468 ｜ 长辈成员: 1357 ｜ 临时访客: 0000）。", 401)
                new_tok = secrets.token_urlsafe(24)
                with app.session_lock:
                    now = time.time()
                    app.sessions = {k: v for k, v in app.sessions.items() if v["exp"] > now}
                    app.sessions[new_tok] = {"role": matched_role, "exp": now + 3600 * 12}
                return self.send_json(
                    {"signedIn": True, "role": matched_role},
                    headers=[("Set-Cookie", f"home_demo={new_tok}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200")]
                )

            if path == "/api/logout" and method == "POST":
                if tok:
                    with app.session_lock:
                        app.sessions.pop(tok, None)
                return self.send_json(
                    {"signedIn": False},
                    headers=[("Set-Cookie", "home_demo=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")]
                )

            if not tok:
                raise Problem("请先输入家庭角色口令登录系统。", 401)

            if path in ("/api/types", "/api/device-types"):
                if method == "GET":
                    return self.send_json(app.device_layer.get_types())
                if method == "POST":
                    app.control_layer.check_edit_permission(role)
                    body = self.read_json_body()
                    with app.repo.lock, app.repo.db:
                        created = app.device_layer.register_type(body)
                        return self.send_json({"created": created, "types": app.device_layer.get_types()})

            match = re.fullmatch(r"/api/plans/(apartment|apple|custom|house)(?:/(.*))?", path)
            if not match:
                raise Problem("请求的 API 路径不存在。", 404)

            key, action = match.groups()
            body = self.read_json_body() if method in ("POST", "PUT") else {}

            # Simulate physical device communication latency outside DB lock
            if method == "POST" and action and re.fullmatch(r"devices/[A-Za-z0-9_-]{1,80}/command", action):
                app.device_layer.simulate_latency(str(body.get("outcome", "ok")))

            # CSV export endpoint returns downloadable text or JSON wrapper
            if action == "export" and method == "GET":
                fmt = (query.get("format", ["csv"])[0]).lower()
                if fmt == "csv":
                    csv_text = app.control_layer.export_items_csv(key, role)
                    return self.send_text(csv_text, filename=f"{key}-assets.csv")
                with app.repo.lock:
                    snap = app.control_layer.project_snapshot(key, role)
                    return self.send_json(snap["plan"])

            with app.repo.lock, app.repo.db:
                m = app.repo.read_model(key)
                result = self.handle_plan_action(app, key, m, action, method, body, query, role, tok)
                return self.send_json(result)

        except Problem as e:
            self.send_json({"error": str(e)}, e.status)
        except (BrokenPipeError, ConnectionResetError):
            pass

    @staticmethod
    def handle_plan_action(app: SmartHomeApp, key: str, m: dict, action: str | None,
                           method: str, body: dict, query: dict, role: str, session_tok: str) -> dict:
        ctrl = app.control_layer
        strat = app.strategy_layer

        if action is None:
            if method == "GET":
                return ctrl.project_snapshot(key, role)
            if method == "PUT":
                warn = ctrl.replace_plan(key, m, body, role, on_after_change=strat.evaluate_ambient_and_occupancy)
                snap = ctrl.project_snapshot(key, role)
                if warn:
                    snap["warning"] = warn
                return snap

        if action == "mount" and method == "POST":
            item = ctrl.mount_ceiling_lamp(key, m, body, role, on_after_change=strat.evaluate_ambient_and_occupancy)
            return {"item": item, "snapshot": ctrl.project_snapshot(key, role)}

        if action == "import" and method == "POST":
            count = ctrl.import_items_batch(key, m, body, role)
            return {"imported": count, "snapshot": ctrl.project_snapshot(key, role)}

        if action == "scene" and method == "POST":
            info = strat.trigger_scene(key, m, str(body.get("mode", "normal")), role=role)
            return {**info, **ctrl.project_snapshot(key, role)}

        if action == "scenes":
            if method == "GET":
                return {"scenes": app.repo.read_scenes(key)}
            if method == "POST":
                saved = strat.upsert_scene(key, body, role)
                return {"scene": saved, "snapshot": ctrl.project_snapshot(key, role)}

        scene_trig = re.fullmatch(r"scenes/([A-Za-z0-9_-]{1,80})/trigger", action or "")
        if scene_trig and method == "POST":
            info = strat.trigger_scene(key, m, scene_trig.group(1), role=role)
            return {**info, "snapshot": ctrl.project_snapshot(key, role)}

        if action == "environment" and method == "POST":
            strat.update_environment(key, m, body)
            return ctrl.project_snapshot(key, role)

        if action == "butler/chat" and method == "POST":
            reply = app.butler_router.handle_chat(key, m, body, role=role, session_key=session_tok)
            return {**reply, "snapshot": ctrl.project_snapshot(key, role)}

        if action == "butler/confirm" and method == "POST":
            confirmed = ctrl.execute_confirmed_token(key, m, str(body.get("confirm_token", "")), role=role)
            return {**confirmed, "snapshot": ctrl.project_snapshot(key, role)}

        dev_match = re.fullmatch(r"devices/([A-Za-z0-9_-]{1,80})(?:/(history|state-logs|command))?", action or "")
        if dev_match:
            dev_id, leaf = dev_match.groups()
            if leaf == "command" and method == "POST":
                detail = ctrl.dispatch_command(
                    key, m, dev_id, body, role=role,
                    on_manual_override=strat.evaluate_ambient_and_occupancy
                )
                return {**detail, "snapshot": ctrl.project_snapshot(key, role)}
            if leaf in ("history", "state-logs") and method == "GET":
                item = ctrl._find_item(m, dev_id)
                ctrl.check_room_access(role, m["plan"], item)
                return {"events": app.repo.query_events(key, dev_id, limit=40)}
            if leaf is None and method == "DELETE":
                force = query.get("force", ["0"])[0] in ("1", "true")
                ctrl.remove_device(key, m, dev_id, role=role, force=force, on_after_change=strat.evaluate_ambient_and_occupancy)
                return ctrl.project_snapshot(key, role)

        raise Problem("未定义的接口动作。", 404)

    def serve_static(self, path: str) -> None:
        root: Path = self.server.app.root
        rel = path.lstrip("/") or "index.html"
        p = (root / rel).resolve()
        allowed = (
            (p.parent == root and p.suffix in (".html", ".css", ".js"))
            or any(p.is_relative_to(root / d) for d in ("assets", "vendor"))
        )
        if not allowed or not p.is_file():
            raise Problem("静态资源文件不存在。", 404)
        content = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(p.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        self.dispatch("GET")

    def do_POST(self) -> None:
        self.dispatch("POST")

    def do_PUT(self) -> None:
        self.dispatch("PUT")

    def do_DELETE(self) -> None:
        self.dispatch("DELETE")


def main(default_root: Path | None = None) -> None:
    root = default_root or Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="5-Layer Smart Home System Server")
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--db", type=Path, default=root / ".local/demo.sqlite3")
    parser.add_argument("--verbose", action="store_true")
    opts = parser.parse_args()

    opts.db.parent.mkdir(parents=True, exist_ok=True)
    pin = os.environ.get("HOME_DEMO_PIN", "2468")
    app = SmartHomeApp(root=root, db_path=opts.db, admin_pin=pin)

    server = ThreadingHTTPServer(("127.0.0.1", opts.port), SmartHomeHTTPHandler)
    server.app = app
    server.verbose = opts.verbose

    stop = threading.Event()

    def background_worker() -> None:
        while not stop.wait(0.3):
            with app.repo.lock, app.repo.db:
                app.strategy_layer.tick_background()

    threading.Thread(target=background_worker, daemon=True).start()
    print(f"智能家居系统 (五层架构)  http://127.0.0.1:{opts.port}/", flush=True)
    print(f"角色口令 —— 管理员: {pin} ｜ 长辈成员: 1357 ｜ 临时访客: 0000", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
