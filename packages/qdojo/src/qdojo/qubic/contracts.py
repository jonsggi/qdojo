"""The two contract calls a bot makes, and the asset records they touch. Pure, no I/O.

A contract call is an ordinary transaction whose destination is the contract
and whose input is the procedure's argument struct: the destination public
key is the contract index in the first uint64 and zeros after it (so Qx,
index 1, is BAAAA…RMID), the input type is the procedure number, and the
input bytes are the struct laid out as the C++ compiler lays it out. A
contract FUNCTION (a read) is the same struct sent in a REQUEST_CONTRACT_FUNCTION
packet instead of a transaction.

Everything here was read out of qubic-cli at the pinned revision and checked
against packets it printed with `-print-only hex` (test_contracts.py holds
them). One thing it does not reproduce on purpose: qubic-cli's
`-qxissueasset` signs the 7 padding bytes after `numberOfDecimalPlaces`
straight off its stack, uninitialised, so two runs give two different
transactions. Those bytes carry nothing the contract reads. They are zero
here, which is what a struct initialised in C++ would hold and the only value
that makes the transaction reproducible.
"""
import struct

from .ids import identity_from_public_key, public_key_from_identity

QX_CONTRACT_INDEX = 1
QUTIL_CONTRACT_INDEX = 4

# Qx: function 1 reads the fees, procedure 1 issues an asset (qx.cpp).
QX_GET_FEE = 1
QX_ISSUE_ASSET = 1
# QUtil: function 7 reads the fees, procedure 7 pays an asset's holders
# pro rata (qutil.h, qutilFunctionId / qutilProcedureId).
QUTIL_GET_FEES = 7
QUTIL_DISTRIBUTE_QU_TO_SHAREHOLDERS = 7

ASSET_NAME_LEN = 7
QX_UNIT_NONE = "0000000"        # unit of measurement: none (7 SI exponents, as digits)

# AssetRecord.type (structs.h)
ASSET_EMPTY, ASSET_ISSUANCE, ASSET_OWNERSHIP, ASSET_POSSESSION = 0, 1, 2, 3
ASSET_RECORD_SIZE = 48
ASSETS_DEPTH = 24

# RequestAssets (message type 52, structs.h): the request kinds and flags.
ASSET_REQ_ISSUANCES, ASSET_REQ_OWNERSHIPS, ASSET_REQ_POSSESSIONS = 0, 1, 2
_ANY_OWNER, _ANY_OWNERSHIP_CONTRACT = 0b1000, 0b10000
_ANY_POSSESSOR, _ANY_POSSESSION_CONTRACT = 0b100000, 0b1000000


def contract_public_key(index: int) -> bytes:
    """A contract's 32-byte key: its index, little-endian, then zeros."""
    if not 0 < index < (1 << 16):
        raise ValueError(f"contract index {index!r} out of range")
    return struct.pack("<Q", index) + bytes(24)


def contract_identity(index: int) -> str:
    return identity_from_public_key(contract_public_key(index))


QX_IDENTITY = contract_identity(QX_CONTRACT_INDEX)          # BAAAA…RMID, qubic-cli's QX_ADDRESS
QUTIL_IDENTITY = contract_identity(QUTIL_CONTRACT_INDEX)


def asset_name_bytes(name: str) -> bytes:
    """An asset name as the chain stores it: up to 7 ASCII bytes, zero padded
    to a uint64. Shape (capitals and digits, letter first) is the caller's
    check; this only refuses what cannot be encoded at all."""
    raw = name.encode("ascii", "strict")
    if not 0 < len(raw) <= ASSET_NAME_LEN:
        raise ValueError(f"asset name must be 1-{ASSET_NAME_LEN} characters, got {name!r}")
    return raw.ljust(8, b"\0")


def asset_name_from_bytes(raw: bytes) -> str:
    return raw[:ASSET_NAME_LEN].split(b"\0", 1)[0].decode("ascii", "replace")


def issue_asset_input(name: str, shares: int, unit: str = QX_UNIT_NONE, decimals: int = 0) -> bytes:
    """Qx IssueAsset_input, 32 bytes: name, shares, unit of measurement,
    decimal places, then the 7 padding bytes the C++ struct carries (zero
    here; see the module docstring). `unit` is qubic-cli's 7-digit form,
    each digit an SI exponent, stored as digit - '0'."""
    if not 0 < shares < (1 << 63):
        raise ValueError(f"share count {shares!r} out of range")
    if len(unit) != ASSET_NAME_LEN or not unit.isdigit():
        raise ValueError(f"unit of measurement must be {ASSET_NAME_LEN} digits, got {unit!r}")
    if not -128 <= decimals <= 127:
        raise ValueError(f"decimal places {decimals!r} out of range")
    return struct.pack("<8sq8sb7x", asset_name_bytes(name), shares,
                       bytes(int(c) for c in unit).ljust(8, b"\0"), decimals)


def distribute_input(issuer: str, name: str) -> bytes:
    """QUtil DistributeQuToShareholders input, 40 bytes: issuer key, asset name."""
    return public_key_from_identity(issuer) + asset_name_bytes(name)


def contract_function_request(index: int, function: int, data: bytes = b"") -> bytes:
    """RequestContractFunction (message type 42): index, function, input size, input."""
    if len(data) > 0xFFFF:
        raise ValueError("contract function input too large")
    return struct.pack("<IHH", index, function, len(data)) + data


def ownerships_request(issuer: str, name: str) -> bytes:
    """RequestAssets (message type 52) for every holder of one asset, laid
    out exactly as `qubic-cli -queryassets ownerships issuer=…,name=…` sends
    it: any owner, any possessor, any managing contract."""
    flags = _ANY_OWNER | _ANY_POSSESSOR | _ANY_OWNERSHIP_CONTRACT | _ANY_POSSESSION_CONTRACT
    return struct.pack("<HHHH", ASSET_REQ_OWNERSHIPS, flags, 0, 0) \
        + public_key_from_identity(issuer) + asset_name_bytes(name) + bytes(64)


def possessions_request(issuer: str, name: str) -> bytes:
    """RequestAssets for every POSSESSION record of one asset, the way
    `-queryassets possessions issuer=…,name=…` asks it: any possessor, any
    managing contract. QUtil's DistributeQuToShareholders pays possessors by
    numberOfPossessedShares, not owners, so this is what a dividend plan
    must count -- `ownerships_request` stays for `bot shares`, which shows
    who owns the asset."""
    flags = _ANY_POSSESSOR | _ANY_POSSESSION_CONTRACT
    return struct.pack("<HHHH", ASSET_REQ_POSSESSIONS, flags, 0, 0) \
        + public_key_from_identity(issuer) + asset_name_bytes(name) + bytes(64)


# ------------------------------------------------------------------ decoding

def parse_qx_fees(out: bytes) -> dict:
    """QxFees_output: three uint32 -- issuance fee, transfer fee, trade fee
    in billionths."""
    if len(out) < 12:
        raise ValueError(f"Qx fees: {len(out)} bytes, expected 12")
    issue, transfer, trade = struct.unpack("<III", out[:12])
    return {"issue": issue, "transfer": transfer, "trade_per_1e9": trade}


def parse_qutil_fees(out: bytes) -> dict:
    """QUtil GetFees_output: int64 fees, the fourth of which is what
    DistributeQuToShareholders charges per holder paid."""
    if len(out) < 32:
        raise ValueError(f"QUtil fees: {len(out)} bytes, expected at least 32")
    smt1, poll_create, poll_vote, per_holder = struct.unpack("<qqqq", out[:32])
    return {"send_to_many": smt1, "poll_creation": poll_create, "poll_vote": poll_vote,
            "distribute_per_shareholder": per_holder}


def decode_asset_record(rec: bytes) -> dict:
    """One 48-byte AssetRecord (structs.h), by its type byte."""
    if len(rec) < ASSET_RECORD_SIZE:
        raise ValueError(f"asset record is {len(rec)} bytes, expected {ASSET_RECORD_SIZE}")
    key, kind = rec[:32], rec[32]
    if kind == ASSET_ISSUANCE:
        return {"type": kind, "issuer": identity_from_public_key(key),
                "name": asset_name_from_bytes(rec[33:40]),
                "decimals": struct.unpack("<b", rec[40:41])[0], "unit": bytes(rec[41:48])}
    if kind in (ASSET_OWNERSHIP, ASSET_POSSESSION):
        managing, index, shares = struct.unpack("<HIq", rec[34:48])
        who = "owner" if kind == ASSET_OWNERSHIP else "possessor"
        return {"type": kind, who: identity_from_public_key(key), "managing_contract": managing,
                "index": index, "shares": shares}
    return {"type": kind}


def decode_owned_asset(body: bytes) -> dict:
    """RespondOwnedAssets: the ownership record, the issuance it is of, the
    tick, the universe index, and the siblings (unused here)."""
    if len(body) < 2 * ASSET_RECORD_SIZE + 8:
        raise ValueError(f"owned-asset record is {len(body)} bytes")
    owned = decode_asset_record(body[:ASSET_RECORD_SIZE])
    issued = decode_asset_record(body[ASSET_RECORD_SIZE:2 * ASSET_RECORD_SIZE])
    tick, universe = struct.unpack("<II", body[2 * ASSET_RECORD_SIZE:2 * ASSET_RECORD_SIZE + 8])
    if owned.get("type") != ASSET_OWNERSHIP or issued.get("type") != ASSET_ISSUANCE:
        raise ValueError("owned-asset record is not an ownership of an issuance")
    return {"issuer": issued["issuer"], "name": issued["name"], "shares": owned["shares"],
            "managing_contract": owned["managing_contract"], "tick": tick, "universe_index": universe}


def decode_asset_response(body: bytes) -> dict:
    """RespondAssets (message type 53): one record, its tick and index."""
    if len(body) < ASSET_RECORD_SIZE + 8:
        raise ValueError(f"asset response is {len(body)} bytes")
    rec = decode_asset_record(body[:ASSET_RECORD_SIZE])
    rec["tick"], rec["universe_index"] = struct.unpack("<II", body[ASSET_RECORD_SIZE:ASSET_RECORD_SIZE + 8])
    return rec
