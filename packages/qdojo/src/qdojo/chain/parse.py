"""Pure parsers for qubic-cli stdout. qubic-cli exits 0 on failure, so the
marker in the text is the only evidence. Each parser returns None when the
marker is missing; the caller turns None into Unknown."""
import re

CONNECT_FAIL = ("Failed to connect", "Unable to establish", "No connection")


def kv(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if ": " in line:
            k, v = line.split(": ", 1)
            out.setdefault(k.strip(), v.strip())
    return out


def _int(s):
    try:
        return int(str(s).strip())
    except (TypeError, ValueError):
        return None


def connection_failed(text: str) -> bool:
    return (not text.strip()) or any(m in text for m in CONNECT_FAIL)


def current_tick(text: str) -> int | None:
    d = kv(text)
    t, e = _int(d.get("Tick")), _int(d.get("Epoch"))
    return t if (t and t > 0 and e and e > 0) else None


def balance(text: str, identity: str) -> int | None:
    """Three-part acceptance: names the identity asked for, has a Balance,
    and a positive Tick. Anything less is not a zero, it is nothing."""
    d = kv(text)
    if d.get("Identity") != identity or "Balance" not in d:
        return None
    b, t = _int(d.get("Balance")), _int(d.get("Tick"))
    return b if (b is not None and t and t > 0) else None


def send_receipt(text: str) -> tuple[str, int] | None:
    """-sendtoaddress / -sendcustomtransaction -> (tx_hash, scheduled_tick)."""
    if "Transaction has been sent!" not in text:
        return None
    h = re.search(r"^TxHash:\s*([a-z]{60})\s*$", text, re.M)
    t = re.search(r"^Tick:\s*(\d+)\s*$", text, re.M)
    return (h.group(1), int(t.group(1))) if (h and t) else None


def qx_fees(text: str) -> dict | None:
    """-qxgetfee -> {issue, transfer, trade_per_1e9} or None."""
    d = kv(text)
    try:
        return {"issue": int(d["Asset issuance fee"]), "transfer": int(d["Transfer fee"]),
                "trade_per_1e9": int(d["Trade fee"])}
    except (KeyError, ValueError):
        return None


def qutil_fees(text: str) -> dict | None:
    """-qutilgetfee -> {distribute_per_shareholder, ...} or None."""
    m = re.search(r"^DistributeQuToShareholders fee \(var \d+\):\s*(-?\d+)\s+per shareholder", text, re.M)
    if not m:
        return None
    return {"distribute_per_shareholder": int(m.group(1))}


def ownerships(text: str) -> list[dict] | None:
    """-queryassets ownerships -> [{owner, shares, managing_contract}] with a
    positive share count, [] when the query matched nothing, None when the
    output carries neither marker."""
    out, cur = [], {}

    def flush():
        if cur.get("owner") and cur.get("shares", 0) > 0:
            out.append({"owner": cur["owner"], "shares": cur["shares"],
                        "managing_contract": cur.get("managing_contract", 0)})

    seen = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("Share ownership"):
            flush()
            cur, seen = {}, True
        elif s.startswith("owner = "):
            cur["owner"] = s.split("= ", 1)[1].strip()
        elif s.startswith("number of shares = "):
            cur["shares"] = _int(s.split("= ", 1)[1]) or 0
        elif s.startswith("managing contract = "):
            cur["managing_contract"] = _int(s.split("= ", 1)[1]) or 0
        elif s.startswith("No assets match your query"):
            seen = True
    flush()
    return out if seen else None


def owned_assets(text: str) -> list[dict] | None:
    """-getasset <identity> -> [{issuer, name, shares}] from the OWNERSHIP
    blocks, or None when the OWNERSHIP header never appeared."""
    out, cur, section, seen = [], {}, None, False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("======== "):
            if cur.get("name") and section == "OWNERSHIP":
                out.append(cur)
            cur, section = {}, s.strip("= ").strip()
            seen = seen or section == "OWNERSHIP"
        elif s.startswith("Asset issuer: "):
            cur["issuer"] = s.split(": ", 1)[1]
        elif s.startswith("Asset name: "):
            cur["name"] = s.split(": ", 1)[1]
        elif s.startswith("Number Of Shares: "):
            cur["shares"] = _int(s.split(": ", 1)[1]) or 0
    if cur.get("name") and section == "OWNERSHIP":
        out.append(cur)
    return out if seen else None


def check_tx_on_tick(text: str, tx_hash: str, tick: int) -> bool | None:
    """-checktxontick -> True (found), False (definitely absent), None (unknown)."""
    if re.search(rf"Found tx {tx_hash} on tick {tick}\b", text):
        return True
    if re.search(rf"Can NOT find tx {tx_hash} on tick {tick}\b", text):
        return False
    return None  # "Please wait a bit more", "empty, not in current epoch or in the future", garbage
