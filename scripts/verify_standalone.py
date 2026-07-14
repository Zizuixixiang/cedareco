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
from standalone_server import PondStore, local_url, make_handler  # noqa: E402


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("[PASS] " + label)


def http_json(url, body=None, method=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {}
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
        check("本机网页地址无需账号", local_url("0.0.0.0", 8765) == "http://127.0.0.1:8765")

        store = PondStore(data_dir / "eco_save.json", seed=77)
        check("独立版只创建一份存档", sorted(path.name for path in data_dir.iterdir()) == ["eco_save.json"])
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
            notice = store.command("status")
            check("%s 完成后小机收到人类协作通知" % action,
                  "🤝 人类协作" in notice and "你的人类帮你" in notice)
            check("%s 人类协作通知写入年鉴" % action,
                  any("你的人类帮你" in item
                      for item in store.project("annals")["timeline"]))
            check("%s 人类协作通知只弹一次" % action,
                  "🤝 人类协作" not in store.command("status"))

        with store.lock:
            rat_state = disaster_cases()[3][0]
            store._save_unlocked(rat_state)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store, "*"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:%d" % server.server_address[1]
        try:
            status, _, health = http_json(base + "/api/health")
            check("健康检查无需账号", status == 200 and health["ok"])
            status, _, payload = http_json(base + "/api/state")
            check("无需账号可读取状态 API", status == 200 and "hunt_rat" in payload["data"]["available_human_actions"])
            with urllib.request.urlopen(base + "/", timeout=5) as response:
                html = response.read().decode("utf-8")
                check("服务端直接提供独立网页", response.status == 200 and 'id="bind-form"' in html)
            with urllib.request.urlopen(base + "/app.js", timeout=5) as response:
                javascript = response.read().decode("utf-8")
                check("网页不发送账号或令牌", response.status == 200 and "Authorization" not in javascript and "token" not in javascript)

            environment = os.environ.copy()
            environment["CEDARECO_URL"] = base
            client_status = subprocess.run(
                [sys.executable, str(ROOT / "standalone_client.py"), "cmd", "status"],
                cwd=str(data_dir), env=environment, capture_output=True, text=True, timeout=10,
            )
            check("AI 客户端无需配对即可玩", client_status.returncode == 0 and "池塘" in client_status.stdout)
            status, _, payload = http_json(base + "/api/command", {"command": "status"})
            check("AI HTTP 指令接口可用", status == 200 and payload["ok"] and "池塘" in payload["text"])
            status, _, payload = http_json(base + "/api/human_action", {"action": "hunt_rat", "payload": {"count": 3}})
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
