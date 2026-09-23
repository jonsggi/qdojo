import json

import pytest

from qdojo.combat import codec
from qdojo.combat.codec import (
    CodecError, FightContext, Format, Mode, Op, Participant, decode_frame, decode_plan,
    decode_state, encode_frame, encode_plan, encode_state,
)
from qdojo.combat.types import Action, FighterState, Plan

from .conftest import ROOT

FIXTURE = json.loads((ROOT / "docs/fixtures/commitment-v1.json").read_text())


def ident(n):
    return bytes([n]) * 32


def fixture_context(rules):
    """The synthetic identities of docs/fixtures/commitment-v1.json, rebuilt from protocol.md fields."""
    def p(fid, owner, op):
        return Participant(ident(fid), ident(owner), ident(op), 1, ident(owner), 1000, 1000)
    return FightContext(
        network_id=ident(1), contract_id=ident(2), contest_id=9, fight_id=42,
        mode=Mode.RANKED, series_format=Format.SINGLE, cup_id=0, season_id=1, start_tick=1000,
        ruleset_digest=rules.digest, commit_ticks=24, reveal_ticks=12, fee_profile_id=1,
        stake_per_fighter=1000, rake_bps=500, house_bps=6000, dev_bps=1000, share_bps=3000,
        house_recipient=ident(9), dev_recipient=ident(10), share_recipient=ident(11),
        participant_a=p(3, 5, 6), participant_b=p(4, 7, 8))


def test_ruleset_digest_matches_fixture(rules):
    assert rules.digest.hex() == FIXTURE["ruleset_digest"]


def test_frozen_commitment_fixture(rules):
    ctx = fixture_context(rules)
    assert ctx.encode().hex() == FIXTURE["context_bytes"]
    assert ctx.digest().hex() == FIXTURE["context_digest"]
    s = FighterState.initial(rules)
    assert codec.round_state_bytes(ctx.digest(), 0, s, s).hex() == FIXTURE["round_state_bytes"]
    state_digest = codec.round_state_digest(ctx.digest(), 0, s, s)
    assert state_digest.hex() == FIXTURE["round_state_digest"]
    plan = Plan.of([Action.JAB, Action.DUCK, Action.KICK, Action.RECOVER, Action.BLOCK, Action.THROW], 2)
    assert encode_plan(plan).hex() == FIXTURE["plan_bytes"]
    fields = dict(network_id=ident(1), contract_id=ident(2), fight_id=42, round_index=0,
                  context_digest=ctx.digest(), round_state_digest=state_digest,
                  fighter_id=ident(3), operator=ident(6), auth_version=1,
                  salt=bytes.fromhex(FIXTURE["salt"]), plan=plan)
    assert codec.commitment_preimage(**fields).hex() == FIXTURE["commitment_preimage"]
    assert codec.commitment(**fields).hex() == FIXTURE["commitment"]


def test_every_commitment_field_is_bound(rules):
    ctx = fixture_context(rules)
    s = FighterState.initial(rules)
    base = dict(network_id=ident(1), contract_id=ident(2), fight_id=42, round_index=0,
                context_digest=ctx.digest(), round_state_digest=codec.round_state_digest(ctx.digest(), 0, s, s),
                fighter_id=ident(3), operator=ident(6), auth_version=1, salt=ident(12),
                plan=Plan.of([Action.JAB] * 6))
    ref = codec.commitment(**base)
    changes = dict(network_id=ident(99), contract_id=ident(99), fight_id=43, round_index=1,
                   context_digest=ident(99), round_state_digest=ident(99), fighter_id=ident(99),
                   operator=ident(99), auth_version=2, salt=ident(99), plan=Plan.of([Action.JAB] * 5 + [Action.KICK]))
    for k, v in changes.items():
        assert codec.commitment(**{**base, k: v}) != ref, k


def test_participants_must_be_ordered(rules):
    ctx = fixture_context(rules)
    swapped = FightContext(**{**ctx.__dict__, "participant_a": ctx.participant_b, "participant_b": ctx.participant_a})
    with pytest.raises(CodecError):
        swapped.encode()


def test_state_and_plan_round_trip():
    s = FighterState(73, 41, 1, 3, 0)
    assert decode_state(encode_state(s)) == s
    with pytest.raises(CodecError):
        decode_state(encode_state(s)[:7] + b"\1")
    p = Plan.of([Action.THROW] * 6, 5)
    assert decode_plan(encode_plan(p)) == p
    assert encode_plan(Plan.of([Action.RECOVER] * 6))[-1] == 255
    for bad in (bytes([6] * 6 + [255]), bytes([0] * 6 + [6]), bytes([2] * 6 + [0]), bytes(6)):
        with pytest.raises(CodecError):
            decode_plan(bad)


def _sample(op):
    vals = {"plan": Plan.of([Action.KICK] * 6, 0)}
    out = {}
    for i, (name, kind) in enumerate(codec.BODIES[op]):
        if kind == "id":
            out[name] = ident(i + 1)
        elif kind == "plan":
            out[name] = vals["plan"]
        else:
            out[name] = (1 << (8 * kind)) - 1 - i
    return out


@pytest.mark.parametrize("op", list(Op), ids=lambda o: o.name)
def test_every_opcode_round_trips(op):
    fields = _sample(op)
    frame = encode_frame(op, 7, fields)
    assert len(frame) == 512 and frame[-1] == 0xA5 and frame[:4] == b"QDC1"
    req = decode_frame(frame)
    assert req.op is op and req.nonce == 7 and req.fields == fields


@pytest.mark.parametrize("mutate,code", [
    (lambda f: f[:511], "BAD_FRAME"),
    (lambda f: f[:511] + b"\0", "BAD_FRAME"),
    (lambda f: b"QDC2" + f[4:], "BAD_FRAME"),
    (lambda f: f[:4] + b"\x63\0" + f[6:], "BAD_OPCODE"),
    (lambda f: f[:6] + b"\1\0" + f[8:], "BAD_FRAME"),
    (lambda f: f[:20] + b"\1" + f[21:], "BAD_FRAME"),
    (lambda f: f[:500] + b"\1" + f[501:], "BAD_FRAME"),
    (lambda f: f[:16] + (100).to_bytes(2, "little") + f[18:], "BAD_FRAME"),   # body bytes past the length are nonzero padding
    (lambda f: f[:16] + (600).to_bytes(2, "little") + f[18:], "BAD_FRAME"),
])
def test_malformed_frames_are_rejected(mutate, code):
    frame = encode_frame(Op.REVEAL, 1, _sample(Op.REVEAL))
    with pytest.raises(CodecError) as exc:
        decode_frame(mutate(frame))
    assert exc.value.code == code


def test_extra_or_missing_body_fields_are_refused():
    fields = _sample(Op.QUEUE_CANCEL)
    with pytest.raises(CodecError):
        encode_frame(Op.QUEUE_CANCEL, 1, {**fields, "extra": 1})
    with pytest.raises(CodecError):
        encode_frame(Op.QUEUE_CANCEL, 1, {})
    with pytest.raises(CodecError):
        encode_frame(Op.QUEUE_CANCEL, 1, {"offer_id": 1 << 64})
