#!/usr/bin/env python3
"""回归验证：human_action 人类前端协作接口。

覆盖：
- 六个 action 各自"灾害中调用生效 / 非灾害中调用被拒"；
- 全程不消耗主 RNG 序列（rng_state 不变）、不推进天数（turn 不变）；
- 巴西龟驱赶累计器：人机合计 ≥2 才赶走，旧档 expelled_once 迁移视为已累计 1；
- 绿潮达标缩短 / 未达标次日少扣溶氧；冰窒息值累积与凿冰暂停；
- 旧档缺新字段时 _migrate 补默认不崩。
"""

import copy
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


def base_state(turn=10):
    s = engine.fresh_state(20260710)
    s["turn"] = turn
    return s


def call(state, action, payload=None):
    """调用 human_action 并断言 rng/turn 不被触碰。"""
    rng_before = state["rng_state"]
    turn_before = state["turn"]
    res = engine.human_action(state, action, payload)
    check("%s：不消耗主 RNG 序列" % action, state["rng_state"] == rng_before)
    check("%s：不推进天数" % action, state["turn"] == turn_before)
    return res


def test_unknown_and_bad_payload():
    s = base_state()
    res = call(s, "feed_dragon")
    check("未知 action 被拒", not res["ok"] and res["error"] == "unknown_action")
    res = call(s, "expel_turtle", "not-a-dict")
    check("非 dict payload 被拒", not res["ok"] and res["error"] == "bad_payload")


def test_expel_turtle():
    # 非灾害中被拒
    s = base_state()
    res = call(s, "expel_turtle")
    check("expel_turtle：无龟时被拒", not res["ok"] and res["error"] == "not_active")

    # 人类先赶一次 -> expelled_once；龟回访后小机再赶 -> gone（人机合计 2）
    s = base_state()
    engine._trigger_brazilian_turtle(s, [])
    res = call(s, "expel_turtle")
    check("expel_turtle：灾害中生效（第 1 次暂离）",
          res["ok"] and res["summary"]["turtle"] == "expelled_once"
          and res["summary"]["human_expel_count"] == 1
          and res["summary"]["return_day"] is not None)
    check("expel_turtle：人类驱赶撤销同名待决策", s["pending_choice"] is None)
    check("expel_turtle：暂离时再驱赶被拒",
          not call(s, "expel_turtle")["ok"])
    # 回访（同一只：累计保留）
    s["turn"] = res["summary"]["return_day"]
    engine._trigger_brazilian_turtle(s, [])
    check("回访保留人机累计", s["flags"]["human_expel_count"] == 1)
    msg = engine._resolve_choice(s, s["pending_choice"], 1, [])
    s["pending_choice"] = None
    check("人 1 次 + 机 1 次 = gone", s["flags"]["brazilian_turtle"] == "gone" and bool(msg))
    check("gone 解锁「驱逐者」", "驱逐者" in s["achievements"])

    # 纯小机路径行为等价：赶一次 expelled_once、回访后再赶一次 gone
    s = base_state()
    engine._trigger_brazilian_turtle(s, [])
    engine._resolve_choice(s, s["pending_choice"], 1, [])
    s["pending_choice"] = None
    check("小机第 1 次驱赶 -> expelled_once",
          s["flags"]["brazilian_turtle"] == "expelled_once")
    s["turn"] = s["flags"]["brazilian_turtle_return_day"]
    engine._trigger_brazilian_turtle(s, [])
    engine._resolve_choice(s, s["pending_choice"], 1, [])
    s["pending_choice"] = None
    check("小机第 2 次驱赶 -> gone", s["flags"]["brazilian_turtle"] == "gone")

    # 新的一只（非回访）触发时累计清零
    s = base_state()
    s["flags"]["ai_expel_count"] = 1
    s["flags"]["human_expel_count"] = 1
    s["flags"]["brazilian_turtle"] = None
    engine._trigger_brazilian_turtle(s, [])
    check("新入侵清零人机累计",
          s["flags"]["ai_expel_count"] == 0 and s["flags"]["human_expel_count"] == 0)


def test_turtle_migration():
    # 旧档：expelled_once 且无累计字段 -> 迁移视为已累计 1，再赶一次即 gone
    s = base_state()
    s["flags"]["brazilian_turtle"] = "expelled_once"
    s["flags"]["brazilian_turtle_return_day"] = s["turn"]
    for k in ("ai_expel_count", "human_expel_count", "human_snail_catch_count",
              "human_crack_count", "ice_suffocation", "ice_suff_pause_day"):
        s["flags"].pop(k, None)
    engine._migrate(s)
    check("旧档迁移：expelled_once 计为 1", s["flags"]["ai_expel_count"] == 1)
    engine._trigger_brazilian_turtle(s, [])
    res = call(s, "expel_turtle")
    check("旧档迁移后人类再赶一次 -> gone",
          res["ok"] and res["summary"]["turtle"] == "gone"
          and res["summary"]["total_expel_count"] == 2)


def test_catch_snail():
    s = base_state()
    res = call(s, "catch_snail")
    check("catch_snail：无螺时被拒", not res["ok"] and res["error"] == "not_active")

    s = base_state()
    engine._trigger_apple_snail(s, [])
    detritus_before = s["env"]["detritus"]
    res = call(s, "catch_snail")
    check("catch_snail：灾害中生效（等同小机手动捞）",
          res["ok"] and s["flags"]["apple_snail"] == "gone"
          and abs(s["env"]["detritus"] - detritus_before - 10) < 1e-9
          and res["summary"]["human_snail_catch_count"] == 1)
    check("catch_snail：撤销同名待决策", s["pending_choice"] is None)
    check("catch_snail：清完再捞被拒", not call(s, "catch_snail")["ok"])

    # clearing（螃蟹清剿中）人类也可直接捞完
    s = base_state()
    s["flags"]["apple_snail"] = {"status": "clearing", "leave_day": s["turn"] + 3}
    res = call(s, "catch_snail")
    check("catch_snail：clearing 状态也生效", res["ok"] and s["flags"]["apple_snail"] == "gone")


def test_pull_hyacinth():
    s = base_state()
    res = call(s, "pull_hyacinth", {"cover": 0.1})
    check("pull_hyacinth：无水葫芦时被拒", not res["ok"] and res["error"] == "not_active")

    # 潜伏期（前 3 天）不可拔
    s = base_state(turn=20)
    s["flags"]["water_hyacinth"] = {"day": 19, "cover": 0.04}
    res = call(s, "pull_hyacinth", {"cover": 0.1})
    check("pull_hyacinth：潜伏期被拒", not res["ok"] and res["error"] == "not_active")

    # 成势后可拔，payload clamp 防作弊
    s = base_state(turn=30)
    s["flags"]["water_hyacinth"] = {"day": 20, "cover": 0.40}
    res = call(s, "pull_hyacinth", {"cover": 9.0})
    check("pull_hyacinth：覆盖率削减被 clamp 到上限",
          res["ok"] and abs(res["summary"]["applied"] - engine.HUMAN_PULL_MAX) < 1e-9
          and abs(s["flags"]["water_hyacinth"]["cover"] - 0.25) < 1e-9)
    res = call(s, "pull_hyacinth", {"cover": -1})
    check("pull_hyacinth：非法 payload 被拒", not res["ok"] and res["error"] == "bad_payload")
    # 拔光即清除
    s["flags"]["water_hyacinth"]["cover"] = 0.05
    res = call(s, "pull_hyacinth", {"cover": 0.15})
    check("pull_hyacinth：拔光即清除",
          res["ok"] and res["summary"]["cleared"] and s["flags"]["water_hyacinth"] is None)


def test_hunt_rat():
    s = base_state()
    res = call(s, "hunt_rat", {"count": 3})
    check("hunt_rat：无鼠患时被拒", not res["ok"] and res["error"] == "not_active")

    s = base_state()
    s["populations"]["田鼠"] = 18.0
    s["flags"]["bio_disasters"] = {"鼠患": {"remaining": 3}}
    res = call(s, "hunt_rat", {"count": 99})
    check("hunt_rat：单次数量被 clamp 到上限",
          res["ok"] and res["summary"]["hits"] == engine.HUMAN_RAT_MAX
          and abs(s["populations"]["田鼠"] - 13.0) < 1e-9 and not res["summary"]["plague_over"])
    res = call(s, "hunt_rat", {"count": 5})
    res = call(s, "hunt_rat", {"count": 5})
    check("hunt_rat：田鼠降到阈值以下鼠患提前平息",
          res["ok"] and res["summary"]["plague_over"]
          and "鼠患" not in s["flags"]["bio_disasters"]
          and s["populations"]["田鼠"] <= engine.RAT_CALM_THRESHOLD)
    check("hunt_rat：平息后再打被拒", not call(s, "hunt_rat", {"count": 1})["ok"])


def test_skim_algae():
    s = base_state()
    res = call(s, "skim_algae", {"amount": 30})
    check("skim_algae：无绿潮时被拒", not res["ok"] and res["error"] == "not_active")

    # 未达标：次日少扣一半溶氧
    s = base_state()
    s["populations"]["水藻"] = 600.0
    s["flags"]["bio_disasters"] = {"绿潮": {"remaining": 3}}
    res = call(s, "skim_algae", {"amount": 10})
    green = s["flags"]["bio_disasters"]["绿潮"]
    check("skim_algae：未达标 -> 次日溶氧减压",
          res["ok"] and not res["summary"]["target_met"]
          and green["do_relief_day"] == s["turn"] + 1 and green["remaining"] == 3)
    res = call(s, "skim_algae", {"amount": 30})
    check("skim_algae：每天限一次", not res["ok"] and res["error"] == "already_today")
    # 达标：缩短 1 天；缩到 0 当场结束
    green["human_skim_day"] = -1
    res = call(s, "skim_algae", {"amount": 25})
    check("skim_algae：达标缩短 1 天", res["ok"] and green["remaining"] == 2)
    green["human_skim_day"] = -1
    green["remaining"] = 1
    res = call(s, "skim_algae", {"amount": 999})
    check("skim_algae：藻量被 clamp 且缩到 0 当场结束",
          res["ok"] and res["summary"]["ended"]
          and "绿潮" not in s["flags"]["bio_disasters"])

    # 未达标减压确实作用在 tick 上：对照同一状态有无 relief 的溶氧差
    s1 = engine.fresh_state(7)
    s1["turn"] = 40
    s1["season"] = "夏"
    s1["flags"]["bio_disasters"] = {"绿潮": {"remaining": 5}}
    s2 = copy.deepcopy(s1)
    s2["flags"]["bio_disasters"]["绿潮"]["do_relief_day"] = s2["turn"] + 1
    engine.tick(s1)
    engine.tick(s2)
    diff = s2["env"]["dissolved_oxygen"] - s1["env"]["dissolved_oxygen"]
    check("skim_algae：减压日 tick 少扣 0.4 溶氧", abs(diff - 0.4) < 1e-6,
          "diff=%.4f" % diff)


def test_crack_ice():
    s = base_state()
    s["season"] = "夏"
    res = call(s, "crack_ice")
    check("crack_ice：未结冰时被拒", not res["ok"] and res["error"] == "not_active")

    s = base_state(turn=100)
    s["season"] = "冬"
    s["flags"]["ice_on"] = True
    s["flags"]["ice_suffocation"] = 4
    res = call(s, "crack_ice")
    check("crack_ice：结冰期生效",
          res["ok"] and s["flags"]["crack_count"] == 1
          and s["flags"]["human_crack_count"] == 1
          and s["flags"]["ice_suff_pause_day"] == s["turn"] + 1
          and engine._chain_active(s, "ice_hole"))
    s["flags"]["crack_count"] = 3
    res = call(s, "crack_ice")
    check("crack_ice：受 crack_count 共享上限约束",
          not res["ok"] and res["error"] == "crack_limit")

    # 冰窒息值：结冰日 +1，暂停日不涨，入春清零
    s = engine.fresh_state(7)
    s["turn"] = 96  # 次日 97 为冬季（91-120）
    s["season"] = "冬"
    s["flags"]["ice_on"] = True
    s["env"]["water_temp"] = 1.0
    before = s["flags"]["ice_suffocation"]
    engine.tick(s)
    check("冰窒息值：结冰日累积 +1", s["flags"]["ice_suffocation"] == before + 1)
    s["flags"]["ice_suff_pause_day"] = s["turn"] + 1
    level = s["flags"]["ice_suffocation"]
    engine.tick(s)
    check("冰窒息值：凿冰次日不涨", s["flags"]["ice_suffocation"] == level)
    engine.tick(s)
    check("冰窒息值：暂停仅一天", s["flags"]["ice_suffocation"] == level + 1)
    s["turn"] = 120
    s["flags"]["human_crack_count"] = 2
    engine.tick(s)  # 入春
    check("入春清零冰窒息值与人类凿冰计数",
          s["season"] == "春" and s["flags"]["ice_suffocation"] == 0
          and s["flags"]["human_crack_count"] == 0)


def test_old_save_compat():
    """旧档缺全部新字段：_migrate 补默认，tick 与 human_action 不崩。"""
    s = engine.fresh_state(99)
    for k in ("ai_expel_count", "human_expel_count", "human_snail_catch_count",
              "human_crack_count", "ice_suffocation", "ice_suff_pause_day"):
        s["flags"].pop(k, None)
    engine._migrate(s)
    check("旧档迁移：新字段补默认",
          all(k in s["flags"] for k in ("ai_expel_count", "human_expel_count",
                                        "human_snail_catch_count", "human_crack_count",
                                        "ice_suffocation", "ice_suff_pause_day")))
    for _ in range(3):
        engine.tick(s)
    res = engine.human_action(s, "expel_turtle")
    check("旧档迁移后 tick / human_action 正常", isinstance(res, dict) and not res["ok"])


def main():
    test_unknown_and_bad_payload()
    test_expel_turtle()
    test_turtle_migration()
    test_catch_snail()
    test_pull_hyacinth()
    test_hunt_rat()
    test_skim_algae()
    test_crack_ice()
    test_old_save_compat()
    print()
    if FAILURES:
        print("共 %d 项失败：" % len(FAILURES))
        for f in FAILURES:
            print("  - " + f)
        sys.exit(1)
    print("全部通过 ✅")


if __name__ == "__main__":
    main()
