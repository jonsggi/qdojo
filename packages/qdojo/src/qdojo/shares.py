"""Bot shares on Qx: issue an asset from the bot's own identity, read who
holds it, and pay dividends through QUtil's on-chain pro-rata distribution.

Every fee is read live from the contract, never hard-coded, and every send
is planned before it is made. The house is never involved in issuing.

Both moves are contract transactions -- a transfer to the contract's
identity carrying the procedure's input -- so they go through the chain's
ordinary `send` and are signed wherever the bot's other transactions are.
`qubic.contracts` builds the inputs; nothing here needs qubic-cli.
"""
import re
from dataclasses import dataclass

from .chain import parse
from .chain.base import SendResult
from .chain.parse import owned_assets, qutil_fees, qx_fees          # noqa: F401  (the text parsers, still importable here)
from .qubic import contracts

ASSET_NAME_RE = re.compile(r"^[A-Z][A-Z0-9]{0,6}$")  # 7 bytes max on chain
QX_UNIT = contracts.QX_UNIT_NONE                     # unit of measurement: none (7 digits)


class SharesError(Exception):
    pass


def check_asset_name(name: str) -> str:
    if not ASSET_NAME_RE.match(name or ""):
        raise SharesError("asset name: 1-7 chars, uppercase A-Z and digits, letter first")
    return name


@dataclass(frozen=True)
class Holding:
    owner: str
    shares: int


def ownerships(text: str) -> list[Holding]:
    """-queryassets ownerships -> holders with a positive share count."""
    return [Holding(h["owner"], h["shares"]) for h in (parse.ownerships(text) or [])]


def total_shares(text: str) -> int | None:
    m = re.search(r"(\d+)\s*$", text.strip().splitlines()[-1]) if text.strip() else None
    return int(m.group(1)) if m else None


# ------------------------------------------------------------------ actions

class Shares:
    def __init__(self, chain):
        """`chain` signs for issue/pay (read-only is enough for reads) and
        answers the fee and asset queries: `qx_fees`, `qutil_fees`,
        `owned_assets`, `asset_holders`. NativeChain and QubicCli both do."""
        self.chain = chain

    @property
    def identity(self) -> str:
        return self.chain.identity

    def fees(self) -> dict:
        return self.chain.qx_fees()

    def holders(self, issuer: str, name: str) -> list[Holding]:
        """OWNERSHIP records: who owns the asset, for `bot shares`."""
        check_asset_name(name)
        return [Holding(h["owner"], h["shares"]) for h in self.chain.asset_holders(issuer, name)
                if h["shares"] > 0]

    def possessors(self, issuer: str, name: str) -> list[Holding]:
        """POSSESSION records: who QUtil's DistributeQuToShareholders pays.
        For plain Qx holdings that were never transferred separately, owner
        and possessor are the same identity; they can differ once a
        possession-only transfer happens, which is why a dividend plan
        reads this instead of `holders`."""
        check_asset_name(name)
        return [Holding(h["possessor"], h["shares"]) for h in self.chain.asset_possessors(issuer, name)
                if h["shares"] > 0]

    def owned(self, identity: str) -> list[dict]:
        return [{"issuer": a["issuer"], "name": a["name"], "shares": a["shares"]}
                for a in self.chain.owned_assets(identity)]

    def plan_issue(self, name: str, count: int) -> dict:
        """`already_issued` is decided over EVERY node this chain knows, not
        just the first that answers: Qx.IssueAsset books its (non-refundable)
        fee before it finds out the issuance is a duplicate, so a single
        node's empty answer -- one that never loaded its universe, is
        lagging, or simply has a different view -- must not be trusted alone
        to say "not issued yet". `checked_nodes` is how many nodes answered
        at all; the caller decides what to do with too few."""
        check_asset_name(name)
        if count <= 0:
            raise SharesError("share count must be positive")
        fees = self.fees()
        bal = self.chain.balance(self.identity)
        answers = self.chain.owned_assets_each(self.identity)
        checked_nodes = len(answers)
        already = any(a.get("name") == name and a.get("issuer") == self.identity
                     for _ip, owned in answers for a in owned)
        return {"issuer": self.identity, "asset": name, "shares": count, "issue_fee": fees["issue"],
                "balance": bal, "affordable": bal >= fees["issue"] + 1, "already_issued": bool(already),
                "checked_nodes": checked_nodes}

    def issue(self, name: str, count: int) -> SendResult:
        """Qx IssueAsset: the issuance fee rides as the amount, the asset as
        the input. The fee is the one just read, not qubic-cli's constant."""
        plan = self.plan_issue(name, count)
        if plan["already_issued"]:
            raise SharesError(f"{self.identity[:8]}… already issued {name}")
        if plan["checked_nodes"] < 2:
            raise SharesError(
                f"{name}'s absence was confirmed by only {plan['checked_nodes']} node; "
                "a duplicate issuance burns the fee and issues nothing -- give a second "
                "node via QDOJO_FALLBACK_NODES or refresh the node cache (`qdojo nodes`)")
        if not plan["affordable"]:
            raise SharesError(f"balance {plan['balance']} below the issuance fee {plan['issue_fee']}")
        return self.chain.send(contracts.QX_IDENTITY, plan["issue_fee"],
                               contracts.issue_asset_input(name, count, QX_UNIT, 0),
                               contracts.QX_ISSUE_ASSET)

    def plan_dividend(self, name: str, amount: int) -> dict:
        """Mirror QUtil's DistributeQuToShareholders exactly (core
        src/contracts/QUtil.h): fees = feePerShareholder * shareholders come
        OUT of the invocation reward (`amount`), not on top of it;
        amountPerShare = (amount - fees) // totalShares; if that is <= 0 the
        contract refunds the WHOLE amount and pays nobody. `amount` is what
        the transaction moves and what leaves the wallet if it distributes;
        there is no separate "cost" on top of it."""
        check_asset_name(name)
        hs = self.possessors(self.identity, name)          # QUtil pays possessors, not owners
        n = len(hs)
        total = sum(h.shares for h in hs)
        fee_per = self.chain.qutil_fees()["distribute_per_shareholder"]
        fee = fee_per * n
        per_share = (amount - fee) // total if total and amount > fee else 0
        if per_share > 0:
            distributed = per_share * total
            refunded = amount - distributed - fee
        else:
            fee = 0                # the contract burns nothing on the refund path
            distributed = 0
            refunded = amount
        return {"asset": name, "holders": n, "total_shares": total, "amount": amount, "per_share": per_share,
                "distributed": distributed, "refunded": refunded, "fee": fee,
                "table": [{"owner": h.owner, "shares": h.shares, "gets": per_share * h.shares} for h in hs]}

    def pay_dividend(self, name: str, amount: int) -> SendResult:
        """QUtil DistributeQuToShareholders: the amount rides as the amount,
        issuer and asset as the input. Refuses up front whenever the
        contract itself would refund the whole amount and pay nobody --
        that refund is real chain behaviour, not a bug, but sending into it
        anyway would just donate `amount` round trip (minus nothing, since
        the contract burns no fee on that path) for no distribution."""
        plan = self.plan_dividend(name, amount)
        if plan["holders"] == 0 or plan["per_share"] <= 0:
            raise SharesError("nothing to distribute: no holders, or amount below "
                              "total shares plus the per-holder fee -- QUtil would refund it in full")
        if self.chain.balance(self.identity) < amount:
            raise SharesError("balance below the amount to distribute")
        return self.chain.send(contracts.QUTIL_IDENTITY, amount,
                               contracts.distribute_input(self.identity, name),
                               contracts.QUTIL_DISTRIBUTE_QU_TO_SHAREHOLDERS)
