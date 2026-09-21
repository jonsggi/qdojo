"""The contract calls, against packets qubic-cli itself printed.

Every vector below came out of `qubic-cli -print-only hex` at the pinned
revision (d8fb56459ca0, the one scripts/build-qubic-cli.sh builds), talking
to fake_node.py on loopback at tick 80,000,000 with `-scheduletick 20`, so
nothing was ever broadcast. The seed is the public 55 'a's, which is why it
is safe to write down; qubic-cli warns about it and signs with it anyway.

    -qxissueasset RYUBOT 1000 0000000 0
    -qutildistributequbictoshareholders BZBQ…QEXK RYUBOT 10005
    -qxgetfee / -qutilgetfee / -getasset BZBQ…QEXK
    -queryassets ownerships issuer=BZBQ…QEXK,name=RYUBOT

The issue-asset vector is special. qubic-cli builds that transaction in an
uninitialised stack struct and signs the 7 padding bytes after
`numberOfDecimalPlaces` as it finds them, so two runs of the same command
print two different transactions: ISSUE_TX and ISSUE_TX_AGAIN are exactly
that pair. There is therefore no single reference to be byte-equal to. What
can be proved -- and is -- is that given the reference's exact input bytes,
padding garbage included, the native builder and signer reproduce the
reference's exact packet; and that the native input agrees with the
reference on every byte the contract reads, and holds zeros where the
reference holds garbage.
"""
import struct

import pytest

from qdojo.qubic import contracts as C
from qdojo.qubic import ids
from qdojo.qubic.tx import Transaction

SEED = "a" * 55
ISSUER = "BZBQFLLBNCXEMGLOBHUVFTLUPLVCPQUASSILFABOFFBCADQSSUPNWLZBQEXK"
TICK = 80_000_020

ISSUE_TX = (
    "1f590d03e613bdded38b4c0820ac44615f91af12435980b3ede3c08c315a2544"
    "0100000000000000000000000000000000000000000000000000000000000000"
    "00ca9a3b00000000" "14b4c404" "0100" "2000"
    "525955424f540000" "e803000000000000" "0000000000000000" "00" "ed8a0afd7f0000"
    "c72b622bdd8e1c2dbe8bb1f933f3ae0d045e0d94fe08070a26864ab57c7ddc0f"
    "886af570cf1ea9b0720fabff47887f9b3b60a9d54700c80286c04555d70c1a00"
)
ISSUE_TX_AGAIN = (
    "1f590d03e613bdded38b4c0820ac44615f91af12435980b3ede3c08c315a2544"
    "0100000000000000000000000000000000000000000000000000000000000000"
    "00ca9a3b00000000" "14b4c404" "0100" "2000"
    "525955424f540000" "e803000000000000" "0000000000000000" "00" "80adfb00000000"
    "7c41465f3df0f5c288d2a257da55bd2681d747e31c1d1e9c00b3327e9e0b1df2"
    "981095ad9e62757b9cc3b355c0adf998d32528293b08fd30bb6945d19caa0a00"
)
DIVIDEND_TX = (
    "1f590d03e613bdded38b4c0820ac44615f91af12435980b3ede3c08c315a2544"
    "0400000000000000000000000000000000000000000000000000000000000000"
    "1527000000000000" "14b4c404" "0700" "2800"
    "1f590d03e613bdded38b4c0820ac44615f91af12435980b3ede3c08c315a2544" "525955424f540000"
    "1d0e684d35c7e08e0b12abfdd436213242d98b6f22d977fe8fa8f4c40d1dcbdd"
    "974322692e1232558098d215948d8a4ece7315f9394dbd34595e3dd3753d1d00"
)
QX_FEE_REQ = "0100000001000000"
QUTIL_FEE_REQ = "0400000007000000"
OWNED_REQ = "1f590d03e613bdded38b4c0820ac44615f91af12435980b3ede3c08c315a2544"
HOLDERS_REQ = (
    "0100" "7800" "0000" "0000"
    "1f590d03e613bdded38b4c0820ac44615f91af12435980b3ede3c08c315a2544"
    "525955424f540000" + "00" * 64
)


def keys():
    return ids.keys_from_seed(SEED)


# ---------------------------------------------------------------- addressing

def test_a_contract_is_addressed_by_its_index():
    """qubic-cli spells Qx out as QX_ADDRESS and QUtil as index 4 in the
    first uint64. They are the same thing."""
    assert C.QX_IDENTITY == "BAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAARMID"
    assert C.contract_public_key(4) == struct.pack("<Q", 4) + bytes(24)
    assert ids.public_key_from_identity(C.QUTIL_IDENTITY) == C.contract_public_key(4)
    assert ids.check_identity(C.QX_IDENTITY) and ids.check_identity(C.QUTIL_IDENTITY)
    with pytest.raises(ValueError):
        C.contract_public_key(0)


# --------------------------------------------------------------- issue asset

def test_issue_asset_reproduces_the_reference_from_its_own_input_bytes():
    subseed, _priv, public = keys()
    for vector in (ISSUE_TX, ISSUE_TX_AGAIN):
        raw = bytes.fromhex(vector)
        assert len(raw) == 80 + 32 + 64
        ref_input = raw[80:112]
        tx = Transaction(public, C.contract_public_key(C.QX_CONTRACT_INDEX), 1_000_000_000, TICK,
                         C.QX_ISSUE_ASSET, ref_input)
        assert tx.sign(subseed).payload() == raw


def test_the_reference_issue_transactions_differ_only_in_uninitialised_padding():
    a, b = bytes.fromhex(ISSUE_TX), bytes.fromhex(ISSUE_TX_AGAIN)
    assert a[:105] == b[:105]                 # header and every byte the contract reads
    assert a[105:112] != b[105:112]           # the 7 padding bytes: stack garbage, twice
    assert a[112:] != b[112:]                 # and therefore two signatures


def test_native_issue_input_matches_the_reference_where_it_matters_and_is_zero_elsewhere():
    ref_input = bytes.fromhex(ISSUE_TX)[80:112]
    ours = C.issue_asset_input("RYUBOT", 1000)
    assert len(ours) == 32
    assert ours[:25] == ref_input[:25]
    assert ours[25:] == bytes(7)
    assert ours == struct.pack("<8sq8sb7x", b"RYUBOT\0\0", 1000, bytes(8), 0)


def test_issue_input_encodes_the_unit_as_digits_minus_zero():
    ours = C.issue_asset_input("KEN1", 5, unit="0000012", decimals=3)
    assert ours[:8] == b"KEN1\0\0\0\0"
    assert ours[16:24] == bytes([0, 0, 0, 0, 0, 1, 2, 0])
    assert ours[24] == 3
    for bad in (dict(shares=0), dict(shares=-1), dict(unit="12"), dict(unit="000000x"), dict(decimals=200)):
        with pytest.raises(ValueError):
            C.issue_asset_input("KEN1", **{"shares": 5, **bad}) if "shares" in bad \
                else C.issue_asset_input("KEN1", 5, **bad)
    with pytest.raises(ValueError):
        C.asset_name_bytes("TOOLONGNAME")
    with pytest.raises(ValueError):
        C.asset_name_bytes("")


# ------------------------------------------------------------------ dividend

def test_dividend_is_byte_identical_to_the_reference():
    """No padding in this struct, so the reference is deterministic and the
    whole packet -- addressing, amount, type, input and signature -- must
    match."""
    subseed, _priv, public = keys()
    got = Transaction.to_identity(public, C.QUTIL_IDENTITY, 10_005, TICK,
                                  C.QUTIL_DISTRIBUTE_QU_TO_SHAREHOLDERS,
                                  C.distribute_input(ISSUER, "RYUBOT")).sign(subseed).payload()
    assert got == bytes.fromhex(DIVIDEND_TX)


def test_distribute_input_is_issuer_key_then_name():
    assert C.distribute_input(ISSUER, "RYUBOT") == ids.public_key_from_identity(ISSUER) + b"RYUBOT\0\0"


# --------------------------------------------------------------------- reads

def test_read_requests_match_the_reference_byte_for_byte():
    assert C.contract_function_request(C.QX_CONTRACT_INDEX, C.QX_GET_FEE) == bytes.fromhex(QX_FEE_REQ)
    assert C.contract_function_request(C.QUTIL_CONTRACT_INDEX, C.QUTIL_GET_FEES) == bytes.fromhex(QUTIL_FEE_REQ)
    assert ids.public_key_from_identity(ISSUER) == bytes.fromhex(OWNED_REQ)
    assert C.ownerships_request(ISSUER, "RYUBOT") == bytes.fromhex(HOLDERS_REQ)
    assert len(C.ownerships_request(ISSUER, "RYUBOT")) == 112


def test_possessions_request_is_the_ownerships_request_with_the_possessor_only_flags():
    """No qubic-cli byte trace for `-queryassets possessions` was captured
    here (unlike the other requests above), so this pins the request's
    SHAPE against `ownerships_request` instead of a golden hex string: same
    112 bytes, same kind field position, same issuer/name/padding, only the
    request kind and the any-* flag bits differ -- possessor and
    possession-managing-contract, not owner and ownership-managing-contract."""
    own = C.ownerships_request(ISSUER, "RYUBOT")
    poss = C.possessions_request(ISSUER, "RYUBOT")
    assert len(poss) == 112
    kind, flags, oc, pc = struct.unpack("<HHHH", poss[:8])
    assert kind == C.ASSET_REQ_POSSESSIONS and oc == 0 and pc == 0
    assert flags == C._ANY_POSSESSOR | C._ANY_POSSESSION_CONTRACT
    assert flags & (C._ANY_OWNER | C._ANY_OWNERSHIP_CONTRACT) == 0
    assert poss[8:] == own[8:]                      # issuer key, name, and the 64 zero bytes match


def test_fee_outputs_decode_and_short_answers_are_refused():
    assert C.parse_qx_fees(struct.pack("<III", 1_000_000_000, 100, 3_000_000)) == \
        {"issue": 1_000_000_000, "transfer": 100, "trade_per_1e9": 3_000_000}
    fees = C.parse_qutil_fees(struct.pack("<11q", 10, 20, 30, 5, 40, 0, 0, 0, 0, 0, 0))
    assert fees["distribute_per_shareholder"] == 5 and fees["send_to_many"] == 10
    for short in (b"", bytes(11), bytes(31)):
        with pytest.raises(ValueError):
            C.parse_qx_fees(short) if len(short) < 12 else None
            C.parse_qutil_fees(short)


def test_asset_records_decode_by_type():
    from fake_node import issuance_record, ownership_record, owned_asset_body
    pub = ids.public_key_from_identity(ISSUER)
    other = ids.public_key_from_identity(ids.identity_from_seed("q" * 55))
    iss = C.decode_asset_record(issuance_record(pub, "RYUBOT", decimals=2))
    assert iss["type"] == C.ASSET_ISSUANCE and iss["issuer"] == ISSUER
    assert iss["name"] == "RYUBOT" and iss["decimals"] == 2
    own = C.decode_asset_record(ownership_record(other, 700, managing_contract=1, index=9))
    assert own == {"type": C.ASSET_OWNERSHIP, "owner": ids.identity_from_public_key(other),
                   "managing_contract": 1, "index": 9, "shares": 700}
    assert C.decode_asset_record(bytes(48)) == {"type": C.ASSET_EMPTY}
    rec = C.decode_owned_asset(owned_asset_body(other, pub, "RYUBOT", 700, 4321))
    assert rec["issuer"] == ISSUER and rec["name"] == "RYUBOT" and rec["shares"] == 700 and rec["tick"] == 4321
    with pytest.raises(ValueError):
        C.decode_owned_asset(bytes(100))
    with pytest.raises(ValueError):
        C.decode_owned_asset(issuance_record(pub, "X") + issuance_record(pub, "X") + bytes(8))
    resp = C.decode_asset_response(ownership_record(other, 300) + struct.pack("<II", 77, 3))
    assert resp["shares"] == 300 and resp["tick"] == 77 and resp["universe_index"] == 3
