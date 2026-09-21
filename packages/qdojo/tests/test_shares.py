"""Shares over a chain that answers the four reads and records every send.

The chain here is a stand-in for NativeChain and QubicCli alike: Shares only
ever asks it for fees, assets, a balance and a send. What the bytes of those
sends are is test_contracts.py's business; that they go to the right
contract with the right input is checked here.
"""
import pytest

from qdojo import shares as S
from qdojo.chain import parse
from qdojo.chain.base import SendResult, Unknown
from qdojo.qubic import contracts

OWN = """Warning: No issuer given, assuming NULL_ID (issued by quorum like contract shares).
Share ownership
\towner = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
\tnumber of shares = 700
\tmanaging contract = 1
Share ownership
\towner = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB
\tnumber of shares = 0
Share ownership
\towner = CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC
\tnumber of shares = 300
\tmanaging contract = 1
"""
GETASSET = """======== OWNERSHIP ========
Asset issuer: AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
Asset name: RYUBOT
Number Of Shares: 700
Tick: 5

======== POSSESSION ========
Asset issuer: AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
Asset name: RYUBOT
Number Of Shares: 700
"""
QUTIL_FEES = """SendToManyV1 fee (var 0):               10
Poll creation fee (var 1):              100
Poll vote fee (var 2):                  100
DistributeQuToShareholders fee (var 3): 5 per shareholder
Shareholder proposal fee (var 4):       100
"""


def test_parsers():
    assert S.qx_fees("Asset issuance fee: 1000000000\nTransfer fee: 100\nTrade fee: 3000000\n") == \
        {"issue": 1000000000, "transfer": 100, "trade_per_1e9": 3000000}
    assert S.qx_fees("garbage") is None
    hs = S.ownerships(OWN)
    assert [(h.owner[0], h.shares) for h in hs] == [("A", 700), ("C", 300)]      # zero-share rows dropped
    assert S.owned_assets(GETASSET) == [{"issuer": "A" * 60, "name": "RYUBOT", "shares": 700}]
    assert S.qutil_fees(QUTIL_FEES) == {"distribute_per_shareholder": 5}


def test_parsers_tell_nothing_from_garbage():
    """An empty list is a real answer -- nobody holds it, nothing is owned --
    only when the binary printed the marker that says so."""
    assert parse.ownerships("No assets match your query.\n") == []
    assert parse.ownerships("Failed to connect 1.2.3.4\n") is None
    assert parse.owned_assets("======== OWNERSHIP ========\n======== POSSESSION ========\n") == []
    assert parse.owned_assets("garbage") is None
    assert parse.qutil_fees("garbage") is None


def test_asset_name_rules():
    for ok in ("RYUBOT", "KEN1", "A", "ZANG1EF"):
        S.check_asset_name(ok)
    for bad in ("", "ryubot", "1ABC", "TOOLONGNAME", "KEN.EXE"):
        with pytest.raises(S.SharesError):
            S.check_asset_name(bad)


class FakeShareChain:
    """What NativeChain and QubicCli both answer to, in memory."""
    identity = "A" * 60

    def __init__(self, balance=2_000_000_000, owned=(), holders=(), issue_fee=1_000_000_000, fee_per=5):
        self.bal, self.owned_list, self.holder_list = balance, list(owned), list(holders)
        self.issue_fee, self.fee_per, self.sends = issue_fee, fee_per, []

    def qx_fees(self):
        return {"issue": self.issue_fee, "transfer": 100, "trade_per_1e9": 3_000_000}

    def qutil_fees(self):
        return {"distribute_per_shareholder": self.fee_per}

    def owned_assets(self, identity):
        return [dict(a) for a in self.owned_list]

    def owned_assets_each(self, identity):
        return [("1.1.1.1", [dict(a) for a in self.owned_list]), ("2.2.2.2", [dict(a) for a in self.owned_list])]

    def asset_holders(self, issuer, name):
        return [dict(h) for h in self.holder_list]

    def asset_possessors(self, issuer, name):
        """Plain holdings: possessor == owner, same shares."""
        return [{"possessor": h["owner"], "shares": h["shares"],
                "managing_contract": h.get("managing_contract", 1)} for h in self.holder_list]

    def balance(self, identity):
        return self.bal

    def send(self, dest, amount, payload=b"", input_type=0):
        self.sends.append((dest, amount, payload, input_type))
        return SendResult("t" * 60, 500)


HOLDERS = ({"owner": "A" * 60, "shares": 700, "managing_contract": 1},
           {"owner": "B" * 60, "shares": 0, "managing_contract": 1},
           {"owner": "C" * 60, "shares": 300, "managing_contract": 1})


def test_plan_and_issue_reads_live_fee_and_refuses_when_poor():
    sh = S.Shares(FakeShareChain(balance=5))
    plan = sh.plan_issue("RYUBOT", 1000)
    assert plan["issue_fee"] == 1_000_000_000 and plan["affordable"] is False
    with pytest.raises(S.SharesError):
        sh.issue("RYUBOT", 1000)
    sh = S.Shares(FakeShareChain())
    res = sh.issue("RYUBOT", 1000)
    assert res.tx_id == "t" * 60 and res.scheduled_tick == 500
    assert sh.chain.sends == [(contracts.QX_IDENTITY, 1_000_000_000,
                               contracts.issue_asset_input("RYUBOT", 1000), contracts.QX_ISSUE_ASSET)]


def test_issue_sends_the_fee_it_read_not_a_constant():
    """qubic-cli hard-codes 1,000,000,000. The plan reads the fee live, so
    the send must carry that same number, whatever it is."""
    sh = S.Shares(FakeShareChain(balance=10_000, issue_fee=5_000))
    sh.issue("RYUBOT", 1)
    assert sh.chain.sends[0][1] == 5_000


def test_issue_refuses_a_second_issuance():
    sh = S.Shares(FakeShareChain(owned=[{"issuer": "A" * 60, "name": "RYUBOT", "shares": 700}]))
    with pytest.raises(S.SharesError):
        sh.issue("RYUBOT", 1000)
    assert sh.chain.sends == []


def test_issue_refuses_when_absence_was_checked_by_only_one_node():
    """A single node's empty answer is one opinion, not proof nothing is
    issued -- Qx books its (non-refundable) fee before finding out an
    issuance is a duplicate, so issue() must not trust one node alone."""
    class OneNode(FakeShareChain):
        def owned_assets_each(self, identity):
            return [("1.1.1.1", [dict(a) for a in self.owned_list])]

    sh = S.Shares(OneNode())
    plan = sh.plan_issue("RYUBOT", 1000)
    assert plan["checked_nodes"] == 1 and plan["already_issued"] is False
    with pytest.raises(S.SharesError, match="only 1 node"):
        sh.issue("RYUBOT", 1000)
    assert sh.chain.sends == []


def test_issue_already_issued_wins_even_if_only_one_of_several_nodes_says_so():
    """already_issued must be true if ANY node reports the issuance -- an
    up-to-date node must not be outvoted by a lagging or empty-universe one."""
    class SplitNodes(FakeShareChain):
        def owned_assets_each(self, identity):
            return [("1.1.1.1", []), ("2.2.2.2", [{"issuer": self.identity, "name": "RYUBOT", "shares": 700}])]

    sh = S.Shares(SplitNodes())
    plan = sh.plan_issue("RYUBOT", 1000)
    assert plan["checked_nodes"] == 2 and plan["already_issued"] is True
    with pytest.raises(S.SharesError, match="already issued"):
        sh.issue("RYUBOT", 1000)
    assert sh.chain.sends == []


def test_dividend_plan_is_pro_rata_with_fee_per_holder():
    """Mirrors QUtil's DistributeQuToShareholders: the fee comes OUT of
    `amount`, not on top of it. 10_005 over 700+300 shares at fee 5/holder:
    fee = 10, per_share = (10_005 - 10) // 1000 = 9, distributed = 9000,
    refunded = 10_005 - 9000 - 10 = 995."""
    sh = S.Shares(FakeShareChain(holders=HOLDERS))
    plan = sh.plan_dividend("RYUBOT", 10_005)
    assert plan["holders"] == 2 and plan["total_shares"] == 1000 and plan["per_share"] == 9
    assert plan["distributed"] == 9_000 and plan["refunded"] == 995 and plan["fee"] == 10
    assert plan["amount"] == 10_005
    assert [(t["owner"][0], t["gets"]) for t in plan["table"]] == [("A", 6300), ("C", 2700)]
    res = sh.pay_dividend("RYUBOT", 10_005)
    assert res.scheduled_tick == 500
    assert sh.chain.sends == [(contracts.QUTIL_IDENTITY, 10_005,
                               contracts.distribute_input("A" * 60, "RYUBOT"),
                               contracts.QUTIL_DISTRIBUTE_QU_TO_SHAREHOLDERS)]
    with pytest.raises(S.SharesError):
        sh.pay_dividend("RYUBOT", 999)       # below one QU per share


def test_dividend_plan_matches_the_refund_band_the_contract_takes():
    """Between `total_shares` and `total_shares + fee` the plan's own
    arithmetic gives per_share <= 0: the contract refunds the whole amount
    and pays nobody, and pay_dividend must refuse before sending into that,
    not just when per_share prints exactly 0."""
    sh = S.Shares(FakeShareChain(holders=HOLDERS))     # total 1000, fee 5/holder * 2 = 10
    for amount in (1000, 1005, 1009):
        plan = sh.plan_dividend("RYUBOT", amount)
        assert plan["per_share"] <= 0 and plan["distributed"] == 0 and plan["fee"] == 0
        assert plan["refunded"] == amount
        with pytest.raises(S.SharesError):
            sh.pay_dividend("RYUBOT", amount)
    assert sh.chain.sends == []


def test_dividend_fee_is_read_live_and_an_unknown_fee_stops_the_plan():
    sh = S.Shares(FakeShareChain(holders=HOLDERS, fee_per=7))
    assert sh.plan_dividend("RYUBOT", 10_000)["fee"] == 14

    class NoFees(FakeShareChain):
        def qutil_fees(self):
            raise Unknown("no answer")
    with pytest.raises(Unknown):
        S.Shares(NoFees(holders=HOLDERS)).plan_dividend("RYUBOT", 10_000)
