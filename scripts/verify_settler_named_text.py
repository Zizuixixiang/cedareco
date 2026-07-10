#!/usr/bin/env python3
"""定居者昵称文案：逐池双路输出、原文兜底与 PRNG 对齐回归。"""

import copy
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import engine  # noqa: E402


NICKNAME = "阿澄"


def state_for(species, nickname=None, turn=7):
    state = engine.fresh_state(20260710)
    state["turn"] = turn
    state["weather"] = "晴"
    settler = engine._new_settler_dict(species, state=state)
    settler["nickname"] = nickname
    state["settlers"] = [settler]
    return state, settler


def random_cases():
    cases = []
    for species, pools in engine.SETTLER_HUNT_TEXT.items():
        named = engine.SETTLER_HUNT_TEXT_NAMED[species]
        for label, original, rewritten in zip(("hit", "miss", "absent"), pools, named):
            cases.append(("SETTLER_HUNT_TEXT.%s.%s" % (species, label), species,
                          original, rewritten, "random"))
    cases.extend([
        ("KINGFISHER_HIT_PANGPI", "翠鸟", engine.KINGFISHER_HIT_PANGPI,
         engine.KINGFISHER_HIT_PANGPI_NAMED, "random"),
        ("KINGFISHER_MISS_PANGPI", "翠鸟", engine.KINGFISHER_MISS_PANGPI,
         engine.KINGFISHER_MISS_PANGPI_NAMED, "random"),
        ("HERON_HIT_GRASS_CARP", "苍鹭", engine.HERON_HIT_GRASS_CARP,
         engine.HERON_HIT_GRASS_CARP_NAMED, "random"),
        ("HERON_MISS_GRASS_CARP", "苍鹭", engine.HERON_MISS_GRASS_CARP,
         engine.HERON_MISS_GRASS_CARP_NAMED, "random"),
        ("KINGFISHER_WINTER_DAILY", "翠鸟", engine.KINGFISHER_WINTER_DAILY,
         engine.KINGFISHER_WINTER_DAILY_NAMED, "random"),
        ("KINGFISHER_WINTER_HUNGRY", "翠鸟", engine.KINGFISHER_WINTER_HUNGRY,
         engine.KINGFISHER_WINTER_HUNGRY_NAMED, "random"),
        ("KINGFISHER_WINTER_CRITICAL", "翠鸟", engine.KINGFISHER_WINTER_CRITICAL,
         engine.KINGFISHER_WINTER_CRITICAL_NAMED, "random"),
        ("KINGFISHER_WINTER_LEAVE", "翠鸟", engine.KINGFISHER_WINTER_LEAVE,
         engine.KINGFISHER_WINTER_LEAVE_NAMED, "random"),
    ])
    for species, original in engine.SETTLER_GROWN.items():
        cases.append(("SETTLER_GROWN.%s" % species, species, original,
                      engine.SETTLER_GROWN_NAMED[species], "random"))
    return cases


def turn_cases():
    cases = []
    for species, original in engine.LONGEVITY_LEAVE_TEXT.items():
        cases.append(("LONGEVITY_LEAVE_TEXT.%s" % species, species, original,
                      engine.LONGEVITY_LEAVE_TEXT_NAMED[species], "turn"))
    for level, originals, named in (
            ("light", engine.SETTLER_WARN_LIGHT, engine.SETTLER_WARN_LIGHT_NAMED),
            ("heavy", engine.SETTLER_WARN_HEAVY, engine.SETTLER_WARN_HEAVY_NAMED)):
        for species, original in originals.items():
            if named.get(species):
                cases.append(("SETTLER_WARN_%s.%s" % (level, species), species,
                              original, named[species], "turn"))
    for species, original in engine.SETTLER_WAKE_TEXT.items():
        cases.append(("SETTLER_WAKE_TEXT.%s" % species, species, original,
                      engine.SETTLER_WAKE_TEXT_NAMED[species], "turn"))
    return cases


def recent_cases():
    return [
        ("GAZE_SETTLER.%s" % species, species, original,
         engine.GAZE_SETTLER_NAMED[species], "recent")
        for species, original in engine.GAZE_SETTLER.items()
    ]


def legacy_pick(state, rng, pool, mode, recent=None):
    avail = [(idx, engine._text_value(item)) for idx, item in enumerate(pool)
             if engine._text_parts(item)[2] is None
             or state["weather"] in engine._text_parts(item)[2]]
    if mode == "turn":
        return avail[state["turn"] % len(avail)][1]
    if mode == "recent":
        choices = [entry for entry in avail if entry[0] not in recent] or avail
        idx, text = choices[rng.randint(0, len(choices) - 1)]
        recent.append(idx)
        if len(recent) > 3:
            recent.pop(0)
        return text
    return avail[rng.randint(0, len(avail) - 1)][1]


def verify_selected_pools():
    cases = random_cases() + turn_cases() + recent_cases()
    for label, species, original, named, mode in cases:
        assert named, "%s 的昵称池为空" % label
        assert all("{nickname}" in engine._text_value(item) for item in named), label
        unnamed_state, unnamed = state_for(species)
        named_state, named_settler = state_for(species, NICKNAME)
        legacy_rng = engine.Mulberry32(991)
        unnamed_rng = engine.Mulberry32(991)
        named_rng = engine.Mulberry32(991)
        legacy_recent = [0] if mode == "recent" and len(original) > 1 else []
        unnamed_recent = list(legacy_recent)
        named_recent = list(legacy_recent)
        expected = legacy_pick(unnamed_state, legacy_rng, original, mode, legacy_recent)
        actual = engine._pick_settler_text(
            unnamed_state, unnamed_rng, unnamed, original, named, mode=mode,
            recent=unnamed_recent if mode == "recent" else None,
        )
        personalized = engine._pick_settler_text(
            named_state, named_rng, named_settler, original, named, mode=mode,
            recent=named_recent if mode == "recent" else None,
        )
        assert actual == expected, "%s 无昵称兜底改变" % label
        assert NICKNAME in personalized, "%s 未写入正确昵称：%s" % (label, personalized)
        assert unnamed_rng.state == named_rng.state, "%s 改变 PRNG 消耗" % label
    return len(cases)


def static_cases():
    cases = []
    for species, named_fields in engine.SETTLER_LEAVE_NAMED.items():
        for field, named in named_fields.items():
            original = engine.SETTLER_TEXT[species].get(field)
            if original is not None:
                pool = named if isinstance(named, list) else [named]
                cases.append(("SETTLER_TEXT.%s.%s" % (species, field), species,
                              original, pool))
    for label, originals, named in (
            ("SETTLER_HINTS", engine.SETTLER_HINTS, engine.SETTLER_HINTS_NAMED),
            ("SETTLER_PREY_GONE", engine.SETTLER_PREY_GONE, engine.SETTLER_PREY_GONE_NAMED),
            ("SETTLER_HIBERNATE_CHRON", engine.SETTLER_HIBERNATE_CHRON,
             engine.SETTLER_HIBERNATE_CHRON_NAMED),
            ("SETTLER_WAKE_CHRON", engine.SETTLER_WAKE_CHRON,
             engine.SETTLER_WAKE_CHRON_NAMED)):
        for species, rewritten in named.items():
            cases.append(("%s.%s" % (label, species), species,
                          originals[species], [rewritten]))
    for species in engine.SETTLER_HIBERNATE_TEXT:
        cases.append(("SETTLER_HIBERNATE_TEXT.%s" % species, species,
                      engine.SETTLER_HIBERNATE_TEXT[species][0],
                      engine.SETTLER_HIBERNATE_TEXT_NAMED[species]))
    for label, original, named in (
            ("SETTLER_GROWN_CHRON", engine.SETTLER_GROWN_CHRON,
             engine.SETTLER_GROWN_CHRON_NAMED),
            ("SETTLER_WARN_CHRON_LIGHT", engine.SETTLER_WARN_CHRON_LIGHT,
             engine.SETTLER_WARN_CHRON_LIGHT_NAMED),
            ("SETTLER_WARN_CHRON_HEAVY", engine.SETTLER_WARN_CHRON_HEAVY,
             engine.SETTLER_WARN_CHRON_HEAVY_NAMED)):
        for species, rewritten in named.items():
            cases.append(("%s.%s" % (label, species), species,
                          original % species, rewritten))
    for kind in engine.SHORT_HUNT:
        cases.append(("SHORT_HUNT.%s" % kind, "翠鸟",
                      engine.SHORT_HUNT[kind] % "翠鸟",
                      [engine.SHORT_HUNT_NAMED["翠鸟"][kind]]))
    for label, species, original, rewritten in cases:
        for turn in range(len(rewritten)):
            unnamed_state, unnamed = state_for(species, turn=turn)
            named_state, named_settler = state_for(species, NICKNAME, turn=turn)
            actual = engine._pick_settler_text(
                unnamed_state, None, unnamed, [original], rewritten, mode="turn")
            personalized = engine._pick_settler_text(
                named_state, None, named_settler, [original], rewritten, mode="turn")
            assert actual == original, "%s 无昵称兜底改变" % label
            assert NICKNAME in personalized, "%s 未写入正确昵称" % label
    return len(cases)


def verify_observe_ambient():
    for species in engine.OBSERVE_SETTLER_NAMED:
        pool = engine.OBSERVE_SETTLER_NAMED[species]
        assert len(pool) == 5, "%s observe named 池不是 5 条" % species
        for turn in range(len(pool)):
            unnamed_state, _ = state_for(species, turn=turn)
            named_state, _ = state_for(species, NICKNAME, turn=turn)
            assert engine._pick_settler_ambient(unnamed_state) \
                == engine._pick_ambient(unnamed_state, engine.OBSERVE_AMBIENT["settler"])
            personalized = engine._pick_settler_ambient(named_state)
            assert personalized == engine._text_value(pool[turn]).format(nickname=NICKNAME)
        named_state, named = state_for(species, NICKNAME, turn=0)
        second = copy.deepcopy(named)
        second["nickname"] = "阿岚"
        named_state["settlers"].append(second)
        ambiguous = engine._pick_settler_ambient(named_state)
        assert NICKNAME not in ambiguous and "阿岚" not in ambiguous


def verify_expanded_named_pools():
    expected_counts = {
        "observe": {species: 5 for species in engine.SETTLER_TYPES},
        "warn_light_duck": {"野鸭": 4},
        "warn_heavy_duck": {"野鸭": 4},
        "starve_duck": {"野鸭": 2},
        "hibernate": {"流浪乌龟": 3, "水蛇": 3},
        "wake": {"流浪乌龟": 4, "水蛇": 3},
        "grown_chron": {species: 2 for species in engine.SETTLER_TYPES},
        "warn_light_chron": {species: 2 for species in engine.SETTLER_TYPES},
        "warn_heavy_chron": {species: 2 for species in engine.SETTLER_TYPES},
    }
    pools = {
        "observe": engine.OBSERVE_SETTLER_NAMED,
        "warn_light_duck": {"野鸭": engine.SETTLER_WARN_LIGHT_NAMED["野鸭"]},
        "warn_heavy_duck": {"野鸭": engine.SETTLER_WARN_HEAVY_NAMED["野鸭"]},
        "starve_duck": {"野鸭": engine.SETTLER_LEAVE_NAMED["野鸭"]["starve"]},
        "hibernate": engine.SETTLER_HIBERNATE_TEXT_NAMED,
        "wake": engine.SETTLER_WAKE_TEXT_NAMED,
        "grown_chron": engine.SETTLER_GROWN_CHRON_NAMED,
        "warn_light_chron": engine.SETTLER_WARN_CHRON_LIGHT_NAMED,
        "warn_heavy_chron": engine.SETTLER_WARN_CHRON_HEAVY_NAMED,
    }
    for label, counts in expected_counts.items():
        for species, count in counts.items():
            pool = pools[label][species]
            assert len(pool) == count, "%s.%s 条数错误" % (label, species)
            assert all("{nickname}" in engine._text_value(item) for item in pool), \
                "%s.%s 有文案缺少昵称" % (label, species)

    routed = [
        ("warn_light_duck", "野鸭", engine.SETTLER_WARN_LIGHT["野鸭"]),
        ("warn_heavy_duck", "野鸭", engine.SETTLER_WARN_HEAVY["野鸭"]),
        ("starve_duck", "野鸭", [engine.SETTLER_TEXT["野鸭"]["starve"]]),
    ]
    routed.extend(("hibernate", species, engine.SETTLER_HIBERNATE_TEXT[species])
                  for species in engine.SETTLER_HIBERNATE_TEXT)
    routed.extend(("wake", species, engine.SETTLER_WAKE_TEXT[species])
                  for species in engine.SETTLER_WAKE_TEXT)
    routed.extend(("grown_chron", species, [engine.SETTLER_GROWN_CHRON % species])
                  for species in engine.SETTLER_GROWN_CHRON_NAMED)
    routed.extend(("warn_light_chron", species,
                   [engine.SETTLER_WARN_CHRON_LIGHT % species])
                  for species in engine.SETTLER_WARN_CHRON_LIGHT_NAMED)
    routed.extend(("warn_heavy_chron", species,
                   [engine.SETTLER_WARN_CHRON_HEAVY % species])
                  for species in engine.SETTLER_WARN_CHRON_HEAVY_NAMED)
    for label, species, unnamed_pool in routed:
        named_pool = pools[label][species]
        for turn in range(len(named_pool)):
            unnamed_state, unnamed = state_for(species, turn=turn)
            named_state, named = state_for(species, NICKNAME, turn=turn)
            actual_unnamed = engine._pick_settler_text(
                unnamed_state, None, unnamed, unnamed_pool, named_pool, mode="turn")
            actual_named = engine._pick_settler_text(
                named_state, None, named, unnamed_pool, named_pool, mode="turn")
            expected_unnamed = engine._weather_texts(unnamed_state, unnamed_pool)
            expected_named = engine._weather_texts(named_state, named_pool)
            assert actual_unnamed == expected_unnamed[turn % len(expected_unnamed)]
            assert actual_named == expected_named[turn % len(expected_named)].format(
                nickname=NICKNAME)

    assert engine.SETTLER_GROWN_CHRON == "那只幼年的%s长成了，开始独自在池塘讨生活。"
    assert engine.SETTLER_WARN_CHRON_LIGHT == "%s 开始吃不饱了。"
    assert engine.SETTLER_WARN_CHRON_HEAVY == "%s 濒临饿死，命悬一线。"

    parts = {
        "翠鸟": ("羽", "喙", "肋骨"),
        "苍鹭": ("羽", "喙", "肋骨"),
        "野鸭": ("羽", "喙", "肋骨"),
        "水蛇": ("鳞", "嘴", "身条"),
        "流浪乌龟": ("壳", "嘴", "壳沿"),
        "螃蟹": ("壳", "嘴", "壳沿"),
    }
    for species, (cover, mouth, outline) in parts.items():
        assert engine.SETTLER_GROWN_CHRON_NAMED[species] == [
            "{nickname}的个头够了。%s上的纹路长齐了。" % cover,
            "{nickname}不再跟在别的影子后面了。它自己就是一道完整的影子。",
        ]
        assert engine.SETTLER_WARN_CHRON_LIGHT_NAMED[species] == [
            "{nickname}开始花更多时间盯住水面。%s探下去的次数多了，抬上来的动静少了。" % mouth,
            "{nickname}的觅食时间拉长了。水面留下的细纹比从前密，但搅起的泥星很少。",
        ]
        assert engine.SETTLER_WARN_CHRON_HEAVY_NAMED[species] == [
            "{nickname}的%s显出来了。它还在觅食，只是动作越来越慢。" % outline,
            "{nickname}把剩下的力气都用在了水边。但水里能回应它的东西不多了。",
        ]
    for group in (engine.SETTLER_GROWN_CHRON_NAMED,
                  engine.SETTLER_WARN_CHRON_LIGHT_NAMED,
                  engine.SETTLER_WARN_CHRON_HEAVY_NAMED):
        for pool in group.values():
            assert all("/" not in engine._text_value(item) for item in pool)

    for item in engine.SETTLER_LEAVE_NAMED["野鸭"]["starve"]:
        body = engine._text_value(item).format(nickname=NICKNAME)
        assert engine._classify_event("settler_leave:" + body)["name"] == "野鸭离开"
    for group in (engine.SETTLER_HIBERNATE_TEXT_NAMED,
                  engine.SETTLER_WAKE_TEXT_NAMED):
        for pool in group.values():
            for item in pool:
                body = engine._text_value(item).format(nickname=NICKNAME)
                assert "定居者" not in engine._classify_event("settler:" + body)["name"]

    return sum(sum(counts.values()) for counts in expected_counts.values())


def stocked_state(named):
    state = engine.fresh_state(314159)
    state["unlocked_species"] = list(engine.RESIDENT_SPECIES)
    for species in engine.RESIDENT_SPECIES:
        state["populations"][species] = 80.0
    state["env"]["detritus"] = 200.0
    for index, species in enumerate(sorted(engine.SETTLER_SPECIES)):
        settler = engine._new_settler_dict(species, state=state)
        settler["nickname"] = ("住客%d" % index) if named else None
        state["settlers"].append(settler)
    return state


def verify_parallel_days():
    unnamed = stocked_state(False)
    named = stocked_state(True)
    for day in range(30):
        engine.tick(unnamed)
        engine.tick(named)
        assert unnamed["rng_state"] == named["rng_state"], "第%d天 PRNG 未对齐" % (day + 1)


def main():
    selected = verify_selected_pools()
    static = static_cases()
    expanded = verify_expanded_named_pools()
    verify_observe_ambient()
    verify_parallel_days()
    print("named/unnamed pool routes: PASS (%d selected + %d static pools)" % (selected, static))
    print("expanded named pools/body-part split: PASS (%d templates checked)" % expanded)
    print("observe same-species ambiguity fallback: PASS")
    print("30-day named/unnamed rng_state alignment: PASS")


if __name__ == "__main__":
    main()
