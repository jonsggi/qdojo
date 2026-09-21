"""The diary bot run keeps for its owner: a heartbeat, a metrics line per
round, a log. These tests hold the writer to "append only when something
changed", the reader to "last line per round wins", and the summary to the
numbers a fighter actually wants to know."""
import json
import os
import sys
import time

import pytest

from qdojo import cockpit, cli, portable
from qdojo.bot import Bot
from qdojo.chain import FakeChain
from qdojo.cli import main
from conftest import HOUSE, ALICE, BOB
from test_house_and_bot import World, make_house, riddle_file, publish_and_open, SUM_SOLVER, WRONG_SOLVER


def rows_on_disk(state):
    return [json.loads(l) for l in open(os.path.join(state, cockpit.METRICS)) if l.strip()]


# ------------------------------------------------------------------- recorder

def test_kind_strips_the_belt_and_the_instance_numbers():
    assert cockpit.kind_of("White belt: sum the numbers") == "sum the numbers"
    assert cockpit.kind_of("Blue belt: fix count_evens") == "fix count_evens"
    assert cockpit.kind_of("Green belt: SHA-256 of a string") == "sha-256 of a string"
    assert cockpit.kind_of(None) == ""


def test_a_line_is_appended_only_when_something_changed(tmp_path):
    rec = cockpit.Recorder(str(tmp_path))
    assert rec.note(7, belt="white", title="White belt: sum the numbers", skipped=True, why="below my belt")
    assert rec.note(7, belt="white", skipped=True, why="below my belt") is None      # same facts, no line
    assert rec.note(7, why=None) is None                                             # None never erases
    assert rec.note(7, entered=True, answer="142")
    lines = rows_on_disk(str(tmp_path))
    assert len(lines) == 2 and lines[-1]["answer"] == "142" and lines[-1]["kind"] == "sum the numbers"
    assert lines[-1]["why"] == "below my belt"                                       # carried forward
    assert oct(os.stat(os.path.join(str(tmp_path), cockpit.METRICS)).st_mode & 0o777) == "0o600"


def test_the_reader_takes_the_last_line_per_round_and_survives_a_torn_one(tmp_path):
    p = tmp_path / cockpit.METRICS
    p.write_text('{"round_id": 1, "entered": true}\n{"round_id": 2, "skipped": true}\n'
                 '{"round_id": 1, "entered": true, "verdict": "winner"}\n{"round_id": 3, "ent')
    rows = cockpit.load_rows(str(p))
    assert rows[1]["verdict"] == "winner" and rows[2]["skipped"] and 3 not in rows
    rec = cockpit.Recorder(str(tmp_path))                     # a restart picks the merged rows back up
    assert rec.pending() == [] and rec.rows[1]["verdict"] == "winner"


def test_settlement_is_filled_in_from_history(tmp_path):
    rec = cockpit.Recorder(str(tmp_path))
    rec.note(5, entered=True, stake=1000, answer="142")
    rec.note(6, entered=True, stake=1000, answer="7")
    rec.note(9, entered=True, stake=1000)                    # the house never saw a commit
    assert rec.pending() == [5, 6, 9]
    history = {"rounds": [
        {"round_id": 5, "state": "settled", "belt": "white", "riddle": {"title": "White belt: sum the numbers"},
         "publish_tick": 100,
         "entries": [{"identity": ALICE, "verdict": "winner", "stake": 1000}],
         "settlement": {"answer": "142", "settle_tick": 400,
                        "payouts": [{"identity": ALICE, "amount": 5000, "kind": "win"},
                                    {"identity": ALICE, "amount": 300, "kind": "bond_release"},
                                    {"identity": BOB, "amount": 9, "kind": "win"}],
                        "bonds_held": [{"identity": ALICE, "amount": 2500}]}},
        {"round_id": 6, "state": "settled", "belt": "white", "riddle": {"title": "t"},
         "entries": [{"identity": ALICE, "verdict": "wrong", "stake": 1000}],
         "settlement": {"answer": "8", "payouts": [], "bonds_held": []}},
        {"round_id": 9, "state": "settled", "entries": [], "settlement": {"payouts": []}},
        {"round_id": 10, "state": "commit", "entries": []},
    ]}
    done = rec.settle_from_history(history, ALICE)
    assert [r["round_id"] for r in done] == [5, 6, 9]
    r5 = rec.rows[5]
    assert r5["verdict"] == "winner" and r5["earned"] == 5300 and r5["bond_held"] == 2500
    assert r5["net"] == 5300 + 2500 - 1000 and r5["truth"] == "142" and r5["settle_tick"] == 400
    assert r5["kind"] == "sum the numbers" and r5["belt"] == "white"
    assert rec.rows[6]["verdict"] == "wrong" and rec.rows[6]["net"] == -1000 and rec.rows[6]["truth"] == "8"
    assert rec.rows[9]["verdict"] == "absent"
    assert rec.pending() == []
    assert rec.settle_from_history(history, ALICE) == []          # nothing left to do, nothing written


# -------------------------------------------------------------------- summary

def rows_fixture(tmp_path):
    rec = cockpit.Recorder(str(tmp_path))
    rec.note(1, belt="white", title="White belt: sum the numbers", entered=True, stake=1000, answer="1",
             solver_seconds=2.0, verdict="winner", earned=3000, net=2000)
    rec.note(2, belt="white", title="White belt: sum the numbers", entered=True, stake=1000, answer="2",
             solver_seconds=4.0, verdict="solved", earned=0, net=-1000)
    rec.note(3, belt="yellow", title="Yellow belt: reverse the string", entered=True, stake=1000, answer="x",
             solver_seconds=6.0, verdict="wrong", earned=0, net=-1000)
    rec.note(4, belt="yellow", title="Yellow belt: reverse the string", skipped=True, why="below my belt")
    rec.note(5, belt="white", title="White belt: sum the numbers", entered=True, stake=1000, answer="5",
             solver_seconds=1.0, verdict="winner", earned=4000, net=3000)
    rec.note(6, belt="white", title="White belt: sum the numbers", entered=True, stake=1000, answer="6",
             solver_seconds=3.0)                                        # still open
    rec.note(7, belt="green", title="Green belt: SHA-256 of a string", solver_failures=1, solver_exit=1,
             solver_stderr="boom", why="solver failed: boom")
    return rec


def test_summary_counts_what_a_fighter_wants_to_know(tmp_path):
    rows_fixture(tmp_path)
    m = cockpit.summary(str(tmp_path), last=3)
    assert (m["rounds_seen"], m["entered"], m["skipped"], m["settled"], m["pending"]) == (7, 5, 1, 4, 1)
    assert m["solved"] == 3 and m["wins"] == 2 and m["solve_rate"] == 0.75 and m["win_rate"] == 0.5
    assert m["avg_solve_seconds"] == 3.2 and m["best_solve_seconds"] == 1.0
    assert m["staked"] == 4000 and m["earned"] == 7000 and m["net"] == 3000
    assert m["streak"] == 1 and m["best_streak"] == 2          # W W L W: current +1, best 2
    assert m["solver_failed"] == 1
    assert m["by_kind"]["sum the numbers"] == {"seen": 4, "entered": 4, "settled": 3, "solved": 3, "wins": 2,
                                                "net": 4000, "solve_rate": 1.0}
    assert m["by_kind"]["reverse the string"]["solve_rate"] == 0.0
    assert m["by_belt"]["white"]["solved"] == 3
    assert m["net_series"] == [[1, 2000], [2, 1000], [3, 0], [5, 3000]]
    assert [r["round_id"] for r in m["last"]] == [7, 6, 5]


def test_summary_of_nothing_is_zeros_not_a_crash(tmp_path):
    m = cockpit.summary(str(tmp_path))
    assert m["rounds_seen"] == 0 and m["solve_rate"] is None and m["net"] == 0 and m["last"] == []


def test_a_losing_streak_is_negative(tmp_path):
    rec = cockpit.Recorder(str(tmp_path))
    rec.note(1, entered=True, verdict="winner", stake=1, earned=2, net=1)
    rec.note(2, entered=True, verdict="wrong", stake=1, earned=0, net=-1)
    rec.note(3, entered=True, verdict="no_reveal", stake=1, earned=0, net=-1)
    assert cockpit.summary(str(tmp_path))["streak"] == -2


# ------------------------------------------------------------------ heartbeat

def test_heartbeat_says_running_then_stale_then_idle(tmp_path, monkeypatch):
    state = str(tmp_path)
    assert cockpit.status(state)["state"] == "idle"
    hb = cockpit.Heartbeat(state, 5.0, board="http://x/board.json", solver=["python3", "/x/evo.py"])
    board = {"generated_tick": 500, "rounds": [{"round_id": 3, "belt": "white", "state": "commit",
                                                "riddle": {"title": "White belt: sum the numbers"},
                                                "publish_tick": 480, "commit_window": 50, "entry_fee": 1000}]}
    hb.beat(board=board, actions=["round 3: committed 1234abcd… for tick 510"])
    doc = json.load(open(os.path.join(state, cockpit.HEARTBEAT)))
    assert doc["pid"] == os.getpid() and doc["solver"] == ["python3", "evo.py"] and doc["tick"] == 500
    json.dump({"3": {"answer": "142", "commit_tick": 510, "commit_tx": "t"}}, open(os.path.join(state, "rounds.json"), "w"))
    st = cockpit.status(state)
    assert st["state"] == "running" and st["pid"] == os.getpid() and st["age"] < 5
    assert st["rounds"][0]["kind"] == "sum the numbers" and st["rounds"][0]["did"] == "committed for tick 510, answer '142'"
    assert st["last_actions"][-1]["text"].startswith("round 3: committed")
    st = cockpit.status(state, now=time.time() + 100)
    assert st["state"] == "stale"
    hb.close()
    assert cockpit.status(state)["state"] == "idle"
    assert not os.path.exists(os.path.join(state, cockpit.HEARTBEAT))


def test_status_never_signals_the_pid():
    """os.kill(pid, 0) is the usual liveness probe on POSIX; on Windows it
    terminates the process. The heartbeat's age is the only evidence used."""
    import ast
    tree = ast.parse(open(cockpit.__file__, encoding="utf-8").read())
    calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert not [c for c in calls if "kill" in c or "signal" in c], calls
    assert "signal" not in {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}


def test_what_the_bot_did_reads_from_rounds_json_first():
    assert cockpit._did(None, None) == "nothing yet"
    assert cockpit._did(None, {"why": "below my belt"}) == "below my belt"
    assert cockpit._did({"skipped": True}, {"why": "strategy says skip"}) == "sat out: strategy says skip"
    assert cockpit._did({"entered": True}, None) == "seated in the lobby, waiting for the riddle"
    assert cockpit._did({"solver_failures": 2}, {"why": "solver failed: boom"}) == "solver failed 2x: solver failed: boom"
    assert cockpit._did({"reveal_tick": 9, "commit_tick": 5}, None) == "revealed for tick 9"
    assert cockpit._did({"dead": True, "commit_tick": 5}, None) == "commit never landed, sitting out"


def test_idle_status_still_names_the_newest_round_on_this_machine(tmp_path):
    state = str(tmp_path)
    json.dump({"41": {"skipped": True}, "42": {"answer": "1", "commit_tick": 7}}, open(os.path.join(state, "rounds.json"), "w"))
    cockpit.Recorder(state).note(42, belt="white", title="White belt: the sum")
    st = cockpit.status(state)
    assert st["state"] == "idle" and st["rounds"][0]["round_id"] == 42 and st["rounds"][0]["did"] == "committed for tick 7, answer '1'"


# ------------------------------------------------------------------------ log

def test_log_rotates_and_tails(tmp_path, monkeypatch):
    monkeypatch.setattr(cockpit, "LOG_BYTES", 2000)
    state = str(tmp_path / "s")
    log = cockpit.open_log(state)
    assert cockpit.open_log(state) is log and len(log.handlers) == 1     # idempotent, never doubled
    log.handlers[0].maxBytes = 2000
    for i in range(200):
        log.info(f"line {i} " + "x" * 40)
    names = sorted(os.listdir(state))
    assert cockpit.LOG in names and f"{cockpit.LOG}.1" in names
    assert os.path.getsize(os.path.join(state, cockpit.LOG)) <= 2100
    tail = cockpit.log_tail(state, 3)
    assert len(tail) == 3 and tail[-1].endswith("line 199 " + "x" * 40)
    assert cockpit.log_tail(str(tmp_path / "nowhere")) == []
    if portable.private_modes_enforced():
        assert oct(os.stat(os.path.join(state, cockpit.LOG)).st_mode & 0o777) == "0o600"
        assert oct(os.stat(os.path.join(state, f"{cockpit.LOG}.1")).st_mode & 0o777) == "0o600"


def test_log_is_private_even_when_umask_would_leave_it_open(tmp_path):
    """bot.log is one of the diary files: 0600 like metrics.jsonl and
    heartbeat.json, whatever the process umask says."""
    if not portable.private_modes_enforced():
        pytest.skip("file modes are not enforced on this platform")
    state = str(tmp_path / "s")
    old_umask = os.umask(0o022)
    try:
        log = cockpit.open_log(state)
        log.info("hello")
    finally:
        os.umask(old_umask)
    assert oct(os.stat(os.path.join(state, cockpit.LOG)).st_mode & 0o777) == "0o600"


# ------------------------------------------------------- the bot, end to end

def test_a_bot_on_the_fake_chain_writes_the_diary_and_history_settles_it(tmp_path):
    world = World()
    h = make_house(world, tmp_path)
    publish_and_open(h, world, riddle_file(tmp_path))
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))

    a_state, b_state = str(tmp_path / "bot-a"), str(tmp_path / "bot-b")
    alice = Bot(world.view(ALICE), a_state, SUM_SOLVER, recorder=cockpit.Recorder(a_state))
    bob = Bot(world.view(BOB), b_state, WRONG_SOLVER, max_stake=10, recorder=cockpit.Recorder(b_state))
    alice.step(board); bob.step(board)
    ra = cockpit.load_rows(os.path.join(a_state, cockpit.METRICS))[1]
    assert ra["entered"] and ra["answer"] == "142" and ra["stake"] == 1000 and ra["solver_exit"] == 0
    assert ra["solver_seconds"] >= 0 and ra["commit_tick"] == world.core.tick + world.core.schedule_offset
    assert ra["title"] == "sum" and ra["publish_tick"] == 1005 and ra["why"] == "committed"
    rb = cockpit.load_rows(os.path.join(b_state, cockpit.METRICS))[1]
    assert rb["skipped"] and not rb["entered"] and rb["why"] == "entry fee 1000 above max stake"
    n_lines = len(rows_on_disk(a_state))
    alice.step(board)                                             # nothing new: nothing written
    assert len(rows_on_disk(a_state)) == n_lines

    world.core.advance(1005 + 51 - world.core.tick)
    alice.step(board)
    ra = cockpit.load_rows(os.path.join(a_state, cockpit.METRICS))[1]
    assert ra["reveal_tick"] == world.core.tick + world.core.schedule_offset and ra.get("verdict") is None
    world.core.advance(1005 + 71 - world.core.tick + 25); h.collect()
    orig = h.chain.confirm
    def confirm_advancing(tx, tick):
        if world.core.tick < tick:
            world.core.advance(tick - world.core.tick)
        return orig(tx, tick)
    h.chain.confirm = confirm_advancing
    h.settle(1, apply=True)
    hist = h.export(str(tmp_path / "web"))
    done = alice.recorder.settle_from_history(hist, ALICE)
    assert [r["round_id"] for r in done] == [1]
    ra = alice.recorder.rows[1]
    assert ra["verdict"] == "winner" and ra["earned"] == 10_000 + 1000 - 50 and ra["net"] == ra["earned"] - 1000
    m = cockpit.summary(a_state)
    assert m["solved"] == 1 and m["solve_rate"] == 1.0 and m["net"] == ra["net"] and m["by_kind"]["sum"]["wins"] == 1


def test_a_solver_failure_is_filed_with_its_exit_code_and_stderr(tmp_path):
    world = World()
    h = make_house(world, tmp_path)
    publish_and_open(h, world, riddle_file(tmp_path))
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    state = str(tmp_path / "bot-c")
    bad = [sys.executable, "-c", "import sys; print('no model', file=sys.stderr); sys.exit(2)"]
    bot = Bot(world.view(ALICE), state, bad, recorder=cockpit.Recorder(state))
    acts = bot.step(board)
    assert any("solver failed (1/2)" in a for a in acts)
    r = cockpit.load_rows(os.path.join(state, cockpit.METRICS))[1]
    assert r["solver_failures"] == 1 and r["solver_exit"] == 2 and "no model" in r["solver_stderr"]
    assert not r["entered"] and r["why"].startswith("solver failed")
    assert cockpit.status(state)["rounds"][0]["did"].startswith("solver failed 1x")


def test_a_bot_without_a_recorder_is_unchanged(tmp_path):
    world = World()
    h = make_house(world, tmp_path)
    publish_and_open(h, world, riddle_file(tmp_path))
    h.collect(); h.export(str(tmp_path / "web"))
    board = json.load(open(tmp_path / "web" / "board.json"))
    state = str(tmp_path / "bot-d")
    acts = Bot(world.view(ALICE), state, SUM_SOLVER).step(board)
    assert any("committed" in a for a in acts)
    assert not os.path.exists(os.path.join(state, cockpit.METRICS))


# ------------------------------------------------------------------------ CLI

def test_status_metrics_and_log_commands_need_no_seed_and_no_node(tmp_path, capsys):
    state = str(tmp_path / "bot")
    os.makedirs(state)
    main(["bot", "--state", state, "status", "--json"])
    assert json.loads(capsys.readouterr().out)["state"] == "idle"
    main(["bot", "--state", state, "status", "--no-color"])
    assert "IDLE" in capsys.readouterr().out
    main(["bot", "--state", state, "metrics"])
    assert "no rounds recorded" in capsys.readouterr().out
    main(["bot", "--state", state, "log"])
    assert "no log" in capsys.readouterr().out

    rows_fixture(tmp_path / "bot")
    cockpit.open_log(state).info("round 1: committed")
    cockpit.Heartbeat(state, 5.0, board="http://x/board.json", solver=["evo.py"]).beat(
        board={"generated_tick": 9, "rounds": [{"round_id": 6, "belt": "white", "state": "commit",
                                                "riddle": {"title": "White belt: sum the numbers"}}]},
        actions=["round 6: committed abcdefgh… for tick 30"])
    json.dump({"6": {"answer": "6", "commit_tick": 30}}, open(os.path.join(state, "rounds.json"), "w"))
    main(["bot", "--state", state, "status", "--no-color"])
    out = capsys.readouterr().out
    assert "RUNNING" in out and "R6" in out and "committed for tick 30" in out and "sum the numbers" in out
    main(["bot", "--state", state, "metrics", "--no-color", "--last", "2"])
    out = capsys.readouterr().out
    assert "3 of 4 settled (75%)" in out and "sum the numbers" in out and "R7" in out and "R6" in out and "R5" not in out
    main(["bot", "--state", state, "metrics", "--json"])
    assert json.loads(capsys.readouterr().out)["solve_rate"] == 0.75
    main(["bot", "--state", state, "log", "-n", "1"])
    assert capsys.readouterr().out.strip().endswith("round 1: committed")


def test_bot_run_once_keeps_a_heartbeat_while_it_polls_and_removes_it_after(tmp_path, monkeypatch, capsys):
    """cmd_bot_run with its chain, its profile defaults and its board fetch
    replaced: one poll on the fake chain must write the diary, the log and a
    heartbeat, and the heartbeat must be gone on the way out."""
    world = World()
    h = make_house(world, tmp_path)
    publish_and_open(h, world, riddle_file(tmp_path))
    h.collect(); h.export(str(tmp_path / "web"))
    board_path = str(tmp_path / "web" / "board.json")
    state = str(tmp_path / "bot-e")
    seen = {}
    script = tmp_path / "sum.py"                                # argparse takes no "-c" inside --solver
    script.write_text("import json,sys; r=json.load(sys.stdin); "
                      "print(json.dumps({'answer': sum(int(x) for x in r['input'].split())}))\n")
    solver = [sys.executable, str(script)]

    def fake_defaults(a):
        a.identity = ALICE
    monkeypatch.setattr(cli, "_bot_defaults", fake_defaults)
    monkeypatch.setattr(cli, "_chain", lambda a, signing: world.view(ALICE))
    real_close = cockpit.Heartbeat.close

    def close_spy(self):
        seen["had_heartbeat"] = os.path.exists(self.path)
        real_close(self)
    monkeypatch.setattr(cockpit.Heartbeat, "close", close_spy)
    main(["bot", "--state", state, "run", "--board", board_path, "--solver", *solver, "--once"])
    out = capsys.readouterr().out
    assert "committed" in out
    assert seen["had_heartbeat"] is True and not os.path.exists(os.path.join(state, cockpit.HEARTBEAT))
    assert cockpit.load_rows(os.path.join(state, cockpit.METRICS))[1]["answer"] == "142"
    assert any("committed" in l for l in cockpit.log_tail(state))
    assert cockpit.status(state)["state"] == "idle"
