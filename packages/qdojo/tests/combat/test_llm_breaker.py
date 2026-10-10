"""The LLM planner's provider circuit breaker, and the status the arena
publishes for an LLM fighter (llm_planner.Breaker, blocked, status; live.py).

No test here reaches the network: every request goes to a scripted fake
provider (an unscripted request fails the test), and the one planner process
started runs with an open breaker behind a proxy that refuses everything."""
import contextlib
import datetime as dt
import io
import json
import os
import subprocess
import sys
import time
import urllib.error

import pytest

from qdojo.combat import api, bot, export, live, planner, scouting
from qdojo.combat import llm_planner as L
from qdojo.combat import readmodel as rm

T0 = dt.datetime(2026, 9, 29, 8, 12, tzinfo=dt.timezone.utc).timestamp()
MODEL = "google/gemini-3.1-flash-lite"
GOOD = {"actions": ["JAB", "KICK", "BLOCK", "DUCK", "THROW", "RECOVER"], "power_slot": -1}


def _obs(round_index=1, fight_id="7"):
    side = {"fighter_id": "00" * 32, "hp": 70, "stamina": 40, "opening": 0, "guard_streak": 0,
            "power_available": True}
    return {"round_index": round_index, "self_slot": "A", "fight_id": fight_id, "self": side,
            "opponent": dict(side), "prior_rounds": [], "opponent_history": scouting.empty(None)}


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def http_error(code, why="Payment Required"):
    return urllib.error.HTTPError(L.URL, code, why, None, None)


def answer(plan=GOOD, cost=0.0001):
    return {"choices": [{"message": {"content": json.dumps(plan)}, "finish_reason": "stop"}],
            "usage": {"cost": cost, "prompt_tokens": 900, "completion_tokens": 40}}


class Provider:
    """A fake OpenRouter: each request takes the next scripted outcome (an
    exception to raise, or a response body), or `always` when set."""

    def __init__(self):
        self.script, self.always, self.requests = [], None, 0

    def __call__(self, req, timeout=None):
        assert req.full_url == L.URL and timeout and timeout <= 20
        self.requests += 1
        if self.always is None and not self.script:
            raise AssertionError("an unscripted request: no test may reach the network")
        out = self.always if self.always is not None else self.script.pop(0)
        if isinstance(out, BaseException):
            raise out
        return Response(out if isinstance(out, bytes) else json.dumps(out).encode())


@pytest.fixture(autouse=True)
def provider(monkeypatch):
    monkeypatch.setenv("OPEN_ROUTER_API_KEY", "test-key-not-real")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    fake = Provider()
    monkeypatch.setattr(L.urllib.request, "urlopen", fake)
    return fake


def decide(state, clock, capsys, **kw):
    """One planner decision in-process: (plan, stderr lines)."""
    out = L.decide(_obs(), MODEL, state, timeout=6, clock=clock, **kw)
    return out, capsys.readouterr().err.splitlines()


def fallback():
    return planner.plan_json(L.fallback_plan(_obs()))


ARENA_LOGS = ("fallback", "adjusted", "breaker")       # what bot.planner_chooser logs


# ---- the breaker in the planner process -----------------------------------------

def test_out_of_credit_opens_the_breaker_and_later_decisions_ask_nobody(tmp_path, provider, capsys):
    state, clock = tmp_path / "ken", Clock(T0)
    provider.script = [http_error(402)]
    out, err = decide(state, clock, capsys)
    assert out == fallback() and provider.requests == 1
    assert err == ["fallback to mixed-v1: provider out of credit (HTTP 402): Payment Required; breaker open, "
                   "no model calls until 08:42 UTC"]
    for minutes in (1, 10, 29):
        clock.t = T0 + 60 * minutes
        out, err = decide(state, clock, capsys)
        assert out == fallback() and provider.requests == 1          # no request while it is open
        assert err == ["no model call, breaker open until 08:42 UTC: provider out of credit (HTTP 402); "
                       "mixed-v1 plays"]
        assert not err[0].startswith(ARENA_LOGS)                       # so the arena does not log the round
    assert L.blocked(state, 1.0, clock.t) == "breaker"
    assert L.status(state, 1.0, clock.t) == {
        "state": "fallback", "reason": "provider out of credit (HTTP 402)", "since": "2026-09-29T08:12:00Z",
        "retry_at": "2026-09-29T08:42:00Z", "plays": "mixed-v1"}


@pytest.mark.parametrize("code,reason", [(401, "provider rejected the API key (HTTP 401)"),
                                         (403, "provider refused access (HTTP 403)")])
def test_every_account_refusal_opens_the_breaker_at_once(tmp_path, provider, capsys, code, reason):
    provider.script = [http_error(code, "Refused")]
    decide(tmp_path / "s", Clock(T0), capsys)
    b = L.read_breaker(tmp_path / "s", T0)
    assert (b["state"], b["kind"], b["reason"], b["until"]) == ("open", "auth", reason, T0 + L.AUTH_BACKOFF)


def test_after_the_backoff_one_probe_goes_out_and_an_answer_closes_the_breaker(tmp_path, provider, capsys):
    state, clock = tmp_path / "ken", Clock(T0)
    provider.script = [http_error(402)]
    decide(state, clock, capsys)
    clock.t = T0 + L.AUTH_BACKOFF
    assert L.blocked(state, 1.0, clock.t) is None                     # due: the arena starts the planner
    assert "retry_at" not in L.status(state, 1.0, clock.t)            # still offline until a probe answers
    provider.script = [http_error(402)]
    out, err = decide(state, clock, capsys)
    assert out == fallback() and provider.requests == 2
    assert err == ["fallback to mixed-v1: probe failed, provider out of credit (HTTP 402): Payment Required; "
                   "breaker open, no model calls until 09:42 UTC"]
    b = L.read_breaker(state, clock.t)
    assert (b["since"], b["backoff"], b["until"]) == (T0, 2 * L.AUTH_BACKOFF, clock.t + 2 * L.AUTH_BACKOFF)
    clock.t = b["until"]
    provider.script = [answer()]
    out, err = decide(state, clock, capsys)
    assert out == planner.plan_json(planner.parse_plan(json.dumps({"schema": planner.PLAN_SCHEMA, **GOOD})))
    assert err[0] == ("breaker closed: the model answered again after 1 h 30 min "
                      "(offline since 08:12 UTC: provider out of credit (HTTP 402))")
    assert err[0].startswith(ARENA_LOGS) and provider.requests == 3
    assert L.read_breaker(state, clock.t) == {"state": "closed", "fails": 0}
    assert L.status(state, 1.0, clock.t) == {"state": "ok"} and L.blocked(state, 1.0, clock.t) is None


def test_failed_probes_double_the_backoff_up_to_six_hours(tmp_path, provider, capsys):
    state, clock = tmp_path / "ken", Clock(T0)
    provider.always = http_error(402)
    seen = []
    for _ in range(7):
        decide(state, clock, capsys)
        b = L.read_breaker(state, clock.t)
        seen.append(b["backoff"])
        clock.t = b["until"]
    assert seen == [1800, 3600, 7200, 14400, 21600, 21600, 21600]
    assert provider.requests == 7


def test_an_open_breaker_lets_one_probe_through_at_a_time(tmp_path, provider, capsys):
    state, clock = tmp_path / "ken", Clock(T0)
    provider.script = [http_error(402)]
    decide(state, clock, capsys)
    clock.t = T0 + L.AUTH_BACKOFF
    first = L.Breaker(state, clock)
    assert first.admit(hold=21) is None and first.probing             # half-open: this process probes
    assert L.blocked(state, 1.0, clock.t) == "breaker"                 # the arena starts no second planner
    out, err = decide(state, clock, capsys)
    assert out == fallback() and provider.requests == 1
    assert err == ["no model call, breaker open, another decision is probing: provider out of credit (HTTP 402); "
                   "mixed-v1 plays"]
    clock.t += 22                                                       # a probe killed by its budget never reports:
    provider.script = [answer()]                                        # its claim lapses
    decide(state, clock, capsys)
    assert provider.requests == 2 and L.read_breaker(state, clock.t)["state"] == "closed"


def test_transient_failures_open_the_breaker_after_three_in_a_row(tmp_path, provider, capsys):
    state, clock = tmp_path / "qwen", Clock(T0)
    refused = urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
    provider.script = [http_error(503, "Service Unavailable"), TimeoutError("The read operation timed out"),
                       answer(), refused, http_error(429, "Too Many Requests"),
                       urllib.error.URLError(TimeoutError("timed out"))]
    lines = []
    for _ in range(5):
        out, err = decide(state, clock, capsys)
        lines += [x for x in err if x.startswith("fallback")]
        assert L.status(state, 1.0, clock.t) == {"state": "ok"}       # a few failures are not an outage
    assert L.read_breaker(state, clock.t) == {"state": "closed", "fails": 2}     # the answer reset the count
    assert lines == ["fallback to mixed-v1: provider error (HTTP 503): Service Unavailable",
                     "fallback to mixed-v1: provider timeout: TimeoutError: The read operation timed out",
                     "fallback to mixed-v1: provider unreachable: URLError: <urlopen error [Errno 111] "
                     "Connection refused>",
                     "fallback to mixed-v1: provider rate limit (HTTP 429): Too Many Requests"]
    out, err = decide(state, clock, capsys)
    assert err == ["fallback to mixed-v1: provider timeout: URLError: <urlopen error timed out>; 3 failures in a row, "
                   "breaker open, no model calls until 08:14 UTC"]
    assert provider.requests == 6
    assert L.status(state, 1.0, clock.t)["reason"] == "provider timeout"
    # A failed probe doubles the short backoff; an account refusal switches to the long one.
    clock.t = T0 + L.TRANSIENT_BACKOFF
    provider.script = [http_error(502, "Bad Gateway")]
    decide(state, clock, capsys)
    assert L.read_breaker(state, clock.t)["backoff"] == 2 * L.TRANSIENT_BACKOFF
    clock.t = L.read_breaker(state, clock.t)["until"]
    provider.script = [http_error(402)]
    decide(state, clock, capsys)
    b = L.read_breaker(state, clock.t)
    assert (b["kind"], b["backoff"], b["reason"], b["since"]) == ("auth", L.AUTH_BACKOFF,
                                                                  "provider out of credit (HTTP 402)", T0)


def test_an_unusable_reply_is_the_models_fault_and_closes_a_probing_breaker(tmp_path, provider, capsys):
    state, clock = tmp_path / "ken", Clock(T0)
    provider.script = [http_error(402)]
    decide(state, clock, capsys)
    clock.t = T0 + L.AUTH_BACKOFF
    provider.script = [answer({"actions": ["JAB"] * 5, "power_slot": -1})]
    out, err = decide(state, clock, capsys, reasoning="off")
    assert out == fallback()
    assert err[0].startswith("breaker closed: ") and err[-1].startswith("fallback to mixed-v1: PlannerError: BAD_PLAN")
    assert L.read_breaker(state, clock.t)["state"] == "closed"


def test_a_200_without_a_completion_is_classified_by_its_error_object(tmp_path, provider, capsys):
    provider.script = [{"error": {"code": 402, "message": "Insufficient credits"}}]
    out, err = decide(tmp_path / "s", Clock(T0), capsys)
    assert err[0].startswith("fallback to mixed-v1: provider out of credit (HTTP 402): Insufficient credits; "
                             "breaker open")
    provider.script = [{"id": "x"}, b"not json"]
    for _ in range(2):
        decide(tmp_path / "t", Clock(T0), capsys)
    assert L.read_breaker(tmp_path / "t", T0) == {"state": "closed", "fails": 2}


def test_offline_since_the_models_last_answer_not_since_the_first_refusal_seen(tmp_path, provider, capsys,
                                                                               monkeypatch):
    """A planner deployed into an outage that began long ago: the breaker is
    new, but the model last answered when spend.json was last written."""
    state = tmp_path / "ken"
    state.mkdir()
    (state / "spend.json").write_text(json.dumps({"2026-09-28": 0.2705}))
    last = dt.datetime(2026, 9, 28, 13, 26, tzinfo=dt.timezone.utc).timestamp()
    os.utime(state / "spend.json", (last, last))
    clock = Clock(T0 + 12 * 86400)
    provider.script = [http_error(402)]
    decide(state, clock, capsys)
    assert L.status(state, 1.0, clock.t) == {
        "state": "fallback", "reason": "provider out of credit (HTTP 402)", "since": "2026-09-28T13:26:00Z",
        "retry_at": "2026-10-11T08:42:00Z", "plays": "mixed-v1"}
    clock.t += L.AUTH_BACKOFF
    provider.script = [answer()]
    out, err = decide(state, clock, capsys)
    assert err[0] == ("breaker closed: the model answered again after 12 d 19 h 16 min "
                      "(offline since 2026-09-28 13:26 UTC: provider out of credit (HTTP 402))")
    monkeypatch.delenv("OPEN_ROUTER_API_KEY")
    assert L.status(state, 1.0, clock.t)["since"] == L._iso((state / "spend.json").stat().st_mtime)


def test_the_daily_cap_asks_nobody(tmp_path, provider, capsys):
    state = tmp_path / "claude"
    state.mkdir()
    (state / "spend.json").write_text(json.dumps({"2026-09-29": 1.0042}))
    out, err = decide(state, Clock(T0), capsys)
    assert out == fallback() and provider.requests == 0
    assert err == ["fallback to mixed-v1: daily cap $1.00 reached"]


def test_a_broken_or_impossible_breaker_file_never_keeps_the_model_shut(tmp_path):
    state = tmp_path / "s"
    state.mkdir()
    p = state / "breaker.json"
    for text in ("{not json", "[]", '{"state": "half"}'):
        p.write_text(text)
        assert L.read_breaker(state, T0) == {"state": "closed", "fails": 0}
    p.write_text(json.dumps({"state": "open", "kind": "auth", "reason": "provider out of credit (HTTP 402)",
                             "since": T0, "until": T0 + 30 * 86400, "backoff": 1800, "probe_until": 0}))
    assert L.read_breaker(state, T0)["until"] == T0                    # a clock set back, a hand edit: due now
    assert L.blocked(state, 1.0, T0) is None
    p.unlink()                                                          # deleting it closes it by hand
    assert L.status(state, 1.0, T0) == {"state": "ok"}


def test_the_breaker_lives_in_the_state_directory_across_processes(tmp_path, provider, capsys):
    """A new planner process (the arena starts one per decision) honours the
    breaker an earlier one opened: it prints the fallback plan and makes no
    request. The process gets a key and a proxy that refuses every
    connection, so even a request by mistake could not leave this host."""
    state, now = tmp_path / "ken", time.time()
    provider.script = [http_error(402)]
    decide(state, Clock(now), capsys)
    before = (state / "breaker.json").read_bytes()
    env = {**os.environ, "OPEN_ROUTER_API_KEY": "test-key-not-real", "HTTPS_PROXY": "http://127.0.0.1:9",
           "https_proxy": "http://127.0.0.1:9", "NO_PROXY": "", "no_proxy": ""}
    obs = _obs(fight_id="12")
    p = subprocess.run([sys.executable, "-m", "qdojo.combat.llm_planner", "--model", MODEL, "--state", str(state),
                        "--daily-usd", "1.0", "--timeout", "6"], input=json.dumps(obs).encode(),
                       capture_output=True, timeout=60, env=env, check=True)
    assert json.loads(p.stdout) == planner.plan_json(L.fallback_plan(obs))     # the arena's in-process plan, too
    err = p.stderr.decode().splitlines()
    assert len(err) == 1 and err[0].startswith("no model call, breaker open until ")
    assert (state / "breaker.json").read_bytes() == before


# ---- the arena: in-process fallback, logs, published status ------------------------

def _arena(tmp_path, lineup, logs=None):
    arena = live.Arena(tmp_path / "arena", lineup, seed=5, deterministic=True,
                       log=(logs.append if logs is not None else lambda m: None))
    arena.clock = Clock(T0)
    return arena


def _fid(arena, label):
    return next(f for f, e in arena.labels.items() if e["label"] == label)


def test_a_day_out_of_credit_starts_seven_planners_and_logs_seven_lines(tmp_path, provider, monkeypatch):
    """A decision every two minutes for 24 hours against a provider that
    answers 402: the arena starts the planner only for the decision that opens
    the breaker and for its probes, logs one line each, and plays mixed-v1
    in-process in between; the first answer closes the breaker (one line)."""
    logs = []
    arena = _arena(tmp_path, [{"label": "KEN.EXE", "llm": {"model": MODEL, "daily_usd": 1.0, "budget_ms": 7000,
                                                            "timeout": 6}}], logs)
    state = arena.dir / "llm" / "KEN.EXE"
    started = []

    def run(command, obs, budget_ms):                    # the planner process, run in-process for the test
        assert command[command.index("--state") + 1] == str(state) and budget_ms == 7000
        started.append(arena.clock.t)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            out = L.decide(obs, MODEL, state, 1.0, 6, clock=arena.clock)
        return planner.PlannerRun(planner.parse_plan(json.dumps(out)), err.getvalue(), 5), None
    monkeypatch.setattr(planner, "run_or_fallback", run)
    choose = arena.bots[_fid(arena, "KEN.EXE")].choose
    assert choose.slow
    provider.always = http_error(402)
    for i in range(24 * 30):
        arena.clock.t = T0 + 120 * i
        obs = _obs(round_index=i % 3, fight_id=str(100 + i // 3))
        assert choose(obs) == L.fallback_plan(obs)
    assert [round((t - T0) / 3600, 1) for t in started] == [0, 0.5, 1.5, 3.5, 7.5, 13.5, 19.5]
    assert provider.requests == len(logs) == 7
    assert all(": planner fallback to mixed-v1: " in m and "provider out of credit (HTTP 402)" in m for m in logs)
    provider.always = answer()
    arena.clock.t = L.read_breaker(state, arena.clock.t)["until"]
    choose(_obs())
    assert len(logs) == 8 and ": planner breaker closed: the model answered again after 1 d 1 h 30 min" in logs[-1]
    assert arena.planner_status(arena.labels[_fid(arena, "KEN.EXE")]) == {"state": "ok"}


def test_a_spent_budget_or_a_missing_key_plays_in_process_and_is_noted_once_a_day(tmp_path, monkeypatch):
    logs = []
    arena = _arena(tmp_path, [{"label": "CLAUDE", "llm": {"model": "anthropic/claude-sonnet-5", "daily_usd": 1.0}}],
                   logs)
    started = []

    def run(command, obs, budget_ms):
        started.append(1)
        return planner.PlannerRun(planner.FALLBACK, "", 5), None
    monkeypatch.setattr(planner, "run_or_fallback", run)
    choose = arena.bots[_fid(arena, "CLAUDE")].choose
    state = arena.dir / "llm" / "CLAUDE"
    state.mkdir(parents=True)
    (state / "spend.json").write_text(json.dumps({"2026-09-29": 1.02}))
    for _ in range(3):
        assert choose(_obs()) == L.fallback_plan(_obs())
    tick = arena.w.tick
    assert started == [] and logs == [f"tick {tick}: bot CLAUDE: daily model budget $1.00 spent: mixed-v1 plays "
                                      "until 00:00 UTC"]
    arena.clock.t = T0 + 86400                       # a new UTC day: the model is asked again
    assert choose(_obs()) == planner.FALLBACK and started == [1]
    monkeypatch.delenv("OPEN_ROUTER_API_KEY")
    for _ in range(2):
        assert choose(_obs()) == L.fallback_plan(_obs())
    assert started == [1] and logs[1:] == [f"tick {tick}: bot CLAUDE: no OpenRouter key in the environment: "
                                           "mixed-v1 plays"]


def test_the_arena_publishes_each_llm_fighters_status_through_the_export_and_the_api(tmp_path):
    lineup = [{"label": "KEN.EXE", "founding": True, "llm": {"model": MODEL, "daily_usd": 1.0}},
              {"label": "CLAUDE", "llm": {"model": "anthropic/claude-sonnet-5", "daily_usd": 0.5}},
              {"label": "QWEN-235", "llm": {"model": "qwen/qwen3-235b-a22b-2507"}},
              {"label": "tanuki", "policy": "reader-v1"}]
    arena = _arena(tmp_path, lineup)
    (arena.dir / "llm" / "KEN.EXE").mkdir(parents=True)
    L.Breaker(arena.dir / "llm" / "KEN.EXE", Clock(T0 - 600)).failure(L._http_error(402))
    claude = arena.dir / "llm" / "CLAUDE"
    claude.mkdir(parents=True)
    (claude / "spend.json").write_text(json.dumps({"2026-09-28": 0.2, "2026-09-29": 0.5031}))
    os.utime(claude / "spend.json", (T0 - 600, T0 - 600))
    dep = arena.deployment(1.5)
    by = {m["name"]: m for m in dep["fighters"].values()}
    assert by["KEN.EXE"]["driver"] == "llm:" + MODEL
    assert by["KEN.EXE"]["driver_status"] == {
        "state": "fallback", "reason": "provider out of credit (HTTP 402)", "since": "2026-09-29T08:02:00Z",
        "retry_at": "2026-09-29T08:32:00Z", "plays": "mixed-v1"}
    assert by["CLAUDE"]["driver_status"] == {
        "state": "fallback", "reason": "daily budget spent ($0.50)", "since": "2026-09-29T08:02:00Z",
        "retry_at": "2026-09-30T00:00:00Z", "plays": "mixed-v1"}
    assert by["QWEN-235"]["driver_status"] == {"state": "ok"}
    assert "driver_status" not in by["tanuki"]
    # The export carries it in index.json and in the fighter's own file ...
    out = tmp_path / "web" / "combat" / "v1"
    export.export_all(arena.w.contract, out, keep=5, deployment=dep)
    index = json.loads((out / "index.json").read_text())
    ids = {m["name"]: h for h, m in dep["fighters"].items()}
    for name in ("KEN.EXE", "CLAUDE", "QWEN-235"):
        assert index["deployment"]["fighters"][ids[name]]["driver_status"] == by[name]["driver_status"]
        assert json.loads((out / "fighters" / f"{ids[name]}.json").read_text())["driver_status"] == \
            by[name]["driver_status"]
    # ... and the read API serves it with the fighter (and in the roster).
    arena.save()
    rm.rebuild(arena.dir, tmp_path / "rm.sqlite", out, log=lambda m: None)
    reader = api.Reader(rm.connect(tmp_path / "rm.sqlite", readonly=True))
    assert reader.fighter(ids["CLAUDE"])["driver_status"] == by["CLAUDE"]["driver_status"]
    assert "driver_status" not in reader.fighter(ids["tanuki"])
    roster = {f["name"]: f for f in reader.fighters()}
    assert roster["KEN.EXE"]["driver_status"] == by["KEN.EXE"]["driver_status"]


def test_without_a_key_every_llm_fighter_says_so(tmp_path, monkeypatch):
    arena = _arena(tmp_path, [{"label": "GEM-LITE", "llm": {"model": "google/gemini-2.5-flash-lite"}}])
    monkeypatch.delenv("OPEN_ROUTER_API_KEY")
    (m,) = arena.deployment(1.5)["fighters"].values()
    assert m["driver_status"] == {"state": "fallback", "reason": "no model API key configured", "plays": "mixed-v1"}


def test_the_bot_logs_breaker_lines_and_not_skipped_rounds(monkeypatch):
    stderr = "\n".join(["no model call, breaker open until 08:42 UTC: provider out of credit (HTTP 402); "
                        "mixed-v1 plays",
                        "breaker closed: the model answered again after 2 h",
                        "test/model: $0.00010 (today $0.0001); tokens in 900, out 40, finish stop",
                        "adjusted: power strike already spent: power_slot dropped, actions kept"])
    monkeypatch.setattr(planner, "run_or_fallback",
                        lambda command, obs, budget_ms: (planner.PlannerRun(planner.FALLBACK, stderr, 5), None))
    logs = []
    bot.planner_chooser(["planner"], 1000, log=logs.append)(_obs())
    assert logs == ["fight 7 round 1: planner breaker closed: the model answered again after 2 h",
                    "fight 7 round 1: planner adjusted: power strike already spent: power_slot dropped, actions kept"]
