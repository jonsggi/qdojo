"""The public indexer (rpc.qubic.org). Discovery only: never authoritative for
money. Every transaction that matters is confirmed against a node afterwards."""
import json
import urllib.request
import urllib.error

from ..round import Observed
from .base import Unknown

BASE = "https://rpc.qubic.org"


def _get(path: str, timeout: int = 25):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "qdojo/0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        raise Unknown(f"indexer {path}: {e}")


def parse_transactions(doc) -> list[Observed]:
    """Walk any indexer response and collect transaction objects. The indexer
    nests them differently per endpoint; the fields we need are stable."""
    out = []

    def walk(x):
        if isinstance(x, dict):
            if {"sourceId", "destId", "tickNumber", "inputHex"} <= set(x):
                txid = x.get("txId") or x.get("transactionId") or ""
                out.append(Observed(tick=int(x["tickNumber"]), tx_id=txid, source=x["sourceId"], dest=x["destId"],
                                    amount=int(x.get("amount", 0)), input_type=int(x.get("inputType", 0)),
                                    payload=bytes.fromhex(x.get("inputHex") or "")))
                return
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(doc)
    return out


class Indexer:
    def __init__(self, base: str = BASE, timeout: int = 25):
        self.base, self.timeout = base, timeout
        self.identity = ""

    def current_tick(self) -> int:
        d = _get("/v1/tick-info", self.timeout)
        t = d.get("tickInfo", {}).get("tick")
        if not isinstance(t, int) or t <= 0:
            raise Unknown("indexer tick-info had no tick")
        return t

    def indexed_tick(self) -> int:
        """The last tick the archive has processed. Anything after it is not
        absent, it is not indexed yet."""
        d = _get("/v1/status", self.timeout)
        t = (d.get("lastProcessedTick") or {}).get("tickNumber")
        if not isinstance(t, int) or t <= 0:
            raise Unknown("indexer status had no lastProcessedTick")
        return t

    def transactions_to(self, identity: str, start_tick: int, end_tick: int) -> list[Observed]:
        d = _get(f"/v2/identities/{identity}/transfers?startTick={start_tick}&endTick={end_tick}", self.timeout)
        if "code" in d and "message" in d and "transactions" not in d:
            raise Unknown(f"indexer refused: {d.get('message')}")
        txs = [o for o in parse_transactions(d) if o.dest == identity and start_tick <= o.tick <= end_tick]
        return sorted(txs)

    def transactions_in_tick(self, tick: int) -> list[Observed]:
        d = _get(f"/v2/ticks/{tick}/transactions", self.timeout)
        if "code" in d and "transactions" not in d:
            raise Unknown(f"indexer refused tick {tick}: {d.get('message')}")
        return sorted(parse_transactions(d))
