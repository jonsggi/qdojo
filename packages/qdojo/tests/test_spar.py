import json

from qdojo import spar


def test_summarize_money_and_fighters(tmp_path):
    rows = [
        {"round_id": 1, "belt": "white", "settled": True, "n_solved": 2, "first_solve_latency_ticks": 40, "stakes_in": 2000,
         "payouts_out": 7000, "house_delta": -5000, "carry": 0,
         "entries": [{"identity": "A" * 60, "name": "RYU", "verdict": "winner", "stake": 1000, "commit_latency_ticks": 40},
                     {"identity": "B" * 60, "name": "KEN", "verdict": "solved", "stake": 1000, "commit_latency_ticks": 90}],
         "payouts": [{"identity": "A" * 60, "amount": 7000, "kind": "win"}]},
        {"round_id": 2, "belt": "green", "settled": True, "n_solved": 0, "first_solve_latency_ticks": None, "stakes_in": 1000,
         "payouts_out": 0, "house_delta": 1000, "carry": 6000,
         "entries": [{"identity": "B" * 60, "name": "KEN", "verdict": "wrong", "stake": 1000, "commit_latency_ticks": 10}],
         "payouts": []},
    ]
    p = tmp_path / "m.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    s = spar.summarize(str(p))
    assert s["rounds"] == 2 and s["money"] == {"stakes_in": 3000, "payouts_out": 7000, "house_delta": -4000, "carry_now": 6000}
    assert s["belts"]["white"]["solve_rate"] == 1.0 and s["belts"]["green"]["solve_rate"] == 0.0
    assert s["fighters"]["RYU"] == {"rounds": 1, "solved": 1, "wins": 1, "stakes": 1000, "earned": 7000, "net": 6000, "avg_solve_ticks": 40.0}
    assert s["fighters"]["KEN"]["net"] == -2000 and s["fighters"]["KEN"]["solved"] == 1
    assert list(s["fighters"]) == ["RYU", "KEN"]     # sorted by net, best first
