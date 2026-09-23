import json
import sys
from pathlib import Path

import pytest

from qdojo.cli import build_parser, main
from qdojo.combat import evaluate as E
from qdojo.combat import npcs, planner
from qdojo.combat.rules import candidate_1
from qdojo.combat.training import Contestant, ReplayMismatch, explain, run_fight, summary, verify_replay
from qdojo.combat.types import Action, FighterState, Plan

from .conftest import ROOT

SEED = bytes(range(32))
EXAMPLE = ROOT / "examples/combat/planner_minimal.py"


def _obs(rules, round_index=0, **kw):
    s = FighterState.initial(rules)
    return npcs.Observation(round_index, kw.get("me", s), kw.get("opp", s), kw.get("history", ()))


def test_stream_matches_reference(reference):
    for n in (1, 2, 5, 6, 7, 12, 200, 256):
        ours = npcs.Stream(SEED, 9, 2)
        theirs = reference.Stream(SEED, 9, 2)
        assert [ours.uniform(n) for _ in range(300)] == [theirs.uniform(n) for _ in range(300)]


@pytest.mark.parametrize("name", ["random", "jabber", "turtle", "kicker"])
def test_simple_npcs_match_reference(rules, reference, name):
    for fight in range(40):
        for r in range(3):
            for power in (0, 1):
                s = FighterState(100, 60, 0, 0, power)
                ours = npcs.plan_for(f"{name}-v1", rules, npcs.Observation(r, s, s), SEED, fight)
                ref_state = reference.State(power_available=power)
                actions, slot = reference.policy(name, ref_state, r, SEED, fight)
                assert ([int(a) for a in ours.actions], ours.power_slot) == (actions, slot)


def test_every_roster_npc_plays_legal_plans(rules):
    for npc_id in npcs.ROSTER:
        for fight in range(20):
            a = Contestant("me", npc=npc_id)
            b = Contestant("them", npc="random-v1")
            replay = run_fight(a, b, SEED, fight + 1)
            assert verify_replay(replay) == replay["outcome"]


def test_mixed_uses_low_stamina_weights(rules):
    rng = npcs.Stream(SEED, 1, 0)
    plan = npcs.mixed_v1(rules, _obs(rules, me=FighterState(100, 3, 0, 0, 1)), rng)
    assert Action.KICK not in plan.actions[:1] and Action.THROW not in plan.actions[:1]


def test_scout_answers_a_jabber(rules):
    history = ((Action.JAB,) * 6, (Action.JAB,) * 6)
    wins = 0
    for fight in range(30):
        plan = npcs.scout_v1(rules, _obs(rules, 2, history=history), npcs.Stream(SEED, fight, 2))
        wins += sum(a in (Action.DUCK, Action.KICK) for a in plan.actions)
    assert wins > 30 * 6 * 0.5


def test_npc_power_only_in_round_two(rules):
    for npc_id in ("jabber-v1", "kicker-v1", "mixed-v1"):
        for r in (0, 1):
            assert npcs.plan_for(npc_id, rules, _obs(rules, r), SEED, 1).power_slot == -1
    assert npcs.plan_for("jabber-v1", rules, _obs(rules, 2), SEED, 1).power_slot == 0


def test_same_seed_same_fight():
    a = run_fight(Contestant("x", npc="scout-v1"), Contestant("y", npc="mixed-v1"), SEED)
    b = run_fight(Contestant("x", npc="scout-v1"), Contestant("y", npc="mixed-v1"), SEED)
    assert a == b
    c = run_fight(Contestant("x", npc="scout-v1"), Contestant("y", npc="mixed-v1"), bytes(32))
    assert c["rounds"] != a["rounds"]


def test_tampered_replay_is_caught():
    replay = run_fight(Contestant("x", npc="random-v1"), Contestant("y", npc="kicker-v1"), SEED)
    verify_replay(replay)
    for tamper in (
        lambda r: r["rounds"][0]["beats"][0]["A"]["after"].update(hp=1),
        lambda r: r["outcome"].update(winner="A" if r["outcome"]["winner"] != "A" else "B"),
        lambda r: r["rounds"][0]["plans"]["A"]["actions"].__setitem__(0, "THROW"
                  if r["rounds"][0]["plans"]["A"]["actions"][0] != "THROW" else "JAB"),
        lambda r: r["rounds"].pop(),
        lambda r: r.update(ruleset_digest="00" * 32),
    ):
        bad = json.loads(json.dumps(replay))
        tamper(bad)
        with pytest.raises((ReplayMismatch, ValueError)):
            verify_replay(bad)


def _script(tmp_path, body):
    p = tmp_path / "bot.py"
    p.write_text(body)
    return [sys.executable, str(p)]


@pytest.mark.parametrize("stdout,code", [
    ('{"schema":"qdojo.combat.plan.v1","actions":["JAB","JAB","JAB","JAB","JAB","JAB"],"power_slot":-1,"x":1}', "BAD_PLAN"),
    ('{"schema":"qdojo.combat.plan.v1","actions":["jab","JAB","JAB","JAB","JAB","JAB"],"power_slot":-1}', "BAD_PLAN"),
    ('{"schema":"qdojo.combat.plan.v1","actions":["JAB","JAB","JAB","JAB","JAB","JAB"],"power_slot":1.0}', "BAD_PLAN"),
    ('{"schema":"qdojo.combat.plan.v1","actions":["JAB","JAB","JAB","JAB","JAB","JAB"],"power_slot":true}', "BAD_PLAN"),
    ('{"schema":"qdojo.combat.plan.v1","actions":["JAB","JAB","JAB","JAB","JAB"],"power_slot":-1}', "BAD_PLAN"),
    ('{"schema":"qdojo.combat.plan.v1","actions":["JAB","JAB","JAB","JAB","JAB","JAB"],"power_slot":-1}{}', "BAD_PLAN"),
    ('{"schema":"qdojo.combat.plan.v1","actions":["BLOCK","JAB","JAB","JAB","JAB","JAB"],"power_slot":0}', "BAD_PLAN"),
    ("x" * 5000, "TOO_LONG"),
])
def test_planner_output_is_strict(tmp_path, stdout, code):
    cmd = _script(tmp_path, f"import sys; sys.stdin.read(); sys.stdout.write({stdout!r})")
    with pytest.raises(planner.PlannerError) as exc:
        planner.run(cmd, {"schema": planner.OBSERVATION_SCHEMA}, 5000)
    assert exc.value.code == code


def test_planner_timeout_exit_and_fallback(tmp_path):
    slow = _script(tmp_path, "import time; time.sleep(5)")
    with pytest.raises(planner.PlannerError) as exc:
        planner.run(slow, {}, 300)
    assert exc.value.code == "TIMEOUT"
    crash = _script(tmp_path, "import sys; print('seed ' + 'a'*55, file=sys.stderr); sys.exit(3)")
    ran, err = planner.run_or_fallback(crash, {}, 5000)
    assert err.code == "EXIT" and ran.plan == planner.FALLBACK
    assert "a" * 55 not in ran.stderr and "[redacted]" in ran.stderr


def test_planner_gets_public_observation_and_fights(tmp_path):
    cmd = [sys.executable, str(EXAMPLE)]
    replay = run_fight(Contestant("you", command=cmd), Contestant("npc", npc="jabber-v1"), SEED)
    assert not replay["fallbacks"]
    verify_replay(replay)
    you = "A" if replay["fighters"]["A"]["name"] == "you" else "B"
    s = summary(replay, you)
    assert s["executed_beats"] > 0 and isinstance(explain(replay, you), list)


def test_observation_carries_prior_rounds_and_no_secrets(tmp_path):
    dump = tmp_path / "obs.jsonl"
    body = ("import json,sys\nobs=json.load(sys.stdin)\n"
            f"open({str(dump)!r},'a').write(json.dumps(obs)+'\\n')\n"
            "print(json.dumps({'schema':'qdojo.combat.plan.v1','actions':['RECOVER']*6,'power_slot':-1}))\n")
    run_fight(Contestant("you", command=_script(tmp_path, body)), Contestant("npc", npc="turtle-v1"), SEED)
    seen = [json.loads(line) for line in dump.read_text().splitlines()]
    assert [o["round_index"] for o in seen] == [0, 1, 2]
    assert [len(o["prior_rounds"]) for o in seen] == [0, 1, 2]
    text = dump.read_text()
    assert SEED.hex() not in text and "salt" not in text


def test_cli_train_and_replay(tmp_path, capsys):
    out = tmp_path / "r.json"
    main(["combat", "train", "--npc", "kicker-v1", "--seed", "11" * 32, "--out", str(out), "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["replay"] == str(out)
    main(["combat", "replay", str(out), "--json"])
    assert json.loads(capsys.readouterr().out)["verified"] is True
    main(["combat", "npcs", "--json"])
    assert {r["id"] for r in json.loads(capsys.readouterr().out)} == set(npcs.ROSTER)


def test_cli_rejects_bad_seed():
    with pytest.raises(SystemExit):
        main(["combat", "train", "--seed", "abc"])


def test_evaluate_small_batch_is_paired_and_reproducible():
    x, y = npcs.ROSTER["scout-v1"].policy, npcs.ROSTER["jabber-v1"].policy
    t1 = E.paired(x, y, 5, "unit")
    t2 = E.paired(x, y, 5, "unit")
    assert t1.scores == t2.scores and t1.fights == 10
    row = E.summarize("jabber-v1", t1)
    assert 0 <= row["lower95"] <= row["score"] <= 1


def test_evaluate_cli(capsys):
    main(["combat", "evaluate", "--policy", "mixed-v1", "--opponent", "turtle-v1", "--seeds", "3", "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["rows"][0]["fights"] == 6


def test_best_response_search_is_bounded(rules):
    plan, value = E.best_response_opening(rules, npcs.ROSTER["jabber-v1"].policy, samples=1, limit=500)
    assert isinstance(plan, Plan)


def test_parser_knows_the_combat_commands():
    for argv in (["combat", "train"], ["combat", "replay", "f.json"], ["combat", "evaluate"], ["combat", "npcs"]):
        build_parser().parse_args(argv)
