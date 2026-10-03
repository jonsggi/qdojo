"""A READ-ONLY client for Qubic's public HTTP RPC (rpc.qubic.org, qubic-http).

Two endpoints and nothing else:
- `GET  /v1/tick-info`            the current tick and epoch;
- `POST /v1/querySmartContract`   a contract FUNCTION (a read): contract index,
  input type, input size and the input bytes, base64. The answer is the
  function's output struct, base64.

There is deliberately no broadcast, no balance-moving call and no signing
here: the client refuses any other path, so it cannot send a transaction to
any network. Seeds and keys never enter it.

Politeness: one request at a time with at least `min_interval` seconds
between requests (a token bucket of one), exponential backoff with jitter on
HTTP 429, 5xx and network errors (honouring Retry-After), and a short-lived
cache of answers, so a poll loop that asks twice in a row costs one request.

The public endpoint sits behind Cloudflare, which answers 403 to Python's
default user agent; the client sends its own.
"""
from __future__ import annotations

import base64
import json
import random
import threading
import time
import urllib.error
import urllib.request

MAINNET_RPC = "https://rpc.qubic.org"
TESTNET_RPC = "https://testnet-rpc.qubic.org"
USER_AGENT = "qdojo-qbay-mirror/1 (read-only; +https://github.com/jonsggi/qdojo)"
ALLOWED = {("GET", "/v1/tick-info"), ("POST", "/v1/querySmartContract")}


class RpcError(RuntimeError):
    """The RPC could not answer (after retries), or answered nonsense."""


class RpcClient:
    def __init__(self, base_url: str = MAINNET_RPC, *, timeout: float = 15.0, min_interval: float = 0.35,
                 retries: int = 4, backoff: float = 1.0, max_backoff: float = 30.0, cache_ttl: float = 2.0,
                 opener=None, clock=time.monotonic, sleep=time.sleep, rng=None):
        self.base = base_url.rstrip("/")
        self.timeout, self.min_interval, self.retries = timeout, min_interval, retries
        self.backoff, self.max_backoff, self.cache_ttl = backoff, max_backoff, cache_ttl
        self._open = opener or urllib.request.urlopen
        self._clock, self._sleep = clock, sleep
        self._rng = rng or random.Random()
        self._lock = threading.Lock()
        self._last = -1e18
        self._cache: dict[tuple, tuple[float, object]] = {}
        self.stats = {"requests": 0, "retries": 0, "cache_hits": 0, "errors": 0}

    # -- transport ---------------------------------------------------------------

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        if (method, path) not in ALLOWED:
            raise RpcError(f"refused: {method} {path} is not a read this client makes")
        data = json.dumps(body).encode() if body is not None else None
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            with self._lock:
                wait = self._last + self.min_interval - self._clock()
                if wait > 0:
                    self._sleep(wait)
                self._last = self._clock()
                self.stats["requests"] += 1
                retry_after = None
                try:
                    req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
                    with self._open(req, timeout=self.timeout) as resp:
                        raw = resp.read()
                    try:
                        return json.loads(raw)
                    except ValueError as exc:
                        raise RpcError(f"{path}: not JSON") from exc
                except urllib.error.HTTPError as exc:
                    last_exc = exc
                    if exc.code != 429 and exc.code < 500:
                        self.stats["errors"] += 1
                        raise RpcError(f"{path}: HTTP {exc.code}") from exc
                    ra = exc.headers.get("Retry-After") if exc.headers else None
                    retry_after = float(ra) if ra and ra.replace(".", "", 1).isdigit() else None
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    last_exc = exc
            if attempt == self.retries:
                break
            self.stats["retries"] += 1
            delay = min(self.max_backoff, self.backoff * 2 ** attempt) * (0.5 + self._rng.random() / 2)
            self._sleep(max(delay, retry_after or 0))
        self.stats["errors"] += 1
        raise RpcError(f"{path}: unreachable after {self.retries + 1} attempts ({last_exc})")

    def _cached(self, key: tuple, fetch, cache: bool):
        now = self._clock()
        hit = self._cache.get(key)
        if cache and hit is not None and now - hit[0] <= self.cache_ttl:
            self.stats["cache_hits"] += 1
            return hit[1]
        value = fetch()
        self._cache[key] = (self._clock(), value)
        if len(self._cache) > 4096:
            self._cache.clear()
        return value

    # -- the two reads -----------------------------------------------------------

    def tick_info(self, cache: bool = True) -> dict:
        def fetch():
            doc = self._request("GET", "/v1/tick-info")
            info = doc.get("tickInfo") or doc
            if not isinstance(info.get("tick"), int):
                raise RpcError("/v1/tick-info: no tick")
            return {"tick": info["tick"], "epoch": info.get("epoch")}
        return self._cached(("tick",), fetch, cache)

    def query_raw(self, contract_index: int, input_type: int, data: bytes) -> dict:
        """The raw JSON answer (what the test fixtures record)."""
        return self._request("POST", "/v1/querySmartContract", {
            "contractIndex": contract_index, "inputType": input_type, "inputSize": len(data),
            "requestData": base64.b64encode(data).decode()})

    def query(self, contract_index: int, input_type: int, data: bytes = b"", cache: bool = True) -> bytes:
        def fetch():
            doc = self.query_raw(contract_index, input_type, data)
            out = doc.get("responseData")
            if not isinstance(out, str):
                raise RpcError(f"querySmartContract {contract_index}/{input_type}: no responseData")
            try:
                return base64.b64decode(out, validate=True)
            except ValueError as exc:
                raise RpcError("responseData is not base64") from exc
        return self._cached(("q", contract_index, input_type, bytes(data)), fetch, cache)


class FixtureRpc:
    """Answers from recorded responses (tests): {"queries": [{contract, input_type,
    request (b64), response (b64)}], "tick_info": {...}}. Unknown requests raise,
    so a test can never fall through to the network."""

    def __init__(self, *docs: dict):
        self.answers: dict[tuple, bytes] = {}
        self.tick = None
        for doc in docs:
            for q in doc.get("queries", []):
                self.answers[(q["contract"], q["input_type"], base64.b64decode(q["request"]))] = \
                    base64.b64decode(q["response"])
            self.tick = doc.get("tick_info", self.tick)
        self.calls = 0
        self.down = False

    def query(self, contract_index, input_type, data=b"", cache=True):
        self.calls += 1
        if self.down:
            raise RpcError("fixture RPC is down")
        key = (contract_index, input_type, bytes(data))
        if key not in self.answers:
            raise RpcError(f"no recorded answer for {contract_index}/{input_type}/{bytes(data).hex()}")
        return self.answers[key]

    def tick_info(self, cache=True):
        if self.down:
            raise RpcError("fixture RPC is down")
        if self.tick is None:
            raise RpcError("no recorded tick")
        return dict(self.tick)
