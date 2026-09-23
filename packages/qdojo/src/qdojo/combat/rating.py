"""Integer combat rating and belts (docs/competition.md §1).

Zero-sum and computed from both OLD ratings. No floats, no stake weighting.
"""
from __future__ import annotations

INITIAL = 1000
FLOOR, CEILING = 0, 3000
PLACEMENT_FIGHTS = 10
WIN, DRAW, LOSS = 2000, 1000, 0

BELTS = ((2100, "black"), (1800, "brown"), (1500, "blue"), (1300, "green"),
         (1100, "orange"), (900, "yellow"), (0, "white"))


def delta(ra: int, rb: int, score_a: int) -> int:
    """Rating moved from B to A (negative moves A to B)."""
    for r in (ra, rb):
        if type(r) is not int or not FLOOR <= r <= CEILING:
            raise ValueError(f"rating {r!r} outside {FLOOR}..{CEILING}")
    if score_a not in (WIN, DRAW, LOSS):
        raise ValueError("score is 2000, 1000 or 0")
    expected = min(1900, max(100, 1000 + 2 * (ra - rb)))
    raw = 32 * (score_a - expected)
    d = (abs(raw) // 2000) * (1 if raw > 0 else -1 if raw < 0 else 0)
    if d > 0:
        d = min(d, rb, CEILING - ra)
    elif d < 0:
        d = -min(-d, ra, CEILING - rb)
    return d


def update(ra: int, rb: int, score_a: int) -> tuple[int, int]:
    d = delta(ra, rb, score_a)
    return ra + d, rb - d


def belt(rating: int, placed: bool) -> str:
    """Display only: provisional fighters show white with their number."""
    if not placed:
        return "white"
    return next(name for floor, name in BELTS if rating >= floor)
