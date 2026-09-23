"""Series bookkeeping and cup brackets (docs/competition.md §4-5). Pure.

A series is a sequence of fresh three-round fights; wins accumulate, draws
add nothing, and a fight cap bounds draw replacements. A cup pairing's tied
series gets one bounded replay (first to one win, at most three fights).
"""
from __future__ import annotations

from dataclasses import dataclass

from .codec import Format

# format -> (wins needed for early victory, maximum fights)
FORMATS = {Format.SINGLE: (1, 1), Format.BO3: (2, 5), Format.BO5: (3, 7)}
REPLAY = (1, 3)


@dataclass
class Series:
    need: int
    cap: int
    wins_a: int = 0
    wins_b: int = 0
    fights: int = 0

    @classmethod
    def of(cls, fmt: Format) -> "Series":
        need, cap = FORMATS[Format(fmt)]
        return cls(need, cap)

    @classmethod
    def replay(cls) -> "Series":
        return cls(*REPLAY)

    def record(self, winner: str | None):
        if self.done:
            raise ValueError("series already decided")
        self.fights += 1
        if winner == "A":
            self.wins_a += 1
        elif winner == "B":
            self.wins_b += 1

    @property
    def done(self) -> bool:
        return self.wins_a >= self.need or self.wins_b >= self.need or self.fights >= self.cap

    @property
    def winner(self) -> str | None:
        """Early threshold, else more wins at the cap; equal wins is a series draw."""
        if not self.done or self.wins_a == self.wins_b:
            return None
        return "A" if self.wins_a > self.wins_b else "B"


def seed_positions(size: int) -> list[int]:
    """Standard bracket order; for eight: [1,8,4,5,2,7,3,6]."""
    if size < 2 or size & (size - 1):
        raise ValueError("bracket size is a power of two >= 2")
    positions = [1, 2]
    while len(positions) < size:
        m = 2 * len(positions) + 1
        positions = [x for seed in positions for x in (seed, m - seed)]
    return positions


def bracket(entrants: list[tuple[int, bytes]]) -> list[bytes | None]:
    """Entrants as (lifetime_rating, fighter_id): rating descending, then ID
    ascending. Returns slot order; None is a bye. No randomness."""
    ordered = sorted(entrants, key=lambda e: (-e[0], e[1]))
    size = 1
    while size < len(ordered):
        size *= 2
    size = max(size, 2)
    return [ordered[s - 1][1] if s <= len(ordered) else None for s in seed_positions(size)]
