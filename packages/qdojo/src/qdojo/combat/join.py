"""Outside builders in the demo arena: register a fighter on the SIMULATED
chain and run your own bot against it from your own machine (AUD-027).

Nothing here executes builder code on the server. The builder runs
`qdojo combat join`, which runs the ordinary owner bot (bot.py) locally with a
`RemoteClient`: reads come from the arena's read API, and every write is a
Qubic-format transaction (qubic/tx.py) signed with SchnorrQ by a key that
never leaves the builder's machine. The arena accepts only:

- a signed registration (name + public key): the arena issues a simulated
  fighter NFT to that key, grants fake QU, and discloses it as `outside`;
- signed player transactions whose 512-byte input is one combat call frame
  (codec.py) with an allowed opcode, from a registered outside key.

Three parts, three processes:
- `JoinService` sits in the API server (`qdojo combat api --join-inbox`):
  validates, verifies signatures, rate-limits and queues into the inbox.
- `ArenaInbox` sits in the arena (`qdojo combat live --join-inbox`): each
  tick it issues queued registrations and submits queued transactions to
  `SimChain` like any bot's, then records receipts.
- `RemoteClient` + `cmd_join` on the builder's machine.

The inbox is one SQLite file in the arena directory, written by both the API
(new rows) and the arena (status changes). Everything is disabled unless both
processes get --join-inbox; see docs/build-a-bot.md §8 and docs/operations.md §8.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import secrets
import sqlite3
import struct
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field, fields
from http.client import HTTPException
from pathlib import Path

from ..hashing import sha256
from ..portable import private_modes_enforced
from ..qubic import ids, schnorrq
from ..qubic.k12 import k12
from ..qubic.tx import SIGNATURE_SIZE, TX_SIZE, Transaction
from . import codec
from .codec import Code, Op

INPUT_TYPE = 1                          # a combat call: input is exactly one 512-byte frame
TX_LEN = TX_SIZE + codec.FRAME_LEN + SIGNATURE_SIZE
REGISTER_TAG = b"qdojo/combat/join/register/v1\0"
OUTSIDE_LABEL = "outside:"             # asset label prefix: outside fighter IDs never collide with house ones
OUTSIDE_FILE = "outside.json"          # the arena's list of outside fighters (read at every start)
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,15}$")
# Names starting with this (any case) are the operator's smoke tests (docs/beta.md §3):
# the gateway takes them only from a key in Limits.operator_keys, and the community
# measurements (community.py) count such fighters as operator tests, never as builders.
OPERATOR_TEST_PREFIX = "test-"
# A registration's client address serves only the per-address limit, which looks
# back this far; after that the inbox forgets it (docs/beta.md §8).
ADDRESS_KEEP_SECONDS = 86_400
# The only answers that mean entry is closed (as the site's entryStatus reads them).
CLOSED_CODES = ("join_disabled", "join_closed")
MAX_RESPONSE = 2 * 1024 * 1024          # bytes: far above any arena document (a replay is ~35 KB)
# What an outside key may send. Never the admin opcodes; no SET_OPERATOR (the
# key that registered is the key that plays); no ADVANCE (the house keeper runs it).
PLAYER_OPS = frozenset({Op.REGISTER_FIGHTER, Op.QUEUE_ENTER, Op.QUEUE_CANCEL, Op.DUEL_OFFER, Op.DUEL_ACCEPT,
                        Op.DUEL_CANCEL, Op.COMMIT, Op.REVEAL, Op.WITHDRAW, Op.CUP_REGISTER, Op.CUP_WITHDRAW,
                        Op.CUP_CHECK_IN})
DEFAULT_PUBLIC_KEY = ids.public_key_from_identity(ids.PUBLIC_DEFAULT_IDENTITY)


def operator_test_name(name) -> bool:
    """Whether a fighter name is reserved for the operator's smoke tests."""
    return str(name or "").lower().startswith(OPERATOR_TEST_PREFIX)


def address_key(ip: str) -> str:
    """What the per-address registration limit counts, and all the inbox keeps of
    a client address: an IPv4 address as it is, an IPv6 address as its /64
    network (one subscriber's usual allocation, every address of which a single
    host can use)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.version == 6 and addr.ipv4_mapped:
        return str(addr.ipv4_mapped)
    if addr.version == 6:
        return str(ipaddress.ip_network((addr, 64), strict=False))
    return str(addr)


def printable(text, limit: int | None = 200) -> str:
    """Text from the arena made safe to print: control and other non-printing
    characters (an escape sequence can redraw or retitle a terminal) are shown
    escaped, and the length is capped."""
    s = "".join(c if c.isprintable() else c.encode("unicode_escape").decode("ascii") for c in str(text))
    return s if limit is None or len(s) <= limit else s[:limit] + "..."


@dataclass
class Limits:
    """Quotas, and the operator's own keys. Every value is a decision for the operator (docs/operations.md §8)."""
    max_outside_fighters: int = 8          # all time, across all builders; a revoked registration frees its place
    registrations_per_day: int = 10        # global
    registrations_per_ip_day: int = 2      # per client address (an IPv6 client: per /64)
    grant_qu: int = 100_000                # fake QU minted to a new outside owner, once
    max_amount: int = 20_000               # largest attachment on one transaction
    tx_burst: int = 20                     # token bucket per identity
    tx_per_second: float = 1.0
    tx_per_day: int = 20_000               # per identity
    reads_per_second: float = 20.0         # chain reads, per client address (an IPv6 client: per /64)
    max_pending: int = 400                 # queued transactions, all identities together
    tick_behind: int = 30                  # a transaction's tick field must be within
    tick_ahead: int = 60                   # [tick - behind, tick + ahead] of the arena
    operator_keys: list = field(default_factory=list)   # public keys (64 hex) that may register test- names

    @classmethod
    def load(cls, path: Path) -> "Limits":
        raw = json.loads(Path(path).read_text())
        known = {f.name for f in fields(cls)}
        unknown = set(raw) - known
        if unknown:
            raise SystemExit(f"qdojo: unknown join limits: {sorted(unknown)}")
        keys = raw.get("operator_keys", [])
        if not (isinstance(keys, list) and all(isinstance(k, str) and re.fullmatch(r"[0-9a-fA-F]{64}", k)
                                               for k in keys)):
            raise SystemExit("qdojo: join limits: operator_keys is a list of public keys, 64 hex digits each")
        return cls(**{**raw, "operator_keys": [k.lower() for k in keys]})

    def public(self) -> dict:
        """The quotas as GET /api/v1/join publishes them (the operator's keys stay private)."""
        return {k: v for k, v in asdict(self).items() if k != "operator_keys"}


class JoinError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def fighter_id_for(name: str) -> bytes:
    """The simulated NFT's fighter ID, as SimFighterNFTs.id_for derives it for the arena's issuer."""
    from .live import ISSUER_LABEL
    from .sim import identity
    return sha256(b"qdojo/combat/sim-asset/v1\0", identity(ISSUER_LABEL), b"QDOJOF", (OUTSIDE_LABEL + name).encode())


def register_digest(network_id: bytes, contract_id: bytes, public_key: bytes, name: str, tick: int) -> bytes:
    return k12(REGISTER_TAG + network_id + contract_id + public_key + struct.pack("<Q", tick) + name.encode(), 32)


def parse_tx(raw: bytes) -> tuple[Transaction, bytes]:
    if len(raw) != TX_LEN:
        raise JoinError(400, "bad_tx", f"a combat transaction is exactly {TX_LEN} bytes")
    src, dst, amount, tick, itype, isize = struct.unpack_from("<32s32sqIHH", raw, 0)
    if isize != codec.FRAME_LEN or itype != INPUT_TYPE:
        raise JoinError(400, "bad_tx", f"input_type must be {INPUT_TYPE} with a {codec.FRAME_LEN}-byte frame")
    if amount < 0:
        raise JoinError(400, "bad_tx", "negative amount")
    return Transaction(src, dst, amount, tick, itype, raw[TX_SIZE:TX_SIZE + isize]), raw[TX_SIZE + isize:]


def _jsonable(v):
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).hex()
    if isinstance(v, (set, frozenset)):
        return sorted(v)
    if isinstance(v, dict):
        return {(k.hex() if isinstance(k, bytes) else str(k)): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


def result_json(r) -> dict:
    return {"code": r.code.name, "op": r.op, "target": r.target, "refunded": r.refunded, "detail": r.detail,
            "data": _jsonable(r.data)}


# ---- the inbox (one SQLite file shared by the API and the arena) -------------------

INBOX_DDL = """
CREATE TABLE IF NOT EXISTS registrations(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, owner TEXT NOT NULL UNIQUE,
  fighter_id TEXT NOT NULL, ip TEXT, received REAL NOT NULL, status TEXT NOT NULL, detail TEXT, tick INTEGER);
CREATE TABLE IF NOT EXISTS txs(
  hash TEXT PRIMARY KEY, who TEXT NOT NULL, op INTEGER NOT NULL, frame BLOB NOT NULL, amount INTEGER NOT NULL,
  received REAL NOT NULL, status TEXT NOT NULL, sim_tx INTEGER, target_tick INTEGER, result TEXT);
CREATE INDEX IF NOT EXISTS txs_status ON txs(status);
CREATE TABLE IF NOT EXISTS usage(who TEXT NOT NULL, day TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY(who, day));
CREATE TABLE IF NOT EXISTS config(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def inbox(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=10, check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(INBOX_DDL)
    conn.row_factory = sqlite3.Row
    os.chmod(path, 0o600)
    return conn


def _day() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def forget_addresses(db: sqlite3.Connection, older_than: float = ADDRESS_KEEP_SECONDS) -> int:
    """Clear the client address of every registration received more than
    `older_than` seconds ago (0: every one). Returns how many were cleared."""
    cutoff = time.time() - older_than
    if db.execute("SELECT 1 FROM registrations WHERE ip IS NOT NULL AND received <= ? LIMIT 1",
                  (cutoff,)).fetchone() is None:
        return 0                                # the arena calls this every tick: no write unless one is due
    return db.execute("UPDATE registrations SET ip = NULL WHERE ip IS NOT NULL AND received <= ?", (cutoff,)).rowcount


def recorded_limits(db: sqlite3.Connection) -> Limits | None:
    """The limits the API recorded in the inbox when it started (JoinService), if any."""
    row = db.execute("SELECT value FROM config WHERE key = 'limits'").fetchone()
    if row is None:
        return None
    known = {f.name for f in fields(Limits)}
    return Limits(**{k: v for k, v in json.loads(row[0]).items() if k in known})


def revoke(db: sqlite3.Connection, name: str, reason: str) -> sqlite3.Row:
    """Retire a registration (operator only): its key can no longer send, and its
    place no longer counts toward max_outside_fighters or the day's global
    registrations, in the API and in the arena. The fighter, its NFT and its
    fights stay in the record, labelled outside."""
    row = db.execute("SELECT * FROM registrations WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise SystemExit(f"qdojo: no registration named {name!r}")
    if row["status"] not in ("new", "active"):
        raise SystemExit(f"qdojo: {row['name']} is {row['status']} already; nothing to revoke")
    db.execute("BEGIN")
    db.execute("UPDATE registrations SET status = 'revoked', detail = ? WHERE id = ?", (reason, row["id"]))
    db.execute("UPDATE txs SET status = 'dropped', result = ? WHERE who = ? AND status = 'new'",
               (json.dumps({"code": None, "detail": "registration revoked"}), row["owner"]))
    db.execute("COMMIT")
    return db.execute("SELECT * FROM registrations WHERE id = ?", (row["id"],)).fetchone()


# ---- API side ------------------------------------------------------------------------

class Bucket:
    def __init__(self, capacity: float, rate: float):
        self.capacity, self.rate = capacity, rate
        self.level: dict[str, tuple[float, float]] = {}
        self.lock = threading.Lock()

    def take(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            level, at = self.level.get(key, (self.capacity, now))
            level = min(self.capacity, level + (now - at) * self.rate)
            if level < 1:
                self.level[key] = (level, now)
                return False
            self.level[key] = (level - 1, now)
            if len(self.level) > 10_000:                      # bounded memory under a spray of keys
                self.level = {k: v for k, v in self.level.items() if now - v[1] < 3600}
            return True


class JoinService:
    """The API's write and chain-read endpoints. Stateless apart from the inbox and rate buckets."""

    def __init__(self, inbox_path: Path, limits: Limits):
        self.path, self.limits = Path(inbox_path), limits
        self.db = inbox(self.path)
        # The arena issues fighters (its cap, the QU grant) by these same limits (ArenaInbox.limits).
        self.db.execute("INSERT INTO config(key, value) VALUES('limits', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (json.dumps(asdict(limits)),))
        self.lock = threading.Lock()
        self.tx_bucket = Bucket(limits.tx_burst, limits.tx_per_second)
        self.read_bucket = Bucket(4 * limits.reads_per_second, limits.reads_per_second)
        self.follower = None

    def attach(self, follower):
        self.follower = follower

    # -- replica reads --------------------------------------------------------------

    def _replica(self):
        fl = self.follower
        if fl is None or fl.replica is None or fl.replica.contract is None or not fl.caught_up:
            raise JoinError(503, "not_ready", "the arena replica is still catching up")
        return fl

    def _client(self, signer: bytes = bytes(32)):
        from .devnet import DevnetClient
        from .scouting import Scout
        fl = self._replica()

        class View:                                 # what DevnetClient needs from a Devnet
            world, m = fl.replica, fl.m
            scout = fl.__dict__.setdefault("_scout", Scout())
        return fl, DevnetClient(View, signer)

    def _names(self) -> set[str]:
        fl = self.follower
        dep = fl.deployment() if fl else {}
        taken = {str(v).lower() for v in (dep.get("names") or {}).values()}
        taken |= {r[0].lower() for r in self.db.execute("SELECT name FROM registrations")}
        return taken

    # -- routes --------------------------------------------------------------------

    def get(self, parts: list[str], q: dict, ip: str) -> tuple[int, dict]:
        try:
            return self._get(parts, q, ip)
        except JoinError as e:
            return e.status, {"schema": "qdojo.combat.api.error.v1",
                              "error": {"status": e.status, "code": e.code, "message": e.message}}

    def post(self, parts: list[str], body: dict, ip: str) -> tuple[int, dict]:
        try:
            if parts == ["join", "register"]:
                return self.register(body, ip)
            if parts == ["tx"]:
                return self.submit(body, ip)
            raise JoinError(404, "not_found", "no such endpoint")
        except JoinError as e:
            return e.status, {"schema": "qdojo.combat.api.error.v1",
                              "error": {"status": e.status, "code": e.code, "message": e.message}}

    def _get(self, parts, q, ip):
        one = lambda k: (q.get(k) or [None])[-1]                           # noqa: E731
        if parts == ["join"]:
            fl = self.follower
            if fl is None:                  # `api --rebuild` attaches it once the new database is in
                raise JoinError(503, "not_ready", "the arena replica is still catching up")
            active = self.db.execute("SELECT COUNT(*) FROM registrations WHERE status IN ('new','active')").fetchone()[0]
            return 200, {"schema": "qdojo.combat.api.join.v1", "enabled": True, "chain": "simulated",
                         "currency": "devnet QU", "network_id": fl.m.network_id.hex(),
                         "contract_id": fl.m.contract_id.hex(), "input_type": INPUT_TYPE,
                         "tx_bytes": TX_LEN, "register_tag": REGISTER_TAG.decode().rstrip("\0"),
                         "tiers": {str(k): v for k, v in fl.m.tiers.items()},
                         "ruleset_digest": fl.m.ruleset.digest.hex(),
                         "timing_profiles": {str(k): list(v) for k, v in fl.m.timing.items()},
                         "outside_fighters": active, "limits": self.limits.public(),
                         "allowed_ops": sorted(o.name for o in PLAYER_OPS)}
        if parts == ["join", "status"]:
            owner, name = one("owner"), one("name")
            row = None
            if owner and re.fullmatch(r"[0-9a-f]{64}", owner):
                row = self.db.execute("SELECT * FROM registrations WHERE owner = ?", (owner,)).fetchone()
            elif name:
                row = self.db.execute("SELECT * FROM registrations WHERE name = ?", (name,)).fetchone()
            if row is None:
                raise JoinError(404, "not_found", "no registration for that owner or name")
            return 200, {"name": row["name"], "owner": row["owner"], "fighter_id": row["fighter_id"],
                         "status": row["status"], "detail": row["detail"], "tick": row["tick"]}
        if len(parts) == 2 and parts[0] == "tx":
            if not re.fullmatch(r"[a-z]{60}", parts[1]):
                raise JoinError(400, "bad_id", "a transaction hash is 60 lowercase letters")
            row = self.db.execute("SELECT * FROM txs WHERE hash = ?", (parts[1],)).fetchone()
            if row is None:
                raise JoinError(404, "not_found", "unknown transaction")
            return 200, {"hash": row["hash"], "status": row["status"], "target_tick": row["target_tick"],
                         "result": json.loads(row["result"]) if row["result"] else None}
        if parts[:1] == ["chain"]:
            if not self.read_bucket.take(address_key(ip)):     # one host may use every address of its /64
                raise JoinError(429, "rate_limited", "too many chain reads; slow down")
            return self._chain(parts[1:], one)
        raise JoinError(404, "not_found", "no such endpoint")

    def _chain(self, parts, one):
        hexarg = lambda k: bytes.fromhex(v) if (v := one(k)) and re.fullmatch(r"[0-9a-f]{64}", v) else None  # noqa: E731
        if parts == ["state"]:
            fid, who = hexarg("fighter"), hexarg("who")
            fl, cl = self._client(who or bytes(32))
            with fl.lock:
                c = fl.replica.contract
                doc = {"tick": fl.replica.tick,
                       "fighter": _jsonable(cl.fighter(fid)) if fid else None,
                       "balance": cl.balance(who) if who else None, "credit": cl.credit(who) if who else None,
                       "nonce": c.nonces[who][0] if who and who in c.nonces else 0,
                       "open_cups": _jsonable(cl.open_cups()),
                       "duel_offers": _jsonable(cl.duel_offers_for(fid)) if fid else []}
            return 200, doc
        if len(parts) == 2 and parts[0] == "fight" and re.fullmatch(r"[0-9]{1,12}", parts[1]):
            slot = one("slot")
            fl, cl = self._client()
            with fl.lock:
                f = cl.fight(int(parts[1]))
                if f is None:
                    raise JoinError(404, "not_found", "no such fight")
                obs = f["observation"](slot) if slot in ("A", "B") and f["phase"] != "DONE" else None
                doc = _jsonable({k: v for k, v in f.items() if k != "observation"})
            doc["observation"] = obs
            doc["tick"] = fl.replica.tick
            return 200, doc
        if parts == ["spend"]:
            ref, fid = one("ref") or "", hexarg("fighter")
            if not re.fullmatch(r"(offer|contest|cup):[0-9]{1,12}", ref) or fid is None:
                raise JoinError(400, "bad_query", "ref is offer:N, contest:N or cup:N; fighter is 64 hex digits")
            fl, cl = self._client()
            with fl.lock:
                out = cl.spend_outcome(ref, fid)
            return 200, {"ref": ref, "outcome": list(out) if out is not None else None}
        raise JoinError(404, "not_found", "no such chain read")

    def _tick(self) -> int:
        return self._replica().replica.tick

    def register(self, body: dict, ip: str) -> tuple[int, dict]:
        lim = self.limits
        name, pk, sig, tick = body.get("name"), body.get("public_key"), body.get("signature"), body.get("tick")
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):     # $ alone lets a trailing newline through
            raise JoinError(400, "bad_name", "a name is 3-16 letters, digits, '-' or '_', starting with a letter or digit")
        if not (isinstance(pk, str) and re.fullmatch(r"[0-9a-f]{64}", pk) and isinstance(sig, str)
                and re.fullmatch(r"[0-9a-f]{128}", sig) and isinstance(tick, int)):
            raise JoinError(400, "bad_body", "public_key (64 hex), signature (128 hex) and tick (int) are required")
        pub = bytes.fromhex(pk)
        if pub == DEFAULT_PUBLIC_KEY:
            raise JoinError(400, "bad_key", "that key is derived from the public all-'a' seed")
        if operator_test_name(name) and pk not in lim.operator_keys:
            raise JoinError(403, "name_reserved", f"names starting with '{OPERATOR_TEST_PREFIX}' are reserved for "
                                                  "the operator's smoke tests; choose another name")
        fl = self._replica()
        now_tick = fl.replica.tick
        if not now_tick - lim.tick_behind <= tick <= now_tick + lim.tick_ahead:
            raise JoinError(400, "stale", f"tick {tick} is outside the window around the arena tick {now_tick}")
        digest = register_digest(fl.m.network_id, fl.m.contract_id, pub, name, tick)
        if not schnorrq.verify(pub, digest, bytes.fromhex(sig)):
            raise JoinError(401, "bad_signature", "the signature does not verify for that public key")
        with self.lock:
            row = self.db.execute("SELECT * FROM registrations WHERE owner = ?", (pk,)).fetchone()
            if row is not None:
                if row["name"].lower() == name.lower():
                    return 200, {"status": row["status"], "name": row["name"], "fighter_id": row["fighter_id"]}
                raise JoinError(409, "one_per_key", f"this key already registered {row['name']}")
            if name.lower() in self._names():
                raise JoinError(409, "name_taken", "that name is taken")
            n = self.db.execute("SELECT COUNT(*) FROM registrations WHERE status IN ('new','active')").fetchone()[0]
            if n >= lim.max_outside_fighters:
                raise JoinError(403, "arena_full", "the arena has no room for more outside fighters right now")
            forget_addresses(self.db)
            since = time.time() - ADDRESS_KEEP_SECONDS
            addr = address_key(ip)
            day = self.db.execute("SELECT COUNT(*) FROM registrations WHERE received > ? AND status != 'revoked'",
                                  (since,)).fetchone()[0]
            by_ip = self.db.execute("SELECT COUNT(*) FROM registrations WHERE received > ? AND ip = ?",
                                    (since, addr)).fetchone()[0]
            if day >= lim.registrations_per_day or by_ip >= lim.registrations_per_ip_day:
                raise JoinError(429, "rate_limited", "registration limit reached; try again tomorrow")
            fid = fighter_id_for(name).hex()
            self.db.execute("INSERT INTO registrations(name, owner, fighter_id, ip, received, status) "
                            "VALUES(?,?,?,?,?, 'new')", (name, pk, fid, addr, time.time()))
        return 202, {"status": "new", "name": name, "fighter_id": fid, "owner": pk,
                     "note": "the arena issues the fighter within a few ticks; then send REGISTER_FIGHTER"}

    def submit(self, body: dict, ip: str) -> tuple[int, dict]:
        lim = self.limits
        raw_hex = body.get("tx")
        if not isinstance(raw_hex, str) or len(raw_hex) != 2 * TX_LEN or not re.fullmatch(r"[0-9a-f]+", raw_hex):
            raise JoinError(400, "bad_tx", f"tx is {TX_LEN} bytes as lowercase hex")
        raw = bytes.fromhex(raw_hex)
        tx, sig = parse_tx(raw)
        fl = self._replica()
        if tx.destination_public_key != fl.m.contract_id:
            raise JoinError(400, "wrong_contract", "the destination is not this arena's contract")
        who = tx.source_public_key.hex()
        reg = self.db.execute("SELECT status FROM registrations WHERE owner = ?", (who,)).fetchone()
        if reg is not None and reg["status"] == "revoked":
            raise JoinError(403, "revoked", "the operator revoked this registration")
        if reg is None or reg["status"] != "active":
            raise JoinError(403, "not_registered", "only a registered, issued outside key may send transactions")
        if tx.amount > lim.max_amount:
            raise JoinError(400, "amount_cap", f"attachments are capped at {lim.max_amount} fake QU")
        now_tick = fl.replica.tick
        if not now_tick - lim.tick_behind <= tx.tick <= now_tick + lim.tick_ahead:
            raise JoinError(400, "stale", f"tick {tx.tick} is outside the window around the arena tick {now_tick}")
        try:
            req = codec.decode_frame(tx.input_bytes)
        except codec.CodecError as exc:
            raise JoinError(400, "bad_frame", str(exc)) from None
        if req.op not in PLAYER_OPS:
            raise JoinError(403, "op_not_allowed", f"{req.op.name} is not a player operation here")
        if not schnorrq.verify(tx.source_public_key, tx.digest(), sig):
            raise JoinError(401, "bad_signature", "the signature does not verify for the source key")
        if not self.tx_bucket.take(who):
            raise JoinError(429, "rate_limited", "too many transactions from this key; slow down")
        from ..qubic.ids import tx_hash_from_digest
        h = tx_hash_from_digest(k12(raw, 32))
        with self.lock:
            old = self.db.execute("SELECT status FROM txs WHERE hash = ?", (h,)).fetchone()
            if old is not None:
                return 200, {"hash": h, "status": old["status"]}
            pending = self.db.execute("SELECT COUNT(*) FROM txs WHERE status IN ('new','pending')").fetchone()[0]
            if pending >= lim.max_pending:
                raise JoinError(503, "busy", "the arena inbox is full; retry shortly")
            day = _day()
            used = self.db.execute("SELECT n FROM usage WHERE who = ? AND day = ?", (who, day)).fetchone()
            if used and used[0] >= lim.tx_per_day:
                raise JoinError(429, "quota", "daily transaction quota reached for this key")
            self.db.execute("BEGIN")
            self.db.execute("INSERT INTO usage VALUES(?,?,1) ON CONFLICT(who, day) DO UPDATE SET n = n + 1", (who, day))
            self.db.execute("INSERT INTO txs(hash, who, op, frame, amount, received, status) VALUES(?,?,?,?,?,?, 'new')",
                            (h, who, int(req.op), tx.input_bytes, tx.amount, time.time()))
            self.db.execute("COMMIT")
        return 202, {"hash": h, "status": "new"}


# ---- arena side ------------------------------------------------------------------------

def load_outside(arena_dir: Path) -> list[dict]:
    """The arena's outside fighters (lineup-shaped entries), whether or not joining is enabled now."""
    try:
        return json.loads((Path(arena_dir) / OUTSIDE_FILE).read_text())
    except (OSError, ValueError):
        return []


class ArenaInbox:
    """Called by live.Arena.step(): issue registrations, submit transactions, record receipts."""

    def __init__(self, path: Path, limits: Limits | None = None):
        self.db = inbox(Path(path))
        self.fixed = limits
        # In-flight SimChain transactions do not survive a restart; tell their senders to resend.
        self.db.execute("UPDATE txs SET status = 'dropped', result = ? WHERE status = 'pending'",
                        (json.dumps({"code": None, "detail": "arena restarted before inclusion"}),))

    @property
    def limits(self) -> Limits:
        """The limits given, else the ones the API recorded in the inbox (its --join-config), so
        the cap and the QU grant the arena applies are the ones GET /api/v1/join publishes."""
        return self.fixed or recorded_limits(self.db) or Limits()

    def drain(self, arena):
        """Before the tick's transactions run: new registrations, then new transactions.
        Also forgets client addresses older than the per-address limit's window."""
        forget_addresses(self.db)
        for row in self.db.execute("SELECT * FROM registrations WHERE status = 'new' ORDER BY id").fetchall():
            self._register(arena, row)
        for row in self.db.execute("SELECT * FROM txs WHERE status = 'new' ORDER BY received LIMIT 200").fetchall():
            receipt = arena.chain.submit(bytes.fromhex(row["who"]), bytes(row["frame"]), row["amount"])
            self.db.execute("UPDATE txs SET status = 'pending', sim_tx = ?, target_tick = ? WHERE hash = ?",
                            (receipt.tx_id, receipt.target_tick, row["hash"]))

    def settle(self, arena):
        """After the tick: included or dropped."""
        for row in self.db.execute("SELECT hash, sim_tx FROM txs WHERE status = 'pending'").fetchall():
            tx = arena.chain.txs.get(row["sim_tx"])
            if tx is None:
                self.db.execute("UPDATE txs SET status = 'dropped' WHERE hash = ?", (row["hash"],))
            elif tx.status == "included":
                self.db.execute("UPDATE txs SET status = 'included', result = ? WHERE hash = ?",
                                (json.dumps(result_json(tx.result)), row["hash"]))
            elif tx.status == "dropped":
                self.db.execute("UPDATE txs SET status = 'dropped' WHERE hash = ?", (row["hash"],))

    def _register(self, arena, row):
        from .devnet import roles
        name, owner = row["name"], bytes.fromhex(row["owner"])
        taken = {e["label"].lower() for e in arena.labels.values()}
        outside = load_outside(arena.dir)
        lim = self.limits
        # A revoked registration's fighter stays listed (and labelled) but no longer holds a place.
        revoked = {r[0] for r in self.db.execute("SELECT fighter_id FROM registrations WHERE status = 'revoked'")}

        def reject(why):
            self.db.execute("UPDATE registrations SET status = 'rejected', detail = ?, tick = ? "
                            "WHERE id = ? AND status = 'new'", (why, arena.w.tick, row["id"]))
            arena.log(f"tick {arena.w.tick}: outside registration {name!r} rejected: {why}")
        if name.lower() in taken:
            return reject("name taken")
        if sum(1 for e in outside if e.get("fighter_id") not in revoked) >= lim.max_outside_fighters:
            return reject("arena full")
        fid = arena.nfts.id_for(OUTSIDE_LABEL + name)
        if fid.hex() != row["fighter_id"] or arena.nfts.token(fid) is not None:
            return reject("asset ID mismatch or already issued")
        # Minted at registration to the builder, who is also its creator (royalties, docs/nft.md §3).
        minted = arena.nfts.poll(arena.nfts.issue(arena.nfts.issuer, fid, owner, creator=owner, immediate=True))
        if minted["code"] != "OK":
            return reject(f"mint refused: {minted['code']}")
        arena.w.mint(owner, lim.grant_qu)
        arena.w.send(roles()["admin"], Op.ADMIN_REGISTER_ASSET, fighter_id=fid, registry_version=1, house_npc=0)
        entry = {"label": name, "origin": "outside", "driver": "builder", "fighter_id": fid.hex(),
                 "owner": owner.hex(), "tick": arena.w.tick}
        tmp = arena.dir / (OUTSIDE_FILE + ".tmp")
        tmp.write_text(json.dumps(outside + [entry], indent=1))
        os.replace(tmp, arena.dir / OUTSIDE_FILE)
        arena.labels[fid] = entry
        arena.save()
        self.db.execute("UPDATE registrations SET status = 'active', tick = ? WHERE id = ? AND status = 'new'",
                        (arena.w.tick, row["id"]))
        arena.log(f"tick {arena.w.tick}: outside fighter {name} issued to {owner.hex()[:12]}")


# ---- builder side: a client over HTTP ----------------------------------------------------

class HttpError(Exception):
    def __init__(self, status: int, doc: dict | None):
        err = doc.get("error") if isinstance(doc, dict) else None
        err = err if isinstance(err, dict) else {}
        code, message = err.get("code"), err.get("message")
        self.code = code if isinstance(code, str) else None
        self.message = message if isinstance(message, str) else ""
        super().__init__(f"HTTP {status}: {self.code or ''} {self.message}".strip())
        self.status, self.doc = status, doc

    def why(self) -> str:
        """The code and message, escaped for printing."""
        return printable(self.code or f"HTTP {self.status}") + (f" ({printable(self.message)})" if self.message else "")


class Refused(HttpError):
    """An error answer to POST /api/v1/join/register: the arena's verdict on the
    registration itself, not on a read around it (see REFUSAL_NEXT). Also
    one_per_key for a key the arena has registered under another name (register())."""


class Http:
    """JSON over HTTP(S) to an arena. Every call is bounded: `timeout` seconds for
    each socket operation, `deadline` seconds for the whole call (connecting,
    headers and body), and at most `max_bytes` of body. A call that runs out of
    time raises TimeoutError; a larger body, or an answer that is not HTTP (another
    service on that port) or is cut off, raises OSError; an answer that is not a
    JSON object raises ValueError."""

    def __init__(self, base: str, timeout: float = 10.0, deadline: float = 30.0, max_bytes: int = MAX_RESPONSE):
        self.base, self.timeout, self.deadline, self.max_bytes = base.rstrip("/"), timeout, deadline, max_bytes

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        # The request runs in a worker so that nothing the server does (a byte every
        # few seconds, in the headers or the body) can hold the caller past the deadline.
        done, box = threading.Event(), {}
        until = time.monotonic() + self.deadline

        def work():
            try:
                box["doc"] = self._call(method, path, body, until)
            except BaseException as exc:            # re-raised in the caller below
                box["exc"] = exc
            finally:
                done.set()
        threading.Thread(target=work, name="qdojo-http", daemon=True).start()
        if not done.wait(self.deadline):
            raise TimeoutError(f"{self.base}{path}: no complete answer within {self.deadline:g} s")
        if "exc" in box:
            raise box["exc"]
        return box["doc"]

    def _read(self, r, until: float) -> bytes:
        read = getattr(r, "read1", r.read)
        chunks, size = [], 0
        while True:
            if time.monotonic() > until:
                raise TimeoutError(f"{self.base}: no complete answer within {self.deadline:g} s")
            chunk = read(65536)
            if not chunk:
                return b"".join(chunks)
            size += len(chunk)
            if size > self.max_bytes:
                raise OSError(f"{self.base}: the answer is larger than {self.max_bytes} bytes; refused")
            chunks.append(chunk)

    def _call(self, method: str, path: str, body: dict | None, until: float) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", "User-Agent": "qdojo-join"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = self._read(r, until)
        except urllib.error.HTTPError as e:
            try:
                doc = json.loads(self._read(e, until))
            except (ValueError, OSError, HTTPException, RecursionError):
                doc = None
            raise HttpError(e.code, doc) from None
        except HTTPException as e:              # BadStatusLine, LineTooLong, IncompleteRead (text the server's: escaped)
            raise OSError(f"{self.base}{path}: not a complete HTTP answer "
                          f"({type(e).__name__}: {printable(e)})") from None
        try:
            doc = json.loads(raw)
        except RecursionError:
            raise ValueError(f"{self.base}{path}: the answer is nested too deeply") from None
        if not isinstance(doc, dict):
            raise ValueError(f"{self.base}{path}: the answer is not a JSON object")
        return doc

    def get(self, path: str) -> dict:
        return self.call("GET", path)

    def post(self, path: str, body: dict) -> dict:
        return self.call("POST", path, body)


@dataclass
class RemoteReceipt:
    """Like chainsim.Pending: a receipt to poll, never a result."""
    tx_hash: str | None
    target_tick: int
    error: str = ""
    code: None = None


class RemoteClient:
    """bot.Client over the arena's API. `refresh()` once per loop; reads between refreshes are cached."""

    def __init__(self, http: Http, info: dict, subseed: bytes, public_key: bytes, fighter_id: bytes,
                 state_dir: Path, log=print):
        self.http, self.info, self.log = http, info, log
        self.subseed, self.pub, self.fid = subseed, public_key, fighter_id
        self.network_id, self.contract_id = bytes.fromhex(info["network_id"]), bytes.fromhex(info["contract_id"])
        self.state_dir = Path(state_dir)
        self.nonce_path = self.state_dir / "nonce.json"
        try:
            self.nonce = json.loads(self.nonce_path.read_text())["nonce"]
        except (OSError, ValueError, KeyError):
            self.nonce = 0
        self.state: dict = {}
        self._fights: dict = {}
        self._obs: dict = {}
        self._spend: dict = {}

    def refresh(self):
        self.state = self.http.get(f"/api/v1/chain/state?fighter={self.fid.hex()}&who={self.pub.hex()}")
        self._fights, self._spend = {}, {}

    # -- reads -----------------------------------------------------------------------

    def tick(self) -> int:
        return int(self.state["tick"])

    def fighter(self, fid: bytes) -> dict | None:
        f = self.state.get("fighter")
        if f is None or fid != self.fid:
            return None
        return {**f, "operator": bytes.fromhex(f["operator"])}

    def balance(self, who: bytes) -> int:
        return int(self.state.get("balance") or 0) if who == self.pub else 0

    def credit(self, who: bytes) -> int:
        return int(self.state.get("credit") or 0) if who == self.pub else 0

    def tier_amount(self, tier: int) -> int | None:
        v = self.info.get("tiers", {}).get(str(tier))
        return int(v) if v is not None else None

    def open_cups(self) -> list[dict]:
        return self.state.get("open_cups") or []

    def duel_offers_for(self, fid: bytes) -> list[dict]:
        return [{**o, "challenger": bytes.fromhex(o["challenger"])} for o in self.state.get("duel_offers") or []]

    def fight(self, fight_id: int) -> dict | None:
        if fight_id not in self._fights:
            try:
                f = self.http.get(f"/api/v1/chain/fight/{int(fight_id)}")
            except HttpError as e:
                if e.status == 404:
                    return None
                raise
            f["committed"], f["revealed"] = set(f["committed"]), set(f["revealed"])

            def observation(slot, fight_id=fight_id, rnd=f["round_index"]):
                key = (fight_id, rnd, slot)
                if key not in self._obs:
                    doc = self.http.get(f"/api/v1/chain/fight/{int(fight_id)}?slot={slot}")
                    self._obs = {key: doc["observation"]}
                return self._obs[key]
            f["observation"] = observation
            self._fights[fight_id] = f
        return self._fights[fight_id]

    def spend_outcome(self, ref: str, fid: bytes):
        if ref not in self._spend:
            out = self.http.get(f"/api/v1/chain/spend?ref={ref}&fighter={fid.hex()}")["outcome"]
            self._spend[ref] = tuple(out) if out is not None else None
        return self._spend[ref]

    # -- writes ---------------------------------------------------------------------------

    def _next_nonce(self) -> int:
        self.nonce = max(self.nonce, int(self.state.get("nonce") or 0)) + 1
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.nonce_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"nonce": self.nonce}))
        os.replace(tmp, self.nonce_path)
        return self.nonce

    def sign(self, op: Op, amount: int, fields_: dict) -> bytes:
        frame = codec.encode_frame(op, self._next_nonce(), fields_)
        tx = Transaction(self.pub, self.contract_id, amount, self.tick() + 2, INPUT_TYPE, frame)
        return tx.sign(self.subseed).payload()

    def send(self, op: Op, amount: int = 0, **fields_) -> RemoteReceipt:
        raw = self.sign(op, amount, fields_)
        try:
            r = self.http.post("/api/v1/tx", {"tx": raw.hex()})
            return RemoteReceipt(r["hash"], self.tick() + 2)
        except (HttpError, OSError) as exc:
            self.log(f"send {op.name} refused: {printable(exc)}")
            return RemoteReceipt(None, self.tick(), str(exc))        # polls as dropped: the bot may resend

    def poll(self, receipt: RemoteReceipt):
        from .contract import CallResult
        if receipt.tx_hash is None:
            return "dropped"
        try:
            r = self.http.get(f"/api/v1/tx/{receipt.tx_hash}")
        except (HttpError, OSError):
            return None
        seen = self.state.get("tick")
        if r["status"] == "included" and seen is not None and int(seen) <= int(r.get("target_tick") or 0):
            return None              # the reads this bot acts on have not reached that tick yet
        if r["status"] == "included":
            x = r["result"]
            return CallResult(Code[x["code"]], x["op"], x["target"], x["refunded"], x["detail"], x["data"])
        if r["status"] == "dropped":
            return "dropped"
        return None


# ---- the CLI flow ---------------------------------------------------------------------

def _home() -> Path:
    return Path(os.environ.get("QDOJO_COMBAT_HOME", os.path.expanduser("~/.qdojo/combat")))


def load_or_make_key(path: Path) -> tuple[bytes, bytes]:
    """A throwaway seed for the SIMULATED arena, created 0600 on first use. Never your real Qubic seed."""
    path = Path(path)
    if path.exists():
        if private_modes_enforced() and path.stat().st_mode & 0o077:
            raise SystemExit(f"qdojo: {path} is readable by others; chmod 600 it first")
        seed = path.read_text().strip()
    else:
        seed = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(ids.SEED_LEN))
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(seed + "\n")
    subseed, _priv, pub = ids.keys_from_seed(seed)
    return subseed, pub


def entry_state(http: Http) -> tuple[str, str, dict | None]:
    """Whether an arena takes outside fighters, read from GET /api/v1/join the way
    the site's BUILD A BOT page reads it (apps/web/combat/logic.js entryStatus):
    OPEN, FULL (every place taken), CLOSED (only join_disabled or join_closed
    say so) or UNKNOWN (anything else: the API down, a proxy error, no answer).
    Returns (state, a printable detail, the join document when it answered)."""
    try:
        info = http.get("/api/v1/join")
    except HttpError as e:
        if e.code in CLOSED_CODES:
            return "CLOSED", e.code, None
        return "UNKNOWN", printable(e.code or f"HTTP {e.status}"), None
    except (OSError, ValueError) as e:
        return "UNKNOWN", f"no answer: {printable(e)}", None
    if not isinstance(info, dict) or info.get("enabled") is not True:
        return "UNKNOWN", "the answer does not say entry is enabled", None
    lim = info.get("limits") if isinstance(info.get("limits"), dict) else {}
    num = lambda v: v if isinstance(v, (int, float)) and not isinstance(v, bool) else None   # noqa: E731
    n, cap = num(info.get("outside_fighters")), num(lim.get("max_outside_fighters"))
    places = f"{'?' if n is None else n} of {'?' if cap is None else cap}"
    return ("FULL" if n is not None and cap is not None and n >= cap else "OPEN"), places, info


def register(http: Http, info: dict, name: str, subseed: bytes, pub: bytes, log=print, wait_s: float = 120) -> dict:
    """Idempotent: registers once, then waits until the arena has issued the fighter.
    An error answer to the registration itself raises Refused; one to a read
    around it (the status, the tick it signs), HttpError. A key the arena has
    registered under another name raises Refused one_per_key, as the arena
    would answer, before anything is signed or sent: a key registers one fighter."""
    try:
        st = http.get(f"/api/v1/join/status?owner={pub.hex()}")
    except HttpError as e:
        if e.status != 404:
            raise
        tick = int(http.get(f"/api/v1/chain/state")["tick"])
        digest = register_digest(bytes.fromhex(info["network_id"]), bytes.fromhex(info["contract_id"]), pub, name, tick)
        sig = schnorrq.sign(subseed, pub, digest)
        try:
            st = http.post("/api/v1/join/register", {"name": name, "public_key": pub.hex(), "tick": tick,
                                                     "signature": sig.hex()})
        except HttpError as e:
            raise Refused(e.status, e.doc) from None
        log(f"registration sent: {printable(st.get('status'))}")
    else:
        other = st["name"]
        if not isinstance(other, str) or other.lower() != name.lower():    # names are compared as the arena does
            raise Refused(409, {"error": {"code": "one_per_key", "message": f"this key already registered {other}"}})
    deadline = time.monotonic() + wait_s
    while st["status"] == "new" and time.monotonic() < deadline:
        time.sleep(2)
        st = http.get(f"/api/v1/join/status?owner={pub.hex()}")
    if st["status"] != "active":
        raise SystemExit(f"qdojo: registration {printable(st['status'])}: "
                         f"{printable(st.get('detail') or 'not issued yet, retry later')}")
    return st


# What a builder can do about each refusal of a registration: error codes of
# POST /api/v1/join/register only (a chain read's rate_limited is the read
# throttle, not the day's registrations; join says to run the command again).
# one_per_key comes from register() itself when the key's registration has
# another name, and from the arena when two joins with one key race.
REFUSAL_NEXT = {
    "join_closed": "entry is closed; the site's BUILD A BOT page shows when it opens",
    "join_disabled": "entry is closed; the site's BUILD A BOT page shows when it opens",
    "arena_full": "every outside-fighter place is taken; try again when the site shows a free place",
    "rate_limited": "the registration limit for today is reached; try again tomorrow",
    "name_taken": "choose another --name",
    "bad_name": "choose another --name: 3-16 letters, digits, '-' or '_', starting with a letter or digit",
    "name_reserved": f"names starting with '{OPERATOR_TEST_PREFIX}' are the operator's; choose another --name",
    "one_per_key": "a key registers one fighter, for good: run join with that fighter's --name",
    "stale": "your clock or the arena's moved on; run the same command again",
}


def cmd_join(a):
    from ..combat import evaluate as E
    from .bot import Bot, Budget, planner_chooser, policy_chooser
    from .rules import RulesetError, by_digest, candidate_1
    import shlex
    key = Path(a.key) if a.key else _home() / "join" / f"{a.name}.seed"
    if a.show_key:                             # contacts no arena (the operator's allow-list, docs/beta.md §5)
        print(f"key {key} -> owner {load_or_make_key(key)[1].hex()}")
        return
    http = Http(a.arena)
    practise = ("practise and benchmark locally (`qdojo combat train`, `qdojo combat evaluate --planner ...`); "
                "the site's BUILD A BOT page shows when entry opens")
    state, detail, info = entry_state(http)
    if state == "CLOSED":
        raise SystemExit(f"qdojo: entry is closed on {a.arena} ({detail}); nothing was created.\nNext: {practise}.")
    if state == "UNKNOWN":
        raise SystemExit(f"qdojo: {a.arena} did not say whether entry is open ({detail}); nothing was created.\n"
                         f"Next: try again later, or check with `qdojo combat doctor --arena {a.arena}`.")
    if state == "FULL" and not key.exists():   # a fighter registered before still runs; a new one cannot enter
        raise SystemExit(f"qdojo: every outside-fighter place on {a.arena} is taken ({detail}); "
                         "nothing was created.\nNext: practise and benchmark locally; the site's BUILD A BOT "
                         "page shows when a place is free.")
    created = not key.exists()
    subseed, pub = load_or_make_key(key)
    print(f"key {key} -> owner {pub.hex()} (simulated arena only: fake QU)")

    def unfinished(why, issued=False):
        if issued:                                 # what is left is REGISTER_FIGHTER on chain
            return SystemExit(f"qdojo: {a.name} is registered on {a.arena}, but registering it on chain did not "
                              f"complete ({why}).\nNext: run the same command again; it reuses {key}, finds the "
                              "registration and finishes it.")
        return SystemExit(f"qdojo: the registration on {a.arena} did not complete ({why}).\nNext: run the same "
                          f"command again; it reuses {key} and finds the registration if the arena received it.")
    try:
        reg = register(http, info, a.name, subseed, pub)
        fid = bytes.fromhex(reg["fighter_id"])
    except Refused as e:
        if e.code not in REFUSAL_NEXT:            # api_down, a proxy error: it may or may not have arrived
            raise unfinished(e.why()) from None
        if e.code in CLOSED_CODES and created:    # the public proxy refuses writes: as closed as a refused GET
            key.unlink(missing_ok=True)
            kept = "nothing was created (the new key is removed again)"
        else:
            kept = f"nothing was registered, and the key stays in {key} for the next attempt"
        raise SystemExit(f"qdojo: {a.arena} refused the registration: {e.why()}; {kept}.\n"
                         f"Next: {REFUSAL_NEXT[e.code]}.") from None
    except HttpError as e:                        # a read around it: the API restarting, the read throttle
        raise unfinished(e.why()) from None
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise unfinished(printable(e)) from None
    # The name as the arena spells it. The same name in another case is this key's own fighter (register()),
    # so it runs from that fighter's state directory: a second one has no plan journal for the rounds the
    # fighter committed (they forfeit) and a budget counted from zero. Only a case variant of --name is
    # taken from the answer, so an arena can never choose the path.
    name = reg.get("name")
    if not (isinstance(name, str) and NAME_RE.fullmatch(name) and name.lower() == a.name.lower()):
        name = a.name
    print(f"fighter {name} = {fid.hex()}")
    rules = candidate_1()
    if info.get("ruleset_digest") and info["ruleset_digest"] != rules.digest.hex():
        try:                                   # any packaged ruleset: the demo arena runs candidate 2
            rules = by_digest(info["ruleset_digest"])
        except RulesetError:
            raise SystemExit("qdojo: the arena runs a ruleset this checkout does not know; update qdojo") from None
    print(f"arena ruleset {rules.semantic_version} {rules.digest.hex()}")
    state = Path(a.state) if a.state else _home() / "join" / name
    say = lambda m: print(printable(m, None), flush=True)       # noqa: E731  (arena text, escaped)
    try:
        client = RemoteClient(http, info, subseed, pub, fid, state, log=say)
        client.refresh()
        if client.state.get("fighter") is None:
            r = client.send(Op.REGISTER_FIGHTER, fighter_id=fid, registry_version=1)
            print("REGISTER_FIGHTER sent")
            for _ in range(60):
                time.sleep(2)
                client.refresh()
                st = client.poll(r)
                if client.state.get("fighter") is not None:
                    break
                if st == "dropped":
                    r = client.send(Op.REGISTER_FIGHTER, fighter_id=fid, registry_version=1)
    except HttpError as e:                        # the API restarting, the read throttle: a rerun resends it
        raise unfinished(e.why(), issued=True) from None
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise unfinished(printable(e), issued=True) from None
    if client.state.get("fighter") is None:
        raise SystemExit("qdojo: the fighter did not register; run join again")
    say(f"registered on chain; balance {client.state.get('balance')} fake QU")
    if a.register_only:
        return
    if a.planner:
        choose = planner_chooser(shlex.split(a.planner), a.budget_ms)
    else:
        choose = policy_chooser(rules, E.policy_by_name(a.npc or "mixed-v1", rules), os.urandom(32))
    budget = Budget(ruleset_digest=rules.digest.hex(), max_stake=int(info["tiers"].get("1", 1000)) * 5,
                    max_total_escrow=int(info["tiers"].get("1", 1000)) * 20)
    if a.budget:
        budget = Budget(**{**budget.__dict__, **json.loads(Path(a.budget).read_text())})
    bot = Bot(client, rules, fid, pub, pub, choose, budget, state, log=say)
    bot.play_cups, bot.accept_duels, bot.ranked = a.cups, a.duels, not a.no_ranked
    last, stop_at = None, (time.monotonic() + a.seconds) if a.seconds else None
    while stop_at is None or time.monotonic() < stop_at:
        try:
            client.refresh()
            msg = bot.step()
        except (HttpError, OSError) as exc:
            msg = f"arena unreachable: {exc}"
        if msg != last:
            say(f"tick {client.state.get('tick')}: {msg}")
            last = msg
        time.sleep(a.poll)


def cmd_registrations(a):
    """The operator's view of the join inbox, on the arena host (docs/operations.md §8)."""
    path = Path(a.inbox) if a.inbox else _home() / "arena" / "inbox.sqlite"
    if not path.exists():
        raise SystemExit(f"qdojo: no join inbox at {path}")
    db = inbox(path)
    if a.action == "revoke":
        if not a.name:
            raise SystemExit("qdojo: revoke needs the fighter's NAME")
        row = revoke(db, a.name, a.reason)
        held = db.execute("SELECT COUNT(*) FROM registrations WHERE status IN ('new','active')").fetchone()[0]
        cap = (recorded_limits(db) or Limits()).max_outside_fighters
        print(f"{row['name']} revoked ({row['detail']}): its key can no longer send, and {held} of {cap} "
              "outside-fighter places are now taken. The fighter stays in the record, labelled outside.")
    elif a.action == "forget-addresses":
        print(f"cleared {forget_addresses(db, 0)} stored client address(es)")
    else:
        rows = [dict(r) for r in db.execute("SELECT name, owner, status, detail, received, tick, ip "
                                            "FROM registrations ORDER BY id")]
        if a.json:
            print(json.dumps(rows, indent=1))
            return
        for r in rows:
            print(f"{r['name']:<16} {r['status']:<8} {time.strftime('%Y-%m-%d %H:%M', time.gmtime(r['received']))} "
                  f"UTC  owner {r['owner'][:16]}  address {r['ip'] or '-'}" + (f"  ({r['detail']})" if r["detail"] else ""))


def add_parser(s):
    d = s.add_parser("join", help="enter the public arena (a devnet: simulated chain, devnet QU) with your own bot")
    d.add_argument("--arena", default="https://qdojo.jonsggi.com", help="arena site or API base URL")
    d.add_argument("--name", required=True, help="fighter name: 3-16 letters, digits, '-' or '_' "
                                                 f"(names starting with '{OPERATOR_TEST_PREFIX}' are the operator's)")
    d.add_argument("--key", help="seed file for the simulated arena (default ~/.qdojo/combat/join/NAME.seed, "
                                 "created 0600); never your real Qubic seed")
    d.add_argument("--show-key", action="store_true",
                   help="print the key's owner (public key), creating the key if needed, and stop; contacts no arena")
    d.add_argument("--planner", help="your planner command, e.g. 'python3 my_bot.py'")
    d.add_argument("--npc", help="without --planner, a built-in policy fights for you (default mixed-v1)")
    d.add_argument("--budget-ms", type=int, default=1500)
    d.add_argument("--budget", help="JSON file overriding the bot's spending budget")
    d.add_argument("--state", help="bot state directory (plan journal, budget, nonce; default "
                                   "~/.qdojo/combat/join/NAME, the name as the arena spells it)")
    d.add_argument("--cups", action="store_true", help="enter open cups")
    d.add_argument("--duels", action="store_true", help="accept duel challenges")
    d.add_argument("--no-ranked", action="store_true", help="stay out of the ranked queue")
    d.add_argument("--register-only", action="store_true", help="register and stop; do not run the bot")
    d.add_argument("--seconds", type=float, help="stop after this long (default: run until interrupted)")
    d.add_argument("--poll", type=float, default=1.0, help="seconds between steps")
    d.set_defaults(fn=cmd_join)
    r = s.add_parser("registrations", help="operator: the join inbox's outside-builder registrations "
                                           "(list, revoke NAME, forget-addresses)")
    r.add_argument("action", choices=("list", "revoke", "forget-addresses"))
    r.add_argument("name", nargs="?", help="revoke: the fighter's name")
    r.add_argument("--inbox", help="the join inbox (default ~/.qdojo/combat/arena/inbox.sqlite)")
    r.add_argument("--reason", default="revoked by the operator", help="revoke: recorded and shown to its builder")
    r.add_argument("--json", action="store_true")
    r.set_defaults(fn=cmd_registrations)
