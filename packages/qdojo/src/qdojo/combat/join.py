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
from dataclasses import asdict, dataclass, fields
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
# What an outside key may send. Never the admin opcodes; no SET_OPERATOR (the
# key that registered is the key that plays); no ADVANCE (the house keeper runs it).
PLAYER_OPS = frozenset({Op.REGISTER_FIGHTER, Op.QUEUE_ENTER, Op.QUEUE_CANCEL, Op.DUEL_OFFER, Op.DUEL_ACCEPT,
                        Op.DUEL_CANCEL, Op.COMMIT, Op.REVEAL, Op.WITHDRAW, Op.CUP_REGISTER, Op.CUP_WITHDRAW,
                        Op.CUP_CHECK_IN})
DEFAULT_PUBLIC_KEY = ids.public_key_from_identity(ids.PUBLIC_DEFAULT_IDENTITY)


@dataclass
class Limits:
    """Quotas. Every number is a decision for the operator (docs/operations.md §8)."""
    max_outside_fighters: int = 8          # all time, across all builders
    registrations_per_day: int = 10        # global
    registrations_per_ip_day: int = 2
    grant_qu: int = 100_000                # fake QU minted to a new outside owner, once
    max_amount: int = 20_000               # largest attachment on one transaction
    tx_burst: int = 20                     # token bucket per identity
    tx_per_second: float = 1.0
    tx_per_day: int = 20_000               # per identity
    reads_per_second: float = 20.0         # chain reads, per client IP
    max_pending: int = 400                 # queued transactions, all identities together
    tick_behind: int = 30                  # a transaction's tick field must be within
    tick_ahead: int = 60                   # [tick - behind, tick + ahead] of the arena

    @classmethod
    def load(cls, path: Path) -> "Limits":
        raw = json.loads(Path(path).read_text())
        known = {f.name for f in fields(cls)}
        unknown = set(raw) - known
        if unknown:
            raise SystemExit(f"qdojo: unknown join limits: {sorted(unknown)}")
        return cls(**raw)


class JoinError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def fighter_id_for(name: str) -> bytes:
    """The simulated NFT's ID, as AssetRegistry.id_for derives it for the arena's issuer."""
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
            active = self.db.execute("SELECT COUNT(*) FROM registrations WHERE status IN ('new','active')").fetchone()[0]
            return 200, {"schema": "qdojo.combat.api.join.v1", "enabled": True, "chain": "simulated",
                         "currency": "fake QU", "network_id": fl.m.network_id.hex() if fl else None,
                         "contract_id": fl.m.contract_id.hex() if fl else None, "input_type": INPUT_TYPE,
                         "tx_bytes": TX_LEN, "register_tag": REGISTER_TAG.decode().rstrip("\0"),
                         "tiers": {str(k): v for k, v in fl.m.tiers.items()} if fl else {},
                         "ruleset_digest": fl.m.ruleset.digest.hex() if fl else None,
                         "timing_profiles": {str(k): list(v) for k, v in fl.m.timing.items()} if fl else {},
                         "outside_fighters": active, "limits": asdict(self.limits),
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
            if not self.read_bucket.take(ip):
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
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise JoinError(400, "bad_name", "a name is 3-16 letters, digits, '-' or '_', starting with a letter or digit")
        if not (isinstance(pk, str) and re.fullmatch(r"[0-9a-f]{64}", pk) and isinstance(sig, str)
                and re.fullmatch(r"[0-9a-f]{128}", sig) and isinstance(tick, int)):
            raise JoinError(400, "bad_body", "public_key (64 hex), signature (128 hex) and tick (int) are required")
        pub = bytes.fromhex(pk)
        if pub == DEFAULT_PUBLIC_KEY:
            raise JoinError(400, "bad_key", "that key is derived from the public all-'a' seed")
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
                raise JoinError(409, "one_per_key", "this key already registered a fighter")
            if name.lower() in self._names():
                raise JoinError(409, "name_taken", "that name is taken")
            n = self.db.execute("SELECT COUNT(*) FROM registrations WHERE status IN ('new','active')").fetchone()[0]
            if n >= lim.max_outside_fighters:
                raise JoinError(403, "arena_full", "the arena has no room for more outside fighters right now")
            since = time.time() - 86400
            day = self.db.execute("SELECT COUNT(*) FROM registrations WHERE received > ?", (since,)).fetchone()[0]
            by_ip = self.db.execute("SELECT COUNT(*) FROM registrations WHERE received > ? AND ip = ?",
                                    (since, ip)).fetchone()[0]
            if day >= lim.registrations_per_day or by_ip >= lim.registrations_per_ip_day:
                raise JoinError(429, "rate_limited", "registration limit reached; try again tomorrow")
            fid = fighter_id_for(name).hex()
            self.db.execute("INSERT INTO registrations(name, owner, fighter_id, ip, received, status) "
                            "VALUES(?,?,?,?,?, 'new')", (name, pk, fid, ip, time.time()))
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
        self.limits = limits or Limits()
        # In-flight SimChain transactions do not survive a restart; tell their senders to resend.
        self.db.execute("UPDATE txs SET status = 'dropped', result = ? WHERE status = 'pending'",
                        (json.dumps({"code": None, "detail": "arena restarted before inclusion"}),))

    def drain(self, arena):
        """Before the tick's transactions run: new registrations, then new transactions."""
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

        def reject(why):
            self.db.execute("UPDATE registrations SET status = 'rejected', detail = ?, tick = ? WHERE id = ?",
                            (why, arena.w.tick, row["id"]))
            arena.log(f"tick {arena.w.tick}: outside registration {name!r} rejected: {why}")
        if name.lower() in taken:
            return reject("name taken")
        if len(outside) >= self.limits.max_outside_fighters:
            return reject("arena full")
        fid = arena.registry.id_for(OUTSIDE_LABEL + name)
        if fid.hex() != row["fighter_id"] or fid in arena.registry.assets:
            return reject("asset ID mismatch or already issued")
        arena.registry.issue(OUTSIDE_LABEL + name, owner)
        arena.w.mint(owner, self.limits.grant_qu)
        arena.w.send(roles()["admin"], Op.ADMIN_REGISTER_ASSET, fighter_id=fid, registry_version=1, house_npc=0)
        entry = {"label": name, "origin": "outside", "driver": "builder", "fighter_id": fid.hex(),
                 "owner": owner.hex(), "tick": arena.w.tick}
        tmp = arena.dir / (OUTSIDE_FILE + ".tmp")
        tmp.write_text(json.dumps(outside + [entry], indent=1))
        os.replace(tmp, arena.dir / OUTSIDE_FILE)
        arena.labels[fid] = entry
        arena.save()
        self.db.execute("UPDATE registrations SET status = 'active', tick = ? WHERE id = ?", (arena.w.tick, row["id"]))
        arena.log(f"tick {arena.w.tick}: outside fighter {name} issued to {owner.hex()[:12]}")


# ---- builder side: a client over HTTP ----------------------------------------------------

class HttpError(Exception):
    def __init__(self, status: int, doc: dict | None):
        err = (doc or {}).get("error") or {}
        super().__init__(f"HTTP {status}: {err.get('code', '')} {err.get('message', '')}".strip())
        self.status, self.doc, self.code = status, doc, err.get("code")


class Http:
    def __init__(self, base: str, timeout: float = 10.0):
        self.base, self.timeout = base.rstrip("/"), timeout

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", "User-Agent": "qdojo-join"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                doc = json.loads(e.read())
            except ValueError:
                doc = None
            raise HttpError(e.code, doc) from None

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
            self.log(f"send {op.name} refused: {exc}")
            return RemoteReceipt(None, self.tick(), str(exc))        # polls as dropped: the bot may resend

    def poll(self, receipt: RemoteReceipt):
        from .contract import CallResult
        if receipt.tx_hash is None:
            return "dropped"
        try:
            r = self.http.get(f"/api/v1/tx/{receipt.tx_hash}")
        except (HttpError, OSError):
            return None
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


def register(http: Http, info: dict, name: str, subseed: bytes, pub: bytes, log=print, wait_s: float = 120) -> dict:
    """Idempotent: registers once, then waits until the arena has issued the fighter."""
    try:
        st = http.get(f"/api/v1/join/status?owner={pub.hex()}")
    except HttpError as e:
        if e.status != 404:
            raise
        tick = int(http.get(f"/api/v1/chain/state")["tick"])
        digest = register_digest(bytes.fromhex(info["network_id"]), bytes.fromhex(info["contract_id"]), pub, name, tick)
        sig = schnorrq.sign(subseed, pub, digest)
        st = http.post("/api/v1/join/register", {"name": name, "public_key": pub.hex(), "tick": tick,
                                                 "signature": sig.hex()})
        log(f"registration sent: {st.get('status')}")
    deadline = time.monotonic() + wait_s
    while st["status"] == "new" and time.monotonic() < deadline:
        time.sleep(2)
        st = http.get(f"/api/v1/join/status?owner={pub.hex()}")
    if st["status"] != "active":
        raise SystemExit(f"qdojo: registration {st['status']}: {st.get('detail') or 'not issued yet, retry later'}")
    return st


def cmd_join(a):
    from ..combat import evaluate as E
    from .bot import Bot, Budget, planner_chooser, policy_chooser
    from .rules import RulesetError, by_digest, candidate_1
    import shlex
    http = Http(a.arena)
    try:
        info = http.get("/api/v1/join")
    except HttpError as e:
        raise SystemExit(f"qdojo: this arena does not accept outside fighters ({e})") from None
    key = Path(a.key) if a.key else _home() / "join" / f"{a.name}.seed"
    subseed, pub = load_or_make_key(key)
    print(f"key {key} -> owner {pub.hex()} (simulated arena only: fake QU)")
    reg = register(http, info, a.name, subseed, pub)
    fid = bytes.fromhex(reg["fighter_id"])
    print(f"fighter {a.name} = {fid.hex()}")
    rules = candidate_1()
    if info.get("ruleset_digest") and info["ruleset_digest"] != rules.digest.hex():
        try:                                   # any packaged ruleset: the demo arena runs candidate 2
            rules = by_digest(info["ruleset_digest"])
        except RulesetError:
            raise SystemExit("qdojo: the arena runs a ruleset this checkout does not know; update qdojo") from None
    state = Path(a.state) if a.state else _home() / "join" / a.name
    client = RemoteClient(http, info, subseed, pub, fid, state)
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
        if client.state.get("fighter") is None:
            raise SystemExit("qdojo: the fighter did not register; run join again")
    print(f"registered on chain; balance {client.state.get('balance')} fake QU")
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
    bot = Bot(client, rules, fid, pub, pub, choose, budget, state, log=print)
    bot.play_cups, bot.accept_duels, bot.ranked = a.cups, a.duels, not a.no_ranked
    last, stop_at = None, (time.monotonic() + a.seconds) if a.seconds else None
    while stop_at is None or time.monotonic() < stop_at:
        try:
            client.refresh()
            msg = bot.step()
        except (HttpError, OSError) as exc:
            msg = f"arena unreachable: {exc}"
        if msg != last:
            print(f"tick {client.state.get('tick')}: {msg}", flush=True)
            last = msg
        time.sleep(a.poll)


def add_parser(s):
    d = s.add_parser("join", help="enter the public demo arena (simulated chain, fake QU) with your own bot")
    d.add_argument("--arena", default="https://qdojo.jonsggi.com", help="arena site or API base URL")
    d.add_argument("--name", required=True, help="fighter name: 3-16 letters, digits, '-' or '_'")
    d.add_argument("--key", help="seed file for the simulated arena (default ~/.qdojo/combat/join/NAME.seed, "
                                 "created 0600); never your real Qubic seed")
    d.add_argument("--planner", help="your planner command, e.g. 'python3 my_bot.py'")
    d.add_argument("--npc", help="without --planner, a built-in policy fights for you (default mixed-v1)")
    d.add_argument("--budget-ms", type=int, default=1500)
    d.add_argument("--budget", help="JSON file overriding the bot's spending budget")
    d.add_argument("--state", help="bot state directory (plan journal, budget, nonce)")
    d.add_argument("--cups", action="store_true", help="enter open cups")
    d.add_argument("--duels", action="store_true", help="accept duel challenges")
    d.add_argument("--no-ranked", action="store_true", help="stay out of the ranked queue")
    d.add_argument("--register-only", action="store_true", help="register and stop; do not run the bot")
    d.add_argument("--seconds", type=float, help="stop after this long (default: run until interrupted)")
    d.add_argument("--poll", type=float, default=1.0, help="seconds between steps")
    d.set_defaults(fn=cmd_join)
