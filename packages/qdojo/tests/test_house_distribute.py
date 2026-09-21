"""cmd_house_distribute: the shareholder pool must only be booked as paid
once the QUtil send is CONFIRMED, never on the receipt, and a distribution
in flight must be recorded so a crash between send and confirm settles
correctly on the next run instead of paying (or losing) the pool twice.
"""
import argparse

import pytest

from qdojo import cli
from qdojo.chain.base import SendResult, Unknown


class FakeDistributeChain:
    """What Shares needs, plus confirm(), all in memory."""
    identity = "H" * 60

    def __init__(self, balance=1_000_000, holders=(), fee_per=5, confirmed=True):
        self.bal, self.holder_list, self.fee_per = balance, list(holders), fee_per
        self.sends = []
        self._confirmed = confirmed          # True / False / Unknown-raising

    def qx_fees(self):
        return {"issue": 1_000_000_000, "transfer": 100, "trade_per_1e9": 3_000_000}

    def qutil_fees(self):
        return {"distribute_per_shareholder": self.fee_per}

    def owned_assets(self, identity):
        return []

    def owned_assets_each(self, identity):
        return [("1.1.1.1", [])]

    def asset_holders(self, issuer, name):
        return [dict(h) for h in self.holder_list]

    def asset_possessors(self, issuer, name):
        return [{"possessor": h["owner"], "shares": h["shares"], "managing_contract": 1}
                for h in self.holder_list]

    def balance(self, identity):
        return self.bal

    def send(self, dest, amount, payload=b"", input_type=0):
        self.sends.append((dest, amount, payload, input_type))
        return SendResult("t" * 60, 500)

    def confirm(self, tx_id, tick):
        if self._confirmed is None:
            raise Unknown("not yet")
        return self._confirmed


class FakeHouse:
    def __init__(self, chain, initial_state=None):
        self.chain = chain
        self._state = dict(initial_state or {})

    def state(self):
        return dict(self._state)

    def _save_state(self, st):
        self._state = dict(st)


HOLDERS = ({"owner": "A" * 60, "shares": 700, "managing_contract": 1},
           {"owner": "C" * 60, "shares": 300, "managing_contract": 1})


def args(apply):
    return argparse.Namespace(asset="HOUSE", apply=apply)


def test_apply_does_not_book_the_pool_before_confirm(monkeypatch, capsys):
    """send() returning a receipt is not proof the transaction landed. The
    pool must still show its old value, in a pending record, until the send
    is confirmed."""
    chain = FakeDistributeChain(holders=HOLDERS, confirmed=None)   # Unknown until settled
    house = FakeHouse(chain, {"shareholder_pool": 10_005})
    monkeypatch.setattr(cli, "_house", lambda a, signing: house)

    cli.cmd_house_distribute(args(apply=True))
    st = house.state()
    assert st["shareholder_pool"] == 10_005            # unchanged: nothing confirmed yet
    assert "pending_distribution" in st
    assert st["pending_distribution"]["amount"] == 10_005
    assert chain.sends and chain.sends[0][1] == 10_005  # the amount, not a "cost" inflated by the fee


def test_settling_a_confirmed_pending_distribution_only_removes_what_left(monkeypatch):
    """9000 distributed + 10 burnt leaves the wallet; the 995 payBack stays
    in the house, so it must stay in the pool too."""
    chain = FakeDistributeChain(holders=HOLDERS, confirmed=True)
    house = FakeHouse(chain, {"shareholder_pool": 10_005,
                              "pending_distribution": {"tx": "t" * 60, "tick": 500, "amount": 10_005,
                                                       "distributed": 9_000, "fee": 10}})
    monkeypatch.setattr(cli, "_house", lambda a, signing: house)

    cli.cmd_house_distribute(args(apply=True))
    st = house.state()
    assert "pending_distribution" not in st
    assert st["shareholder_pool"] == 10_005 - 9_000 - 10       # == 995, the payBack remainder
    assert st["shareholder_paid"] == 9_000


def test_settling_a_refused_pending_distribution_leaves_the_pool_alone(monkeypatch):
    chain = FakeDistributeChain(holders=HOLDERS, confirmed=False)
    house = FakeHouse(chain, {"shareholder_pool": 10_005,
                              "pending_distribution": {"tx": "t" * 60, "tick": 500, "amount": 10_005,
                                                       "distributed": 9_000, "fee": 10}})
    monkeypatch.setattr(cli, "_house", lambda a, signing: house)

    cli.cmd_house_distribute(args(apply=True))
    st = house.state()
    assert "pending_distribution" not in st
    assert st["shareholder_pool"] == 10_005
    assert st.get("shareholder_paid", 0) == 0


def test_settling_an_undecidable_pending_distribution_stays_pending(monkeypatch):
    chain = FakeDistributeChain(holders=HOLDERS, confirmed=None)
    pending = {"tx": "t" * 60, "tick": 500, "amount": 10_005, "distributed": 9_000, "fee": 10}
    house = FakeHouse(chain, {"shareholder_pool": 10_005, "pending_distribution": dict(pending)})
    monkeypatch.setattr(cli, "_house", lambda a, signing: house)

    cli.cmd_house_distribute(args(apply=True))
    st = house.state()
    assert st["pending_distribution"] == pending
    assert st["shareholder_pool"] == 10_005


def test_a_pending_distribution_blocks_planning_a_new_one(monkeypatch):
    """A pool must never be distributed twice: with a pending record on
    file, --apply settles it and does not also plan or send a new one."""
    chain = FakeDistributeChain(holders=HOLDERS, confirmed=True)
    house = FakeHouse(chain, {"shareholder_pool": 10_005,
                              "pending_distribution": {"tx": "t" * 60, "tick": 500, "amount": 10_005,
                                                       "distributed": 9_000, "fee": 10}})
    monkeypatch.setattr(cli, "_house", lambda a, signing: house)

    cli.cmd_house_distribute(args(apply=True))
    assert chain.sends == []               # settling never sends -- confirm() only


def test_plan_only_does_not_touch_a_pending_distribution(monkeypatch):
    chain = FakeDistributeChain(holders=HOLDERS, confirmed=True)
    pending = {"tx": "t" * 60, "tick": 500, "amount": 10_005, "distributed": 9_000, "fee": 10}
    house = FakeHouse(chain, {"shareholder_pool": 10_005, "pending_distribution": dict(pending)})
    monkeypatch.setattr(cli, "_house", lambda a, signing: house)

    cli.cmd_house_distribute(args(apply=False))
    assert house.state()["pending_distribution"] == pending
    assert chain.sends == []


def test_a_refund_band_amount_is_never_sent():
    """plan_dividend/pay_dividend already refuse an amount the contract
    would refund whole; cmd_house_distribute must not swallow that refusal
    into a pending record."""
    from qdojo.shares import Shares, SharesError
    chain = FakeDistributeChain(holders=HOLDERS)          # total 1000, fee 5/holder * 2 = 10
    sh = Shares(chain)
    with pytest.raises(SharesError):
        sh.pay_dividend("HOUSE", 1005)                     # in [total, total + fee)
    assert chain.sends == []
