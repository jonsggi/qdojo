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


def check_tx_on_tick(text: str, tx_hash: str, tick: int) -> bool | None:
    """-checktxontick -> True (found), False (definitely absent), None (unknown)."""
    if re.search(rf"Found tx {tx_hash} on tick {tick}\b", text):
        return True
    if re.search(rf"Can NOT find tx {tx_hash} on tick {tick}\b", text):
        return False
    return None  # "Please wait a bit more", "empty, not in current epoch or in the future", garbage
