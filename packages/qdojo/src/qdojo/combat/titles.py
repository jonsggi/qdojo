"""Title belts (docs/competition.md §7): display honours from finished fights.

Three belts, none of which changes a stat, a stake or access:

- THE SCRAP HEAP BELT, the lineal title. The winner of the arena's first
  ranked fight decided in combat holds it first. It passes only when its
  holder LOSES a ranked fight by combat result (KO or decision) to the
  winner. A draw is a successful defence; a forfeit, double fault or void
  moves nothing (belts are won in combat, not on the clock). A ranked fight
  involving the holder is a title fight.
- THE MONTAGE BELT: the champion of the most recent finished season that
  crowned one (contract.season_standings, evaluated at the season's closeout
  tick with the arena's qualification rule).
- THE BOTTLE CAP BELT: the champion of the highest-numbered completed cup.

The state is a plain dict folded from finished fights in a fixed order,
(result tick, fight ID), so it is a pure function of the journal. The arena
compacts finished fights out of memory (store.compact), so the fold runs
before every compaction and the state lives in store.History, which a
snapshot pickles and a full replay rebuilds at the same ticks. Readers (the
exporter, the read model) fold the fights not yet in the state on a cheap
copy: `current(contract)`.

Only fights whose result tick is before the contract's current tick are
folded into the persistent state: every later fight ends at a later tick,
so nothing can ever be folded out of order.
"""
from __future__ import annotations

from bisect import bisect_right

from . import codec
from .ledger import split_purse

LINEAL = {"id": "lineal", "name": "THE SCRAP HEAP BELT"}
SEASON = {"id": "season", "name": "THE MONTAGE BELT"}
CUP = {"id": "cup", "name": "THE BOTTLE CAP BELT"}
RECENT = 64              # title fights remembered in the state (newest last)
PUBLIC_REIGNS = 100      # lineal reigns published in titles.json (the API has all)
FINAL_CUP = ("COMPLETE", "CANCELLED", "ABORTED")
# The arena compacts (and so checkpoints titles) every live.COMPACT_EVERY
# ticks; the read model's replica checkpoints on the same ticks.
CHECKPOINT_EVERY = 600


def new_state() -> dict:
    return {"v": 1, "floor": 1, "mark": [-1, 0], "reigns": [], "recent": [],
            "seasons": {}, "cup_floor": 0, "cups_seen": [], "cup_wins": {}, "cup_last": None,
            # Career extras that must outlive compaction like the titles:
            # win streaks (fight order) and QU earnings (per settled contest or cup).
            "streaks": {}, "money": {}, "contest_floor": 0, "contests_seen": []}


def _fork(st: dict) -> dict:
    """A copy that folding may change without touching `st` (only the last
    reign, the lists and the small maps are ever mutated)."""
    reigns = list(st["reigns"])
    if reigns:
        reigns[-1] = dict(reigns[-1])
    return {**st, "mark": list(st["mark"]), "reigns": reigns, "recent": list(st["recent"]),
            "seasons": dict(st["seasons"]), "cups_seen": list(st["cups_seen"]), "cup_wins": dict(st["cup_wins"]),
            "streaks": {k: list(v) for k, v in st["streaks"].items()},
            "money": {k: {m: dict(x) if isinstance(x, dict) else x for m, x in v.items()} for k, v in st["money"].items()},
            "contests_seen": list(st["contests_seen"])}


def holder(st: dict) -> str | None:
    r = st["reigns"]
    return r[-1]["holder"] if r and r[-1]["to_fight"] is None else None


def _streak(st: dict, f) -> None:
    """Win streaks over combat results in every mode: a combat win extends
    it, a combat draw or loss ends it; forfeits and no-results leave it."""
    res = f.result
    if res["kind"] != "COMBAT":
        return
    for slot, p in (("A", f.context.participant_a), ("B", f.context.participant_b)):
        cur = st["streaks"].setdefault(p.fighter_id.hex(), [0, 0])
        if res.get("winner") == slot:
            cur[0] += 1
            cur[1] = max(cur[1], cur[0])
        else:
            cur[0] = 0


def _fold_fight(st: dict, f) -> None:
    _streak(st, f)
    if f.context.mode != codec.Mode.RANKED:
        return
    res = f.result
    side = {"A": f.context.participant_a.fighter_id.hex(), "B": f.context.participant_b.fighter_id.hex()}
    kind, tick = res["kind"], res["tick"]
    winner = side.get(res.get("winner")) if res.get("winner") else None
    h = holder(st)
    if h is None:
        if kind == "COMBAT" and winner is not None:
            st["reigns"].append({"holder": winner, "from_tick": tick, "from_fight": f.fight_id, "won_from": None,
                                 "to_tick": None, "to_fight": None, "lost_to": None, "how": None,
                                 "defenses": 0, "wins": 0, "draws": 0, "title_fights": 0})
        return
    if h not in side.values():
        return
    challenger = side["B"] if side["A"] == h else side["A"]
    reign = st["reigns"][-1]
    reign["title_fights"] += 1
    changed = kind == "COMBAT" and winner == challenger
    if kind == "COMBAT" and not changed:
        reign["defenses"] += 1
        reign["wins" if winner == h else "draws"] += 1
    st["recent"].append({"fight_id": f.fight_id, "tick": tick, "holder": h, "challenger": challenger,
                         "kind": kind, "result": res.get("result"), "winner": winner, "changed": changed})
    del st["recent"][:-RECENT]
    if changed:
        reign.update(to_tick=tick, to_fight=f.fight_id, lost_to=challenger, how=res.get("result"))
        st["reigns"].append({"holder": challenger, "from_tick": tick, "from_fight": f.fight_id, "won_from": h,
                             "to_tick": None, "to_fight": None, "lost_to": None, "how": None,
                             "defenses": 0, "wins": 0, "draws": 0, "title_fights": 0})


def _fold_fights(st: dict, c, limit: int | None) -> None:
    """Every finished fight from `floor` on, in (result tick, fight ID) order;
    with `limit`, only those with result tick < limit."""
    top = c.next_id["fight"]
    ready, floor = [], None
    for fid in range(st["floor"], top):
        f = c.fights.get(fid)
        if f is None:
            continue          # compacted: already folded (the fold runs before every compaction)
        done = f.phase == "DONE" and f.result is not None and (limit is None or f.result["tick"] < limit)
        if done:
            ready.append(((f.result["tick"], fid), f))
        elif floor is None:
            floor = fid
    mark = tuple(st["mark"])
    for key, f in sorted(ready, key=lambda x: x[0]):
        if key > mark:
            _fold_fight(st, f)
            mark = key
    st["mark"] = list(mark)
    st["floor"] = floor if floor is not None else top


def _fold_cups(st: dict, c) -> None:
    seen = set(st["cups_seen"])
    for kid in sorted(c.cups):
        k = c.cups[kid]
        if kid <= st["cup_floor"] or kid in seen or k.status not in FINAL_CUP:
            continue
        seen.add(kid)
        if k.status == "COMPLETE" and k.champion is not None:
            _cup_money(st, c, kid, k)
            who = k.champion.hex()
            st["cup_wins"][who] = st["cup_wins"].get(who, 0) + 1
            if st["cup_last"] is None or kid > st["cup_last"]["cup_id"]:
                st["cup_last"] = {"cup_id": kid, "champion": who}
    floor = st["cup_floor"]
    while floor + 1 in seen:
        floor += 1
        seen.discard(floor)
    st["cup_floor"], st["cups_seen"] = floor, sorted(seen)


MODES = ("ranked", "duel", "cup")


def _purse(st: dict, hexid: str) -> dict:
    return st["money"].setdefault(hexid, {m: {"won": 0, "lost": 0, "rake": 0, "wins": 0} for m in MODES}
                                  | {"prize_sponsorship": 0, "biggest": None})


def _gain(st: dict, hexid: str, mode: str, net: int, rake: int, ref: str):
    m = _purse(st, hexid)
    m[mode]["won"] += net
    m[mode]["rake"] += rake
    m[mode]["wins"] += 1
    best = m["biggest"]
    # Ties go to the most recent contest or cup (by ID), whatever the fold order.
    key = (net, ref.split(":")[0], int(ref.split(":")[1]))
    if best is None or key > (best["amount"], best["ref"].split(":")[0], int(best["ref"].split(":")[1])):
        m["biggest"] = {"amount": net, "mode": mode, "ref": ref}


def _fold_contests(st: dict, c) -> None:
    """Ranked and duel stakes, once per settled contest: the winner gains the
    other stake less the rake (ledger.split_purse), the loser loses its
    stake; draws, double faults and voids are refunds."""
    seen = set(st["contests_seen"])
    for cid in sorted(c.contests):
        ct = c.contests[cid]
        if cid <= st["contest_floor"] or cid in seen or ct.status != "DONE" or not ct.result:
            continue
        seen.add(cid)
        if ct.mode not in (codec.Mode.RANKED, codec.Mode.DUEL):
            continue
        winner = ct.result.get("winner")
        if ct.result["kind"] not in ("COMBAT", "FORFEIT") or winner is None:
            continue
        mode = codec.Mode(ct.mode).name.lower()
        credit, rake = split_purse(2 * ct.stake, c.m.fees[ct.fee_profile_id])[:2]
        side = {"A": ct.a.fighter_id.hex(), "B": ct.b.fighter_id.hex()}
        _gain(st, side[winner], mode, credit - ct.stake, rake, f"contest:{cid}")
        _purse(st, side["B" if winner == "A" else "A"])[mode]["lost"] += ct.stake
    floor = st["contest_floor"]
    while floor + 1 in seen:
        floor += 1
        seen.discard(floor)
    st["contest_floor"], st["contests_seen"] = floor, sorted(seen)


def _cup_money(st: dict, c, kid: int, k) -> None:
    """A completed cup: the champion gains the prize (sponsorship and entries
    less the entry rake) less its own entry; every other entrant loses its
    entry. An aborted or cancelled cup refunds everyone."""
    fee = c.m.fees[k.descriptor["fee_profile_id"]]
    entries = {fid.hex(): e.amount for fid, e in k.entries.items()}
    gross = sum(entries.values())
    rake = gross * fee.rake_bps // 10_000
    champ = k.champion.hex()
    prize = k.sponsorship + gross - rake
    _gain(st, champ, "cup", prize - entries.get(champ, 0), rake, f"cup:{kid}")
    _purse(st, champ)["prize_sponsorship"] += k.sponsorship
    for who, amount in entries.items():
        if who != champ:
            _purse(st, who)["cup"]["lost"] += amount


def _fold_seasons(st: dict, c, rule) -> None:
    current = c.m.season(c.tick)
    known = {s for f in c.fighters.values() for s in f.season_stats}
    for s in sorted(known):
        if str(s) in st["seasons"] or (current and s >= current):
            continue
        closes = c.m.season_first_tick(s + 1) + c.m.season_closeout_ticks
        if c.tick < closes:
            continue
        standings = c.season_standings(s, closes, rule)
        st["seasons"][str(s)] = standings["champion"].hex() if standings["champion"] else None


def advance(st: dict, c, rule=None, limit: int | None = None) -> dict:
    """Fold everything finished into `st` (in place) and return it."""
    _fold_fights(st, c, limit)
    _fold_contests(st, c)
    _fold_cups(st, c)
    _fold_seasons(st, c, rule)
    return st


def persistent(c) -> dict:
    """The contract's persistent title state (on store.History), created empty."""
    from .store import history
    h = history(c)
    st = getattr(h, "titles", None)
    if st is None:
        st = h.titles = new_state()
    return st


def checkpoint(c) -> dict:
    """Advance the persistent state up to (not including) the current tick.
    store.compact calls this before it moves finished fights out of memory."""
    from .store import history
    return advance(persistent(c), c, getattr(history(c), "title_rule", None), limit=c.tick)


def current(c, rule=None) -> dict:
    """The title state including every fight finished so far, without
    changing the contract's persistent state."""
    from .store import history
    rule = rule if rule is not None else getattr(history(c), "title_rule", None)
    return advance(_fork(persistent(c)), c, rule)


# ---- queries ---------------------------------------------------------------------

class Lookup:
    """Which reign a finished fight belongs to, by bisection over the reigns."""

    def __init__(self, st: dict):
        self.st = st
        self.keys = [(r["from_tick"], r["from_fight"]) for r in st["reigns"]]
        self.holder = holder(st)

    def reign_at(self, key: tuple, ids: set) -> dict | None:
        reigns = self.st["reigns"]
        i = bisect_right(self.keys, key) - 1
        # The fight that took the belt belongs to the reign it ended, not the one it began.
        while i >= 0 and self.keys[i] == key:
            i -= 1
        if i < 0:
            return None
        r = reigns[i]
        if r["holder"] in ids and (r["to_fight"] is None or key <= (r["to_tick"], r["to_fight"])):
            return r
        return None

    def flags(self, f) -> dict:
        """title_fight: a ranked fight involving the lineal holder at its start.
        A live fight: the holder now (a fighter's exclusive lock means it cannot
        have won or lost the belt elsewhere since the fight began). A finished
        fight: the reign whose interval holds it. new_champion: who took the
        belt in this fight, when it changed hands."""
        if f.context.mode != codec.Mode.RANKED:
            return {"title_fight": False}
        ids = {f.context.participant_a.fighter_id.hex(), f.context.participant_b.fighter_id.hex()}
        if f.phase != "DONE" or not f.result:
            return {"title_fight": self.holder in ids}
        r = self.reign_at((f.result["tick"], f.fight_id), ids)
        out = {"title_fight": r is not None}
        if r is not None and r["to_fight"] == f.fight_id:
            out["new_champion"] = r["lost_to"]
        return out


def reign_doc(r: dict) -> dict:
    return {"holder": r["holder"], "from_tick": str(r["from_tick"]), "from_fight": str(r["from_fight"]),
            "won_from": r["won_from"], "to_tick": None if r["to_tick"] is None else str(r["to_tick"]),
            "to_fight": None if r["to_fight"] is None else str(r["to_fight"]), "lost_to": r["lost_to"],
            "how": r["how"], "defenses": r["defenses"], "wins": r["wins"], "draws": r["draws"],
            "title_fights": r["title_fights"]}


def fighter_titles(st: dict) -> dict:
    """Career honours per fighter (hex -> dict); fighters without any are absent."""
    out: dict = {}

    def me(h):
        return out.setdefault(h, {"lineal_reigns": 0, "lineal_defenses": 0, "best_reign_defenses": 0,
                                  "title_fights": 0, "season_titles": [], "cup_titles": 0, "holds": []})
    for r in st["reigns"]:
        m = me(r["holder"])
        m["lineal_reigns"] += 1
        m["lineal_defenses"] += r["defenses"]
        m["best_reign_defenses"] = max(m["best_reign_defenses"], r["defenses"])
        m["title_fights"] += r["title_fights"]
    for s, who in sorted(st["seasons"].items(), key=lambda x: int(x[0])):
        if who:
            me(who)["season_titles"].append(int(s))
    for who, n in st["cup_wins"].items():
        me(who)["cup_titles"] = n
    h = holder(st)
    if h:
        me(h)["holds"].append("lineal")
    season = season_holder(st)
    if season:
        me(season["champion"])["holds"].append("season")
    if st["cup_last"]:
        me(st["cup_last"]["champion"])["holds"].append("cup")
    return out


def earnings(st: dict, hexid: str) -> dict:
    """What a fighter's fights paid, in fake QU: per mode `won` (net gain in
    won contests or cups, after rake), `lost` (stakes and entry fees lost),
    `net`, `rake` paid on its wins; `won`, `lost`, `net`, `rake` over all
    modes, cup `prize_sponsorship` and the `biggest_win`. Execution fees are
    not per fighter (the arena operator's reserve pays them)."""
    m = st["money"].get(hexid)
    if m is None:
        m = {x: {"won": 0, "lost": 0, "rake": 0, "wins": 0} for x in MODES} | {"prize_sponsorship": 0, "biggest": None}
    out = {x: {"won": str(m[x]["won"]), "lost": str(m[x]["lost"]), "net": str(m[x]["won"] - m[x]["lost"]),
               "rake": str(m[x]["rake"]), "paid_wins": m[x]["wins"]} for x in MODES}
    won, lost, rake = (sum(m[x][k] for x in MODES) for k in ("won", "lost", "rake"))
    b = m["biggest"]
    return {**out, "won": str(won), "lost": str(lost), "net": str(won - lost), "rake": str(rake),
            "prize_sponsorship": str(m["prize_sponsorship"]),
            "biggest_win": ({"amount": str(b["amount"]), "mode": b["mode"], "ref": b["ref"]} if b else None),
            "currency": "fake QU"}


def streak(st: dict, hexid: str) -> dict:
    cur, best = st["streaks"].get(hexid, [0, 0])
    return {"current": cur, "best": best}


def season_holder(st: dict) -> dict | None:
    crowned = [(int(s), who) for s, who in st["seasons"].items() if who]
    if not crowned:
        return None
    s, who = max(crowned)
    return {"season": s, "champion": who}


def public(st: dict, reigns: int | None = PUBLIC_REIGNS) -> dict:
    """The body of titles.json and /api/v1/titles."""
    h = holder(st)
    cur = st["reigns"][-1] if h else None
    hist = st["reigns"] if reigns is None else st["reigns"][-reigns:]
    seasons = sorted(((int(s), who) for s, who in st["seasons"].items()))
    latest_final = seasons[-1][0] if seasons else None
    return {
        "lineal": {**LINEAL, "holder": h, "since_tick": str(cur["from_tick"]) if cur else None,
                   "since_fight": str(cur["from_fight"]) if cur else None,
                   "defenses": cur["defenses"] if cur else 0, "reigns_total": len(st["reigns"]),
                   "history": [reign_doc(r) for r in reversed(hist)],
                   "recent_title_fights": [{**x, "fight_id": str(x["fight_id"]), "tick": str(x["tick"])}
                                           for x in reversed(st["recent"])],
                   "rules": "Ranked fights only. Passes when the holder loses by KO or decision; a draw is a "
                            "defence; a forfeit, double fault or void moves nothing."},
        "season": {**SEASON, **(season_holder(st) or {"season": None, "champion": None}),
                   "latest_final_season": latest_final,
                   "history": [{"season": s, "champion": who} for s, who in reversed(seasons)]},
        "cup": {**CUP, "cup_id": str(st["cup_last"]["cup_id"]) if st["cup_last"] else None,
                "champion": st["cup_last"]["champion"] if st["cup_last"] else None,
                "wins": dict(sorted(st["cup_wins"].items(), key=lambda x: (-x[1], x[0])))},
        "fighters": fighter_titles(st),
        "career": {h: {"earnings": earnings(st, h), "streak": streak(st, h)}
                   for h in sorted(set(st["money"]) | set(st["streaks"]))},
        "folded_through": {"tick": str(st["mark"][0]), "fight": str(st["mark"][1])},
    }
