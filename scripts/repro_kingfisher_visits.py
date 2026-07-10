#!/usr/bin/env python3
"""Reproduce visitor folio counts around kingfisher settlement choices."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import engine


class ScriptRng:
    def __init__(self, chances=None, randint_value=2):
        self.chances = list(chances or [])
        self.randint_value = randint_value
        self.state = 0

    def chance(self, p):
        if self.chances:
            return self.chances.pop(0)
        return False

    def randint(self, a, b):
        return max(a, min(b, self.randint_value))

    def random(self):
        return 0.99

    def uniform(self, a, b):
        return a + (b - a) * self.random()


def base_state():
    state = engine.fresh_state(4242)
    state["turn"] = 140
    state["season"] = engine.season_of(state["turn"])
    state["populations"]["鲫鱼"] = 20
    state["populations"]["鳑鲏"] = 0
    state["folio"]["visitors"]["翠鸟"] = {"count": 5, "notes": ["掠食鲫鱼"]}
    state["choice_cooldowns"] = {"__any__": 0, "翠鸟定居": 0}
    return state


def show(label, state, events, before):
    rec = state["folio"]["visitors"].get("翠鸟", {})
    print("== %s ==" % label)
    print("count: %s -> %s" % (before, rec.get("count", 0)))
    print("notes:", ",".join(rec.get("notes", [])))
    print("pending:", state.get("pending_choice", {}).get("event") if state.get("pending_choice") else None)
    if state.get("pending_choice"):
        print("desc:", state["pending_choice"]["desc"])
    print("events:")
    for ev in events:
        print("  " + ev)
    print()


def run_random_events(label, state):
    before = state["folio"]["visitors"].get("翠鸟", {}).get("count", 0)
    events = []
    # First random-event chance is the kingfisher visit; all later visitors miss.
    engine._random_events(state, events, ScriptRng([True]), state["season"])
    show(label, state, events, before)


def heron_state(count):
    state = engine.fresh_state(5151)
    state["turn"] = 140
    state["season"] = engine.season_of(state["turn"])
    state["populations"]["鲫鱼"] = 20
    state["folio"]["visitors"]["苍鹭"] = {"count": count, "notes": []}
    state["choice_cooldowns"] = {"__any__": 0, "苍鹭": 0, "苍鹭定居": 0}
    return state


def run_heron_settlement():
    state = heron_state(3)
    before = state["folio"]["visitors"]["苍鹭"]["count"]
    events = []
    engine._random_events(
        state,
        events,
        # kingfisher, bat, cat, snake, hedgehog, weasel, deer miss; heron hits.
        ScriptRng([False, False, False, False, False, False, False, True], randint_value=4),
        state["season"],
    )
    rec = state["folio"]["visitors"]["苍鹭"]
    print("== heron settlement visit at count=3 ==")
    print("count: %s -> %s" % (before, rec.get("count", 0)))
    print("notes:", ",".join(rec.get("notes", [])))
    print("pending:", state.get("pending_choice", {}).get("event") if state.get("pending_choice") else None)
    if state.get("pending_choice"):
        print("desc:", state["pending_choice"]["desc"])
    print("events:")
    for ev in events:
        print("  " + ev)
    print()


def run_heron_normal_choice_resolution():
    state = heron_state(0)
    before = state["folio"]["visitors"]["苍鹭"]["count"]
    events = []
    engine._random_events(
        state,
        events,
        ScriptRng([False, False, False, False, False, False, False, True], randint_value=4),
        state["season"],
    )
    after_trigger = state["folio"]["visitors"]["苍鹭"]["count"]
    choice_events = []
    engine._resolve_choice(state, state["pending_choice"], 1, choice_events)
    after_choose = state["folio"]["visitors"]["苍鹭"]["count"]
    print("== heron normal choice counts once ==")
    print("count: %s -> %s -> %s" % (before, after_trigger, after_choose))
    print("notes:", ",".join(state["folio"]["visitors"]["苍鹭"].get("notes", [])))
    print("events:")
    for ev in events + choice_events:
        print("  " + ev)
    print()


def main():
    ready = base_state()
    run_random_events("choice-ready visit at count=5", ready)

    suppressed = base_state()
    suppressed["pending_choice"] = {
        "event": "水华",
        "desc": "dummy",
        "choices": ["a", "b"],
    }
    run_random_events("other pending choice suppresses settlement", suppressed)

    cooldown = base_state()
    cooldown["choice_cooldowns"]["__any__"] = cooldown["turn"] - 1
    run_random_events("global cooldown suppresses settlement", cooldown)

    wait_state = base_state()
    # Keep an old choice pending to exercise the tick/wait can_choose path.
    wait_state["pending_choice"] = {
        "event": "水华",
        "desc": "dummy",
        "choices": ["a", "b"],
    }
    before = wait_state["folio"]["visitors"]["翠鸟"]["count"]
    original_random_events = engine._random_events
    try:
        def forced_random_events(state, events, rng, season):
            return original_random_events(state, events, ScriptRng([True]), season)

        engine._random_events = forced_random_events
        events = engine.tick(wait_state)
    finally:
        engine._random_events = original_random_events
    show("full tick with existing pending choice", wait_state, events, before)
    run_heron_settlement()
    run_heron_normal_choice_resolution()


if __name__ == "__main__":
    main()
