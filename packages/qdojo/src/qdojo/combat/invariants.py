"""Whole-system invariants for the reference contract on a (simulated) chain.

`check(world)` returns a list of violations (empty when healthy). Tests, the
scenario library and the long soak run call it every tick. Each violation
names the object and the rule it breaks.

Rules:
- Conservation: external balances plus the contract balance equal what was
  minted, and the contract balance equals the sum of its liabilities.
- Locks: every non-IDLE fighter points at a live offer, contest or cup that
  includes it, and every live offer and contest holds its fighters' locks.
- Liveness: no fight sits past its deadline without END_TICK acting on it; no
  open offer outlives its expiry by more than one matching interval (lazy
  cleanup); no running cup outlives its absolute expiry. Ticks when the
  contract did not run (a service gap) are allowed, since nothing can act then.

`check_export(contract, root, slack)` checks a public export against the
contract (AUD-025): no published live fight is overdue by more than `slack`
ticks, and every fight the contract finished before the export ran is
published in its final form, also in results.json and index.json.
"""
from __future__ import annotations

import json
from pathlib import Path

from .codec import Mode


def check(world) -> list[str]:
    c = world.contract
    out = []
    minted = getattr(world, "minted", None)
    if minted is not None:
        total = sum(world.balances.values()) + c.ledger.balance
        if total != minted:
            out.append(f"conservation: external + contract = {total}, minted {minted}")
    if c.ledger.balance != c.ledger.liabilities():
        out.append(f"ledger: balance {c.ledger.balance} != liabilities {c.ledger.liabilities()}")
    if any(v < 0 for v in c.ledger.credits.values()):
        out.append("ledger: negative credit")

    for fid, f in c.fighters.items():
        tag = fid.hex()[:8]
        if f.lock in ("QUEUED", "DUEL_OFFER"):
            o = c.offers.get(f.lock_ref)
            if o is None or o.status != "OPEN" or o.fighter_id != fid:
                out.append(f"lock: {tag} {f.lock} -> offer {f.lock_ref} not open for it")
        elif f.lock == "CONTEST":
            ct = c.contests.get(f.lock_ref)
            if ct is None or ct.status != "ACTIVE" or fid not in (ct.a.fighter_id, ct.b.fighter_id):
                out.append(f"lock: {tag} CONTEST -> contest {f.lock_ref} not active for it")
        elif f.lock == "TOURNAMENT":
            k = c.cups.get(f.lock_ref)
            if k is None or k.status not in ("REGISTRATION", "RUNNING") or fid not in k.entries:
                out.append(f"lock: {tag} TOURNAMENT -> cup {f.lock_ref} not live for it")
        elif f.lock != "IDLE":
            out.append(f"lock: {tag} unknown lock {f.lock}")
    for o in c.offers.values():
        if o.status == "OPEN" and c.fighters[o.fighter_id].lock_ref != o.offer_id:
            out.append(f"lock: open offer {o.offer_id} not held by its fighter")
    for ct in c.contests.values():
        if ct.status == "ACTIVE" and ct.mode != Mode.CUP:
            for fid in (ct.a.fighter_id, ct.b.fighter_id):
                f = c.fighters[fid]
                if f.lock != "CONTEST" or f.lock_ref != ct.contest_id:
                    out.append(f"lock: contest {ct.contest_id} active but {fid.hex()[:8]} not locked to it")

    serviced = c.last_serviced
    for fight in c.fights.values():
        if fight.phase == "COMMIT" and serviced > fight.commit_last:
            out.append(f"liveness: fight {fight.fight_id} still COMMIT after its deadline {fight.commit_last}")
        if fight.phase == "REVEAL" and serviced > fight.reveal_last:
            out.append(f"liveness: fight {fight.fight_id} still REVEAL after its deadline {fight.reveal_last}")
    for o in c.offers.values():
        if o.status == "OPEN" and o.kind == "RANKED" and serviced > o.expires_tick + c.m.match_interval:
            out.append(f"liveness: offer {o.offer_id} open {serviced - o.expires_tick} ticks past expiry")
        if o.status == "OPEN" and o.kind == "DUEL" and serviced > o.expires_tick:
            out.append(f"liveness: duel offer {o.offer_id} open past expiry")
    for k in c.cups.values():
        if k.status == "RUNNING" and serviced > k.expiry_tick:
            out.append(f"liveness: cup {k.cup_id} running past its absolute expiry")
    return out


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def check_export(contract, root, slack: int) -> list[str]:
    """Published fight files against the contract. `slack` is how many ticks a
    live file may lag: at least the export interval, since a live fight's file
    is refreshed only when the exporter runs. Fights the contract no longer
    holds in memory (compacted history) are checked for finality only."""
    c, root = contract, Path(root)
    out = []
    manifest = _read(root / "manifest.json")
    if manifest is None:
        return ["export: manifest.json missing or unreadable"]
    exported = int(manifest["generated_tick"])
    fights_dir = root / "fights"
    published = sorted(int(p.stem) for p in fights_dir.glob("*.json") if p.stem.isdigit()) if fights_dir.exists() else []
    for fid in published:
        doc = _read(fights_dir / f"{fid}.json")
        if doc is None:
            out.append(f"export: fight {fid} file unreadable")
            continue
        if doc.get("final") is True:
            if doc.get("phase") != "DONE" or not doc.get("result"):
                out.append(f"export: fight {fid} marked final but published as {doc.get('phase')}")
            continue
        phase = doc.get("phase")
        deadline = doc.get("commit_last") if phase == "COMMIT" else doc.get("reveal_last") if phase == "REVEAL" else None
        if deadline is not None and c.tick - int(deadline) > slack:
            out.append(f"export: fight {fid} published as {phase} with deadline {deadline}, "
                       f"overdue by {c.tick - int(deadline)} ticks at tick {c.tick}")
        fight = c.fights.get(fid)
        contest = c.contests.get(fight.contest_id) if fight is not None else None
        if fight is None or contest is None:
            if fid < c.next_id["fight"]:
                out.append(f"export: fight {fid} is history in the contract but its published file is not final")
            continue
        done = contest.status == "DONE" and fight.phase == "DONE"
        if done and contest.result and int(contest.result["tick"]) <= exported:
            out.append(f"export: fight {fid} finished at tick {contest.result['tick']} but the export "
                       f"of tick {exported} still publishes it as {phase}")
    index = _read(root / "index.json")
    if index is not None:
        for x in index.get("active_fights", []):
            fight = c.fights.get(int(x))
            if fight is None or (fight.phase == "DONE" and fight.result and int(fight.result["tick"]) <= exported):
                out.append(f"export: index lists fight {x} as active after it finished")
    results = _read(root / "results.json")
    if results is not None:
        for r in results.get("results", []):
            doc = _read(fights_dir / f"{r['fight_id']}.json")
            if doc is not None and doc.get("phase") != "DONE":
                out.append(f"export: results.json has fight {r['fight_id']} finished, its file says {doc.get('phase')}")
    return out


class InvariantError(AssertionError):
    pass


def assert_ok(world):
    bad = check(world)
    if bad:
        raise InvariantError("; ".join(bad[:5]) + (f" (+{len(bad) - 5} more)" if len(bad) > 5 else ""))
