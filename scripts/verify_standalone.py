#!/usr/bin/env python3
"""独立前端/服务端零依赖回归。"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine  # noqa: E402
from standalone_server import PondStore, load_or_create_token, local_urls, make_handler  # noqa: E402


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("[PASS] " + label)


def http_json(url, token=None, body=None, method=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method or ("POST" if data is not None else "GET"))
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, dict(response.headers), json.loads(response.read().decode("utf-8"))


def disaster_cases():
    cases = []
    state = engine.fresh_state(1)
    state["turn"] = 10
    state["flags"]["brazilian_turtle"] = "active"
    cases.append((state, "expel_turtle", None))

    state = engine.fresh_state(2)
    state["turn"] = 10
    state["flags"]["apple_snail"] = {"status": "active", "count": 6, "human_helped": False}
    cases.append((state, "catch_snail", {"count": 2}))

    state = engine.fresh_state(3)
    state["turn"] = 10
    state["flags"]["water_hyacinth"] = {"day": 7, "cover": .12, "outbreak_cover": .12, "human_helped": False}
    cases.append((state, "pull_hyacinth", {"stalks": 2}))

    state = engine.fresh_state(4)
    state["turn"] = 10
    state["populations"]["田鼠"] = 20
    state["flags"].setdefault("bio_disasters", {})["鼠患"] = {"remaining": 3, "outbreak_count": 20, "human_helped": False}
    cases.append((state, "hunt_rat", {"count": 3}))

    state = engine.fresh_state(5)
    state["turn"] = 10
    state["populations"]["水藻"] = 100
    state["flags"].setdefault("bio_disasters", {})["绿潮"] = {"remaining": 4, "human_helped": False, "human_skim_total": 0, "skim_day_reduced": False}
    cases.append((state, "skim_algae", {"amount": 10}))

    state = engine.fresh_state(6)
    state["turn"] = 10
    state["season"] = "冬"
    state["flags"]["ice_on"] = True
    cases.append((state, "crack_ice", None))
    return cases


def main():
    with tempfile.TemporaryDirectory(prefix="cedareco-standalone-") as temporary:
        data_dir = Path(temporary)
        token = load_or_create_token(data_dir)
        check("自动生成绑定令牌", len(token) >= 24)
        check("绑定令牌可稳定复用", load_or_create_token(data_dir) == token)
        base_url, paired_url = local_urls("0.0.0.0", 8765, token)
        check("本机网页链接可一键绑定", base_url == "http://127.0.0.1:8765" and paired_url.endswith("#token=" + token))

        store = PondStore(data_dir / "eco_save.json", seed=77)
        state = store.project("state")
        check("初始池塘可读取", state["day"] == 0)
        check("无灾害时无协作入口", state["available_human_actions"] == [])

        text = store.command("new 88")
        check("AI 指令可重开池塘", "新池初成" in text)
        text = store.command("summon 水藻 50; observe")
        check("AI 指令与网页共用存档", "水藻" in text and store.project("state")["day"] == 1)

        for state, action, payload in disaster_cases():
            with store.lock:
                store._save_unlocked(state)
            projected = store.project("state")
            check("%s 仅在对应灾害开放" % action, action in projected["available_human_actions"])
            result = store.human_action(action, payload)
            check("%s 可写回独立存档" % action, result.get("ok") is True)
            check("%s 成功后不重复开放" % action, action not in store.project("state")["available_human_actions"])

        with store.lock:
            rat_state = disaster_cases()[3][0]
            store._save_unlocked(rat_state)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store, token, "*"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:%d" % server.server_address[1]
        try:
            status, _, health = http_json(base + "/api/health")
            check("健康检查无需令牌", status == 200 and health["ok"])
            try:
                http_json(base + "/api/state", "wrong")
                raise AssertionError("错误令牌未被拒绝")
            except urllib.error.HTTPError as exc:
                check("错误绑定令牌返回 401", exc.code == 401)
            status, _, payload = http_json(base + "/api/state", token)
            check("绑定后可读取正式状态 API", status == 200 and "hunt_rat" in payload["data"]["available_human_actions"])
            with urllib.request.urlopen(base + "/", timeout=5) as response:
                html = response.read().decode("utf-8")
                check("服务端直接提供独立网页", response.status == 200 and 'id="bind-form"' in html)
            with urllib.request.urlopen(base + "/app.js", timeout=5) as response:
                javascript = response.read().decode("utf-8")
                check("网页支持终端链接自动配对", response.status == 200 and "readFragmentBinding" in javascript)

            client_config = data_dir / "client.json"
            environment = os.environ.copy()
            environment["CEDARECO_CLIENT_CONFIG"] = str(client_config)
            bound = subprocess.run(
                [sys.executable, str(ROOT / "standalone_client.py"), "bind", base, token],
                cwd=str(data_dir), env=environment, capture_output=True, text=True, timeout=10,
            )
            check("AI 客户端可一次配对", bound.returncode == 0 and client_config.is_file())
            client_status = subprocess.run(
                [sys.executable, str(ROOT / "standalone_client.py"), "cmd", "status"],
                cwd=str(data_dir), env=environment, capture_output=True, text=True, timeout=10,
            )
            check("AI 客户端配对后可直接玩", client_status.returncode == 0 and "池塘" in client_status.stdout)
            status, _, payload = http_json(base + "/api/command", token, {"command": "status"})
            check("AI HTTP 指令接口可用", status == 200 and payload["ok"] and "池塘" in payload["text"])
            status, _, payload = http_json(base + "/api/human_action", token, {"action": "hunt_rat", "payload": {"count": 3}})
            check("人类协作 HTTP 接口可用", status == 200 and payload["ok"])
            request = urllib.request.Request(base + "/api/state", method="OPTIONS", headers={"Origin": "https://example.com"})
            with urllib.request.urlopen(request, timeout=5) as response:
                check("跨域静态前端可预检", response.status == 204 and response.headers.get("Access-Control-Allow-Origin") == "*")
            try:
                urllib.request.urlopen(base + "/assets/%2e%2e/engine.py", timeout=5)
                raise AssertionError("静态目录穿越未被拒绝")
            except urllib.error.HTTPError as exc:
                check("静态资源禁止目录穿越", exc.code == 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    print("\n独立版验证全部通过 ✅")


if __name__ == "__main__":
    main()
