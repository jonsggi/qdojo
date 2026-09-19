"""The Qubic primitives, against frozen reference vectors. No network, no binary.

Every expected value here came out of qubic-cli, the reference implementation,
and is written down so this suite needs nothing installed. The only seed used
is the publicly known 55 'a's -- the identity anyone can spend from, which is
what makes it the one seed safe to put in a repository.

`scripts/crosscheck-signer.py` is the other half: it re-derives and re-signs
against a live qubic-cli over many identities. This file proves the pieces
stay right; that script proves they were right to begin with.
"""
import pytest

from qdojo.qubic import fourq, ids, schnorrq
from qdojo.qubic.k12 import k12
from qdojo.qubic.tx import Transaction

ALLA = "a" * 55

# qubic-cli -showkeys with no conf (it falls back to the 55-'a' seed)
REF_PRIVATE = "cctwbaulwuyhybijykxrmxnyrvzbalwryiiahltfwanuafhyfhepcjjgvaec"
REF_PUBLIC = "bzbqfllbncxemglobhuvftluplvcpquassilfaboffbcadqssupnwlzbqexk"
REF_IDENTITY = "BZBQFLLBNCXEMGLOBHUVFTLUPLVCPQUASSILFABOFFBCADQSSUPNWLZBQEXK"

# qubic-cli -print-only hex -sendtoaddressintick <REF_IDENTITY> 12345 80732400
REF_PAYLOAD = bytes.fromhex(
    "1f590d03e613bdded38b4c0820ac44615f91af12435980b3ede3c08c315a2544"
    "1f590d03e613bdded38b4c0820ac44615f91af12435980b3ede3c08c315a2544"
    "3930000000000000f0e0cf0400000000"
    "8d2fa826775df4d167899079219766339c2a7ca28ceb338911a780e45c29502e"
    "053763bd193d8b4ed9a41dbcba3ec9119b5faa422fae7c0487848f8262080600"
)


# ------------------------------------------------------------------- K12

def test_k12_derives_the_reference_private_key():
    """The whole point of SUFFIX_OFFSET: a spec-faithful K12 fails this."""
    subseed = k12(bytes(55), 32)            # 'a'*55 -> 55 zero bytes
    assert ids.identity_from_public_key(k12(subseed, 32), lower=True) == REF_PRIVATE


def test_k12_refuses_inputs_that_would_need_the_tree_path():
    with pytest.raises(ValueError):
        k12(bytes(8192), 32)


@pytest.mark.parametrize("n", [0, 1, 166, 167, 168, 169, 335, 336, 337])
def test_k12_block_boundaries(n):
    """Lengths either side of the rate exercise every padding branch,
    including len+1 == rate, which permutes before placing the suffix."""
    assert len(k12(bytes(n), 32)) == 32


# ----------------------------------------------------------------- curve

def test_generator_is_the_one_the_reference_uses():
    """Re-derive G from the reference's own key pair: G = privkey^-1 * pubkey."""
    private = ids.public_key_from_identity(REF_PRIVATE)
    point = fourq.decode(ids.public_key_from_identity(REF_PUBLIC))
    assert point is not None
    k = int.from_bytes(private, "little") % fourq.N
    assert fourq.pt_affine(fourq.scalar_mul(pow(k, -1, fourq.N), point)) == fourq.G


def test_generator_has_the_stated_order():
    assert fourq.on_curve(*fourq.G)
    assert fourq.pt_eq(fourq.scalar_mul(fourq.N), fourq.IDENTITY)


@pytest.mark.parametrize("k", [1, 2, 3, 12345, fourq.N - 1])
def test_encode_decode_round_trip(k):
    enc = fourq.encode(fourq.scalar_mul(k))
    back = fourq.decode(enc)
    assert back is not None and fourq.encode(back) == enc


def test_decode_rejects_a_point_off_the_curve():
    assert fourq.decode(bytes([0xAA]) + bytes(31)) is None


# ------------------------------------------------------------ identities

def test_the_public_seed_derives_the_public_identity():
    assert ids.identity_from_seed(ALLA) == REF_IDENTITY
    assert ids.PUBLIC_DEFAULT_IDENTITY == REF_IDENTITY


def test_identity_round_trip():
    assert ids.identity_from_public_key(ids.public_key_from_identity(REF_IDENTITY)) == REF_IDENTITY


def test_checksum_catches_a_single_changed_character():
    assert ids.check_identity(REF_IDENTITY)
    swapped = ("C" if REF_IDENTITY[0] != "C" else "D") + REF_IDENTITY[1:]
    assert not ids.check_identity(swapped)


@pytest.mark.parametrize("bad", ["a" * 54, "a" * 56, "A" * 55, "a" * 54 + "1", ""])
def test_rejects_a_seed_that_is_not_55_lowercase_letters(bad):
    with pytest.raises(ValueError):
        ids.subseed_from_seed(bad)


# --------------------------------------------------------------- signing

def test_signature_matches_the_reference_byte_for_byte():
    subseed, _priv, public = ids.keys_from_seed(ALLA)
    tx = Transaction.to_identity(public, REF_IDENTITY, 12345, 80732400)
    assert tx.sign(subseed).payload() == REF_PAYLOAD


def test_signing_is_deterministic():
    subseed, _priv, public = ids.keys_from_seed(ALLA)
    tx = Transaction.to_identity(public, REF_IDENTITY, 1, 5)
    assert tx.sign(subseed).signature == tx.sign(subseed).signature


def test_signature_verifies_and_a_flipped_bit_does_not():
    subseed, _priv, public = ids.keys_from_seed(ALLA)
    tx = Transaction.to_identity(public, REF_IDENTITY, 1, 5)
    signed = tx.sign(subseed)
    assert signed.verify()
    bad = bytearray(signed.signature)
    bad[40] ^= 0x01
    assert not schnorrq.verify(public, tx.digest(), bytes(bad))


def test_a_signature_does_not_carry_to_a_different_transaction():
    subseed, _priv, public = ids.keys_from_seed(ALLA)
    signed = Transaction.to_identity(public, REF_IDENTITY, 1, 5).sign(subseed)
    other = Transaction.to_identity(public, REF_IDENTITY, 2, 5)
    assert not schnorrq.verify(public, other.digest(), signed.signature)


def test_refuses_to_sign_as_someone_else():
    subseed = ids.keys_from_seed(ALLA)[0]
    other_public = ids.keys_from_seed("b" * 55)[2]
    with pytest.raises(ValueError):
        Transaction.to_identity(other_public, REF_IDENTITY, 1, 5).sign(subseed)


def test_amounts_above_32_bits_survive():
    """The amount field is an int64. qubic-cli -sendtoaddressintick truncates
    it to 32 bits; nothing here may inherit that."""
    public = ids.keys_from_seed(ALLA)[2]
    tx = Transaction.to_identity(public, REF_IDENTITY, 8_000_000_000, 5)
    assert int.from_bytes(tx.body()[64:72], "little") == 8_000_000_000


def test_a_dojo_payload_rides_in_the_input():
    subseed, _priv, public = ids.keys_from_seed(ALLA)
    body = b"DOJO" + bytes(60)
    tx = Transaction.to_identity(public, REF_IDENTITY, 7, 9, input_type=0x444F, payload=body)
    assert tx.body()[80:] == body
    assert int.from_bytes(tx.body()[76:78], "little") == 0x444F
    assert int.from_bytes(tx.body()[78:80], "little") == len(body)
    assert tx.sign(subseed).verify()


def test_the_two_digests_are_different_hashes():
    """The signed digest covers the transaction; the hash digest covers the
    transaction AND its signature. Confusing them names nothing."""
    subseed, _priv, public = ids.keys_from_seed(ALLA)
    signed = Transaction.to_identity(public, REF_IDENTITY, 12345, 80732400).sign(subseed)
    assert signed.transaction.digest().hex() != signed.tx_hash()
    assert len(signed.tx_hash()) == 60 and signed.tx_hash().islower()
