import random

from qdojo import model, payload


def test_default_cohort_runs_and_money_conserves_shape():
    p = model.Params(rounds=60)
    r = model.simulate(p, [model.Archetype.from_dict(d) for d in model.DEFAULT_COHORT], random.Random(1))
    assert r["rounds_played"] > 0 and r["house_cost_per_round"] >= 0
    assert set(r["by_archetype"]) == {"specialist", "llm", "agent", "evo", "npc"}
    assert r["by_archetype"]["npc"]["earned_share"] == 0.0            # NPCs never solve, never earn


def test_ladder_promotes_the_specialist_out_of_white():
    p = model.Params(rounds=100, payout_mode=payload.MODE_FIRST, bond_bps=0)
    r = model.run(p, replicates=3)
    spec = r["by_archetype"]["specialist"]
    assert spec["final_belts"].get("white", 0) < 1.0                  # it does not stay white
    assert r["promotions"]["mean"] > 0


def test_matching_costs_less_than_a_fixed_seed():
    base = model.Params(rounds=80, bond_bps=0)
    res = model.sweep(base, {"match_bps": [0, 10000]}, replicates=3)
    fixed, matched = res[0], res[1]
    assert fixed["combo"]["match_bps"] == 0 and matched["house_cost_per_round"] <= fixed["house_cost_per_round"]


def test_calibrate_reads_fighters_json():
    fj = {"fighters": [{"identity": "A" * 60, "name": "X", "rounds_played": 5, "by_belt": {"white": {"rounds": 3, "solved": 2, "wins": 1, "avg_solve_ticks": 12.0}}}]}
    c = model.calibrate(fj)
    assert c[0]["solve"]["white"] == 0.67 and c[0]["solve"]["blue"] == 0.0 and c[0]["latency"]["white"][0] == 12.0


def test_calibrate_house_funded_comes_from_identities_not_names():
    fj = {"fighters": [{"identity": "A" * 60, "name": "NPC-FAKE", "rounds_played": 5, "by_belt": {}},
                       {"identity": "B" * 60, "name": "REAL", "rounds_played": 5, "by_belt": {}}]}
    c = {x["name"]: x for x in model.calibrate(fj, npcs={"B" * 60})}
    assert c["NPC-FAKE"]["house_funded"] is False and c["REAL"]["house_funded"] is True
