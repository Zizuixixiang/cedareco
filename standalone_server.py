#!/usr/bin/env python3
"""瓶中生态独立网页服务。

零第三方依赖，同时提供静态前端、AI 指令 API 和人类灾害协作 API。
一个服务实例对应一座池塘；网页与 AI 直接共享同一份本地存档。
"""

import argparse
import json
import mimetypes
import os
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import engine


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
ASSETS_ROOT = ROOT / "assets"
MAX_BODY_BYTES = 64 * 1024


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class PondStore:
    """对一份 JSON 存档做进程内串行、原子读写。"""

    def __init__(self, save_path, seed=12345):
        self.save_path = Path(save_path)
        self.seed = int(seed)
        self.lock = threading.RLock()
        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            if not self.save_path.exists():
                self._save_unlocked(engine.fresh_state(self.seed))

    def _load_unlocked(self):
        try:
            with self.save_path.open("r", encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, ValueError) as exc:
            raise ApiError(500, "池塘存档无法读取：%s" % exc)
        if not isinstance(state, dict):
            raise ApiError(500, "池塘存档格式不正确")
        engine._migrate(state)
        return state

    def _save_unlocked(self, state):
        descriptor, temporary = tempfile.mkstemp(
            prefix=".eco-save-", suffix=".json", dir=str(self.save_path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, str(self.save_path))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def project(self, name, species=None):
        with self.lock:
            state = self._load_unlocked()
            if name == "state":
                data = engine.api_state(state)
                data["available_human_actions"] = self._available_human_actions(state)
                return data
            if name == "codex":
                return engine.api_codex(state)
            if name == "folio":
                return engine.api_folio(state)
            if name == "annals":
                return engine.api_annals(state)
            if name == "species":
                value = engine.api_species(state, species)
                if value is None:
                    raise ApiError(404, "物种未解锁或不存在")
                return value
            raise ApiError(404, "接口不存在")

    @staticmethod
    def _available_human_actions(state):
        flags = state.get("flags", {})
        available = []
        if flags.get("brazilian_turtle") == "active":
            available.append("expel_turtle")
        apple = flags.get("apple_snail")
        if isinstance(apple, dict) and apple.get("status") == "incubating":
            available.append("catch_snail")
        elif isinstance(apple, dict) and apple.get("status") in ("active", "clearing") \
                and not apple.get("human_helped"):
            available.append("catch_snail")
        hyacinth = flags.get("water_hyacinth")
        if isinstance(hyacinth, dict) and state.get("turn", 0) >= hyacinth.get("day", 0) + 3 \
                and not hyacinth.get("human_helped"):
            available.append("pull_hyacinth")
        biological = flags.get("bio_disasters", {})
        rat = biological.get("鼠患") if isinstance(biological, dict) else None
        if rat and not (isinstance(rat, dict) and rat.get("human_helped")):
            available.append("hunt_rat")
        algae = biological.get("绿潮") if isinstance(biological, dict) else None
        if algae and not (isinstance(algae, dict) and algae.get("human_helped")):
            available.append("skim_algae")
        attempted_today = flags.get("ice_attempt_day") == state.get("turn") \
            and flags.get("ice_human_attempted")
        if state.get("season") == "冬" and flags.get("ice_on") and not attempted_today:
            available.append("crack_ice")
        return available

    def command(self, command):
        if not isinstance(command, str) or not command.strip():
            raise ApiError(400, "command 需要是非空字符串")
        with self.lock:
            state = self._load_unlocked()
            previous_state = engine._STATE
            previous_save = engine.save_state
            try:
                engine._STATE = state
                engine.save_state = lambda _state: None
                text = engine.cmd(command.strip())
                state = engine._STATE
                self._save_unlocked(state)
            finally:
                engine.save_state = previous_save
                engine._STATE = previous_state
            return text

    def human_action(self, action, payload=None):
        if not isinstance(action, str) or not action:
            raise ApiError(400, "action 不能为空")
        with self.lock:
            state = self._load_unlocked()
            result = engine.human_action(state, action, payload)
            if result.get("ok"):
                self._save_unlocked(state)
            return result

    def reset(self, seed=None):
        with self.lock:
            actual_seed = self.seed if seed is None else int(seed)
            state = engine.fresh_state(actual_seed)
            self._save_unlocked(state)
            return engine.api_state(state)


def local_url(host, port):
    """返回适合终端点击的本机地址。"""
    shown_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url_host = "[%s]" % shown_host if ":" in shown_host else shown_host
    return "http://%s:%d" % (url_host, port)


def make_handler(store, allowed_origin="*"):
    class StandaloneHandler(BaseHTTPRequestHandler):
        server_version = "CedarEcoStandalone/1.0"

        def log_message(self, format_string, *args):
            print("[%s] %s" % (self.log_date_time_string(), format_string % args))

        def _cors_headers(self):
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Vary", "Origin")

        def _security_headers(self):
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src *; font-src 'self'; base-uri 'none'; frame-ancestors 'none'")

        def _json(self, status, value):
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._cors_headers()
            self._security_headers()
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self):
            raw_length = self.headers.get("Content-Length", "0")
            try:
                length = int(raw_length)
            except ValueError:
                raise ApiError(400, "Content-Length 不正确")
            if length <= 0 or length > MAX_BODY_BYTES:
                raise ApiError(413 if length > MAX_BODY_BYTES else 400, "请求体为空或过大")
            try:
                value = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise ApiError(400, "请求体不是有效 JSON")
            if not isinstance(value, dict):
                raise ApiError(400, "请求体需要是 JSON 对象")
            return value

        def _serve_file(self, path):
            if path == "/":
                target = WEB_ROOT / "index.html"
            elif path in ("/app.js", "/style.css"):
                target = WEB_ROOT / path[1:]
            elif path.startswith("/assets/"):
                relative = urllib.parse.unquote(path[len("/assets/"):])
                target = ASSETS_ROOT / relative
                try:
                    target.resolve().relative_to(ASSETS_ROOT.resolve())
                except (OSError, ValueError):
                    raise ApiError(404, "文件不存在")
            else:
                raise ApiError(404, "页面不存在")
            if not target.is_file():
                raise ApiError(404, "文件不存在")
            body = target.read_bytes()
            mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") or mime == "application/javascript" else ""))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache" if target.suffix in (".html", ".js", ".css") else "public, max-age=86400")
            self._security_headers()
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors_headers()
            self._security_headers()
            self.end_headers()

        def do_GET(self):
            try:
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path == "/api/health":
                    self._json(200, {"ok": True, "service": "cedareco-standalone"})
                    return
                if parsed.path.startswith("/api/"):
                    route = parsed.path[len("/api/"):]
                    if route in ("state", "codex", "folio", "annals"):
                        self._json(200, {"ok": True, "data": store.project(route)})
                        return
                    if route.startswith("species/"):
                        species = urllib.parse.unquote(route[len("species/"):])
                        self._json(200, {"ok": True, "data": store.project("species", species)})
                        return
                    raise ApiError(404, "接口不存在")
                self._serve_file(parsed.path)
            except ApiError as exc:
                self._json(exc.status, {"ok": False, "error": exc.message})
            except Exception as exc:
                self._json(500, {"ok": False, "error": "服务器内部错误", "detail": str(exc)})

        def do_POST(self):
            try:
                parsed = urllib.parse.urlsplit(self.path)
                body = self._read_json()
                if parsed.path == "/api/command":
                    text = store.command(body.get("command"))
                    self._json(200, {"ok": True, "text": text})
                    return
                if parsed.path == "/api/human_action":
                    result = store.human_action(body.get("action"), body.get("payload"))
                    self._json(200, result)
                    return
                if parsed.path == "/api/new":
                    seed = body.get("seed")
                    try:
                        data = store.reset(seed)
                    except (TypeError, ValueError):
                        raise ApiError(400, "seed 需要是整数")
                    self._json(200, {"ok": True, "data": data})
                    return
                raise ApiError(404, "接口不存在")
            except ApiError as exc:
                self._json(exc.status, {"ok": False, "error": exc.message})
            except Exception as exc:
                self._json(500, {"ok": False, "error": "服务器内部错误", "detail": str(exc)})

    return StandaloneHandler


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="启动瓶中生态独立前端与 API")
    parser.add_argument("--host", default=os.getenv("CEDARECO_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("CEDARECO_PORT", "8765")))
    parser.add_argument("--save", default=os.getenv("CEDARECO_SAVE_FILE", str(ROOT / "eco_save.json")))
    parser.add_argument("--seed", type=int, default=int(os.getenv("CEDARECO_SEED", "12345")))
    parser.add_argument("--allowed-origin", default=os.getenv("CEDARECO_ALLOWED_ORIGIN", "*"))
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    save_path = Path(args.save).expanduser().resolve()
    store = PondStore(save_path, args.seed)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(store, args.allowed_origin))
    actual_port = server.server_address[1]
    base_url = local_url(args.host, actual_port)
    print("瓶中生态独立版已启动：%s" % base_url)
    print("浏览器直接打开上面的地址；本机 AI 可直接使用 standalone_client.py。")
    print("按 Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
