"""Canonical combat bytes and SHA-256 digests (docs/protocol.md §2-3).

Everything that enters a hash is a fixed little-endian layout built here by
hand: no JSON text, no hex, no host struct padding. This module knows nothing
about transport; chain adapters send the 512-byte frames it produces.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

from ..hashing import sha256
from .types import NO_POWER, Action, FighterState, Plan, PlanError

TAG_CONTEXT = b"qdojo/combat/context/v1\0"
TAG_STATE = b"qdojo/combat/state/v1\0"
TAG_COMMIT = b"qdojo/combat/commit/v1\0"
TAG_EVENT = b"qdojo/combat/event/v1\0"

FRAME_LEN = 512
FRAME_MAGIC = b"QDC1"
FRAME_HEADER = 24
FRAME_SENTINEL = 0xA5
MAX_BODY = FRAME_LEN - FRAME_HEADER - 1     # 487
PLAN_NO_POWER = 255


class CodecError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class Mode(IntEnum):
    RANKED = 0
    DUEL = 1
    CUP = 2
    EXHIBITION = 3


class Format(IntEnum):
    SINGLE = 0
    BO3 = 1
    BO5 = 2


def _id32(value: bytes, name: str) -> bytes:
    if not isinstance(value, (bytes, bytearray)) or len(value) != 32:
        raise CodecError("BAD_BODY", f"{name} must be 32 bytes")
    return bytes(value)


def _u(value: int, width: int, name: str) -> bytes:
    if type(value) is not int or not 0 <= value < 1 << (8 * width):
        raise CodecError("BAD_BODY", f"{name}={value!r} does not fit u{8 * width}")
    return value.to_bytes(width, "little")


# ---- participants, context and state ---------------------------------------

@dataclass(frozen=True)
class Participant:
    fighter_id: bytes
    owner: bytes
    operator: bytes
    auth_version: int
    payout_recipient: bytes
    lifetime_rating: int
    season_rating: int

    def encode(self) -> bytes:
        return (_id32(self.fighter_id, "fighter_id") + _id32(self.owner, "owner")
                + _id32(self.operator, "operator") + _u(self.auth_version, 4, "auth_version")
                + _id32(self.payout_recipient, "payout_recipient")
                + _u(self.lifetime_rating, 2, "lifetime_rating") + _u(self.season_rating, 2, "season_rating"))


@dataclass(frozen=True)
class FightContext:
    network_id: bytes
    contract_id: bytes
    contest_id: int
    fight_id: int
    mode: Mode
    series_format: Format
    cup_id: int
    season_id: int
    start_tick: int
    ruleset_digest: bytes
    commit_ticks: int
    reveal_ticks: int
    fee_profile_id: int
    stake_per_fighter: int
    rake_bps: int
    house_bps: int
    dev_bps: int
    share_bps: int
    house_recipient: bytes
    dev_recipient: bytes
    share_recipient: bytes
    participant_a: Participant
    participant_b: Participant

    def encode(self) -> bytes:
        # Slot A is the smaller fighter ID as unsigned bytes (docs/combat.md §2).
        if not self.participant_a.fighter_id < self.participant_b.fighter_id:
            raise CodecError("BAD_BODY", "participants must be ordered by fighter_id")
        return b"".join((
            _id32(self.network_id, "network_id"), _id32(self.contract_id, "contract_id"),
            _u(self.contest_id, 8, "contest_id"), _u(self.fight_id, 8, "fight_id"),
            _u(int(Mode(self.mode)), 1, "mode"), _u(int(Format(self.series_format)), 1, "series_format"),
            _u(self.cup_id, 8, "cup_id"), _u(self.season_id, 4, "season_id"),
            _u(self.start_tick, 8, "start_tick"), _id32(self.ruleset_digest, "ruleset_digest"),
            _u(self.commit_ticks, 2, "commit_ticks"), _u(self.reveal_ticks, 2, "reveal_ticks"),
            _u(self.fee_profile_id, 4, "fee_profile_id"), _u(self.stake_per_fighter, 8, "stake_per_fighter"),
            _u(self.rake_bps, 2, "rake_bps"), _u(self.house_bps, 2, "house_bps"),
            _u(self.dev_bps, 2, "dev_bps"), _u(self.share_bps, 2, "share_bps"),
            _id32(self.house_recipient, "house_recipient"), _id32(self.dev_recipient, "dev_recipient"),
            _id32(self.share_recipient, "share_recipient"),
            self.participant_a.encode(), self.participant_b.encode(),
        ))

    def digest(self) -> bytes:
        return sha256(TAG_CONTEXT, self.encode())


def encode_state(s: FighterState) -> bytes:
    """Eight bytes: hp u16, stamina u16, opening, guard_streak, power_available, reserved 0."""
    return (_u(s.hp, 2, "hp") + _u(s.stamina, 2, "stamina") + _u(s.opening, 1, "opening")
            + _u(s.guard_streak, 1, "guard_streak") + _u(s.power_available, 1, "power_available") + b"\0")


def decode_state(data: bytes) -> FighterState:
    if len(data) != 8 or data[7] != 0:
        raise CodecError("BAD_STATE", "fighter state is eight bytes with a zero reserved byte")
    hp, stamina = struct.unpack_from("<HH", data)
    return FighterState(hp, stamina, data[4], data[5], data[6])


def round_state_bytes(context_digest: bytes, round_index: int, a: FighterState, b: FighterState) -> bytes:
    return _id32(context_digest, "context_digest") + _u(round_index, 1, "round_index") + encode_state(a) + encode_state(b)


def round_state_digest(context_digest: bytes, round_index: int, a: FighterState, b: FighterState) -> bytes:
    """Bound to the ROUND-START state, after any break recovery."""
    return sha256(TAG_STATE, round_state_bytes(context_digest, round_index, a, b))


# ---- plans and commitments -------------------------------------------------

def encode_plan(plan: Plan) -> bytes:
    slot = PLAN_NO_POWER if plan.power_slot == NO_POWER else plan.power_slot
    return bytes([int(a) for a in plan.actions] + [slot])


def decode_plan(data: bytes) -> Plan:
    if len(data) != 7:
        raise CodecError("BAD_PLAN", "a plan is seven bytes")
    slot = data[6]
    if slot != PLAN_NO_POWER and slot > 5:
        raise CodecError("BAD_PLAN", f"power_slot byte {slot}")
    try:
        return Plan.of(list(data[:6]), NO_POWER if slot == PLAN_NO_POWER else slot)
    except PlanError as exc:
        raise CodecError("BAD_PLAN", str(exc)) from None


def commitment_preimage(*, network_id: bytes, contract_id: bytes, fight_id: int, round_index: int,
                        context_digest: bytes, round_state_digest: bytes, fighter_id: bytes,
                        operator: bytes, auth_version: int, salt: bytes, plan: Plan) -> bytes:
    return b"".join((
        TAG_COMMIT, _id32(network_id, "network_id"), _id32(contract_id, "contract_id"),
        _u(fight_id, 8, "fight_id"), _u(round_index, 1, "round_index"),
        _id32(context_digest, "context_digest"), _id32(round_state_digest, "round_state_digest"),
        _id32(fighter_id, "fighter_id"), _id32(operator, "operator"),
        _u(auth_version, 4, "auth_version"), _id32(salt, "salt"), encode_plan(plan),
    ))


def commitment(**fields) -> bytes:
    return sha256(commitment_preimage(**fields))


def event_digest(previous: bytes, seq: int, event_type: int, body: bytes) -> bytes:
    return sha256(TAG_EVENT, _id32(previous, "previous_digest"), _u(seq, 8, "event_seq"),
                  _u(event_type, 2, "event_type"), body)


# ---- 512-byte request frames -----------------------------------------------

class Op(IntEnum):
    REGISTER_FIGHTER = 1
    SET_OPERATOR = 2
    QUEUE_ENTER = 3
    QUEUE_CANCEL = 4
    DUEL_OFFER = 5
    DUEL_ACCEPT = 6
    COMMIT = 7
    REVEAL = 8
    ADVANCE = 9
    WITHDRAW = 10
    CUP_REGISTER = 11
    CUP_WITHDRAW = 12
    CUP_CHECK_IN = 13
    DUEL_CANCEL = 14
    # Deployment administration (docs/protocol.md §8): authorised by the
    # manifest's admin identity only; cannot touch accepted contests or credits.
    ADMIN_REGISTER_ASSET = 100
    ADMIN_CREATE_CUP = 101
    ADMIN_RETIRE_RULESET = 102


# Field layouts per opcode (docs/protocol.md §3). Width 32 is a raw 32-byte
# field, 7 is a plan; every other width is an unsigned little-endian integer.
_ID, _PLAN = "id", "plan"
BODIES: dict[Op, tuple[tuple[str, object], ...]] = {
    Op.REGISTER_FIGHTER: (("fighter_id", _ID), ("registry_version", 4)),
    Op.SET_OPERATOR: (("fighter_id", _ID), ("new_operator", _ID), ("expected_auth_version", 4)),
    Op.QUEUE_ENTER: (("fighter_id", _ID), ("auth_version", 4), ("ruleset_digest", _ID),
                     ("timing_profile_id", 4), ("fee_profile_id", 4), ("tier_id", 2),
                     ("max_gap", 2), ("expires_tick", 8)),
    Op.QUEUE_CANCEL: (("offer_id", 8),),
    Op.DUEL_OFFER: (("fighter_id", _ID), ("auth_version", 4), ("opponent_id", _ID),
                    ("ruleset_digest", _ID), ("timing_profile_id", 4), ("fee_profile_id", 4),
                    ("stake", 8), ("format", 1), ("expires_tick", 8)),
    Op.DUEL_ACCEPT: (("offer_id", 8), ("fighter_id", _ID), ("auth_version", 4)),
    Op.COMMIT: (("fight_id", 8), ("round_index", 1), ("fighter_id", _ID), ("auth_version", 4),
                ("round_state_digest", _ID), ("commitment", _ID)),
    Op.REVEAL: (("fight_id", 8), ("round_index", 1), ("fighter_id", _ID), ("auth_version", 4),
                ("round_state_digest", _ID), ("salt", _ID), ("plan", _PLAN)),
    Op.ADVANCE: (("target_kind", 1), ("target_id", 8)),
    Op.WITHDRAW: (),
    Op.CUP_REGISTER: (("cup_id", 8), ("fighter_id", _ID), ("auth_version", 4)),
    Op.CUP_WITHDRAW: (("cup_id", 8), ("fighter_id", _ID)),
    Op.CUP_CHECK_IN: (("cup_id", 8), ("pairing_id", 8), ("fighter_id", _ID), ("auth_version", 4)),
    Op.DUEL_CANCEL: (("offer_id", 8),),
    Op.ADMIN_REGISTER_ASSET: (("fighter_id", _ID), ("registry_version", 4), ("house_npc", 1)),
    Op.ADMIN_CREATE_CUP: (("ruleset_digest", _ID), ("timing_profile_id", 4), ("fee_profile_id", 4),
                          ("entry_fee", 8), ("registration_close", 8), ("min_entrants", 1),
                          ("max_entrants", 1), ("level_ticks", 2), ("first_level_delay", 2),
                          ("checkin_ticks", 2), ("replay_delay", 2)),
    Op.ADMIN_RETIRE_RULESET: (("ruleset_digest", _ID),),
}


class Code(IntEnum):
    """Stable result codes (docs/protocol.md §6)."""
    OK = 0
    DUPLICATE = 1
    BAD_FRAME = 2
    BAD_OPCODE = 3
    BAD_BODY = 4
    BAD_AMOUNT = 5
    UNKNOWN_FIGHTER = 6
    NOT_OWNER = 7
    NOT_OPERATOR = 8
    STALE_AUTH = 9
    FIGHTER_BUSY = 10
    COOLDOWN = 11
    FULL = 12
    NONCE_CONFLICT = 13
    STALE = 14
    NOT_FOUND = 15
    EXPIRED = 16
    ALREADY_MATCHED = 17
    INCOMPATIBLE = 18
    RULESET_RETIRED = 19
    WRONG_PHASE = 20
    LATE = 21
    ALREADY_COMMITTED = 22
    BAD_STATE = 23
    BAD_COMMITMENT = 24
    BAD_PLAN = 25
    ALREADY_REVEALED = 26
    TERMINAL = 27
    SERVICE_VOID = 28
    TRANSFER_FAILED = 29


def _width(kind) -> int:
    return 32 if kind == _ID else 7 if kind == _PLAN else kind


def encode_body(op: Op, fields: dict) -> bytes:
    layout = BODIES[Op(op)]
    names = [n for n, _ in layout]
    if set(fields) != set(names):
        raise CodecError("BAD_BODY", f"{Op(op).name} takes exactly {names}")
    out = []
    for name, kind in layout:
        v = fields[name]
        if kind == _ID:
            out.append(_id32(v, name))
        elif kind == _PLAN:
            out.append(encode_plan(v))
        else:
            out.append(_u(v, kind, name))
    return b"".join(out)


def decode_body(op: Op, body: bytes) -> dict:
    layout = BODIES[op]
    if len(body) != sum(_width(k) for _, k in layout):
        raise CodecError("BAD_BODY", f"{op.name} body is {len(body)} bytes")
    out, at = {}, 0
    for name, kind in layout:
        w = _width(kind)
        chunk = body[at:at + w]
        at += w
        if kind == _ID:
            out[name] = bytes(chunk)
        elif kind == _PLAN:
            out[name] = decode_plan(chunk)
        else:
            out[name] = int.from_bytes(chunk, "little")
    return out


def encode_frame(op: Op, nonce: int, fields: dict) -> bytes:
    body = encode_body(op, fields)
    header = FRAME_MAGIC + _u(int(Op(op)), 2, "opcode") + b"\0\0" + _u(nonce, 8, "nonce") \
        + _u(len(body), 2, "body_length") + b"\0" * 6
    frame = header + body
    return frame + b"\0" * (FRAME_LEN - 1 - len(frame)) + bytes([FRAME_SENTINEL])


@dataclass(frozen=True)
class Request:
    op: Op
    nonce: int
    fields: dict


def decode_frame(frame: bytes) -> Request:
    """Strict: every reserved, padding and sentinel byte is checked."""
    if len(frame) != FRAME_LEN or frame[-1] != FRAME_SENTINEL:
        raise CodecError("BAD_FRAME", "a request is 512 bytes ending in 0xA5")
    if frame[:4] != FRAME_MAGIC:
        raise CodecError("BAD_FRAME", "missing QDC1 magic")
    opcode, flags, nonce, length = struct.unpack_from("<HHQH", frame, 4)
    if flags or any(frame[18:24]):
        raise CodecError("BAD_FRAME", "nonzero flags or reserved bytes")
    if length > MAX_BODY:
        raise CodecError("BAD_FRAME", f"body length {length} exceeds {MAX_BODY}")
    try:
        op = Op(opcode)
    except ValueError:
        raise CodecError("BAD_OPCODE", str(opcode)) from None
    body = frame[FRAME_HEADER:FRAME_HEADER + length]
    if any(frame[FRAME_HEADER + length:FRAME_LEN - 1]):
        raise CodecError("BAD_FRAME", "nonzero padding")
    return Request(op, nonce, decode_body(op, body))
