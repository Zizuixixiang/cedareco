# -*- coding: utf-8 -*-
"""
build_blind.py —— 盲玩版打包器

把 engine.py 整个源码 base64 编码，生成 ecosystem.py 盲玩文件。
盲玩文件对外只暴露 cmd() 与 new_game()，AI 看不到内部物种参数与公式。

用法：
    python build_blind.py
生成：
    ecosystem.py（与 engine.py 行为一致，但源码经过编码隐藏）
"""

import os
import base64

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_PATH = os.path.join(HERE, "engine.py")
OUT_PATH = os.path.join(HERE, "ecosystem.py")

WRAPPER = '''# -*- coding: utf-8 -*-
"""
ecosystem.py —— 瓶中生态 · 盲玩版（由 build_blind.py 自动生成，请勿手改）

对外只暴露两个接口：
    cmd("指令")    -> 执行一条/多条指令，返回结果文字
    new_game(seed) -> 重开一局

引擎内部的物种参数、数学公式、事件概率均已编码隐藏，方便"盲玩"——
AI 玩家只能通过 observe / status / gaze 等观察手段去推测生态规律。

用法：
    import ecosystem
    print(ecosystem.new_game(42))
    print(ecosystem.cmd("summon 水藻 50; wait 7"))
"""

import base64 as _b64

# —— 引擎源码（base64 编码，请勿依赖其内部细节）——
_ENGINE_B64 = (
{chunks}
)

# 解码并在隔离命名空间中执行引擎源码
_src = _b64.b64decode(_ENGINE_B64).decode("utf-8")
_ns = {"__name__": "_pond_engine", "__file__": __file__}
exec(compile(_src, "<pond-engine>", "exec"), _ns)

# 只导出这两个接口
cmd = _ns["cmd"]
new_game = _ns["new_game"]

__all__ = ["cmd", "new_game"]


if __name__ == "__main__":
    print(cmd("help"))
'''


def build():
    with open(SRC_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    b64 = base64.b64encode(src.encode("utf-8")).decode("ascii")
    # 切成 76 字符一行，用括号内字符串相邻自动拼接，便于阅读与版本管理
    width = 76
    rows = [b64[i:i + width] for i in range(0, len(b64), width)]
    chunks = "\n".join('    "%s"' % row for row in rows)
    out = WRAPPER.replace("{chunks}", chunks)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(out)
    print("已生成 %s（源码 %d 字节 → base64 %d 字符，%d 行）" %
          (os.path.basename(OUT_PATH), len(src), len(b64), len(rows)))


if __name__ == "__main__":
    build()
