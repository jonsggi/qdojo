"""Public combat data under /data/combat/v1/ (docs/api.md §3).

An exporter is an indexer: it reads confirmed contract state and re-derives
the detailed beat traces from the revealed plans with its own engine call.
It never publishes a live commitment's plan or salt: those appear only after
their reveal was accepted, which is when the contract records them.

Legacy riddle exports (/data/board.json, history.json ...) are never
written or reinterpreted here.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import codec, npcs
from .contract import CombatContract
from .engine import resolve_round
from .rating import PLACEMENT_FIGHTS, belt
from .types import FightState

SCHEMA = "qdojo.combat.{}.v1"
PAGE = 64


def _hex(b):
    return b.hex() if isinstance(b, (bytes, bytearray)) else b


def _participant(p: codec.Participant) -> dict:
    return {"fighter_id": p.fighter_id.hex(), "owner": p.owner.hex(), "operator": p.operator.hex(),
            "auth_version": p.auth_version, "payout_recipient": p.payout_recipient.hex(),
            "lifetime_rating": p.lifetime_rating, "season_rating": p.season_rating}


def _envelope(c: CombatContract, kind: str, body: dict) -> dict:
    return {"schema": SCHEMA.format(kind), "network_id": c.m.network_id.hex(), "contract_id": c.m.contract_id.hex(),
            "generated_tick": str(c.tick), "source": "reference-contract-state", **body}


def fight_replay(c: CombatContract, fight_id: int) -> dict:
    """Confirmed plans and salts, re-derived traces, and what could be checked."""
    fight = c.fights[fight_id]
    ctx = fight.context
    rounds, state = [], None
    for r in fight.rounds:
        start: FightState = r["start"]
        plans = {s: codec.decode_plan(r["plans"][s]) for s in "AB"}
        res = resolve_round(c.m.ruleset, start, plans["A"], plans["B"])
        entry = res.to_json()
        entry.update({
            "tick": str(r["tick"]), "round_state_digest": r["round_state_digest"].hex(),
            "commitments": {s: r["commitments"][s].hex() for s in "AB"},
            "salts": {s: r["salts"][s].hex() for s in "AB"},
            "plan_bytes": {s: r["plans"][s].hex() for s in "AB"},
            "unexecuted": {s: [a.name for a in plans[s].actions[res.executed:]] for s in "AB"},
        })
        rounds.append(entry)
        state = res.end
    result = fight.result or {}
    contest = c.contests[fight.contest_id]
    settlement = None
    if contest.settlement is not None and fight.fight_id == contest.fights[-1]:
        settlement = {
            "contest_result": {k: (str(v) if k == "tick" else v) for k, v in contest.result.items()},
            "stake_per_fighter": str(contest.stake), "series_fights": [str(x) for x in contest.fights],
            "payers": {s: p.hex() for s, p in contest.payers.items()},
            "credits": {who.hex(): str(v) for who, v in sorted(contest.settlement["credits"].items())},
            "ratings": contest.settlement["ratings"] if contest.mode == codec.Mode.RANKED else None,
        }
    if state is None and result:
        state = fight.state          # a forfeit before any reveal: the state at the deadline
    body = {
        "fight_id": str(fight.fight_id), "contest_id": str(fight.contest_id),
        "mode": codec.Mode(ctx.mode).name.lower(), "ruleset_digest": ctx.ruleset_digest.hex(),
        "semantic_version": c.m.ruleset.semantic_version,
        "context_bytes": ctx.encode().hex(), "context_digest": fight.context_digest.hex(),
        "fighters": {"A": _participant(ctx.participant_a), "B": _participant(ctx.participant_b)},
        "rounds": rounds,
        "result": {k: v for k, v in result.items() if k != "tick"} | ({"tick": str(result["tick"])} if result else {}),
        "outcome": ({"winner": result.get("winner"), "result": result.get("result") or result.get("kind")}
                    if result else None),
        "final": ({"A": state.a.to_json(), "B": state.b.to_json()} if state else None),
        "forfeit_round": (fight.state.round_index if result.get("kind") in ("FORFEIT", "DOUBLE_FAULT") else None),
        "settlement": settlement,
        # This export comes from contract state, not raw confirmed transactions,
        # so inclusion is not independently established here (api.md §4).
        "evidence": {"inputs_confirmed": "UNAVAILABLE", "source": "same-source export"},
    }
    return _envelope(c, "replay", body)


def fight_summary(c: CombatContract, fight_id: int) -> dict:
    f = c.fights[fight_id]
    view = c.fight_view(fight_id)
    view["result"] = ({k: (str(v) if k == "tick" else v) for k, v in f.result.items()} if f.result else None)
    view.update({"fight_id": str(f.fight_id), "contest_id": str(f.contest_id),
                 "commit_last": str(f.commit_last), "reveal_last": str(f.reveal_last),
                 "fighters": {"A": _participant(f.context.participant_a), "B": _participant(f.context.participant_b)},
                 "mode": codec.Mode(f.context.mode).name.lower()})
    return _envelope(c, "fight", view)


def fighter(c: CombatContract, fid: bytes) -> dict:
    f = c.fighters[fid]
    placed = f.placement >= PLACEMENT_FIGHTS
    return _envelope(c, "fighter", {
        "fighter_id": fid.hex(), "owner": f.owner.hex(), "operator": f.operator.hex(),
        "auth_version": f.auth_version, "house_npc": f.house_npc, "lock": f.lock,
        "lifetime_rating": f.lifetime, "provisional": not placed, "belt": belt(f.lifetime, placed),
        "placement_fights": f.placement, "record": f.record,
        "faults_by_epoch": {str(k): v for k, v in f.faults.items()}, "cooldown_until": str(f.cooldown_until),
        "season_ratings": {str(k): v for k, v in f.season_rating.items()},
        "fights": [str(x.fight_id) for x in c.fights.values()
                   if fid in (x.context.participant_a.fighter_id, x.context.participant_b.fighter_id)][-PAGE:],
    })


def book(c: CombatContract) -> dict:
    t = c.tick
    from .matchmaking import window
    offers = [{"offer_id": str(o.offer_id), "kind": o.kind, "fighter_id": o.fighter_id.hex(),
               "rating": o.rating, "stake": str(o.amount), "window": window(o, t) if o.kind == "RANKED" else None,
               "max_gap": o.max_gap, "expires_tick": str(o.expires_tick),
               "opponent_id": o.opponent_id.hex() if o.opponent_id else None}
              for o in sorted(c.offers.values(), key=lambda o: o.offer_id) if o.status == "OPEN"]
    active = [str(f.fight_id) for f in c.fights.values() if f.phase != "DONE"]
    nxt = t + (-t) % c.m.match_interval
    return _envelope(c, "book", {"offers": offers, "capacity": {"offers": c.m.max_offers, "fights": c.m.max_fights,
                                                              "fights_in_use": c.fights_in_use()},
                                 "active_fights": active, "next_matching_tick": str(nxt)})


def manifest(c: CombatContract) -> dict:
    return _envelope(c, "manifest", {
        "ruleset_digest": c.m.ruleset.digest.hex(), "semantic_version": c.m.ruleset.semantic_version,
        "timing_profiles": {str(k): {"commit_ticks": v[0], "reveal_ticks": v[1]} for k, v in c.m.timing.items()},
        "tiers": {str(k): str(v) for k, v in c.m.tiers.items()},
        "match_interval_ticks": c.m.match_interval,
        "pair_starts_per_epoch": c.m.pair_starts_per_epoch, "pair_rematch_ticks": c.m.pair_rematch_ticks,
        "ticks_per_epoch": c.m.ticks_per_epoch,
        "fee_profiles": {str(k): {"rake_bps": v.rake_bps, "house_bps": v.house_bps, "dev_bps": v.dev_bps,
                                  "share_bps": v.share_bps} for k, v in c.m.fees.items()},
        "supported_schemas": [SCHEMA.format(k) for k in ("replay", "fight", "fighter", "book", "events", "npcs")],
    })


def events(c: CombatContract, after: int = 0) -> dict:
    page = c.events_page(after, PAGE)
    return _envelope(c, "events", {"after": str(after), "events": [
        {"seq": str(seq), "tick": str(t), "type": kind, "fields": [_hex(x) if not isinstance(x, int) else str(x)
                                                                  for x in fields], "digest": d.hex()}
        for seq, t, kind, fields, d in page]})


def npc_list() -> dict:
    return {"schema": SCHEMA.format("npcs"), "npcs": [
        {"id": n.id, "behavior": n.behavior, "lesson": n.lesson, "practice": True, "exhibition": True,
         "ranked": False} for n in npcs.ROSTER.values()]}


def _write(path: Path, doc: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def export_all(c: CombatContract, root: Path, keep: int | None = None, deployment: dict | None = None) -> list[Path]:
    """Write every public file; returns the paths written.

    `keep` limits fight files to the most recent N fights (plus every active
    one) and removes older fight files from `root`; the full history stays in
    the contract journal. `deployment` labels what produced the data (for a
    devnet: fake QU, synthetic identities)."""
    root = Path(root)
    if root.name != "v1" or root.parent.name != "combat":
        raise ValueError("export root must be .../combat/v1 so legacy files are never touched")
    out = []
    fight_ids = sorted(c.fights)
    if keep is not None:
        recent = set(fight_ids[-keep:]) | {f for f, x in c.fights.items() if x.phase != "DONE"}
        fight_ids = [f for f in fight_ids if f in recent]
        fights_dir = root / "fights"
        if fights_dir.exists():
            for p in fights_dir.iterdir():
                stem = p.name.split(".")[0]
                if stem.isdigit() and int(stem) not in recent:
                    if p.is_dir():
                        for q in p.iterdir():
                            q.unlink()
                        p.rmdir()
                    else:
                        p.unlink()

    def put(rel, doc):
        p = root / rel
        _write(p, doc)
        out.append(p)
    put("manifest.json", manifest(c))
    from .rules import CANDIDATE_1, RULESET_DIR, digest_of
    artifact = json.loads((RULESET_DIR / f"{CANDIDATE_1}.json").read_text())
    if digest_of(artifact) != c.m.ruleset.digest:
        raise ValueError("the packaged ruleset artifact is not the contract's ruleset")
    put(f"rulesets/{c.m.ruleset.digest.hex()}.json", {"schema": SCHEMA.format("ruleset"),
                                                     "semantic_version": c.m.ruleset.semantic_version,
                                                     "digest": c.m.ruleset.digest.hex(),
                                                     "rules": artifact})
    put("book.json", book(c))
    put("npcs.json", npc_list())
    for fid in fight_ids:
        fight = c.fights[fid]
        # A finished fight never changes again: write it once, so a live export
        # does not rewrite hundreds of files for a new generated_tick.
        final = fight.phase == "DONE" and c.contests[fight.contest_id].status == "DONE"
        if final and (root / f"fights/{fid}.json").exists():
            continue
        put(f"fights/{fid}.json", fight_summary(c, fid))
        if fight.rounds or fight.result:
            put(f"fights/{fid}/replay.json", fight_replay(c, fid))
    for fid in c.fighters:
        put(f"fighters/{fid.hex()}.json", fighter(c, fid))
    put("events/latest.json", events(c, max(0, c.event_seq - PAGE)))
    results = []
    for fid in reversed(fight_ids):
        f = c.fights[fid]
        if f.phase != "DONE" or not f.result:
            continue
        results.append({"fight_id": str(fid), "contest_id": str(f.contest_id),
                        "mode": codec.Mode(f.context.mode).name.lower(),
                        "A": f.context.participant_a.fighter_id.hex(), "B": f.context.participant_b.fighter_id.hex(),
                        "kind": f.result["kind"], "winner": f.result.get("winner"),
                        "result": f.result.get("result"), "tick": str(f.result["tick"])})
    put("results.json", _envelope(c, "results", {"results": results}))
    extra = {"generated_at": deployment["generated_at"]} if deployment and "generated_at" in deployment else {}
    put("index.json", _envelope(c, "index", {
        "fights": [str(f) for f in fight_ids][-(keep or 200):],
        "active_fights": [str(f) for f in fight_ids if c.fights[f].phase != "DONE"],
        "fighters": [f.hex() for f in c.fighters],
        "deployment": deployment or {"kind": "unspecified"},
        "names": {k: v for k, v in (deployment or {}).get("names", {}).items()}, **extra}))
    return out
