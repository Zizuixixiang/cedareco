#!/usr/bin/env python3
"""给 AI 使用的瓶中生态独立版客户端。"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_CONFIG = Path(os.getenv("CEDARECO_CLIENT_CONFIG", str(Path.home() / ".cedareco-client.json")))


def load_config(path=DEFAULT_CONFIG):
    values = {}
    if path.exists():
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            values = {}
    return {
        "url": os.getenv("CEDARECO_URL") or values.get("url"),
        "token": os.getenv("CEDARECO_TOKEN") or values.get("token"),
    }


def save_config(url, token, path=DEFAULT_CONFIG):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"url": url.rstrip("/"), "token": token}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def request(url, token, path, body=None):
    target = url.rstrip("/") + path
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": "Bearer " + token}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(target, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            message = payload.get("error") or payload.get("message")
        except Exception:
            message = None
        raise RuntimeError(message or "HTTP %d" % exc.code)
    except urllib.error.URLError as exc:
        raise RuntimeError("无法连接瓶中生态服务：%s" % exc.reason)


def parser():
    root = argparse.ArgumentParser(description="连接自己的瓶中生态池塘")
    root.add_argument("--url")
    root.add_argument("--token")
    sub = root.add_subparsers(dest="action")
    bind = sub.add_parser("bind", help="保存服务地址和令牌")
    bind.add_argument("server_url")
    bind.add_argument("access_token")
    command = sub.add_parser("cmd", help="让 AI 执行游戏指令")
    command.add_argument("command", nargs=argparse.REMAINDER)
    sub.add_parser("state", help="读取当前池塘 JSON 状态")
    new = sub.add_parser("new", help="重开一局")
    new.add_argument("seed", nargs="?", type=int, default=12345)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    if args.action == "bind":
        request(args.server_url, args.access_token, "/api/state")
        save_config(args.server_url, args.access_token)
        print("绑定成功。以后可直接运行：python standalone_client.py cmd observe")
        return 0

    config = load_config()
    url = args.url or config.get("url")
    token = args.token or config.get("token")
    if not url or not token:
        print("尚未绑定。先运行：python standalone_client.py bind http://127.0.0.1:8765 <令牌>", file=sys.stderr)
        return 2
    if args.action == "cmd":
        command = " ".join(args.command).strip()
        if not command:
            print("请提供游戏指令，例如 cmd observe", file=sys.stderr)
            return 2
        payload = request(url, token, "/api/command", {"command": command})
        print(payload.get("text", ""))
        return 0
    if args.action == "state":
        print(json.dumps(request(url, token, "/api/state").get("data"), ensure_ascii=False, indent=2))
        return 0
    if args.action == "new":
        request(url, token, "/api/new", {"seed": args.seed})
        print("新池已建立（seed=%d）。" % args.seed)
        return 0
    parser().print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
