"""NativeChain's guards, offline.

Nothing here reaches the network: the "unreachable node" cases use a closed
local port, which is refused instantly rather than waiting out a timeout.
The live protocol is exercised by scripts/crosscheck-signer.py against a real
node; what matters here is that the refusals fire before anything is signed.
"""
import os

import pytest

from qdojo.chain.base import ChainError, Unknown
from qdojo.chain.native import NativeChain
from qdojo.qubic import identity_from_seed, PUBLIC_DEFAULT_IDENTITY

SEED = "q" * 55
OTHER = "z" * 55
DEAD = ("127.0.0.1", 1)     # nothing listens here; connect() is refused at once


def chain(**kw):
    kw.setdefault("timeout", 0.5)
    return NativeChain(DEAD[0], DEAD[1], **kw)


def test_derives_its_own_identity_from_the_seed():
    c = chain(seed=SEED)
    assert c.identity == identity_from_seed(SEED)


def test_accepts_a_matching_identity_and_refuses_a_mismatched_one():
    chain(seed=SEED, identity=identity_from_seed(SEED))
    with pytest.raises(ChainError, match="refusing to sign"):
        chain(seed=SEED, identity=identity_from_seed(OTHER))


def test_refuses_the_publicly_spendable_default_seed():
    """55 'a's derives an identity whose key everyone has. qubic-cli signs as
    it without a word when no seed is given; here it is a hard stop."""
    with pytest.raises(ChainError, match="anyone can spend"):
        chain(seed="a" * 55)
    assert identity_from_seed("a" * 55) == PUBLIC_DEFAULT_IDENTITY


def test_refuses_a_malformed_seed():
    with pytest.raises(ChainError, match="bad seed"):
        chain(seed="nope")


def test_seed_and_conf_are_mutually_exclusive(tmp_path):
    p = tmp_path / "bot.conf"
    p.write_text(f"seed={SEED}\n")
    os.chmod(p, 0o600)
    with pytest.raises(ChainError, match="not both"):
        chain(seed=SEED, conf=str(p))


def test_reads_a_conf_without_ever_writing_one(tmp_path):
    p = tmp_path / "bot.conf"
    p.write_text(f"seed={SEED}\n")
    os.chmod(p, 0o600)
    before = set(os.listdir(tmp_path))
    c = chain(conf=str(p))
    assert c.identity == identity_from_seed(SEED)
    assert set(os.listdir(tmp_path)) == before


def test_a_loose_conf_is_refused(tmp_path):
    p = tmp_path / "loose.conf"
    p.write_text(f"seed={SEED}\n")
    os.chmod(p, 0o644)
    with pytest.raises(Exception):
        chain(conf=str(p))


def test_without_a_seed_it_is_read_only():
    c = chain()
    with pytest.raises(ChainError, match="read-only"):
        c.send(identity_from_seed(OTHER), 1)


def test_a_bad_destination_is_refused_before_any_node_is_contacted():
    """The checksum check runs first, so a mistyped destination costs nothing
    and does not look like a dead node."""
    c = chain(seed=SEED)
    with pytest.raises(ChainError, match="checksum"):
        c.send("Q" * 60, 1)
    with pytest.raises(ChainError, match="checksum"):
        c.balance("Q" * 60)


def test_no_reachable_node_is_unknown_not_zero():
    c = chain(seed=SEED)
    with pytest.raises(Unknown):
        c.current_tick()
    with pytest.raises(Unknown):
        c.balance(identity_from_seed(OTHER))


def test_an_indexer_is_required_for_history():
    c = chain(seed=SEED)
    with pytest.raises(ChainError, match="indexer"):
        c.indexed_tick()
    with pytest.raises(ChainError, match="indexer"):
        c.transactions_to(identity_from_seed(OTHER), 1, 2)
