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


def test_sensei_gate_runs_through_the_real_settlement():
    """The model holds no sensei rule of its own: under the sensei gate the
    engine seats the seniors and settle() pays them out of their own pot, so
    across a whole run the seniors can never take out more than they put in."""
    p = model.Params(rounds=100, gate="sensei", rake_bps=2000, bond_bps=0)
    r = model.simulate(p, [model.Archetype.from_dict(d) for d in model.DEFAULT_COHORT], random.Random(3))
    assert r["sensei_seats_per_round"] > 0
    assert -1000 <= r["sensei_net_per_seat"] <= 0                 # a fair pool less the rake, never the beginners' money
    assert r["carry_end"] >= 0 and r["avg_carry_in"] >= 0
    res = model.sweep(model.Params(rounds=40, bond_bps=0), {"gate": ["strict", "sensei"]}, replicates=2)
    assert res[0]["sensei_seats_per_round"] == 0 and res[0]["sensei_net_per_seat"] is None
    assert res[1]["sensei_seats_per_round"] > 0


def test_fixed_fee_mode_never_moves_the_fee():
    p = model.Params(rounds=40, demand="ev", rake_bps=2000)
    r = model.simulate(p, [model.Archetype.from_dict(d) for d in model.DEFAULT_COHORT], random.Random(1))
    assert all(set(v["series"]) == {1000} for v in r["fees"].values())
    assert all(len(v["series"]) == len(v["entrants"]) for v in r["fees"].values())


def test_auto_fee_moves_per_belt_and_stays_between_floor_and_f_star():
    p = model.Params(rounds=100, fee_mode="auto", demand="ev", refill=True, rake_bps=2000, seed_cap=5000, min_players=3,
                     fee_headroom=2, fee_floor=100)
    r = model.simulate(p, [model.Archetype.from_dict(d) for d in model.DEFAULT_COHORT], random.Random(1))
    f_star = 5000 / (5 * 0.2)
    for belt, v in r["fees"].items():
        assert v["series"] and all(100 <= f <= f_star for f in v["series"]), (belt, v["series"])
        assert v["series"][0] == 1000                                  # no history: the start fee
    assert len({v["final"] for v in r["fees"].values()}) > 1           # the belts price differently
    assert all(v is None or v >= 0 for v in r["subsidy_per_seat"].values())


def test_hopeless_fighters_stay_home_under_ev_demand():
    hopeless = [{"name": "dud", "solve": {b: 0.0 for b in model.Params().belts},
                 "latency": {b: [10, 3] for b in model.Params().belts}, "count": 6}]
    cohort = [model.Archetype.from_dict(d) for d in hopeless]
    sits = model.simulate(model.Params(rounds=20, demand="none"), cohort, random.Random(1))
    stays = model.simulate(model.Params(rounds=20, demand="ev"), cohort, random.Random(1))
    assert sits["rounds_played"] == 20 and stays["rounds_played"] == 0 and stays["void_rounds"] == 20


def test_corollary_retires_the_seed_on_the_taper():
    p = model.Params(rounds=100, demand="ev", refill=True, rake_bps=2000, target_pot=10000, target_pot_taper=50)
    r = model.simulate(p, [model.Archetype.from_dict(d) for d in model.DEFAULT_COHORT], random.Random(1))
    assert r["seed_retired_round"] is not None and r["seed_retired_round"] <= 60
    assert all(c == 0 for c in r["seed_cap_final"].values())
    r = model.run(p, replicates=2)
    assert r["seed_retired_round"] is not None and "fee_trajectory" in r
