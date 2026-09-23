"""A persistent local devnet: the reference contract on a fake chain, in one directory.

`qdojo combat devnet …` and the chain-shaped commands (queue, duel, cup,
fighter, withdraw, bot run) operate on it until a deployed Qubic contract and
its native adapter exist. Its QU is fake and minted locally; its identities
are synthetic labels, never keys. State is the input journal (store.py), so
every restart replays to the identical contract.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import codec, export
from .codec import Code, Op
from .contract import Manifest, development_manifest
from .rules import candidate_1
from .sim import World, identity
from .store import StoreError, refuse_legacy

JOURNAL = "devnet.journal"
MARKER = "devnet.json"
SCHEMA = "qdojo.combat.devnet.v1"


def roles() -> dict[str, bytes]:
    return {k: identity(k) for k in ("admin", "house", "dev", "share")}


def manifest() -> Manifest:
    r = roles()
    return development_manifest(candidate_1(), r["admin"], r["house"], r["dev"], r["share"])


class Devnet:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        refuse_legacy(self.dir)
        self.m = manifest()
        marker = self.dir / MARKER
        if marker.exists():
            meta = json.loads(marker.read_text())
            if meta.get("schema") != SCHEMA or meta.get("ruleset_digest") != self.m.ruleset.digest.hex():
                raise StoreError(f"{self.dir} is not a devnet for this ruleset")
            records = [json.loads(x) for x in (self.dir / JOURNAL).read_text().splitlines() if x.strip()]
            self.world = World.replay(self.m, records)
        else:
            self.dir.mkdir(parents=True, exist_ok=True)
            self.world = World(self.m)
            self.world.mint(roles()["admin"], 10**12)
            marker.write_text(json.dumps({"schema": SCHEMA, "ruleset_digest": self.m.ruleset.digest.hex(),
                                          "note": "fake QU, synthetic identities; not a deployment"}))
        self._saved = len(self.world.journal)

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
        active = None
        if f.lock == "CONTEST":
            contest = self.c.contests[f.lock_ref]
            live = [x for x in contest.fights if self.c.fights[x].phase != "DONE"]
            active = live[-1] if live else None
        return {"lock": f.lock, "auth_version": f.auth_version, "active_fight": active,
                "lifetime": f.lifetime, "operator": f.operator}

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
                "history_manifest": {"opponent_fight_ids": [], "as_of_tick": str(self.tick())},
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
