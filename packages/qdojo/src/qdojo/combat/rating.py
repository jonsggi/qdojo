"""Integer combat rating and belts (docs/competition.md §1).

Zero-sum and computed from both OLD ratings. No floats, no stake weighting.
"""
from __future__ import annotations

INITIAL = 1000
FLOOR, CEILING = 0, 3000
PLACEMENT_FIGHTS = 10
WIN, DRAW, LOSS = 2000, 1000, 0

# The belt ladder (competition.md §1): display only, derived from lifetime
# rating. Colour belts are 160 points wide, each split into four steps shown
# as 0-3 stripes (one per 40 points); white's stripes count from 480. Black
# belt is 1st dan at 1600 and gains a dan every 60 points to 5th dan at 1840;
# red (grandmaster) starts at 1900. Provisional fighters show white.
BELTS = ((1900, "red"), (1600, "black"), (1440, "brown"), (1280, "purple"), (1120, "blue"),
         (960, "green"), (800, "orange"), (640, "yellow"), (0, "white"))
BAND, STRIPE = 160, 40
BLACK, DAN_STEP, DANS = 1600, 60, 5
RED = 1900
COLOURS = ("white", "yellow", "orange", "green", "blue", "purple", "brown")


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


def belt_info(rating: int, placed: bool) -> dict:
    """The belt as published: `belt` (colour name, backward compatible),
    `belt_rank` (0 white .. 6 brown, 7..11 black 1st..5th dan, 12 red),
    `belt_stripes` (0-3 within a colour belt, else 0) and `dan` (1-5 on a
    black belt, else None). Display only, like `belt`."""
    name = belt(rating, placed)
    stripes, dan = 0, None
    if name in COLOURS:
        rank = COLOURS.index(name)
        floor = next(f for f, n in BELTS if n == name)
        if name == "white":
            floor = BELTS[-2][0] - BAND          # white's stripes cover its top 160 points
        stripes = 0 if not placed else max(0, min(3, (rating - floor) // STRIPE))
    elif name == "black":
        dan = min(DANS, 1 + (rating - BLACK) // DAN_STEP)
        rank = len(COLOURS) + dan - 1
    else:
        rank = len(COLOURS) + DANS
    return {"belt": name, "belt_rank": rank, "belt_stripes": stripes, "dan": dan}
