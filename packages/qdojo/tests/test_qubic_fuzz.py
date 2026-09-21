"""Self-consistency over random values, covering what the conformance script cannot.

`scripts/crosscheck-signer.py` proves SIGNING against qubic-cli byte for byte,
but it can never exercise `verify()` or `decode()`: `-print-only` emits a
signature, it never checks one. That matters because `NativeChain.send`
refuses to broadcast when `verify()` returns False -- a verify bug would be an
availability failure in a money path, with sends randomly refusing for no
visible reason.

The counts here are deliberately small so the suite stays quick. The same
checks have been run at 6,000 iterations off-suite; raise ITERATIONS locally
when touching the field arithmetic.
"""
import random

import pytest

from qdojo.qubic import fourq, ids, schnorrq
from qdojo.qubic.tx import Transaction

ITERATIONS = 40
ALPHABET = "abcdefghijklmnopqrstuvwxyz"


def random_case(rng):
    seed = "".join(rng.choice(ALPHABET) for _ in range(55))
    subseed, _priv, public = ids.keys_from_seed(seed)
    dest = ids.identity_from_seed("".join(rng.choice(ALPHABET) for _ in range(55)))
    size = rng.choice([0, 1, 13, 200, 1024])
    tx = Transaction.to_identity(
        public, dest,
        rng.randrange(0, 1_000_000_000_000_000),
        rng.randrange(1, 2 ** 32),
        input_type=rng.randrange(65536),
        payload=bytes(rng.randrange(256) for _ in range(size)),
    )
    return public, tx, tx.sign(subseed)


def test_every_signature_we_make_verifies():
    rng = random.Random(1234)
    for _ in range(ITERATIONS):
        _public, _tx, signed = random_case(rng)
        assert signed.verify()


def test_no_single_flipped_bit_survives_verification():
    rng = random.Random(5678)
    for _ in range(ITERATIONS):
        public, tx, signed = random_case(rng)
        sig = bytearray(signed.signature)
        sig[rng.randrange(0, 62)] ^= 1 << rng.randrange(8)
        assert not schnorrq.verify(public, tx.digest(), bytes(sig))


def test_a_signature_never_carries_to_another_transaction():
    rng = random.Random(99)
    for _ in range(ITERATIONS // 4):
        public, tx, signed = random_case(rng)
        other = Transaction(tx.source_public_key, tx.destination_public_key,
                            tx.amount ^ 1, tx.tick, tx.input_type, tx.input_bytes)
        assert not schnorrq.verify(public, other.digest(), signed.signature)


def test_public_keys_decode_and_re_encode_to_themselves():
    rng = random.Random(4321)
    for _ in range(ITERATIONS):
        public = ids.keys_from_seed("".join(rng.choice(ALPHABET) for _ in range(55)))[2]
        point = fourq.decode(public)
        assert point is not None
        assert fourq.encode(point) == public


@pytest.mark.parametrize("case", range(8))
def test_the_group_law_holds(case):
    """(a+b)G == aG + bG. A carry or reduction bug in the field arithmetic
    breaks this long before it produces a wrong signature anyone notices."""
    rng = random.Random(1000 + case)
    a, b = rng.randrange(1, fourq.N), rng.randrange(1, fourq.N)
    assert fourq.encode(fourq.scalar_mul((a + b) % fourq.N)) == \
        fourq.encode(fourq.pt_add(fourq.scalar_mul(a), fourq.scalar_mul(b)))
