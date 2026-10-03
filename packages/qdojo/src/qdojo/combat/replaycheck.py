"""Verify an arena replay (an export's fights/<id>/replay.json) without trusting it.

The Python twin of the site's verifier (apps/web/combat/logic.js verifyReplay,
docs/api.md §4 checks 1, 3 and 4): the ruleset digest is a packaged one and
agrees with the fight context; the context bytes hash to the context digest
and name the replay's network, contract, fight and fighters; every round-start
digest and both commitments are recomputed from the revealed plan bytes and
salts; every round is re-resolved from those plans and must reproduce each
recorded state and trace and the outcome. Chain inclusion (check 2) cannot be
established from a same-source export, and is not claimed.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from ..hashing import sha256
from . import codec
from .engine import new_fight, resolve_round
from .rules import RulesetError, by_digest
from .types import Plan

CONTEXT_LEN = 526            # docs/protocol.md §2: 254 bytes of terms + two 136-byte participants
_PARTICIPANT = 136


class ReplayMismatch(ValueError):
    pass


def load(source: str) -> dict:
    """A replay from a path or an http(s) URL."""
    if source.startswith(("http://", "https://")):
        req = urllib.request.Request(source, headers={"Accept": "application/json", "User-Agent": "qdojo-cli"})
        with urllib.request.urlopen(req, timeout=20) as r:      # noqa: S310 (scheme checked above)
            return json.loads(r.read().decode("utf-8"))
    return json.loads(Path(source).read_text(encoding="utf-8"))


def is_arena(replay: dict) -> bool:
    return isinstance(replay, dict) and "context_bytes" in replay


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


def verify_arena_replay(replay: dict) -> dict:
    """Raises ReplayMismatch on the first failed check; returns the checks and the outcome."""
    if not is_arena(replay) or replay.get("schema") != "qdojo.combat.replay.v1":
        raise ReplayMismatch("not an arena qdojo.combat.replay.v1 document")
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
    for i, entry in enumerate(replay.get("rounds") or []):
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
            shown = entry["plans"][s]
            if Plan.of(shown["actions"], shown["power_slot"]) != plan:
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
        res = resolve_round(rules, state, plans["A"], plans["B"])
        recomputed = res.to_json()
        for key in ("start", "executed_beats", "beats", "break_recovery", "end"):
            if recomputed[key] != entry.get(key):
                raise ReplayMismatch(f"round {i}: recorded {key} differs from the re-derived one")
        state = res.end
    n = len(replay.get("rounds") or [])
    checks.append(f"PASS {n} round-start digest(s) and {2 * n} commitment(s) recomputed from plan bytes and salts")
    outcome = replay.get("outcome")
    result = (replay.get("result") or {}).get("kind")
    if result == "COMBAT" or (outcome and outcome.get("result") in ("KO", "DOUBLE_KO", "HP", "HP_TIE")):
        if state.outcome is None:
            raise ReplayMismatch("the replay claims a fought result but its rounds do not finish the fight")
        mine = state.outcome.to_json()
        if {"winner": mine["winner"], "result": mine["result"]} != {"winner": outcome.get("winner"),
                                                                    "result": outcome.get("result")}:
            raise ReplayMismatch("recorded outcome differs from the re-derived one")
        checks.append(f"PASS independent replay of {n} round(s) reproduces every state, trace and the outcome "
                      f"({mine['result']})")
    elif outcome is None:
        checks.append(f"PASS independent replay of {n} round(s) reproduces every state and trace (no result yet)")
        mine = None
    else:
        # A forfeit or double fault: a timeout, not something the plans can re-derive.
        checks.append(f"PASS independent replay of {n} round(s); the result {outcome.get('result')} is a protocol "
                      f"timeout, not replayed")
        mine = outcome
    checks.append("UNAVAILABLE chain inclusion: a same-source export cannot prove it (docs/api.md §4)")
    return {"checks": checks, "outcome": mine, "rules": rules.semantic_version}
