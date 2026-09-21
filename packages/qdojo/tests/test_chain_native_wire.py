"""NativeChain against nodes that really speak the protocol.

The guard tests in test_chain_native.py cover the refusals. These cover the
round trips -- sign, broadcast, confirm -- which until now had only ever been
driven by hand against a live node. That proves they work on a good day and
nothing about a node that is dead, stale, or missing the tick.
"""
import struct

import pytest

from qdojo.chain.base import ChainError, Unknown
from qdojo.chain.native import NativeChain
from qdojo.qubic import ids
from qdojo.qubic.tx import SignedTransaction, Transaction

from fake_node import FakeNode, cluster

SEED = "q" * 55
DEST = ids.identity_from_seed("z" * 55)
SCHEDULE = 20


def live(fake, **kw):
    kw.setdefault("timeout", 2.0)
    kw.setdefault("schedule_offset", SCHEDULE)
    return NativeChain(fake.host, fake.port, **kw)


def decode(raw):
    src, dst, amount, tick, itype, isize = struct.unpack("<32s32sqIHH", raw[:80])
    return {"src": src, "dst": dst, "amount": amount, "tick": tick,
            "input_type": itype, "input": raw[80:80 + isize], "sig": raw[80 + isize:]}


# ------------------------------------------------------------------- send

def test_send_signs_broadcasts_and_reports_the_scheduled_tick():
    with FakeNode(tick=1000, initial_tick=900) as f:
        r = live(f, seed=SEED).send(DEST, 4242)
        assert f.wait_for_received(1), "the node never received the broadcast"

    assert r.scheduled_tick == 1000 + SCHEDULE
    (raw,) = f.received
    tx = decode(raw)
    assert ids.identity_from_public_key(tx["src"]) == ids.identity_from_seed(SEED)
    assert ids.identity_from_public_key(tx["dst"]) == DEST
    assert tx["amount"] == 4242 and tx["tick"] == 1000 + SCHEDULE
    # The bytes on the wire verify, and hash to the id the caller was handed.
    signed = SignedTransaction(Transaction(tx["src"], tx["dst"], tx["amount"],
                                           tx["tick"], tx["input_type"], tx["input"]),
                               tx["sig"])
    assert signed.verify()
    assert signed.tx_hash() == r.tx_id


def test_a_payload_rides_along_and_is_covered_by_the_signature():
    body = b"DOJO" + bytes(20)
    with FakeNode(tick=1000, initial_tick=900) as f:
        live(f, seed=SEED).send(DEST, 1, payload=body, input_type=0x444F)
        assert f.wait_for_received(1)
    tx = decode(f.received[0])
    assert tx["input"] == body and tx["input_type"] == 0x444F
    signed = SignedTransaction(Transaction(tx["src"], tx["dst"], tx["amount"],
                                           tx["tick"], tx["input_type"], tx["input"]),
                               tx["sig"])
    assert signed.verify()


def test_the_same_bytes_reach_every_node():
    """One node quietly dropping the packet costs the whole tick, so the
    identical signed transaction goes to all of them -- identical bytes are
    one transaction however many nodes see them."""
    a, b, c = cluster(3, tick=1000, initial_tick=900)
    with a, b, c:
        ch = NativeChain(a.host, a.port, seed=SEED, timeout=2.0,
                         schedule_offset=SCHEDULE, fallback_nodes=(b.host, c.host))
        r = ch.send(DEST, 7)
        assert all(n.wait_for_received(1) for n in (a, b, c))
    assert a.received == b.received == c.received
    from qdojo.qubic.ids import tx_hash_from_digest
    from qdojo.qubic.k12 import k12
    assert tx_hash_from_digest(k12(a.received[0], 32)) == r.tx_id


def test_one_live_node_out_of_three_is_still_a_send():
    a, b, c = cluster(3, tick=1000, initial_tick=900)
    with a:                                   # b and c are never started
        ch = NativeChain(a.host, a.port, seed=SEED, timeout=0.4,
                         schedule_offset=SCHEDULE, fallback_nodes=(b.host, c.host))
        r = ch.send(DEST, 11)
        assert a.wait_for_received(1)
    assert r.tx_id


def test_send_never_returns_a_receipt_when_nothing_is_reachable():
    """Whether it fails on the tick read or on the write, the one thing it may
    never do is hand back a SendResult for a transaction that went nowhere."""
    with FakeNode(tick=1000, initial_tick=900) as f:
        c = live(f, seed=SEED)
        assert c.current_tick() == 1000
    with pytest.raises((ChainError, Unknown)):
        c.send(DEST, 1)


def test_broadcast_to_an_unreachable_node_is_an_error():
    from qdojo.qubic.node import Node, NodeError
    with pytest.raises(NodeError, match="cannot reach"):
        with Node("127.0.0.1", 1, 0.3) as n:
            n.broadcast(signed_for(10).payload())


def test_a_read_only_chain_never_even_asks_for_the_tick():
    with FakeNode(tick=1000, initial_tick=900) as f:
        with pytest.raises(ChainError, match="read-only"):
            live(f).send(DEST, 1)
        assert f.requests == []


# ---------------------------------------------------------------- confirm

def signed_for(tick, amount=5):
    subseed, _priv, public = ids.keys_from_seed(SEED)
    return Transaction.to_identity(public, DEST, amount, tick).sign(subseed)


def test_confirm_finds_the_transaction_in_its_tick():
    s = signed_for(950)
    with FakeNode(tick=1100, initial_tick=900, tick_txs={950: [s.payload()]}) as f:
        assert live(f, seed=SEED).confirm(s.tx_hash(), 950) is True


def test_confirm_does_not_confuse_a_neighbour_in_the_same_tick():
    mine, other = signed_for(950, 5), signed_for(950, 6)
    with FakeNode(tick=1100, initial_tick=900, tick_txs={950: [other.payload()]}) as f:
        assert live(f, seed=SEED).confirm(mine.tx_hash(), 950) is False


def test_confirm_is_false_once_the_tick_is_safely_past():
    """A transaction is valid for exactly one tick. Once that tick is behind
    us by a margin and the node has its data, absent means never landed."""
    s = signed_for(950)
    with FakeNode(tick=1150, initial_tick=900, tick_txs={950: []}) as f:
        assert live(f, seed=SEED).confirm(s.tx_hash(), 950) is False


def test_confirm_stays_unknown_while_the_tick_is_still_recent():
    """Judging before the scheduled tick arrives proves nothing -- that is the
    miss that has been read as a dead send before."""
    s = signed_for(950)
    with FakeNode(tick=955, initial_tick=900, tick_txs={950: []}) as f:
        with pytest.raises(Unknown):
            live(f, seed=SEED).confirm(s.tx_hash(), 950)


def test_confirm_stays_unknown_before_the_epochs_initial_tick():
    """Older than the epoch's start the data is simply gone, which is not
    evidence that the transaction never landed."""
    s = signed_for(500)
    with FakeNode(tick=2000, initial_tick=900, tick_txs={500: []}) as f:
        with pytest.raises(Unknown):
            live(f, seed=SEED).confirm(s.tx_hash(), 500)


def test_confirm_is_unknown_when_nothing_answers():
    with pytest.raises(Unknown):
        NativeChain("127.0.0.1", 1, seed=SEED, timeout=0.3).confirm("z" * 60, 950)


# -------------------------------------------------------------- fallbacks

def test_a_read_falls_back_past_a_dead_node():
    dead, good = cluster(2, tick=4321, initial_tick=900)
    with good:                                # `dead` is never started
        c = NativeChain(dead.host, dead.port, seed=SEED, timeout=0.4,
                        fallback_nodes=(good.host,))
        assert c.current_tick() == 4321


def test_a_node_that_answers_incoherently_is_skipped_like_a_dead_one():
    broken, good = cluster(2, initial_tick=900)
    broken.tick, broken.initial_tick = 100, 500      # initial after tick
    good.tick = 4321
    with broken, good:
        c = NativeChain(broken.host, broken.port, seed=SEED, timeout=0.5,
                        fallback_nodes=(good.host,))
        assert c.current_tick() == 4321


def test_balance_comes_back_through_a_fallback():
    dead, good = cluster(2, tick=1000, initial_tick=900)
    pub = ids.public_key_from_identity(DEST)
    good.balances = {pub: (900, 400)}
    with good:
        c = NativeChain(dead.host, dead.port, seed=SEED, timeout=0.4,
                        fallback_nodes=(good.host,))
        assert c.balance(DEST) == 500
