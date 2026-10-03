"""The advertised starter planner and the builder's benchmark (AUD-029, AUD-031).

Every observation here is produced by the engine (training.run_fight and
training.observation), not written by hand, so a field the starter reads that
the arena does not send would fail here first.
"""
import functools
import json
import subprocess
import sys

import pytest

from qdojo.cli import main
from qdojo.combat import codec, engine, npcs, planner, replaycheck
from qdojo.combat import evaluate as E
from qdojo.combat.rules import CANDIDATE_3, KNOWN, PUBLIC_ARENA, by_version
from qdojo.combat.training import Contestant, observation, practice_context, practice_fighter_id, run_fight
from qdojo.combat.types import FighterState, FightState

from .conftest import ROOT

STARTER = ROOT / "examples/combat/planner_minimal.py"
DOWNLOAD = ROOT / "apps/web/combat/planner_minimal.py"
CMD = [sys.executable, str(STARTER)]
C3 = by_version(CANDIDATE_3)
# A loaded two-CPU CI host can take over a second to start Python; a timeout
# here would test the host, not the planner. Logic errors still fail.
SLOW_HOST_MS = 20_000
NEW_MOVE_USERS = ("stander", "feinter", "spam-last-stand", "spam-feint", "cycle-feint-last-stand")


def _opponent(name, rules):
    if name in npcs.ROSTER:
        return Contestant(name, npc=name)
    return Contestant(name, policy=E.policy_by_name(name, rules), policy_id=name)


def _fight(rules, opp, n, cmd=CMD):
    you = Contestant("you", command=cmd, budget_ms=SLOW_HOST_MS)
    replay = run_fight(you, _opponent(opp, rules), bytes([n]) * 32, 1, rules)
    return replay, you.diagnostics


def test_the_download_is_the_repository_example():
    assert DOWNLOAD.read_bytes() == STARTER.read_bytes()


def test_the_starter_targets_the_public_arena_ruleset():
    text = STARTER.read_text()
    assert PUBLIC_ARENA == CANDIDATE_3
    for version, digest in KNOWN.items():          # it knows every packaged ruleset by digest
        assert digest in text and version in text


@pytest.mark.parametrize("version", sorted(KNOWN))
def test_complete_fights_never_fall_back_or_get_adjusted(version):
    """Every supported ruleset, against the roster and (candidate 3) opponents
    that actually play LAST_STAND and FEINT."""
    rules = by_version(version)
    opponents = list(npcs.ROSTER) + (list(NEW_MOVE_USERS) if len(rules.submitted) > 6 else [])
    used_new = set()
    for i, opp in enumerate(opponents):
        replay, diags = _fight(rules, opp, i)
        assert replay["fallbacks"] == [], (version, opp, diags)
        assert not any(d.get("adjusted") or d.get("error") for d in diags), (version, opp, diags)
        assert replay["ruleset_digest"] == rules.digest.hex()
        other = "B" if replay["fighters"]["A"]["name"] == "you" else "A"
        for r in replay["rounds"]:
            for b in r["beats"]:
                used_new.add(b[other]["effective"])
    if len(rules.submitted) > 6:
        assert {"LAST_STAND", "FEINT"} <= used_new, "the opponents must really execute the new moves"


def _obs(rules, me, opp, history, round_index):
    """An engine-built observation for `me` with `history` = (prior rounds, my slot)."""
    prior, slot = history
    ids = tuple(sorted((practice_fighter_id("you"), practice_fighter_id("them"))))
    ctx = practice_context(rules, 1, ids)
    state = FightState(round_index, me, opp) if slot == "A" else FightState(round_index, opp, me)
    return json.loads(json.dumps(observation(rules, ctx, state, slot, ids, prior[:round_index],
                                             planner.DEFAULT_BUDGET_MS)))


def _prior_against(rules, opp_name, rounds=2):
    """Real prior-round records of a fight against `opp_name`, and the starter's slot in it."""
    replay = _history_fight(rules.semantic_version, opp_name)
    return replay["rounds"][:rounds], ("A" if replay["fighters"]["A"]["name"] == "you" else "B")


@functools.cache
def _history_fight(version, opp_name):
    return _fight(by_version(version), opp_name, 7)[0]


def _plan(obs):
    ran = planner.run(CMD, obs, SLOW_HOST_MS)
    return ran.plan, ran.stderr


@pytest.mark.parametrize("version", sorted(KNOWN))
@pytest.mark.parametrize("stamina,power,round_index", [(48, 1, 2), (3, 1, 2), (0, 0, 2), (20, 0, 1), (11, 1, 0)])
def test_low_stamina_spent_power_and_mixed_histories(version, stamina, power, round_index):
    rules = by_version(version)
    hp = rules.initial[0]
    for opp in (["stander", "feinter", "mixed-v1"] if len(rules.submitted) > 6 else ["mixed-v1", "turtle-v1"]):
        prior = _prior_against(rules, opp, rounds=round_index) if round_index else ([], "A")
        me = FighterState(hp - 30, min(stamina, rules.max_stamina), 0, 2, power)
        them = FighterState(hp, rules.max_stamina, 0, 0, 1)
        obs = _obs(rules, me, them, prior, round_index)
        plan, _ = _plan(obs)
        legal, why = planner.legal_plan(rules, me, plan)
        assert why is None, (version, opp, plan, why)
        engine.validate_plan(rules, me, plan)


def test_it_uses_the_new_moves_sensibly():
    hp = C3.initial[0]
    # Trailing a non-blocker: a LAST_STAND filler.
    plan, err = _plan(_obs(C3, FighterState(hp - 40, 48, 0, 0, 1), FighterState(hp, 48, 0, 0, 1),
                           _prior_against(C3, "jabber-v1"), 2))
    assert "LAST_STAND" in [a.name for a in plan.actions], err
    # Against a blocker: FEINT sets up the guard break.
    plan, err = _plan(_obs(C3, FighterState(hp, 48, 0, 0, 1), FighterState(hp, 48, 0, 0, 1),
                           _prior_against(C3, "turtle-v1"), 2))
    assert "FEINT" in [a.name for a in plan.actions], err
    # The same history under candidate 2 never names a move that ruleset lacks.
    c2 = by_version("combat-v1-candidate-2")
    plan, _ = _plan(_obs(c2, FighterState(hp - 40, 48, 0, 0, 1), FighterState(hp, 48, 0, 0, 1), ([], "A"), 2))
    assert {a.name for a in plan.actions} <= {"JAB", "KICK", "BLOCK", "DUCK", "THROW", "RECOVER"}


def test_an_unsupported_ruleset_is_a_clear_diagnostic():
    obs = _obs(C3, FighterState.initial(C3), FighterState.initial(C3), ([], "A"), 0)
    obs["ruleset_digest"] = "ab" * 32
    p = subprocess.run(CMD, input=json.dumps(obs), text=True, capture_output=True, timeout=30)
    assert p.returncode == 2 and p.stdout == ""
    assert "unsupported ruleset_digest" in p.stderr and "combat-v1-candidate-3" in p.stderr


# ---- evaluate --planner (AUD-031) ---------------------------------------------

BAD = "import json,sys\nobs=json.load(sys.stdin)\nif obs['round_index']==1: sys.exit('round 1 is not written yet')\n" \
      "print(json.dumps({'schema':'qdojo.combat.plan.v1','actions':['JAB']*6,'power_slot':-1}))\n"


def _evaluate(capsys, *argv):
    code = 0
    try:
        main(["combat", "evaluate", "--budget-ms", str(SLOW_HOST_MS), *argv])
    except SystemExit as exc:
        code = exc.code
    return code, capsys.readouterr()


def test_evaluate_a_planner_and_compare_two_versions(tmp_path, capsys):
    bad = tmp_path / "bad.py"
    bad.write_text(BAD)
    code, out = _evaluate(capsys, "--planner", f"{sys.executable} {STARTER}", "--planner", f"{sys.executable} {bad}",
                          "--opponent", "feinter", "--opponent", "jabber-v1", "--seeds", "2", "--json")
    doc = json.loads(out.out)
    assert code == 1 and "fallback plan" in out.err          # a failing planner is never a silent success
    assert doc["schema"] == "qdojo.combat.evaluation.v1"
    assert doc["semantic_version"] == PUBLIC_ARENA and doc["ruleset_digest"] == C3.digest.hex()
    assert doc["fights_per_opponent"] == 4 and doc["suite"] == "test" and doc["opponents"] == ["feinter", "jabber-v1"]
    good, broken = doc["planners"]
    assert good["planner"]["fallback_rounds"] == 0 and good["planner"]["rounds"] > 0
    assert good["total"]["fights"] == 8 and good["total"]["W"] + good["total"]["D"] + good["total"]["L"] == 8
    assert broken["planner"]["failures"] == {"EXIT": broken["planner"]["fallback_rounds"]}
    assert broken["planner"]["fights_with_fallback"] == broken["planner"]["fights"] == 8
    assert "round 1 is not written yet" in broken["planner"]["first_error"]
    assert all(r["fallback_rounds"] > 0 for r in broken["rows"])
    (cmp,) = doc["comparisons"]
    assert cmp["pairs"] == 4 and cmp["mean_difference"] < 0


def test_evaluation_is_reproducible_and_seed_suites_differ(capsys):
    args = ["--planner", f"{sys.executable} {STARTER}", "--opponent", "mixed-v1", "--seeds", "3", "--json"]
    a = json.loads(_evaluate(capsys, *args)[1].out)
    b = json.loads(_evaluate(capsys, *args)[1].out)
    assert a["planners"][0]["rows"] == b["planners"][0]["rows"]
    train = json.loads(_evaluate(capsys, *args, "--suite", "train")[1].out)
    assert E.eval_seed("train/mixed-v1", 0) != E.eval_seed("test/mixed-v1", 0)
    assert train["suite"] == "train"


def test_human_report_names_the_ruleset_first(capsys):
    code, out = _evaluate(capsys, "--planner", f"{sys.executable} {STARTER}", "--opponent", "stander", "--seeds", "1")
    assert code == 0
    first = out.out.splitlines()[0]
    assert first.startswith("ruleset combat-v1-candidate-3 ") and "public arena" in first
    assert "| **ALL** |" in out.out and "0 fell back" in out.out


# ---- arena replay verification ------------------------------------------------

def test_arena_replay_check_rejects_tampering(tmp_path):
    from qdojo.combat import export, live
    arena = live.Arena(tmp_path / "arena", [{"label": "a", "policy": "stander"}, {"label": "b", "policy": "feinter"}],
                       profile="demo-c3", seed=3, deterministic=True, log=lambda m: None)
    c = arena.w.contract
    for _ in range(400):
        arena.step()
        if any(f.phase == "DONE" and f.result.get("kind") == "COMBAT" for f in c.fights.values()):
            break
    fid = next(f.fight_id for f in c.fights.values() if f.phase == "DONE" and f.result.get("kind") == "COMBAT")
    replay = json.loads(json.dumps(export.fight_replay(c, fid)))
    report = replaycheck.verify_arena_replay(replay)
    assert report["rules"] == CANDIDATE_3 and report["outcome"] is not None
    tampered = [("salt", lambda d: d["rounds"][0]["salts"].update(A="00" * 32)),
                ("plan", lambda d: d["rounds"][0]["plans"]["A"]["actions"].__setitem__(
                    0, "BLOCK" if d["rounds"][0]["plans"]["A"]["actions"][0] != "BLOCK" else "DUCK")),
                ("beat", lambda d: d["rounds"][-1]["beats"][0]["A"]["after"].update(hp=1)),
                ("outcome", lambda d: d["outcome"].update(winner="B" if d["outcome"]["winner"] == "A" else "A")),
                ("context", lambda d: d.update(context_bytes=d["context_bytes"][:-2] + "00")),
                ("ruleset", lambda d: d.update(ruleset_digest=KNOWN["combat-v1-candidate-2"]))]
    for what, edit in tampered:
        doc = json.loads(json.dumps(replay))
        edit(doc)
        with pytest.raises(replaycheck.ReplayMismatch):
            replaycheck.verify_arena_replay(doc)
    assert codec.TAG_CONTEXT                       # the module verifies with the protocol's own tags
