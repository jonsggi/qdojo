"""A persistent local devnet: the reference contract on a fake chain, in one directory.

`qdojo combat devnet …` and the chain-shaped commands (queue, duel, cup,
fighter, withdraw, bot run) operate on it until a deployed Qubic contract and
its native adapter exist. Its QU is fake and minted locally; its identities
are synthetic labels, never keys. State is the input journal (store.py), so
every restart replays to the identical contract.

Restarts (AUD-024). A long-running devnet (the demo arena) also writes a
state snapshot now and then: the pickled world after a `digest` checkpoint
record in the journal, with the journal's byte length and SHA-256 at that
point, the manifest, and a fingerprint of the contract code. A restart loads
the newest snapshot that verifies (journal prefix hash, code, manifest,
payload hash, event digest, invariants) and replays only the journal after
it; anything that does not verify falls back to the previous snapshot, then
to a full replay. Every replay checks the `digest` checkpoints it crosses.
The journal stays the source of truth: deleting the snapshots is always safe.

A devnet records its manifest values in devnet.json when it is created, so
changing a profile default never changes how an existing journal replays.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import pickle
import time
from pathlib import Path

from . import codec, export, invariants, scouting, store
from .codec import Code, Op
from .contract import Manifest, Qualification, development_manifest
from .ledger import FeeProfile
from .rules import CANDIDATE_1, CANDIDATE_2, by_version
from .sim import World, _Failing, _Owners, identity
from .store import StoreError, refuse_legacy

JOURNAL = "devnet.journal"
MARKER = "devnet.json"
SCHEMA = "qdojo.combat.devnet.v1"
SNAPSHOT, SNAPSHOT_PREV = "snapshot.pickle", "snapshot.prev.pickle"
SNAPSHOT_SCHEMA = "qdojo.combat.snapshot.v1"


def roles() -> dict[str, bytes]:
    return {k: identity(k) for k in ("admin", "house", "dev", "share")}


# The demo arena's commit and reveal windows, in ticks (protocol.md §4). Change
# them here, or for one new arena with `qdojo combat live --timing C,R`. An
# existing arena keeps the values it was created with (devnet.json).
DEMO_TIMING = (24, 12)
# The candidate-2 demo arena's windows (docs/model.md §4, AUD-022): a round
# takes the commit window plus ~4 ticks of reveal latency, so 9/6 gives a
# median ranked fight of ~37 ticks (55 s at 1.5 s per tick).
DEMO_C2_TIMING = (9, 6)

# Manifest profiles. "dev" is the development fixture with the specified
# matchmaking limits. "demo" is the public spectator arena: shorter epochs and
# looser pair limits so a small bot population keeps fighting, seasons turn
# over within hours, and stakes large enough that rake covers the simulated
# execution cost of a fight (docs/economics-report.md). The site shows which
# profile produced its data. Keys beyond Manifest fields: "ruleset" (a
# packaged semantic version, default candidate 1), "timing" {profile:
# [commit, reveal]}, "tiers" {tier: stake}, "fees" {profile: bps}.
# "demo-c2" is the demo arena on combat-v1 candidate 2 (docs/combat.md §11,
# AUD-021) with DEMO_C2_TIMING: always a fresh devnet, never a converted one.
# Demo fee profiles in bps: 1 for ranked fights and duels, 2 for cup entries.
DEMO_FEES = {1: {"rake_bps": 500, "house_bps": 6000, "dev_bps": 1000, "share_bps": 3000},
             2: {"rake_bps": 1000, "house_bps": 6000, "dev_bps": 1000, "share_bps": 3000}}

PROFILES = {
    "dev": {},
    "demo": {"ticks_per_epoch": 2400, "season_epochs": 4, "season_closeout_ticks": 300,
             # At most 3 rated starts per pair per epoch (was 6): in a small field
             # the two best fighters otherwise spend most of their fights on each
             # other (AUD-020). Spec value: 2.
             "pair_starts_per_epoch": 3, "pair_rematch_ticks": 60,
             "timing": {1: DEMO_TIMING}, "tiers": {1: 5000, 2: 20000}, "fees": DEMO_FEES},
}
PROFILES["demo-c2"] = {**PROFILES["demo"], "ruleset": CANDIDATE_2, "timing": {1: DEMO_C2_TIMING}}

# Season championship qualification per profile (contract.Qualification): the
# demo arena scales the distinct-opponent thresholds to its small field.
QUALIFICATION = {"dev": Qualification(), "demo": Qualification(scale=True), "demo-c2": Qualification(scale=True)}

# Arenas created before devnet.json recorded manifest values replay with these.
LEGACY_PROFILES = {
    "dev": {},
    "demo": {"ticks_per_epoch": 2400, "season_epochs": 4, "season_closeout_ticks": 300,
             "pair_starts_per_epoch": 6, "pair_rematch_ticks": 60},
}


def params_json(params: dict) -> dict:
    """Profile values in devnet.json form (string keys, lists)."""
    out = {k: v for k, v in params.items() if k not in ("timing", "tiers", "fees")}
    if "timing" in params:
        out["timing"] = {str(k): list(v) for k, v in params["timing"].items()}
    if "tiers" in params:
        out["tiers"] = {str(k): int(v) for k, v in params["tiers"].items()}
    if "fees" in params:
        out["fees"] = {str(k): dict(v) for k, v in params["fees"].items()}
    return out


def manifest(profile: str = "dev", params: dict | None = None) -> Manifest:
    """The manifest for a profile, or for explicit profile values (as recorded in devnet.json)."""
    r = roles()
    p = dict(PROFILES[profile] if params is None else params)
    timing = {int(k): tuple(v) for k, v in p.pop("timing", {}).items()}
    tiers = {int(k): int(v) for k, v in p.pop("tiers", {}).items()}
    fees = p.pop("fees", {})
    rules = by_version(p.pop("ruleset", CANDIDATE_1))     # recorded in devnet.json, like every other value
    m = development_manifest(rules, r["admin"], r["house"], r["dev"], r["share"], **p)
    changes = {}
    if timing:
        changes["timing"] = {**m.timing, **timing}
    if tiers:
        changes["tiers"] = tiers
    if fees:
        changes["fees"] = {**m.fees, **{int(k): FeeProfile(int(k), v["rake_bps"], v["house_bps"], v["dev_bps"],
                                                             v["share_bps"], r["house"], r["dev"], r["share"])
                                        for k, v in fees.items()}}
    return dataclasses.replace(m, **changes) if changes else m


def recorded(meta: dict) -> tuple[str, dict, Manifest]:
    """(profile, params, manifest) a devnet replays with, from its devnet.json:
    the recorded values, or for a devnet from before they were recorded the
    legacy profile values. Every reader of a journal must use this (the
    arena, the read model), never the current profile defaults."""
    profile = meta.get("profile", "dev")
    params = meta.get("params", params_json(LEGACY_PROFILES.get(profile, PROFILES[profile])))
    return profile, params, manifest(profile, params)


# ---- journal replay and snapshots -------------------------------------------

STATE_MODULES = ("contract", "ledger", "matchmaking", "series", "rating", "engine", "codec", "types", "rules",
                 "sim", "store")


def code_fingerprint() -> str:
    """SHA-256 over the source of every module whose code shapes the pickled
    state; a snapshot from other code is never loaded (full replay instead)."""
    import importlib
    h = hashlib.sha256(b"qdojo/combat/snapshot-code/v1\0")
    for name in STATE_MODULES:
        mod = importlib.import_module(f"{__package__}.{name}")
        h.update(name.encode() + b"\0" + Path(mod.__file__).read_bytes())
    return h.hexdigest()


def manifest_digest(m: Manifest) -> str:
    return hashlib.sha256(json.dumps(store.header(m), sort_keys=True).encode()).hexdigest()


def apply_records(w: World, records, compact_every: int = 0, compact=None):
    """Apply journal records to a world (as World.replay does), checking every
    `digest` checkpoint and compacting hot state every `compact_every` ticks."""
    for rec in records:
        k = rec["k"]
        if k == "mint":
            w.mint(bytes.fromhex(rec["who"]), rec["amount"])
        elif k == "owner":
            w.owners[bytes.fromhex(rec["id"])] = bytes.fromhex(rec["owner"]) if rec["owner"] else None
        elif k == "fail":
            who = bytes.fromhex(rec["who"])
            (w.transfer_fails.add if rec["on"] else w.transfer_fails.discard)(who)
        elif k == "call":
            w.raw(bytes.fromhex(rec["who"]), bytes.fromhex(rec["frame"]), rec["amount"])
        elif k == "end":
            w.end()
            if compact_every and compact is not None and w.tick % compact_every == 0:
                compact(w.contract)
        elif k == "begin":
            w.skip_ticks(rec["t"] - w.tick)
        elif k == "digest":
            c = w.contract
            if c.event_seq != rec["event_seq"] or c.event_digest.hex() != rec["event_digest"]:
                raise StoreError(f"replay diverged at the checkpoint of tick {rec['t']}: event digest differs")
        elif k == "xfer":
            _move(w, bytes.fromhex(rec["from"]), bytes.fromhex(rec["to"]), rec["amount"])
        elif k == "start":
            pass
        else:
            raise StoreError(f"unknown journal record {k!r}")
    w.nonces = {who: last[0] for who, last in w.contract.nonces.items()}


def _move(w: World, frm: bytes, to: bytes, amount: int):
    if not 0 <= amount <= w.balances.get(frm, 0):
        raise StoreError("external transfer exceeds the sender's balance")
    w.balances[frm] -= amount
    w.balances[to] = w.balances.get(to, 0) + amount


def _parse(raw: bytes) -> list[dict]:
    return [json.loads(x) for x in raw.split(b"\n") if x.strip()]


def _world_state(w: World) -> bytes:
    c = w.contract
    hooks = (c.owner_of, c.transfer)
    c.owner_of = c.transfer = None
    try:
        return pickle.dumps({"tick": w.tick, "balances": w.balances, "nonces": w.nonces, "minted": w.minted,
                             "owners": dict(w.owners), "fails": set(w.transfer_fails), "contract": c},
                            protocol=pickle.HIGHEST_PROTOCOL)
    finally:
        c.owner_of, c.transfer = hooks


def _world_from_state(m: Manifest, state: dict) -> World:
    w = World.__new__(World)
    w.manifest, w.tick, w.balances, w.nonces, w.minted = m, state["tick"], state["balances"], state["nonces"], state["minted"]
    w.journal = []
    w.owners = _Owners(w)
    dict.update(w.owners, state["owners"])          # no journal records: these are restored, not new
    w.transfer_fails = _Failing()
    w.transfer_fails.world = w
    set.update(w.transfer_fails, state["fails"])
    c = state["contract"]
    if c.m != m:
        raise StoreError("snapshot manifest differs")
    c.owner_of, c.transfer = w.owners.get, w._transfer
    w.contract = c
    return w


class Devnet:
    def __init__(self, directory: Path, profile: str | None = None, params: dict | None = None,
                 compact=None, compact_every: int = 0):
        """`params` (new devnets only) override the profile's manifest values.
        `compact(contract)` runs every `compact_every` ticks during a replay."""
        self.dir = Path(directory)
        refuse_legacy(self.dir)
        marker = self.dir / MARKER
        self._compact, self._compact_every = compact, compact_every
        self._jhash, self._jbytes = hashlib.sha256(), 0
        self.restart = {"mode": "new", "seconds": 0.0, "tried": []}
        self.snapshot_tick = None
        if marker.exists():
            meta = json.loads(marker.read_text())
            stored = meta.get("profile", "dev")
            if profile is not None and profile != stored:
                raise StoreError(f"{self.dir} is a {stored!r} devnet; its rules cannot change to {profile!r}")
            self.profile, self.params, self.m = recorded(meta)
            if params is not None and params_json({**PROFILES[stored], **params}) != self.params:
                raise StoreError(f"{self.dir} was created with other manifest values; they cannot change")
            if meta.get("schema") != SCHEMA or meta.get("ruleset_digest") != self.m.ruleset.digest.hex():
                raise StoreError(f"{self.dir} is not a devnet for this ruleset")
            started = time.monotonic()
            self.world = self._restore()
            self.restart["seconds"] = round(time.monotonic() - started, 2)
        else:
            self.profile = profile or "dev"
            self.params = params_json({**PROFILES[self.profile], **(params or {})})
            self.m = manifest(self.profile, self.params)
            self.dir.mkdir(parents=True, exist_ok=True)
            self.world = World(self.m)
            self.world.mint(roles()["admin"], 10**12)
            marker.write_text(json.dumps({"schema": SCHEMA, "ruleset_digest": self.m.ruleset.digest.hex(),
                                          "profile": self.profile, "params": self.params,
                                          "note": "fake QU, synthetic identities; not a deployment"}))
        self._saved = len(self.world.journal) if (self.dir / JOURNAL).exists() else 0
        self.scout = scouting.Scout()

    # -- restore --------------------------------------------------------------

    def _journal_bytes(self) -> bytes:
        path = self.dir / JOURNAL
        raw = path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            cut = raw.rfind(b"\n") + 1
            try:
                json.loads(raw[cut:])
                raw += b"\n"                           # complete record, missing its newline
            except ValueError:
                raw = raw[:cut]                        # torn final record from a crash mid-append
            with open(path, "r+b") as f:
                f.truncate(cut)
                f.seek(cut)
                f.write(raw[cut:])
                f.flush()
        return raw

    def _restore(self) -> World:
        raw = self._journal_bytes()
        self._jhash, self._jbytes = hashlib.sha256(raw), len(raw)
        for name in (SNAPSHOT, SNAPSHOT_PREV):
            path = self.dir / name
            if not path.exists():
                continue
            try:
                w = self._from_snapshot(path, raw)
                self.restart["mode"] = f"snapshot {name}"
                return w
            except Exception as exc:                  # any doubt: the next snapshot, then a full replay
                self.restart["tried"].append(f"{name}: {exc}")
        records = _parse(raw)
        start = next(r for r in records if r["k"] == "start")
        w = World(self.m, tick=start["t"])
        apply_records(w, records, self._compact_every, self._compact)
        w.journal.clear()                              # everything replayed is already in the file
        self.restart["mode"] = "full replay"
        return w

    def _from_snapshot(self, path: Path, raw: bytes) -> World:
        blob = path.read_bytes()
        cut = blob.index(b"\n")
        head, payload = json.loads(blob[:cut]), blob[cut + 1:]
        if head.get("schema") != SNAPSHOT_SCHEMA:
            raise StoreError("not a snapshot")
        if head["code"] != code_fingerprint():
            raise StoreError("written by other contract code")
        if head["manifest"] != manifest_digest(self.m):
            raise StoreError("written for another manifest")
        n = head["journal_bytes"]
        if n > len(raw) or hashlib.sha256(raw[:n]).hexdigest() != head["journal_sha256"]:
            raise StoreError("the journal does not continue the snapshot's journal")
        if hashlib.sha256(payload).hexdigest() != head["payload_sha256"]:
            raise StoreError("payload hash differs")
        w = _world_from_state(self.m, pickle.loads(payload))
        c = w.contract
        if (w.tick, c.event_seq, c.event_digest.hex()) != (head["tick"], head["event_seq"], head["event_digest"]):
            raise StoreError("snapshot state does not match its header")
        bad = invariants.check(w)
        if bad:
            raise StoreError(f"snapshot state breaks invariants: {bad[:2]}")
        apply_records(w, _parse(raw[n:]), self._compact_every, self._compact)
        w.journal.clear()
        self.snapshot_tick = head["tick"]
        return w

    # -- saving ---------------------------------------------------------------

    def save(self, trim: bool = False):
        """Append new journal records. With `trim`, forget them in memory
        afterwards (a long-running arena); by default the in-memory journal
        keeps every record (samples and fixtures write it out whole)."""
        new = self.world.journal[self._saved:] if (self.dir / JOURNAL).exists() else self.world.journal
        data = "".join(json.dumps(rec, separators=(",", ":")) + "\n" for rec in new).encode()
        with open(self.dir / JOURNAL, "ab") as f:
            f.write(data)
        self._jhash.update(data)
        self._jbytes += len(data)
        if trim:
            self.world.journal.clear()
            self._saved = 0
        else:
            self._saved = len(self.world.journal)

    def transfer_external(self, frm: bytes, to: bytes, amount: int):
        """Move fake QU between two external wallets (a market payment),
        journalled so a replay rebuilds the balances. Not a contract call."""
        _move(self.world, frm, to, amount)
        self.world.journal.append({"k": "xfer", "t": self.world.tick, "from": frm.hex(), "to": to.hex(),
                                   "amount": amount})

    def snapshot(self) -> Path:
        """Checkpoint the event digest into the journal, save it, and write a
        verifiable snapshot of the world at that point (the previous one is kept)."""
        w, c = self.world, self.world.contract
        w.journal.append({"k": "digest", "t": w.tick, "event_seq": c.event_seq, "event_digest": c.event_digest.hex()})
        self.save(trim=True)
        payload = _world_state(w)
        head = {"schema": SNAPSHOT_SCHEMA, "profile": self.profile, "code": code_fingerprint(),
                "manifest": manifest_digest(self.m), "journal_bytes": self._jbytes,
                "journal_sha256": self._jhash.hexdigest(), "tick": w.tick, "event_seq": c.event_seq,
                "event_digest": c.event_digest.hex(), "payload_bytes": len(payload),
                "payload_sha256": hashlib.sha256(payload).hexdigest(),
                "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        path, tmp = self.dir / SNAPSHOT, self.dir / (SNAPSHOT + ".tmp")
        with open(tmp, "wb") as f:
            f.write(json.dumps(head).encode() + b"\n" + payload)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            path.replace(self.dir / SNAPSHOT_PREV)
        tmp.replace(path)
        self.snapshot_tick = w.tick
        return path

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
        return [{"offer_id": o.offer_id, "stake": o.amount, "format": o.series_format, "challenger": o.fighter_id,
                 "challenger_rating": self.c.fighters[o.fighter_id].lifetime}
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

    def _pruned(self, table: str, n: int):
        """A finished record compaction moved out of hot state (store.History), or None."""
        h = getattr(self.c, "history", None)
        return getattr(h, table).get(n) if h is not None else None

    def spend_outcome(self, ref: str, fid: bytes):
        kind, _, n = ref.partition(":")
        if kind == "cup":
            k = self.c.cups.get(int(n))
            if k is None:
                old = self._pruned("cups", int(n))
                if old is None:
                    return None
                status, champion, sponsorship, gross, entry_fee, fee_id, _entrants = old
                if status in ("CANCELLED", "ABORTED"):
                    return ("refund", entry_fee)
                if champion != fid:
                    return ("settled", 0)
                return ("settled", sponsorship + gross - gross * self.net.m.fees[fee_id].rake_bps // 10_000)
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
            if o is None:
                old = self._pruned("offers", int(n))
                if old is None:
                    return None
                status, contest_id, amount = old
                return ("contest", f"contest:{contest_id}") if status == "MATCHED" else ("refund", amount)
            if o.status == "OPEN":
                return None
            if o.status == "MATCHED":
                return ("contest", f"contest:{o.contest_id}")
            return ("refund", o.amount)
        contest = self.c.contests.get(int(n))
        if contest is None:
            old = self._pruned("contests", int(n))
            if old is None:
                return None
            kind_, winner, stake, fee_id, a, b = old
            r, me, fee = {"kind": kind_, "winner": winner}, "A" if a == fid else "B", self.net.m.fees[fee_id]
        elif contest.status != "DONE":
            return None
        else:
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
