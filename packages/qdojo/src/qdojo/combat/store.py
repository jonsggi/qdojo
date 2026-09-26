"""Durable contract state by input journal (event sourcing).

The reference contract is deterministic, so its state is exactly the replay
of its confirmed inputs: calls (invocator, 512-byte frame, attached QU),
tick boundaries, asset-owner changes and recipients whose transfers fail.
A journal is JSON lines, appended and fsynced per record; a torn final line
is dropped on load. `replay` rebuilds the contract and checks that the
recorded event digest matches, so a journal from another ruleset, manifest
or build cannot be silently loaded.

Riddle-era state (rounds.json, observed.jsonl) is refused outright.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .contract import CombatContract, Manifest

SCHEMA = "qdojo.combat.journal.v1"
LEGACY_MARKERS = ("rounds.json", "observed.jsonl", "secret.json")


class StoreError(RuntimeError):
    pass


def refuse_legacy(directory: Path):
    for name in LEGACY_MARKERS:
        if (Path(directory) / name).exists():
            raise StoreError(f"{directory} holds riddle-era state ({name}); combat never loads it")


def header(manifest: Manifest) -> dict:
    """Every manifest value, so an independent implementation can replay the journal."""
    m = manifest
    return {"schema": SCHEMA, "network_id": m.network_id.hex(), "contract_id": m.contract_id.hex(),
            "ruleset_digest": m.ruleset.digest.hex(), "admin": m.admin.hex(),
            "timing": {str(k): list(v) for k, v in m.timing.items()},
            "fees": {str(k): {"rake_bps": f.rake_bps, "house_bps": f.house_bps, "dev_bps": f.dev_bps,
                              "share_bps": f.share_bps, "house": f.house.hex(), "dev": f.dev.hex(),
                              "share": f.share.hex()} for k, f in m.fees.items()},
            "tiers": {str(k): v for k, v in m.tiers.items()},
            **{k: getattr(m, k) for k in (
                "genesis_tick", "genesis_epoch", "ticks_per_epoch", "season_start_epoch", "season_epochs",
                "season_closeout_ticks", "max_fighters", "max_accounts", "max_offers", "max_fights", "max_cups",
                "max_cup_entrants", "event_ring", "match_interval", "cooldown_ticks", "faults_per_epoch",
                "pair_starts_per_epoch", "pair_rematch_ticks")},
            "offer_lifetime": list(m.offer_lifetime)}


def write(path: Path, manifest: Manifest, journal: list, final_event_digest: bytes | None = None):
    """Write a whole journal atomically (tmp + rename)."""
    path = Path(path)
    refuse_legacy(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(header(manifest)) + "\n")
        for rec in journal:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")
        if final_event_digest is not None:
            f.write(json.dumps({"k": "digest", "event_digest": final_event_digest.hex()}) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load(path: Path) -> tuple[dict, list]:
    lines = Path(path).read_text(encoding="utf-8").split("\n")
    head = json.loads(lines[0])
    if head.get("schema") != SCHEMA:
        raise StoreError("not a combat journal")
    records = []
    for i, line in enumerate(lines[1:], 1):
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            if i == len(lines) - 1 or all(not x for x in lines[i + 1:]):
                break          # torn tail from a crash mid-append
            raise StoreError(f"corrupt journal line {i}") from None
    return head, records


def replay(manifest: Manifest, head: dict, records: list) -> CombatContract:
    """Rebuild the contract from its inputs and verify the recorded digest."""
    if head != header(manifest):
        raise StoreError("journal belongs to a different network, contract, ruleset or admin")
    owners: dict[bytes, bytes | None] = {}
    failing: set[bytes] = set()

    def transfer(to, amount):
        return to not in failing

    contract = None
    for rec in records:
        k = rec["k"]
        if k == "start":
            contract = CombatContract(manifest, owners.get, transfer, rec["t"])
        elif k == "owner":
            owners[bytes.fromhex(rec["id"])] = bytes.fromhex(rec["owner"]) if rec["owner"] else None
        elif k == "fail":
            (failing.add if rec["on"] else failing.discard)(bytes.fromhex(rec["who"]))
        elif k == "call":
            contract.call(bytes.fromhex(rec["who"]), bytes.fromhex(rec["frame"]), rec["amount"], rec["t"])
        elif k == "end":
            contract.end_tick(rec["t"])
            contract.begin_tick(rec["t"] + 1)
        elif k == "begin":
            contract.begin_tick(rec["t"])
        elif k == "mint":
            pass                # external balances are not contract state
        elif k == "digest":
            if contract.event_digest.hex() != rec["event_digest"]:
                raise StoreError("replayed event digest differs from the recorded one")
        else:
            raise StoreError(f"unknown journal record {k!r}")
    if contract is None:
        raise StoreError("empty journal")
    return contract


# ---- compaction of finished history (AUD-024) --------------------------------

class History:
    """What compaction took out of the contract's hot state, kept small.

    The contract never reads a finished fight, contest, offer or cup again
    (the C++ port evicts them). Readers that summarise history (the exporter,
    a bot settling its budget) find here what they would have found there:
    per-fighter records by mode, each fighter's recent fight ids, and bounded
    outcome maps for bots that settle late."""

    RECENT = 64                 # fight ids kept per fighter (the exporter's page)
    OUTCOMES = 20_000           # pruned contests/offers/cups remembered for late budget settlement

    def __init__(self):
        self.records_by_mode: dict[bytes, dict[str, dict[str, int]]] = {}
        self.recent_fights: dict[bytes, list[int]] = {}
        self.contests: dict[int, tuple] = {}     # contest_id -> (kind, winner, stake, fee_profile_id, a, b)
        self.offers: dict[int, tuple] = {}       # offer_id -> (status, contest_id, amount)
        self.cups: dict[int, tuple] = {}         # cup_id -> (status, champion, sponsorship, entries_gross, entry_fee, fee_profile_id)
        self.pruned = {"fights": 0, "contests": 0, "offers": 0, "cups": 0}

    def _remember(self, table: dict, key, value):
        table[key] = value
        while len(table) > self.OUTCOMES:
            del table[next(iter(table))]


def count_fight(out: dict, fight) -> None:
    """Add one finished fight to per-fighter records by mode: W/D/L for fought
    results, FW/FL for forfeits, N for no result (double fault or void)."""
    from .codec import Mode
    if fight.phase != "DONE" or not fight.result:
        return
    mode = Mode(fight.context.mode).name.lower()
    kind, winner = fight.result.get("kind"), fight.result.get("winner")
    for side, p in (("A", fight.context.participant_a), ("B", fight.context.participant_b)):
        r = out.setdefault(p.fighter_id, {}).setdefault(mode, {"W": 0, "D": 0, "L": 0, "FW": 0, "FL": 0, "N": 0})
        if kind == "COMBAT":
            r["W" if winner == side else "D" if winner is None else "L"] += 1
        elif kind == "FORFEIT":
            r["FW" if winner == side else "FL"] += 1
        else:
            r["N"] += 1


def history(contract) -> History:
    h = getattr(contract, "history", None)
    if h is None:
        h = contract.history = History()
    return h


def compact(contract, keep_ticks: int = 2400, keep_recent: int = 400, per_fighter: int = 12,
            keep_cups: int = 20, keep_epochs: int = 8, keep_seasons: int = 6) -> dict:
    """Move finished records out of the contract's hot state. Returns counts.

    Kept in hot state:
    - everything live: open offers, active contests and their fights, cups in
      registration or running;
    - contests that finished within `keep_ticks`, so bots settle their budgets
      from them (they read the contest a tick or so after it ends);
    - the `keep_recent` newest fights (the public export publishes 200), each
      fighter's last `per_fighter` finished fights (opponent scouting reads the
      last ten), and the fights of the `keep_cups` newest cups (cups.json);
    - a contest while any of its fights is kept, and an offer while its contest is.
    Pair-start counters of past epochs, fault counts older than `keep_epochs`
    epochs and season stats older than `keep_seasons` seasons are dropped: the
    contract reads only the current epoch's and a live contest's season.
    Nothing here changes what the contract does next or the event digest."""
    c = contract
    h = history(c)
    t = c.tick
    cutoff = t - keep_ticks
    live_cups = {k.cup_id for k in c.cups.values() if k.status in ("REGISTRATION", "RUNNING")}
    recent_cups = set(sorted(c.cups)[-keep_cups:]) | live_cups
    keep_fights = set(sorted(c.fights)[-keep_recent:])
    per: dict[bytes, int] = {}
    for fid in sorted(c.fights, reverse=True):
        f = c.fights[fid]
        if f.phase != "DONE":
            keep_fights.add(fid)
            continue
        for p in (f.context.participant_a, f.context.participant_b):
            n = per.get(p.fighter_id, 0)
            if n < per_fighter:
                keep_fights.add(fid)
            per[p.fighter_id] = n + 1
    keep_contests = set()
    for ct in c.contests.values():
        young = ct.status != "DONE" or not ct.result or ct.result.get("tick", t) > cutoff
        if young or ct.cup_id in recent_cups or any(x in keep_fights for x in ct.fights):
            keep_contests.add(ct.contest_id)
    counts = {"fights": 0, "contests": 0, "offers": 0, "cups": 0}
    for cid in [x for x in c.contests if x not in keep_contests]:
        ct = c.contests.pop(cid)
        h._remember(h.contests, cid, (ct.result["kind"], ct.result.get("winner"), ct.stake, ct.fee_profile_id,
                                      ct.a.fighter_id, ct.b.fighter_id))
        for fid in ct.fights:
            f = c.fights.pop(fid, None)
            if f is None:
                continue
            count_fight(h.records_by_mode, f)
            for p in (f.context.participant_a, f.context.participant_b):
                ids = h.recent_fights.setdefault(p.fighter_id, [])
                ids.append(fid)
                ids.sort()
                del ids[:-History.RECENT]
            counts["fights"] += 1
        counts["contests"] += 1
    for oid in [o.offer_id for o in c.offers.values() if o.status != "OPEN"
                and (o.contest_id not in c.contests if o.status == "MATCHED" else o.expires_tick <= cutoff)]:
        o = c.offers.pop(oid)
        h._remember(h.offers, oid, (o.status, o.contest_id, o.amount))
        counts["offers"] += 1
    for kid in [k for k in sorted(c.cups) if k not in recent_cups]:
        k = c.cups[kid]
        if any(ct.cup_id == kid for ct in c.contests.values()):
            continue
        del c.cups[kid]
        fee_id = k.descriptor["fee_profile_id"]
        h._remember(h.cups, kid, (k.status, k.champion, k.sponsorship, sum(e.amount for e in k.entries.values()),
                                  k.descriptor["entry_fee"], fee_id, tuple(k.entries)))
        counts["cups"] += 1
    epoch = c.m.epoch(t)
    for key in [k for k in c.pair_starts if k[2] < epoch]:
        del c.pair_starts[key]
    season = c.m.season(t)
    for ftr in c.fighters.values():
        for e in [e for e in ftr.faults if e < epoch - keep_epochs]:
            del ftr.faults[e]
        for s in [s for s in ftr.season_stats if s < season - keep_seasons]:
            del ftr.season_stats[s]
        for s in [s for s in ftr.season_rating if s < season - keep_seasons]:
            del ftr.season_rating[s]
    for k, v in counts.items():
        h.pruned[k] += v
    return counts
