"""Bot shares on Qx: issue an asset from the bot's own identity, read who
holds it, and pay dividends through QUtil's on-chain pro-rata distribution.

Every fee is read live from the contract, never hard-coded, and every send
is planned before it is made. The house is never involved in issuing.
"""
import re
import subprocess
from dataclasses import dataclass

from .chain import parse
from .chain.base import Unknown, ChainError

ASSET_NAME_RE = re.compile(r"^[A-Z][A-Z0-9]{0,6}$")  # 7 bytes max on chain
QX_UNIT = "0000000"                                  # unit of measurement: none (7 digits)


class SharesError(Exception):
    pass


def check_asset_name(name: str) -> str:
    if not ASSET_NAME_RE.match(name or ""):
        raise SharesError("asset name: 1-7 chars, uppercase A-Z and digits, letter first")
    return name


# ------------------------------------------------------------------ parsers

def qx_fees(text: str) -> dict | None:
    """-qxgetfee -> {issue, transfer, trade_bps_1e9} or None."""
    d = parse.kv(text)
    try:
        return {"issue": int(d["Asset issuance fee"]), "transfer": int(d["Transfer fee"]),
                "trade_per_1e9": int(d["Trade fee"])}
    except (KeyError, ValueError):
        return None


@dataclass(frozen=True)
class Holding:
    owner: str
    shares: int


def ownerships(text: str) -> list[Holding]:
    """-queryassets ownerships -> holders with a positive share count."""
    out, cur = [], {}
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("Share ownership"):
            if cur.get("owner") and cur.get("shares", 0) > 0:
                out.append(Holding(cur["owner"], cur["shares"]))
            cur = {}
        elif s.startswith("owner = "):
            cur["owner"] = s.split("= ", 1)[1].strip()
        elif s.startswith("number of shares = "):
            try:
                cur["shares"] = int(s.split("= ", 1)[1])
            except ValueError:
                cur["shares"] = 0
    if cur.get("owner") and cur.get("shares", 0) > 0:
        out.append(Holding(cur["owner"], cur["shares"]))
    return out


def owned_assets(text: str) -> list[dict]:
    """-getasset <identity> -> [{issuer, name, shares}] from the OWNERSHIP blocks."""
    out, cur, section = [], {}, None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("======== "):
            if cur.get("name") and section == "OWNERSHIP":
                out.append(cur)
            cur, section = {}, s.strip("= ").strip()
        elif s.startswith("Asset issuer: "):
            cur["issuer"] = s.split(": ", 1)[1]
        elif s.startswith("Asset name: "):
            cur["name"] = s.split(": ", 1)[1]
        elif s.startswith("Number Of Shares: "):
            try:
                cur["shares"] = int(s.split(": ", 1)[1])
            except ValueError:
                cur["shares"] = 0
    if cur.get("name") and section == "OWNERSHIP":
        out.append(cur)
    return out


def total_shares(text: str) -> int | None:
    m = re.search(r"(\d+)\s*$", text.strip().splitlines()[-1]) if text.strip() else None
    return int(m.group(1)) if m else None


# ------------------------------------------------------------------ actions

class Shares:
    def __init__(self, cli):
        """`cli` is a QubicCli (signing for issue/pay, read-only is enough for reads)."""
        self.cli = cli

    def fees(self) -> dict:
        f = qx_fees(self.cli._run(["-qxgetfee"]))
        if f is None:
            raise Unknown("no Qx fee lines in -qxgetfee output")
        return f

    def holders(self, issuer: str, name: str) -> list[Holding]:
        check_asset_name(name)
        return ownerships(self.cli._run(["-queryassets", "ownerships", f"issuer={issuer},name={name}"]))

    def owned(self, identity: str) -> list[dict]:
        return owned_assets(self.cli._run(["-getasset", identity]))

    def plan_issue(self, name: str, count: int) -> dict:
        check_asset_name(name)
        if count <= 0:
            raise SharesError("share count must be positive")
        fees = self.fees()
        bal = self.cli.balance(self.cli.identity)
        already = [a for a in self.owned(self.cli.identity) if a.get("name") == name and a.get("issuer") == self.cli.identity]
        return {"issuer": self.cli.identity, "asset": name, "shares": count, "issue_fee": fees["issue"],
                "balance": bal, "affordable": bal >= fees["issue"] + 1, "already_issued": bool(already)}

    def issue(self, name: str, count: int):
        plan = self.plan_issue(name, count)
        if plan["already_issued"]:
            raise SharesError(f"{self.cli.identity[:8]}… already issued {name}")
        if not plan["affordable"]:
            raise SharesError(f"balance {plan['balance']} below the issuance fee {plan['issue_fee']}")
        out = self.cli._run(["-qxissueasset", name, str(count), QX_UNIT, "0"], signed=True)
        r = parse.send_receipt(out)
        if r is None:
            raise ChainError("issue produced no receipt; treat as NOT sent until proven otherwise")
        from .chain.base import SendResult
        return SendResult(*r)

    def plan_dividend(self, name: str, amount: int) -> dict:
        check_asset_name(name)
        hs = self.holders(self.cli.identity, name)
        n = len(hs)
        total = sum(h.shares for h in hs)
        fee_per = 5  # QUTIL_DISTRIBUTE_QU_TO_SHAREHOLDER_FEE_PER_SHAREHOLDER in the pinned core
        per_share = amount // total if total else 0
        return {"asset": name, "holders": n, "total_shares": total, "amount": amount, "per_share": per_share,
                "distributed": per_share * total, "remainder_refunded": amount - per_share * total,
                "fee": fee_per * n, "cost": amount + fee_per * n,
                "table": [{"owner": h.owner, "shares": h.shares, "gets": per_share * h.shares} for h in hs]}

    def pay_dividend(self, name: str, amount: int):
        plan = self.plan_dividend(name, amount)
        if plan["holders"] == 0 or plan["per_share"] == 0:
            raise SharesError("nothing to distribute: no holders or amount below one QU per share")
        if self.cli.balance(self.cli.identity) < plan["cost"]:
            raise SharesError("balance below amount plus distribution fee")
        out = self.cli._run(["-qutildistributequbictoshareholders", self.cli.identity, name, str(amount)], signed=True)
        r = parse.send_receipt(out)
        if r is None:
            raise ChainError("distribution produced no receipt; treat as NOT sent")
        from .chain.base import SendResult
        return SendResult(*r)
