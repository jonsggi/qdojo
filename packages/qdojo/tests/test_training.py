import ast
import json
import os

import pytest

from qdojo import training
from qdojo.training import Attempt

REAL = os.path.join(os.path.dirname(__file__), "..", "..", "..", "apps", "web", "data", "history.json")


def rd(**kw):
    """A settled round in the published shape."""
    base = {"round_id": 7, "belt": "white", "title": "White belt: the sum", "entry_fee": 1000,
            "commit_window": 300, "reveal_window": 120, "publish_tick": 1000, "payout_mode": "first",
            "house_seed": 0, "match_bps": 0, "carry_in": 0, "rake_bps": 0,
            "riddle": {"round_id": 7, "title": "White belt: the sum", "statement": "s",
                       "input": "1 2", "answer_format": "integer"},
            "entries": [], "settlement": {"answer": "142", "payouts": [], "void": False}}
    return base | kw


def entry(idn, tick, verdict="winner", stake=1000, answer="142"):
    return {"identity": idn * 60, "commit_tick": tick, "commit_tx": idn * 60, "stake": stake,
            "reveal_tick": tick + 1, "reveal_tx": idn * 60, "answer": answer, "verdict": verdict}


# ------------------------------------------------- the safety property itself

def test_training_cannot_send():
    """The guarantee is the module's shape, not a flag somebody must remember.

    If this fails, do not 'fix' it by adding a conditional: training must stay
    a thing that holds nothing it could send money with.
    """
    src = os.path.join(os.path.dirname(training.__file__), "training.py")
    tree = ast.parse(open(src, encoding="utf-8").read())
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not called & {"send", "bow", "settle_and_pay", "transfer"}, called
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            imported.add(n.module or "")
            imported |= {a.name for a in n.names}
        elif isinstance(n, ast.Import):
            imported |= {a.name for a in n.names}
    assert "chain" not in " ".join(imported), imported
    assert "QubicCli" not in imported and "onboard" not in imported
    # Scan the CODE, not the prose: the module's docstring says at length that
    # it holds no seed and no chain, and a substring grep would trip on its own
    # explanation. Strip docstrings, then look at what is left.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and ast.get_docstring(node):
            node.body = node.body[1:]
    code = ast.unparse(tree)
    for forbidden in ("payload.encode", "chain", "conf", "Signer"):
        assert forbidden not in code, f"training.py's code touches {forbidden!r}"


# ------------------------------------------------------------------- grading

def test_a_fast_correct_answer_takes_first():
    r = rd(entries=[entry("a", 1040), entry("b", 1050)],
           settlement={"answer": "142", "void": False,
                       "payouts": [{"identity": "a" * 60, "amount": 2000, "kind": "win"}]})
    a = training.grade(r, "142", seconds=1.0)
    assert a.correct and a.rank == 1 and a.rivals == 2
    assert a.solve_ticks == training.SCHEDULE_OFFSET + 2
    assert a.would_pay and a.would_pay > 0 and a.net == a.would_pay - 1000


def test_a_slow_correct_answer_places_behind_the_rivals():
    r = rd(entries=[entry("a", 1030), entry("b", 1035)],
           settlement={"answer": "142", "void": False,
                       "payouts": [{"identity": "a" * 60, "amount": 2000, "kind": "win"}]})
    a = training.grade(r, "142", seconds=30.0)
    assert a.correct and a.rank == 3


def test_a_wrong_answer_loses_the_stake_and_is_priced_at_zero():
    a = training.grade(rd(), "999", seconds=1.0)
    assert a.correct is False and a.would_pay == 0 and a.net == -1000


def test_an_answer_after_the_window_cannot_pay():
    a = training.grade(rd(commit_window=10), "142", seconds=60.0)
    assert a.correct and a.in_window is False and a.would_pay == 0
    assert "window" in a.why_unpriced


def test_a_solver_that_failed_is_recorded_not_scored():
    a = training.grade(rd(), None, seconds=0.5, error="solver exited 2: no model")
    assert a.correct is False or a.correct is None
    assert a.error and a.would_pay is None


def test_a_round_nobody_solved_is_flagged():
    """The best hook we have: a correct answer would have taken it uncontested."""
    a = training.grade(rd(), "142", seconds=1.0)
    assert a.unsolved is True and a.rivals == 0 and a.rank == 1


def test_an_unreproducible_round_declines_to_price_rather_than_guess():
    """house_fighters is not published, so on an NPC round the matched seed
    comes out wrong. An unknown is not a zero."""
    r = rd(settlement={"answer": "142", "void": False,
                       "payouts": [{"identity": "z" * 60, "amount": 99999, "kind": "win"}]})
    a = training.grade(r, "142", seconds=1.0)
    assert a.correct is True
    assert a.would_pay is None and "not fully published" in a.why_unpriced


def test_entries_are_rebuilt_each_time_because_settle_rewrites_verdicts():
    r = rd(payout_mode="podium", entries=[entry("a", 1030), entry("b", 1031), entry("c", 1032),
                                          entry("d", 1033)])
    first = [e.verdict for e in training.entries_from_round(r)]
    training.grade(r, "142", seconds=1.0)
    assert [e.verdict for e in training.entries_from_round(r)] == first


# ---------------------------------------------------------------- scorecard

def test_scorecard_counts_only_what_it_can_stand_behind():
    at = [Attempt(round_id=1, belt="white", title="t", answer_format="integer", seconds=1.0,
                  correct=True, would_pay=500, net=-500, stake=1000, solve_ticks=22, in_window=True),
          Attempt(round_id=2, belt="white", title="t", answer_format="integer", seconds=1.0,
                  correct=True, would_pay=None, stake=1000, solve_ticks=30, in_window=True),
          Attempt(round_id=3, belt="blue", title="t", answer_format="integer", seconds=1.0,
                  correct=False, would_pay=0, net=-1000, stake=1000)]
    s = training.scorecard(at)
    assert s["fought"] == 3 and s["solved"] == 2
    assert s["would_have_placed"] == 1 and s["would_have_earned"] == 500
    assert s["unpriced"] == 1                      # never counted as an earning of 0
    assert s["by_belt"]["white"] == {"fought": 2, "solved": 2}
    assert s["by_belt"]["blue"]["solved"] == 0


def test_scorecard_of_nothing_does_not_divide_by_zero():
    s = training.scorecard([])
    assert s["fought"] == 0 and s["median_solve_ticks"] is None


# ------------------------------------------------------- against the real log

@pytest.mark.skipif(not os.path.exists(REAL), reason="no live export here")
def test_the_real_corpus_is_gradeable():
    h = json.load(open(REAL, encoding="utf-8"))
    rounds = training.settled_rounds(h)
    assert len(rounds) > 100
    # Every recent round must re-settle to exactly what the house paid. If this
    # breaks, the money column of the scorecard has stopped being true.
    recent = rounds[-30:]
    assert all(training.reproduces(r) for r in recent)


@pytest.mark.skipif(not os.path.exists(REAL), reason="no live export here")
def test_replay_scores_a_perfect_solver_against_real_rounds():
    """A 'solver' that already knows the answer must score 100%, which proves
    the plumbing end to end: riddle in, answer compared, money graded."""
    import subprocess, sys, textwrap
    h = json.load(open(REAL, encoding="utf-8"))
    rounds = training.settled_rounds(h)[-3:]
    truth = {r["round_id"]: r["settlement"]["answer"] for r in rounds}
    prog = textwrap.dedent(f"""
        import json, sys
        r = json.load(sys.stdin)
        print(json.dumps({{"answer": {truth!r}[r["round_id"]]}}))
    """)
    out = training.replay({"rounds": rounds}, [sys.executable, "-c", prog], rounds=3)
    assert len(out) == 3
    assert all(a.correct for a in out), [a.error for a in out]
    assert all(a.would_pay is not None for a in out)
    s = training.scorecard(out)
    assert s["solved"] == 3 and s["fought"] == 3
