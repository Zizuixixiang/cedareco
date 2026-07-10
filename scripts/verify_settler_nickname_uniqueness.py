#!/usr/bin/env python3
"""Regression checks for settler nickname uniqueness."""

import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import engine


def add_current(state, species, arrive_day):
    settler = engine._new_settler_dict(species, state=state)
    settler["arrive_day"] = arrive_day
    state["settlers"].append(settler)
    return settler


def departed_life(species, nickname, reason="food", return_eligible=True):
    return {
        "name": species,
        "species": species,
        "nickname": nickname,
        "origin": "arrived",
        "arrive_day": 10,
        "leave_day": 60,
        "age": 30,
        "leave_age": 30,
        "reason": reason,
        "return_eligible": return_eligible,
        "return_records": [],
        "descendant_of": None,
    }


def check_current_same_species_conflict():
    state = engine.fresh_state(1)
    state["turn"] = 100
    first = add_current(state, "翠鸟", 80)
    second = add_current(state, "翠鸟", 90)
    first["nickname"] = "小蓝"

    result = engine._cmd_name(state, ["[D-90]", "翠鸟", "小蓝"])
    assert "已经叫「小蓝」" in result
    assert second["nickname"] is None


def check_return_candidate_reserves_nickname():
    state = engine.fresh_state(1)
    state["turn"] = 100
    state["folio"]["settlers"]["翠鸟"] = {
        "times": 1,
        "max_days": 30,
        "residents": [departed_life("翠鸟", "小蓝")],
    }
    current = add_current(state, "翠鸟", 90)

    result = engine._cmd_name(state, ["翠鸟", "小蓝"])
    assert "可能回归" in result
    assert current["nickname"] is None


def check_same_settler_can_keep_its_name():
    state = engine.fresh_state(1)
    state["turn"] = 100
    current = add_current(state, "翠鸟", 90)
    current["nickname"] = "小蓝"

    result = engine._cmd_name(state, ["翠鸟", "小蓝"])
    assert result.startswith("🏷")
    assert current["nickname"] == "小蓝"


def check_different_species_can_share_nickname():
    state = engine.fresh_state(1)
    state["turn"] = 100
    kingfisher = add_current(state, "翠鸟", 80)
    turtle = add_current(state, "流浪乌龟", 90)
    kingfisher["nickname"] = "小蓝"

    result = engine._cmd_name(state, ["流浪乌龟", "小蓝"])
    assert result.startswith("🏷")
    assert turtle["nickname"] == "小蓝"


def check_nonreturning_life_releases_nickname():
    state = engine.fresh_state(1)
    state["turn"] = 100
    state["folio"]["settlers"]["翠鸟"] = {
        "times": 1,
        "max_days": 30,
        "residents": [departed_life(
            "翠鸟", "小蓝", reason="old_age", return_eligible=False
        )],
    }
    current = add_current(state, "翠鸟", 90)

    result = engine._cmd_name(state, ["翠鸟", "小蓝"])
    assert result.startswith("🏷")
    assert current["nickname"] == "小蓝"


def main():
    checks = [
        check_current_same_species_conflict,
        check_return_candidate_reserves_nickname,
        check_same_settler_can_keep_its_name,
        check_different_species_can_share_nickname,
        check_nonreturning_life_releases_nickname,
    ]
    for check in checks:
        check()
    print("settler nickname uniqueness checks: PASS (%d cases)" % len(checks))


if __name__ == "__main__":
    main()
