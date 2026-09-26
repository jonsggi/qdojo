"""Load and freeze a combat ruleset; its digest names the rules a fight used.

The digest is SHA256("qdojo/combat/rules/v1\\0" || canonical JSON), where the
canonical form is sorted keys, no whitespace, ASCII, integers only
(docs/protocol.md §2). A loaded ruleset is checked field by field: an unknown
or missing key is an error, never a default.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from ..hashing import sha256

TAG_RULES = b"qdojo/combat/rules/v1\0"
RULESET_DIR = Path(__file__).resolve().parent / "rulesets"
CANDIDATE_1 = "combat-v1-candidate-1"
CANDIDATE_1_DIGEST = "12085c86a61ffd106430b6690acbd522c5a94f90ed8024585817f4939fe4842c"
# Candidate 2 (docs/combat.md "Candidate 2"): the same engine and action table
# with rebalanced numbers. Candidate 1 stays loadable: journals and replays
# bound to its digest must keep verifying.
CANDIDATE_2 = "combat-v1-candidate-2"
CANDIDATE_2_DIGEST = "c90da811dc1e5275d09c8e09d25d15c548866b9c01907c4f1878ca321b9e4650"
# Every packaged ruleset, by semantic version, with the digest its file must hash to.
KNOWN = {CANDIDATE_1: CANDIDATE_1_DIGEST, CANDIDATE_2: CANDIDATE_2_DIGEST}

_KEYS = {
    "semantic_version", "rounds", "beats_per_round", "initial", "limits",
    "action_names", "submitted_action_ids", "base_costs", "damage",
    "block_streak_cost", "block_strain", "ordinary_recovery", "recover_unhit",
    "recover_hit", "exhausted_recovery", "break_recovery", "opening_damage",
    "power_damage", "power_cost",
}
_ACTION_NAMES = ["JAB", "KICK", "BLOCK", "DUCK", "THROW", "RECOVER", "EXHAUSTED"]


class RulesetError(ValueError):
    """A ruleset artifact that is malformed or not the one it claims to be."""


def canonical(doc: dict) -> bytes:
    text = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return text.encode("ascii")


def digest_of(doc: dict) -> bytes:
    return sha256(TAG_RULES, canonical(doc))


@dataclass(frozen=True)
class Ruleset:
    semantic_version: str
    digest: bytes
    rounds: int
    beats_per_round: int
    initial: tuple[int, int, int, int, int]   # hp, stamina, opening, guard_streak, power_available
    max_hp: int
    max_stamina: int
    max_guard_streak: int
    base_costs: tuple[int, ...]
    damage: tuple[tuple[int, ...], ...]       # damage[attacker][defender], effective actions
    block_streak_cost: int
    block_strain: int
    ordinary_recovery: int
    recover_unhit: int
    recover_hit: int
    exhausted_recovery: int
    break_recovery: int
    opening_damage: int
    power_damage: int
    power_cost: int


def _int(value, where):
    if type(value) is not int or value < 0:
        raise RulesetError(f"{where}: expected a nonnegative integer, got {value!r}")
    return value


def parse(doc: dict) -> Ruleset:
    if not isinstance(doc, dict) or set(doc) != _KEYS:
        raise RulesetError(f"ruleset keys differ: {sorted(set(doc) ^ _KEYS) if isinstance(doc, dict) else doc!r}")
    if doc["action_names"] != _ACTION_NAMES or doc["submitted_action_ids"] != list(range(6)):
        raise RulesetError("action table differs from combat-v1")
    n = len(_ACTION_NAMES)
    costs = doc["base_costs"]
    matrix = doc["damage"]
    if not (isinstance(costs, list) and len(costs) == n):
        raise RulesetError("base_costs must have one entry per action")
    if not (isinstance(matrix, list) and len(matrix) == n and all(isinstance(r, list) and len(r) == n for r in matrix)):
        raise RulesetError("damage must be a 7x7 matrix")
    initial, limits = doc["initial"], doc["limits"]
    if set(initial) != {"hp", "stamina", "opening", "guard_streak", "power_available"}:
        raise RulesetError("initial state keys differ")
    if set(limits) != {"hp", "stamina", "guard_streak"}:
        raise RulesetError("limits keys differ")
    if not isinstance(doc["semantic_version"], str) or not doc["semantic_version"].isascii():
        raise RulesetError("semantic_version must be an ASCII string")
    rules = Ruleset(
        semantic_version=doc["semantic_version"],
        digest=digest_of(doc),
        rounds=_int(doc["rounds"], "rounds"),
        beats_per_round=_int(doc["beats_per_round"], "beats_per_round"),
        initial=tuple(_int(initial[k], "initial." + k)
                      for k in ("hp", "stamina", "opening", "guard_streak", "power_available")),
        max_hp=_int(limits["hp"], "limits.hp"),
        max_stamina=_int(limits["stamina"], "limits.stamina"),
        max_guard_streak=_int(limits["guard_streak"], "limits.guard_streak"),
        base_costs=tuple(_int(c, "base_costs") for c in costs),
        damage=tuple(tuple(_int(c, "damage") for c in row) for row in matrix),
        **{k: _int(doc[k], k) for k in (
            "block_streak_cost", "block_strain", "ordinary_recovery", "recover_unhit",
            "recover_hit", "exhausted_recovery", "break_recovery", "opening_damage",
            "power_damage", "power_cost")},
    )
    # The engine and the byte codec assume these shapes; a ruleset outside them
    # is a new semantic version, not a parameter change.
    if rules.rounds != 3 or rules.beats_per_round != 6:
        raise RulesetError("combat-v1 has three rounds of six beats")
    hp, stamina, opening, guard, power = rules.initial
    if not (0 < hp <= rules.max_hp and stamina <= rules.max_stamina and opening <= 1
            and guard <= rules.max_guard_streak and power <= 1):
        raise RulesetError("initial state is outside the limits")
    if rules.max_hp > 0xFFFF or rules.max_stamina > 0xFFFF or rules.max_guard_streak > 0xFF:
        raise RulesetError("limits must fit the eight-byte state encoding")
    return rules


def load_file(path: Path, expect_digest: str | None = None) -> Ruleset:
    rules = parse(json.loads(Path(path).read_text(encoding="ascii")))
    if expect_digest is not None and rules.digest.hex() != expect_digest:
        raise RulesetError(f"{path}: digest {rules.digest.hex()} is not the expected {expect_digest}")
    return rules


@cache
def by_version(version: str) -> Ruleset:
    """A packaged ruleset by semantic version, refusing to load if its bytes drifted."""
    if version not in KNOWN:
        raise RulesetError(f"unknown ruleset {version!r}; known: {', '.join(KNOWN)}")
    return load_file(RULESET_DIR / f"{version}.json", KNOWN[version])


def by_digest(digest: str | bytes) -> Ruleset:
    """A packaged ruleset by its digest (hex or bytes); how a replay or journal
    bound to a digest finds its rules."""
    hexd = digest.hex() if isinstance(digest, (bytes, bytearray)) else str(digest)
    for version, d in KNOWN.items():
        if d == hexd:
            return by_version(version)
    raise RulesetError(f"no packaged ruleset has digest {hexd}")


def artifact(version: str) -> dict:
    """The packaged JSON document of a ruleset (what an export publishes)."""
    by_version(version)                       # checks the digest
    return json.loads((RULESET_DIR / f"{version}.json").read_text(encoding="ascii"))


def candidate_1() -> Ruleset:
    """The frozen combat-v1 candidate 1, refusing to load if its bytes drifted."""
    return by_version(CANDIDATE_1)


def candidate_2() -> Ruleset:
    """combat-v1 candidate 2: the rebalanced numbers of docs/combat.md "Candidate 2"."""
    return by_version(CANDIDATE_2)
