#!/usr/bin/env python3
"""六灾立法回归：动作契约、逐日机制、PRNG 边界与旧档兼容。"""

import copy
import inspect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import engine  # noqa: E402


FAILURES = []


def check(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print("[%s] %s%s" % (status, label, ("  " + detail) if detail and not cond else ""))
    if not cond:
        FAILURES.append(label)


def base_state(turn=10, seed=20260710):
    s = engine.fresh_state(seed)
    s["turn"] = turn
    return s


def call(state, action, payload=None, rng_may_change=False):
    """除凿冰判定外，human_action 必须不消耗 RNG 且一律不推进天数。"""
    rng_before = state["rng_state"]
    turn_before = state["turn"]
    res = engine.human_action(state, action, payload)
    if not rng_may_change:
        check("%s：不消耗主 RNG 序列" % action, state["rng_state"] == rng_before)
    check("%s：不推进天数" % action, state["turn"] == turn_before)
    return res


def process_bio(state):
    engine._process_biological_disasters(state, [], engine.rng_from(state))


def state_with_next_roll(lo, hi, turn=100):
    """构造下一枚 Mulberry32 值落在 [lo, hi) 的状态，不推进待测状态。"""
    for raw in range(1, 100000):
        s = base_state(turn=turn, seed=raw)
        s["rng_state"] = raw
        if lo <= engine.rng_from(s).random() < hi:
            s["season"] = "冬"
            s["flags"]["ice_on"] = True
            s["env"]["detritus"] = 100
            return s
    raise AssertionError("找不到目标随机区间")


def test_unknown_and_bad_payload():
    s = base_state()
    check("未知 action 被拒", call(s, "feed_dragon")["error"] == "unknown_action")
    check("非 dict payload 被拒", call(s, "expel_turtle", "bad")["error"] == "bad_payload")


def test_turtle_and_migration():
    s = base_state()
    check("expel_turtle：无龟拒绝", call(s, "expel_turtle")["error"] == "not_active")

    s = base_state()
    engine._trigger_brazilian_turtle(s, [])
    first = call(s, "expel_turtle")
    check("巴西龟：人类首次驱赶暂离且撤销决策",
          first["ok"] and first["summary"]["turtle"] == "expelled_once"
          and first["summary"]["human_expel_count"] == 1 and s["pending_choice"] is None)
    check("巴西龟：暂离窗口不能重复帮", call(s, "expel_turtle")["error"] == "not_active")
    s["turn"] = first["summary"]["return_day"]
    engine._trigger_brazilian_turtle(s, [])
    engine._resolve_choice(s, s["pending_choice"], 1, [])
    check("巴西龟：人机累计两次彻底驱离",
          s["flags"]["brazilian_turtle"] == "gone" and "驱逐者" in s["achievements"])

    s = base_state()
    s["flags"]["brazilian_turtle"] = "expelled_once"
    for key in ("ai_expel_count", "human_expel_count"):
        s["flags"].pop(key, None)
    engine._migrate(s)
    check("巴西龟旧档：expelled_once 迁移为小机累计一次",
          s["flags"]["ai_expel_count"] == 1)


def test_snail_count_and_suppression():
    s = base_state()
    check("catch_snail：无螺拒绝", call(s, "catch_snail", {"count": 2})["error"] == "not_active")

    s = base_state()
    engine._hatch_apple_snail(s, [])
    apple = s["flags"]["apple_snail"]
    check("福寿螺：爆发携带 count=12",
          apple["status"] == "active" and apple["count"] == 12)
    partial = call(s, "catch_snail", {"count": 5})
    check("福寿螺：按只扣减并返回剩余",
          partial["ok"] and partial["summary"]["caught"] == 5
          and partial["summary"]["remaining_count"] == 7
          and s["flags"]["apple_snail"]["count"] == 7)
    check("福寿螺：同场第二次人类提交拒绝",
          call(s, "catch_snail", {"count": 1})["error"] == "already_helped")

    factors = []
    for count in (12, 6, 0):
        x = base_state()
        x["flags"]["apple_snail"] = ({"status": "active", "count": count}
                                       if count else "gone")
        factors.append(engine._apple_snail_algae_factor(x))
    check("福寿螺：12/6/0 只线性压制为 0.7/0.85/1.0",
          all(abs(a - b) < 1e-9 for a, b in zip(factors, (0.7, 0.85, 1.0))))

    s = base_state()
    engine._hatch_apple_snail(s, [])
    det = s["env"]["detritus"]
    cleared = call(s, "catch_snail", {"count": 999})
    check("福寿螺：捞到 0 当场解除、碎屑 +10、清光文案",
          cleared["ok"] and cleared["summary"]["cleared"]
          and s["flags"]["apple_snail"] == "gone"
          and abs(s["env"]["detritus"] - det - 10) < 1e-9
          and "清光" in cleared["message"])

    s = base_state()
    s["flags"]["apple_snail"] = {"status": "clearing", "count": 5,
                                   "human_helped": False}
    det = s["env"]["detritus"]
    counts = []
    for _ in range(3):
        s["turn"] += 1
        engine._process_invasions(s, [])
        apple = s["flags"]["apple_snail"]
        counts.append(0 if apple == "gone" else apple["count"])
    check("福寿螺：螃蟹固定每天吃 2 只且清零", counts == [3, 1, 0])
    check("福寿螺：螃蟹清零沉入碎屑 +10",
          abs(s["env"]["detritus"] - det - 10) < 1e-9)


def test_snail_incubation():
    s = base_state(turn=20)
    rng_before = s["rng_state"]
    events = []
    engine._trigger_apple_snail(s, events)
    check("福寿螺卵块：固定三天孵化且不计灾害",
          s["flags"]["apple_snail"] == {"status": "incubating", "hatch_day": 23}
          and s["disaster_count_this_season"] == 0 and s["pending_choice"] is None)
    egg_text = " ".join(events)
    check("福寿螺卵块：文本含粉色卵、小机够不着、人类孵化前清理",
          all(word in egg_text for word in ("粉色", "我自己够不着", "你的人类", "孵化前")))
    check("福寿螺卵块：触发不新增掷骰", s["rng_state"] == rng_before)
    det = s["env"]["detritus"]
    stopped = call(s, "catch_snail")
    check("福寿螺卵块：掐灭、碎屑 +3、prevented=true",
          stopped["ok"] and stopped["summary"]["prevented"]
          and s["flags"]["apple_snail"] is None
          and abs(s["env"]["detritus"] - det - 3) < 1e-9)

    control = base_state(turn=20)
    incubating = copy.deepcopy(control)
    incubating["flags"]["apple_snail"] = {"status": "incubating", "hatch_day": 99}
    check("福寿螺卵块：孵化期不压水藻出生率",
          engine._apple_snail_algae_factor(control) == engine._apple_snail_algae_factor(incubating) == 1.0)

    s = base_state(turn=30)
    engine._trigger_apple_snail(s, [])
    s["turn"] = 33
    rng_before = s["rng_state"]
    engine._process_invasions(s, [])
    check("福寿螺卵块：hatch_day 转为 12 只 active",
          s["flags"]["apple_snail"]["status"] == "active"
          and s["flags"]["apple_snail"]["count"] == 12)
    check("福寿螺卵块：孵化推进不新增掷骰", s["rng_state"] == rng_before)


def test_hyacinth_stalks_and_scaled_cost():
    s = base_state(turn=30)
    s["flags"]["water_hyacinth"] = {"day": 20, "cover": 0.40,
                                      "outbreak_cover": 0.40, "human_helped": False}
    res = call(s, "pull_hyacinth", {"stalks": 99})
    check("水葫芦：按株且单次 clamp 7 株，每株 0.02",
          res["ok"] and res["summary"]["stalks"] == 7
          and abs(res["summary"]["cover_reduced"] - 0.14) < 1e-9
          and abs(s["flags"]["water_hyacinth"]["cover"] - 0.26) < 1e-9)
    check("水葫芦：同场第二次人类提交拒绝",
          call(s, "pull_hyacinth", {"stalks": 1})["error"] == "already_helped")

    s = base_state(turn=30)
    for name in ("浮萍", "田螺", "水黾"):
        s["populations"][name] = 100.0
    s["flags"]["water_hyacinth"] = {"day": 20, "cover": 0.20,
                                      "outbreak_cover": 0.40, "human_helped": True}
    turb, det = s["env"]["turbidity"], s["env"]["detritus"]
    pc = {"event": "水葫芦飘入", "choices": ["拔掉", "放任"]}
    engine._resolve_choice(s, pc, 1, [])
    check("水葫芦：小机拔除代价按剩余覆盖 50% 缩放",
          abs(s["env"]["turbidity"] - turb - 0.075) < 1e-9
          and abs(s["env"]["detritus"] - det - 2.5) < 1e-9
          and abs(s["populations"]["浮萍"] - 95) < 1e-9
          and abs(s["populations"]["田螺"] - 85) < 1e-9
          and abs(s["populations"]["水黾"] - 85) < 1e-9)


def test_rat_linear_calm_and_cooldown():
    s = base_state(turn=40)
    s["populations"]["田鼠"] = 20.0
    s["populations"]["芦苇"] = 100.0
    s["env"]["turbidity"] = 0.0
    s["flags"]["bio_disasters"] = {
        "鼠患": {"remaining": 3, "outbreak_count": 20.0, "human_helped": False}}
    process_bio(s)
    check("鼠患：每天按当前 20 只线性损失芦苇 24%",
          abs(s["populations"]["芦苇"] - 76.0) < 1e-9)
    check("鼠患：每天浑浊增加 当前田鼠×0.008",
          abs(s["env"]["turbidity"] - 0.16) < 1e-9)

    hit = call(s, "hunt_rat", {"count": 99})
    check("鼠患：hunt clamp 为 min(当前数,12)",
          hit["ok"] and hit["summary"]["hits"] == 12
          and abs(s["populations"]["田鼠"] - 8) < 1e-9)
    check("鼠患：同场第二次人类提交拒绝",
          call(s, "hunt_rat", {"count": 1})["error"] == "already_helped")

    s = base_state(turn=50)
    s["populations"]["田鼠"] = 5.0
    s["populations"]["芦苇"] = 100.0
    s["flags"]["bio_disasters"] = {
        "鼠患": {"remaining": 3, "outbreak_count": 20.0, "human_helped": False}}
    process_bio(s)
    check("鼠患：降到 outbreak_count×25% 当场解除且不再破坏",
          "鼠患" not in s["flags"]["bio_disasters"]
          and abs(s["populations"]["芦苇"] - 100) < 1e-9)

    s = base_state(turn=55)
    s["populations"]["田鼠"] = 6.0
    s["flags"]["bio_disasters"] = {
        "鼠患": {"remaining": 3, "outbreak_count": 20.0, "human_helped": False}}
    remove_msg = engine._cmd_remove(s, ["田鼠", "1"])
    check("鼠患：其他即时减鼠操作越过 25% 线也当场解除",
          "鼠患" not in s["flags"]["bio_disasters"] and "成功平息" in remove_msg)

    s = base_state(turn=60)
    s["populations"]["田鼠"] = 20.0
    s["flags"]["bio_disasters"] = {
        "鼠患": {"remaining": 1, "outbreak_count": 20.0, "human_helped": False}}
    process_bio(s)
    until = s["flags"]["rat_plague_cooldown_until"]
    check("鼠患：三天到期田鼠回落 25% 并设置十天冷却",
          abs(s["populations"]["田鼠"] - 15) < 1e-9 and until == 70)
    s["populations"]["田鼠"] = 20.0
    s["turn"] = until
    process_bio(s)
    blocked = "鼠患" not in s["flags"]["bio_disasters"]
    s["turn"] = until + 1
    process_bio(s)
    check("鼠患：完整冷却十天内不触发、第十一天可触发",
          blocked and s["flags"]["bio_disasters"]["鼠患"]["outbreak_count"] == 20.0)


def test_green_tide_persistent_relief_and_baseline():
    s = base_state(turn=40)
    s["populations"]["水藻"] = 600.0
    s["flags"]["bio_disasters"] = {
        "绿潮": {"remaining": 3, "human_helped": False,
                 "human_skim_total": 0.0, "skim_day_reduced": False}}
    res = call(s, "skim_algae", {"amount": 50})
    green = s["flags"]["bio_disasters"]["绿潮"]
    check("绿潮：累计 50 后每日减免 0.3 且提前一天",
          res["ok"] and res["summary"]["daily_do_relief"] == 0.3
          and res["summary"]["shortened"] and green["remaining"] == 2)
    check("绿潮：同场第二次人类提交拒绝",
          call(s, "skim_algae", {"amount": 1})["error"] == "already_helped")

    plain = base_state(turn=40)
    plain["flags"]["bio_disasters"] = {"绿潮": {"remaining": 3, "human_skim_total": 0}}
    helped = copy.deepcopy(plain)
    helped["flags"]["bio_disasters"]["绿潮"]["human_skim_total"] = 50
    d0_plain, d0_helped = plain["env"]["dissolved_oxygen"], helped["env"]["dissolved_oxygen"]
    process_bio(plain)
    process_bio(helped)
    first_plain = d0_plain - plain["env"]["dissolved_oxygen"]
    first_helped = d0_helped - helped["env"]["dissolved_oxygen"]
    process_bio(plain)
    process_bio(helped)
    check("绿潮：0.3 减免在后续每天持续生效",
          abs(first_plain - first_helped - 0.3) < 1e-9
          and abs(helped["env"]["dissolved_oxygen"] - plain["env"]["dissolved_oxygen"] - 0.6) < 1e-9)

    # 典型 5 天全额绿潮：从 fresh_state 的 9 mg/L 起步，检查原本在场的鱼无一归零。
    s = engine.fresh_state(77)
    s["turn"] = 40
    s["season"] = "夏"
    s["populations"]["水藻"] = 600.0
    s["env"]["nutrients"] = 120.0
    for name, count in {"鲫鱼": 20.0, "鲤鱼": 10.0, "草鱼": 6.0,
                        "鳑鲏": 30.0, "泥鳅": 20.0}.items():
        s["populations"][name] = count
    s["flags"]["bio_disasters"] = {"绿潮": {"remaining": 5, "human_skim_total": 0}}
    s["pending_choice"] = {"event": "验证占位", "desc": "", "choices": []}
    fish_before = {name: s["populations"][name] for name in engine.FISH
                   if s["populations"][name] >= 1}
    for _ in range(5):
        engine.tick(s)
    extinct = [name for name in fish_before if s["populations"][name] < 0.5]
    check("绿潮无人干预基线：典型 5 天全额扣氧不致鱼类灭绝",
          len(fish_before) == 5 and not extinct,
          "extinct=%r DO=%.2f" % (extinct, s["env"]["dissolved_oxygen"]))


class HuntProbeR:
    def __init__(self):
        self.chances = []

    def chance(self, p):
        self.chances.append(p)
        return True

    def randint(self, lo, hi):
        return lo


def test_crack_joint_hole_and_spring_loss():
    # 中间区间：单方失败，第二方加入后同一枚值在 85% 阈值下成功。
    s = state_with_next_roll(0.40, 0.85)
    rng_before = s["rng_state"]
    human = call(s, "crack_ice", rng_may_change=True)
    check("凿冰：人类单方 40% 判定失败且只消耗当日共享判定",
          human["ok"] and not human["summary"]["success"]
          and not human["summary"]["joint_attempt"] and s["rng_state"] != rng_before)
    ai_text = engine._cmd_crack(s, [])
    check("凿冰：小机同日加入，复用判定并按 85% 联合成功",
          s["flags"]["ice_attempt_success"] and "联合判定成功" in ai_text
          and engine._chain_active(s, "ice_hole"))
    rng_after_joint = s["rng_state"]
    again = call(s, "crack_ice", rng_may_change=True)
    check("凿冰：人类当天第二次拒绝且不再掷骰",
          again["error"] == "already_today" and s["rng_state"] == rng_after_joint)

    s = state_with_next_roll(0.40, 0.85)
    ai_text = engine._cmd_crack(s, [])
    rng_after_ai = s["rng_state"]
    human = call(s, "crack_ice", rng_may_change=True)
    check("凿冰：小机先失败、人类后加入也联合成功",
          "单独判定失败" in ai_text and human["summary"]["success"]
          and human["summary"]["joint_attempt"] and s["rng_state"] == rng_after_ai)

    s = state_with_next_roll(0.0, 1.0)
    for day in range(100, 104):
        s["turn"] = day
        s["env"]["detritus"] = 100
        engine._cmd_crack(s, [])
    check("凿冰：废除每冬三次上限，第四次仍可尝试且计数保留", s["flags"]["crack_count"] == 4)

    # 洞口覆盖后续三个 tick；第一天对照应 +0.3 且不计憋气。
    no_hole = base_state(turn=100, seed=9)
    no_hole["season"] = "冬"
    no_hole["flags"]["ice_on"] = True
    no_hole["env"]["water_temp"] = 1.0
    no_hole["pending_choice"] = {"event": "验证占位", "desc": "", "choices": []}
    hole = copy.deepcopy(no_hole)
    hole["chain"]["ice_hole"] = hole["turn"] + 4
    engine.tick(no_hole)
    engine.tick(hole)
    check("冰洞：有效日溶氧 +0.3 且憋气不计天",
          abs(hole["env"]["dissolved_oxygen"] - no_hole["env"]["dissolved_oxygen"] - 0.3) < 1e-6
          and no_hole["flags"]["ice_suffocation"] == 1
          and hole["flags"]["ice_suffocation"] == 0)
    t = 100
    hole["chain"]["ice_hole"] = t + 4
    active_days = []
    for day in (t + 1, t + 2, t + 3, t + 4):
        hole["turn"] = day
        active_days.append(engine._chain_active(hole, "ice_hole"))
    check("冰洞：后续恰好三个 tick 有效", active_days == [True, True, True, False])

    s = base_state(turn=121)
    s["season"] = "冬"
    s["flags"]["ice_on"] = True
    s["flags"]["ice_suffocation"] = 5
    s["flags"]["ice_total_days"] = 10
    s["hibernate"]["青蛙"] = 100.0
    engine._season_events(s, [], "春", "冬")
    check("春融：青蛙按 5/10×40%=20% 比例折损并清账",
          abs(s["populations"]["青蛙"] - 80) < 1e-9
          and s["flags"]["ice_suffocation"] == 0 and s["flags"]["ice_total_days"] == 0)
    old_path_source = inspect.getsource(engine.tick) + inspect.getsource(engine._season_events)
    check("凿冰：旧低温三天固定 20% 折损路径已删除",
          "hibernation_crisis" not in old_path_source and "winter_low_temp_days" not in old_path_source)

    # 翠鸟在冰封无洞/有洞时，捕食成功率上限分别为 10%/25%。
    def kingfisher_probe(with_hole):
        x = base_state(turn=100)
        x["season"] = "冬"
        x["flags"]["ice_on"] = True
        if with_hole:
            x["chain"]["ice_hole"] = x["turn"] + 2
        x["populations"]["鳑鲏"] = 0
        x["populations"]["鲫鱼"] = 2  # 低猎物量下冰洞仍应固定恢复到 25%
        settler = {"name": "翠鸟", "health": 0.8, "since_hunt": 0, "desc_streak": 0}
        probe = HuntProbeR()
        engine._settler_hunt(x, settler, engine.SETTLER_TYPES["翠鸟"]["hunter"], [], probe)
        return probe.chances[1]
    check("冰封翠鸟：无洞 10%、有洞恢复 25%",
          abs(kingfisher_probe(False) - 0.10) < 1e-9
          and abs(kingfisher_probe(True) - 0.25) < 1e-9)


def test_once_rejections_and_help_texts():
    # 四灾各自的 already_helped 已在专项用例覆盖；这里集中检查错误码与六场提示。
    hints = engine.HUMAN_HELP_HINT
    check("六个人类可帮场景都自然提示前端动作",
          set(hints) == {"巴西龟入侵", "福寿螺入侵", "水葫芦飘入", "绿潮", "鼠患", "结冰"}
          and all("你的人类可以在前端帮忙" in text for text in hints.values()))


def test_human_result_notice_and_chronicle():
    expected_leads = {
        "expel_turtle": "你的人类帮你驱赶了巴西龟",
        "catch_snail": "你的人类帮你捞走了福寿螺",
        "pull_hyacinth": "你的人类帮你拔除了水葫芦",
        "hunt_rat": "你的人类帮你打退了田鼠",
        "skim_algae": "你的人类帮你捞走了水面的浮藻",
        "crack_ice": "你的人类帮你尝试了凿冰",
    }
    check("六种人类协作都有对应的小机文案",
          all(engine._human_action_notice(
              action, {"message": "完成。", "summary": {}}
          ).startswith(lead + "：完成。")
              for action, lead in expected_leads.items()))
    check("福寿螺卵块预防有独立小机文案",
          engine._human_action_notice(
              "catch_snail", {"message": "完成。", "summary": {"prevented": True}}
          ).startswith("你的人类帮你清理了岸边的福寿螺卵块："))

    s = base_state(turn=20)
    s["flags"]["apple_snail"] = {"status": "active", "count": 2,
                                     "human_helped": False}
    result = call(s, "catch_snail", {"count": 2})
    notices = s["pending_human_notices"]
    check("人类协作成功后生成给小机的待读通知",
          result["ok"] and len(notices) == 1
          and notices[0].startswith("你的人类帮你捞走了福寿螺：")
          and result["message"] in notices[0])
    check("人类协作通知同步写入年鉴",
          s["chronicle"][-1].endswith(notices[0]))
    first = engine._take_human_notices(s)
    second = engine._take_human_notices(s)
    check("小机通知只消费一次",
          len(first) == 1 and "🤝 人类协作" in first[0]
          and notices[0] in first[0] and second == [])

    rejected = base_state(turn=20)
    failed = call(rejected, "catch_snail", {"count": 2})
    check("人类协作失败不生成通知或年鉴",
          not failed["ok"] and rejected["pending_human_notices"] == []
          and rejected["chronicle"] == [])


def test_api_state_frontend_triggers():
    """正式前端只读 api_state；六种入口所需字段必须都投影出去。"""
    quiet = engine.api_state(base_state())
    check("正式状态：无灾害时不暴露小游戏入口",
          quiet["disasters"]["invasion"] is None
          and quiet["disasters"]["water_hyacinth_cover"] is None
          and not any(item["name"] in ("鼠患", "绿潮")
                      for item in quiet["disasters"]["biological"])
          and quiet["flags"]["ice_on"] is False
          and quiet["flags"]["apple_snail"] is None)

    s = base_state()
    s["flags"]["brazilian_turtle"] = "active"
    check("正式状态：巴西龟入口可识别",
          engine.api_state(s)["disasters"]["invasion"] == "巴西龟入侵")

    s = base_state()
    s["flags"]["apple_snail"] = {"status": "active", "count": 7,
                                     "human_helped": False}
    snail = engine.api_state(s)
    check("正式状态：福寿螺入口与剩余数可识别",
          snail["disasters"]["invasion"] == "福寿螺入侵"
          and snail["flags"]["apple_snail"]["count"] == 7)

    s = base_state()
    s["flags"]["water_hyacinth"] = {"day": 7, "cover": 0.12,
                                        "outbreak_cover": 0.12, "human_helped": False}
    check("正式状态：水葫芦入口可识别",
          engine.api_state(s)["disasters"]["water_hyacinth_cover"] == 0.12)

    s = base_state()
    s["flags"].setdefault("bio_disasters", {})["鼠患"] = {"remaining": 3,
                                                              "outbreak_count": 20,
                                                              "human_helped": False}
    check("正式状态：鼠患入口可识别",
          any(item["name"] == "鼠患" for item in engine.api_state(s)["disasters"]["biological"]))

    s = base_state()
    s["flags"].setdefault("bio_disasters", {})["绿潮"] = {"remaining": 4,
                                                              "human_helped": False,
                                                              "human_skim_total": 0.0}
    check("正式状态：绿潮入口可识别",
          any(item["name"] == "绿潮" for item in engine.api_state(s)["disasters"]["biological"]))

    s = base_state()
    s["season"] = "冬"
    s["flags"].update({"ice_on": True, "ice_suffocation": 2,
                         "ice_total_days": 5, "ice_ai_attempted": True})
    ice = engine.api_state(s)["flags"]
    check("正式状态：凿冰入口与冬季进度可识别",
          ice["ice_on"] is True and ice["ice_suffocation"] == 2
          and ice["ice_total_days"] == 5 and ice["ice_ai_attempted"] is True)


def test_old_save_compat_and_rng_inventory():
    s = engine.fresh_state(99)
    for key in ("ice_total_days", "ice_attempt_day", "ice_human_attempted",
                "ice_ai_attempted", "ice_attempt_roll", "ice_attempt_success"):
        s["flags"].pop(key, None)
    s["flags"]["apple_snail"] = "active"
    engine._migrate(s)
    check("旧档迁移：补齐凿冰字段并把 active 螺升级为 12 只",
          all(key in s["flags"] for key in ("ice_total_days", "ice_attempt_day",
                                             "ice_human_attempted", "ice_ai_attempted",
                                             "ice_attempt_roll", "ice_attempt_success"))
          and s["flags"]["apple_snail"]["count"] == 12)
    for _ in range(3):
        engine.tick(s)
    check("旧档迁移后 tick 正常", isinstance(engine.api_state(s), dict))

    # 代码级守门：六个人类 handler 中只有 crack_ice 可进入共享随机判定。
    deterministic_handlers = (engine._human_expel_turtle, engine._human_catch_snail,
                              engine._human_pull_hyacinth, engine._human_hunt_rat,
                              engine._human_skim_algae)
    check("PRNG 守门：除凿冰外的人类动作不引用 rng_from/random/chance",
          all(not any(token in inspect.getsource(fn)
                      for token in ("rng_from", ".random(", ".chance("))
              for fn in deterministic_handlers))
    crack_source = inspect.getsource(engine._ice_crack_attempt)
    check("PRNG 守门：新增成功掷骰仅位于每日共享凿冰判定",
          crack_source.count(".random()") == 1 and ".chance(" not in crack_source)


def main():
    test_unknown_and_bad_payload()
    test_turtle_and_migration()
    test_snail_count_and_suppression()
    test_snail_incubation()
    test_hyacinth_stalks_and_scaled_cost()
    test_rat_linear_calm_and_cooldown()
    test_green_tide_persistent_relief_and_baseline()
    test_crack_joint_hole_and_spring_loss()
    test_once_rejections_and_help_texts()
    test_human_result_notice_and_chronicle()
    test_api_state_frontend_triggers()
    test_old_save_compat_and_rng_inventory()
    print()
    if FAILURES:
        print("共 %d 项失败：" % len(FAILURES))
        for failure in FAILURES:
            print("  - " + failure)
        sys.exit(1)
    print("全部通过 ✅")


if __name__ == "__main__":
    main()
