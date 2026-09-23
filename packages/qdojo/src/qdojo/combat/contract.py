"""Reference combat contract: the bounded state machine the Qubic port implements.

Pure and deterministic. Time is the tick number passed in; money is integer
QU moved only through `ledger`; ownership comes from an `owner_of` callback
(the QPI asset query on chain, a dict in tests). The contract computes
combat itself from confirmed reveals; nobody signs a winner.

Entry points mirror the chain runtime:
  begin_tick(T)                            BEGIN_TICK
  call(invocator, frame, amount, T)        the single Dispatch user procedure
  end_tick(T)                              END_TICK: deadlines, resolution, matching, cups
Queries are plain methods returning bounded records.

Owning documents: protocol.md (bytes, windows, nonces, service gaps),
matchmaking.md, competition.md, spec.md §4-5 (identity, locks, money).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..hashing import sha256
from . import codec, matchmaking as mm, rating as rt
from .codec import Code, Format, Mode, Op
from .engine import new_fight, resolve_round, validate_plan
from .ledger import MAX_STAKE, FeeProfile, Ledger
from .rules import Ruleset
from .series import Series, bracket
from .types import FightState, Plan, PlanError, Result, RoundResult

IDLE, QUEUED, DUEL_OFFER, CONTEST, TOURNAMENT = "IDLE", "QUEUED", "DUEL_OFFER", "CONTEST", "TOURNAMENT"
ZERO = bytes(32)
EVENT_TAG_GENESIS = sha256(b"qdojo/combat/event/genesis/v1\0")


# ---- configuration ---------------------------------------------------------

@dataclass(frozen=True)
class Manifest:
    """Deployment values. Tests use the development fixture; production values
    come from a reviewed release manifest and are never guessed."""
    network_id: bytes
    contract_id: bytes
    admin: bytes
    ruleset: Ruleset
    timing: dict[int, tuple[int, int]]            # profile id -> (commit_ticks, reveal_ticks)
    fees: dict[int, FeeProfile]
    tiers: dict[int, int]                          # tier id -> stake per fighter
    genesis_tick: int = 0
    genesis_epoch: int = 1
    ticks_per_epoch: int = 10_000
    season_start_epoch: int = 1
    season_epochs: int = 4
    season_closeout_ticks: int = 1200
    max_fighters: int = 1024
    max_accounts: int = 2048
    max_offers: int = 64
    max_fights: int = 16
    max_cups: int = 4
    max_cup_entrants: int = 16
    event_ring: int = 2048
    match_interval: int = 4
    offer_lifetime: tuple[int, int] = (40, 1200)
    cooldown_ticks: int = 240
    faults_per_epoch: int = 3

    def epoch(self, tick: int) -> int:
        return self.genesis_epoch + (tick - self.genesis_tick) // self.ticks_per_epoch

    def season(self, tick: int) -> int:
        e = self.epoch(tick)
        if e < self.season_start_epoch:
            return 0
        return 1 + (e - self.season_start_epoch) // self.season_epochs

    def season_first_tick(self, season: int) -> int:
        epoch = self.season_start_epoch + (season - 1) * self.season_epochs
        return self.genesis_tick + (epoch - self.genesis_epoch) * self.ticks_per_epoch


def development_manifest(ruleset: Ruleset, admin: bytes, house: bytes, dev: bytes, share: bytes,
                         network_id: bytes = b"\xd0" * 32, contract_id: bytes = b"\xc0" * 32, **kw) -> Manifest:
    """spec.md's development fixture: one 1,000 QU tier, 500 bps rake split 6000/1000/3000."""
    fee = FeeProfile(1, 500, 6000, 1000, 3000, house, dev, share)
    return Manifest(network_id, contract_id, admin, ruleset, {1: (24, 12)}, {1: fee}, {1: 1000}, **kw)


# ---- records ---------------------------------------------------------------

@dataclass
class Fighter:
    fighter_id: bytes
    owner: bytes
    operator: bytes
    auth_version: int
    house_npc: bool = False
    lock: str = IDLE
    lock_ref: int = 0
    lifetime: int = rt.INITIAL
    season_rating: dict[int, int] = field(default_factory=dict)
    placement: int = 0
    faults: dict[int, int] = field(default_factory=dict)          # epoch -> terminal faults
    cooldown_until: int = 0
    suspended_epoch: int = 0
    record: dict[str, int] = field(default_factory=lambda: {"W": 0, "D": 0, "L": 0, "FW": 0, "FL": 0})
    season_stats: dict[int, dict] = field(default_factory=dict)

    def rating_in(self, season: int) -> int:
        return self.season_rating.get(season, rt.INITIAL)


@dataclass
class Fight:
    fight_id: int
    contest_id: int
    context: codec.FightContext
    context_digest: bytes
    state: FightState
    phase: str                     # COMMIT, REVEAL, DONE
    start_tick: int
    commit_last: int
    reveal_last: int
    commits: dict[str, bytes] = field(default_factory=dict)
    reveals: dict[str, tuple[bytes, Plan]] = field(default_factory=dict)
    rounds: list[dict] = field(default_factory=list)
    result: dict | None = None     # {"kind": COMBAT|FORFEIT|DOUBLE_FAULT|VOID, "winner": "A"|"B"|None, ...}

    def round_state_digest(self) -> bytes:
        s = self.state
        return codec.round_state_digest(self.context_digest, s.round_index, s.a, s.b)

    def slot_of(self, fighter_id: bytes) -> str | None:
        if fighter_id == self.context.participant_a.fighter_id:
            return "A"
        if fighter_id == self.context.participant_b.fighter_id:
            return "B"
        return None


@dataclass
class Contest:
    contest_id: int
    mode: Mode
    fmt: Format
    a: codec.Participant
    b: codec.Participant
    payers: dict[str, bytes]
    stake: int
    fee_profile_id: int
    timing_profile_id: int
    generation: int
    start_tick: int
    season: int
    series: Series
    cup_id: int = 0
    pairing_id: int = 0
    fights: list[int] = field(default_factory=list)
    status: str = "ACTIVE"         # ACTIVE, DONE
    result: dict | None = None
    replay: bool = False
    starts_key: tuple | None = None   # ranked pair/epoch counter to reverse on a service void
    settlement: dict | None = None    # credit deltas and rating changes, recorded once at termination


@dataclass
class CupEntry:
    fighter_id: bytes
    payer: bytes
    owner: bytes
    operator: bytes
    amount: int


@dataclass
class Pairing:
    pairing_id: int
    level: int
    a: bytes | None
    b: bytes | None
    checked: set = field(default_factory=set)
    contest_id: int = 0
    winner: bytes | None = None
    status: str = "SCHEDULED"      # SCHEDULED, PLAYING, REPLAY_WAIT, DONE, UNRESOLVED, EMPTY
    replay_at: int = 0
    played_combat: bool = False
    final_snapshot_owner: bytes | None = None


@dataclass
class Cup:
    cup_id: int
    descriptor: dict
    sponsor: bytes
    sponsorship: int
    generation: int
    created_tick: int
    entries: dict[bytes, CupEntry] = field(default_factory=dict)
    status: str = "REGISTRATION"   # REGISTRATION, RUNNING, COMPLETE, CANCELLED, ABORTED
    levels: int = 0
    level: int = 0
    level_start: int = 0
    postponed: set = field(default_factory=set)
    pending_reservation: bool = False
    reserved: int = 0
    pairings: dict[int, Pairing] = field(default_factory=dict)
    slots: list = field(default_factory=list)
    champion: bytes | None = None
    combat_fights: int = 0
    expiry_tick: int = 0
    next_pairing: int = 1


@dataclass
class CallResult:
    code: Code
    op: int = 0
    target: int = 0
    refunded: int = 0
    detail: str = ""
    data: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.code in (Code.OK, Code.DUPLICATE)


class Reject(Exception):
    def __init__(self, code: Code, detail: str = ""):
        super().__init__(f"{code.name}: {detail}")
        self.code, self.detail = code, detail


def _event_body(fields: tuple) -> bytes:
    """qdojo.combat.event-body.v1: each field as u8 tag then value.
    Tag 0: u64 LE. Tag 1: u16 length then raw bytes. Tag 2: u8 length then ASCII."""
    out = bytearray()
    for v in fields:
        if isinstance(v, bool) or isinstance(v, int):
            out += b"\0" + int(v).to_bytes(8, "little")
        elif isinstance(v, (bytes, bytearray)):
            out += b"\1" + len(v).to_bytes(2, "little") + bytes(v)
        else:
            s = str(v).encode("ascii")
            out += b"\2" + bytes([len(s)]) + s
    return bytes(out)


EVENT_TYPES = {name: i + 1 for i, name in enumerate((
    "SERVICE_GAP", "FIGHTER_REGISTERED", "OPERATOR_SET", "OFFER_OPEN", "OFFER_CLOSED", "MATCHED",
    "DUEL_ACCEPTED", "FIGHT_CREATED", "COMMITTED", "REVEALED", "ROUND_RESOLVED", "FIGHT_ENDED",
    "CONTEST_SETTLED", "RATING", "FAULT", "WITHDRAWN", "WITHDRAW_FAILED", "CUP_CREATED",
    "CUP_ENTRY", "CUP_BRACKET", "CUP_LEVEL", "CUP_PAIRING", "CUP_FINISHED", "ASSET_REGISTERED",
    "RULESET_RETIRED", "REFUND_CREDIT", "CUP_WITHDRAWN", "CUP_CHECKED_IN", "CUP_REPLAY_SCHEDULED"))}


# ---- the contract ----------------------------------------------------------

class CombatContract:
    def __init__(self, manifest: Manifest, owner_of: Callable[[bytes], bytes | None],
                 transfer: Callable[[bytes, int], bool], construction_tick: int):
        self.m = manifest
        self.owner_of = owner_of
        self.transfer = transfer
        self.ledger = Ledger()
        self.assets: dict[bytes, tuple[int, bool]] = {}        # fighter_id -> (registry_version, house_npc)
        self.fighters: dict[bytes, Fighter] = {}
        self.offers: dict[int, mm.Offer] = {}
        self.contests: dict[int, Contest] = {}
        self.fights: dict[int, Fight] = {}
        self.cups: dict[int, Cup] = {}
        self.nonces: dict[bytes, tuple[int, bytes, CallResult]] = {}
        self.pair_starts: dict[tuple[bytes, bytes, int], int] = {}
        self.pair_last: dict[tuple[bytes, bytes], int] = {}
        self.retired: set[bytes] = set()
        # Identities holding an account slot (nonce and credit). The admin and the
        # fee recipients hold theirs from construction, so rake always has a home.
        self.accounts: set[bytes] = {manifest.admin} | {x for f in manifest.fees.values()
                                                       for x in (f.house, f.dev, f.share)}
        self.next_id = {"offer": 1, "contest": 1, "fight": 1, "cup": 1}
        self.events: list[tuple] = []
        self.event_seq = 0
        self.event_digest = EVENT_TAG_GENESIS
        # Service heartbeat (protocol.md §5). The construction tick is exempt
        # from the missing-predecessor check.
        self.generation = 1
        self.last_serviced = construction_tick
        self.last_observed = construction_tick
        self.tick = construction_tick

    # -- service continuity -------------------------------------------------

    def ensure_service(self, t: int):
        if t < self.last_observed:
            raise ValueError("ticks run forward")
        if t == self.last_observed:
            return
        if t - 1 != self.last_serviced:
            self.generation += 1
            self._emit("SERVICE_GAP", self.generation, self.last_serviced, t)
        self.last_observed = t
        self.tick = t

    def begin_tick(self, t: int):
        self.ensure_service(t)

    # -- events -------------------------------------------------------------

    def _emit(self, kind: str, *fields):
        self.event_seq += 1
        body = _event_body(fields)
        self.event_digest = codec.event_digest(self.event_digest, self.event_seq, EVENT_TYPES[kind], body)
        self.events.append((self.event_seq, self.tick, kind, fields, self.event_digest))
        if len(self.events) > self.m.event_ring:
            del self.events[0]

    # -- dispatch -----------------------------------------------------------

    def call(self, invocator: bytes, frame: bytes, amount: int, t: int) -> CallResult:
        """One confirmed user transaction: invocator == originator, `amount` attached."""
        self.ensure_service(t)
        self.ledger.receive(amount)
        try:
            req = codec.decode_frame(frame)
        except codec.CodecError as exc:
            return self._reject(invocator, amount, Code[exc.code], 0, 0, str(exc))
        digest = sha256(frame)
        if req.op is Op.ADVANCE and req.nonce != 0:
            return self._reject(invocator, amount, Code.BAD_BODY, req.op, 0, "Advance uses nonce 0")
        if req.op is not Op.ADVANCE:
            # Only registry-backed users and existing account holders get state slots
            # (protocol.md §3); a stranger cannot fill nonce or credit storage.
            if not self._eligible(invocator, req):
                return self._reject(invocator, amount, Code.NOT_OWNER, req.op, 0, "no account slot for this identity")
            try:
                self._claim(invocator)
            except Reject as r:
                return self._reject(invocator, amount, r.code, req.op, 0, r.detail)
            prev = self.nonces.get(invocator)
            if prev is not None:
                last_nonce, last_digest, last_result = prev
                if req.nonce == last_nonce:
                    if last_digest == digest:
                        refunded = self._refund(invocator, amount)
                        return CallResult(Code.DUPLICATE, req.op, last_result.target, refunded,
                                          "identical retry", dict(last_result.data))
                    return self._reject(invocator, amount, Code.NONCE_CONFLICT, req.op, 0)
                if req.nonce < last_nonce:
                    return self._reject(invocator, amount, Code.STALE, req.op, 0)
            if req.nonce == 0:
                return self._reject(invocator, amount, Code.STALE, req.op, 0, "nonce 0 is reserved for Advance")
        handler = getattr(self, "_op_" + req.op.name.lower())
        try:
            result = handler(invocator, req.fields, amount, t)
        except Reject as r:
            return self._reject(invocator, amount, r.code, req.op, 0, r.detail)
        result.op = int(req.op)
        if req.op is not Op.ADVANCE:
            self.nonces[invocator] = (req.nonce, digest, result)
        self.ledger.check()
        return result

    def _reject(self, invocator, amount, code, op, target, detail=""):
        refunded = self._refund(invocator, amount)
        self.ledger.check()
        return CallResult(code, int(op), target, refunded, detail)

    def _eligible(self, who: bytes, req) -> bool:
        if who in self.accounts:
            return True
        if any(f.owner == who or f.operator == who for f in self.fighters.values()):
            return True
        if req.op is Op.REGISTER_FIGHTER:
            fid = req.fields["fighter_id"]
            return fid in self.assets and self.owner_of(fid) == who
        return False

    def _claim(self, *who: bytes):
        """Reserve account slots (nonce + credit) before accepting funds for them."""
        new = [w for w in dict.fromkeys(who) if w not in self.accounts]
        if len(self.accounts) + len(new) > self.m.max_accounts:
            raise Reject(Code.FULL, "account capacity")
        self.accounts.update(new)

    def _refund(self, who: bytes, amount: int) -> int:
        """Rejected attachments become withdrawal credit for account holders. An
        identity without a slot is paid straight back and never given one (so
        strangers cannot exhaust the account table); if that transfer fails the
        amount is still owed, as credit outside the slot table, never kept."""
        if not amount:
            return 0
        if who in self.accounts:
            self.ledger.refund_attachment(who, amount)
            self._emit("REFUND_CREDIT", who, amount)
            return amount
        self.ledger.balance -= amount
        if not self.transfer(who, amount):
            self.ledger.balance += amount
            self.ledger.refund_attachment(who, amount)
            self._emit("REFUND_CREDIT", who, amount)
        return amount

    def _need_zero(self, amount):
        if amount:
            raise Reject(Code.BAD_AMOUNT, "this operation takes no QU")

    # -- helpers ------------------------------------------------------------

    def _fighter(self, fid: bytes) -> Fighter:
        f = self.fighters.get(fid)
        if f is None:
            raise Reject(Code.UNKNOWN_FIGHTER)
        return f

    def _confirmed_owner(self, f: Fighter) -> bytes:
        """The live asset owner. Unknown ownership is never treated as the old owner."""
        owner = self.owner_of(f.fighter_id)
        if owner is None:
            raise Reject(Code.BAD_STATE, "asset ownership unavailable")
        return owner

    def _authorize(self, f: Fighter, invocator: bytes, auth_version: int, allow_owner=True):
        owner = self._confirmed_owner(f)
        if owner != f.owner:
            raise Reject(Code.NOT_OWNER, "asset changed hands; the new owner must register it")
        if auth_version != f.auth_version:
            raise Reject(Code.STALE_AUTH)
        if invocator != f.operator and not (allow_owner and invocator == f.owner):
            raise Reject(Code.NOT_OPERATOR)

    def _ranked_admissible(self, f: Fighter, t: int):
        if f.house_npc:
            raise Reject(Code.INCOMPATIBLE, "house NPCs never enter ranked")
        if t < f.cooldown_until:
            raise Reject(Code.COOLDOWN)
        if f.suspended_epoch == self.m.epoch(t):
            raise Reject(Code.COOLDOWN, "ranked admission suspended for this epoch")

    def _profiles(self, ruleset_digest, timing_id, fee_id):
        if ruleset_digest != self.m.ruleset.digest:
            raise Reject(Code.INCOMPATIBLE, "unknown ruleset")
        if ruleset_digest in self.retired:
            raise Reject(Code.RULESET_RETIRED)
        if timing_id not in self.m.timing or fee_id not in self.m.fees:
            raise Reject(Code.INCOMPATIBLE, "unknown timing or fee profile")

    def fights_in_use(self) -> int:
        """Slots held by non-cup fights plus every cup's level reservation."""
        live = sum(1 for c in self.contests.values() if c.status == "ACTIVE" and c.mode != Mode.CUP)
        return live + sum(c.reserved for c in self.cups.values() if c.status == "RUNNING")

    def _new_id(self, kind: str) -> int:
        n = self.next_id[kind]
        self.next_id[kind] = n + 1
        return n

    # -- registry -----------------------------------------------------------

    def _op_admin_register_asset(self, inv, f, amount, t):
        self._need_zero(amount)
        if inv != self.m.admin:
            raise Reject(Code.NOT_OWNER, "admin only")
        if f["house_npc"] not in (0, 1):
            raise Reject(Code.BAD_BODY)
        self.assets[f["fighter_id"]] = (f["registry_version"], bool(f["house_npc"]))
        self._emit("ASSET_REGISTERED", f["fighter_id"], f["registry_version"], f["house_npc"])
        return CallResult(Code.OK)

    def _op_admin_retire_ruleset(self, inv, f, amount, t):
        self._need_zero(amount)
        if inv != self.m.admin:
            raise Reject(Code.NOT_OWNER, "admin only")
        self.retired.add(f["ruleset_digest"])
        self._emit("RULESET_RETIRED", f["ruleset_digest"])
        return CallResult(Code.OK)

    def _op_register_fighter(self, inv, f, amount, t):
        self._need_zero(amount)
        fid = f["fighter_id"]
        asset = self.assets.get(fid)
        if asset is None or asset[0] != f["registry_version"]:
            raise Reject(Code.UNKNOWN_FIGHTER, "not a recognised registry asset")
        owner = self.owner_of(fid)
        if owner is None:
            raise Reject(Code.BAD_STATE, "asset ownership unavailable")
        if owner != inv:
            raise Reject(Code.NOT_OWNER)
        existing = self.fighters.get(fid)
        if existing is None:
            if len(self.fighters) >= self.m.max_fighters:
                raise Reject(Code.FULL)
            self.fighters[fid] = Fighter(fid, owner, owner, 1, house_npc=asset[1])
        elif existing.owner != owner:
            if existing.lock not in (IDLE, TOURNAMENT):
                raise Reject(Code.FIGHTER_BUSY)
            # The buyer binds the asset; rating, history and faults follow the fighter.
            existing.owner, existing.operator = owner, owner
            existing.auth_version += 1
        else:
            return CallResult(Code.DUPLICATE, detail="already registered to this owner")
        self._emit("FIGHTER_REGISTERED", fid, owner, self.fighters[fid].auth_version)
        return CallResult(Code.OK, data={"auth_version": self.fighters[fid].auth_version})

    def _op_set_operator(self, inv, f, amount, t):
        self._need_zero(amount)
        ftr = self._fighter(f["fighter_id"])
        owner = self._confirmed_owner(ftr)
        if inv != owner or owner != ftr.owner:
            raise Reject(Code.NOT_OWNER)
        if f["expected_auth_version"] != ftr.auth_version:
            raise Reject(Code.STALE_AUTH)
        if ftr.lock == TOURNAMENT:
            cup = self.cups.get(ftr.lock_ref)
            if cup is None or not self._between_pairings(cup, ftr.fighter_id):
                raise Reject(Code.FIGHTER_BUSY, "authority is fixed after check-in")
        elif ftr.lock != IDLE:
            raise Reject(Code.FIGHTER_BUSY)
        ftr.operator = f["new_operator"]
        ftr.auth_version += 1
        self._emit("OPERATOR_SET", ftr.fighter_id, ftr.operator, ftr.auth_version)
        return CallResult(Code.OK, data={"auth_version": ftr.auth_version})

    # -- ranked queue -------------------------------------------------------

    def _op_queue_enter(self, inv, f, amount, t):
        ftr = self._fighter(f["fighter_id"])
        self._authorize(ftr, inv, f["auth_version"])
        self._profiles(f["ruleset_digest"], f["timing_profile_id"], f["fee_profile_id"])
        tier = self.m.tiers.get(f["tier_id"])
        if tier is None:
            raise Reject(Code.INCOMPATIBLE, "unknown tier")
        if amount != tier:
            raise Reject(Code.BAD_AMOUNT, f"exactly {tier} QU")
        lo, hi = mm.MAX_GAP_RANGE
        if not lo <= f["max_gap"] <= hi:
            raise Reject(Code.BAD_BODY, "max_gap 100..200")
        life = f["expires_tick"] - t
        if not self.m.offer_lifetime[0] <= life <= self.m.offer_lifetime[1]:
            raise Reject(Code.BAD_BODY, "offer lifetime 40..1200 ticks")
        if ftr.lock != IDLE:
            raise Reject(Code.FIGHTER_BUSY)
        self._ranked_admissible(ftr, t)
        if sum(1 for o in self.offers.values() if o.status == "OPEN") >= self.m.max_offers:
            raise Reject(Code.FULL)
        self._claim(ftr.owner)                  # the payout recipient needs a credit slot
        oid = self._new_id("offer")
        offer = mm.Offer(oid, ftr.fighter_id, ftr.owner, ftr.operator, ftr.auth_version, inv, ftr.owner,
                         f["ruleset_digest"], f["timing_profile_id"], f["fee_profile_id"], f["tier_id"],
                         amount, ftr.lifetime, f["max_gap"], t, f["expires_tick"], self.generation)
        self.offers[oid] = offer
        self.ledger.escrow_offer(oid, inv, amount)
        ftr.lock, ftr.lock_ref = QUEUED, oid
        self._emit("OFFER_OPEN", oid, ftr.fighter_id, amount, f["expires_tick"])
        return CallResult(Code.OK, target=oid, data={"offer_id": oid})

    def _close_offer(self, o: mm.Offer, status: str):
        o.status = status
        self.ledger.release_offer(o.offer_id)
        ftr = self.fighters.get(o.fighter_id)
        if ftr and ftr.lock in (QUEUED, DUEL_OFFER) and ftr.lock_ref == o.offer_id:
            ftr.lock, ftr.lock_ref = IDLE, 0
        self._emit("OFFER_CLOSED", o.offer_id, status)

    def _cancel(self, inv, offer_id, kind, t):
        o = self.offers.get(offer_id)
        if o is None or o.kind != kind:
            raise Reject(Code.NOT_FOUND)
        live_owner = self.owner_of(o.fighter_id)
        if inv not in (o.owner, o.operator) and not (live_owner is not None and inv == live_owner):
            raise Reject(Code.NOT_OWNER)
        if o.status == "MATCHED":
            raise Reject(Code.ALREADY_MATCHED)
        if o.status != "OPEN":
            return CallResult(Code.DUPLICATE, target=offer_id, detail=o.status)
        self._close_offer(o, "CANCELLED")
        return CallResult(Code.OK, target=offer_id)

    def _op_queue_cancel(self, inv, f, amount, t):
        self._need_zero(amount)
        return self._cancel(inv, f["offer_id"], "RANKED", t)

    def _still_valid(self, o: mm.Offer) -> bool:
        ftr = self.fighters.get(o.fighter_id)
        owner = self.owner_of(o.fighter_id)
        return (ftr is not None and owner is not None and owner == o.owner == ftr.owner
                and ftr.operator == o.operator and ftr.auth_version == o.auth_version
                and ftr.lock_ref == o.offer_id)

    def _matching(self, t: int):
        epoch = self.m.epoch(t)

        def key(x, y):
            return (min(x, y), max(x, y))
        facts = mm.Facts(
            tick=t, generation=self.generation, still_valid=self._still_valid,
            is_npc=lambda fid: self.fighters[fid].house_npc,
            in_cooldown=lambda fid: t < self.fighters[fid].cooldown_until
            or self.fighters[fid].suspended_epoch == epoch,
            pair_starts=lambda x, y: self.pair_starts.get(key(x, y) + (epoch,), 0),
            pair_last_result=lambda x, y: self.pair_last.get(key(x, y)),
            capacity_left=lambda: self.m.max_fights - self.fights_in_use())

        def invalid(o):
            self._close_offer(o, "EXPIRED" if t >= o.expires_tick else "INVALIDATED")

        def match(x, y):
            x.status = y.status = "MATCHED"
            k = key(x.fighter_id, y.fighter_id) + (epoch,)
            self.pair_starts[k] = self.pair_starts.get(k, 0) + 1
            self._emit("MATCHED", x.offer_id, y.offer_id)
            self._start_contest(Mode.RANKED, Format.SINGLE, x, y, t, starts_key=k)
        return mm.matching_pass(list(self.offers.values()), facts, invalid, match)

    def _participant(self, o: mm.Offer, season: int) -> codec.Participant:
        ftr = self.fighters[o.fighter_id]
        return codec.Participant(o.fighter_id, o.owner, o.operator, o.auth_version, o.payout_recipient,
                                 ftr.lifetime, ftr.rating_in(season))

    def _start_contest(self, mode, fmt, x: mm.Offer, y: mm.Offer, t: int, starts_key=None,
                       cup_id=0, pairing_id=0) -> Contest:
        if x.fighter_id > y.fighter_id:
            x, y = y, x
        season = self.m.season(t) if mode == Mode.RANKED else 0
        cid = self._new_id("contest")
        contest = Contest(cid, mode, fmt, self._participant(x, season), self._participant(y, season),
                          {"A": x.payer, "B": y.payer}, x.amount, x.fee_profile_id, x.timing_profile_id,
                          self.generation, t, season, Series.of(fmt), cup_id, pairing_id)
        contest.starts_key = starts_key
        self.contests[cid] = contest
        if x.offer_id and y.offer_id:
            self.ledger.offers_to_contest(cid, (x.offer_id, y.offer_id))
            x.contest_id = y.contest_id = cid
        for o in (x, y):
            ftr = self.fighters[o.fighter_id]
            if mode != Mode.CUP:
                ftr.lock, ftr.lock_ref = CONTEST, cid
        self._new_fight(contest, t)
        return contest

    def _new_fight(self, contest: Contest, t: int):
        fid = self._new_id("fight")
        commit, reveal = self.m.timing[contest.timing_profile_id]
        fee = self.m.fees[contest.fee_profile_id]
        ctx = codec.FightContext(
            self.m.network_id, self.m.contract_id, contest.contest_id, fid, contest.mode, contest.fmt,
            contest.cup_id, contest.season, t, self.m.ruleset.digest, commit, reveal, fee.id,
            contest.stake, fee.rake_bps, fee.house_bps, fee.dev_bps, fee.share_bps,
            fee.house, fee.dev, fee.share, contest.a, contest.b)
        fight = Fight(fid, contest.contest_id, ctx, ctx.digest(), new_fight(self.m.ruleset), "COMMIT",
                      t, t + commit, t + commit + reveal)
        self.fights[fid] = fight
        contest.fights.append(fid)
        self._emit("FIGHT_CREATED", fid, contest.contest_id, t, fight.commit_last, fight.reveal_last)

    # -- duels --------------------------------------------------------------

    def _op_duel_offer(self, inv, f, amount, t):
        ftr = self._fighter(f["fighter_id"])
        self._authorize(ftr, inv, f["auth_version"])
        self._profiles(f["ruleset_digest"], f["timing_profile_id"], f["fee_profile_id"])
        opp = self._fighter(f["opponent_id"])
        if opp.fighter_id == ftr.fighter_id:
            raise Reject(Code.INCOMPATIBLE)
        if f["format"] not in (0, 1, 2):
            raise Reject(Code.BAD_BODY, "format 0..2")
        if not min(self.m.tiers.values()) <= f["stake"] <= MAX_STAKE:
            raise Reject(Code.BAD_AMOUNT, "stake outside the enabled range")
        if amount != f["stake"]:
            raise Reject(Code.BAD_AMOUNT, "attach exactly the stake")
        life = f["expires_tick"] - t
        if not self.m.offer_lifetime[0] <= life <= self.m.offer_lifetime[1]:
            raise Reject(Code.BAD_BODY, "offer lifetime 40..1200 ticks")
        if ftr.lock != IDLE:
            raise Reject(Code.FIGHTER_BUSY)
        if t < ftr.cooldown_until:
            raise Reject(Code.COOLDOWN)
        if sum(1 for o in self.offers.values() if o.status == "OPEN") >= self.m.max_offers:
            raise Reject(Code.FULL)
        self._claim(ftr.owner)
        oid = self._new_id("offer")
        o = mm.Offer(oid, ftr.fighter_id, ftr.owner, ftr.operator, ftr.auth_version, inv, ftr.owner,
                     f["ruleset_digest"], f["timing_profile_id"], f["fee_profile_id"], 0, amount,
                     ftr.lifetime, 0, t, f["expires_tick"], self.generation, kind="DUEL",
                     opponent_id=opp.fighter_id, series_format=f["format"])
        self.offers[oid] = o
        self.ledger.escrow_offer(oid, inv, amount)
        ftr.lock, ftr.lock_ref = DUEL_OFFER, oid
        self._emit("OFFER_OPEN", oid, ftr.fighter_id, amount, f["expires_tick"])
        return CallResult(Code.OK, target=oid, data={"offer_id": oid})

    def _op_duel_cancel(self, inv, f, amount, t):
        self._need_zero(amount)
        return self._cancel(inv, f["offer_id"], "DUEL", t)

    def _op_duel_accept(self, inv, f, amount, t):
        o = self.offers.get(f["offer_id"])
        if o is None or o.kind != "DUEL":
            raise Reject(Code.NOT_FOUND)
        if o.status == "MATCHED":
            raise Reject(Code.ALREADY_MATCHED)
        if o.status != "OPEN":
            raise Reject(Code.EXPIRED, o.status)
        if t >= o.expires_tick or o.generation != self.generation:
            self._close_offer(o, "EXPIRED" if t >= o.expires_tick else "INVALIDATED")
            raise Reject(Code.EXPIRED)
        if not self._still_valid(o):
            self._close_offer(o, "INVALIDATED")
            raise Reject(Code.INCOMPATIBLE, "the challenger changed hands or authority")
        if f["fighter_id"] != o.opponent_id:
            raise Reject(Code.INCOMPATIBLE, "not the named opponent")
        d = self._fighter(f["fighter_id"])
        self._authorize(d, inv, f["auth_version"])
        if d.lock != IDLE:
            raise Reject(Code.FIGHTER_BUSY)
        if t < d.cooldown_until:
            raise Reject(Code.COOLDOWN)
        if amount != o.amount:
            raise Reject(Code.BAD_AMOUNT, "attach exactly the challenger's stake")
        if self.fights_in_use() >= self.m.max_fights:
            raise Reject(Code.FULL)
        self._claim(d.owner)
        mine = self._new_id("offer")
        accept = mm.Offer(mine, d.fighter_id, d.owner, d.operator, d.auth_version, inv, d.owner,
                          o.ruleset_digest, o.timing_profile_id, o.fee_profile_id, 0, amount,
                          d.lifetime, 0, t, o.expires_tick, self.generation, status="MATCHED", kind="DUEL")
        self.offers[mine] = accept
        self.ledger.escrow_offer(mine, inv, amount)
        o.status = "MATCHED"
        contest = self._start_contest(Mode.DUEL, Format(o.series_format), o, accept, t)
        self._emit("DUEL_ACCEPTED", o.offer_id, contest.contest_id)
        return CallResult(Code.OK, target=contest.contest_id, data={"contest_id": contest.contest_id})

    # -- commit / reveal ----------------------------------------------------

    def _fight_for(self, f, inv, t):
        fight = self.fights.get(f["fight_id"])
        if fight is None:
            raise Reject(Code.NOT_FOUND)
        if fight.phase == "DONE":
            raise Reject(Code.TERMINAL)
        slot = fight.slot_of(f["fighter_id"])
        if slot is None:
            raise Reject(Code.UNKNOWN_FIGHTER, "not in this fight")
        part = fight.context.participant_a if slot == "A" else fight.context.participant_b
        if inv != part.operator:
            raise Reject(Code.NOT_OPERATOR)
        if f["auth_version"] != part.auth_version:
            raise Reject(Code.STALE_AUTH)
        if f["round_index"] != fight.state.round_index:
            raise Reject(Code.BAD_STATE, "wrong round")
        if f["round_state_digest"] != fight.round_state_digest():
            raise Reject(Code.BAD_STATE, "round-start state differs")
        return fight, slot, part

    def _op_commit(self, inv, f, amount, t):
        self._need_zero(amount)
        fight, slot, _ = self._fight_for(f, inv, t)
        if fight.phase != "COMMIT" or t <= fight.start_tick:
            raise Reject(Code.WRONG_PHASE)
        if t > fight.commit_last:
            raise Reject(Code.LATE)
        have = fight.commits.get(slot)
        if have is not None:
            if have == f["commitment"]:
                return CallResult(Code.DUPLICATE, target=fight.fight_id)
            raise Reject(Code.ALREADY_COMMITTED)
        fight.commits[slot] = f["commitment"]
        self._emit("COMMITTED", fight.fight_id, fight.state.round_index, f["fighter_id"], f["commitment"])
        return CallResult(Code.OK, target=fight.fight_id)

    def _op_reveal(self, inv, f, amount, t):
        self._need_zero(amount)
        fight, slot, part = self._fight_for(f, inv, t)
        if fight.phase == "COMMIT" and t <= fight.commit_last:
            raise Reject(Code.WRONG_PHASE)
        if fight.phase != "REVEAL":
            raise Reject(Code.WRONG_PHASE)
        if t > fight.reveal_last:
            raise Reject(Code.LATE)
        plan: Plan = f["plan"]
        expected = codec.commitment(
            network_id=self.m.network_id, contract_id=self.m.contract_id, fight_id=fight.fight_id,
            round_index=fight.state.round_index, context_digest=fight.context_digest,
            round_state_digest=fight.round_state_digest(), fighter_id=part.fighter_id,
            operator=part.operator, auth_version=part.auth_version, salt=f["salt"], plan=plan)
        if fight.commits.get(slot) != expected:
            raise Reject(Code.BAD_COMMITMENT)
        state = fight.state.a if slot == "A" else fight.state.b
        try:
            validate_plan(self.m.ruleset, state, plan)
        except PlanError as exc:
            raise Reject(Code.BAD_PLAN, str(exc)) from None
        if slot in fight.reveals:
            if fight.reveals[slot] == (f["salt"], plan):
                return CallResult(Code.DUPLICATE, target=fight.fight_id)
            raise Reject(Code.ALREADY_REVEALED)
        fight.reveals[slot] = (f["salt"], plan)
        self._emit("REVEALED", fight.fight_id, fight.state.round_index, part.fighter_id,
                   f["salt"], codec.encode_plan(plan))
        return CallResult(Code.OK, target=fight.fight_id)

    # -- public progress ----------------------------------------------------

    def _op_advance(self, inv, f, amount, t):
        """Public, nonce 0. Only mechanically eligible cleanup; never picks a winner."""
        self._need_zero(amount)
        kind, target = f["target_kind"], f["target_id"]
        if kind == 1:
            o = self.offers.get(target)
            if o is None:
                raise Reject(Code.NOT_FOUND)
            if o.status == "OPEN" and (t >= o.expires_tick or o.generation != self.generation):
                self._close_offer(o, "EXPIRED" if t >= o.expires_tick else "INVALIDATED")
            return CallResult(Code.OK, target=target, data={"status": o.status})
        if kind == 2:
            fight = self.fights.get(target)
            if fight is None:
                raise Reject(Code.NOT_FOUND)
            return CallResult(Code.OK, target=target, data={"phase": fight.phase, "result": fight.result})
        if kind == 3:
            cup = self.cups.get(target)
            if cup is None:
                raise Reject(Code.NOT_FOUND)
            return CallResult(Code.OK, target=target, data={"status": cup.status})
        raise Reject(Code.BAD_BODY, "target_kind 1 offer, 2 fight, 3 cup")

    # -- withdrawal ---------------------------------------------------------

    def _op_withdraw(self, inv, f, amount, t):
        self._need_zero(amount)
        value = self.ledger.begin_withdraw(inv)
        if not value:
            return CallResult(Code.OK, data={"amount": 0})
        if not self.transfer(inv, value):
            self.ledger.restore(inv, value)
            self._emit("WITHDRAW_FAILED", inv, value)
            raise Reject(Code.TRANSFER_FAILED)
        self._emit("WITHDRAWN", inv, value)
        return CallResult(Code.OK, data={"amount": value})

    # -- END_TICK -----------------------------------------------------------

    def end_tick(self, t: int):
        self.ensure_service(t)
        # Objective service gaps void unfinished work captured under an older generation.
        for c in [c for c in self.contests.values() if c.status == "ACTIVE" and c.generation != self.generation]:
            if c.mode != Mode.CUP:
                self._void_contest(c, t)
        for o in [o for o in self.offers.values() if o.status == "OPEN" and o.generation != self.generation]:
            self._close_offer(o, "INVALIDATED")
        for cup in [c for c in self.cups.values() if c.status in ("REGISTRATION", "RUNNING")
                    and c.generation != self.generation]:
            self._abort_cup(cup, t, "SERVICE_VOID")

        processed = 0
        for fight in sorted((x for x in self.fights.values() if x.phase != "DONE"), key=lambda x: x.fight_id):
            if processed >= self.m.max_fights:
                break
            processed += 1
            self._fight_tick(fight, t)
        for o in [o for o in self.offers.values() if o.status == "OPEN" and o.kind == "DUEL" and t >= o.expires_tick]:
            self._close_offer(o, "EXPIRED")
        if t % self.m.match_interval == 0 and sum(1 for o in self.offers.values()
                                                  if o.status == "OPEN" and o.kind == "RANKED") >= 2:
            self._matching(t)
        for cup in sorted(self.cups.values(), key=lambda c: c.cup_id):
            self._cup_tick(cup, t)
        self.last_serviced = t
        self.ledger.check()

    def _fight_tick(self, fight: Fight, t: int):
        if fight.phase == "COMMIT" and t == fight.commit_last:
            have = set(fight.commits)
            if have == {"A", "B"}:
                fight.phase = "REVEAL"
            elif have:
                self._end_fight(fight, t, {"kind": "FORFEIT", "winner": have.pop(), "stage": "COMMIT"})
            else:
                self._end_fight(fight, t, {"kind": "DOUBLE_FAULT", "winner": None, "stage": "COMMIT"})
            return
        if fight.phase != "REVEAL":
            return
        if set(fight.reveals) == {"A", "B"}:
            self._resolve(fight, t)
        elif t == fight.reveal_last:
            have = set(fight.reveals)
            if have:
                self._end_fight(fight, t, {"kind": "FORFEIT", "winner": have.pop(), "stage": "REVEAL"})
            else:
                self._end_fight(fight, t, {"kind": "DOUBLE_FAULT", "winner": None, "stage": "REVEAL"})

    def _resolve(self, fight: Fight, t: int):
        (salt_a, plan_a), (salt_b, plan_b) = fight.reveals["A"], fight.reveals["B"]
        res: RoundResult = resolve_round(self.m.ruleset, fight.state, plan_a, plan_b)
        fight.rounds.append({"round_index": fight.state.round_index, "tick": t,
                             "start": fight.state, "round_state_digest": fight.round_state_digest(),
                             "commitments": dict(fight.commits),
                             "salts": {"A": salt_a, "B": salt_b},
                             "plans": {"A": codec.encode_plan(plan_a), "B": codec.encode_plan(plan_b)},
                             "executed": res.executed, "end": res.end})
        self._emit("ROUND_RESOLVED", fight.fight_id, fight.state.round_index, res.executed,
                   codec.encode_state(res.end.a) + codec.encode_state(res.end.b))
        fight.state = res.end
        fight.commits.clear()
        fight.reveals.clear()
        if res.end.outcome is not None:
            o = res.end.outcome
            self._end_fight(fight, t, {"kind": "COMBAT", "winner": o.winner, "result": o.result.value})
            return
        commit, reveal = fight.context.commit_ticks, fight.context.reveal_ticks
        fight.phase, fight.start_tick = "COMMIT", t
        fight.commit_last, fight.reveal_last = t + commit, t + commit + reveal

    def _end_fight(self, fight: Fight, t: int, result: dict):
        fight.phase, fight.result = "DONE", {**result, "tick": t}
        self._emit("FIGHT_ENDED", fight.fight_id, result["kind"], result.get("winner") or "-")
        contest = self.contests[fight.contest_id]
        if result["kind"] == "COMBAT":
            if contest.mode == Mode.CUP:
                self.cups[contest.cup_id].combat_fights += 1
            contest.series.record(result["winner"])
            if not contest.series.done:
                self._new_fight(contest, t)
                return
            self._finish_contest(contest, t, {"kind": "COMBAT", "winner": contest.series.winner,
                                              "last_result": result.get("result")})
        else:
            self._finish_contest(contest, t, result)

    # -- settlement ---------------------------------------------------------

    def _finish_contest(self, c: Contest, t: int, result: dict):
        c.status, c.result = "DONE", {**result, "tick": t}
        fa, fb = self.fighters[c.a.fighter_id], self.fighters[c.b.fighter_id]
        side = {"A": c.a, "B": c.b}
        kind, winner = result["kind"], result.get("winner")
        credits_before = dict(self.ledger.credits)
        ratings_before = {"A": (fa.lifetime, fa.rating_in(c.season)), "B": (fb.lifetime, fb.rating_in(c.season))}
        if kind == "DOUBLE_FAULT":
            self._fault(fa, t)
            self._fault(fb, t)
        elif kind == "FORFEIT":
            self._fault(fb if winner == "A" else fa, t)
        if c.mode in (Mode.RANKED, Mode.DUEL):
            if kind in ("COMBAT", "FORFEIT") and winner is not None:
                self.ledger.settle_win(c.contest_id, side[winner].payout_recipient, self.m.fees[c.fee_profile_id])
            else:
                self.ledger.settle_refund(c.contest_id)
        if c.mode == Mode.RANKED:
            self._rate(c, t, kind, winner)
            k = (min(fa.fighter_id, fb.fighter_id), max(fa.fighter_id, fb.fighter_id))
            self.pair_last[k] = t
        for ftr in (fa, fb):
            if c.mode != Mode.CUP and ftr.lock == CONTEST and ftr.lock_ref == c.contest_id:
                ftr.lock, ftr.lock_ref = IDLE, 0
        c.settlement = {
            "credits": {who: self.ledger.credits.get(who, 0) - credits_before.get(who, 0)
                        for who in set(self.ledger.credits) | set(credits_before)
                        if self.ledger.credits.get(who, 0) != credits_before.get(who, 0)},
            "ratings": {"A": {"lifetime": [ratings_before["A"][0], fa.lifetime],
                              "season": [ratings_before["A"][1], fa.rating_in(c.season)]},
                        "B": {"lifetime": [ratings_before["B"][0], fb.lifetime],
                              "season": [ratings_before["B"][1], fb.rating_in(c.season)]}},
        }
        self._emit("CONTEST_SETTLED", c.contest_id, kind, winner or "-")
        if c.mode == Mode.CUP:
            self._cup_pairing_done(c, t)

    def _void_contest(self, c: Contest, t: int):
        """Objective service void: refund, no rating, no fault; reverse the pair start once."""
        for fid in c.fights:
            fight = self.fights[fid]
            if fight.phase != "DONE":
                fight.phase, fight.result = "DONE", {"kind": "VOID", "winner": None, "tick": t}
        c.status, c.result = "DONE", {"kind": "VOID", "winner": None, "tick": t}
        if c.mode in (Mode.RANKED, Mode.DUEL):
            self.ledger.settle_refund(c.contest_id)
        key = getattr(c, "starts_key", None)
        if key and self.pair_starts.get(key, 0) > 0:
            self.pair_starts[key] -= 1
        for fid in (c.a.fighter_id, c.b.fighter_id):
            ftr = self.fighters[fid]
            if ftr.lock == CONTEST and ftr.lock_ref == c.contest_id:
                ftr.lock, ftr.lock_ref = IDLE, 0
        self._emit("CONTEST_SETTLED", c.contest_id, "VOID", "-")

    def _fault(self, ftr: Fighter, t: int):
        e = self.m.epoch(t)
        ftr.faults[e] = ftr.faults.get(e, 0) + 1
        ftr.cooldown_until = max(ftr.cooldown_until, t + self.m.cooldown_ticks)
        if ftr.faults[e] >= self.m.faults_per_epoch:
            ftr.suspended_epoch = e
        self._emit("FAULT", ftr.fighter_id, ftr.faults[e])

    def _rate(self, c: Contest, t: int, kind: str, winner):
        """Ranked only: combat results (draws included) and unilateral forfeits."""
        if kind not in ("COMBAT", "FORFEIT"):
            return
        fa, fb = self.fighters[c.a.fighter_id], self.fighters[c.b.fighter_id]
        score = rt.DRAW if winner is None else rt.WIN if winner == "A" else rt.LOSS
        # Both from the snapshotted OLD ratings; the exclusive lock means nothing else moved them.
        fa.lifetime, fb.lifetime = rt.update(c.a.lifetime_rating, c.b.lifetime_rating, score)
        s = c.season
        if s:
            fa.season_rating[s], fb.season_rating[s] = rt.update(c.a.season_rating, c.b.season_rating, score)
        combat = kind == "COMBAT"
        for me, opp, mine in ((fa, fb, "A"), (fb, fa, "B")):
            won = winner == mine
            if combat:
                me.placement += 1
                me.record["W" if won else "D" if winner is None else "L"] += 1
            else:
                me.record["FW" if won else "FL"] += 1
            if s and combat:
                st = me.season_stats.setdefault(s, {"fights": 0, "wins": 0, "opponents": set(), "defeated": set(),
                                                    "final_epoch_fights": 0})
                st["fights"] += 1
                st["opponents"].add(opp.fighter_id)
                if won:
                    st["wins"] += 1
                    st["defeated"].add(opp.fighter_id)
                final_epoch = self.m.season_start_epoch + s * self.m.season_epochs - 1
                if self.m.epoch(c.start_tick) == final_epoch:
                    st["final_epoch_fights"] += 1
        self._emit("RATING", fa.fighter_id, fa.lifetime, fb.fighter_id, fb.lifetime)

    # -- cups ---------------------------------------------------------------

    def _op_admin_create_cup(self, inv, f, amount, t):
        if inv != self.m.admin:
            raise Reject(Code.NOT_OWNER, "admin only")
        self._profiles(f["ruleset_digest"], f["timing_profile_id"], f["fee_profile_id"])
        if sum(1 for c in self.cups.values() if c.status in ("REGISTRATION", "RUNNING")) >= self.m.max_cups:
            raise Reject(Code.FULL)
        if not 4 <= f["min_entrants"] <= f["max_entrants"] <= self.m.max_cup_entrants:
            raise Reject(Code.BAD_BODY, "entrants 4..16")
        if not 0 < f["entry_fee"] <= MAX_STAKE or f["registration_close"] <= t:
            raise Reject(Code.BAD_BODY)
        # Every scheduled boundary must fall on a tick END_TICK examines: check-in
        # ends at level_start+checkin-1, a postponed level retries at level_start-1.
        if f["checkin_ticks"] < 1 or f["first_level_delay"] < 2 or f["replay_delay"] < 1:
            raise Reject(Code.BAD_BODY)
        commit, reveal = self.m.timing[f["timing_profile_id"]]
        worst = f["checkin_ticks"] + 7 * 3 * (commit + reveal) + f["replay_delay"] + 3 * 3 * (commit + reveal) + 2
        if worst > f["level_ticks"]:
            raise Reject(Code.INCOMPATIBLE, f"a level needs {worst} ticks; the window is {f['level_ticks']}")
        cid = self._new_id("cup")
        cup = Cup(cid, dict(f), inv, amount, self.generation, t)
        self.cups[cid] = cup
        if amount:
            self.ledger.reserve_cup(cid, inv, amount)
        self._emit("CUP_CREATED", cid, f["entry_fee"], amount, f["registration_close"])
        return CallResult(Code.OK, target=cid, data={"cup_id": cid})

    def _cup(self, cup_id) -> Cup:
        cup = self.cups.get(cup_id)
        if cup is None:
            raise Reject(Code.NOT_FOUND)
        return cup

    def _represented(self, cup: Cup, owner: bytes, operator: bytes, exclude: bytes | None = None) -> bool:
        for e in cup.entries.values():
            if e.fighter_id == exclude or not self._alive_in_cup(cup, e.fighter_id):
                continue
            ftr = self.fighters[e.fighter_id]
            if owner in (ftr.owner, ftr.operator) or operator in (ftr.owner, ftr.operator):
                return True
        return False

    def _alive_in_cup(self, cup: Cup, fid: bytes) -> bool:
        if cup.status == "REGISTRATION":
            return fid in cup.entries
        return fid in cup.slots

    def _op_cup_register(self, inv, f, amount, t):
        cup = self._cup(f["cup_id"])
        if cup.status != "REGISTRATION" or t >= cup.descriptor["registration_close"]:
            raise Reject(Code.WRONG_PHASE)
        ftr = self._fighter(f["fighter_id"])
        self._authorize(ftr, inv, f["auth_version"])
        if ftr.house_npc:
            raise Reject(Code.INCOMPATIBLE, "house NPCs do not enter cups")
        if amount != cup.descriptor["entry_fee"]:
            raise Reject(Code.BAD_AMOUNT)
        if ftr.lock != IDLE:
            raise Reject(Code.FIGHTER_BUSY)
        if t < ftr.cooldown_until:
            raise Reject(Code.COOLDOWN)
        if len(cup.entries) >= cup.descriptor["max_entrants"]:
            raise Reject(Code.FULL)
        if self._represented(cup, ftr.owner, ftr.operator):
            raise Reject(Code.INCOMPATIBLE, "one fighter per owner/operator")
        self._claim(ftr.owner)
        cup.entries[ftr.fighter_id] = CupEntry(ftr.fighter_id, inv, ftr.owner, ftr.operator, amount)
        self.ledger.reserve_cup(cup.cup_id, inv, amount)
        ftr.lock, ftr.lock_ref = TOURNAMENT, cup.cup_id
        self._emit("CUP_ENTRY", cup.cup_id, ftr.fighter_id, amount)
        return CallResult(Code.OK, target=cup.cup_id)

    def _op_cup_withdraw(self, inv, f, amount, t):
        self._need_zero(amount)
        cup = self._cup(f["cup_id"])
        if cup.status != "REGISTRATION" or t >= cup.descriptor["registration_close"]:
            raise Reject(Code.WRONG_PHASE, "entries are part of the prize after the roster locks")
        e = cup.entries.get(f["fighter_id"])
        if e is None:
            raise Reject(Code.NOT_FOUND)
        ftr = self.fighters[e.fighter_id]
        if inv not in (ftr.owner, ftr.operator, e.payer):
            raise Reject(Code.NOT_OWNER)
        del cup.entries[e.fighter_id]
        self.ledger.release_cup_entry(cup.cup_id, e.payer, e.amount)
        ftr.lock, ftr.lock_ref = IDLE, 0
        self._emit("CUP_WITHDRAWN", cup.cup_id, e.fighter_id, e.payer, e.amount)
        return CallResult(Code.OK, target=cup.cup_id)

    def _between_pairings(self, cup: Cup, fid: bytes) -> bool:
        if cup.status == "REGISTRATION":
            return True
        for p in cup.pairings.values():
            if fid in (p.a, p.b) and p.status in ("PLAYING", "REPLAY_WAIT"):
                return False
            if fid in (p.a, p.b) and p.status == "SCHEDULED" and fid in p.checked:
                return False
        return True

    def _op_cup_check_in(self, inv, f, amount, t):
        self._need_zero(amount)
        cup = self._cup(f["cup_id"])
        p = cup.pairings.get(f["pairing_id"])
        if cup.status != "RUNNING" or p is None or p.status != "SCHEDULED":
            raise Reject(Code.WRONG_PHASE)
        if not cup.level_start <= t < cup.level_start + cup.descriptor["checkin_ticks"] or p.level != cup.level:
            raise Reject(Code.WRONG_PHASE, "outside the check-in window")
        fid = f["fighter_id"]
        if fid not in (p.a, p.b):
            raise Reject(Code.UNKNOWN_FIGHTER)
        ftr = self._fighter(fid)
        self._authorize(ftr, inv, f["auth_version"])
        if self._represented(cup, ftr.owner, ftr.operator, exclude=fid):
            raise Reject(Code.INCOMPATIBLE, "owner/operator already represented in this cup")
        if fid in p.checked:
            return CallResult(Code.DUPLICATE, target=p.pairing_id)
        if t < ftr.cooldown_until:
            raise Reject(Code.COOLDOWN, "cup check-in observes the fault cooldown")
        self._claim(ftr.owner)                  # a transferred finalist's owner may be new
        p.checked.add(fid)
        self._emit("CUP_CHECKED_IN", cup.cup_id, p.pairing_id, fid)
        return CallResult(Code.OK, target=p.pairing_id)

    def _cup_tick(self, cup: Cup, t: int):
        d = cup.descriptor
        if cup.status == "REGISTRATION" and t >= d["registration_close"]:
            self._lock_roster(cup, t)
            return
        if cup.status != "RUNNING":
            return
        if t >= cup.expiry_tick:
            self._abort_cup(cup, t, "EXPIRED")
            return
        if cup.pending_reservation:
            # A postponed level retries its reservation just before its check-in opens.
            if t == cup.level_start - 1:
                self._schedule_level(cup, t)
            return
        checkin_end = cup.level_start + d["checkin_ticks"] - 1
        if t == checkin_end:
            self._start_level_pairings(cup, t)
        for p in cup.pairings.values():
            if p.level == cup.level and p.status == "REPLAY_WAIT" and t >= p.replay_at:
                self._start_pairing_contest(cup, p, t, replay=True)
        if t > checkin_end and all(p.status in ("DONE", "UNRESOLVED", "EMPTY")
                                   for p in cup.pairings.values() if p.level == cup.level):
            self._advance_level(cup, t)

    def _lock_roster(self, cup: Cup, t: int):
        d = cup.descriptor
        if len(cup.entries) < d["min_entrants"]:
            for e in cup.entries.values():
                ftr = self.fighters[e.fighter_id]
                ftr.lock, ftr.lock_ref = IDLE, 0
            self.ledger.refund_cup(cup.cup_id)
            cup.status = "CANCELLED"
            self._emit("CUP_FINISHED", cup.cup_id, "CANCELLED")
            return
        cup.slots = bracket([(self.fighters[f].lifetime, f) for f in cup.entries])
        size = len(cup.slots)
        cup.levels = size.bit_length() - 1
        cup.status = "RUNNING"
        cup.level = 0
        cup.level_start = t + d["first_level_delay"]
        cup.expiry_tick = cup.level_start + (cup.levels + 1) * d["level_ticks"] + d["level_ticks"]
        self._emit("CUP_BRACKET", cup.cup_id, sha256(b"".join(s or ZERO for s in cup.slots)))
        self._schedule_level(cup, t)

    def _schedule_level(self, cup: Cup, t: int):
        pairs = [(cup.slots[i], cup.slots[i + 1]) for i in range(0, len(cup.slots), 2)]
        need = sum(1 for a, b in pairs if a is not None and b is not None)
        free = self.m.max_fights - self.fights_in_use()
        if need > free:
            if cup.level in cup.postponed:
                self._abort_cup(cup, t, "CAPACITY")
                return
            cup.postponed.add(cup.level)
            cup.level_start += cup.descriptor["level_ticks"]
            cup.expiry_tick += cup.descriptor["level_ticks"]
            self._emit("CUP_LEVEL", cup.cup_id, cup.level, cup.level_start, 1)
            cup.pending_reservation = True
            return
        cup.pending_reservation = False
        cup.reserved = need
        for a, b in pairs:
            pid = cup.next_pairing
            cup.next_pairing += 1
            p = Pairing(pid, cup.level, a, b)
            if a is None or b is None:
                p.winner = a or b
                p.status = "DONE" if p.winner else "EMPTY"
            cup.pairings[pid] = p
        self._emit("CUP_LEVEL", cup.cup_id, cup.level, cup.level_start, 0)

    def _pairing_offer(self, cup: Cup, fid: bytes, t: int) -> mm.Offer:
        ftr = self.fighters[fid]
        return mm.Offer(0, fid, ftr.owner, ftr.operator, ftr.auth_version, ZERO, ftr.owner,
                        cup.descriptor["ruleset_digest"], cup.descriptor["timing_profile_id"],
                        cup.descriptor["fee_profile_id"], 0, 0, ftr.lifetime, 0, t, t, self.generation)

    def _start_level_pairings(self, cup: Cup, t: int):
        for p in cup.pairings.values():
            if p.level != cup.level or p.status != "SCHEDULED":
                continue
            both = {p.a, p.b} <= p.checked
            if both:
                self._start_pairing_contest(cup, p, t)
            elif p.checked:
                # The absent fighter forfeits the pairing; a missed check-in is
                # not a commit/reveal fault, so no cooldown is added.
                p.winner = next(iter(p.checked))
                p.status = "DONE"
                cup.reserved -= 1
            else:
                p.status = "UNRESOLVED"
                cup.reserved -= 1
            self._emit("CUP_PAIRING", cup.cup_id, p.pairing_id, p.status)

    def _start_pairing_contest(self, cup: Cup, p: Pairing, t: int, replay=False):
        final = cup.level == cup.levels - 1
        fmt = Format.BO5 if final else Format.BO3
        x, y = self._pairing_offer(cup, p.a, t), self._pairing_offer(cup, p.b, t)
        c = self._start_contest(Mode.CUP, fmt, x, y, t, cup_id=cup.cup_id, pairing_id=p.pairing_id)
        if replay:
            c.series = Series.replay()
            c.replay = True
        if final:
            p.final_snapshot_owner = None   # set per side at settlement from the contest snapshot
        p.contest_id = c.contest_id
        p.status = "PLAYING"

    def _cup_pairing_done(self, c: Contest, t: int):
        cup = self.cups[c.cup_id]
        p = cup.pairings[c.pairing_id]
        kind, winner = c.result["kind"], c.result.get("winner")
        side = {"A": c.a, "B": c.b}
        if kind in ("COMBAT", "FORFEIT") and winner is not None:
            p.winner = side[winner].fighter_id
            p.final_snapshot_owner = side[winner].payout_recipient
            p.status = "DONE"
        elif kind == "COMBAT" and not c.replay:
            p.status = "REPLAY_WAIT"
            p.replay_at = t + cup.descriptor["replay_delay"]
            self._emit("CUP_REPLAY_SCHEDULED", cup.cup_id, p.pairing_id, p.replay_at)
            return
        else:
            p.status = "UNRESOLVED"
        cup.reserved -= 1
        self._emit("CUP_PAIRING", cup.cup_id, p.pairing_id, p.status)

    def _advance_level(self, cup: Cup, t: int):
        level_pairs = sorted((p for p in cup.pairings.values() if p.level == cup.level), key=lambda p: p.pairing_id)
        survivors = [p.winner if p.status == "DONE" else None for p in level_pairs]
        for p in level_pairs:
            for fid in (p.a, p.b):
                if fid and fid != p.winner and fid in cup.entries:
                    ftr = self.fighters[fid]
                    if ftr.lock == TOURNAMENT and ftr.lock_ref == cup.cup_id:
                        ftr.lock, ftr.lock_ref = IDLE, 0
        cup.reserved = 0
        if cup.level == cup.levels - 1:
            final = level_pairs[0]
            if final.status == "DONE" and final.winner and cup.combat_fights > 0:
                self._pay_cup(cup, final, t)
            else:
                self._abort_cup(cup, t, "NO_CHAMPION")
            return
        cup.slots = survivors
        cup.level += 1
        cup.level_start += cup.descriptor["level_ticks"]
        if t >= cup.level_start:
            cup.level_start = t + 1
        self._schedule_level(cup, t)

    def _release_cup_locks(self, cup: Cup):
        for fid in cup.entries:
            ftr = self.fighters[fid]
            if ftr.lock == TOURNAMENT and ftr.lock_ref == cup.cup_id:
                ftr.lock, ftr.lock_ref = IDLE, 0

    def _pay_cup(self, cup: Cup, final: Pairing, t: int):
        entry_gross = sum(e.amount for e in cup.entries.values())
        recipient = final.final_snapshot_owner or self.fighters[final.winner].owner
        self.ledger.pay_cup(cup.cup_id, recipient, entry_gross, self.m.fees[cup.descriptor["fee_profile_id"]])
        cup.status, cup.champion = "COMPLETE", final.winner
        self._release_cup_locks(cup)
        self._emit("CUP_FINISHED", cup.cup_id, "COMPLETE", final.winner)

    def _abort_cup(self, cup: Cup, t: int, why: str):
        """Whole-event abort: every entry and the sponsorship go back, no rake, no trophy."""
        for c in self.contests.values():
            if c.cup_id == cup.cup_id and c.status == "ACTIVE":
                for fid in c.fights:
                    fight = self.fights[fid]
                    if fight.phase != "DONE":
                        fight.phase, fight.result = "DONE", {"kind": "VOID", "winner": None, "tick": t}
                c.status, c.result = "DONE", {"kind": "VOID", "winner": None, "tick": t}
        self.ledger.refund_cup(cup.cup_id)
        cup.status, cup.reserved = "ABORTED", 0
        self._release_cup_locks(cup)
        self._emit("CUP_FINISHED", cup.cup_id, "ABORTED", why)

    # -- seasons ------------------------------------------------------------

    def season_standings(self, season: int, t: int) -> dict:
        """Frozen only after the season's closeout interval; qualification per competition.md §3."""
        closes = self.m.season_first_tick(season + 1) + self.m.season_closeout_ticks
        rows = []
        for ftr in self.fighters.values():
            st = ftr.season_stats.get(season)
            if not st:
                continue
            qualified = (st["fights"] >= 12 and len(st["opponents"]) >= 4 and len(st["defeated"]) >= 3
                         and st["final_epoch_fights"] >= 3 and ftr.placement >= rt.PLACEMENT_FIGHTS
                         and ftr.suspended_epoch != self.m.epoch(t))
            rows.append({"fighter_id": ftr.fighter_id, "rating": ftr.rating_in(season),
                         "defeated": len(st["defeated"]), "wins": st["wins"], "fights": st["fights"],
                         "qualified": qualified})
        rows.sort(key=lambda r: (-r["rating"], -r["defeated"], -r["wins"], r["fighter_id"]))
        eligible = [r for r in rows if r["qualified"]]
        champion, playoff = None, []
        if eligible:
            top = (eligible[0]["rating"], eligible[0]["defeated"], eligible[0]["wins"])
            tied = [r for r in eligible if (r["rating"], r["defeated"], r["wins"]) == top]
            if len(tied) == 1:
                champion = tied[0]["fighter_id"]
            else:
                playoff = [r["fighter_id"] for r in tied]
        return {"season": season, "final": t >= closes, "standings": rows, "champion": champion,
                "playoff": playoff, "status": "CHAMPION" if champion else "PLAYOFF" if playoff else "NO_CHAMPION"}

    # -- queries ------------------------------------------------------------

    def events_page(self, after: int = 0, limit: int = 64) -> list[tuple]:
        return [e for e in self.events if e[0] > after][:min(limit, 64)]

    def fight_view(self, fight_id: int) -> dict:
        f = self.fights[fight_id]
        return {"fight_id": f.fight_id, "contest_id": f.contest_id, "phase": f.phase,
                "round_index": f.state.round_index, "state": f.state.to_json(),
                "context_digest": f.context_digest.hex(), "round_state_digest": f.round_state_digest().hex(),
                "commit_last": f.commit_last, "reveal_last": f.reveal_last,
                "committed": sorted(f.commits), "revealed": sorted(f.reveals), "result": f.result}
