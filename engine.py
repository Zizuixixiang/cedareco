# -*- coding: utf-8 -*-
"""
池塘生态引擎 · engine.py
单文件 / 零依赖（json, os, re, math）
对外接口：
    cmd("指令")   -> 返回结果文字
    new_game(seed) -> 重开一局

设计参考 DESIGN.md。时间节奏：1 回合=1 天，1 季=30 天，1 年=120 回合。
确定性：自实现 mulberry32 PRNG，同 seed + 同指令序列 = 完全可复现。
存档：同目录 eco_save.json。
"""

import os
import json
import re
import math
import base64

SAVE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eco_save.json")

# ---------------------------------------------------------------------------
# 1. PRNG —— mulberry32（确定性，可序列化）
# ---------------------------------------------------------------------------

class Mulberry32:
    """mulberry32：32 位状态，确定性伪随机。状态可整型序列化。"""

    MASK = 0xFFFFFFFF

    def __init__(self, seed):
        self.state = int(seed) & self.MASK

    def next_u32(self):
        self.state = (self.state + 0x6D2B79F5) & self.MASK
        t = self.state
        t = (t ^ (t >> 15)) * (t | 1) & self.MASK
        t ^= (t + ((t ^ (t >> 7)) * (t | 61) & self.MASK)) & self.MASK
        t &= self.MASK
        return (t ^ (t >> 14)) & self.MASK

    def random(self):
        """返回 [0, 1) 浮点。"""
        return self.next_u32() / 4294967296.0

    def uniform(self, a, b):
        return a + (b - a) * self.random()

    def randint(self, a, b):
        """含端点的整数 [a, b]。"""
        if b < a:
            a, b = b, a
        return a + int(self.random() * (b - a + 1))

    def chance(self, p):
        return self.random() < p


# ---------------------------------------------------------------------------
# 2. 物种定义（14 种常驻 + 蜻蜓成虫隐形变量）
# ---------------------------------------------------------------------------
# 字段：
#   space          空间：水中/水面/水底/岸边/空中
#   trophic        营养级：producer/primary/secondary/apex/decomposer
#   birth_rate     基础内禀增长率（每回合）
#   death_rate     基础自然死亡率（每回合）
#   max_capacity   环境承载上限 K（基准值，随环境调整）
#   food_sources   食物来源（物种名列表，producer 为环境驱动留空）
#   predation      捕食效率（对 food_sources 的转化系数）
#   init           新局初始数量
#   lifecycle      变态机制（可选）：dict(stage_days, into, ratio)

SPECIES = {
    # ---- 生产者 ----
    "水藻": {
        "space": "水中", "trophic": "producer",
        "birth_rate": 0.35, "death_rate": 0.05, "max_capacity": 1000,
        "food_sources": [], "predation": 0.0, "init": 200,
    },
    "浮萍": {
        "space": "水面", "trophic": "producer",
        "birth_rate": 0.35, "death_rate": 0.04, "max_capacity": 280,
        "food_sources": [], "predation": 0.0, "init": 20,
    },
    "芦苇": {
        "space": "岸边", "trophic": "producer",
        "birth_rate": 0.10, "death_rate": 0.02, "max_capacity": 150,
        "food_sources": [], "predation": 0.0, "init": 30,
    },
    # ---- 初级消费者 ----
    "水蚤": {
        # 核心饲料生物：全场最高繁殖率 + 大承载量，数量震荡最明显
        "space": "水中", "trophic": "primary",
        "birth_rate": 0.55, "death_rate": 0.12, "max_capacity": 1000,
        "food_sources": ["水藻"], "predation": 0.0006, "init": 100,
    },
    "田螺": {
        # 浮萍的天然制约：对浮萍取食效率远高于水藻，压住水面覆盖率
        "space": "水底", "trophic": "primary",
        "birth_rate": 0.08, "death_rate": 0.03, "max_capacity": 120,
        "food_sources": ["水藻", "浮萍"], "predation": 0.0004, "init": 15,
        "food_efficiency": {"浮萍": 1.0},
        "detritus_feeder": True,
    },
    "蝌蚪": {
        "space": "水中", "trophic": "primary",
        "birth_rate": 0.0, "death_rate": 0.06, "max_capacity": 300,
        "food_sources": ["水藻"], "predation": 0.0005, "init": 0,
        "lifecycle": {"stage_days": 30, "into": "青蛙", "ratio": 0.4},
    },
    "孑孓": {
        # 脏水里很能活：死亡率低；有机碎屑越多繁殖越快（detritus_breeder）
        "space": "水中", "trophic": "primary",
        "birth_rate": 0.30, "death_rate": 0.06, "max_capacity": 500,
        "food_sources": ["水藻"], "predation": 0.0004, "init": 0,
        "detritus_feeder": True, "detritus_breeder": True,
        "lifecycle": {"stage_days": 10, "into": "蚊子", "ratio": 0.6},
    },
    # ---- 次级消费者 ----
    "蜻蜓幼虫": {
        "space": "水底", "trophic": "secondary",
        "birth_rate": 0.0, "death_rate": 0.03, "max_capacity": 120,
        "food_sources": ["水蚤", "蝌蚪", "孑孓"], "predation": 0.0012, "init": 5,
        "lifecycle": {"stage_days": 60, "into": "蜻蜓成虫", "ratio": 0.5, "season_only": "夏"},
    },
    "鲫鱼": {
        "space": "水中", "trophic": "secondary",
        "birth_rate": 0.12, "death_rate": 0.035, "max_capacity": 150,
        "food_sources": ["水蚤", "孑孓", "蜻蜓幼虫"], "predation": 0.0015, "init": 10,
        "needs_oxygen": True,
    },
    "青蛙": {
        # 靠飞虫保底维持：birth*0.3(飞虫保底因子)≈death，能活但繁殖慢；成虫充足时才壮大
        "space": "岸边", "trophic": "secondary",
        "birth_rate": 0.10, "death_rate": 0.03, "max_capacity": 60,
        "food_sources": ["蚊子", "蜻蜓成虫", "飞虫"], "predation": 0.02, "init": 0,
        "spawns": {"into": "蝌蚪", "season": "春", "ratio": 6},
    },
    # ---- 大型杂食鱼 / 其他 ----
    "鲤鱼": {
        # 大型杂食鱼（原顶级捕食者）；翻搅底泥，每天微量增加浑浊度
        "space": "水中", "trophic": "apex",
        "birth_rate": 0.025, "death_rate": 0.02, "max_capacity": 30,
        "food_sources": ["鲫鱼", "淡水虾", "蝌蚪", "水蚯蚓"], "predation": 0.006, "init": 2,
        "needs_oxygen": True, "turbidity_per_day": 0.005,
    },
    # ---- V1.0 扩展：新增 7 种常驻 ----
    "泥鳅": {
        "space": "水底", "trophic": "primary",
        "birth_rate": 0.08, "death_rate": 0.03, "max_capacity": 80,
        "food_sources": ["孑孓", "水蚯蚓"], "predation": 0.0006, "init": 0,
        "detritus_feeder": True,
    },
    "淡水虾": {
        # 碎屑 > 30 时繁殖率 ×1.5（碎屑多时大量现身）
        "space": "水底", "trophic": "primary",
        "birth_rate": 0.12, "death_rate": 0.04, "max_capacity": 120,
        "food_sources": ["水藻"], "predation": 0.0004, "init": 0,
        "detritus_feeder": True,
        "detritus_breed_bonus": {"threshold": 30, "mult": 1.5},
    },
    "河蚌": {
        # 滤食者：每天降浑浊度、扣水蚤、产假粪加碎屑；浑浊/缺氧时死亡率翻倍
        "space": "水底", "trophic": "primary",
        "birth_rate": 0.02, "death_rate": 0.02, "max_capacity": 15,
        "food_sources": [], "predation": 0.0, "init": 0,
        "filter_feeder": True,
    },
    "水黾": {
        # 浮萍覆盖率 > 0.7 时死亡率翻倍（没有活动空间）
        "space": "水面", "trophic": "secondary",
        "birth_rate": 0.10, "death_rate": 0.04, "max_capacity": 60,
        "food_sources": ["蚊子", "飞虫"], "predation": 0.01, "init": 0,
        "cover_death_penalty": {"threshold": 0.7, "mult": 2.0},
    },
    "睡莲": {
        # 与浮萍共同计算水面覆盖率；为青蛙提供栖息加成（繁殖率 ×1.3）
        "space": "水面", "trophic": "producer",
        "birth_rate": 0.06, "death_rate": 0.02, "max_capacity": 80,
        "food_sources": [], "predation": 0.0, "init": 0,
    },
    "蟾蜍": {
        # 比青蛙耐：干旱不受影响、冬季不休眠
        "space": "岸边", "trophic": "secondary",
        "birth_rate": 0.06, "death_rate": 0.02, "max_capacity": 20,
        "food_sources": ["蚊子", "蜻蜓成虫", "飞虫", "水黾"], "predation": 0.02, "init": 0,
        "drought_immune": True, "no_hibernate": True,
    },
    "水蚯蚓": {
        # 碎屑 > 50 时繁殖率 ×2；加速碎屑分解（每天额外耗碎屑 1.0 → 营养盐 0.5）
        "space": "水底", "trophic": "primary",
        "birth_rate": 0.15, "death_rate": 0.05, "max_capacity": 200,
        "food_sources": [], "predation": 0.0, "init": 0,
        "detritus_feeder": True, "detritus_breeder": True,
        "detritus_breed_bonus": {"threshold": 50, "mult": 2.0},
    },
    "田鼠": {
        # 哺乳动物自繁殖
        "space": "岸边", "trophic": "primary",
        "birth_rate": 0.08, "death_rate": 0.05, "max_capacity": 40,
        "food_sources": ["芦苇"], "predation": 0.0008, "init": 5,
    },
    "细菌": {
        "space": "水底", "trophic": "decomposer",
        "birth_rate": 0.50, "death_rate": 0.20, "max_capacity": 2000,
        "food_sources": [], "predation": 0.0, "init": 100,
    },
    # ---- 隐形变量：蜻蜓成虫、蚊子 ----
    "蜻蜓成虫": {
        "space": "空中", "trophic": "secondary", "hidden": True,
        "birth_rate": 0.0, "death_rate": 0.15, "max_capacity": 80,
        "food_sources": [], "predation": 0.0, "init": 0,
        "autumn_spawn": {"into": "蜻蜓幼虫", "season": "秋", "ratio": 1.5},
    },
    "蚊子": {
        "space": "空中", "trophic": "primary", "hidden": True,
        "birth_rate": 0.10, "death_rate": 0.25, "max_capacity": 600,
        "food_sources": [], "predation": 0.0, "init": 0,
    },
}

# 别名（容错召唤）
ALIASES = {
    "藻": "水藻", "海藻": "水藻", "绿藻": "水藻",
    "蚊子幼虫": "孑孓", "蚊幼虫": "孑孓", "孑孒": "孑孓",
    "青蛙幼体": "蝌蚪",
    "蜻蜓": "蜻蜓幼虫",
    "鱼": "鲫鱼", "鲫鱼": "鲫鱼",
    "螺": "田螺", "蜗牛": "田螺",
    "老鼠": "田鼠",
}

RESIDENT_SPECIES = [k for k, v in SPECIES.items() if not v.get("hidden")]

# ---------------------------------------------------------------------------
# 2b. 定居者（Settlers）模板
# ---------------------------------------------------------------------------
# 通过随机事件到来、玩家收留后加入。按个体管理（age/health），不繁殖。

SETTLER_TYPES = {
    "流浪乌龟": {"max_age": 90, "daily_food": {"水藻": 2, "鲫鱼": 1}},
    # daily_food 中的 "有机碎屑" 特殊处理：从环境 detritus 扣除
    "螃蟹": {"max_age": 120, "daily_food": {"田螺": 1, "河蚌": 0.5, "有机碎屑": 2},
            "turbidity_per_day": 0.01},
    "水蛇": {"max_age": 150, "daily_food": {"鲫鱼": 1, "青蛙": 0.5}},
    "野鸭": {"max_age": 180, "daily_food": {"浮萍": 3, "孑孓": 2},
            "detritus_per_day": 2.0, "nutrients_per_day": 1.0},
    # 访客变常驻
    "翠鸟": {"max_age": 200, "daily_food": {"鲫鱼": 1}, "prob_food": 0.6},
    "苍鹭": {"max_age": 180, "daily_food": {"鲫鱼": 2, "泥鳅": 1},
            "on_settle_flag": "heron_resident"},
}

# 定居者叙事文案（到来 / 饥饿离开 / 年迈离开 + 各自的年鉴记录）
SETTLER_TEXT = {
    "流浪乌龟": {
        "arrive_chron": "流浪乌龟住了下来，成为池塘的一部分。",
        "starve": "流浪乌龟找不到食物，缩进壳里，慢慢爬离了池塘。",
        "age": "年迈的流浪乌龟在一个清晨悄然离去，水面恢复了平静。",
    },
    "螃蟹": {
        "arrive_chron": "螃蟹在池塘住了下来。",
        "starve": "螃蟹翻遍水底也找不到足够的食物，拖着空空的壳，爬出了池塘。",
        "age": "老螃蟹在一个秋日里慢慢爬到岸边，缩进石缝，再也没有出来。",
        "starve_chron": "螃蟹找不到食物，拖着空壳爬出了池塘。",
        "age_chron": "老螃蟹在一个秋日里缩进石缝，再也没有出来。",
    },
    "水蛇": {
        "arrive_chron": "水蛇在池塘住了下来，成了最安静的住客。",
        "starve": "水蛇守了多日，再找不到足够的猎物，终于滑入芦苇深处，再也没有盘回来。",
        "age": "那条水蛇在一个清晨缓缓滑向岸边，钻进草丛，池塘失去了它最安静的住客。",
        "starve_chron": "水蛇找不到猎物，滑入了芦苇深处。",
        "age_chron": "水蛇在某个清晨离去，池塘的水面再也不见那道细长的波纹。",
    },
    "野鸭": {
        "arrive_chron": "一对野鸭在池塘住了下来，筑了巢。",
        "starve": "池塘的食物养不活这对野鸭了。它们在某天清晨起飞，再也没有降落。",
        "age": "那只年老的野鸭在一个秋日悄然离群，独自飞向南方，再也没有回来。",
        "starve_chron": "野鸭找不到足够的食物，起飞离去了。",
        "age_chron": "老野鸭在秋日离群南飞，再也没有回来。",
    },
    "翠鸟": {
        "arrive_chron": "翠鸟在枯枝上筑了巢，从此池塘多了一道蓝影。",
        "starve": "翠鸟在枝头等了许久。水里再也没有合适的鱼影浮上，它终于飞走了，枯枝上空出一截。",
        "age": "翠鸟的羽毛不如从前蓝了。一个清晨，它最后一次从枯枝上俯冲入水，然后飞向远方，没有再回来。",
        "starve_chron": "翠鸟飞走了，枯枝上空了一截。",
        "age_chron": "老翠鸟最后一次俯冲入水，飞向了远方。",
    },
    "苍鹭": {
        "arrive_chron": "苍鹭在岸边搭了巢，成了池塘最从容的住客。",
        "starve": "浅水里的鱼越来越少了。苍鹭在岸边站了一整天，终于展开宽大的翅膀，朝远方飞去。",
        "age": "老苍鹭的动作越来越慢。某个冬日它蜷缩在巢边，天亮时已经不动了。水面上再没有那个从容的倒影。",
        "starve_chron": "苍鹭离开了，浅水里再也看不到那个安静的倒影。",
        "age_chron": "老苍鹭在冬日的巢边静卧而去。",
    },
}

# 翠鸟定居者捕食成功 / 失败文案
KINGFISHER_HIT = [
    "翠鸟俯冲入水，叼出一条鲫鱼，鱼尾在它喙里甩了几下便不再动了。",
    "水面炸开一圈水花，翠鸟衔着鱼回到枝头，仰头将鱼顺进喉咙。",
]
KINGFISHER_MISS = [
    "翠鸟扎进水里，又空空地窜回来，抖掉羽上的水珠，重新盯住水面。",
    "它扑了个空。水花散去，翠鸟落在枝头，偏了偏头，像是没想明白。",
]

# ---------------------------------------------------------------------------
# 2c. 决策事件（choose 机制）
# ---------------------------------------------------------------------------
# 触发时设置 pending_choice，等待玩家 choose。default 为连续 3 天不选时的默认项（1-based）。
# 实际效果在 _resolve_choice 中按 key 分支处理。

# requires：触发前提（列表中任一物种当前存在才触发；空表示无前提）。
# desc_tmpl：含 {targets} 占位的动态描述，按实际在场目标填充，避免"盯上不存在的猎物"。
CHOICE_EVENTS = {
    "蛇": {
        "desc": "一条水蛇无声地切开水面，头探向岸边的草丛。",
        "desc_tmpl": "一条水蛇无声地切开水面，头探向草丛里的%s。",
        "requires": ["青蛙", "田鼠"],
        "choices": ["把它赶走", "不去干预", "保持距离观察"],
        "default": 2,
        "title": "水蛇来访",
    },
    "苍鹭": {
        "desc": "一只苍鹭立在浅水里，脖颈弯成一道弓，长喙对准水面。",
        "requires": ["鲫鱼"],
        "choices": ["挥手吓走它", "让它捕食"],
        "default": 2,
        "title": "苍鹭来访",
    },
    "流浪乌龟": {
        "desc": "池边多了一团暗影。龟壳覆着干泥，脖子慢慢伸出来，朝向水面。",
        "requires": [],
        "choices": ["收留它", "让它离开"],
        "default": 2,
        "title": "流浪乌龟来访",
    },
    "水獭": {
        "desc": "一道油亮的影子滑入水中，水獭的眼睛在水面下闪动。",
        "requires": ["鲫鱼", "鲤鱼"],
        "choices": ["想办法留住它", "任其离开"],
        "default": 2,
        "title": "水獭来访",
    },
    "暴雨": {
        "desc": "天暗下来，云层压得很低，空气里满是雨腥气。",
        "requires": [],
        "choices": ["提前加固堤岸", "顺其自然"],
        "default": 2,
        "title": "暴雨",
    },
    "干旱": {
        "desc": "日光一天天晒着，水面缓慢退下，露出一圈干裂的泥岸。",
        "requires": [],
        "choices": ["引水补充", "静观其变"],
        "default": 2,
        "title": "干旱",
    },
    "热浪": {
        "desc": "热空气压着池塘，水面不闪动了，水底在变闷。",
        "requires": [],
        "choices": ["为池塘遮荫降温", "硬扛过去"],
        "default": 2,
        "title": "热浪",
    },
    # ---- V1.0 扩展：新增决策事件 ----
    "白鹭": {
        "desc": "一只白鹭踏入浅水，长腿抬得很慢，目光扫过泥底。它在找泥鳅和河蚌。",
        "requires": ["泥鳅", "河蚌"],
        "choices": ["驱赶", "放任"],
        "default": 2,
        "title": "白鹭来访",
    },
    "洪水": {
        "desc": "暴雨连下数日，上游的水翻涌而下。池塘正在被淹没，浑浊的洪水冲了进来。",
        "requires": [],
        "choices": ["加固堤岸", "开放引入"],
        "default": 1,
        "title": "洪水",
    },
    "水华": {
        "desc": "水面被一层黏稠的绿藻封住了，光透不下去。水下闷得发慌，气泡从藻缝里艰难地冒出来。",
        "requires": [],
        "choices": ["紧急清理", "等待自然恢复"],
        "default": 2,
        "title": "水华",
    },
    "螃蟹": {
        "desc": "一只螃蟹从浑水里横着爬了出来，挥着一对大钳子，站在岸边，像是在打量这个新世界。",
        "requires": [],
        "choices": ["收留它", "让它离开"],
        "default": 2,
        "title": "螃蟹来访",
    },
    "野鸭": {
        "desc": "一对野鸭在池塘降落，绕着水面游了好几圈。它们没有飞走的意思，像是在找地方留下来。",
        "requires": [],
        "choices": ["欢迎留下", "让它们继续迁徙"],
        "default": 2,
        "title": "野鸭定居",
    },
    "翠鸟定居": {
        "desc": "这是翠鸟第五次停在那根枯枝上了。今天它没有急着俯冲，而是歪着头，打量着枝杈间的位置。",
        "requires": [],
        "choices": ["让它留下筑巢", "让它自行决定"],
        "default": 2,
        "title": "翠鸟定居",
    },
    "苍鹭定居": {
        "desc": "苍鹭第三次来的时候没有捕鱼。它衔着一根枯枝，放在岸边的高草丛里。然后它又衔来第二根。",
        "requires": [],
        "choices": ["欢迎它安家", "赶走它"],
        "default": 2,
        "title": "苍鹭定居",
    },
}

# 决策事件冷却天数：同类事件至少间隔这么多天才会再次触发
CHOICE_COOLDOWN = 10
# 跨类型全局冷却：任意决策结算后，这么多天内不触发任何新决策
CHOICE_GLOBAL_COOLDOWN = 3

# ---------------------------------------------------------------------------
# 2d. 造物名册发现制（解锁条件 + 叙述）
# ---------------------------------------------------------------------------
# 每项：(物种, 条件函数(state)->bool, 发现叙述)
# 条件用历史最大值字典 max_seen 判断"曾经超过"，不会回退。

STARTER_SPECIES = ["水藻", "浮萍", "芦苇"]


def _discovery_rules():
    def maxs(s, n):
        return s["max_seen"].get(n, 0)

    return [
        ("水蚤", lambda s: maxs(s, "水藻") > 200,
         "水藻深处，有什么极小的东西在跳动，影子碎碎地晃。"),
        ("田螺", lambda s: maxs(s, "水藻") > 200,
         "石头上多出几道浅浅的爬痕，蜗壳缓缓移动。"),
        ("孑孓", lambda s: maxs(s, "有机碎屑") > 20,
         "水面浮着一群细小的扭动，被光一照，投下怪异的影。"),
        ("鲫鱼", lambda s: maxs(s, "水蚤") > 150,
         "水蚤群中，一道银光一闪，旋即隐去。"),
        ("蜻蜓幼虫", lambda s: s["populations"].get("水蚤", 0) > 10
         and s["populations"].get("孑孓", 0) > 10,
         "淤泥里伏着一样东西，只有眼睛露出来。"),
        ("青蛙", lambda s: s["populations"].get("蚊子", 0) > 0
         or s["populations"].get("蜻蜓成虫", 0) > 0,
         "暮色中，一声短促的蛙鸣试探般响起，随后沉默了。"),
        ("田鼠", lambda s: maxs(s, "芦苇") > 15,
         "芦苇间多出几条细细的通道，草茎被压弯又弹回。"),
        ("鲤鱼", lambda s: maxs(s, "鲫鱼") > 30,
         "深水里荡开一圈涟漪，宽大、缓慢，底下有什么在转身。"),
        # ---- V1.0 扩展：新增 7 种发现规则 ----
        ("泥鳅", lambda s: maxs(s, "有机碎屑") > 40,
         "水底一团浑雾散去，泥里钻出几条滑溜溜的影子，又钻进另一片浑雾里。"),
        ("淡水虾", lambda s: s["populations"].get("田螺", 0) > 20
         and s["populations"].get("水蚤", 0) > 20,
         "石缝里有什么透明的东西弹了一下。又一下。一只淡水虾倒退着隐回暗处。"),
        ("河蚌", lambda s: s["flags"].get("clear_ever", False)
         and s["flags"].get("clear_streak", 0) >= 20,
         "淤泥上隆起一小块，壳缝微张。水从那里流进去，又从另一边流出来，变得更清。"),
        ("水黾", lambda s: _surface_cover(s) < 0.5
         and (s["populations"].get("蚊子", 0) > 0
              or s["populations"].get("蜻蜓成虫", 0) > 0),
         "水面被踩出一圈圈细密的水印，几只长腿的虫子在水上滑行，如履平地。"),
        ("睡莲", lambda s: s["flags"].get("lily_streak", 0) >= 30,
         "水面冒出一片圆叶，卷着边，慢慢摊开。几天后，一朵白花开在圆叶旁边。"),
        # 蟾蜍只在经历干旱后解锁，采用"干旱后现身"的特殊叙述
        ("蟾蜍", lambda s: s["flags"].get("experienced_drought", False),
         "干裂的泥地里，一道裂缝在慢慢扩大。一只蟾蜍从裂缝里爬出来，满身是干土，眨了眨眼。"),
        ("水蚯蚓", lambda s: maxs(s, "有机碎屑") > 60,
         "淤泥表面蠕动着一团红色的细丝。凑近看，是无数的水蚯蚓，密密麻麻地扭动。"),
    ]


DISCOVERY_RULES = _discovery_rules()

# folio 中未发现物种的模糊线索（不直白）
FOLIO_CLUES = {
    "水蚤": "水里的绿意足够浓时，它们才会现身。",
    "田螺": "身负重壳，贴着水底行走。",
    "孑孓": "浑水里，它们悬在表面扭动。",
    "鲫鱼": "许多细小的活物是它的食粮。",
    "蜻蜓幼虫": "在水下潜伏，出击快如弹射。",
    "青蛙": "当空中有飞虫，蛙声才会响起。",
    "田鼠": "岸上的草丛要密到能藏住它。",
    "鲤鱼": "它需要一层又一层的食物垫在下面。",
    "泥鳅": "据说底层的腐土里，藏着一种善钻的影子。",
    "淡水虾": "它藏在水底的石缝间，要等碎屑堆积才会成群现身。",
    "河蚌": "水底埋着沉默的壳，水经过它便清了几分。",
    "水黾": "它需要一片不被浮萍盖满的水面，才能在水上行走。",
    "睡莲": "它需要浮萍和绿藻在水里共存久了，才会从水底升起。",
    "蟾蜍": "经历过干旱的池塘，才会从裂缝里爬出这种比青蛙更能忍的住客。",
    "水蚯蚓": "腐物堆积的水底，会有红色的细虫成团蠕动。",
}

# ---------------------------------------------------------------------------
# 2e. gaze（凝视）微观描写模板
# ---------------------------------------------------------------------------
# 每个条件至少 3 套文案，按 PRNG 随机选，连续 gaze 不会完全重复。后续可持续扩充。

GAZE_SEASON = {
    "春": [
        "春日的光斜斜铺下，水面碎成一片金光。",
        "水还凉着，岸边的嫩芽带一点透明的绿。",
        "湿润的草气浮在空气里，涟漪懒懒地散开又消失。",
    ],
    "夏": [
        "正午的热气压着水面，蒸出黏糊糊的水汽。",
        "烈日把水晒得温热，阴影里也躲着暑气。",
        "蝉声从草丛涌起，水面白得晃眼。",
    ],
    "秋": [
        "枯叶旋落，水面接住它，秋光淡了。",
        "凉风擦过水面，把最后一丝热也带走了。",
        "午后光线如蜜，水面静止，像一面旧铜镜。",
    ],
    "冬": [
        "池边凝着冰凌，吐息在空中结成白气。",
        "天光灰白，池水沉暗，冰冷刺骨。",
        "寒意自水底升起，池塘的呼吸慢了下来。",
    ],
}

GAZE_ENV = {
    "low_do": [
        "水面浮着细密的气泡，沉闷像一层膜盖着。",
        "水色发暗，鱼嘴探出水面，急促地张合。",
        "水底积着浊气，水草低垂，无精打采。",
    ],
    "cover": [
        "浮萍盖满水面，底下是幽绿的昏暗。",
        "浮萍遮住阳光，水下只剩几点浑浊的光斑。",
        "绿毯铺满，深处的黑暗纹丝不动。",
    ],
    "turbid": [
        "水浑如米汤，水下的动静模糊不清。",
        "泥沙悬着，光线只透得下半尺。",
        "浑黄里，影子都软了，轮廓模糊。",
    ],
    "clear": [
        "水清见底，水草的每一丝摆动都看得分明。",
        "阳光探到水底，沙石上小生命游过。",
        "水像通透的琥珀，把万物凝固其中。",
    ],
}

GAZE_SUBJECT = {
    "水藻": [
        "水藻成片摇曳，光线穿过它们，碎成绿影。像水底的森林。",
        "绿丝上挂着气泡，一串串，向水面升去。",
        "日光照透，水藻泛着幽幽翠色，缓缓舒展。",
    ],
    "浮萍": [
        "浮萍挤挤挨挨，随细浪碰撞，分开，又聚拢。",
        "几片浮萍打旋，影子在水面碎成光斑。",
        "绿毯上水珠滚动，偶尔一闪。",
    ],
    "芦苇": [
        "风梳过芦苇，它们齐齐伏低。",
        "芦苇沙沙响，空茎在风里低咽。",
        "长影落水，随波纹轻轻晃动。",
    ],
    "水蚤": [
        "水蚤成群跳动，细小的身子一弹一弹。",
        "光柱里，水蚤浮沉，密得水都活了。",
        "它们撞上水草，匆忙散开，又聚回。",
    ],
    "田螺": [
        "田螺爬过石面，黏液痕微微发亮。",
        "田螺慢慢刮食苔藓，石头露出一小块灰白。",
        "几只螺凝固不动，像嵌在时间里的石子。",
    ],
    "孑孓": [
        "孑孓倒悬水下，一受惊，陡然扭动下沉。",
        "成片孑孓屈伸游动，浅水微微发颤。",
        "水面上，无数小尾巴轻轻摆动。",
    ],
    "蝌蚪": [
        "黑豆般的蝌蚪挤在暖水边，尾巴甩动。",
        "一团墨迹似的蝌蚪在水中缓缓移动。",
        "蝌蚪笨拙拐弯，圆脑袋轻碰。",
    ],
    "蜻蜓幼虫": [
        "淤泥里，一双凸眼警觉地转动。",
        "捕肢弹出，水蚤消失，只余一点浑迹。",
        "它贴着水草缓缓挪动，影子拖在身后。",
    ],
    "鲫鱼": [
        "一群鲫鱼倏地转向，银亮的鳞片同时翻起一片光。",
        "鲫鱼们贴着水草穿梭，时聚时散，警觉又灵活。",
        "几条鲫鱼在水中悬停，鳃盖一开一合地轻轻搏动。",
        "鲫鱼侧扁的身子一闪，银鳞在光线里亮了一下，又暗了。",
        "一条鲫鱼啃着水藻，嘴唇一张一合，尾鳍轻轻摆着。",
    ],
    "青蛙": [
        "青蛙蹲在浮萍上，鼓着腮，目光定在水面。",
        "低沉的蛙鸣荡开水面，圆纹一圈圈散去。",
        "青蛙蹬腿入水，几秒后冒出两只眼睛。",
    ],
    "鲤鱼": [
        "一条鲤鱼的暗影从深处缓缓掠过，鲫鱼群散开又聚拢。",
        "鲤鱼拱进底泥，尾巴翘出水面，搅起一团浑雾，良久才散。",
        "深水里，鲤鱼翻了个身，鳞光一闪，又沉进浑暗里。",
    ],
    "田鼠": [
        "草丛窸窣，一颗小脑袋探出来，又缩回去。",
        "田鼠沿苇根窜过，细碎的脚印留在湿泥上。",
        "深处的草茎轻轻晃动，田鼠正在啃咬。",
    ],
    "蚊子": [
        "蚊子贴水面打转，嗡鸣细若游丝。",
        "暮色中，蚊蚋升腾，如薄雾织在水面之上。",
        "蚊子歇在芦苇尖，风一过，惊飞。",
    ],
    "蜻蜓成虫": [
        "蜻蜓掠过水面，翅翼闪出虹光。",
        "它在芦苇间盘旋，轻点水面，倏然远去。",
        "蜻蜓停在枝头，纹丝不动，晒着薄翅。",
    ],
    # ---- V1.0 扩展：新增 7 种凝视文案 ----
    "泥鳅": [
        "泥鳅从淤泥里探出半截身子，胡须轻轻摆动，又倏地缩回去。",
        "一条泥鳅扭着身子钻进泥里，留下一串细密的气泡。",
        "几条泥鳅在腐叶间穿梭，搅起一小团浑雾，又缓缓沉降。",
    ],
    "淡水虾": [
        "一只淡水虾倒着弹了一下，透明的身子在水里几乎看不见。",
        "石缝里探出两根细长的触须，轻轻扫过水流。",
        "几只虾聚在腐叶上，小钳子忙碌地夹取着什么。",
    ],
    "河蚌": [
        "河蚌半埋在泥里，壳缝微微张开，吐出一线清水。",
        "一只河蚌缓缓沉入更深的泥里，只露一道弧形的壳沿。",
        "蚌壳翕动，一闭一合之间，泥面上多了几粒细小的假粪。",
    ],
    "水黾": [
        "水黾的长腿在水面压出几个浅浅的凹坑，身子悬在光与水的交界。",
        "一只落水的蚊虫挣扎，水黾滑过去，转眼就收了它的挣扎。",
        "几只水黾同时转向，水面上一圈圈涟漪碰撞、交错、散开。",
    ],
    "睡莲": [
        "睡莲的圆叶铺在水面，边缘微微卷起，水珠在上面滚动。",
        "一朵白花开在莲叶间，花瓣张开，迎着午后的光。",
        "青蛙蹲在睡莲叶上，一动不动，叶子只是微微沉了一下。",
    ],
    "蟾蜍": [
        "蟾蜍趴在泥地里，粗糙的皮肤和干泥几乎分不清。",
        "夜色里，一声闷闷的呱叫从岸边传来，短促，低沉。",
        "蟾蜍慢慢爬过干裂的泥岸，身后留下一行浅浅的拖痕。",
    ],
    "水蚯蚓": [
        "水蚯蚓成团地在泥面上蠕动，红色的细丝缠在一起，又散开。",
        "一条水蚯蚓从泥里探出，轻轻摆动，像是在试探水里的味道。",
        "淤泥表面覆着一层细密的红，微微颤动，仿佛水底在呼吸。",
    ],
}

# 苍鹭来访后 2 天，鲫鱼/鲤鱼凝视优先抽取"躲藏"变体
GAZE_FISH_HIDE = {
    "鲫鱼": [
        "鲫鱼藏在暗处，偶见一道银光闪过又消失。水草轻轻晃动，又归于静止。",
        "水草丛深处，几尾鲫鱼挤在一起，鳃盖翕动，却不游出来。",
        "浅水里空了。只有几道影子在暗处移动，小心翼翼的。",
    ],
    "鲤鱼": [
        "鲤鱼沉在池底最深处，一动不动，暗影融进了更暗的水底。",
        "那条大鲤鱼把自己埋进淤泥里，只露出脊背的轮廓。",
        "深水里什么也看不见。鲤鱼的暗影消失了，仿佛它也成了水底的一部分。",
    ],
}

# look 指令的物种风味描述（覆盖改名物种与新增物种）
LOOK_DESC = {
    "鲫鱼": "杂食鱼，吃水蚤也啃水藻。身子侧扁，银鳞闪亮，成群游动。",
    "鲤鱼": "大型杂食鱼，拱翻底泥找食，也吃小鱼。每一次翻身都搅浑一片水。",
    "泥鳅": "底栖鱼，在淤泥里钻行，吃有机碎屑和孑孓。身子滑溜，胡须探路。",
    "淡水虾": "底栖杂食，躲石缝，碎屑多时现身。身子透明，遇险就弹走。",
    "河蚌": "过滤者，沉在水底滤食浮游生物。让水变清，假粪沉入淤泥喂底层。",
    "水黾": "水面昆虫，长腿在水面滑行，吃落水的小虫。浮萍太密就没有路可走。",
    "睡莲": "水面植物，圆叶铺开，夏开白花。跟浮萍争水面，给青蛙一个歇脚的地方。",
    "蟾蜍": "两栖，比青蛙耐旱，趴在泥地里。夜里闷声叫，吃蚊子和飞虫。",
    "水蚯蚓": "分解者，在淤泥里蠕动，加速碎屑分解。碎屑越多，它们越多。",
}

# gaze 主体候选顺序（实际按在场随机抽取，不依赖顺序）
GAZE_SUBJECT_ORDER = list(GAZE_SUBJECT.keys())

GAZE_SETTLER = {
    "流浪乌龟": [
        "乌龟在角落慢慢啃食水藻，壳上映着水光。",
        "它趴在半露的石上，伸长脖子，四望。",
        "四肢划水，圆壳慢慢没入暗处。",
    ],
    "螃蟹": [
        "螃蟹从石缝里横着挪出来，一只大钳子拖在身后，另一只举在前面。",
        "螃蟹翻开一块石头，底下的泥鳅慌忙窜出，又被螃蟹的钳子吓了回去。",
        "它在水底横行，搅起一小片泥沙，又停下来，吐出一串气泡。",
    ],
    "水蛇": [
        "水蛇盘在芦苇根部，头枕在自己的身体上，鳞片微微起伏。",
        "一条水蛇悄无声息地切开水面，头探向岸边，又慢慢收回去。",
        "芦苇丛里，水蛇正蜕下旧皮，半透明的蛇蜕挂在枯茎上轻轻晃动。",
    ],
    "野鸭": [
        "一对野鸭并排游过水面，颈子一前一后地摆动，身后留下两道展开的波纹。",
        "野鸭把头埋进水里，尾巴朝天翘起，过了一会儿才甩着水珠冒出来。",
        "芦苇丛边，母鸭伏在巢上，公鸭在附近慢慢游着，像在站岗。",
    ],
    "翠鸟": [
        "翠鸟蹲在枯枝上，缩着脖子，羽毛被逆光打出一圈蓝边。",
        "一道蓝影垂直扎入水面，碎光溅起。翠鸟叼着银亮的小鱼冲回枝头。",
        "翠鸟歪过头，用喙梳理胸前的羽毛，一下一下，不紧不慢。",
    ],
    "苍鹭": [
        "苍鹭站在浅水里，长颈微曲，整个身子像一尊静物。水面纹丝不动，它的影子也纹丝不动。",
        "苍鹭缩起一条腿，独自立在岸边，风吹过羽毛也不抖一下。",
        "苍鹭在岸边慢慢走动，长腿抬起、落下，每一步都像经过计算。水里的倒影跟着它无声地移动。",
    ],
}

GAZE_EMPTY = [
    "池塘空着。天光落在水面，没有动静。",
    "静水无生命，只有微尘在光柱里浮沉。",
    "水如镜，深处沉默，还在等第一个住客。",
]

# ---------------------------------------------------------------------------
# 3. 环境与季节
# ---------------------------------------------------------------------------

SEASONS = ["春", "夏", "秋", "冬"]
SEASON_LEN = 30
YEAR_LEN = SEASON_LEN * 4

SEASON_ENV = {
    # 目标基准值（tick 中向其缓动）
    "春": {"water_temp": 18, "light": 0.85, "desc": "光斜斜照进来，水开始暖了。"},
    "夏": {"water_temp": 28, "light": 1.0,  "desc": "日光白得晃眼，水面蒸起一层薄薄的热气。"},
    "秋": {"water_temp": 16, "light": 0.7,  "desc": "一片黄叶落在水面上，光变软了。"},
    "冬": {"water_temp": 6,  "light": 0.45, "desc": "寒气从水面蔓延到池底，冰凌在岸边聚拢。"},
}


def season_of(turn):
    return SEASONS[(turn // SEASON_LEN) % 4]


# ---------------------------------------------------------------------------
# 4. 成就
# ---------------------------------------------------------------------------

ACHIEVEMENTS = {
    "初生之池": "首次投放物种",
    "食物链初成": "同时存在生产者、消费者、捕食者",
    "稳定生态": "连续 30 天无物种归零",
    "生物多样性": "同时存在 8 种以上物种",
    "大丰收": "鲤鱼数量达到 5 条以上",
    "蛙鸣之夜": "青蛙数量达到 10 只以上",
    "蚊灾": "蚊子数量失控超过阈值",
    "翻塘": "经历一次溶氧暴跌导致的大规模死亡",
    "四季轮回": "经历完整的一年（120 回合）",
    "萤光之夜": "触发萤火虫大爆发事件",
    "不速之客": "流浪乌龟定居池塘",
    "造物主的耐心": "连续 100 天不做任何干预",
    # ---- V1.0 扩展：新增 5 个成就 ----
    "仙鹤降临": "在薄雾中见到了仙鹤",
    "水下花园": "睡莲和水藻共存超过 30 天",
    "底栖王国": "泥鳅、水蚯蚓、河蚌同时存在",
    "水华危机": "经历了一次水华",
    "共生之池": "同时存在 15 种以上物种",
}


# ---------------------------------------------------------------------------
# 5. 游戏状态
# ---------------------------------------------------------------------------

def fresh_state(seed):
    # 空池起步：除自带的分解者细菌外，所有物种初始为 0，玩家自行 summon 建设
    pops = {name: 0.0 for name in SPECIES}
    pops["细菌"] = float(SPECIES["细菌"]["init"])
    # 变态计时器：记录各阶段生物的"队列"（按投放/出生回合分批），简化为平均年龄
    return {
        "version": 2,
        "seed": int(seed),
        "rng_state": int(seed) & 0xFFFFFFFF,
        "turn": 0,
        "populations": pops,
        "env": {
            # 干净淡水初始值
            "water_temp": 18.0,      # ℃
            "dissolved_oxygen": 9.0, # mg/L（清水溶氧充足）
            "light": 0.85,           # 0~1 相对光照
            "nutrients": 15.0,       # 营养盐（贫营养）
            "detritus": 0.0,         # 有机碎屑（无沉积）
            "turbidity": 0.05,       # 浑浊度 0~1（清澈）
        },
        # 生命周期年龄池：{物种: [[count, age_days], ...]}
        "cohorts": {name: [] for name in SPECIES if SPECIES[name].get("lifecycle")},
        "season": "春",
        "seen": [],                  # 已出现过的物种（图鉴）
        "achievements": [],          # 已达成成就
        "flags": {
            "days_no_extinction": 0,
            "days_no_intervention": 0,
            "turtle_resident": False,
            # V1.0 扩展：发现制/成就所需的连续天数与历史标记
            "clear_streak": 0,           # 连续清水稳定天数（浊度<0.2 且溶氧>4）
            "clear_ever": False,         # 浑浊度是否曾经 < 0.15
            "lily_streak": 0,            # 浮萍与水藻同时存活的连续天数
            "garden_streak": 0,          # 睡莲与水藻同时存在的连续天数
            "experienced_drought": False,  # 是否经历过干旱
            "duck_visits": 0,            # 迁徙野鸭群累计来访次数
        },
        "log": [],                   # 最近一回合的事件列表
        "pending_pause": None,       # wait 自动暂停原因
        # ---- v4：三层架构 / 发现制 / 万物志 / 年鉴 ----
        "settlers": [],              # 定居者列表（个体）
        "unlocked_species": list(STARTER_SPECIES),   # 已解锁可召唤物种
        "max_seen": {},              # 各物种/碎屑历史最大值（发现制判定）
        "folio": {                   # 万物志四本
            "species": {},           # 物种志：name -> {first_day, first_season, extinct_count, alive}
            "settlers": {},          # 定居者志：name -> {times, max_days}
            "visitors": {},          # 访客志：key -> {count, notes}
            "events": {},            # 事件志：key -> {count, notes}
        },
        "chronicle": [],             # 年鉴：已格式化的时间线文本
        "pending_choice": None,      # 待决策事件 dict，或 None
        "pending_wait_days": 0,      # 决策中断的 wait 剩余天数
        "choice_cooldowns": {},      # 决策事件 -> 上次触发的回合（冷却用）
        "extinct_alerted": [],       # 已就归零提醒过的物种（去重，恢复后清除）
        # V1.0 扩展：连锁叙事计时器 与 解锁冷却
        "chain": {},                 # 连锁效果 -> 生效截止回合
        "last_unlock_turn": -999,    # 上次解锁回合（解锁冷却用）
    }


_STATE = None  # 当前活动状态（内存）


# ---------------------------------------------------------------------------
# 6. 存档 IO
# ---------------------------------------------------------------------------

def save_state(state):
    try:
        with open(SAVE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def load_state():
    global _STATE
    if _STATE is not None:
        return _STATE
    if os.path.exists(SAVE_PATH):
        try:
            with open(SAVE_PATH, "r", encoding="utf-8") as f:
                _STATE = json.load(f)
            _migrate(_STATE)
            return _STATE
        except (OSError, ValueError):
            pass
    _STATE = fresh_state(12345)
    save_state(_STATE)
    return _STATE


def _migrate(state):
    """补齐缺字段，向后兼容旧存档。"""
    base = fresh_state(state.get("seed", 12345))
    for k, v in base.items():
        if k not in state:
            state[k] = v
    for name in SPECIES:
        state["populations"].setdefault(name, float(SPECIES[name]["init"]))
    for k, v in base["env"].items():
        state["env"].setdefault(k, v)
    for k, v in base["flags"].items():
        state["flags"].setdefault(k, v)
    for name in base["cohorts"]:
        state["cohorts"].setdefault(name, [])
    # v4 新增字段：旧存档兼容
    state.setdefault("settlers", [])
    state.setdefault("unlocked_species", list(STARTER_SPECIES))
    state.setdefault("max_seen", {})
    cod = state.setdefault("folio", {})
    for book in ("species", "settlers", "visitors", "events"):
        cod.setdefault(book, {})
    state.setdefault("chronicle", [])
    state.setdefault("pending_choice", None)
    state.setdefault("pending_wait_days", 0)
    state.setdefault("choice_cooldowns", {})
    state.setdefault("extinct_alerted", [])
    state.setdefault("chain", {})
    state.setdefault("last_unlock_turn", -999)


def rng_from(state):
    r = Mulberry32(0)
    r.state = int(state["rng_state"]) & 0xFFFFFFFF
    return r


def commit_rng(state, r):
    state["rng_state"] = int(r.state) & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# 7. 核心模拟 tick()
# ---------------------------------------------------------------------------

def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _surface_cover(state):
    """水面覆盖率：浮萍 + 睡莲 共同计算。"""
    pop = state["populations"]
    c = pop.get("浮萍", 0) / SPECIES["浮萍"]["max_capacity"] \
        + pop.get("睡莲", 0) / SPECIES["睡莲"]["max_capacity"]
    return _clamp(c, 0.0, 1.0)


def _chain_set(state, key, days):
    """开启一段连锁效果，生效至 turn+days。"""
    state.setdefault("chain", {})[key] = state["turn"] + days


def _chain_active(state, key):
    return state["turn"] <= state.get("chain", {}).get(key, -1)


def tick(state):
    """推进一回合，返回本回合事件文字列表。"""
    r = rng_from(state)
    events = []
    pop = state["populations"]
    env = state["env"]

    state["turn"] += 1
    turn = state["turn"]
    season = season_of(turn)
    prev_season = state["season"]
    state["season"] = season
    if season != prev_season:
        events.append("season:" + SEASON_ENV[season]["desc"])
        _chronicle(state, "入%s，%s" % (season, SEASON_ENV[season]["desc"]))

    # --- (1) 环境参数变化 ---
    target = SEASON_ENV[season]
    env["water_temp"] += (target["water_temp"] - env["water_temp"]) * 0.2
    # 水面覆盖率（浮萍 + 睡莲）影响光照
    duckweed_cover = _surface_cover(state)
    # 大雾：光照系数压低（连锁效果，持续约 2 天）
    light_target = target["light"] * (0.3 if _chain_active(state, "fog") else 1.0)
    base_light = light_target * (1 - 0.6 * duckweed_cover) * (1 - 0.5 * env["turbidity"])
    env["light"] += (base_light - env["light"]) * 0.3
    env["light"] = _clamp(env["light"], 0.0, 1.0)
    # 浑浊度自然沉降
    env["turbidity"] = _clamp(env["turbidity"] * 0.9, 0.0, 1.0)
    # 溶氧：温度越高溶氧越低；光合作用（水藻）产氧；覆盖>80%阻断气体交换
    do_sat = _clamp(14.6 - 0.35 * env["water_temp"], 4.0, 14.6)
    photo = 0.002 * pop["水藻"] * env["light"]
    exchange = 1.0 if duckweed_cover < 0.8 else 0.2
    env["dissolved_oxygen"] += ((do_sat - env["dissolved_oxygen"]) * 0.3 * exchange) + photo * 0.01
    env["dissolved_oxygen"] = _clamp(env["dissolved_oxygen"], 0.0, 16.0)

    # --- (2) 生产者 Logistic 增长 ---
    temp_factor = _clamp(1 - abs(env["water_temp"] - 24) / 30, 0.2, 1.0)
    for name in ("水藻", "浮萍", "睡莲", "芦苇"):
        sp = SPECIES[name]
        n = pop[name]
        if n <= 0 and name in ("睡莲",):
            continue  # 未投放的睡莲不生长
        if name == "水藻":
            k = sp["max_capacity"] * env["light"] * _clamp(env["nutrients"] / 50, 0.1, 2.0)
        elif name == "浮萍":
            # 软化季节摆动：K 维持在 cap 的较高比例，避免覆盖率大起大落
            k = sp["max_capacity"] * (0.7 + 0.3 * _clamp(env["nutrients"] / 50, 0.0, 1.0)) \
                * (0.75 + 0.25 * target["light"])
        elif name == "睡莲":
            # 与浮萍类似的水面植物，受营养盐与季节光照影响，但更慢更稳
            k = sp["max_capacity"] * (0.6 + 0.4 * _clamp(env["nutrients"] / 50, 0.0, 1.0)) \
                * (0.7 + 0.3 * target["light"])
        else:  # 芦苇 受季节影响小
            k = sp["max_capacity"] * temp_factor
        k = max(1.0, k)
        growth = sp["birth_rate"] * temp_factor * n * (1 - n / k)
        pop[name] = max(0.0, n + growth - sp["death_rate"] * n)
        if name == "水藻":
            env["nutrients"] = max(0.0, env["nutrients"] - growth * 0.05)

    # --- (3) 捕食（Lotka-Volterra 简化） ---
    consumed_detritus = 0.0
    # 收集捕食意图后统一结算，避免顺序偏差
    deltas = {name: 0.0 for name in SPECIES}
    for name in SPECIES:
        sp = SPECIES[name]
        if not sp["food_sources"] and not sp.get("detritus_feeder"):
            continue
        n = pop[name]
        if n <= 0:
            continue
        eff = sp["predation"] * temp_factor
        food_eff = sp.get("food_efficiency", {})
        for prey in sp["food_sources"]:
            if prey not in pop:
                continue
            peff = eff * food_eff.get(prey, 1.0)
            # 苍鹭定居后，鲫鱼/泥鳅学会躲藏，被捕食系数永久 -20%
            if prey in ("鲫鱼", "泥鳅") and state["flags"].get("heron_resident"):
                peff *= 0.8
            eaten = _clamp(peff * n * pop[prey], 0, pop[prey] * 0.5)
            deltas[prey] -= eaten
            # 转化为捕食者增长
            deltas[name] += eaten * 0.15
        if sp.get("detritus_feeder"):
            d = _clamp(0.0005 * n * env["detritus"], 0, env["detritus"] * 0.3)
            consumed_detritus += d
            deltas[name] += d * 0.05
    env["detritus"] = max(0.0, env["detritus"] - consumed_detritus)
    for name, d in deltas.items():
        pop[name] = max(0.0, pop[name] + d)

    # --- (4) 消费者自然增长 + 自然死亡 ---
    for name in SPECIES:
        sp = SPECIES[name]
        if sp["trophic"] == "producer":
            continue
        n = pop[name]
        if n <= 0:
            continue
        br = sp["birth_rate"] * temp_factor
        # 有食物来源者，繁殖受食物丰度影响：保底 20% 基础繁殖率，食物越多越接近满速
        if sp["food_sources"]:
            # "飞虫" 是隐形保底食物：只要有水草或有机碎屑，飞虫就存在，不计入真实种群
            real_food = sum(pop.get(f, 0) for f in sp["food_sources"] if f != "飞虫")
            factor = 0.2 + 0.8 * _clamp(real_food / (sp["max_capacity"] * 0.5), 0.0, 1.0)
            if "飞虫" in sp["food_sources"]:
                flybugs = pop.get("水藻", 0) > 0 or pop.get("浮萍", 0) > 0 or env["detritus"] > 0
                if flybugs:
                    # 飞虫提供固定 0.3 的食物因子保底；成虫充足时正常计算会更高
                    factor = max(factor, 0.3)
            br *= factor
        # 孑孓等：有机碎屑越多繁殖越快
        if sp.get("detritus_breeder"):
            br *= 1.0 + _clamp(env["detritus"] / 100.0, 0.0, 1.5)
        # 淡水虾/水蚯蚓：碎屑超过阈值时繁殖率跳增
        bonus = sp.get("detritus_breed_bonus")
        if bonus and env["detritus"] > bonus["threshold"]:
            br *= bonus["mult"]
        # 睡莲在场：青蛙获得栖息加成，繁殖率 ×1.3
        if name == "青蛙" and pop.get("睡莲", 0) >= 1:
            br *= 1.3
        # 干旱期间：青蛙繁殖受抑，蟾蜍免疫
        if name == "青蛙" and _chain_active(state, "drought") and not sp.get("drought_immune"):
            br *= 0.85
        # 干旱期间蟾蜍繁殖 ×1.5
        if sp.get("drought_immune") and _chain_active(state, "drought"):
            br *= 1.5
        # 冬季青蛙休眠（繁殖减缓）；蟾蜍不休眠
        if season == "冬" and not sp.get("no_hibernate") and name in ("青蛙",):
            br *= 0.5
        # 水蚯蚓充足时泥鳅食物丰沛，繁殖 ×1.2
        if name == "泥鳅" and pop.get("水蚯蚓", 0) > 100:
            br *= 1.2
        k = sp["max_capacity"]
        births = br * n * (1 - n / max(1.0, k))
        deaths = sp["death_rate"] * n
        # 低溶氧致死
        if sp.get("needs_oxygen") and env["dissolved_oxygen"] < 4.0:
            deaths += n * (4.0 - env["dissolved_oxygen"]) / 4.0 * 0.5
        # 水黾：浮萍覆盖过高没有活动空间，死亡率翻倍
        cdp = sp.get("cover_death_penalty")
        if cdp and _surface_cover(state) > cdp["threshold"]:
            deaths *= cdp["mult"]
        # 青蛙干旱期间死亡率上升（蟾蜍免疫）
        if name == "青蛙" and _chain_active(state, "drought") and not sp.get("drought_immune"):
            deaths *= 1.5
        # 水蛇定居：田鼠不敢出洞，死亡率降低 50%
        if name == "田鼠" and _has_settler(state, "水蛇"):
            deaths *= 0.5
        # 冬季青蛙休眠：代谢降低，死亡率随繁殖一同减缓（蛰伏越冬）
        if season == "冬" and name == "青蛙":
            deaths *= 0.5
        new_n = max(0.0, n + births - deaths)
        # 死亡转化为有机碎屑
        env["detritus"] += (n - new_n) * 0.5 if new_n < n else 0.0
        pop[name] = new_n

    # --- (4b) 物种特殊效果（河蚌滤食 / 水蚯蚓分解 / 鲤鱼翻泥等） ---
    _apply_special_effects(state, events, r)

    # --- (5) 生命周期变态 ---
    _process_lifecycle(state, events, r)
    _process_spawning(state, events, season)

    # --- (6) 细菌分解（消耗溶氧，碎屑→营养盐） ---
    bac = pop["细菌"]
    sp_b = SPECIES["细菌"]
    # 细菌繁殖受碎屑驱动
    food_factor = _clamp(env["detritus"] / 100, 0.0, 2.0)
    bac_k = sp_b["max_capacity"] * food_factor
    bac = bac + sp_b["birth_rate"] * bac * (1 - bac / max(1.0, bac_k)) - sp_b["death_rate"] * bac
    # 细菌是水体自带的基础微生物群落：保留 >=1 的种子，碎屑出现时能重新繁盛，
    # 不会因一时缺乏有机质而彻底消失（否则乘性增长无法从 0 恢复）。
    bac = max(1.0, bac)
    decompose = _clamp(0.002 * bac * env["detritus"], 0, env["detritus"])
    o2_cost = decompose * 0.02
    env["detritus"] -= decompose
    env["nutrients"] += decompose * 0.4
    env["dissolved_oxygen"] = max(0.0, env["dissolved_oxygen"] - o2_cost)
    pop["细菌"] = bac
    # 翻塘判定：碎屑过多 + 细菌爆发 → 溶氧暴跌
    if env["dissolved_oxygen"] < 2.0 and env["detritus"] > 150:
        kill = 0.4
        for name in SPECIES:
            if SPECIES[name].get("needs_oxygen"):
                lost = pop[name] * kill
                pop[name] -= lost
                env["detritus"] += lost * 0.5
        events.append("crisis:水里像被抽走了呼吸，鱼纷纷浮起，白腹朝天。")
        _unlock(state, events, "翻塘")

    # 营养盐缓慢自然流失 / 上限
    env["nutrients"] = _clamp(env["nutrients"], 0.0, 500.0)
    env["detritus"] = _clamp(env["detritus"], 0.0, 1000.0)

    # --- (6b) 定居者摄食 + 衰老（在种群层 LV 计算之后） ---
    _process_settlers(state, events, r)

    # --- (6c) 发现制：刷新历史最大值与连续天数，检查物种解锁 ---
    _update_max_seen(state)
    _update_streaks(state)
    _check_discovery(state, events)
    _folio_update_species(state)

    # --- (7) 随机事件（含决策事件） ---
    _random_events(state, events, r, season)

    # --- 取整种群（保留隐形精度，对外展示用整数）---
    # 内部保留浮点，方便长期演化

    # --- 关键事件检测（供 wait 暂停） ---
    _detect_pause(state, events)

    # --- 成就检测 ---
    _check_achievements(state, events)

    # --- 图鉴：记录出现过的物种 ---
    for name in RESIDENT_SPECIES:
        if pop[name] >= 1 and name not in state["seen"]:
            state["seen"].append(name)

    # --- 连续无归零计数 ---
    extinct_now = any(pop[n] < 1 for n in RESIDENT_SPECIES if n in state["seen"])
    if extinct_now:
        state["flags"]["days_no_extinction"] = 0
    else:
        state["flags"]["days_no_extinction"] += 1

    state["log"] = events
    commit_rng(state, r)
    return events


def _has_settler(state, name):
    return any(s["name"] == name for s in state.get("settlers", []))


def _apply_special_effects(state, events, r):
    """V1.0 扩展物种的特殊环境效果（在 LV 计算之后结算）。"""
    pop = state["populations"]
    env = state["env"]
    # 翻底泥：含 turbidity_per_day 的物种在场则微量增加浑浊度
    for name in SPECIES:
        tpd = SPECIES[name].get("turbidity_per_day")
        if tpd and pop.get(name, 0) >= 1:
            env["turbidity"] = _clamp(env["turbidity"] + tpd, 0.0, 1.0)
    # 河蚌滤食：降浑浊、扣水蚤、产假粪；浑浊或缺氧时额外死亡
    m = pop.get("河蚌", 0)
    if m >= 1:
        scale = min(1.0, m / 10.0)
        env["turbidity"] = max(0.0, env["turbidity"] - 0.02 * scale)
        pop["水蚤"] = max(0.0, pop.get("水蚤", 0) - (1.0 + r.random()) * scale)
        env["detritus"] += 0.5 * scale
        extra = 0.0
        if env["turbidity"] > 0.5:
            extra += m * SPECIES["河蚌"]["death_rate"]
        if env["dissolved_oxygen"] < 3.0:
            extra += m * SPECIES["河蚌"]["death_rate"]
        if extra:
            pop["河蚌"] = max(0.0, m - extra)
    # 水蚯蚓：加速碎屑分解，转化为营养盐
    w = pop.get("水蚯蚓", 0)
    if w >= 1:
        dec = min(env["detritus"], 1.0 * min(1.0, w / 100.0))
        env["detritus"] -= dec
        env["nutrients"] += dec * 0.5


def _update_streaks(state):
    """更新发现制/成就所需的连续天数与历史标记。"""
    f = state["flags"]
    pop = state["populations"]
    env = state["env"]
    if env["turbidity"] < 0.2 and env["dissolved_oxygen"] > 4.0:
        f["clear_streak"] = f.get("clear_streak", 0) + 1
    else:
        f["clear_streak"] = 0
    if env["turbidity"] < 0.15:
        f["clear_ever"] = True
    if pop.get("浮萍", 0) > 0 and pop.get("水藻", 0) > 0:
        f["lily_streak"] = f.get("lily_streak", 0) + 1
    else:
        f["lily_streak"] = 0
    if pop.get("睡莲", 0) > 0 and pop.get("水藻", 0) > 0:
        f["garden_streak"] = f.get("garden_streak", 0) + 1
    else:
        f["garden_streak"] = 0


def _process_lifecycle(state, events, r):
    """处理 cohort 年龄推进与变态。"""
    pop = state["populations"]
    season = state["season"]
    for name, cohorts in state["cohorts"].items():
        sp = SPECIES[name]
        lc = sp["lifecycle"]
        # 把当前未入队的种群数量同步进 cohort（新增的视为 age 0）
        tracked = sum(c[0] for c in cohorts)
        actual = pop[name]
        if actual > tracked + 0.5:
            cohorts.append([actual - tracked, 0])
        elif actual < tracked - 0.5:
            # 因捕食/死亡减少，按比例缩减各 cohort
            if tracked > 0:
                scale = max(0.0, actual / tracked)
                for c in cohorts:
                    c[0] *= scale
        # 推进年龄，处理成熟
        matured_total = 0.0
        new_cohorts = []
        for count, age in cohorts:
            age += 1
            if age >= lc["stage_days"]:
                # 季节限制（如蜻蜓幼虫仅夏末羽化）
                if lc.get("season_only") and season != lc["season_only"]:
                    new_cohorts.append([count, age])
                    continue
                into = lc["into"]
                matured = count * lc["ratio"]
                if into in pop:
                    pop[into] += matured
                matured_total += matured
                # 未成熟的部分死亡（不再保留）
            else:
                new_cohorts.append([count, age])
        state["cohorts"][name] = new_cohorts
        if matured_total >= 1:
            pop[name] = max(0.0, pop[name] - matured_total / max(lc["ratio"], 0.01))
            events.append("lifecycle:%d 只%s悄然变了形态，化作%s" % (int(matured_total), name, lc["into"]))


def _process_spawning(state, events, season):
    """青蛙春季产卵、蜻蜓成虫秋季产卵。"""
    pop = state["populations"]
    turn = state["turn"]
    # 青蛙产卵：春季，每季触发一次（季初）
    fr = SPECIES["青蛙"].get("spawns")
    if fr and season == fr["season"] and turn % SEASON_LEN == 1 and pop["青蛙"] >= 0.5:
        eggs = pop["青蛙"] * fr["ratio"]
        pop[fr["into"]] += eggs
        events.append("spawn:春水微暖，青蛙产下卵块。数日后，%d 只蝌蚪挤在浅水里。" % int(eggs))
    # 死锁解除：春季只要还有青蛙（哪怕被压得很低）却完全没有蝌蚪，立即补一批
    elif fr and season == fr["season"] and pop["青蛙"] >= 0.5 and pop[fr["into"]] < 1:
        eggs = pop["青蛙"] * 5
        pop[fr["into"]] += eggs
        events.append("spawn:春日的光下，青蛙寻得水域产卵，%d 只蝌蚪孵了出来。" % int(eggs))
    # 蜻蜓成虫秋季产卵
    asp = SPECIES["蜻蜓成虫"].get("autumn_spawn")
    if asp and season == asp["season"] and turn % SEASON_LEN == 1 and pop["蜻蜓成虫"] >= 1:
        larvae = pop["蜻蜓成虫"] * asp["ratio"]
        pop[asp["into"]] += larvae
        events.append("spawn:蜻蜓点过水面，卵沉入水底。不久，%d 只幼虫潜伏在淤泥里。" % int(larvae))


# ---------------------------------------------------------------------------
# 7b. v4：年鉴 / 万物志 / 定居者 / 发现制 / 决策
# ---------------------------------------------------------------------------

def _chronicle(state, text):
    """向年鉴追加一条时间线记录。"""
    state["chronicle"].append("%s 第%d天：%s" % (state["season"], state["turn"], text))


def _folio_bump(state, book, key, note=None):
    """访客志/事件志计数与影响描述累计。"""
    d = state["folio"][book].setdefault(key, {"count": 0, "notes": []})
    d["count"] += 1
    if note and note not in d["notes"]:
        d["notes"].append(note)


def _update_max_seen(state):
    """刷新历史最大值字典（种群 + 有机碎屑），供发现制判定。"""
    ms = state["max_seen"]
    pop = state["populations"]
    for name in SPECIES:
        v = pop.get(name, 0)
        if v > ms.get(name, 0):
            ms[name] = v
    det = state["env"]["detritus"]
    if det > ms.get("有机碎屑", 0):
        ms["有机碎屑"] = det


def _check_discovery(state, events):
    """发现制：生态达成条件时自动解锁物种并入册。

    解锁冷却：两次解锁至少间隔 5 天，且每回合最多解锁一种，避免一口气弹出一串。
    """
    if state["turn"] - state.get("last_unlock_turn", -999) < 5:
        return
    for name, cond, narrative in DISCOVERY_RULES:
        if name in state["unlocked_species"]:
            continue
        try:
            ok = cond(state)
        except Exception:
            ok = False
        if ok:
            state["unlocked_species"].append(name)
            state["last_unlock_turn"] = state["turn"]
            events.append("discover:%s——造物名册更新：【%s】" % (narrative, name))
            _chronicle(state, "%s——造物名册更新：%s" % (narrative, name))
            # 物种志首次发现登记
            sp = state["folio"]["species"].setdefault(name, {})
            sp.setdefault("first_day", state["turn"])
            sp.setdefault("first_season", state["season"])
            sp.setdefault("extinct_count", 0)
            sp.setdefault("alive", state["populations"].get(name, 0) >= 1)
            return  # 一次只解锁一种，保证 5 天间隔


def _folio_update_species(state):
    """物种志：跟踪已发现物种的存活/归零次数（历史最大值由 max_seen 提供）。"""
    cod = state["folio"]["species"]
    pop = state["populations"]
    for name in state["unlocked_species"]:
        e = cod.get(name)
        if e is None:
            e = cod[name] = {"first_day": state["turn"], "first_season": state["season"],
                             "extinct_count": 0, "alive": pop.get(name, 0) >= 1}
        alive = pop.get(name, 0) >= 1
        if e.get("alive") and not alive:
            e["extinct_count"] = e.get("extinct_count", 0) + 1
            _chronicle(state, "%s 的身影再也看不到了。" % name)
        e["alive"] = alive


def _add_settler(state, name):
    """收留一名定居者，加入列表并登记定居者志。"""
    t = SETTLER_TYPES[name]
    state["settlers"].append({
        "name": name, "age": 0, "health": 1.0,
        "max_age": t["max_age"], "daily_food": dict(t["daily_food"]),
    })
    rec = state["folio"]["settlers"].setdefault(name, {"times": 0, "max_days": 0})
    rec["times"] += 1
    # 定居时设置的永久标记（如苍鹭定居→鱼群学会躲藏）
    flag = t.get("on_settle_flag")
    if flag:
        state["flags"][flag] = True
    txt = SETTLER_TEXT.get(name, {})
    _chronicle(state, txt.get("arrive_chron", "%s 住了下来，成为池塘的一部分。" % name))


def _process_settlers(state, events, r):
    """定居者每日摄食 + 衰老 + 特殊效果结算（在种群 LV 计算之后）。"""
    pop = state["populations"]
    env = state["env"]
    survivors = []
    for s in state["settlers"]:
        s["age"] += 1
        name = s["name"]
        cfg = SETTLER_TYPES.get(name, {})
        # 概率捕食（翠鸟）：每天 prob_food 概率才真正取食；落空不扣食物也不掉血
        prob = cfg.get("prob_food")
        feeds = True
        if prob is not None:
            if r.chance(prob):
                if pop.get("鲫鱼", 0) >= 1:
                    events.append("settler:" + KINGFISHER_HIT[r.randint(0, len(KINGFISHER_HIT) - 1)])
                else:
                    events.append("settler:" + KINGFISHER_MISS[r.randint(0, len(KINGFISHER_MISS) - 1)])
            else:
                feeds = False  # 空手而归
        short = False
        if feeds:
            for food, amt in s["daily_food"].items():
                if food == "有机碎屑":
                    if env["detritus"] >= amt:
                        env["detritus"] -= amt
                    else:
                        env["detritus"] = 0.0
                        short = True
                    continue
                have = pop.get(food, 0)
                if have >= amt:
                    pop[food] = have - amt
                else:
                    pop[food] = 0.0
                    short = True
            if short:
                s["health"] = round(s["health"] - 0.1, 3)
        # 定居者对环境的持续影响
        tpd = cfg.get("turbidity_per_day")
        if tpd:
            env["turbidity"] = _clamp(env["turbidity"] + tpd, 0.0, 1.0)
        if cfg.get("detritus_per_day"):
            env["detritus"] += cfg["detritus_per_day"]
        if cfg.get("nutrients_per_day"):
            env["nutrients"] += cfg["nutrients_per_day"]
        # 离开判定
        txt = SETTLER_TEXT.get(name, {})
        leave = leave_chron = None
        if s["health"] <= 0:
            leave = txt.get("starve", "%s 找不到食物，离开了池塘。" % name)
            leave_chron = txt.get("starve_chron", leave)
        elif s["age"] > s["max_age"]:
            leave = txt.get("age", "年迈的%s悄然离去。" % name)
            leave_chron = txt.get("age_chron", leave)
        if leave:
            events.append("settler:" + leave)
            _chronicle(state, leave_chron)
            rec = state["folio"]["settlers"].setdefault(name, {"times": 0, "max_days": 0})
            if s["age"] > rec.get("max_days", 0):
                rec["max_days"] = s["age"]
        else:
            survivors.append(s)
    state["settlers"] = survivors


def _choice_prompt(pc):
    c = pc["choices"]
    opts = " 或 ".join("choose %d (%s)" % (i + 1, lab) for i, lab in enumerate(c))
    return "%s\n请输入 %s" % (pc["desc"], opts)


def _parse_choice(args, choices):
    """正则冗余解析：choose 1 / choose 收留 / 1 / 收留 / 收留它 都识别为对应选项。"""
    s = "".join(a.strip() for a in args).strip() if args else ""
    if not s:
        return None
    m = re.match(r"^([0-9]+)$", s)
    if m:
        i = int(m.group(1))
        return i if 1 <= i <= len(choices) else None
    for i, c in enumerate(choices, 1):
        if s == c or c.startswith(s) or s in c or c[:2] == s[:2]:
            return i
    return None


def _choice_ready(state, key):
    """决策事件是否可触发：全局冷却 + 同类冷却 + 触发前提（目标物种存在）满足。"""
    spec = CHOICE_EVENTS[key]
    cds = state.get("choice_cooldowns", {})
    # 跨类型全局冷却：任意决策结算后 N 天内不触发任何新决策
    if state["turn"] - cds.get("__any__", -9999) < CHOICE_GLOBAL_COOLDOWN:
        return False
    # 同类冷却
    if state["turn"] - cds.get(key, -9999) < CHOICE_COOLDOWN:
        return False
    req = spec.get("requires") or []
    if req and not any(state["populations"].get(n, 0) >= 1 for n in req):
        return False
    return True


def _trigger_choice(state, events, key):
    """触发一个决策事件：设置 pending_choice，本回合不再生成其他随机事件。"""
    spec = CHOICE_EVENTS[key]
    # 动态描述：只提及当前真实在场的目标，避免"盯上不存在的猎物"
    desc = spec["desc"]
    if spec.get("desc_tmpl") and spec.get("requires"):
        present = [n for n in spec["requires"] if state["populations"].get(n, 0) >= 1]
        if present:
            desc = spec["desc_tmpl"] % "和".join(present)
    state["pending_choice"] = {
        "event": key,
        "desc": desc,
        "choices": list(spec["choices"]),
        "default": spec["default"],
        "waited": 0,
    }
    state.setdefault("choice_cooldowns", {})[key] = state["turn"]
    events.append("choice:" + desc)
    return True


def _resolve_choice(state, pc, idx, events):
    """应用决策结果（idx 为 1-based），返回结果文案。

    结果使用确定性数值（不消耗 PRNG），以保证引擎随机流与基线对齐。
    """
    pop = state["populations"]
    env = state["env"]
    key = pc["event"]
    chosen = pc["choices"][idx - 1]
    title = CHOICE_EVENTS[key]["title"]

    if key == "蛇":
        # 结算文案同样按当下真实在场的目标动态生成
        targets = [n for n in ("青蛙", "田鼠") if pop.get(n, 0) >= 1]
        tstr = "和".join(targets) if targets else "岸边的小动物"
        if idx == 1:
            msg = "你拍起一片水花，水蛇扭身潜入深处，%s安全了。" % tstr
        elif idx == 3:
            # 第三选项：保持距离观察 → 水蛇定居
            _add_settler(state, "水蛇")
            msg = ("你决定保持距离。水蛇继续盘在芦苇间，偶尔滑入水中，带起一道细长的波纹。"
                   "它成了池塘里最安静的住客。")
        else:
            pop["青蛙"] = max(0.0, pop["青蛙"] - 1)
            pop["田鼠"] = max(0.0, pop["田鼠"] - 1)
            msg = "水蛇慢慢游开，水面恢复平静，%s少了几只。" % tstr
    elif key == "苍鹭":
        # 苍鹭来访后两天，鱼群躲藏（gaze 变体）
        _chain_set(state, "heron_hide", 2)
        if idx == 1:
            msg = "你扬起手，苍鹭振翅而起，浅水里的鱼影散而复聚。"
        else:
            pop["鲫鱼"] = max(0.0, pop["鲫鱼"] - 4)
            msg = "长喙一刺，水花溅起，苍鹭衔着银亮的鲫鱼，飞入远处天光里。"
    elif key == "流浪乌龟":
        if idx == 1:
            _add_settler(state, "流浪乌龟")
            state["flags"]["turtle_resident"] = True
            _unlock(state, events, "不速之客")
            msg = "你收留了它。乌龟踏入浅水，壳没入光影交界的绿里。"
        else:
            msg = "乌龟在岸边停了一会儿，然后转身，消失在草丛深处。"
    elif key == "水獭":
        if idx == 1:
            env["turbidity"] = _clamp(env["turbidity"] + 0.15, 0, 1)
            pop["鲫鱼"] *= 0.85
            msg = "你试图挽留，水獭却搅起一团浑水，叼走几条鱼，然后顺流而去。"
        else:
            pop["鲫鱼"] *= 0.5
            pop["鲤鱼"] *= 0.6
            msg = "水獭住了几日，鱼群的银光稀疏下来。某天清晨，水面空空的，它走了。"
    elif key == "暴雨":
        if idx == 1:
            env["turbidity"] = _clamp(env["turbidity"] + 0.2, 0, 1)
            env["nutrients"] += 20
            msg = "你加固了堤岸，雨水顺着岸沿淌开，池水没有浑得太久。"
        else:
            env["turbidity"] = _clamp(env["turbidity"] + 0.5, 0, 1)
            env["nutrients"] += 60
            msg = "雨砸进池塘，泥沙翻滚，水面变成一片浑黄。"
        # 连锁：暴雨结算时营养盐额外 +15；若碎屑>40，后续 5 天水华概率 ×2
        env["nutrients"] += 15
        if env["detritus"] > 40:
            _chain_set(state, "waterbloom_x2", 5)
        _chain_set(state, "crab_maybe", 1)  # 暴雨次回合 15% 概率冲入螃蟹
    elif key == "干旱":
        # 连锁：标记经历过干旱（蟾蜍解锁），开启 5 天干旱窗口
        state["flags"]["experienced_drought"] = True
        _chain_set(state, "drought", 5)
        if idx == 1:
            env["dissolved_oxygen"] = max(0.0, env["dissolved_oxygen"] - 0.5)
            msg = "你引来新水，水面慢慢涨回原来的高度，焦渴缓和下来。"
        else:
            env["dissolved_oxygen"] = max(0.0, env["dissolved_oxygen"] - 2)
            msg = "水线一天天低下去，池塘变小了。"
    elif key == "热浪":
        if idx == 1:
            env["water_temp"] += 3
            env["dissolved_oxygen"] = max(0.0, env["dissolved_oxygen"] - 1)
            msg = "你撑起一片阴凉，水面烫人的光被挡开一些。"
        else:
            env["water_temp"] += 6
            env["dissolved_oxygen"] = max(0.0, env["dissolved_oxygen"] - 3)
            msg = "热浪炙烤，水面蒸腾，鱼儿开始浮头。"
    elif key == "白鹭":
        if idx == 1:
            msg = "你扬起手臂，白鹭展翅而起，修长的身影划过水面，飞远了。"
        else:
            pop["泥鳅"] = max(0.0, pop.get("泥鳅", 0) - 2)
            pop["河蚌"] = max(0.0, pop.get("河蚌", 0) - 1)
            msg = "白鹭从容地翻出一只河蚌，又叼走两条泥鳅，在浅水里留下一串清晰的爪印。"
    elif key == "洪水":
        if idx == 1:
            msg = "你加固了堤岸，洪水被挡在外面。池塘保住了，但也拒绝了河水带来的新生命。"
        else:
            env["turbidity"] = _clamp(env["turbidity"] + 0.6, 0, 1)
            env["nutrients"] += 80
            env["detritus"] += 60
            pop["河蚌"] *= 0.7  # 洪水冲击：河蚌 -30%
            msg = "你打开了池塘的边界。洪水带来了泥沙、断枝，还有意想不到的来客。"
            _chain_set(state, "crab_incoming", 2)  # 次回合可能触发螃蟹定居决策
    elif key == "水华":
        state["flags"]["water_bloom_done"] = True
        _unlock(state, events, "水华危机")
        if idx == 1:
            pop["水藻"] *= 0.4
            pop["水蚤"] *= 0.6
            env["dissolved_oxygen"] = max(0.0, env["dissolved_oxygen"] + 1)
            msg = "你捞走大片绿藻，水面重新见了光。但清理带走了不少微小的生命。"
        else:
            env["dissolved_oxygen"] = max(0.0, env["dissolved_oxygen"] - 2)
            msg = "你没有动手。几天后，浮萍和睡莲的叶开始挤压绿藻的空间，水面慢慢被撕开几道缝隙。"
    elif key == "螃蟹":
        if idx == 1:
            _add_settler(state, "螃蟹")
            msg = "你收留了这只螃蟹。它横着爬进池塘，钳子夹住一块石头，在底下安了家。"
        else:
            msg = "螃蟹在岸边转了两圈，又横着爬回了浑水里，不见了。"
    elif key == "野鸭":
        if idx == 1:
            _add_settler(state, "野鸭")
            msg = ("你欢迎了这对野鸭。它们在芦苇丛边筑了巢。"
                   "从此池塘多了一对终年游弋的住客，也多了一层水面的热闹。")
        else:
            msg = "你没有挽留。野鸭在池塘歇了一夜，天刚亮就起飞了，翅膀扇动的声音很久才散。"
    elif key == "翠鸟定居":
        if idx == 1:
            _add_settler(state, "翠鸟")
            msg = "你默许了。翠鸟衔来第一根细枝，搭在枯枝的弯处。从此池塘多了一道蓝影，不只是过客。"
        else:
            msg = "你没有出声。翠鸟在枝头停了一会儿，最终飞走了，落在远处另一片水域。"
    elif key == "苍鹭定居":
        if idx == 1:
            _add_settler(state, "苍鹭")  # 内部会设置 heron_resident 永久标记
            msg = "你欢迎了它。苍鹭继续衔枝，在岸边搭起一个粗糙的巢。它成了池塘最从容的住客。"
        else:
            msg = "你扬起手，苍鹭展开宽大的翅膀退后两步，看了你一眼，最终放弃了枯枝，飞远了。"
    else:
        msg = "水面重新静下来。"

    # 访客志 / 事件志登记
    book = "events" if key in ("暴雨", "干旱", "热浪", "洪水", "水华") else "visitors"
    _folio_bump(state, book, key, note="你选择「%s」" % chosen)
    _chronicle(state, "%s —— 你选择「%s」" % (title, chosen))
    # 跨类型全局冷却：任意决策结算后开始计时
    state.setdefault("choice_cooldowns", {})["__any__"] = state["turn"]
    return msg


def _auto_resolve_choice(state, events):
    """连续 3 天未选择，按默认结果自动结算（确定性，不消耗 PRNG）。"""
    pc = state["pending_choice"]
    msg = _resolve_choice(state, pc, pc["default"], events)
    events.append("choice_auto:你犹豫太久了，" + msg)
    state["pending_choice"] = None


def _random_events(state, events, r, season):
    pop = state["populations"]
    env = state["env"]

    # 决策待定：累加等待天数，满 3 天自动按默认结算。
    # 注意：不在此 return —— 仍照常掷骰其余（非决策）事件，使随机流与基线对齐；
    # 本回合只是不再新触发决策事件（suppress）。
    suppress_choice = False
    pc = state.get("pending_choice")
    if pc:
        pc["waited"] = pc.get("waited", 0) + 1
        if pc["waited"] >= 3:
            _auto_resolve_choice(state, events)
        suppress_choice = True

    # 生物访客 —— 概率受季节影响
    def vis(p):
        return r.chance(p)

    def can_choose():
        return not suppress_choice and not state.get("pending_choice")

    has_turtle = any(s["name"] == "流浪乌龟" for s in state["settlers"])

    def vcount(name):
        return state["folio"]["visitors"].get(name, {}).get("count", 0)

    # 连锁：洪水后螃蟹横入 —— 次回合触发螃蟹决策
    if _chain_active(state, "crab_incoming") and can_choose() and _choice_ready(state, "螃蟹"):
        _trigger_choice(state, events, "螃蟹")
        state["chain"].pop("crab_incoming", None)
    # 连锁：暴雨后 15% 概率冲入螃蟹
    if _chain_active(state, "crab_maybe"):
        state["chain"].pop("crab_maybe", None)
        if vis(0.15) and can_choose() and _choice_ready(state, "螃蟹"):
            _trigger_choice(state, events, "螃蟹")

    # 常见 ~15%（无需决策）
    # 翠鸟：累计来访 5 次后，下一次变为"定居"决策
    if not _has_settler(state, "翠鸟") and vis(0.05):
        loss = r.randint(1, 3)  # 始终消耗，维持随机流对齐
        if vcount("翠鸟") >= 5 and can_choose() and _choice_ready(state, "翠鸟定居"):
            _trigger_choice(state, events, "翠鸟定居")
        else:
            pop["鲫鱼"] = max(0.0, pop["鲫鱼"] - loss)
            events.append("visitor:一道翠蓝色的影子俯冲而下，水面溅起碎光。%d 条鲫鱼不见了。" % loss)
            _folio_bump(state, "visitors", "翠鸟", "掠食鲫鱼")
    # 蝙蝠：萤火虫大爆发次日出现概率 ×3
    bat_p = 0.15 if _chain_active(state, "bat_x3") else 0.05
    if vis(bat_p):
        pop["蚊子"] *= 0.7
        pop["蜻蜓成虫"] *= 0.85
        events.append("visitor:暮色里，翅膀划过水面，蚊蚋与蜻蜓的振翅声静了下来。")
        _folio_bump(state, "visitors", "蝙蝠群", "夜捕飞虫")
    if vis(0.05):
        if r.chance(0.3):
            if r.chance(0.5) and pop["鲫鱼"] >= 1:
                pop["鲫鱼"] -= 1
                events.append("visitor:一只猫把爪子探入水中，捞起一条银光，随即隐没草丛。")
            elif pop["田鼠"] >= 1:
                pop["田鼠"] -= 1
                events.append("visitor:猫扑进芦苇丛，叼出一团灰影。")
        else:
            events.append("visitor:猫蹲了很久，爪子空落落地收回，转身走掉了。")
        _folio_bump(state, "visitors", "流浪猫", "觊觎鱼和田鼠")

    # 少见 ~5%
    snake_ok = season != "冬"
    if snake_ok and vis(0.02):  # 蛇 —— 决策
        r.randint(1, 2)  # 维持随机流对齐（原立即效果在此消耗一次抽样）
        if can_choose() and _choice_ready(state, "蛇"):
            _trigger_choice(state, events, "蛇")
    if vis(0.02):
        pop["孑孓"] *= 0.9
        events.append("visitor:夜色里，一团刺球窸窸窣窣翻着落叶，找小虫。")
        _folio_bump(state, "visitors", "刺猬", "翻找岸边昆虫")
    if vis(0.02):
        pop["田鼠"] = max(0.0, pop["田鼠"] - r.randint(1, 2))
        events.append("visitor:一道细长的影子追着田鼠窜过，芦苇剧烈摇晃。")
        _folio_bump(state, "visitors", "黄鼠狼", "捕食田鼠")

    # 稀有 ~1%
    deer_p = 0.02 if season == "秋" else 0.005
    if vis(deer_p):
        env["turbidity"] = _clamp(env["turbidity"] + 0.4, 0, 1)
        pop["浮萍"] *= 0.8
        events.append("visitor:鹿俯颈饮水，蹄子踩塌了岸边一块泥土，浑黄漫入水里。")
        _folio_bump(state, "visitors", "鹿", "踩塌岸边致水质浑浊")
    # 苍鹭：累计来访 3 次后变为"定居"决策
    if not _has_settler(state, "苍鹭") and vis(0.005):
        r.randint(3, 5)  # 维持随机流对齐
        if vcount("苍鹭") >= 3 and can_choose() and _choice_ready(state, "苍鹭定居"):
            _trigger_choice(state, events, "苍鹭定居")
        elif can_choose() and _choice_ready(state, "苍鹭"):
            _trigger_choice(state, events, "苍鹭")
    if vis(0.005) and not has_turtle and can_choose() and _choice_ready(state, "流浪乌龟"):
        _trigger_choice(state, events, "流浪乌龟")  # 流浪乌龟 —— 决策（同时只会有一只）

    # 传说级 ~0.2%
    if vis(0.002):
        events.append("legend:满月之夜，无数萤火从草丛升起，水面落满流动的光。")
        _folio_bump(state, "events", "萤火虫大爆发", "纯观赏奇景")
        _chain_set(state, "bat_x3", 1)  # 连锁：次日蝙蝠出现概率 ×3
        _unlock(state, events, "萤光之夜")
    if vis(0.002) and can_choose() and _choice_ready(state, "水獭"):  # 水獭 —— 决策
        _trigger_choice(state, events, "水獭")
    duck_p = 0.004 if season in ("春", "秋") else 0.0005
    if vis(duck_p):
        state["flags"]["duck_visits"] = state["flags"].get("duck_visits", 0) + 1
        if state["flags"]["duck_visits"] >= 3 and not _has_settler(state, "野鸭") \
                and can_choose() and _choice_ready(state, "野鸭"):
            _trigger_choice(state, events, "野鸭")  # 第 3 次来访 → 定居决策
        else:
            env["detritus"] += 80
            events.append("legend:一群野鸭落在水面，翅膀收起，暗影沉入水里。天亮时它们飞走，留下一池浑浊。")
            _folio_bump(state, "visitors", "迁徙野鸭群", "粪便使碎屑激增")

    # 环境灾害 —— 受季节影响
    if season == "夏" and vis(0.03) and can_choose() and _choice_ready(state, "暴雨"):  # 暴雨
        _trigger_choice(state, events, "暴雨")
    if season in ("夏", "秋") and vis(0.02) and can_choose() and _choice_ready(state, "干旱"):  # 干旱
        _trigger_choice(state, events, "干旱")
    if season == "夏" and vis(0.01) and can_choose() and _choice_ready(state, "热浪"):  # 热浪
        _chain_set(state, "heatwave", 3)  # 热浪窗口，供水华判定
        _trigger_choice(state, events, "热浪")
    if season == "冬" and vis(0.01):  # 寒潮 —— 无需决策
        env["light"] *= 0.3
        env["dissolved_oxygen"] = max(0.0, env["dissolved_oxygen"] - 1.5)
        events.append("disaster:冷空气骤然压下来，水面结成一片灰白，光再也透不下去。")
        _folio_bump(state, "events", "寒潮", "结冰阻断光照与气体交换")

    # ---- V1.0 扩展：新增访客与环境事件 ----
    # 池鹭（常见 ~10%，春夏秋；捕泥鳅）
    if season != "冬" and vis(0.10) and pop.get("泥鳅", 0) >= 1:
        pop["泥鳅"] = max(0.0, pop["泥鳅"] - r.randint(1, 2))
        events.append("visitor:一只池鹭踩着浮萍边缘，低头盯住水下。长喙一刺，一条泥鳅被叼了起来。")
        _folio_bump(state, "visitors", "池鹭", "捕食泥鳅")
    # 燕子（常见 ~8%，春夏；只减蚊子，幅度温和）
    if season in ("春", "夏") and vis(0.08):
        pop["蚊子"] *= 0.9
        events.append("visitor:几只燕子贴着水面掠过去，速度快得像几道黑线。蚊子少了一片。")
        _folio_bump(state, "visitors", "燕子", "捕食蚊子")
    # 白鹭（少见 ~4%，春夏秋；需决策，需泥鳅或河蚌在场）
    if season != "冬" and vis(0.04) and can_choose() and _choice_ready(state, "白鹭"):
        _trigger_choice(state, events, "白鹭")
    # 仙鹤（传说级 ~0.1%，冬春；纯观赏，解锁成就）
    if season in ("冬", "春") and vis(0.001):
        events.append("legend:薄雾中，一只仙鹤立在水边，长颈微曲，一动不动。"
                      "水面映着它的倒影，像一幅不真实的水墨。片刻后，它展开翅，慢慢消失在雾里。")
        _folio_bump(state, "visitors", "仙鹤", "纯观赏奇景")
        _unlock(state, events, "仙鹤降临")
    # 大雾（少见 ~5%，春秋；无决策，压低光照约 2 天）
    if season in ("春", "秋") and vis(0.05):
        _chain_set(state, "fog", 2)
        events.append("weather:大雾笼罩了池塘。水面不见了，芦苇不见了，一切都化进灰白的模糊里。"
                      "光线穿过浓雾，只剩下朦胧的暗影。")
        _folio_bump(state, "events", "大雾", "光照骤降两三天")
    # 洪水（稀有 ~0.8%，仅夏；需决策）
    if season == "夏" and vis(0.008) and can_choose() and _choice_ready(state, "洪水"):
        _trigger_choice(state, events, "洪水")
    # 水华（自动触发）：热浪窗口 + (营养盐>60 或 碎屑>50) + 水面覆盖>0.6
    bloom_ok = (_chain_active(state, "heatwave")
                and (env["nutrients"] > 60 or env["detritus"] > 50)
                and _surface_cover(state) > 0.6)
    bloom_p = 0.3 * (2 if _chain_active(state, "waterbloom_x2") else 1)
    if bloom_ok and vis(bloom_p) and can_choose() and _choice_ready(state, "水华"):
        _trigger_choice(state, events, "水华")


def _detect_pause(state, events):
    """检测关键事件，设置 pending_pause（供 wait 暂停）。"""
    pop = state["populations"]
    env = state["env"]
    reasons = []
    for ev in events:
        if ev.startswith("crisis:") or ev.startswith("disaster:"):
            reasons.append(ev.split(":", 1)[1])
    # 物种归零（曾出现过又归零）—— 去重：同一物种只在首次归零提醒，恢复后再归零才再提醒
    alerted = state.setdefault("extinct_alerted", [])
    for name in RESIDENT_SPECIES:
        if name in state["seen"] and pop[name] < 1:
            if name not in alerted:
                reasons.append("%s 数量归零" % name)
                alerted.append(name)
        elif name in alerted and pop[name] >= 1:
            # 已恢复：清除标记，下次归零会重新提醒
            alerted.remove(name)
    if env["dissolved_oxygen"] < 3.0:
        reasons.append("溶氧危机（%.1f mg/L）" % env["dissolved_oxygen"])
    if reasons:
        state["pending_pause"] = "；".join(dict.fromkeys(reasons))


def _check_achievements(state, events):
    pop = state["populations"]
    f = state["flags"]
    present = [n for n in RESIDENT_SPECIES if pop[n] >= 1]

    if len([n for n in RESIDENT_SPECIES if pop[n] >= 1]) >= 1 and state["seen"]:
        _unlock(state, events, "初生之池")
    trophs = set(SPECIES[n]["trophic"] for n in present)
    if "producer" in trophs and ("primary" in trophs or "secondary" in trophs) and \
       ("secondary" in trophs or "apex" in trophs):
        _unlock(state, events, "食物链初成")
    if f["days_no_extinction"] >= 30:
        _unlock(state, events, "稳定生态")
    if len(present) >= 8:
        _unlock(state, events, "生物多样性")
    if pop["鲤鱼"] >= 5:
        _unlock(state, events, "大丰收")
    if pop["青蛙"] >= 10:
        _unlock(state, events, "蛙鸣之夜")
    if pop["蚊子"] >= 400:
        _unlock(state, events, "蚊灾")
    if state["turn"] >= YEAR_LEN:
        _unlock(state, events, "四季轮回")
    if f["days_no_intervention"] >= 100:
        _unlock(state, events, "造物主的耐心")
    # ---- V1.0 扩展：新增成就 ----
    if f.get("garden_streak", 0) >= 30:
        _unlock(state, events, "水下花园")
    if pop.get("泥鳅", 0) >= 1 and pop.get("水蚯蚓", 0) >= 1 and pop.get("河蚌", 0) >= 1:
        _unlock(state, events, "底栖王国")
    if len(present) >= 15:
        _unlock(state, events, "共生之池")
    # 仙鹤降临、水华危机在对应事件中直接解锁


def _unlock(state, events, name):
    if name not in state["achievements"]:
        state["achievements"].append(name)
        events.append("achievement:🏆 解锁成就【%s】%s" % (name, ACHIEVEMENTS.get(name, "")))


# ---------------------------------------------------------------------------
# 8. 文字渲染
# ---------------------------------------------------------------------------

def _ipop(state, name):
    return int(round(state["populations"][name]))


def _status_bar(state):
    """末尾 JSON 状态栏。"""
    pop = state["populations"]
    env = state["env"]
    pc = state.get("pending_choice")
    bar = {
        "day": state["turn"],
        "turn": state["turn"],
        "season": state["season"],
        "temp": round(env["water_temp"], 1),
        "DO": round(env["dissolved_oxygen"], 1),
        "light": round(env["light"], 2),
        "nutrients": round(env["nutrients"], 0),
        "detritus": round(env["detritus"], 0),
        "turbidity": round(env["turbidity"], 2),
        "pop": {n: int(round(pop[n])) for n in RESIDENT_SPECIES if pop[n] >= 1},
        "unlocked": list(state.get("unlocked_species", [])),
        "settlers": [{"name": s["name"], "health": s["health"]} for s in state.get("settlers", [])],
        "pending_choice": bool(pc),
        "choices": list(pc["choices"]) if pc else [],
        "events": [
            {"type": m["type"], "name": m["name"], "effect": m["effect"]}
            for m in (_classify_event(ev) for ev in state.get("log", []))
        ],
    }
    return json.dumps(bar, ensure_ascii=False, separators=(",", ":"))


# 事件图标（tag -> 图标），与万物志/渲染保持一致
EVENT_ICONS = {
    "season": "🍃", "visitor": "🐾", "legend": "✨", "disaster": "⛈",
    "crisis": "⚠️", "lifecycle": "🦋", "spawn": "🥚", "achievement": "🏆",
    "discover": "🔎", "choice": "❓", "choice_auto": "⌛", "settler": "🐢",
    "weather": "🌫",
}

# 生物访客/灾害事件识别表：(body 关键片段, 标题名, 事件类型, 影响描述)
_VISITOR_TABLE = [
    ("翠蓝色", "翠鸟来访", "visitor", None),       # 影响由正文中的鲫鱼数动态解析
    ("翅膀划过水面", "蝙蝠来访", "visitor", "蚊子↓ 蜻蜓成虫↓"),
    ("爪子探入水中", "流浪猫来访", "visitor", "鲫鱼 -1"),
    ("扑进芦苇丛", "流浪猫来访", "visitor", "田鼠 -1"),
    ("爪子空落落", "流浪猫来访", "visitor", "无"),
    ("刺球", "刺猬来访", "visitor", "孑孓↓"),
    ("细长的影子追着田鼠", "黄鼠狼来访", "visitor", "田鼠↓"),
    ("鹿俯颈饮水", "鹿来访", "visitor", "浑浊↑ 浮萍↓"),
    ("无数萤火", "萤火虫大爆发", "legend", "观赏奇景"),
    ("一群野鸭", "迁徙野鸭群", "legend", "有机碎屑 +80"),
    ("冷空气骤然压下来", "寒潮", "disaster", "光照↓ 溶氧↓"),
    ("鱼纷纷浮起", "翻塘", "crisis", "鱼类大量死亡"),
    # V1.0 扩展
    ("一只池鹭", "池鹭来访", "visitor", "泥鳅↓"),
    ("几只燕子", "燕子来访", "visitor", "蚊子↓"),
    ("一只仙鹤", "仙鹤来访", "legend", "观赏奇景"),
    ("大雾笼罩", "大雾", "weather", "光照↓"),
]

# 决策事件按正文关键字归到标题（触发描述 / 超时结算文案均可识别）
_CHOICE_KEYWORDS = [
    # V1.0 扩展（更具体的关键词放前面，优先匹配）
    ("第五次", "翠鸟定居"), ("蓝影", "翠鸟定居"), ("枯枝的弯处", "翠鸟定居"),
    ("苍鹭第三次", "苍鹭定居"), ("衔着一根枯枝", "苍鹭定居"), ("最从容的住客", "苍鹭定居"),
    ("白鹭", "白鹭来访"),
    ("上游的水", "洪水"), ("洪水", "洪水"), ("开放引入", "洪水"),
    ("绿藻", "水华"), ("水华", "水华"),
    ("螃蟹", "螃蟹来访"),
    ("野鸭", "野鸭定居"),
    ("水蛇", "水蛇来访"), ("苍鹭", "苍鹭来访"), ("水獭", "水獭来访"),
    ("乌龟", "流浪乌龟来访"), ("龟", "流浪乌龟来访"),
    ("干裂", "干旱"), ("水线", "干旱"), ("引来新水", "干旱"), ("焦渴", "干旱"),
    ("热", "热浪"),
    ("雨", "暴雨"), ("泥沙", "暴雨"), ("堤岸", "暴雨"),
]


def _choice_title_from_text(text):
    for kw, title in _CHOICE_KEYWORDS:
        if kw in text:
            return title
    return "池畔抉择"


def _classify_event(ev):
    """把内部事件标签解析为结构化信息：type / name（标题）/ effect（影响）。

    同时附带 icon、body（原文案），以及聚合所需的 into/count/subject 字段。
    不改动事件字符串本身，仅作只读解析。
    """
    if ":" in ev:
        tag, body = ev.split(":", 1)
    else:
        tag, body = "", ev
    meta = {
        "tag": tag, "icon": EVENT_ICONS.get(tag, "·"), "body": body,
        "type": tag or "info", "name": "", "effect": "",
        "into": None, "count": 0, "subject": None,
    }

    if tag == "season":
        name = "时序流转"
        for s, v in SEASON_ENV.items():
            if v["desc"] == body:
                name = "入" + s
                break
        meta["name"] = name
    elif tag == "lifecycle":
        m = re.search(r"(\d+)\s*只(.+?)悄然变了形态，化作(.+)", body)
        if m:
            meta["count"] = int(m.group(1))
            meta["into"] = m.group(3)
            meta["name"] = m.group(2) + "蜕变"
            meta["effect"] = "%s +%d" % (m.group(3), meta["count"])
        else:
            meta["name"] = "蜕变"
    elif tag == "spawn":
        if "蜻蜓" in body:
            meta["name"] = "蜻蜓产卵"
            meta["into"] = "蜻蜓幼虫"
            m = re.search(r"(\d+)\s*只幼虫", body)
            if m:
                meta["count"] = int(m.group(1))
                meta["effect"] = "蜻蜓幼虫 +%d" % meta["count"]
        else:
            meta["name"] = "青蛙产卵"
            meta["into"] = "蝌蚪"
            m = re.search(r"(\d+)\s*只蝌蚪", body)
            if m:
                meta["count"] = int(m.group(1))
                meta["effect"] = "蝌蚪 +%d" % meta["count"]
    elif tag == "discover":
        m = re.search(r"【(.+?)】", body)
        sp = m.group(1) if m else ""
        meta["name"] = "新物种发现"
        meta["effect"] = ("解锁「%s」" % sp) if sp else "解锁新物种"
    elif tag == "settler":
        meta["name"] = "流浪乌龟离开" if "乌龟" in body else "定居者离开"
        meta["effect"] = "离开池塘"
    elif tag == "achievement":
        m = re.search(r"【(.+?)】", body)
        meta["name"] = m.group(1) if m else "成就"
        meta["effect"] = "解锁成就"
    elif tag in ("choice", "choice_auto"):
        meta["name"] = _choice_title_from_text(body)
        meta["effect"] = "等待抉择" if tag == "choice" else "超时自动结算"
    elif tag in ("visitor", "legend", "disaster", "crisis"):
        for frag, title, etype, eff in _VISITOR_TABLE:
            if frag in body:
                meta["name"] = title
                meta["type"] = etype
                if title.endswith("来访"):
                    meta["subject"] = title[:-2]
                if frag == "翠蓝色":
                    fm = re.search(r"(\d+)\s*条鲫鱼", body)
                    meta["effect"] = "鲫鱼 -%s" % (fm.group(1) if fm else "?")
                else:
                    meta["effect"] = eff or ""
                break
        else:
            meta["name"] = "访客来访" if tag == "visitor" else "异象"
    else:
        meta["name"] = "事件"
    return meta


def _render_events(events):
    """把内部事件渲染为：图标【事件名称】+ 换行 + 原文案。"""
    lines = []
    for ev in events:
        meta = _classify_event(ev)
        # 成就文案自带 🏆【名称】 格式，直接展示，避免双重标题
        if meta["tag"] == "achievement":
            lines.append(meta["body"])
            continue
        lines.append("%s【%s】\n%s" % (meta["icon"], meta["name"], meta["body"]))
    return lines


def _observe_text(state, events):
    pop = state["populations"]
    lines = []
    lines.append("【第 %d 天 · %s】" % (state["turn"], state["season"]))
    rendered = _render_events(events)
    if rendered:
        lines.extend(rendered)
    else:
        lines.append("· 水面如镜，只有光线在水底缓缓移动。")
    # 简短变化描述
    notable = []
    for name in ("水藻", "水蚤", "鲫鱼", "青蛙", "蚊子", "鲤鱼"):
        v = _ipop(state, name)
        if v > 0:
            notable.append("%s%d" % (name, v))
    if notable:
        lines.append("· 当前：" + " / ".join(notable))
    if state.get("pending_choice"):
        lines.append(_choice_prompt(state["pending_choice"]))
    lines.append(_status_bar(state))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 9. 指令解析与执行
# ---------------------------------------------------------------------------

def _resolve_species(name):
    name = name.strip()
    if name in SPECIES:
        return name
    if name in ALIASES:
        return ALIASES[name]
    return None


def _mark_intervention(state, intervened):
    if intervened:
        state["flags"]["days_no_intervention"] = 0


def cmd(command):
    """对外主接口：执行一条或多条（分号分隔）指令，返回文字。"""
    state = load_state()
    parts = [p.strip() for p in re.split(r"[;；]", command) if p.strip()]
    if not parts:
        return _help_text()
    outputs = []
    for part in parts:
        outputs.append(_exec_one(state, part))
    save_state(state)
    return "\n\n".join(outputs)


CHOOSE_VERBS = ("choose", "选择", "选", "决定")
# 决策待定时仍可执行的只读 / 逃离指令（不推进时间、不干预生态）
PENDING_OK_VERBS = (
    "help", "帮助", "?", "status", "状态", "面板", "folio", "万物志",
    "chronicle", "年鉴", "look", "查看", "gaze", "凝视", "注视",
    "encyclopedia", "图鉴", "new", "reset", "新游戏", "重开",
    "export", "导出", "import_save", "import", "导入",
)


def _exec_one(state, part):
    tokens = part.split()
    verb = tokens[0].lower() if tokens else ""
    args = tokens[1:]

    # 决策待定：只读 / choose / 重开放行，其余推进或干预类指令一律阻塞
    if state.get("pending_choice"):
        pc = state["pending_choice"]
        if verb in CHOOSE_VERBS:
            return _cmd_choose(state, args)
        if verb not in PENDING_OK_VERBS:
            # 尝试把整句当作裸选择（如 "1" / "收留它"）
            idx = _parse_choice(tokens, pc["choices"])
            if idx is not None:
                return _cmd_choose(state, tokens)
            return "有一件事在池边等待你的注视。\n" + _choice_prompt(pc)
        # 放行的只读指令继续走下方正常分发

    if verb in ("help", "帮助", "?"):
        return _help_text()
    if verb in ("gaze", "凝视", "注视"):
        return _cmd_gaze(state)
    if verb in CHOOSE_VERBS:
        return _cmd_choose(state, args)
    if verb in ("folio", "万物志"):
        return _cmd_folio(state)
    if verb in ("chronicle", "年鉴"):
        return _cmd_chronicle(state, args)
    if verb in ("export", "导出"):
        return _cmd_export(state, args)
    if verb in ("import_save", "import", "导入"):
        return _cmd_import(state, args)
    if verb in ("observe", "看", "观察"):
        events = tick(state)
        return _observe_text(state, events)
    if verb in ("wait", "等待", "等"):
        return _cmd_wait(state, args)
    if verb in ("summon", "召唤", "投放"):
        return _cmd_summon(state, args)
    if verb in ("remove", "移除", "清除"):
        return _cmd_remove(state, args)
    if verb in ("feed", "投喂", "喂"):
        return _cmd_feed(state, args)
    if verb in ("clean", "清理", "换水"):
        return _cmd_clean(state, args)
    if verb in ("status", "状态", "面板"):
        return _cmd_status(state)
    if verb in ("encyclopedia", "图鉴"):
        return _cmd_encyclopedia(state)
    if verb in ("look", "查看"):
        return _cmd_look(state, args)
    if verb in ("new", "reset", "新游戏", "重开"):
        seed = int(args[0]) if args and args[0].lstrip("-").isdigit() else 12345
        new_game(seed)
        return ("🌊 新池初成（seed=%d）。一池清水，静待你的第一笔。\n"
                "万物始于水中微光——也许，从最简单的绿开始。" % seed)
    return "未知指令：%s（输入 help 查看可用指令）" % verb


def _advance(state, days):
    """连续推进若干天，遇关键事件或决策事件暂停。返回结果文字（不含状态栏）。"""
    state["pending_pause"] = None
    key_events = []
    morph = {}          # 变态聚合：into 物种 -> 累计数量
    visits = {}         # 访客聚合：访客名 -> 次数
    fish_taken = 0      # 翠鸟叼走的鲫鱼累计
    actual = 0
    paused_choice = False
    for _ in range(days):
        events = tick(state)
        actual += 1
        state["flags"]["days_no_intervention"] += 1  # wait 不算干预
        for ev in events:
            meta = _classify_event(ev)
            tag = meta["tag"]
            if tag == "lifecycle":
                # 蜕变/羽化 —— 聚合，不逐条刷屏
                if meta["into"]:
                    morph[meta["into"]] = morph.get(meta["into"], 0) + meta["count"]
                else:
                    key_events.append("第%d天 %s" % (state["turn"], meta["body"]))
            elif tag == "visitor":
                sub = meta["subject"]
                if sub:
                    visits[sub] = visits.get(sub, 0) + 1
                if sub == "翠鸟":
                    fm = re.search(r"(\d+)\s*条鲫鱼", meta["body"])
                    if fm:
                        fish_taken += int(fm.group(1))
            elif tag in ("crisis", "disaster", "legend", "achievement", "discover", "settler"):
                key_events.append("第%d天 %s" % (state["turn"], meta["body"]))
        # 决策事件：立即暂停，记录剩余天数
        if state.get("pending_choice"):
            state["pending_wait_days"] = days - actual
            paused_choice = True
            break
        if state["pending_pause"]:
            break
    lines = ["⏩ 推进了 %d 天（第 %d 天 · %s）" % (actual, state["turn"], state["season"])]
    if key_events:
        lines.append("期间关键事件：")
        lines.extend("  " + e for e in key_events)
    # 变态聚合成一句
    if morph:
        seg = "；".join("%d 只陆续蜕变，羽化为%s" % (n, into) for into, n in morph.items())
        lines.append("这段时间，" + seg + "。")
    # 访客汇总
    if visits:
        parts = []
        for vname, cnt in visits.items():
            if vname == "翠鸟" and fish_taken:
                parts.append("翠鸟来过 %d 次，叼走 %d 条鲫鱼" % (cnt, fish_taken))
            else:
                parts.append("%s来访 %d 次" % (vname, cnt))
        lines.append("期间" + "；".join(parts) + "。")
    if paused_choice:
        lines.append("⏸ 池塘边发生了一件需要你决定的事：")
        lines.append(_choice_prompt(state["pending_choice"]))
    elif state["pending_pause"]:
        lines.append("⚠️ 自动暂停：%s" % state["pending_pause"])
        state["pending_pause"] = None
    elif not (key_events or morph or visits):
        lines.append("日子平静地流过，无事发生。")
    return "\n".join(lines)


MAX_WAIT_DAYS = 7


def _cmd_wait(state, args):
    days = 1
    if args and args[0].lstrip("-").isdigit():
        days = max(1, int(args[0]))
    state["pending_wait_days"] = 0
    notice = ""
    if days > MAX_WAIT_DAYS:
        days = MAX_WAIT_DAYS
        notice = "造物主一次最多能观望七日的光阴。\n"
    text = _advance(state, days)
    return notice + text + "\n" + _status_bar(state)


def _cmd_choose(state, args):
    pc = state.get("pending_choice")
    if not pc:
        return "此刻无事发生。"
    idx = _parse_choice(args, pc["choices"])
    if idx is None:
        return "无法识别你的选择。请输入 choose 1 (%s) 或 choose 2 (%s)。" % (
            pc["choices"][0], pc["choices"][1])
    evs = []
    msg = _resolve_choice(state, pc, idx, evs)
    state["pending_choice"] = None
    _mark_intervention(state, True)
    lines = ["🫳 " + msg]
    lines.extend(_render_events(evs))
    # 继续被决策打断的 wait 剩余天数
    remaining = state.get("pending_wait_days", 0)
    state["pending_wait_days"] = 0
    if remaining > 0:
        lines.append("——继续推进剩余 %d 天——" % remaining)
        lines.append(_advance(state, remaining))
    lines.append(_status_bar(state))
    return "\n".join(lines)


def _cmd_summon(state, args):
    if not args:
        return "用法：summon [物种] [数量]"
    name = _resolve_species(args[0])
    qty = 0
    if len(args) >= 2 and args[1].lstrip("-").isdigit():
        qty = int(args[1])
    else:
        qty = 10
    if name is None:
        # 不限制：未知物种，自然规律当裁判 —— 直接告知它无法在池塘存活
        return "你投下%s，它在水中闪烁一下，便消散了。" % args[0]
    # 发现制：只能召唤已解锁物种
    if name not in state.get("unlocked_species", []):
        return "造物名册中尚无此物种的记录。"
    new_pop = state["populations"].get(name, 0) + qty
    state["populations"][name] = new_pop
    if name not in state["seen"]:
        state["seen"].append(name)
    # 投放后的瞬时数量计入历史最大值，使大批量投放能立刻满足发现制阈值
    ms = state["max_seen"]
    if new_pop > ms.get(name, 0):
        ms[name] = new_pop
    _mark_intervention(state, True)
    _unlock(state, [], "初生之池")
    # 立即检查是否因这次投放解锁了新物种
    disc = []
    _check_discovery(state, disc)
    lines = ["✋ 你向池塘投放了 %d 个「%s」（%s）。" % (qty, name, SPECIES[name]["space"])]
    lines.extend(_render_events(disc))
    return "\n".join(lines)


def _cmd_remove(state, args):
    if not args:
        return "用法：remove [物种] [数量]"
    # 先看是否为定居者 —— 对定居者为"驱离"
    target = args[0].strip()
    for s in list(state["settlers"]):
        if s["name"] == target or _resolve_species(target) == s["name"]:
            state["settlers"].remove(s)
            _mark_intervention(state, True)
            _chronicle(state, "你将%s送出池塘，它头也不回地走了。" % s["name"])
            return "🚪 你驱离了「%s」。它沿着岸边，慢慢走远，没有回头。" % s["name"]
    name = _resolve_species(args[0])
    if name is None or name not in state["populations"]:
        return "池塘里没有「%s」。" % args[0]
    cur = state["populations"][name]
    if len(args) >= 2 and args[1].lstrip("-").isdigit():
        qty = min(cur, int(args[1]))
    else:
        qty = cur
    state["populations"][name] = max(0.0, cur - qty)
    _mark_intervention(state, True)
    return "🗑 你从池塘移除了 %d 个「%s」（不可逆）。" % (int(qty), name)


def _cmd_feed(state, args):
    state["env"]["nutrients"] += 15
    # 未吃完的饲料 → 有机碎屑
    state["env"]["detritus"] += 25
    # 水蚤、孑孓等小幅获益
    state["populations"]["水蚤"] *= 1.05
    _mark_intervention(state, True)
    return "🍚 你向池塘投喂了饲料。鱼儿争食，未吃完的沉入水底，慢慢腐解，水底多了一层沉淀。"


def _cmd_clean(state, args):
    pop = state["populations"]
    pop["水藻"] *= 0.4
    # 副作用：带走水蚤和微生物
    pop["水蚤"] *= 0.5
    pop["细菌"] *= 0.5
    state["env"]["detritus"] *= 0.7
    state["env"]["turbidity"] = _clamp(state["env"]["turbidity"] - 0.2, 0, 1)
    _mark_intervention(state, True)
    return "🧹 你捞走水藻，换了水。池水清澈起来，但许多微小的生命也随之流走了。"


def _cmd_status(state):
    pop = state["populations"]
    env = state["env"]
    lines = ["═══ 详细状态面板 ═══"]
    lines.append("第 %d 天 · %s季 · 第 %d 年" % (state["turn"], state["season"], state["turn"] // YEAR_LEN + 1))
    lines.append("─ 环境参数 ─")
    lines.append("  水温 %.1f℃ | 溶氧 %.1f mg/L | 光照 %.2f" % (env["water_temp"], env["dissolved_oxygen"], env["light"]))
    lines.append("  营养盐 %.0f | 有机碎屑 %.0f | 浑浊度 %.2f" % (env["nutrients"], env["detritus"], env["turbidity"]))
    lines.append("─ 种群数量 ─")
    by_troph = {}
    for name in RESIDENT_SPECIES:
        by_troph.setdefault(SPECIES[name]["trophic"], []).append(name)
    troph_label = {"producer": "生产者", "primary": "初级消费者",
                   "secondary": "次级消费者", "apex": "顶级捕食者", "decomposer": "分解者"}
    for troph in ("producer", "primary", "secondary", "apex", "decomposer"):
        names = by_troph.get(troph, [])
        seg = "  ".join("%s:%d" % (n, int(round(pop[n]))) for n in names)
        lines.append("  [%s] %s" % (troph_label[troph], seg))
    # 隐形变量
    lines.append("  [空中] 蚊子:%d  蜻蜓成虫:%d" % (int(round(pop["蚊子"])), int(round(pop["蜻蜓成虫"]))))
    lines.append("已解锁成就：%d/%d" % (len(state["achievements"]), len(ACHIEVEMENTS)))
    lines.append(_status_bar(state))
    return "\n".join(lines)


def _cmd_encyclopedia(state):
    lines = ["📖 图鉴"]
    lines.append("已出现物种（%d/%d）：" % (len(state["seen"]), len(RESIDENT_SPECIES)))
    lines.append("  " + ("、".join(state["seen"]) if state["seen"] else "（暂无）"))
    未见 = [n for n in RESIDENT_SPECIES if n not in state["seen"]]
    if 未见:
        lines.append("  未发现：" + "、".join("?" * 0 or n for n in 未见))
    lines.append("")
    lines.append("🏆 成就（%d/%d）：" % (len(state["achievements"]), len(ACHIEVEMENTS)))
    for name, cond in ACHIEVEMENTS.items():
        mark = "✅" if name in state["achievements"] else "🔒"
        lines.append("  %s %s —— %s" % (mark, name, cond))
    return "\n".join(lines)


def _cmd_folio(state):
    """万物志：物种志 / 定居者志 / 访客志 / 事件志 + 模糊线索。"""
    cod = state["folio"]
    ms = state["max_seen"]
    lines = ["📚 万物志"]

    # —— 物种志 ——（只列真正在池塘中出现过的物种，pop 曾 > 0）
    lines.append("─ 物种志 ─")
    unlocked = list(state["unlocked_species"])
    appeared = [n for n in unlocked if n in state["seen"]]
    for name in appeared:
        e = cod["species"].get(name, {})
        peak = int(round(ms.get(name, state["populations"].get(name, 0))))
        fd = e.get("first_day")
        first = ("第%d天发现" % fd) if fd is not None else "开局已知"
        ext = e.get("extinct_count", 0)
        lines.append("  【%s】%s · 历史最高 %d · 归零 %d 次" % (name, first, peak, ext))
    if not appeared:
        lines.append("  （池塘里还未有生灵现身）")
    # 已解锁但尚未现身的物种：只作为可召唤名册列出
    summonable = [n for n in unlocked if n not in state["seen"]]
    if summonable:
        lines.append("─ 造物名册（可召唤，尚未现身）─")
        lines.append("  " + "、".join(summonable))
    # 模糊线索：列 1~2 个未解锁物种
    undiscovered = [n for n, _c, _t in DISCOVERY_RULES if n not in unlocked]
    for name in undiscovered[:2]:
        lines.append("  【???】%s" % FOLIO_CLUES.get(name, "线索隐约，尚不可知"))
    lines.append("  ……更多的生命还在迷雾中。")

    # —— 定居者志 ——
    if cod["settlers"]:
        lines.append("─ 定居者志 ─")
        for name, rec in cod["settlers"].items():
            cur = sum(1 for s in state["settlers"] if s["name"] == name)
            lines.append("  【%s】定居 %d 次 · 最长存活 %d 天%s" % (
                name, rec.get("times", 0), rec.get("max_days", 0),
                "（当前在塘）" if cur else ""))

    # —— 访客志 ——
    if cod["visitors"]:
        lines.append("─ 访客志 ─")
        for key, rec in cod["visitors"].items():
            note = "；".join(rec.get("notes", [])[:3])
            lines.append("  %s × %d%s" % (key, rec.get("count", 0),
                                          "（%s）" % note if note else ""))

    # —— 事件志 ——
    if cod["events"]:
        lines.append("─ 事件志 ─")
        for key, rec in cod["events"].items():
            lines.append("  %s × %d" % (key, rec.get("count", 0)))

    return "\n".join(lines)


def _cmd_chronicle(state, args):
    """年鉴：默认最近 20 条，chronicle all 输出完整历史。"""
    ch = state.get("chronicle", [])
    if not ch:
        return "📜 年鉴还是空白的一页。"
    show_all = bool(args) and args[0].lower() in ("all", "全部")
    entries = ch if show_all else ch[-20:]
    head = "📜 年鉴（共 %d 条%s）" % (len(ch), "" if show_all else "，显示最近 %d 条" % len(entries))
    return head + "\n" + "\n".join("  " + e for e in entries)


def _gaze_pick(r, options):
    return options[r.randint(0, len(options) - 1)]


def _gaze_sample(r, seq, k):
    """从 seq 中无放回随机取 k 个。"""
    pool = list(seq)
    out = []
    for _ in range(min(k, len(pool))):
        out.append(pool.pop(r.randint(0, len(pool) - 1)))
    return out


def _cmd_gaze(state):
    """凝视：不推进时间，按当前种群/环境/季节/定居者生成一段微观描写（纯文字）。

    用 PRNG 随机选择文案并提交其状态，使同一情形下连续 gaze 不会完全重复。
    """
    r = rng_from(state)
    pop = state["populations"]
    env = state["env"]
    season = state["season"]
    lines = [_gaze_pick(r, GAZE_SEASON[season])]

    # 环境氛围：按最显著的一种状态选一句
    cover = _surface_cover(state)
    if env["dissolved_oxygen"] < 4.0:
        lines.append(_gaze_pick(r, GAZE_ENV["low_do"]))
    elif cover > 0.7:
        lines.append(_gaze_pick(r, GAZE_ENV["cover"]))
    elif env["turbidity"] > 0.4:
        lines.append(_gaze_pick(r, GAZE_ENV["turbid"]))
    elif env["turbidity"] < 0.1 and env["dissolved_oxygen"] >= 6.0:
        lines.append(_gaze_pick(r, GAZE_ENV["clear"]))

    # 主体：在场物种里随机挑 2~3 个来描写
    # 苍鹭来访后两天，鲫鱼/鲤鱼优先抽"躲藏"变体
    hide = _chain_active(state, "heron_hide")
    present = [n for n in GAZE_SUBJECT_ORDER if pop.get(n, 0) >= 1]
    if not present:
        lines.append(_gaze_pick(r, GAZE_EMPTY))
    else:
        k = min(len(present), r.randint(2, 3))
        for n in _gaze_sample(r, present, k):
            if hide and n in GAZE_FISH_HIDE:
                lines.append(_gaze_pick(r, GAZE_FISH_HIDE[n]))
            else:
                lines.append(_gaze_pick(r, GAZE_SUBJECT[n]))

    # 定居者也要入画
    for s in state.get("settlers", []):
        tmpl = GAZE_SETTLER.get(s["name"])
        if tmpl:
            lines.append(_gaze_pick(r, tmpl))

    commit_rng(state, r)
    return "\n".join(lines)


def _cmd_look(state, args):
    if not args:
        return "用法：look [物种/季节]"
    key = args[0]
    # 季节
    if key in SEASON_ENV:
        e = SEASON_ENV[key]
        return "【%s】%s\n  基准水温 %d℃，基准光照 %.2f" % (key, e["desc"], e["water_temp"], e["light"])
    name = _resolve_species(key)
    if name is None:
        return "图鉴里没有「%s」。" % key
    sp = SPECIES[name]
    troph_label = {"producer": "生产者", "primary": "初级消费者",
                   "secondary": "次级消费者", "apex": "大型杂食鱼", "decomposer": "分解者"}
    lines = ["【%s】%s · %s" % (name, sp["space"], troph_label.get(sp["trophic"], ""))]
    if name in LOOK_DESC:
        lines.append("  " + LOOK_DESC[name])
    food = "、".join(sp["food_sources"]) if sp["food_sources"] else "阳光/营养盐/碎屑等环境来源"
    lines.append("  食物来源：" + food)
    lines.append("  繁殖率 %.2f | 死亡率 %.2f | 承载上限 %d" % (sp["birth_rate"], sp["death_rate"], sp["max_capacity"]))
    if sp.get("lifecycle"):
        lc = sp["lifecycle"]
        lines.append("  生命周期：约 %d 天后变态为「%s」（转化率 %.0f%%）" % (lc["stage_days"], lc["into"], lc["ratio"] * 100))
    lines.append("  当前数量：%d" % int(round(state["populations"].get(name, 0))))
    return "\n".join(lines)


def _lite_snapshot(state):
    """精简存档：核心状态 + folio 摘要，砍掉完整 chronicle，控制体积。"""
    cod = state["folio"]
    return {
        "lite": True,
        "version": state.get("version", 2),
        "seed": state.get("seed"),
        "rng_state": state["rng_state"],
        "turn": state["turn"],
        "season": state["season"],
        "populations": {k: round(v, 2) for k, v in state["populations"].items() if v > 0},
        "env": {k: round(v, 2) for k, v in state["env"].items()},
        "settlers": state["settlers"],
        "unlocked_species": state["unlocked_species"],
        "seen": state.get("seen", []),
        "max_seen": {k: round(v, 1) for k, v in state["max_seen"].items()},
        "pending_choice": state.get("pending_choice"),
        "pending_wait_days": state.get("pending_wait_days", 0),
        "choice_cooldowns": state.get("choice_cooldowns", {}),
        # folio 摘要：每本志压缩为最小键值，不含逐条 notes
        "folio": {
            "species": {n: [e.get("first_day"), e.get("extinct_count", 0)]
                        for n, e in cod["species"].items()},
            "settlers": {n: [r.get("times", 0), r.get("max_days", 0)]
                         for n, r in cod["settlers"].items()},
            "visitors": {n: r.get("count", 0) for n, r in cod["visitors"].items()},
            "events": {n: r.get("count", 0) for n, r in cod["events"].items()},
        },
    }


def _restore_from_lite(data):
    """从精简存档重建完整 state（缺失字段由 fresh_state 默认值补齐）。"""
    base = fresh_state(data.get("seed", 12345))
    base["version"] = data.get("version", base["version"])
    base["rng_state"] = data.get("rng_state", base["rng_state"])
    base["turn"] = data.get("turn", 0)
    base["season"] = data.get("season", season_of(base["turn"]))
    for k, v in data.get("populations", {}).items():
        if k in base["populations"]:
            base["populations"][k] = v
    base["env"].update(data.get("env", {}))
    base["settlers"] = data.get("settlers", [])
    base["unlocked_species"] = data.get("unlocked_species", list(STARTER_SPECIES))
    base["seen"] = data.get("seen", [n for n in RESIDENT_SPECIES
                                      if base["populations"].get(n, 0) >= 1])
    base["max_seen"] = data.get("max_seen", {})
    base["pending_choice"] = data.get("pending_choice")
    base["pending_wait_days"] = data.get("pending_wait_days", 0)
    base["choice_cooldowns"] = data.get("choice_cooldowns", {})
    fs = data.get("folio", {})
    base["folio"]["species"] = {
        n: {"first_day": p[0], "first_season": None,
            "extinct_count": p[1] if len(p) > 1 else 0,
            "alive": base["populations"].get(n, 0) >= 1}
        for n, p in fs.get("species", {}).items()}
    base["folio"]["settlers"] = {n: {"times": p[0], "max_days": p[1]}
                                 for n, p in fs.get("settlers", {}).items()}
    base["folio"]["visitors"] = {n: {"count": c, "notes": []}
                                 for n, c in fs.get("visitors", {}).items()}
    base["folio"]["events"] = {n: {"count": c, "notes": []}
                               for n, c in fs.get("events", {}).items()}
    base["chronicle"] = []   # lite 加载后年鉴为空
    return base


def _cmd_export(state, args):
    """导出存档为 base64 字符串。export lite 只导核心状态 + folio 摘要。"""
    lite = bool(args) and args[0].lower() in ("lite", "精简")
    data = _lite_snapshot(state) if lite else state
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    b64 = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    label = "精简存档" if lite else "完整存档"
    tip = "（精简版：仅核心状态，年鉴不含其中）" if lite else "（完整版：含全部年鉴历史）"
    return "📦 %s%s，复制下面整段即可保存/迁移：\n%s" % (label, tip, b64)


def _cmd_import(state, args):
    """从 base64 字符串恢复存档，自动识别完整 / 精简。"""
    if not args:
        return "用法：import_save [base64 存档字符串]"
    b64 = "".join(args).strip()
    try:
        raw = base64.b64decode(b64.encode("ascii"), validate=True)
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return "无法解析这段存档字符串，请确认复制完整、没有多余空格或换行。"
    if not isinstance(data, dict) or "populations" not in data:
        return "这段字符串不是有效的池塘存档。"
    is_lite = bool(data.get("lite"))
    restored = _restore_from_lite(data) if is_lite else data
    _migrate(restored)
    if is_lite:
        restored["chronicle"] = []
    # 原地替换当前 state，使 cmd() 末尾的保存写入恢复后的内容
    state.clear()
    state.update(restored)
    kind = "精简存档" if is_lite else "完整存档"
    return "📥 已从%s恢复：第 %d 天 · %s。%s" % (
        kind, state["turn"], state["season"],
        "（精简存档不含年鉴历史，已重置为空）" if is_lite else "")


def _help_text():
    return (
        "🌊 池塘生态 · 造物主可用的力量\n"
        "  observe          注视池塘，推进一回合，观察变化。（附状态栏）\n"
        "  wait [天数]      连续推进多日（单次最多 7 天），遇关键事件自动暂停。\n"
        "  gaze             凝望此刻的池塘，看一段微观景象。（不推进时间）\n"
        "  summon 物种 数量 向池塘投放生灵。（不拘物种，后果自负）\n"
        "  remove 物种 数量 从池塘中取走生物。（不可逆）\n"
        "  feed             撒下饲料，滋养万物。（残饵沉底腐烂，令碎屑增加）\n"
        "  clean            清理水藻与浊水，池水变清，但会带走微小生命。\n"
        "  choose 选项      对眼前的事做出选择。（choose 1 / choose 收留 均可）\n"
        "  status           详细数据面板。\n"
        "  folio            万物志（物种/定居者/访客/事件）。\n"
        "  chronicle [all]  年鉴时间线（默认最近 20 条）。\n"
        "  encyclopedia     图鉴与成就。\n"
        "  look 物种/季节   查看详细信息。\n"
        "  export [lite]    导出存档为 base64（lite 为精简版）。\n"
        "  import_save 串   从 base64 字符串恢复存档。\n"
        "  new [seed]       重开一局。\n"
        "  支持分号批量：summon 水藻 50; summon 水蚤 30; wait 7"
    )


# ---------------------------------------------------------------------------
# 10. new_game
# ---------------------------------------------------------------------------

def new_game(seed=12345):
    """重开一局，重置状态并存档。"""
    global _STATE
    _STATE = fresh_state(seed)
    save_state(_STATE)
    return _STATE


# ---------------------------------------------------------------------------
# CLI 自测
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(cmd("help"))
