#!/usr/bin/env python3
"""给 AI 使用的瓶中生态独立版客户端。"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


DEFAULT_URL = os.getenv("CEDARECO_URL", "http://127.0.0.1:8765")


def request(url, path, body=None):
    target = url.rstrip("/") + path
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {}
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
    root = argparse.ArgumentParser(description="操作独立存档中的瓶中生态池塘")
    root.add_argument("--url", default=DEFAULT_URL, help="服务地址；默认 http://127.0.0.1:8765")
    sub = root.add_subparsers(dest="action")
    command = sub.add_parser("cmd", help="让 AI 执行游戏指令")
    command.add_argument("command", nargs=argparse.REMAINDER)
    sub.add_parser("state", help="读取当前池塘 JSON 状态")
    new = sub.add_parser("new", help="重开一局")
    new.add_argument("seed", nargs="?", type=int, default=12345)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    url = args.url
    if args.action == "cmd":
        command = " ".join(args.command).strip()
        if not command:
            print("请提供游戏指令，例如 cmd observe", file=sys.stderr)
            return 2
        payload = request(url, "/api/command", {"command": command})
        print(payload.get("text", ""))
        return 0
    if args.action == "state":
        print(json.dumps(request(url, "/api/state").get("data"), ensure_ascii=False, indent=2))
        return 0
    if args.action == "new":
        request(url, "/api/new", {"seed": args.seed})
        print("新池已建立（seed=%d）。" % args.seed)
        return 0
    parser().print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
