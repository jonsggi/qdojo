"""A persistent local devnet: the reference contract on a fake chain, in one directory.

`qdojo combat devnet …` and the chain-shaped commands (queue, duel, cup,
fighter, withdraw, bot run) operate on it until a deployed Qubic contract and
its native adapter exist. Its QU is fake and minted locally; its identities
are synthetic labels, never keys. State is the input journal (store.py), so
every restart replays to the identical contract.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from . import codec, export, scouting
from .codec import Code, Op
from .contract import Manifest, development_manifest
from .rules import CANDIDATE_1, CANDIDATE_2, by_version
from .sim import World, identity
from .store import StoreError, refuse_legacy

JOURNAL = "devnet.journal"
MARKER = "devnet.json"
SCHEMA = "qdojo.combat.devnet.v1"


def roles() -> dict[str, bytes]:
    return {k: identity(k) for k in ("admin", "house", "dev", "share")}


# Manifest profiles. "dev" is the development fixture with the specified
# matchmaking limits. "demo" is the public spectator arena: shorter epochs and
# looser pair limits so a small bot population keeps fighting, and seasons
# turn over within hours. The site shows which profile produced its data.
#
# A profile may also name its ruleset ("ruleset", default candidate 1) and
# replace the timing profiles ("timing": {id: (commit_ticks, reveal_ticks)},
# default the development fixture's {1: (24, 12)}). "demo-c2" is the demo
# arena on combat-v1 candidate 2 with the demo timing of docs/model.md §4
# (AUD-021, AUD-022): a fresh devnet directory, never a converted one.
DEMO = {"ticks_per_epoch": 2400, "season_epochs": 4, "season_closeout_ticks": 300,
        "pair_starts_per_epoch": 6, "pair_rematch_ticks": 60}
DEMO_TIMING = {1: (9, 6)}       # commit, reveal ticks: ~13 ticks a round, ~38 per ranked fight (57 s at 1.5 s)
PROFILES = {
    "dev": {},
    "demo": dict(DEMO),
    "demo-c2": {**DEMO, "ruleset": CANDIDATE_2, "timing": DEMO_TIMING},
}


def manifest(profile: str = "dev") -> Manifest:
    r = roles()
    kw = dict(PROFILES[profile])
    rules = by_version(kw.pop("ruleset", CANDIDATE_1))
    timing = kw.pop("timing", None)
    m = development_manifest(rules, r["admin"], r["house"], r["dev"], r["share"], **kw)
    return replace(m, timing=dict(timing)) if timing else m


class Devnet:
    def __init__(self, directory: Path, profile: str | None = None):
        self.dir = Path(directory)
        refuse_legacy(self.dir)
        marker = self.dir / MARKER
        if marker.exists():
            meta = json.loads(marker.read_text())
            stored = meta.get("profile", "dev")
            if profile is not None and profile != stored:
                raise StoreError(f"{self.dir} is a {stored!r} devnet; its rules cannot change to {profile!r}")
            self.profile = stored
            self.m = manifest(stored)
            if meta.get("schema") != SCHEMA or meta.get("ruleset_digest") != self.m.ruleset.digest.hex():
                raise StoreError(f"{self.dir} is not a devnet for this ruleset")
            records = [json.loads(x) for x in (self.dir / JOURNAL).read_text().splitlines() if x.strip()]
            self.world = World.replay(self.m, records)
        else:
            self.profile = profile or "dev"
            self.m = manifest(self.profile)
            self.dir.mkdir(parents=True, exist_ok=True)
            self.world = World(self.m)
            self.world.mint(roles()["admin"], 10**12)
            marker.write_text(json.dumps({"schema": SCHEMA, "ruleset_digest": self.m.ruleset.digest.hex(),
                                          "profile": self.profile,
                                          "note": "fake QU, synthetic identities; not a deployment"}))
        self._saved = len(self.world.journal)
        self.scout = scouting.Scout()

    def save(self):
        new = self.world.journal[self._saved:] if (self.dir / JOURNAL).exists() else self.world.journal
        with open(self.dir / JOURNAL, "a", encoding="utf-8") as f:
            for rec in new:
                f.write(json.dumps(rec, separators=(",", ":")) + "\n")
        self._saved = len(self.world.journal)

    # -- convenience for local play ------------------------------------------

    def ensure_fighter(self, label: str, funds: int = 100_000) -> tuple[bytes, bytes]:
        """Register a synthetic fighter owned by identity('owner:'+label)."""
        fid, owner = identity("fighter:" + label), identity("owner:" + label)
        c = self.world.contract
        if fid not in c.fighters:
            admin = roles()["admin"]
            self.world.owners[fid] = owner
            self.world.mint(owner, funds)
            self.world.send(admin, Op.ADMIN_REGISTER_ASSET, fighter_id=fid, registry_version=1, house_npc=0)
            self.world.send(owner, Op.REGISTER_FIGHTER, fighter_id=fid, registry_version=1)
        return fid, owner

    def client(self, signer: bytes) -> "DevnetClient":
        return DevnetClient(self, signer)


class DevnetClient:
    """The bot's view of the devnet as one signer; reads are contract queries."""

    def __init__(self, net: Devnet, signer: bytes):
        self.net, self.signer = net, signer
        self.network_id, self.contract_id = net.m.network_id, net.m.contract_id

    @property
    def c(self):
        return self.net.world.contract

    def tick(self) -> int:
        return self.net.world.tick

    def send(self, op: Op, amount: int = 0, **fields):
        return self.net.world.send(self.signer, op, amount, **fields)

    def balance(self, who: bytes) -> int:
        return self.net.world.balances.get(who, 0)

    def credit(self, who: bytes) -> int:
        return self.c.ledger.credits.get(who, 0)

    def tier_amount(self, tier: int) -> int | None:
        return self.net.m.tiers.get(tier)

    def fighter(self, fid: bytes) -> dict | None:
        f = self.c.fighters.get(fid)
        if f is None:
            return None
        active, cup = None, None
        if f.lock == "CONTEST":
            contest = self.c.contests[f.lock_ref]
            live = [x for x in contest.fights if self.c.fights[x].phase != "DONE"]
            active = live[-1] if live else None
        elif f.lock == "TOURNAMENT":
            k = self.c.cups[f.lock_ref]
            for contest in self.c.contests.values():
                if contest.cup_id == k.cup_id and contest.status == "ACTIVE" \
                        and fid in (contest.a.fighter_id, contest.b.fighter_id):
                    live = [x for x in contest.fights if self.c.fights[x].phase != "DONE"]
                    active = live[-1] if live else None
            pairing = next((p for p in k.pairings.values() if p.level == k.level and p.status == "SCHEDULED"
                            and fid in (p.a, p.b)), None)
            cup = {"cup_id": k.cup_id, "status": k.status, "level": k.level, "level_start": k.level_start,
                   "checkin_ticks": k.descriptor["checkin_ticks"],
                   "pairing_id": pairing.pairing_id if pairing else None,
                   "checked_in": bool(pairing and fid in pairing.checked)}
        t = self.tick()
        return {"lock": f.lock, "auth_version": f.auth_version, "active_fight": active,
                "lifetime": f.lifetime, "operator": f.operator, "cup": cup,
                "cooldown_until": f.cooldown_until, "suspended": f.suspended_epoch == self.net.m.epoch(t)}

    def open_cups(self) -> list[dict]:
        t = self.tick()
        return [{"cup_id": k.cup_id, "entry_fee": k.descriptor["entry_fee"], "entries": len(k.entries),
                 "max_entrants": k.descriptor["max_entrants"], "registration_close": k.descriptor["registration_close"]}
                for k in self.c.cups.values() if k.status == "REGISTRATION" and t < k.descriptor["registration_close"]]

    def duel_offers_for(self, fid: bytes) -> list[dict]:
        t = self.tick()
        return [{"offer_id": o.offer_id, "stake": o.amount, "format": o.series_format, "challenger": o.fighter_id}
                for o in self.c.offers.values()
                if o.kind == "DUEL" and o.status == "OPEN" and o.opponent_id == fid and t < o.expires_tick]

    def fight(self, fight_id: int) -> dict | None:
        fight = self.c.fights.get(fight_id)
        if fight is None:
            return None
        ctx = fight.context
        parts = {"A": ctx.participant_a, "B": ctx.participant_b}

        def observation(slot: str) -> dict:
            other = "B" if slot == "A" else "A"
            me, opp = (fight.state.a, fight.state.b) if slot == "A" else (fight.state.b, fight.state.a)
            replay = export.fight_replay(self.c, fight_id)
            # Scouting as of this round's start, so every call in a round sees the same history.
            scout = getattr(self.net, "scout", None) or self.__dict__.setdefault("_scout", scouting.Scout())
            scouted = scout.history(self.c, parts[other].fighter_id, fight_id, fight.start_tick)
            return {
                "schema": "qdojo.combat.observation.v1", "mode": codec.Mode(ctx.mode).name.lower(),
                "network_id": self.network_id.hex(), "contract_id": self.contract_id.hex(),
                "fight_id": str(fight_id), "contest_id": str(fight.contest_id),
                "round_index": fight.state.round_index, "self_slot": slot,
                "ruleset_digest": ctx.ruleset_digest.hex(), "context_digest": fight.context_digest.hex(),
                "round_state_digest": fight.round_state_digest().hex(),
                "self": {"fighter_id": parts[slot].fighter_id.hex(), **me.to_json(),
                         "power_available": bool(me.power_available)},
                "opponent": {"fighter_id": parts[other].fighter_id.hex(), **opp.to_json(),
                             "power_available": bool(opp.power_available)},
                "deadlines": {"commit_last_tick": str(fight.commit_last),
                              "reveal_first_tick": str(fight.commit_last + 1),
                              "reveal_last_tick": str(fight.reveal_last)},
                "observed_tick": str(self.tick()),
                "prior_rounds": replay["rounds"],
                "history_manifest": {"opponent_fight_ids": [f["fight_id"] for f in scouted["fights"]],
                                     "as_of_tick": scouted["as_of_tick"]},
                "opponent_history": scouted,
                "decision_budget_ms": 1500,
            }
        return {"fight_id": fight_id, "phase": fight.phase, "round_index": fight.state.round_index,
                "start_tick": fight.start_tick, "commit_last": fight.commit_last, "reveal_last": fight.reveal_last,
                "context_digest": fight.context_digest.hex(), "round_state_digest": fight.round_state_digest().hex(),
                "slot_of": {parts[s].fighter_id.hex(): s for s in "AB"},
                "auth_version": {s: parts[s].auth_version for s in "AB"},
                "committed": set(fight.commits), "revealed": set(fight.reveals), "observation": observation}

    def spend_outcome(self, ref: str, fid: bytes):
        kind, _, n = ref.partition(":")
        if kind == "cup":
            k = self.c.cups.get(int(n))
            if k is None:
                return None
            entry = k.entries.get(fid)
            if k.status in ("REGISTRATION", "RUNNING"):
                if entry is None and k.status == "REGISTRATION":
                    return ("refund", k.descriptor["entry_fee"])       # withdrawn before close
                return None
            if k.status in ("CANCELLED", "ABORTED"):
                return ("refund", k.descriptor["entry_fee"])
            if k.champion != fid:
                return ("settled", 0)
            fee = self.net.m.fees[k.descriptor["fee_profile_id"]]
            gross_entries = sum(e.amount for e in k.entries.values())
            return ("settled", k.sponsorship + gross_entries - gross_entries * fee.rake_bps // 10_000)
        if kind == "offer":
            o = self.c.offers.get(int(n))
            if o is None or o.status == "OPEN":
                return None
            if o.status == "MATCHED":
                return ("contest", f"contest:{o.contest_id}")
            return ("refund", o.amount)
        contest = self.c.contests.get(int(n))
        if contest is None or contest.status != "DONE":
            return None
        me = "A" if contest.a.fighter_id == fid else "B"
        r = contest.result
        stake = contest.stake
        fee = self.net.m.fees[contest.fee_profile_id]
        if r["kind"] in ("COMBAT", "FORFEIT") and r.get("winner") == me:
            gross = 2 * stake
            return ("settled", gross - gross * fee.rake_bps // 10_000)
        if r["kind"] == "FORFEIT" or r["kind"] == "DOUBLE_FAULT":
            return ("fault", stake if r["kind"] == "DOUBLE_FAULT" else 0)
        if r.get("winner") is None:
            return ("settled", stake)
        return ("settled", 0)


def result_text(r) -> str:
    return r.code.name + (f" ({r.detail})" if r.detail else "") + (f" refunded {r.refunded}" if r.refunded else "")


__all__ = ["Devnet", "DevnetClient", "manifest", "roles", "result_text", "Code"]
