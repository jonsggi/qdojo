"""Shares and the rite over the native chain, against a node that speaks
the protocol, with no qubic-cli anywhere.

The library half proves the two contract transactions reach the node with
the right destination, input and a signature that verifies. The CLI half
proves the bot commands never go looking for the binary: PATH is empty,
QUBIC_CLI is unset, and `onboard.find_cli` is replaced by something that
fails the test if called.
"""
import contextlib
import json
import os
import struct

import pytest

from qdojo import nodes, onboard, term
from qdojo.chain.base import Unknown
from qdojo.chain.native import NativeChain
from qdojo.qubic import contracts, ids
from qdojo.qubic.tx import SignedTransaction, Transaction
from qdojo.shares import Shares, SharesError

from fake_node import FakeNode, cluster

SEED = "q" * 55
ME = ids.identity_from_seed(SEED)
ME_KEY = ids.public_key_from_identity(ME)
ALICE = ids.identity_from_seed("l" * 55)
CARL = ids.identity_from_seed("c" * 55)
QX_FEES = struct.pack("<III", 1_000_000_000, 100, 3_000_000)
QUTIL_FEES = struct.pack("<11q", 10, 100, 100, 5, 100, 0, 0, 0, 0, 0, 0)


def decode(raw):
    src, dst, amount, tick, itype, isize = struct.unpack("<32s32sqIHH", raw[:80])
    return {"src": src, "dst": dst, "amount": amount, "tick": tick, "input_type": itype,
            "input": raw[80:80 + isize], "sig": raw[80 + isize:]}


def node(**kw):
    kw.setdefault("tick", 1000)
    kw.setdefault("initial_tick", 900)
    kw.setdefault("contract_outputs", {(1, 1): QX_FEES, (4, 7): QUTIL_FEES})
    return FakeNode(**kw)


def chain(f, seed=SEED):
    return NativeChain(f.ip, f.port, seed=seed, timeout=2.0, schedule_offset=20)


def two_nodes(**kw):
    """Two fake nodes on the same port (see fake_node.cluster), so a chain
    built against them gets a genuine second opinion for an absence check."""
    kw.setdefault("tick", 1000)
    kw.setdefault("initial_tick", 900)
    kw.setdefault("contract_outputs", {(1, 1): QX_FEES, (4, 7): QUTIL_FEES})
    return cluster(2, **kw)


def chain2(primary, fallback, seed=SEED):
    return NativeChain(primary.ip, primary.port, seed=seed, timeout=2.0, schedule_offset=20,
                       fallback_nodes=(fallback.ip,))


# ------------------------------------------------------------------- reads

def test_fees_and_assets_are_read_from_the_node():
    holders = {(ME_KEY, b"RYUBOT\0\0"): [(ids.public_key_from_identity(ALICE), 700),
                                        (ids.public_key_from_identity(CARL), 300)]}
    owned = {ME_KEY: [(ME_KEY, "RYUBOT", 1000), (ids.public_key_from_identity(ALICE), "KEN", 5)]}
    with node(holders=holders, owned=owned) as f:
        c = chain(f)
        assert c.qx_fees() == {"issue": 1_000_000_000, "transfer": 100, "trade_per_1e9": 3_000_000}
        assert c.qutil_fees()["distribute_per_shareholder"] == 5
        assert c.owned_assets(ME) == [
            {"issuer": ME, "name": "RYUBOT", "shares": 1000, "managing_contract": 1, "tick": 1000, "universe_index": 0},
            {"issuer": ALICE, "name": "KEN", "shares": 5, "managing_contract": 1, "tick": 1000, "universe_index": 0}]
        assert c.asset_holders(ME, "RYUBOT") == [{"owner": ALICE, "shares": 700, "managing_contract": 1},
                                                 {"owner": CARL, "shares": 300, "managing_contract": 1}]
        assert c.asset_holders(ME, "NOBODY") == [] and c.owned_assets(ALICE) == []
        assert f.contract_calls == [(1, 1, b""), (4, 7, b"")]


def test_a_function_the_node_cannot_run_is_unknown_not_a_zero_fee():
    with node(contract_outputs={}) as f:
        with pytest.raises(Unknown):
            chain(f).qx_fees()
        with pytest.raises(Unknown):
            Shares(chain(f)).plan_issue("RYUBOT", 10)


def test_a_bad_identity_is_refused_before_any_node_is_asked():
    from qdojo.chain.base import ChainError
    with node() as f:
        c = chain(f)
        with pytest.raises(ChainError, match="checksum"):
            c.owned_assets("A" * 60)
        with pytest.raises(ChainError, match="checksum"):
            c.asset_holders("A" * 60, "RYUBOT")
        assert f.requests == []


# ------------------------------------------------------------------- sends

def test_issue_reaches_the_node_as_a_qx_transaction():
    a, b = two_nodes(balances={ME_KEY: (2_000_000_000, 0)})
    with a, b:
        sh = Shares(chain2(a, b))
        plan = sh.plan_issue("RYUBOT", 1000)
        assert plan["affordable"] and not plan["already_issued"] and plan["issue_fee"] == 1_000_000_000
        assert plan["checked_nodes"] == 2
        r = sh.issue("RYUBOT", 1000)
        assert a.wait_for_received(1)
    tx = decode(a.received[0])
    assert tx["src"] == ME_KEY and tx["dst"] == contracts.contract_public_key(contracts.QX_CONTRACT_INDEX)
    assert tx["amount"] == 1_000_000_000 and tx["tick"] == 1020 == r.scheduled_tick
    assert tx["input_type"] == contracts.QX_ISSUE_ASSET
    assert tx["input"] == contracts.issue_asset_input("RYUBOT", 1000)
    signed = SignedTransaction(Transaction(tx["src"], tx["dst"], tx["amount"], tx["tick"],
                                           tx["input_type"], tx["input"]), tx["sig"])
    assert signed.verify() and signed.tx_hash() == r.tx_id


def test_issue_is_refused_when_the_node_says_it_is_already_issued():
    a, b = two_nodes(balances={ME_KEY: (2_000_000_000, 0)}, owned={ME_KEY: [(ME_KEY, "RYUBOT", 1)]})
    with a, b:
        with pytest.raises(SharesError, match="already issued"):
            Shares(chain2(a, b)).issue("RYUBOT", 1000)
    assert a.received == [] and b.received == []


def test_issue_is_refused_when_only_one_node_confirms_the_absence():
    """A single node with an empty (or lagging, or fresh) universe must not
    be enough on its own to say "not issued yet": Qx books the issuance fee
    before finding out it is a duplicate, so a wrong "not issued" burns it
    for nothing."""
    with node(balances={ME_KEY: (2_000_000_000, 0)}) as f:
        sh = Shares(chain(f))
        plan = sh.plan_issue("RYUBOT", 1000)
        assert plan["checked_nodes"] == 1 and plan["already_issued"] is False
        with pytest.raises(SharesError, match="only 1 node"):
            sh.issue("RYUBOT", 1000)
        assert f.received == []


def test_issue_already_issued_wins_even_when_the_primary_has_an_empty_universe():
    """Order must not decide the outcome: an up-to-date node saying "issued"
    must not be outvoted by an empty-universe or lagging primary that is
    asked first."""
    a, b = two_nodes(balances={ME_KEY: (2_000_000_000, 0)})
    b.owned[ME_KEY] = [(ME_KEY, "RYUBOT", 700)]     # only the fallback knows
    with a, b:
        with pytest.raises(SharesError, match="already issued"):
            Shares(chain2(a, b)).issue("RYUBOT", 1000)
    assert a.received == [] and b.received == []


def test_dividend_reaches_the_node_as_a_qutil_transaction():
    holders = {(ME_KEY, b"RYUBOT\0\0"): [(ids.public_key_from_identity(ALICE), 700),
                                        (ids.public_key_from_identity(CARL), 300)]}
    with node(balances={ME_KEY: (50_000, 0)}, holders=holders) as f:
        sh = Shares(chain(f))
        plan = sh.plan_dividend("RYUBOT", 10_005)
        assert plan["holders"] == 2 and plan["fee"] == 10 and plan["cost"] == 10_015
        r = sh.pay_dividend("RYUBOT", 10_005)
        assert f.wait_for_received(1)
    tx = decode(f.received[0])
    assert tx["dst"] == contracts.contract_public_key(contracts.QUTIL_CONTRACT_INDEX)
    assert tx["amount"] == 10_005 and tx["input_type"] == contracts.QUTIL_DISTRIBUTE_QU_TO_SHAREHOLDERS
    assert tx["input"] == ME_KEY + b"RYUBOT\0\0"
    signed = SignedTransaction(Transaction(tx["src"], tx["dst"], tx["amount"], tx["tick"],
                                           tx["input_type"], tx["input"]), tx["sig"])
    assert signed.verify() and signed.tx_hash() == r.tx_id


# ----------------------------------------------------------------- the CLI

@pytest.fixture
def no_binary(tmp_path, monkeypatch):
    """No qubic-cli anywhere, and a bot command that looks for one fails."""
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    for v in ("QUBIC_CLI", "QDOJO_CHAIN", "QDOJO_NODE", "QDOJO_CONF", "QDOJO_IDENTITY",
              "NO_COLOR", "FORCE_COLOR"):
        monkeypatch.delenv(v, raising=False)

    def never(explicit=None):
        raise AssertionError("a bot command looked for qubic-cli on the native chain")
    monkeypatch.setattr(onboard, "find_cli", never)
    term.set_enabled(False)
    yield
    term.set_enabled(None)


def test_the_rite_and_the_share_commands_need_nothing_but_python(no_binary, tmp_path, monkeypatch, capsys):
    from qdojo.cli import main
    state = str(tmp_path / "state")
    with node(tick=5000, initial_tick=4000, peers=()) as f:
        at = f"{f.ip}:{f.port}"
        monkeypatch.setattr(nodes, "BOOTSTRAP", [at])       # discovery must never leave this machine
        main(["--node", at, "bot", "--state", state, "init", "--full", "--yes", "--provider", "none",
              "--name", "TESTBOT", "--no-color"])
        out = capsys.readouterr().out
        assert "signer verified" in out and "identity derived" in out
        assert "the test riddle is solved" in out            # through the real solver path
        assert f"node {at}" in out and "tick 5000" in out    # the fake node really answered
        assert "fund the identity" in out                    # and its balance was really read: empty
        prof = onboard.load_profile(state)
        assert prof["name"] == "TESTBOT" and prof["cli"] == "" and len(prof["identity"]) == 60
        assert nodes.load(state)[0]["ip"] == at              # cached with its port, for `bot run`
        me = prof["identity"]
        key = ids.public_key_from_identity(me)

        # Everything below runs off the profile and the node cache alone.
        f.balances[key] = (2_000_000_000, 0)
        f.owned[key] = [(key, "TESTBOT", 1000)]
        f.holders[(key, b"TESTBOT\0")] = [(ids.public_key_from_identity(ALICE), 600),
                                          (ids.public_key_from_identity(CARL), 400)]

        main(["bot", "--state", state, "shares"])
        assert json.loads(capsys.readouterr().out) == [{"issuer": me, "name": "TESTBOT", "shares": 1000}]

        main(["bot", "--state", state, "shares", "--name", "TESTBOT"])
        out = capsys.readouterr().out
        lines = out.splitlines()
        assert lines[0].split() == [ALICE, "600", "60.00%"] and lines[1].split() == [CARL, "400", "40.00%"]
        assert lines[2] == "holders 2  total shares 1000"

        main(["bot", "--state", state, "issue-shares", "KEN", "50"])
        out, err = capsys.readouterr()
        plan = json.loads(out)
        assert plan["issue_fee"] == 1_000_000_000 and plan["affordable"] is True and not plan["already_issued"]
        assert "PLAN ONLY" in err and f.received == []

        main(["bot", "--state", state, "dividend", "TESTBOT", "10000"])
        out, err = capsys.readouterr()
        plan = json.loads(out)
        assert plan["holders"] == 2 and plan["per_share"] == 10 and plan["fee"] == 10
        assert "PLAN ONLY" in err and f.received == []

        main(["bot", "--state", state, "nodes"])
        assert nodes.load(state)[0]["ip"] == at and "tick 5000" in capsys.readouterr().out


def test_chain_cli_is_the_only_way_to_reach_for_the_binary(no_binary, tmp_path, monkeypatch):
    from qdojo.cli import main
    state = str(tmp_path / "state")
    with node() as f:
        main(["--node", f"{f.ip}:{f.port}", "bot", "--state", state, "init", "--no-setup", "--yes", "--no-color"])
        with pytest.raises(AssertionError, match="looked for qubic-cli"):
            main(["--chain", "cli", "bot", "--state", state, "shares"])
