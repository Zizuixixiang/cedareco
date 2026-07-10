#!/usr/bin/env python3
"""回归验证：雨雪雾天气不会混入带天气门控的晴天天光文案。"""

import copy
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import engine  # noqa: E402


ADVERSE_WEATHERS = ("小雨", "雨", "梅雨", "雪", "大雪", "雾")
SAMPLE_WEATHERS = ("雨", "雪", "雾", "晴")
SEASONS = ("春", "夏", "秋", "冬")


def annotated_pools():
    pools = []
    pools.extend(v["desc_pool"] for v in engine.SEASON_ENV.values() if v.get("desc_pool"))
    pools.extend(engine.SEASON_OMEN.values())
    pools.extend(engine.GAZE_SEASON.values())
    pools.extend(engine.GAZE_ENV.values())
    pools.extend(engine.GAZE_SUBJECT.values())
    pools.extend(engine.GAZE_SETTLER.values())
    pools.extend(engine.GAZE_SETTLER_NAMED.values())
    pools.append(engine.GAZE_EMPTY)
    pools.extend(engine.OBSERVE_AMBIENT.values())
    pools.extend(engine.OBSERVE_SETTLER_NAMED.values())
    pools.extend(v for v in engine.SEASON_TEXT.values() if isinstance(v, list))
    pools.extend(engine.CHOICE_EVENTS[key]["desc_pool"] for key in ("干旱", "热浪"))
    pools.extend(engine.PAIR_SETTLE_TEXT.values())
    pools.extend(engine.SETTLER_GROWN.values())
    pools.extend(engine.SETTLER_GROWN_NAMED.values())
    pools.extend(engine.SETTLER_INTERACTIONS.values())
    pools.extend(engine.DISEASE_ONSET.values())
    pools.extend((engine.DISEASE_SPREAD, engine.DISEASE_PEAK, engine.DISEASE_END))
    pools.extend((engine.TURTLE_WAKE_TEXT, engine.FIREFLY_LEGEND_TEXT))
    pools.extend(engine.SETTLER_WAKE_TEXT_NAMED.values())
    return pools


def weather_annotations():
    annotations = []
    for pool in annotated_pools():
        for item in pool:
            text, _deps, weathers = engine._text_parts(item)
            if weathers is not None:
                annotations.append((text, weathers))
    return annotations


def populated_state(seed, weather, season="春", turn=1):
    state = engine.fresh_state(seed)
    state["rng_state"] = seed
    state["weather"] = weather
    state["season"] = season
    state["turn"] = turn
    state["unlocked_species"] = list(engine.RESIDENT_SPECIES)
    for name in engine.GAZE_SUBJECT:
        state["populations"][name] = 20.0
    state["env"].update({
        "dissolved_oxygen": 8.0,
        "nutrients": 20.0,
        "detritus": 10.0,
        "turbidity": 0.05,
    })
    state["settlers"] = [
        {"name": name, "recent_gaze": [], "health": 1.0, "age": 0}
        for name in engine.GAZE_SETTLER
    ]
    return state


def assert_weather_safe(text, weather, annotations):
    blocked = [line for line, allowed in annotations
               if weather not in allowed and line in text]
    assert not blocked, "%s天出现受限文案：%r" % (weather, blocked)


def verify_pool_filters(annotations):
    for weather in ADVERSE_WEATHERS + ("晴",):
        state = populated_state(1, weather)
        for turn in range(40):
            state["turn"] = turn
            for pool in annotated_pools():
                assert engine._weather_texts(state, pool), \
                    "%s天下文案池被天气过滤为空" % weather
                picked = engine._pick_ambient(state, pool)
                if picked is not None:
                    assert_weather_safe(picked, weather, annotations)
                picked = engine._pick_t(state, pool)
                if picked is not None:
                    assert_weather_safe(picked, weather, annotations)


def verify_observe_and_gaze(annotations):
    sunny_observe = []
    sunny_gaze = []
    samples = {}
    for weather in ADVERSE_WEATHERS + ("晴",):
        for season in SEASONS:
            for seed in range(1, 161):
                turn = seed % 30 or 1
                state = populated_state(seed, weather, season, turn)
                observe = engine._observe_text(state, [])
                gaze = engine._cmd_gaze(copy.deepcopy(state))
                assert_weather_safe(observe, weather, annotations)
                assert_weather_safe(gaze, weather, annotations)
                if weather == "晴":
                    sunny_observe.append(observe)
                    sunny_gaze.append(gaze)
                if weather in SAMPLE_WEATHERS and weather not in samples:
                    samples[weather] = (observe, gaze)

                empty = populated_state(seed, weather, season, turn)
                empty["settlers"] = []
                for name in engine.GAZE_SUBJECT:
                    empty["populations"][name] = 0.0
                empty_gaze = engine._cmd_gaze(empty)
                assert_weather_safe(empty_gaze, weather, annotations)

    sunny_text = "\n".join(sunny_observe + sunny_gaze)
    assert "阳光探到水底" in sunny_text
    assert "日光照透" in sunny_text
    return samples


def verify_rng_consumption():
    for season in SEASONS:
        sunny = populated_state(20260710, "晴", season, 17)
        rainy = copy.deepcopy(sunny)
        rainy["weather"] = "雨"
        for _ in range(8):
            engine._cmd_gaze(sunny)
            engine._cmd_gaze(rainy)
            assert sunny["rng_state"] == rainy["rng_state"], \
                "天气过滤改变了 gaze 的 PRNG 消耗序列"

    sunny_state = populated_state(1, "晴")
    rainy_state = populated_state(1, "雨")
    for pool in annotated_pools():
        sunny_rng = engine.Mulberry32(99)
        rainy_rng = engine.Mulberry32(99)
        engine._pick_weather(sunny_state, sunny_rng, pool)
        engine._pick_weather(rainy_state, rainy_rng, pool)
        assert sunny_rng.state == rainy_rng.state, \
            "天气过滤改变了随机文案池的 PRNG 消耗序列"


def verify_fallback():
    state = populated_state(7, "雨")
    only_sun = [
        ("只应在晴天出现 A", (), engine.SUNLIGHT_WEATHERS),
        ("只应在晴天出现 B", (), engine.SUNLIGHT_WEATHERS),
    ]
    assert engine._pick_ambient(state, only_sun) is None

    original = engine.OBSERVE_AMBIENT["low_do"]
    try:
        engine.OBSERVE_AMBIENT["low_do"] = only_sun
        state["env"]["dissolved_oxygen"] = 3.0
        output = engine._observe_ambient(state)
        assert output and "只应在晴天出现" not in output
    finally:
        engine.OBSERVE_AMBIENT["low_do"] = original


def one_line(text):
    return text.replace("\n", " / ")[:180]


def main():
    annotations = weather_annotations()
    assert annotations
    verify_pool_filters(annotations)
    samples = verify_observe_and_gaze(annotations)
    verify_rng_consumption()
    verify_fallback()

    print("weather-gated copy entries: %d" % len(annotations))
    print("observe/gaze cases: %d" % ((len(ADVERSE_WEATHERS) + 1) * len(SEASONS) * 160 * 2))
    print("RNG alignment: 4 seasons x 8 consecutive gaze: OK")
    print("all-filter ambient fallback: OK")
    for weather in SAMPLE_WEATHERS:
        observe, gaze = samples[weather]
        print("[%s observe] %s" % (weather, one_line(observe)))
        print("[%s gaze] %s" % (weather, one_line(gaze)))


if __name__ == "__main__":
    main()
