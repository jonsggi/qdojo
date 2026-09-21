"""The entry fee as a published function of published data.

Per belt, the next fee is retargeted from the occupancy of the last few
settled or void rounds at that belt (docs/spec.md §5). Everything here is
pure and reads only what history.json publishes, so the house and a bot
compute the same number (docs/api.md, "The entry fee").
"""
import math
from dataclasses import dataclass, field

COUNTED_STATES = ("settled", "void")   # rounds that retarget; open rounds and failed publishes do not


@dataclass(frozen=True)
class FeePolicy:
    alpha: float = 0.5        # fee' = fee * (occ / tgt) ** alpha
    window: int = 8           # K: settled or void rounds at the belt that count
    headroom: int = 2         # tgt = min_players + headroom
    clamp: float = 1.5        # one retarget moves the fee by at most this factor either way
    floor: int = 100          # absolute floor in QU
    start: int = 1000         # the fee at a belt with no history yet
    cap: int = 0              # an absolute ceiling in QU; 0 = none. The only ceiling when there is no rake
    floors: dict = field(default_factory=dict)   # per-belt floor, overriding `floor`

    def floor_for(self, belt: str) -> int:
        return int(self.floors.get(belt, self.floor))

    def public(self) -> dict:
        return {"mode": "auto", "alpha": self.alpha, "window": self.window, "headroom": self.headroom,
                "clamp": self.clamp, "floor": self.floor, "start": self.start, "cap": self.cap,
                "floors": dict(self.floors)}


def f_star(seed_cap: int, tgt: int, rake_bps: int) -> float | None:
    """The fair-game fee: what the average fighter (share 1/n of the winners'
    pot) breaks even at on the seed alone, f* = seed_cap / (n * rho). None
    when there is no rake: then every fee is +EV on average and there is no
    ceiling. The carry is deliberately not in it: it is last round's luck,
    and a ceiling that jumps after every no-winner round makes the fee hunt
    (docs/model.md, the entry-fee section)."""
    if rake_bps <= 0 or tgt <= 0:
        return None
    return seed_cap / (tgt * rake_bps / 10000)


def _sig(x: float, sig: int, how: str) -> int:
    """x to `sig` significant figures as an integer; `how` is nearest (half
    up), down or up. Below 10**(sig-1) every integer already has that many
    figures, so only the integer rounding applies."""
    if x <= 0:
        return 0
    f = {"nearest": lambda v: math.floor(v + 0.5), "down": math.floor, "up": math.ceil}[how]
    e = math.floor(math.log10(x)) - (sig - 1)
    if e <= 0:
        return int(f(x))
    q = 10 ** e
    return int(f(x / q) * q)


def round_fee(x: float, lo: int, hi: float | None, sig: int = 3) -> int:
    """Three significant figures, kept inside [lo, hi]: the nearest first;
    if that crosses a bound, the neighbour on the right side of it; if the
    bounds are narrower than the grid, the bound itself. Never below 1 QU."""
    r = _sig(x, sig, "nearest")
    if hi is not None and r > hi:
        r = _sig(x, sig, "down")
    if r < lo:
        r = _sig(x, sig, "up")
    if hi is not None and r > hi:
        r = int(math.floor(hi))
    return max(1, int(r))


def rows_at(rows, belt: str, window: int) -> list:
    """The last `window` settled or void rounds at `belt`, oldest first.
    `rows` are history.json round objects (or anything with round_id, belt,
    state, entrants, entry_fee); any belt, any order."""
    rs = [r for r in rows if (r.get("belt") or "") == belt and r.get("state") in COUNTED_STATES]
    rs.sort(key=lambda r: r["round_id"])
    return rs[-window:] if window > 0 else rs


def last_fee(rows, belt: str, default: int) -> int:
    rs = rows_at(rows, belt, 1)
    return int(rs[-1]["entry_fee"]) if rs else int(default)


def next_fee(rows, belt: str, policy: FeePolicy, min_players: int, seed_cap: int, rake_bps: int) -> dict:
    """The fee the next round at `belt` charges, and every input it was
    derived from, so the derivation can be published and replayed.

        occ  = mean entrants over the last K settled or void rounds at the belt
        tgt  = min_players + headroom
        fee' = fee * (occ / tgt) ** alpha, held within fee / clamp .. fee * clamp
        fee  = max(floor_b, min(fee', ceiling)), then three significant figures

    With no history at the belt the fee is `start`, bounded the same way.
    The ceiling is the lower of f* and the operator's cap, whichever exist.
    A floor above f* means the seed is too small to make even the floor a
    fair game: the floor wins, f* is reported but not applied, and only the
    cap bounds the fee from above."""
    tgt = max(1, int(min_players) + int(policy.headroom))
    floor_b = policy.floor_for(belt)
    fs = f_star(seed_cap, tgt, rake_bps)
    used = rows_at(rows, belt, policy.window)
    if used:
        from_fee = int(used[-1]["entry_fee"])
        occ = sum(int(r.get("entrants") or 0) for r in used) / len(used)
        raw = from_fee * (occ / tgt) ** policy.alpha
        raw = min(max(raw, from_fee / policy.clamp), from_fee * policy.clamp)
    else:
        from_fee, occ, raw = int(policy.start), None, float(policy.start)
    bounds = [b for b in (fs if (fs is not None and fs >= floor_b) else None, policy.cap or None) if b is not None]
    ceiling = min(bounds) if bounds else None
    if ceiling is not None and ceiling < floor_b:
        ceiling = float(floor_b)      # a cap below the floor: the floor wins, the fee is the floor
    bounded = max(float(floor_b), raw if ceiling is None else min(raw, ceiling))
    fee = round_fee(bounded, floor_b, ceiling)
    return {**policy.public(), "fee": fee, "from_fee": from_fee,
            "occ": None if occ is None else round(occ, 3), "tgt": tgt,
            "f_star": None if fs is None else round(fs, 1), "floor_b": floor_b,
            "rounds": [int(r["round_id"]) for r in used],
            "seed_cap": int(seed_cap), "rake_bps": int(rake_bps)}


def parse_floor(text: str, default: int = 100) -> tuple[int, dict]:
    """'100' -> (100, {}); 'white=100,blue=500' -> (default, {...}); both mix."""
    floor, floors = int(default), {}
    for item in (text or "").split(","):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            k, v = item.split("=", 1)
            floors[k.strip()] = int(v)
        else:
            floor = int(item)
    return floor, floors
