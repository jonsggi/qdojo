import pytest

from qdojo import shares as S
from qdojo.chain.base import Unknown

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


def test_parsers():
    assert S.qx_fees("Asset issuance fee: 1000000000\nTransfer fee: 100\nTrade fee: 3000000\n") == \
        {"issue": 1000000000, "transfer": 100, "trade_per_1e9": 3000000}
    assert S.qx_fees("garbage") is None
    hs = S.ownerships(OWN)
    assert [(h.owner[0], h.shares) for h in hs] == [("A", 700), ("C", 300)]      # zero-share rows dropped
    assert S.owned_assets(GETASSET) == [{"issuer": "A" * 60, "name": "RYUBOT", "shares": 700}]


def test_asset_name_rules():
    for ok in ("RYUBOT", "KEN1", "A", "ZANG1EF"):
        S.check_asset_name(ok)
    for bad in ("", "ryubot", "1ABC", "TOOLONGNAME", "KEN.EXE"):
        with pytest.raises(S.SharesError):
            S.check_asset_name(bad)


class FakeCli:
    identity = "A" * 60

    def __init__(self, balance=2_000_000_000, owned=""):
        self.bal, self.owned_text, self.calls = balance, owned, []

    def _run(self, args, signed=False):
        self.calls.append((tuple(args), signed))
        if args[0] == "-qxgetfee":
            return "Asset issuance fee: 1000000000\nTransfer fee: 100\nTrade fee: 3000000\n"
        if args[0] == "-getasset":
            return self.owned_text
        if args[0] == "-queryassets":
            return OWN
        if args[0] in ("-qxissueasset", "-qutildistributequbictoshareholders"):
            return "Transaction has been sent!\nTxHash: " + "t" * 60 + "\nTick: 500\n"
        return ""

    def balance(self, identity):
        return self.bal


def test_plan_and_issue_reads_live_fee_and_refuses_when_poor():
    sh = S.Shares(FakeCli(balance=5))
    plan = sh.plan_issue("RYUBOT", 1000)
    assert plan["issue_fee"] == 1_000_000_000 and plan["affordable"] is False
    with pytest.raises(S.SharesError):
        sh.issue("RYUBOT", 1000)
    sh = S.Shares(FakeCli())
    res = sh.issue("RYUBOT", 1000)
    assert res.tx_id == "t" * 60 and res.scheduled_tick == 500
    assert (("-qxissueasset", "RYUBOT", "1000", "0000000", "0"), True) in sh.cli.calls


def test_issue_refuses_a_second_issuance():
    sh = S.Shares(FakeCli(owned=GETASSET))
    with pytest.raises(S.SharesError):
        sh.issue("RYUBOT", 1000)


def test_dividend_plan_is_pro_rata_with_fee_per_holder():
    sh = S.Shares(FakeCli())
    plan = sh.plan_dividend("RYUBOT", 10_005)
    assert plan["holders"] == 2 and plan["total_shares"] == 1000 and plan["per_share"] == 10
    assert plan["distributed"] == 10_000 and plan["remainder_refunded"] == 5 and plan["fee"] == 10
    assert [(t["owner"][0], t["gets"]) for t in plan["table"]] == [("A", 7000), ("C", 3000)]
    res = sh.pay_dividend("RYUBOT", 10_005)
    assert res.scheduled_tick == 500
    with pytest.raises(S.SharesError):
        sh.pay_dividend("RYUBOT", 999)       # below one QU per share
