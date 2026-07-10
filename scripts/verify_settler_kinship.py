#!/usr/bin/env python3
"""Regression checks for settler kinship, returns, and population caps."""

import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import engine


class AlwaysRng:
    state = 0

    def chance(self, probability):
        return True

    def randint(self, low, high):
        return low

    def random(self):
        return 0.0


def base_state(turn=1):
    state = engine.fresh_state(7)
    state["turn"] = turn
    state["season"] = "春"
    state["populations"]["浮萍"] = 500
    state["populations"]["孑孓"] = 500
    state["populations"]["鲫鱼"] = 500
    state["populations"]["泥鳅"] = 500
    state["populations"]["鳑鲏"] = 500
    return state


def adult(state, species="野鸭", origin="arrived", parent_ids=None):
    settler = engine._new_settler_dict(
        species, state=state, origin=origin, parent_ids=parent_ids,
    )
    settler["age"] = 20
    settler["juvenile"] = False
    settler["juvenile_left"] = 0
    return settler


def process(state):
    events = []
    engine._process_settlers(state, events, AlwaysRng())
    return events


def bred(events):
    return any(event.startswith("settler_birth:") for event in events)


def check_parent_child_blocked():
    state = base_state()
    parent = adult(state)
    other_parent = adult(state)
    child = adult(
        state, origin="born",
        parent_ids=[parent["settler_id"], other_parent["settler_id"]],
    )
    state["settlers"] = [parent, child]
    assert not bred(process(state))


def check_siblings_blocked():
    state = base_state()
    parents = ["old-parent-a", "old-parent-b"]
    first = adult(state, origin="born", parent_ids=parents)
    second = adult(state, origin="born", parent_ids=parents)
    state["settlers"] = [first, second]
    assert not bred(process(state))


def check_unrelated_second_generation_can_breed():
    state = base_state()
    first = adult(state, origin="born", parent_ids=["a", "b"])
    second = adult(state, origin="born", parent_ids=["c", "d"])
    state["settlers"] = [first, second]
    assert bred(process(state))
    child = state["settlers"][-1]
    assert set(child["parent_ids"]) == {first["settler_id"], second["settler_id"]}


def check_returned_child_keeps_identity_and_kinship():
    state = base_state(turn=40)
    parent = adult(state)
    other_parent = adult(state)
    child = adult(
        state, origin="born",
        parent_ids=[parent["settler_id"], other_parent["settler_id"]],
    )
    child_id = child["settler_id"]
    engine._archive_settler_life(state, child, "food")
    state["turn"] = 41
    returned = engine._returning_settler(state, "野鸭", AlwaysRng())[0]
    assert returned["settler_id"] == child_id
    assert returned["parent_ids"] == child["parent_ids"]
    state["settlers"] = [parent, returned]
    assert not bred(process(state))


def check_same_ancestor_descendants_are_siblings():
    state = base_state(turn=80)
    ancestor = adult(state)
    ancestor["nickname"] = "老白"
    ancestor["age"] = 60
    engine._archive_settler_life(state, ancestor, "old_age")

    engine._add_settler(state, "野鸭", [], AlwaysRng())
    engine._add_settler(state, "野鸭", [], AlwaysRng())
    assert len(state["settlers"]) == 2
    assert state["settlers"][0]["parent_ids"] == state["settlers"][1]["parent_ids"]
    assert not bred(process(state))


def check_invitation_repairs_kinship_deadlock():
    state = base_state()
    parents = ["old-parent-a", "old-parent-b"]
    state["settlers"] = [
        adult(state, origin="born", parent_ids=parents),
        adult(state, origin="born", parent_ids=parents),
    ]
    assert engine._can_invite_settler(state, "野鸭") is True

    state["settlers"].append(adult(state))
    assert engine._can_invite_settler(state, "野鸭") is False


def check_total_population_cap_is_hard_limit():
    state = base_state()
    # 苍鹭上限为 3；旧逻辑只数非 born，这种 2+1 组合会误生第 4 只。
    first = adult(state, species="苍鹭")
    second = adult(state, species="苍鹭")
    child = adult(
        state, species="苍鹭", origin="born",
        parent_ids=[first["settler_id"], second["settler_id"]],
    )
    state["settlers"] = [first, second, child]
    assert not bred(process(state))
    assert engine._settler_count(state, "苍鹭") == 3
    assert engine._can_invite_settler(state, "苍鹭") is False


def check_lite_roundtrip_preserves_identity_and_annual_limit():
    state = base_state()
    state["settlers"] = [adult(state), adult(state)]
    assert bred(process(state))
    original_ids = [settler["settler_id"] for settler in state["settlers"]]

    restored = engine._restore_from_lite(engine._lite_snapshot(state))
    engine._migrate(restored)
    assert [settler["settler_id"] for settler in restored["settlers"]] == original_ids
    assert restored["breed_year"]["野鸭"] == state["turn"] // engine.YEAR_LEN
    assert not bred(process(restored))

    newcomer = adult(restored, species="水蛇")
    assert newcomer["settler_id"] not in original_ids


def check_legacy_born_remains_conservatively_blocked():
    state = base_state()
    founder = adult(state)
    legacy_child = adult(state, origin="born", parent_ids=["placeholder"])
    for key in ("settler_id", "parent_ids", "legacy_kinship_unknown"):
        legacy_child.pop(key, None)
    state["settlers"] = [founder, legacy_child]
    engine._migrate(state)
    assert legacy_child["legacy_kinship_unknown"] is True
    assert not bred(process(state))


def check_legacy_return_chain_cannot_wash_kinship():
    state = base_state(turn=50)
    return_record = {"day": 30, "after_days": 10, "from_leave_day": 20}
    born_life = {
        "name": "野鸭", "species": "野鸭", "nickname": "小白",
        "origin": "born", "arrive_day": 10, "leave_day": 20,
        "age": 10, "leave_age": 10, "reason": "food",
        "return_eligible": False, "return_records": [return_record.copy()],
        "descendant_of": None,
    }
    returned_life = {
        "name": "野鸭", "species": "野鸭", "nickname": "小白",
        "origin": "returned", "arrive_day": 30, "leave_day": 40,
        "age": 20, "leave_age": 20, "reason": "food",
        "return_eligible": True, "return_records": [return_record.copy()],
        "descendant_of": None,
    }
    state["folio"]["settlers"]["野鸭"] = {
        "times": 2, "max_days": 20, "residents": [born_life, returned_life],
    }
    engine._migrate(state)
    assert born_life["settler_id"] == returned_life["settler_id"]
    assert returned_life["legacy_kinship_unknown"] is True

    returned = engine._returning_settler(state, "野鸭", AlwaysRng())[0]
    assert returned["settler_id"] == born_life["settler_id"]
    assert returned["legacy_kinship_unknown"] is True


def check_descendant_marker_survives_return():
    state = base_state(turn=80)
    ancestor = adult(state)
    ancestor["nickname"] = "老白"
    engine._archive_settler_life(state, ancestor, "old_age")
    engine._add_settler(state, "野鸭", [], AlwaysRng())
    descendant = state["settlers"].pop()
    marker = dict(descendant["descendant_of"])
    parent_ids = list(descendant["parent_ids"])
    engine._archive_settler_life(state, descendant, "food")
    state["turn"] += 1

    returned = engine._returning_settler(state, "野鸭", AlwaysRng())[0]
    assert returned["descendant_of"] == marker
    assert returned["parent_ids"] == parent_ids


def main():
    checks = [
        check_parent_child_blocked,
        check_siblings_blocked,
        check_unrelated_second_generation_can_breed,
        check_returned_child_keeps_identity_and_kinship,
        check_same_ancestor_descendants_are_siblings,
        check_invitation_repairs_kinship_deadlock,
        check_total_population_cap_is_hard_limit,
        check_lite_roundtrip_preserves_identity_and_annual_limit,
        check_legacy_born_remains_conservatively_blocked,
        check_legacy_return_chain_cannot_wash_kinship,
        check_descendant_marker_survives_return,
    ]
    for check in checks:
        check()
    print("settler kinship checks: PASS (%d cases)" % len(checks))


if __name__ == "__main__":
    main()
