"""Ranked matching: window, compatibility and pass order (docs/matchmaking.md §2-3). Pure.

The contract supplies the facts (ownership, locks, cooldowns, pair history,
capacity) through `Facts`; this module decides only which OPEN offers pair,
in which order, within the fixed work bounds.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

BASE_WINDOW = 100
WIDEN_STEP = 50
WIDEN_TICKS = 40
MAX_GAP_RANGE = (100, 200)
PASS_SNAPSHOT = 64
PASS_MATCHES = 4
PAIR_STARTS_PER_EPOCH = 2
PAIR_REMATCH_TICKS = 120


@dataclass
class Offer:
    offer_id: int
    fighter_id: bytes
    owner: bytes
    operator: bytes
    auth_version: int
    payer: bytes
    payout_recipient: bytes
    ruleset_digest: bytes
    timing_profile_id: int
    fee_profile_id: int
    tier_id: int
    amount: int
    rating: int
    max_gap: int
    created_tick: int
    expires_tick: int
    generation: int
    status: str = "OPEN"          # OPEN, MATCHED, CANCELLED, EXPIRED, INVALIDATED
    kind: str = "RANKED"          # RANKED or DUEL
    opponent_id: bytes = b""      # DUEL only
    series_format: int = 0        # DUEL only
    contest_id: int = 0           # set when matched


def window(o: Offer, tick: int) -> int:
    return min(o.max_gap, BASE_WINDOW + WIDEN_STEP * ((tick - o.created_tick) // WIDEN_TICKS))


@dataclass
class Facts:
    """Contract-side answers the predicate needs; each must be cheap and bounded."""
    tick: int
    generation: int
    still_valid: Callable[[Offer], bool]               # ownership/authority/lock rechecked
    is_npc: Callable[[bytes], bool]
    in_cooldown: Callable[[bytes], bool]
    pair_starts: Callable[[bytes, bytes], int]         # this epoch
    pair_last_result: Callable[[bytes, bytes], int | None]
    capacity_left: Callable[[], int]
    pair_starts_per_epoch: int = PAIR_STARTS_PER_EPOCH
    pair_rematch_ticks: int = PAIR_REMATCH_TICKS


def compatible(x: Offer, y: Offer, f: Facts) -> bool:
    t = f.tick
    for o in (x, y):
        if o.status != "OPEN" or t >= o.expires_tick or o.generation != f.generation:
            return False
    if x.fighter_id == y.fighter_id or x.owner == y.owner or x.operator == y.operator:
        return False
    if f.is_npc(x.fighter_id) or f.is_npc(y.fighter_id):
        return False
    if (x.ruleset_digest, x.timing_profile_id, x.fee_profile_id, x.tier_id, x.amount) != \
       (y.ruleset_digest, y.timing_profile_id, y.fee_profile_id, y.tier_id, y.amount):
        return False
    gap = abs(x.rating - y.rating)
    if gap > window(x, t) or gap > window(y, t):
        return False
    if f.pair_starts(x.fighter_id, y.fighter_id) >= f.pair_starts_per_epoch:
        return False
    last = f.pair_last_result(x.fighter_id, y.fighter_id)
    if last is not None and t - last < f.pair_rematch_ticks:
        return False
    if f.in_cooldown(x.fighter_id) or f.in_cooldown(y.fighter_id):
        return False
    return f.capacity_left() > 0


def matching_pass(offers: list[Offer], f: Facts, on_invalid: Callable[[Offer], None],
                  on_match: Callable[[Offer, Offer], None]) -> tuple[int, int]:
    """One bounded pass. Returns (matches, comparisons).

    Offers are snapshotted by increasing offer_id; at most 64 are revalidated;
    each earlier offer takes the first compatible later one; four matches end
    the pass. An unmatched older offer never blocks a younger pair.
    """
    snapshot = sorted((o for o in offers if o.status == "OPEN" and o.kind == "RANKED"),
                      key=lambda o: o.offer_id)[:PASS_SNAPSHOT]
    live = []
    for o in snapshot:
        if f.tick >= o.expires_tick or o.generation != f.generation or not f.still_valid(o):
            on_invalid(o)
        else:
            live.append(o)
    if len(live) < 2:
        return 0, 0
    matched, comparisons, taken = 0, 0, set()
    for i, x in enumerate(live):
        if matched >= PASS_MATCHES:
            break
        if x.offer_id in taken:
            continue
        for y in live[i + 1:]:
            if y.offer_id in taken:
                continue
            comparisons += 1
            if compatible(x, y, f):
                taken.update((x.offer_id, y.offer_id))
                on_match(x, y)
                matched += 1
                break
    return matched, comparisons
