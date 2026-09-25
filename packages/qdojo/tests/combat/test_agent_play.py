"""Engine-side support for agent play: plan validation before commit, no
resend loops, history in the live arena, opponent scouting in observations."""
import datetime as dt
import json

from qdojo.combat import bot as botmod
from qdojo.combat import evaluate as E
from qdojo.combat import live, llm_planner, npcs, planner, scouting
from qdojo.combat.bot import Bot, Budget, BudgetState, decide, policy_chooser
from qdojo.combat.codec import Op, decode_plan
from qdojo.combat.devnet import Devnet
from qdojo.combat.rules import candidate_1
from qdojo.combat.types import NO_POWER, Action, FighterState, Plan

RULES = candidate_1()
NOON = dt.datetime(2026, 9, 23, 12, tzinfo=dt.timezone.utc)
J, K, R = Action.JAB, Action.KICK, Action.RECOVER


def _power_every_round(rules, obs, rng):
    """The LLM bug in one line: a power slot every round, spent or not."""
    return Plan.of([K, J, R, K, J, R], 0)


def _bot(net, label, choose, tmp_path, **budget):
    fid, owner = net.ensure_fighter(label)
    b = Budget(ruleset_digest=RULES.digest.hex(), **budget)
    return Bot(net.client(owner), RULES, fid, owner, owner, choose, b, tmp_path / label, clock=lambda: NOON)


def _counting(client, counts):
    send = client.send

    def counted(op, amount=0, **fields):
        counts[Op(op).name] = counts.get(Op(op).name, 0) + 1
        return send(op, amount, **fields)
    client.send = counted


# ---- A: validation before commit -----------------------------------------

def test_legal_plan_drops_a_spent_power_slot_and_keeps_the_actions():
    spent = FighterState(80, 40, 0, 0, 0)
    fresh = FighterState(80, 40, 0, 0, 1)
    plan = Plan.of([K, J, R, K, J, R], 3)
    assert planner.legal_plan(RULES, fresh, plan) == (plan, None)
    fixed, why = planner.legal_plan(RULES, spent, plan)
    assert fixed == Plan(plan.actions, NO_POWER) and "power" in why
    bad = Plan((J,) * 5, NO_POWER)                          # the wrong shape: the fallback
    fixed, why = planner.legal_plan(RULES, fresh, bad)
    assert fixed == planner.FALLBACK and "fallback" in why


def test_a_power_reusing_policy_never_forfeits(tmp_path):
    net = Devnet(tmp_path / "net")
    logs = []
    a = _bot(net, "alpha", policy_chooser(RULES, _power_every_round, bytes(32)), tmp_path)
    a.log = logs.append
    b = _bot(net, "beta", policy_chooser(RULES, npcs.mixed_v1, bytes(32)), tmp_path)
    for _ in range(600):
        a.step(), b.step()
        net.world.end()
    c = net.world.contract
    done = [x for x in c.contests.values() if x.status == "DONE"]
    assert done and all(x.result["kind"] == "COMBAT" for x in done)
    assert any("power strike already spent" in m for m in logs)
    for fight in c.fights.values():
        slot = fight.slot_of(a.fighter_id)
        powered = [r for r in fight.rounds if decode_plan(r["plans"][slot]).power_slot != NO_POWER]
        assert len(powered) <= 1


def test_a_rejected_reveal_is_not_resent(tmp_path, monkeypatch):
    # Bypass validation to commit an illegal plan, as the old bot did.
    monkeypatch.setattr(planner, "legal_plan", lambda rules, state, plan, fallback=None: (plan, None))
    net = Devnet(tmp_path / "net")
    a = _bot(net, "alpha", policy_chooser(RULES, _power_every_round, bytes(32)), tmp_path)
    b = _bot(net, "beta", policy_chooser(RULES, npcs.mixed_v1, bytes(32)), tmp_path)
    counts = {}
    _counting(a.client, counts)
    for _ in range(200):
        a.step(), b.step()
        net.world.end()
        done = [x for x in net.world.contract.contests.values() if x.status == "DONE"]
        if done:
            break
    assert done and done[0].result["kind"] == "FORFEIT"
    rounds = len(net.world.contract.fights[done[0].fights[-1]].rounds)
    # One reveal per played round plus the single rejected one; the old bot re-sent it every tick.
    assert counts["REVEAL"] == rounds + 1
    rejected = [r for r in a.journal.records.values() if r["status"] == "reveal:rejected:BAD_PLAN"]
    assert len(rejected) == 1


def test_no_queue_entries_while_cooling_down_and_faults_age_out(tmp_path):
    net = Devnet(tmp_path / "net")
    a = _bot(net, "alpha", policy_chooser(RULES, npcs.mixed_v1, bytes(32)), tmp_path)
    b = _bot(net, "beta", policy_chooser(RULES, npcs.mixed_v1, bytes(32)), tmp_path,
             stop_after_faults=3, fault_window_ticks=500)
    for _ in range(200):                                 # beta enters once, then goes silent
        a.step()
        if not b.bstate.spends:
            b.step()
        net.world.end()
    counts = {}
    _counting(b.client, counts)
    b.step()
    assert b.bstate.faults == 1 and b.bstate.fault_ticks
    cooldown = net.world.contract.fighters[b.fighter_id].cooldown_until
    while net.world.tick < cooldown:
        assert b.step().startswith("cooling down")
        net.world.end()
    assert "QUEUE_ENTER" not in counts
    assert b.step().startswith(("entry sent", "entered offer"))    # one fault of three: still playing


def test_fault_window_counts_recent_faults_only():
    budget = Budget(ruleset_digest="ab", stop_after_faults=3, fault_window_ticks=100)
    st = BudgetState(faults=50, fault_ticks=[10, 20, 910, 950])
    assert decide(budget, st, "d", 1000, 1000, 1, 10**6, "ab") == (True, "ok")
    st.fault_ticks.append(990)
    assert "3 protocol fault(s) in the last 100 ticks" in decide(budget, st, "d", 1000, 1000, 1, 10**6, "ab")[1]
    lifetime = Budget(ruleset_digest="ab", stop_after_faults=3)
    assert decide(lifetime, st, "d", 1000, 1000, 1, 10**6, "ab")[0] is False


def test_the_live_demo_budget_has_a_real_fault_stop():
    b = live._budget(RULES, {"label": "x"}, epoch_ticks=2400)
    assert (b.stop_after_faults, b.fault_window_ticks) == (live.DEMO_STOP_AFTER_FAULTS, 2400)
    b = live._budget(RULES, {"label": "x", "stop_after_faults": 5, "min_ticks_between_fights": 900})
    assert b.stop_after_faults == 5 and b.min_ticks_between_fights == 900


def _obs(power: bool, prior=(), history=None) -> dict:
    side = {"fighter_id": "00" * 32, "hp": 70, "stamina": 40, "opening": 0, "guard_streak": 0,
            "power_available": power}
    return {"round_index": 2, "self_slot": "A", "fight_id": "7", "self": side, "opponent": dict(side),
            "prior_rounds": list(prior), "opponent_history": history or scouting.empty(None)}


def test_llm_prompt_says_power_is_gone_and_the_planner_drops_it():
    text = llm_planner._user_prompt(_obs(False))
    assert "power_available: false — you have ALREADY USED your power strike; power_slot must be -1" in text
    plan, read = llm_planner._model_plan('{"read": "they kick", "actions": ["KICK","JAB","RECOVER",'
                                         '"KICK","JAB","RECOVER"], "power_slot": 0}')
    assert read == "they kick"
    assert llm_planner.legal(_obs(False), plan)["power_slot"] == -1
    assert llm_planner.legal(_obs(True), plan)["power_slot"] == 0


def test_claude_requests_cache_the_system_prompt_and_skip_temperature():
    prompt = llm_planner.PROMPTS / "planner-system-claude.md"
    body = llm_planner.request_body("anthropic/claude-sonnet-5", _obs(True), prompt, "off")
    assert body["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert "temperature" not in body and body["reasoning"] == {"enabled": False}
    assert "reasoning" not in llm_planner.request_body("anthropic/claude-sonnet-5", _obs(True), prompt, "none")
    other = llm_planner.request_body("qwen/qwen3-235b-a22b-2507", _obs(True))
    assert other["temperature"] == 0.7 and isinstance(other["messages"][0]["content"], str)


# ---- B: history in the live arena ----------------------------------------

def test_history_policies_receive_prior_rounds_in_the_live_arena(tmp_path):
    seen = []
    reader = E.policy_by_name("reader-v1")

    def recording(rules, obs, rng):
        plan = reader(rules, obs, rng)
        if obs.round_index > 0:
            blind = npcs.Observation(obs.round_index, obs.self_state, obs.opponent_state, (), obs.slot, ())
            again = npcs.Stream(bytes(32), 0, obs.round_index)
            seen.append((obs.round_index, len(obs.prior), len(obs.opponent_history),
                         plan != reader(rules, blind, again)))
        return plan

    lineup = [{"label": "reader", "policy": "reader-v1"}, {"label": "kicker", "policy": "kicker-v1"}]
    arena = live.Arena(tmp_path / "arena", lineup, seed=5, deterministic=True, log=lambda m: None)
    fid = next(f for f, e in arena.labels.items() if e["label"] == "reader")
    arena.bots[fid].choose = policy_chooser(RULES, recording, bytes(32))
    for _ in range(700):
        arena.step()
    assert seen, "reader should have reached round 2 at least once"
    assert all(n_prior == r and n_hist == r for r, n_prior, n_hist, _ in seen)
    assert any(changed for *_, changed in seen)        # it plays differently with history than without


def test_repeat_last_winner_repeats_a_plan_live(tmp_path):
    lineup = [{"label": "rlw", "policy": "repeat-last-winner"}, {"label": "mixed", "policy": "mixed-v1"}]
    arena = live.Arena(tmp_path / "arena", lineup, seed=9, deterministic=True, log=lambda m: None)
    for _ in range(700):
        arena.step()
    c = arena.w.contract
    fid = next(f for f, e in arena.labels.items() if e["label"] == "rlw")
    repeats = later = 0
    for fight in c.fights.values():
        slot = fight.slot_of(fid)
        plans = [decode_plan(r["plans"]["A"]).actions for r in fight.rounds] if slot else []
        plans_b = [decode_plan(r["plans"]["B"]).actions for r in fight.rounds] if slot else []
        mine = plans if slot == "A" else plans_b
        for i in range(1, len(mine)):
            later += 1
            repeats += mine[i] in (plans[i - 1], plans_b[i - 1])
    assert later and repeats == later


def test_prior_results_rebuild_the_engine_rounds():
    from qdojo.combat.training import Contestant, run_fight
    replay = run_fight(Contestant("x", policy=npcs.mixed_v1), Contestant("y", policy=npcs.scout_v1), bytes(32))
    prior = botmod.prior_results(RULES, replay["rounds"])
    assert len(prior) == len(replay["rounds"])
    assert [r.to_json()["beats"] for r in prior] == [r["beats"] for r in replay["rounds"]]


# ---- C: opponent scouting --------------------------------------------------

def _observations(arena, label):
    fid = next(f for f, e in arena.labels.items() if e["label"] == label)
    b = arena.bots[fid]
    me = b.client.fighter(fid)
    if not me or not me.get("active_fight"):
        return None
    fight = b.client.fight(me["active_fight"])
    slot = fight["slot_of"][fid.hex()]
    return fight["observation"](slot), fight["observation"](slot), fight


def test_observations_carry_bounded_public_opponent_history(tmp_path):
    lineup = [{"label": "a", "policy": "scout-v1"}, {"label": "b", "policy": "kicker-v1"},
              {"label": "c", "policy": "mixed-v1"}]
    arena = live.Arena(tmp_path / "arena", lineup, seed=3, deterministic=True, log=lambda m: None)
    checked = 0
    for _ in range(3000):
        arena.step()
        if arena.w.tick % 50 or arena.w.tick < 1200:
            continue
        got = _observations(arena, "a")
        if not got:
            continue
        obs, again, fight = got
        assert obs == again                                   # deterministic within a round
        hist = obs["opponent_history"]
        assert hist["fighter_id"] == obs["opponent"]["fighter_id"]
        assert obs["history_manifest"]["opponent_fight_ids"] == [f["fight_id"] for f in hist["fights"]]
        assert len(hist["fights"]) <= scouting.MAX_FIGHTS
        assert sum(len(f["rounds"]) for f in hist["fights"]) <= scouting.MAX_PLANS
        assert len(json.dumps(obs)) < planner.OBSERVATION_CAP
        c = arena.w.contract
        start = c.fights[fight["fight_id"]].start_tick
        for f in hist["fights"]:
            past = c.fights[int(f["fight_id"])]
            assert past.fight_id != fight["fight_id"] and past.phase == "DONE" and past.result["tick"] < start
            for r, rec in zip(f["rounds"], past.rounds):             # exactly the revealed plans
                assert r["plan"] == decode_plan(rec["plans"][f["slot"]]).to_json()
        ids = [int(x) for x in obs["history_manifest"]["opponent_fight_ids"]]
        assert ids == sorted(ids, reverse=True)
        if hist["fights"]:
            checked += 1
            prompt = llm_planner._user_prompt(obs)
            assert "Scouting: opponent's last" in prompt and "Round 1 plans:" in prompt
        if checked >= 3:
            break
    assert checked >= 3


def test_scouting_is_capped(tmp_path, monkeypatch):
    lineup = [{"label": "a", "policy": "kicker-v1"}, {"label": "b", "policy": "jabber-v1"}]
    arena = live.Arena(tmp_path / "arena", lineup, seed=4, deterministic=True, log=lambda m: None)
    for _ in range(2500):
        arena.step()
    c = arena.w.contract
    fid = next(f for f, e in arena.labels.items() if e["label"] == "a")
    done = [f for f in c.fights.values() if f.phase == "DONE" and f.slot_of(fid)]
    assert len(done) >= 5
    full = scouting.Scout().history(c, fid, -1, arena.w.tick + 1)
    assert [int(f["fight_id"]) for f in full["fights"]] == sorted((f.fight_id for f in done), reverse=True)
    monkeypatch.setattr(scouting, "MAX_FIGHTS", 3)
    hist = scouting.Scout().history(c, fid, -1, arena.w.tick + 1)
    assert len(hist["fights"]) == 3 and hist["summary"]["fights"] == 3
    assert sum(hist["summary"]["plan_actions_by_round"]["0"].values()) == 6 * 3
    monkeypatch.setattr(scouting, "MAX_FIGHTS", 10)
    monkeypatch.setattr(scouting, "MAX_PLANS", 4)
    hist = scouting.Scout().history(c, fid, -1, arena.w.tick + 1)
    assert 0 < sum(len(f["rounds"]) for f in hist["fights"]) <= 4
    monkeypatch.setattr(scouting, "MAX_PLANS", 60)
    monkeypatch.setattr(scouting, "MAX_BYTES", 2500)
    hist = scouting.Scout().history(c, fid, -1, arena.w.tick + 1)
    assert len(json.dumps(hist, separators=(",", ":"))) <= 2500 and hist["fights"] == full["fights"][:len(hist["fights"])]


def test_practice_with_a_power_reusing_planner_adjusts_instead_of_crashing(tmp_path):
    import sys
    from qdojo.combat.training import Contestant, run_fight
    bot = tmp_path / "bot.py"
    bot.write_text("import json,sys\njson.load(sys.stdin)\nprint(json.dumps({'schema':'qdojo.combat.plan.v1',"
                   "'actions':['KICK','JAB','RECOVER','JAB','KICK','RECOVER'],'power_slot':0}))\n")
    you = Contestant("you", command=[sys.executable, str(bot)], budget_ms=5000)
    replay = run_fight(you, Contestant("kicker-v1", policy=npcs.ROSTER["kicker-v1"].policy), bytes(32))
    assert len(replay["rounds"]) >= 2
    assert any("power" in d.get("adjusted", "") for d in you.diagnostics)


def test_llm_prompt_projects_where_a_repeating_opponent_runs_dry():
    obs = _obs(True)
    obs["opponent"]["stamina"] = 30
    obs["prior_rounds"] = [{"plans": {"A": {"actions": ["JAB"] * 6, "power_slot": -1},
                                      "B": {"actions": ["KICK"] * 6, "power_slot": -1}}}]
    line = llm_planner._projection_line(obs)
    assert "KICK KICK KICK KICK KICK KICK" in line and "EXHAUSTED" in line
    obs["prior_rounds"] = []
    assert llm_planner._projection_line(obs) is None        # nothing to project from
