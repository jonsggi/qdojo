"""The wire, against a node that answers -- and against one that misbehaves.

Until this file existed the protocol layer had no automated test at all: it
had only been driven by hand against live nodes, which proves it works on a
good day and nothing about a bad one. The misbehaviour cases are the point.
"""
import pytest

from qdojo.qubic import ids
from qdojo.qubic.node import Node, NodeError
from qdojo.qubic.tx import Transaction

from fake_node import FakeNode

SEED = "q" * 55
DEST = ids.identity_from_seed("z" * 55)


def node_for(fake, timeout=2.0):
    return Node(fake.ip, fake.port, timeout)


# ------------------------------------------------------------------- reads

def test_tick_info():
    with FakeNode(tick=1234, epoch=42, initial_tick=1000) as f, node_for(f) as n:
        assert n.tick_info() == {"tick": 1234, "epoch": 42, "initial_tick": 1000,
                                 "tick_duration": 0, "aligned_votes": 0,
                                 "misaligned_votes": 0}


def test_balance_is_incoming_minus_outgoing():
    pub = ids.public_key_from_identity(DEST)
    with FakeNode(balances={pub: (5000, 1200)}) as f, node_for(f) as n:
        e = n.entity(pub)
    assert e["balance"] == 3800 and e["incoming"] == 5000 and e["outgoing"] == 1200


def test_an_answer_about_another_identity_is_refused():
    """A node that replies about the wrong key must not be read as a balance
    for the key we asked about."""
    pub = ids.public_key_from_identity(DEST)
    other = ids.public_key_from_identity(ids.identity_from_seed("y" * 55))
    with FakeNode(lie_about=other, balances={other: (9999, 0)}) as f, node_for(f) as n:
        with pytest.raises(NodeError, match="different identity"):
            n.entity(pub)


def test_unrelated_packets_before_the_answer_are_skipped():
    with FakeNode(tick=777, initial_tick=700, noise_before_answer=3) as f, node_for(f) as n:
        assert n.tick_info()["tick"] == 777


def test_a_node_that_only_ever_sends_noise_gives_up():
    with FakeNode(initial_tick=700, noise_before_answer=100) as f, node_for(f) as n:
        with pytest.raises(NodeError, match="none of type"):
            n.tick_info()


def test_public_peers_arrive_unprompted():
    with FakeNode(peers=("9.9.9.9", "8.8.8.8")) as f, node_for(f) as n:
        assert n.public_peers() == ["9.9.9.9", "8.8.8.8"]


def test_public_peers_is_empty_not_an_error_when_none_are_announced():
    with FakeNode(announce_peers=False, tick=5) as f, node_for(f) as n:
        assert n.public_peers() == []


def test_an_incoherent_tick_is_refused():
    """initial_tick after tick is not a small inaccuracy; it is a node whose
    answers cannot be used to schedule anything."""
    with FakeNode(tick=100, initial_tick=500) as f, node_for(f) as n:
        with pytest.raises(NodeError, match="incoherent"):
            n.tick_info()


def test_a_nonsense_packet_size_is_refused():
    with FakeNode(bad_size=True) as f, node_for(f) as n:
        with pytest.raises(NodeError, match="packet of type"):
            n.tick_info()


def test_a_node_that_hangs_up_is_an_error_not_an_empty_answer():
    with FakeNode(hang_up=True) as f:
        with pytest.raises(NodeError):
            with node_for(f) as n:
                n.tick_info()


def test_a_node_that_never_answers_times_out():
    with FakeNode(silent=True, announce_peers=False) as f, node_for(f, timeout=0.3) as n:
        with pytest.raises(NodeError):
            n.tick_info()


def test_unreachable_node():
    with pytest.raises(NodeError, match="cannot reach"):
        with Node("127.0.0.1", 1, 0.3):
            pass


def test_must_be_used_as_a_context_manager():
    with pytest.raises(NodeError, match="context manager"):
        Node("127.0.0.1", 1).tick_info()


# -------------------------------------------------------------- broadcast

def test_broadcast_writes_the_exact_signed_bytes():
    subseed, _priv, public = ids.keys_from_seed(SEED)
    signed = Transaction.to_identity(public, DEST, 4242, 1010).sign(subseed)
    with FakeNode() as f:
        with node_for(f) as n:
            n.broadcast(signed.payload())
        assert f.wait_for_received(1), "the node never received the broadcast"
    assert f.received == [signed.payload()]


def test_a_broadcast_packet_is_framed_as_the_protocol_requires():
    """size includes the header, the type is BROADCAST_TRANSACTION, and dejavu
    is zero on anything we originate."""
    from qdojo.qubic.node import BROADCAST_TRANSACTION, packet
    body = b"\x01\x02\x03"
    p = packet(BROADCAST_TRANSACTION, body, dejavu=0)
    assert int.from_bytes(p[0:3], "little") == len(p) == 8 + len(body)
    assert p[3] == BROADCAST_TRANSACTION and p[4:8] == b"\0\0\0\0"


def test_a_request_gets_a_nonzero_dejavu():
    """A repeated id can be dropped as a duplicate, so requests must vary."""
    from qdojo.qubic.node import REQUEST_ENTITY, packet
    ids_seen = {packet(REQUEST_ENTITY, bytes(32))[4:8] for _ in range(20)}
    assert b"\0\0\0\0" not in ids_seen and len(ids_seen) > 1


# -------------------------------------------------- tick transactions

def test_tick_transactions_returns_every_payload_until_end_respond():
    subseed, _priv, public = ids.keys_from_seed(SEED)
    a = Transaction.to_identity(public, DEST, 1, 50).sign(subseed).payload()
    b = Transaction.to_identity(public, DEST, 2, 50).sign(subseed).payload()
    with FakeNode(tick_txs={50: [a, b]}) as f, node_for(f) as n:
        assert n.tick_transactions(50) == [a, b]


def test_an_empty_tick_is_an_empty_list():
    with FakeNode(tick_txs={}) as f, node_for(f) as n:
        assert n.tick_transactions(50) == []
