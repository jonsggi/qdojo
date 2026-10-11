"""An LLM-driven combat planner process (docs/api.md §1) via OpenRouter.

  OPEN_ROUTER_API_KEY=... python -m qdojo.combat.llm_planner --model deepseek/deepseek-v4-flash \
      --state ~/.qdojo/combat/llm/ken --daily-usd 1.00
  ... --model anthropic/claude-sonnet-5 --prompt planner-system-claude.md --reasoning off

Reads one observation on stdin, prints one plan. A model answer is used only
if it parses as a plan; it is then checked against the fighter's state with
the engine's validate_plan (a spent power slot is dropped, anything else
illegal falls back). Otherwise, and whenever the day's spend cap is
reached, the plan comes from the local mixed-v1 policy, with the reason on
stderr. That keeps the fighter playing instead of falling back to six idle
RECOVERs. Spend is read from OpenRouter's usage accounting and kept per UTC
day in the state directory. No key, seed or salt is ever printed.

A circuit breaker in the state directory (breaker.json) stops asking a
provider that keeps refusing. An account error (HTTP 401, 402, 403: a bad
key, no credit, no access) opens it at once for 30 minutes; three transient
failures in a row (429, 5xx, timeouts, connection errors), each within 30
minutes of the one before, open it for 2 minutes. While it is open no request
is made and mixed-v1 plays at once. When the time is up, one process probes:
an answer closes the breaker, a failure opens it again for twice as long (at
most 6 hours, or 30 minutes for transient failures). It logs changes, not
rounds: the decision that opens it prints the usual "fallback ..." line,
closing it prints "breaker closed ...", and a decision it skips prints a line
the arena does not log. Deleting breaker.json closes it by hand (after a
top-up, say). It also keeps when the model last answered and when the current
run of failures began. The arena reads the same files to publish each LLM
fighter's status, and does not start this process at all while no model call
could be made (live.py). The planner's own files never stop a decision: one
it cannot read counts as empty. A state directory it cannot write to (a full
disk, a read-only mount) gets no request, whose cost could not be counted
toward the cap: the fallback plays and its log line says why. A write that
fails after the request (the disk filled meanwhile) loses no paid reply, only
the record (a breaker that cannot save cannot open), and a log line says so.
"""
from __future__ import annotations

import time

# The arena's time budget for a decision runs from the moment it starts this
# process, so the request's timeout counts from here, not from after the imports.
STARTED = time.monotonic()

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import math
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    import fcntl
except ImportError:                     # no flock on this platform: the breaker runs unlocked
    fcntl = None

from . import npcs, planner, scouting
from .engine import resolve_beat
from .rules import CANDIDATE_1, RulesetError, by_digest, candidate_1
from .types import Action, FighterState

PROMPTS = Path(__file__).resolve().parents[5] / "prompts/combat"
PROMPT = PROMPTS / "planner-system.md"
URL = "https://openrouter.ai/api/v1/chat/completions"
FALLBACK_POLICY = "mixed-v1"

# The circuit breaker (module docstring). Seconds.
AUTH_BACKOFF, AUTH_BACKOFF_MAX = 30 * 60, 6 * 3600
TRANSIENT_BACKOFF, TRANSIENT_BACKOFF_MAX, TRIP_AFTER = 2 * 60, 30 * 60, 3
BACKOFF = {"auth": (AUTH_BACKOFF, AUTH_BACKOFF_MAX), "transient": (TRANSIENT_BACKOFF, TRANSIENT_BACKOFF_MAX)}
RUN_GAP = 30 * 60               # failures further apart (an idle stretch, the arena down) are not one run
PROBE_MARGIN = 15               # a probe's claim outlives its request timeout by this much
PROBE_HOLD_MAX = 5 * 60         # and never holds longer than this
ACCOUNT_ERRORS = {401: "provider rejected the API key", 402: "provider out of credit",
                  403: "provider refused access"}


def _rules(obs: dict):
    """The ruleset the observation names (candidate 1 when it names none this
    package knows): projections, fallbacks and the legality check use it."""
    try:
        return by_digest(str(obs.get("ruleset_digest")))
    except RulesetError:
        return candidate_1()


def prompt_for(prompt: Path, obs: dict) -> Path:
    """A ruleset other than candidate 1 uses the prompt's "-<ruleset suffix>"
    sibling when one exists (planner-system.md -> planner-system-candidate-2.md),
    so the model is told the numbers of the game it is actually playing."""
    rules = _rules(obs)
    if rules.semantic_version == CANDIDATE_1:
        return prompt
    variant = prompt.with_name(f"{prompt.stem}-{rules.semantic_version.removeprefix('combat-v1-')}{prompt.suffix}")
    return variant if variant.exists() else prompt


def _power_line(side: dict, who: str) -> str:
    if side["power_available"]:
        return f"{who} power_available: true (the once-per-fight power strike is still unused)"
    if who == "Your":
        return ("Your power_available: false — you have ALREADY USED your power strike; "
                "power_slot must be -1")
    return f"{who} power_available: false (already used)"


def _pct(counts: dict) -> str:
    total = sum(counts.values())
    if not total:
        return "none"
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ", ".join(f"{a} {100 * n // total}%" for a, n in ranked if n)


def _scouting_lines(obs: dict) -> list[str]:
    """A compact scouting report from observation.opponent_history."""
    hist = obs.get("opponent_history") or {}
    fights = hist.get("fights") or []
    if not fights:
        return ["Scouting: no finished fights of this opponent on record."]
    summ = hist.get("summary") or scouting.summarize(fights)
    rec = summ.get("record", {})
    record = " ".join(f"{k}{v}" for k, v in sorted(rec.items()))
    lines = [f"Scouting: opponent's last {len(fights)} finished fight(s), newest first; their record {record}."]
    for k, counts in sorted(summ.get("plan_actions_by_round", {}).items()):
        lines.append(f"  Round {int(k) + 1} plans: {_pct(counts)}.")
    power = summ.get("power", {})
    used = power.get("used_in_round", {})
    if used or power.get("never"):
        where = ", ".join(f"round {int(k) + 1} in {n}" for k, n in sorted(used.items()))
        lines.append(f"  Power strike used: {where or 'never'}; unused in {power.get('never', 0)} fight(s).")
    r = obs["round_index"]
    same = [(f, x) for f in fights for x in f["rounds"] if x["round_index"] == r][:4]
    if same:
        lines.append(f"  Their recent round-{r + 1} plans (newest first):")
        for f, x in same:
            p = x["plan"]
            power_txt = f", power on beat {p['power_slot'] + 1}" if p["power_slot"] != -1 else ""
            lines.append(f"    fight {f['fight_id']} ({f['outcome']}): {' '.join(p['actions'])}{power_txt}")
    distinct = {tuple(x["plan"]["actions"]) for f in fights for x in f["rounds"]}
    total = sum(len(f["rounds"]) for f in fights)
    if total >= 3 and len(distinct) == 1:
        lines.append("  They played the SAME plan in every scouted round: expect it again.")
    elif total >= 3:
        lines.append(f"  {len(distinct)} distinct plans in {total} scouted rounds.")
    return lines


def _expected_plan(obs: dict) -> tuple[list[str], str] | None:
    """The opponent plan most worth projecting: their plan last round in this
    fight, else their most recent scouted plan for this round index."""
    other = "B" if obs["self_slot"] == "A" else "A"
    if obs.get("prior_rounds"):
        return obs["prior_rounds"][-1]["plans"][other]["actions"], "their plan from last round"
    for f in (obs.get("opponent_history") or {}).get("fights", []):
        for r in f["rounds"]:
            if r["round_index"] == obs["round_index"]:
                return r["plan"]["actions"], f"their round-{obs['round_index'] + 1} plan from fight {f['fight_id']}"
    return None


def _projection_line(obs: dict) -> str | None:
    """Their stamina, beat by beat, if they repeat that plan and are never hit
    (their best case): where they would be EXHAUSTED, and open to 18 from a KICK."""
    guess = _expected_plan(obs)
    if guess is None:
        return None
    actions, source = guess
    rules = _rules(obs)
    them = planner.fighter_state(obs["opponent"])
    # A fresh, blocking stand-in each beat: it never hits them, so their
    # recoveries are the unhit kind and nothing but their own plan moves them.
    wall = FighterState(rules.max_hp, rules.max_stamina, 0, 0, 0)
    staminas, exhausted = [them.stamina], []
    for i, name in enumerate(actions):
        them, _, tr = resolve_beat(rules, them, wall, Action[name], Action.BLOCK)
        staminas.append(them.stamina)
        if tr.a.effective is Action.EXHAUSTED:
            exhausted.append(i + 1)
    line = (f"Projection: if the opponent repeats {source} ({' '.join(actions)}) and is never hit, "
            f"their stamina goes {'->'.join(map(str, staminas))}")
    if exhausted:
        line += f"; they could NOT pay for beat(s) {', '.join(map(str, exhausted))} and would be EXHAUSTED there"
    return line + "."


def _user_prompt(obs: dict) -> str:
    me, opp = obs["self"], obs["opponent"]
    me_slot = obs["self_slot"]
    other = "B" if me_slot == "A" else "A"
    lines = [f"Round {obs['round_index'] + 1} of 3.",
             f"You: HP {me['hp']}, stamina {me['stamina']}, opening {me['opening']}, "
             f"block streak {me['guard_streak']}.",
             _power_line(me, "Your") + ".",
             f"Opponent: HP {opp['hp']}, stamina {opp['stamina']}, opening {opp['opening']}, "
             f"block streak {opp['guard_streak']}.",
             _power_line(opp, "Opponent") + "."]
    for r in obs.get("prior_rounds", []):
        plans = r.get("plans", {})
        mine = [b[me_slot]["effective"] for b in r["beats"]]
        theirs = [b[other]["effective"] for b in r["beats"]]
        start, end = r.get("start", {}), r.get("end", {})
        line = f"Round {r['round_index'] + 1}: you played {' '.join(mine)}; opponent played {' '.join(theirs)}."
        if plans:
            pp = plans[other]
            line += (f" Opponent's revealed plan: {' '.join(pp['actions'])}"
                     + (f" (power on beat {pp['power_slot'] + 1})" if pp["power_slot"] != -1 else "") + ".")
        if start and end:
            line += (f" HP you {start[me_slot]['hp']}->{end[me_slot]['hp']},"
                     f" opponent {start[other]['hp']}->{end[other]['hp']}.")
        lines.append(line)
    lines += _scouting_lines(obs)
    projection = _projection_line(obs)
    if projection:
        lines.append(projection)
    lines.append("Choose your six actions for this round.")
    return "\n".join(lines)


def _extract_json(text: str) -> str:
    """The last JSON object in the reply that has an "actions" key (a model may
    think aloud before it), else the outermost {...} span."""
    dec, found, i = json.JSONDecoder(), None, text.find("{")
    while i >= 0:
        try:
            doc, end = dec.raw_decode(text, i)
        except ValueError:
            i = text.find("{", i + 1)
            continue
        if isinstance(doc, dict) and "actions" in doc:
            found = text[i:end]
        i = text.find("{", end)
    if found is not None:
        return found
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise planner.PlannerError("BAD_PLAN", "no JSON object in the model reply")
    return text[start:end + 1]


def _model_plan(text: str):
    """The plan in a model reply. Only "actions" and "power_slot" are read; a
    short free-text key such as "read" is allowed and ignored."""
    try:
        doc = json.loads(_extract_json(text))
    except ValueError as exc:
        raise planner.PlannerError("BAD_PLAN", f"reply is not JSON: {exc}") from None
    if not isinstance(doc, dict) or "actions" not in doc:
        raise planner.PlannerError("BAD_PLAN", "reply lacks actions")
    actions, power_slot, notes = _normalise(doc["actions"], doc.get("power_slot", -1))
    for n in notes:
        print(f"repaired: {n}", file=sys.stderr)
    body = {"schema": planner.PLAN_SCHEMA, "actions": actions, "power_slot": power_slot}
    return planner.parse_plan(json.dumps(body)), doc.get("read")


ATTACKS = ("JAB", "KICK", "THROW")


def _normalise(actions, power_slot):
    """Repair the harmless slips models make, so a sound read of the fight is
    not thrown away for a spelling: lower case and spaces in names, a
    "POWER JAB" style name (becomes the power slot when none is set), a power
    slot as a string, and a power slot on a move that cannot carry power
    (dropped). Anything else is left for parse_plan to reject."""
    notes = []
    if not isinstance(actions, list):
        return actions, power_slot, notes
    out = []
    for i, a in enumerate(actions):
        if isinstance(a, str):
            name = a.strip().upper().replace("-", " ").replace("_", " ")
            if name.startswith("POWER ") or name.endswith(" POWER") or name.endswith("*"):
                base = name.replace("POWER", "").replace("*", "").strip()
                if base in ATTACKS:
                    if power_slot in (-1, None, "-1"):
                        power_slot = i
                    notes.append(f"action {a!r} read as {base} with the power slot")
                    name = base
            if name == "LAST STAND" or name == "LASTSTAND":      # candidate 3's two-word action name
                name = "LAST_STAND"
            if name != a:
                a = name
        out.append(a)
    if isinstance(power_slot, str) and power_slot.lstrip("-").isdigit():
        power_slot = int(power_slot)
    if power_slot is None:
        power_slot = -1
    if isinstance(power_slot, int) and 0 <= power_slot < len(out) and out[power_slot] not in ATTACKS:
        notes.append(f"power_slot {power_slot} selects {out[power_slot]}, not an attack: dropped")
        power_slot = -1
    return out, power_slot, notes


def fallback_plan(obs: dict):
    """The local mixed-v1 plan for this observation, seeded by the observation
    itself: the arena's in-process fallback (live.py) and this process agree."""
    obs = json.loads(json.dumps(obs))           # exactly what the process reads from stdin
    rules = _rules(obs)
    s, o = planner.fighter_state(obs["self"]), planner.fighter_state(obs["opponent"])
    seed = hashlib.sha256(json.dumps(obs, sort_keys=True).encode()).digest()
    return npcs.mixed_v1(rules, npcs.Observation(obs["round_index"], s, o), npcs.Stream(seed, 0, obs["round_index"]))


def _fallback(obs: dict, why: str, quiet: bool = False) -> dict:
    """The fallback plan, with the reason on stderr. A quiet line (a decision
    the open breaker skipped) does not start with "fallback", so the arena,
    which logs those lines (bot.planner_chooser), does not log every round."""
    if quiet:
        print(f"no model call, {why}; {FALLBACK_POLICY} plays", file=sys.stderr)
    else:
        print(f"fallback to {FALLBACK_POLICY}: {why}", file=sys.stderr)
    return planner.plan_json(fallback_plan(obs))


def _day(now: float) -> str:
    return dt.datetime.fromtimestamp(now, dt.timezone.utc).date().isoformat()


def _number(v) -> float | None:
    """A JSON number as a finite float, else None. The planner's files are
    read through it, so a hand edit or a broken file (a string, true, NaN, an
    integer too large for a float) never stops a decision."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        v = float(v)
    except OverflowError:
        return None
    return v if math.isfinite(v) else None


class Spend:
    """USD spent per UTC day, from OpenRouter's usage accounting; the last 60 days are kept."""

    def __init__(self, state: Path, clock=time.time):
        self.path = state / "spend.json"
        self.day = _day(clock())
        self.doc = _spend_doc(self.path)
        self.today = self.doc.get(self.day, 0.0)

    def add(self, usd: float) -> str | None:
        """None once the record is written, else why not, for the log line.
        The reply it paid for is used all the same: decide() saw the
        directory take a write before the request."""
        self.today += usd
        self.doc[self.day] = self.today
        self.doc = dict(sorted(self.doc.items())[-60:])
        try:
            _write_json(self.path, self.doc)
        except OSError as exc:
            return f"spend not saved: {type(exc).__name__}: {str(exc)[:120]}"
        return None


def _spend_doc(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        doc = {}
    days = ((k, _number(v)) for k, v in doc.items()) if isinstance(doc, dict) else ()
    return {k: v for k, v in days if v is not None}


def _tmp(path: Path) -> Path:
    return path.with_name(f"{path.name}.{os.getpid()}.tmp")


def _write_json(path: Path, doc: dict):
    """Atomically, through a temporary file of this process's own (two
    decisions of one fighter can overlap). A write that fails (a full disk)
    raises and leaves no temporary file behind."""
    tmp = _tmp(path)
    try:
        tmp.write_text(json.dumps(doc))
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise


def _check_writable(path: Path):
    """Raises OSError when `path` could not be written now (a full disk, a
    read-only mount): its temporary file is written and removed, and `path`
    itself is left alone (spend.json's last write is a time the breaker reads)."""
    tmp = _tmp(path)
    try:
        tmp.write_text("{}")
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def _written(path: Path) -> float | None:
    """When a file was last written, if it exists."""
    try:
        return path.stat().st_mtime
    except OSError:
        return None


# ---- the provider circuit breaker --------------------------------------------

@contextlib.contextmanager
def _locked(state: Path):
    """Holds the fighter's breaker lock (breaker.lock) while its record is read
    and rewritten, so decisions that overlap neither both claim a probe nor
    lose an update. Held for a file read and write, never across a request.
    Best effort: where the lock cannot be taken (a read-only directory), the
    update runs unlocked."""
    try:
        fd = os.open(state / "breaker.lock", os.O_RDWR | os.O_CREAT, 0o600) if fcntl else None
    except OSError:
        fd = None
    try:
        if fd is not None:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if fd is not None:
            os.close(fd)                # releases the lock



class ProviderError(Exception):
    """A request the provider did not answer with a completion. `kind` is
    "auth" (the account: key, credit, access) or "transient"; `reason` is the
    short wording the breaker keeps and the export shows, `detail` is for the log."""

    def __init__(self, kind: str, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.kind, self.reason, self.detail = kind, reason, detail


def _http_error(code: int, detail: str = "") -> ProviderError:
    if code in ACCOUNT_ERRORS:
        return ProviderError("auth", f"{ACCOUNT_ERRORS[code]} (HTTP {code})", detail)
    return ProviderError("transient", f"{'provider rate limit' if code == 429 else 'provider error'} (HTTP {code})",
                         detail)


def provider_error(exc: Exception) -> ProviderError:
    """What a request raised, classified for the breaker. Everything but an
    account refusal is transient: a timeout, a refused connection, a 5xx, a
    body that is not JSON."""
    if isinstance(exc, urllib.error.HTTPError):
        return _http_error(exc.code, str(exc.reason)[:120])
    detail = f"{type(exc).__name__}: {str(exc)[:120]}"
    if isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError):
        return ProviderError("transient", "provider timeout", detail)
    if isinstance(exc, ValueError):
        return ProviderError("transient", "unreadable provider response", detail)
    return ProviderError("transient", "provider unreachable", detail)


def _body_error(doc) -> ProviderError:
    """A 200 response without a completion: OpenRouter's error object, if any, says why."""
    err = doc.get("error") if isinstance(doc, dict) else None
    err = err if isinstance(err, dict) else {}
    code, detail = err.get("code"), str(err.get("message") or "")[:120]
    if type(code) is int:
        return _http_error(code, detail)
    return ProviderError("transient", "provider sent no completion", detail)


def _when(t: float, now: float) -> str:
    """A time for a log line: HH:MM UTC, with the date when it is not today."""
    at = dt.datetime.fromtimestamp(t, dt.timezone.utc)
    return at.strftime("%H:%M UTC" if _day(t) == _day(now) else "%Y-%m-%d %H:%M UTC")


def _span(seconds: float) -> str:
    m = max(0, int(seconds)) // 60
    d, h, m = m // 1440, m // 60 % 24, m % 60
    return " ".join(f"{n} {u}" for n, u in ((d, "d"), (h, "h"), (m, "min")) if n) or "under a minute"


def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _past(v, now: float) -> float | None:
    """A time from the breaker record, no later than now (a clock set back), or None."""
    v = _number(v)
    return None if v is None or v < 0 else min(v, now)


def read_breaker(state: Path, now: float, legacy: float | None = None) -> dict:
    """The breaker record in the state directory: {"state": "closed", "fails": n,
    "since", "failed"} (n transient failures in a row, the first of them at
    `since`, the latest at `failed`) or
    {"state": "open", "kind", "reason", "since" (when this run of failures
    began), "until", "backoff", "probe_until"}, each with "answered": when the
    model last answered, or None. A record that has never said (none yet, or
    one from before it kept the time) takes `legacy`. Missing or unreadable
    is closed, and a value that is not a sane number reads as its default.
    An open breaker whose times lie further ahead than its kind's longest
    backoff, or a probe's claim than PROBE_HOLD_MAX, could put them (a clock
    set back, a hand edit) is due at once, so nothing can keep it shut for
    longer than it ever means to."""
    try:
        doc = json.loads((Path(state) / "breaker.json").read_text())
    except (OSError, ValueError):
        doc = None
    doc = doc if isinstance(doc, dict) else {}
    answered = _past(doc.get("answered"), now) if "answered" in doc else legacy
    if doc.get("state") != "open":
        fails = doc.get("fails")
        fails = fails if type(fails) is int and fails > 0 else 0
        return {"state": "closed", "fails": fails, "since": _past(doc.get("since"), now) if fails else None,
                "failed": _past(doc.get("failed"), now) if fails else None, "answered": answered}

    def num(key, default=0.0):
        v = _number(doc.get(key))
        return default if v is None else v
    kind = doc.get("kind") if doc.get("kind") in ("auth", "transient") else "transient"
    until, probe = num("until"), num("probe_until")
    if until - now > BACKOFF[kind][1]:
        until = now
    if probe - now > PROBE_HOLD_MAX:
        probe = 0.0
    reason = doc.get("reason") if isinstance(doc.get("reason"), str) and doc.get("reason") else "provider failure"
    since = _past(doc.get("since"), now)
    return {"state": "open", "kind": kind, "reason": reason[:120], "since": now if since is None else since,
            "until": until, "backoff": num("backoff", TRANSIENT_BACKOFF), "probe_until": probe, "answered": answered}


class Breaker:
    """The provider circuit breaker of one fighter, shared by its planner
    processes through breaker.json (each decision is a new process).

    closed: requests are made; transient failures in a row are counted.
    open: no request until `until`. Then the first process to come claims the
    probe (half-open) for its request's time; its answer closes the breaker,
    its failure opens it again for twice as long. Each update re-reads the
    file under the fighter's lock, so overlapping processes lose nothing.
    Saving is best effort: a record that cannot be written only means the
    breaker cannot open, and the log line says so."""

    def __init__(self, state: Path, clock=time.time):
        self.state, self.clock = Path(state), clock
        self.probing = False
        # Before breaker.json kept the model's last answer, the last write of
        # spend.json was it: read before this process writes spend.json itself.
        self.legacy = _written(self.state / "spend.json")

    def read(self) -> dict:
        return read_breaker(self.state, self.clock(), self.legacy)

    def _save(self, doc: dict) -> str | None:
        """None once the record is written, else why not, for the log line."""
        try:
            _write_json(self.state / "breaker.json", doc)
        except OSError as exc:
            return f"breaker state not saved: {type(exc).__name__}: {str(exc)[:120]}"
        return None

    def admit(self, hold: float) -> str | None:
        """None if this process may ask the provider now (claiming the probe of
        an open breaker that is due, for `hold` seconds at most), else why
        not, for a quiet fallback."""
        with _locked(self.state):
            now, b = self.clock(), self.read()
            if b["state"] != "open":
                return None
            if now < b["until"]:
                return f"breaker open until {_when(b['until'], now)}: {b['reason']}"
            if now < b["probe_until"]:
                return f"breaker open, another decision is probing: {b['reason']}"
            unsaved = self._save({**b, "probe_until": now + min(hold, PROBE_HOLD_MAX)})
        if unsaved:                         # the probe goes out unclaimed: another decision may probe too
            print(unsaved, file=sys.stderr)
        self.probing = True
        return None

    def success(self) -> str | None:
        """The provider answered: the breaker closes and keeps the time.
        Returns the log line when that closed an open breaker, or when the
        record could not be saved."""
        with _locked(self.state):
            now, b = self.clock(), self.read()
            unsaved = self._save({"state": "closed", "fails": 0, "answered": now})
        self.probing = False
        if unsaved or b["state"] != "open":
            return unsaved
        return (f"breaker closed: the model answered again after {_span(now - b['since'])} "
                f"(offline since {_when(b['since'], now)}: {b['reason']})")

    def failure(self, err: ProviderError) -> str:
        """A request failed. Returns the fallback reason, which says when the
        breaker opened and until when, or that it could not be saved."""
        with _locked(self.state):
            return self._failure(err)

    def _failure(self, err: ProviderError) -> str:
        now, b = self.clock(), self.read()
        first, most = BACKOFF[err.kind]
        if b["state"] == "open":
            if not self.probing:            # a request from before it opened: the breaker already knows
                return f"{err}; breaker already open"
            self.probing = False
            backoff = min(most, 2 * b["backoff"]) if b["kind"] == err.kind else first
            doc = {**b, "kind": err.kind, "reason": err.reason, "until": now + backoff, "backoff": backoff,
                   "probe_until": 0}
            told = f"probe failed, {err}; breaker open, no model calls until {_when(now + backoff, now)}"
        else:
            # Offline since the first failure of this run, not since the model's
            # last answer: a fighter can sit idle for hours between the two.
            # A failure more than RUN_GAP after the one before starts a new
            # run, so an idle stretch or the arena's downtime joins nothing.
            run = b["since"] is not None and b["failed"] is not None and now - b["failed"] <= RUN_GAP
            fails, since = (b["fails"] + 1, b["since"]) if run else (1, now)
            if err.kind == "auth" or fails >= TRIP_AFTER:
                doc = {"state": "open", "kind": err.kind, "reason": err.reason, "since": since,
                       "until": now + first, "backoff": first, "probe_until": 0, "answered": b["answered"]}
                told = (f"{err}; {f'{fails} failures in a row, ' if err.kind != 'auth' else ''}breaker open, "
                        f"no model calls until {_when(now + first, now)}")
            else:
                doc = {"state": "closed", "fails": fails, "since": since, "failed": now, "answered": b["answered"]}
                told = str(err)
        unsaved = self._save(doc)
        return told if unsaved is None else f"{err}; {unsaved}"


# ---- what the arena reads: this planner's status -------------------------------

def api_key(env=None) -> str | None:
    env = os.environ if env is None else env
    return env.get("OPEN_ROUTER_API_KEY") or env.get("OPENROUTER_API_KEY")


def _spent(state: Path, now: float) -> tuple[float, float | None]:
    """USD spent on the UTC day of `now`, and when spend.json was last written
    (once the day's cap is reached, nothing is spent, so: when it was reached)."""
    path = Path(state) / "spend.json"
    at = _written(path)
    usd = _spend_doc(path).get(_day(now), 0.0) if at is not None else 0.0
    return usd, at


def blocked(state: Path, daily_usd: float, now: float | None = None, env=None) -> str | None:
    """Why this planner would make no model call right now: "no_key", "budget"
    (the day's cap is spent) or "breaker" (open, or a probe already running);
    None when it would call or probe. The arena then plays fallback_plan
    in-process instead of starting the planner."""
    now = time.time() if now is None else now
    if not api_key(env):
        return "no_key"
    if _spent(state, now)[0] >= daily_usd:
        return "budget"
    b = read_breaker(state, now)
    if b["state"] == "open" and (now < b["until"] or now < b["probe_until"]):
        return "breaker"
    return None


def status(state: Path, daily_usd: float, now: float | None = None, env=None) -> dict:
    """What chooses this fighter's plans now, for the public export (index.json
    deployment.fighters[id].driver_status): {"state": "ok"} while the model is
    asked, else {"state": "fallback", "reason", "since", "last_answer",
    "retry_at", "plays"}: why; since when (the first failure of this outage,
    or when the day's budget ran out); when the model last answered (an open
    breaker, no key); when it is next asked (times ISO-8601 UTC, each only
    when known); and the policy that plays meanwhile."""
    now = time.time() if now is None else now
    usd, at = _spent(state, now)
    b = read_breaker(state, now, legacy=at)
    last = {"last_answer": _iso(b["answered"])} if b["answered"] is not None else {}
    if not api_key(env):
        return {"state": "fallback", "reason": "no model API key configured", **last, "plays": FALLBACK_POLICY}
    if b["state"] == "open":
        return {"state": "fallback", "reason": b["reason"], "since": _iso(b["since"]), **last,
                **({"retry_at": _iso(b["until"])} if b["until"] > now else {}), "plays": FALLBACK_POLICY}
    if usd >= daily_usd:
        midnight = dt.datetime.fromisoformat(_day(now)).replace(tzinfo=dt.timezone.utc) + dt.timedelta(days=1)
        return {"state": "fallback", "reason": "daily model budget spent",
                **({"since": _iso(at)} if at is not None and _day(at) == _day(now) else {}),
                "retry_at": _iso(midnight.timestamp()), "plays": FALLBACK_POLICY}
    return {"state": "ok"}


def request_body(model: str, obs: dict, prompt: Path = PROMPT, reasoning: str = "low",
                 max_tokens: int = 1200) -> dict:
    system = prompt.read_text()
    anthropic = model.startswith("anthropic/")
    body = {"model": model, "max_tokens": max_tokens, "usage": {"include": True},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": _user_prompt(obs)}]}
    if anthropic:
        # The system prompt is the same for every round: cache it (a cache read
        # costs a tenth of an input token), and leave sampling at the model
        # default. The Claude prompt lets the model reason briefly in the reply
        # before the JSON object; the last JSON object with "actions" is read.
        body["messages"][0]["content"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        body["messages"][1]["content"] += ("\nThe commit window is short: think in at most three short sentences, "
                                               "then end with the JSON object.")
    else:
        body["temperature"] = 0.7
        body["response_format"] = {"type": "json_object"}
        body["messages"][1]["content"] += "\nAnswer with the JSON object only."
    # Little or no hidden reasoning: a reasoning model otherwise spends the
    # whole token budget before answering.
    # "none" sends no setting (the model's default); "off" turns reasoning off
    # outright (a Claude model otherwise thinks adaptively, ~500 tokens a call).
    if reasoning == "off":
        body["reasoning"] = {"enabled": False}
    elif reasoning != "none":
        body["reasoning"] = {"effort": reasoning, "exclude": True}
    return body


def ask(model: str, obs: dict, timeout: float, spend: "Spend", prompt: Path = PROMPT, reasoning: str = "low",
        max_tokens: int = 1200, breaker: "Breaker | None" = None) -> dict:
    """One model call. Its cost is recorded even when the reply is unusable,
    or a billed reply carries no completion at all. The plan is checked
    against this fighter's state before it is returned. A request that gets
    no completion raises ProviderError; one that does tells the breaker, if
    any (an unusable reply is the model's fault, not the provider's). A
    spend or breaker record that cannot be saved is logged; the reply is
    used all the same."""
    key = api_key()
    if not key:
        raise planner.PlannerError("NOT_STARTED", "no OpenRouter key in the environment")
    started = time.monotonic()

    def note(line: str | None):
        if line:
            print(line, file=sys.stderr)

    def call(reasoning_now: str) -> str:
        body = request_body(model, obs, prompt, reasoning_now, max_tokens)
        req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                              "X-Title": "qdojo combat demo"})
        left = max(1.0, timeout - (time.monotonic() - started))
        try:
            with urllib.request.urlopen(req, timeout=left) as resp:
                doc = json.loads(resp.read())
        except Exception as exc:            # whatever the request raised is the provider's failure
            raise provider_error(exc) from None
        usage = doc.get("usage") if isinstance(doc, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        cost = _number(usage.get("cost")) or 0.0
        if not isinstance(doc, dict) or not doc.get("choices"):
            if cost > 0:                    # billed all the same: it counts toward the day's cap
                note(spend.add(cost))
            raise _body_error(doc)
        note(spend.add(cost))
        if breaker is not None:
            note(breaker.success())
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
        choice = doc["choices"][0]
        print(f"{model}: ${cost:.5f} (today ${spend.today:.4f}); tokens in {usage.get('prompt_tokens')}"
              f"{f' ({cached} cached)' if cached else ''}, out {usage.get('completion_tokens')}"
              f", finish {choice.get('finish_reason')}", file=sys.stderr)
        return choice["message"].get("content") or ""

    text = call(reasoning)
    try:
        plan, read = _model_plan(text)
    except planner.PlannerError as exc:
        # An empty or prose-only reply is usually hidden reasoning that used
        # the token budget: one more try with reasoning off, if time allows.
        print(f"unusable reply ({exc}); first 160 chars: {text[:160]!r}", file=sys.stderr)
        if reasoning == "off" or time.monotonic() - started > timeout / 2:
            raise
        text = call("off")
        plan, read = _model_plan(text)
    if read:
        print(f"read: {str(read)[:200]}", file=sys.stderr)
    return legal(obs, plan)


def legal(obs: dict, plan) -> dict:
    """The contract's own plan check, applied before the plan leaves the planner."""
    plan, why = planner.legal_plan(_rules(obs), planner.fighter_state(obs["self"]), plan)
    if why:
        print(f"adjusted: {why}", file=sys.stderr)
    return planner.plan_json(plan)


def decide(obs: dict, model: str, state: Path, daily_usd: float = 1.0, timeout: float = 20.0, prompt: Path = PROMPT,
           reasoning: str = "low", max_tokens: int = 1200, clock=time.time) -> dict:
    """One decision: the model's checked plan, or the fallback with the reason
    on stderr. The planner's own files never stop it (module docstring)."""
    try:
        state.mkdir(parents=True, exist_ok=True)
        _check_writable(state / "spend.json")
    except OSError as exc:              # nowhere to keep the day's spend: no paid request
        return _fallback(obs, f"state directory unusable: {type(exc).__name__}: {str(exc)[:120]}")
    spend, breaker = Spend(state, clock), Breaker(state, clock)
    if spend.today >= daily_usd:
        return _fallback(obs, f"daily cap ${daily_usd:.2f} reached")
    try:
        shut = breaker.admit(timeout + PROBE_MARGIN)
        if shut is None:
            return ask(model, obs, timeout, spend, prompt_for(prompt, obs), reasoning, max_tokens, breaker)
    except ProviderError as exc:        # no completion: the breaker counts it
        try:
            why = breaker.failure(exc)
        except Exception as bad:        # the breaker's own trouble never costs the fallback
            why = f"{exc}; breaker not updated: {type(bad).__name__}: {str(bad)[:120]}"
        return _fallback(obs, why)
    except Exception as exc:            # any other model or parse failure: play the local policy
        return _fallback(obs, f"{type(exc).__name__}: {str(exc)[:160]}")
    return _fallback(obs, shut, quiet=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", required=True, help="OpenRouter model id, e.g. anthropic/claude-sonnet-5")
    p.add_argument("--state", required=True, help="directory for the daily spend record and the circuit breaker")
    p.add_argument("--daily-usd", type=float, default=1.0)
    p.add_argument("--timeout", type=float, default=20.0,
                   help="seconds for the model's answer, counted from this process's start")
    p.add_argument("--prompt", help="system prompt: a path, or a name under prompts/combat "
                                    "(default planner-system.md)")
    p.add_argument("--reasoning", default="low", choices=("none", "off", "minimal", "low", "medium", "high"),
                   help="hidden reasoning effort; none sends no reasoning setting, off disables reasoning")
    p.add_argument("--max-tokens", type=int, default=1200)
    a = p.parse_args()
    obs = json.load(sys.stdin)
    prompt = PROMPT
    if a.prompt:
        prompt = Path(os.path.expanduser(a.prompt))
        if not prompt.is_absolute() and not prompt.exists():
            prompt = PROMPTS / a.prompt
    # What starting Python and the imports took (up to a second on a busy
    # host) comes off the request's time, so a hung provider is reported as a
    # timeout, which the breaker counts, before the arena's budget kills us.
    timeout = max(1.0, a.timeout - (time.monotonic() - STARTED))
    out = decide(obs, a.model, Path(os.path.expanduser(a.state)), a.daily_usd, timeout, prompt, a.reasoning,
                 a.max_tokens)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
