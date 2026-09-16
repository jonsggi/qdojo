"""The belt ladder: a rank per identity that moves with results and gates
which tables an identity may sit at. Pure rules; the house persists the
state and publishes every change in the settlement so anyone can replay it.

Rules (docs/spec.md §6):
- Ranks: white 0, yellow 1, orange 2, green 3, blue 4. Everyone starts white.
- You may enter a round at your belt or above, never below. Sitting down at
  a table below your belt is refused and refunded ("outranked").
- Results at YOUR belt move points: winner +2, solved +1, any failure -1.
  Reach +3 and you are promoted one belt (points reset); reach -3 and you
  are demoted one belt (points reset).
- Results ABOVE your belt: a win promotes you straight to that belt, a solve
  gives +1, a failure costs nothing. Ambition is not punished.
- A sensei (sitting BELOW your belt, where the round allows it) moves no
  points at all, and can win back at most its own stake.
"""
from dataclasses import dataclass

BELTS = ("white", "yellow", "orange", "green", "blue")
RANKS = {b: i for i, b in enumerate(BELTS)}
PROMOTE_AT = 3
DEMOTE_AT = -3
FAILURES = ("wrong", "no_reveal", "no_commit", "bad_reveal")


def rank_of(state: dict, identity: str) -> int:
    return int((state.get(identity) or {}).get("rank", 0))


def belt_name(rank: int) -> str:
    return BELTS[max(0, min(rank, len(BELTS) - 1))]


def may_enter(state: dict, identity: str, riddle_rank: int) -> bool:
    return rank_of(state, identity) <= riddle_rank


@dataclass(frozen=True)
class Change:
    identity: str
    before: int
    after: int
    points: int
    reason: str


def apply_settlement(state: dict, riddle_rank: int, entries) -> list[Change]:
    """Mutates `state` ({identity: {rank, points}}) with one round's verdicts.
    `entries` is any iterable of objects/dicts with identity and verdict."""
    changes = []
    for e in entries:
        idn = e["identity"] if isinstance(e, dict) else e.identity
        verdict = e["verdict"] if isinstance(e, dict) else e.verdict
        if (e.get("sensei") if isinstance(e, dict) else getattr(e, "sensei", False)):
            continue   # sat below its belt: teaches, does not climb or fall
        cur = state.setdefault(idn, {"rank": 0, "points": 0})
        before, above = cur["rank"], riddle_rank > cur["rank"]
        if verdict == "winner":
            if above:
                cur["rank"], cur["points"] = riddle_rank, 0
                changes.append(Change(idn, before, cur["rank"], 0, "won above belt"))
                continue
            cur["points"] += 2
        elif verdict == "solved":
            cur["points"] += 1
        elif verdict in FAILURES:
            if above:
                continue
            cur["points"] -= 1
        else:
            continue  # refunds, outranked, late: not a fight
        if cur["points"] >= PROMOTE_AT and cur["rank"] < len(BELTS) - 1:
            cur["rank"], cur["points"] = cur["rank"] + 1, 0
            changes.append(Change(idn, before, cur["rank"], 0, "promoted"))
        elif cur["points"] >= PROMOTE_AT:
            cur["points"] = PROMOTE_AT  # already at the top: hold
        elif cur["points"] <= DEMOTE_AT and cur["rank"] > 0:
            cur["rank"], cur["points"] = cur["rank"] - 1, 0
            changes.append(Change(idn, before, cur["rank"], 0, "demoted"))
        elif cur["points"] <= DEMOTE_AT:
            cur["points"] = DEMOTE_AT   # white belt cannot fall further
    return changes


def public(state: dict) -> dict:
    return {idn: {"rank": v["rank"], "belt": belt_name(v["rank"]), "points": v["points"]} for idn, v in state.items()}
