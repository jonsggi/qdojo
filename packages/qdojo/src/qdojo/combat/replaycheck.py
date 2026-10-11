"""Verify an arena replay (an export's fights/<id>/replay.json) without trusting it.

The Python twin of the site's verifier (apps/web/combat/logic.js verifyReplay
and replayMismatches, docs/api.md §4 checks 1, 3 and 4): the ruleset digest is
a packaged one and agrees with the fight context; the context bytes hash to
the context digest and name the replay's network, contract, fight and
fighters; every round-start digest and both commitments are recomputed from
the revealed plan bytes and salts; every round is re-resolved from those plans
and must reproduce each recorded state, trace and unplayed suffix; and the
recorded outcome, result winner and final state must be the replayed ones. A
forfeit, double fault or void is decided by the protocol (a missed deadline,
a service gap), not by the plans: the revealed rounds must not have ended the
fight and its forfeit round must be the replayed one, but the result itself
is reported as claimed. Chain inclusion (check 2) cannot be established from
a same-source export, and is not claimed.
"""
from __future__ import annotations

import http.client
import json
import threading
import urllib.request
from pathlib import Path

from ..hashing import sha256
from . import codec
from .engine import new_fight, resolve_round
from .rules import RulesetError, by_digest
from .training import ReplayMismatch          # one class for both verifiers, practice and arena
from .types import Plan, PlanError, StateError

CONTEXT_LEN = 526            # docs/protocol.md §2: 254 bytes of terms + two 136-byte participants
_PARTICIPANT = 136
TIMEOUTS = ("FORFEIT", "DOUBLE_FAULT", "VOID")     # results no plan re-derives (logic.js isForfeit)
MAX_BYTES = 2 << 20          # a downloaded replay; a three-round fight is under 40 KB
DEADLINE_S = 30.0            # the whole download: urlopen's timeout bounds each read, not the sum
_MISSING = object()


def load(source: str) -> dict:
    """A replay from a path or an http(s) URL; OSError or ValueError if it
    cannot be read. A download is refused past MAX_BYTES or DEADLINE_S
    seconds: a server that sends a byte at a time would otherwise hold the
    command for as long as it likes."""
    if source.startswith(("http://", "https://")):
        return json.loads(_download(source).decode("utf-8"))
    return json.loads(Path(source).read_text(encoding="utf-8"))


def _download(url: str) -> bytes:
    got: dict = {}

    def fetch():
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "qdojo-cli"})
            with urllib.request.urlopen(req, timeout=20) as r:      # noqa: S310 (scheme checked by load)
                got["body"] = r.read(MAX_BYTES + 1)
        except http.client.HTTPException as exc:                    # a garbled or truncated response
            got["error"] = OSError(f"{type(exc).__name__}: {exc}")
        except Exception as exc:                                     # noqa: BLE001 (raised below)
            got["error"] = exc

    # urlopen cannot be interrupted, so it runs in a daemon thread that is
    # abandoned at the deadline; the command exits soon after.
    t = threading.Thread(target=fetch, name="replay-download", daemon=True)
    t.start()
    t.join(DEADLINE_S)
    if t.is_alive():
        raise TimeoutError(f"no complete response within {DEADLINE_S:g} s")
    if "error" in got:
        raise got["error"]
    if len(got["body"]) > MAX_BYTES:
        raise ValueError(f"the response is larger than {MAX_BYTES} bytes, which no replay is")
    return got["body"]


def is_arena(replay) -> bool:
    """Only local practice (train --out: mode "practice", no context bytes) takes
    the practice verifier. Every other document is checked as an arena replay,
    where one without context bytes fails, as it does on the site."""
    return not (isinstance(replay, dict) and replay.get("mode") == "practice" and "context_bytes" not in replay)


def _hex(value, n: int, what: str) -> bytes:
    try:
        raw = bytes.fromhex(str(value))
    except ValueError:
        raise ReplayMismatch(f"{what} is not hex") from None
    if len(raw) != n:
        raise ReplayMismatch(f"{what} is not {n} bytes")
    return raw


def _participant(raw: bytes) -> dict:
    return {"fighter_id": raw[0:32].hex(), "owner": raw[32:64].hex(), "operator": raw[64:96].hex(),
            "auth_version": int.from_bytes(raw[96:100], "little")}


def _object(replay: dict, key: str) -> dict | None:
    value = replay.get(key)
    if value is not None and not isinstance(value, dict):
        raise ReplayMismatch(f"{key} is neither an object nor null")
    return value


def _timeout(result: dict | None, outcome: dict | None) -> str | None:
    """logic.js isForfeit: the timeout a result record (and its outcome) names, if any."""
    if result is None:
        return None
    for claim in (result.get("kind"), result.get("result"), (outcome or {}).get("result")):
        if claim in TIMEOUTS:
            return claim
    return None


def _truthy(value) -> bool:
    """JavaScript truthiness of a JSON value, as logic.js reads a claim."""
    return value not in (None, False, 0, "")


def verify_arena_replay(replay: dict) -> dict:
    """Raises ReplayMismatch on the first failed check, a malformed document
    included. Returns the checks, the ruleset, the outcome the engine
    re-derived (None while the fight is open and after a forfeit, double fault
    or void) and, for those three, the result the export claims
    ({"result", "winner"}, else None)."""
    try:
        return _verify(replay)
    except ReplayMismatch:
        raise
    except (KeyError, IndexError, TypeError, AttributeError, ValueError, RecursionError) as exc:
        raise ReplayMismatch(f"malformed replay: {type(exc).__name__} {exc}") from None


def _verify(replay: dict) -> dict:
    if not isinstance(replay, dict) or replay.get("schema") != "qdojo.combat.replay.v1":
        raise ReplayMismatch("not a qdojo.combat.replay.v1 document")
    if "context_bytes" not in replay:
        raise ReplayMismatch("no context_bytes, which every arena replay carries (only a practice replay, mode "
                             "practice, has none)")
    checks = []
    ctx = _hex(replay["context_bytes"], CONTEXT_LEN, "context_bytes")
    # 1. the ruleset: packaged, and the same in the replay and the committed context.
    try:
        rules = by_digest(str(replay.get("ruleset_digest")))
    except RulesetError:
        raise ReplayMismatch("replay names a ruleset this package does not know; update qdojo") from None
    if ctx[102:134].hex() != rules.digest.hex():
        raise ReplayMismatch("the fight context commits to a different ruleset than the replay names")
    checks.append(f"PASS ruleset {rules.semantic_version} {rules.digest.hex()} (replay and fight context)")
    # 3. context digest, identities, round-start digests and commitments.
    ctx_digest = sha256(codec.TAG_CONTEXT, ctx)
    if ctx_digest.hex() != replay.get("context_digest"):
        raise ReplayMismatch("context_bytes do not hash to context_digest")
    fight_id = int.from_bytes(ctx[72:80], "little")
    if (ctx[0:32].hex(), ctx[32:64].hex(), str(fight_id)) != (replay.get("network_id"), replay.get("contract_id"),
                                                              str(replay.get("fight_id"))):
        raise ReplayMismatch("the fight context names another network, contract or fight")
    parts = {"A": _participant(ctx[254:254 + _PARTICIPANT]), "B": _participant(ctx[254 + _PARTICIPANT:])}
    for s in "AB":
        claimed = (replay.get("fighters") or {}).get(s) or {}
        if any(claimed.get(k) != parts[s][k] for k in ("fighter_id", "operator", "auth_version")):
            raise ReplayMismatch(f"fighter {s} in the replay differs from the committed context")
    checks.append(f"PASS context digest {ctx_digest.hex()[:16]} names network, contract, fight {fight_id} and both fighters")
    state = new_fight(rules)
    rounds = replay.get("rounds") or []
    for i, entry in enumerate(rounds):
        if state.outcome is not None:
            raise ReplayMismatch(f"round {i} recorded after the fight ended")
        if entry.get("round_index") != state.round_index:
            raise ReplayMismatch(f"round {i} has round_index {entry.get('round_index')!r}")
        rsd = codec.round_state_digest(ctx_digest, state.round_index, state.a, state.b)
        if rsd.hex() != entry.get("round_state_digest"):
            raise ReplayMismatch(f"round {i}: round_state_digest differs from the re-derived start state")
        plans = {}
        for s in "AB":
            raw = _hex(entry["plan_bytes"][s], 7, f"round {i} {s} plan_bytes")
            try:
                plan = codec.decode_plan(raw)
            except codec.CodecError as exc:
                raise ReplayMismatch(f"round {i} {s}: {exc}") from None
            try:
                shown = entry["plans"][s]
                same = Plan.of(shown["actions"], shown["power_slot"]) == plan
            except (PlanError, KeyError, TypeError):
                same = False
            if not same:
                raise ReplayMismatch(f"round {i} {s}: displayed plan differs from the committed plan bytes")
            got = codec.commitment(network_id=ctx[0:32], contract_id=ctx[32:64], fight_id=fight_id,
                                   round_index=state.round_index, context_digest=ctx_digest, round_state_digest=rsd,
                                   fighter_id=bytes.fromhex(parts[s]["fighter_id"]),
                                   operator=bytes.fromhex(parts[s]["operator"]),
                                   auth_version=parts[s]["auth_version"],
                                   salt=_hex(entry["salts"][s], 32, f"round {i} {s} salt"), plan=plan)
            if got.hex() != entry["commitments"][s]:
                raise ReplayMismatch(f"round {i} {s}: plan and salt do not open the commitment")
            plans[s] = plan
        # 4. independent replay of the round.
        try:
            res = resolve_round(rules, state, plans["A"], plans["B"])
        except (PlanError, StateError) as exc:
            raise ReplayMismatch(f"round {i}: the engine refuses the revealed plans ({exc})") from None
        recomputed = res.to_json()
        for key in ("start", "executed_beats", "beats", "break_recovery", "end"):
            if recomputed[key] != entry.get(key):
                raise ReplayMismatch(f"round {i}: recorded {key} differs from the re-derived one")
        unplayed = entry.get("unexecuted") or {}
        for s in "AB":
            if (unplayed.get(s) or []) != [a.name for a in plans[s].actions[res.executed:]]:
                raise ReplayMismatch(f"round {i} {s}: recorded unexecuted suffix differs from the re-derived one")
        state = res.end
    n = len(rounds)
    checks.append(f"PASS {n} round-start digest(s) and {2 * n} commitment(s) recomputed from plan bytes and salts"
                  if n else "UNAVAILABLE commitments: no plan was revealed, so there is none to open")
    # 4, continued: what the export says happened, against the replayed fight.
    result, outcome, final = (_object(replay, k) for k in ("result", "outcome", "final"))
    mine = state.outcome.to_json() if state.outcome is not None else None
    timeout = _timeout(result, outcome)
    claim = None
    if timeout:
        if mine is not None:
            raise ReplayMismatch(f"the export records a {timeout}, but the revealed rounds already ended the fight "
                                 f"by {mine['result']}")
        if replay.get("forfeit_round") is not None and replay["forfeit_round"] != state.round_index:
            # null is "not recorded": the exporter writes it for a void (export.py)
            raise ReplayMismatch(f"forfeit_round differs from the replayed round ({state.round_index})")
        if result.get("winner") not in ("A", "B", None):
            raise ReplayMismatch(f"the {timeout} record names no fighter slot as winner")
        claim = {"result": timeout, "winner": result.get("winner")}
    elif outcome is None and not (result is not None and _truthy(result.get("kind"))):
        if mine is not None:
            raise ReplayMismatch(f"the revealed rounds already ended the fight by {mine['result']}, but the export "
                                 f"shows it in progress")
    else:
        if mine is None:
            raise ReplayMismatch("the export claims a result, but the revealed rounds do not end the fight")
        o = outcome or {}
        if (o.get("winner", _MISSING), o.get("result", _MISSING)) != (mine["winner"], mine["result"]):
            raise ReplayMismatch(f"recorded outcome differs from the re-derived one ({mine['result']}, "
                                 f"winner {mine['winner']})")
        if result is not None and "winner" in result and result["winner"] != mine["winner"]:
            raise ReplayMismatch("the result record names a different winner than the replayed one")
    if final is not None and (n or timeout):
        if final.get("A") != state.a.to_json() or final.get("B") != state.b.to_json():
            raise ReplayMismatch("recorded final state differs from the replayed one")
    if not n:
        checks.append("UNAVAILABLE independent replay: no round was revealed"
                      + (f" before the {timeout}" if timeout else " yet") + ", so there is nothing to replay")
    elif timeout:
        checks.append(f"PASS independent replay of {n} round(s) reproduces every state and trace, and they leave the "
                      f"fight open: the {timeout} is decided by the protocol, not replayed")
    elif mine is not None:
        checks.append(f"PASS independent replay of {n} round(s) reproduces every state, trace and the outcome "
                      f"({mine['result']})")
    else:
        checks.append(f"PASS independent replay of {n} round(s) reproduces every state and trace (no result yet)")
    checks.append("UNAVAILABLE chain inclusion: a same-source export cannot prove it (docs/api.md §4)")
    return {"checks": checks, "outcome": mine, "claimed": claim, "rules": rules.semantic_version}
