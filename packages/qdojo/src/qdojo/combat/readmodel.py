"""A SQLite read model of the arena: every fight, fighter, rating change,
season, cup, duel and ownership record, for the read API (docs/api.md §3.2).

It is an index, never an authority. Its only input is the devnet's input
journal (store.py): a `Replica` replays the journal into its own copy of the
reference contract, exactly as a restart of the arena would, and `sync`
copies public state from that copy into SQLite. Names, drivers, origin and
simulated NFT history come from the public export's index.json (the arena's
deployment block), which is public already.

- Rebuildable: `rebuild` deletes nothing in place; it builds a new file from
  the whole journal and swaps it in atomically.
- Incremental: `Follower` tails the journal (only complete lines), applies new
  records and re-syncs what can still change: new and unfinished fights,
  unsettled contests, open cups, every fighter and season. Every write is an
  upsert of a pure function of the replica's state, so an incremental database
  and a rebuilt one hold the same rows (tests/combat/test_readmodel.py).
- Restartable: the follower pickles its replica now and then (a private,
  local file next to the database), so a restart resumes in seconds instead of
  replaying the whole journal. A snapshot from different code is ignored.

Stored documents carry no `generated_tick`: the API adds the database's tick
when it serves them, so a document never depends on when it was indexed.
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import sqlite3
import threading
import time
import zlib
from pathlib import Path

from . import codec, export
from .contract import CombatContract, Manifest
from .rating import PLACEMENT_FIGHTS, belt

SCHEMA_VERSION = "qdojo.combat.readmodel.v1"
JOURNAL = "devnet.journal"
MARKER = "devnet.json"
SNAPSHOT_EVERY_S = 900.0
READ_CHUNK = 8 << 20

DDL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fighters(
  fighter_id TEXT PRIMARY KEY, name TEXT, origin TEXT, driver TEXT, house_npc INTEGER NOT NULL,
  owner TEXT NOT NULL, operator TEXT NOT NULL, auth_version INTEGER NOT NULL, lock TEXT NOT NULL,
  lifetime_rating INTEGER NOT NULL, placement INTEGER NOT NULL, provisional INTEGER NOT NULL, belt TEXT,
  record TEXT NOT NULL, faults TEXT NOT NULL, season_ratings TEXT NOT NULL, cooldown_until INTEGER NOT NULL,
  suspended_epoch INTEGER NOT NULL, asset TEXT);
CREATE TABLE IF NOT EXISTS fights(
  fight_id INTEGER PRIMARY KEY, contest_id INTEGER NOT NULL, mode TEXT NOT NULL, a TEXT NOT NULL, b TEXT NOT NULL,
  phase TEXT NOT NULL, final INTEGER NOT NULL, start_tick INTEGER NOT NULL, end_tick INTEGER,
  kind TEXT, winner TEXT, result TEXT, rounds INTEGER NOT NULL, summary BLOB NOT NULL, replay BLOB);
CREATE INDEX IF NOT EXISTS fights_by_mode ON fights(mode, fight_id);
CREATE INDEX IF NOT EXISTS fights_open ON fights(final) WHERE final = 0;
CREATE TABLE IF NOT EXISTS fight_sides(
  fighter_id TEXT NOT NULL, fight_id INTEGER NOT NULL, slot TEXT NOT NULL, opponent_id TEXT NOT NULL,
  mode TEXT NOT NULL, outcome TEXT, tick INTEGER, PRIMARY KEY(fighter_id, fight_id)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS sides_by_mode ON fight_sides(fighter_id, mode, fight_id);
CREATE TABLE IF NOT EXISTS contests(
  contest_id INTEGER PRIMARY KEY, mode TEXT NOT NULL, format TEXT NOT NULL, a TEXT NOT NULL, b TEXT NOT NULL,
  stake INTEGER NOT NULL, status TEXT NOT NULL, season INTEGER NOT NULL, cup_id INTEGER NOT NULL,
  pairing_id INTEGER NOT NULL, start_tick INTEGER NOT NULL, end_tick INTEGER, doc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS contests_by_mode ON contests(mode, contest_id);
CREATE TABLE IF NOT EXISTS ratings(
  fighter_id TEXT NOT NULL, contest_id INTEGER NOT NULL, fight_id INTEGER NOT NULL, tick INTEGER NOT NULL,
  season INTEGER NOT NULL, kind TEXT NOT NULL, lifetime_before INTEGER NOT NULL, lifetime_after INTEGER NOT NULL,
  season_before INTEGER NOT NULL, season_after INTEGER NOT NULL, PRIMARY KEY(fighter_id, contest_id)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS cups(
  cup_id INTEGER PRIMARY KEY, status TEXT NOT NULL, created_tick INTEGER NOT NULL, champion TEXT, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS seasons(
  season INTEGER PRIMARY KEY, status TEXT NOT NULL, final INTEGER NOT NULL, champion TEXT, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ownership(
  fighter_id TEXT NOT NULL, seq INTEGER NOT NULL, tick INTEGER NOT NULL, from_owner TEXT, to_owner TEXT NOT NULL,
  PRIMARY KEY(fighter_id, seq)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ownership_by_owner ON ownership(to_owner);
CREATE TABLE IF NOT EXISTS sales(
  seq INTEGER PRIMARY KEY, tick INTEGER NOT NULL, fighter_id TEXT NOT NULL, seller TEXT NOT NULL,
  buyer TEXT NOT NULL, price INTEGER NOT NULL, fee INTEGER NOT NULL, doc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sales_by_fighter ON sales(fighter_id, seq);
"""
TABLES = ("fighters", "fights", "fight_sides", "contests", "ratings", "cups", "seasons", "ownership", "sales")
FINAL_CUP = ("COMPLETE", "CANCELLED", "ABORTED")


class ReadModelError(RuntimeError):
    pass


def pack(doc) -> bytes:
    return zlib.compress(json.dumps(doc, separators=(",", ":")).encode(), 6)


def unpack(blob):
    return None if blob is None else json.loads(zlib.decompress(blob))


def _strip(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("generated_tick", None)
    return doc


def outcome_of(result: dict | None, slot: str) -> str | None:
    """W/D/L for a fought result, FW/FL for a forfeit, N for a double fault or void, None while live."""
    if not result:
        return None
    kind, winner = result.get("kind"), result.get("winner")
    if kind == "COMBAT":
        return "D" if winner is None else "W" if winner == slot else "L"
    if kind == "FORFEIT":
        return "FW" if winner == slot else "FL"
    return "N"


def code_version() -> str:
    """Digest of the combat package's code and rulesets: a snapshot is only
    reused by the exact code that wrote it."""
    h = hashlib.sha256()
    here = Path(__file__).parent
    for p in sorted(list(here.glob("*.py")) + list((here / "rulesets").glob("*"))):
        if p.is_file():
            h.update(p.name.encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


# ---- the replica: the journal replayed into a private contract --------------

class Replica:
    """World.replay, one record at a time and without re-journalling. Only
    confirmed inputs are applied; nothing here can send a transaction."""

    def __init__(self, manifest: Manifest):
        self.m = manifest
        self.contract: CombatContract | None = None
        self.tick = 0
        self.balances: dict[bytes, int] = {}
        self.owners: dict[bytes, bytes | None] = {}
        self.failing: set[bytes] = set()
        self.records = 0

    def _transfer(self, to: bytes, amount: int) -> bool:
        if to in self.failing:
            return False
        self.balances[to] = self.balances.get(to, 0) + amount
        return True

    def apply(self, rec: dict):
        k = rec["k"]
        if k == "start":
            if self.contract is not None:
                raise ReadModelError("a second start record in one journal")
            self.tick = rec["t"]
            self.contract = CombatContract(self.m, self.owners.get, self._transfer, self.tick)
        elif self.contract is None:
            raise ReadModelError("journal does not begin with a start record")
        elif k == "mint":
            who = bytes.fromhex(rec["who"])
            self.balances[who] = self.balances.get(who, 0) + rec["amount"]
        elif k == "owner":
            self.owners[bytes.fromhex(rec["id"])] = bytes.fromhex(rec["owner"]) if rec["owner"] else None
        elif k == "fail":
            (self.failing.add if rec["on"] else self.failing.discard)(bytes.fromhex(rec["who"]))
        elif k == "call":
            who = bytes.fromhex(rec["who"])
            self.balances[who] = self.balances.get(who, 0) - rec["amount"]
            self.contract.call(who, bytes.fromhex(rec["frame"]), rec["amount"], self.tick)
        elif k == "end":
            self.contract.end_tick(self.tick)
            self.tick += 1
            self.contract.begin_tick(self.tick)
        elif k == "begin":
            self.tick = rec["t"]
            self.contract.begin_tick(self.tick)
        elif k == "digest":
            # The arena's checkpoint before a state snapshot: the replica must agree.
            c = self.contract
            if c.event_seq != rec["event_seq"] or c.event_digest.hex() != rec["event_digest"]:
                raise ReadModelError(f"replica diverged from the arena at the checkpoint of tick {rec['t']}")
        elif k == "xfer":
            # A market payment between external wallets (not contract state).
            frm, to = bytes.fromhex(rec["from"]), bytes.fromhex(rec["to"])
            self.balances[frm] = self.balances.get(frm, 0) - rec["amount"]
            self.balances[to] = self.balances.get(to, 0) + rec["amount"]
        else:
            raise ReadModelError(f"unknown journal record {k!r}")
        self.records += 1


def manifest_for(devnet_dir: Path) -> Manifest:
    """The manifest the devnet replays with: its recorded values (devnet.recorded),
    never the current profile defaults, which may have changed since it was created."""
    from .devnet import SCHEMA, recorded
    meta = json.loads((Path(devnet_dir) / MARKER).read_text())
    if meta.get("schema") != SCHEMA:
        raise ReadModelError(f"{devnet_dir} is not a combat devnet")
    m = recorded(meta)[2]
    if meta.get("ruleset_digest") != m.ruleset.digest.hex():
        raise ReadModelError(f"{devnet_dir} was made for another ruleset")
    return m


# ---- public metadata from the export ---------------------------------------

def load_deployment(export_dir: Path | None) -> dict:
    """The deployment block of the export's index.json, or {} without one.
    index.json cuts each fighter's ownership history to its last entries
    ("history_truncated"); the full history then comes from the fighter file."""
    if export_dir is None:
        return {}
    try:
        dep = json.loads((Path(export_dir) / "index.json").read_text()).get("deployment") or {}
    except (OSError, ValueError):
        return {}
    for hexid, m in (dep.get("fighters") or {}).items():
        asset = m.get("asset") or {}
        if asset.get("history_truncated"):
            try:
                full = json.loads((Path(export_dir) / "fighters" / f"{hexid}.json").read_text()).get("asset")
            except (OSError, ValueError):
                full = None
            if full and len(full.get("history") or []) >= len(asset.get("history") or []):
                m["asset"] = {**asset, "history": full["history"], "history_truncated": False}
    return dep


def origin_of(meta: dict, house_npc: bool) -> str:
    """house: operator-run (demo bots, NPCs); outside: registered and run by an outside builder."""
    if meta.get("origin") in ("house", "outside"):
        return meta["origin"]
    return "house" if house_npc or meta else "unknown"


# ---- sync: contract state -> rows -------------------------------------------

def connect(path: Path, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5, check_same_thread=False)
    else:
        conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(DDL)
        row = conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        if row is None:
            conn.execute("INSERT INTO meta VALUES('schema', ?)", (SCHEMA_VERSION,))
            conn.commit()
        elif row[0] != SCHEMA_VERSION:
            raise ReadModelError(f"{path} holds {row[0]}, not {SCHEMA_VERSION}; rebuild it")
    conn.row_factory = sqlite3.Row
    return conn


def get_meta(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return default if row is None else json.loads(row[0])


def set_meta(conn, key: str, value):
    conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, json.dumps(value)))


class Syncer:
    """Copies what can still change from a contract into SQLite. Remembers
    which fights, contests and cups are still open between calls."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        q = lambda sql: {r[0] for r in conn.execute(sql)}                       # noqa: E731
        self.open_fights = q("SELECT fight_id FROM fights WHERE final = 0")
        self.open_contests = q("SELECT contest_id FROM contests WHERE status != 'DONE'")
        self.open_cups = q("SELECT cup_id FROM cups WHERE status NOT IN ('COMPLETE','CANCELLED','ABORTED')")
        mx = lambda sql: (conn.execute(sql).fetchone()[0] or 0)                  # noqa: E731
        self.max_fight = mx("SELECT MAX(fight_id) FROM fights")
        self.max_contest = mx("SELECT MAX(contest_id) FROM contests")
        self.max_cup = mx("SELECT MAX(cup_id) FROM cups")

    def sync(self, c: CombatContract, deployment: dict, state: dict, rule=None, sales: list | None = None,
             economics: dict | None = None):
        """One transaction: the database afterwards describes contract `c` at its tick.
        `rule` is the season qualification (the arena profile's), `sales` the
        simulated market's sales (the arena's market.json), `economics` the
        export's economics.json body."""
        conn = self.conn
        meta = deployment.get("fighters") or {}
        with conn:
            fights = sorted(self.open_fights | {f for f in c.fights if f > self.max_fight})
            for fid in fights:
                self._fight(c, fid)
            contests = sorted(self.open_contests | {x for x in c.contests if x > self.max_contest})
            for cid in contests:
                self._contest(c, cid)
            cups = sorted(self.open_cups | {k for k in c.cups if k > self.max_cup})
            if cups:
                by_pairing = export.pairing_fights(c)
                for kid in cups:
                    self._cup(c, kid, by_pairing)
            for fid, f in c.fighters.items():
                self._fighter(c, fid, f, meta.get(fid.hex(), {}))
            for s in export.season_numbers(c):
                d = export.season_doc(c, s, rule)
                conn.execute("INSERT OR REPLACE INTO seasons VALUES(?,?,?,?,?)",
                             (s, d["status"], int(d["final"]), d["champion"], json.dumps(d)))
            conn.execute("DELETE FROM ownership")
            for hexid, m in meta.items():
                for i, h in enumerate(((m.get("asset") or {}).get("history")) or []):
                    conn.execute("INSERT INTO ownership VALUES(?,?,?,?,?)",
                                 (hexid, i, int(h["tick"]), h.get("from"), h["to"]))
            if sales is not None:
                conn.execute("DELETE FROM sales")
                for i, x in enumerate(sales, 1):
                    conn.execute("INSERT INTO sales VALUES(?,?,?,?,?,?,?,?)",
                                 (i, int(x["tick"]), x["fighter_id"], x["seller"], x["buyer"], int(x["price"]),
                                  int(x["fee"]), json.dumps(x)))
            if economics is not None:
                set_meta(conn, "economics", economics)
            for k, v in state.items():
                set_meta(conn, k, v)
            set_meta(conn, "tick", c.tick)
            set_meta(conn, "event_seq", c.event_seq)
            set_meta(conn, "event_digest", c.event_digest.hex())
            set_meta(conn, "deployment", {k: v for k, v in deployment.items() if k not in ("fighters", "names")})
            set_meta(conn, "network_id", c.m.network_id.hex())
            set_meta(conn, "contract_id", c.m.contract_id.hex())
        self.max_fight = max([self.max_fight] + list(c.fights))
        self.max_contest = max([self.max_contest] + list(c.contests))
        self.max_cup = max([self.max_cup] + list(c.cups))

    def _fight(self, c, fid):
        x = c.fights[fid]
        contest = c.contests[x.contest_id]
        final = x.phase == "DONE" and contest.status == "DONE"
        summary = _strip(export.fight_summary(c, fid))
        summary["final"] = final
        replay = _strip(export.fight_replay(c, fid)) if (x.rounds or x.result) else None
        a, b = x.context.participant_a.fighter_id.hex(), x.context.participant_b.fighter_id.hex()
        mode = codec.Mode(x.context.mode).name.lower()
        r = x.result or {}
        winner = {"A": a, "B": b}.get(r.get("winner"))
        self.conn.execute("INSERT OR REPLACE INTO fights VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (fid, x.contest_id, mode, a, b, x.phase, int(final), x.start_tick, r.get("tick"),
                           r.get("kind"), winner, r.get("result"), len(x.rounds), pack(summary),
                           pack(replay) if replay is not None else None))
        for slot, me, opp in (("A", a, b), ("B", b, a)):
            self.conn.execute("INSERT OR REPLACE INTO fight_sides VALUES(?,?,?,?,?,?,?)",
                              (me, fid, slot, opp, mode, outcome_of(x.result, slot), r.get("tick")))
        if final:
            self.open_fights.discard(fid)
        else:
            self.open_fights.add(fid)

    def _contest(self, c, cid):
        ct = c.contests[cid]
        mode = codec.Mode(ct.mode).name.lower()
        doc = export.duel_doc(ct)
        doc["mode"] = mode
        end = ct.result.get("tick") if ct.result else None
        self.conn.execute("INSERT OR REPLACE INTO contests VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (cid, mode, codec.Format(ct.fmt).name, ct.a.fighter_id.hex(), ct.b.fighter_id.hex(),
                           ct.stake, ct.status, ct.season, ct.cup_id, ct.pairing_id, ct.start_tick, end,
                           json.dumps(doc)))
        if ct.status == "DONE" and ct.mode == codec.Mode.RANKED and ct.settlement and ct.result:
            kind = ct.result.get("kind")
            last = ct.fights[-1] if ct.fights else 0
            for slot, p in (("A", ct.a), ("B", ct.b)):
                r = ct.settlement["ratings"][slot]
                self.conn.execute("INSERT OR REPLACE INTO ratings VALUES(?,?,?,?,?,?,?,?,?,?)",
                                  (p.fighter_id.hex(), cid, last, end, ct.season, kind, r["lifetime"][0],
                                   r["lifetime"][1], r["season"][0], r["season"][1]))
        if ct.status == "DONE":
            self.open_contests.discard(cid)
        else:
            self.open_contests.add(cid)

    def _cup(self, c, kid, by_pairing):
        k = c.cups[kid]
        d = export.cup_doc(c, k, by_pairing)
        self.conn.execute("INSERT OR REPLACE INTO cups VALUES(?,?,?,?,?)",
                          (kid, k.status, k.created_tick, d["champion"], json.dumps(d)))
        if k.status in FINAL_CUP:
            self.open_cups.discard(kid)
        else:
            self.open_cups.add(kid)

    def _fighter(self, c, fid, f, m):
        placed = f.placement >= PLACEMENT_FIGHTS
        self.conn.execute(
            "INSERT OR REPLACE INTO fighters VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (fid.hex(), m.get("name"), origin_of(m, f.house_npc), m.get("driver"), int(f.house_npc),
             f.owner.hex(), f.operator.hex(), f.auth_version, f.lock, f.lifetime, f.placement, int(not placed),
             belt(f.lifetime, placed), json.dumps(f.record, sort_keys=True),
             json.dumps({str(k): v for k, v in sorted(f.faults.items())}),
             json.dumps({str(k): v for k, v in sorted(f.season_rating.items())}),
             f.cooldown_until, f.suspended_epoch, json.dumps(m.get("asset")) if m.get("asset") else None))


def dump(conn) -> dict:
    """Every row of every table (for the rebuild-equals-incremental check)."""
    out = {}
    for t in TABLES:
        rows = conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall()
        out[t] = [tuple(unpack(v) if isinstance(v, bytes) else v for v in r) for r in rows]
    return out


# ---- following the journal ----------------------------------------------------

class Follower:
    """Tails a devnet journal into a replica and a database.

    `lock` guards the replica: the API's chain-read endpoints take it too."""

    def __init__(self, devnet_dir: Path, db_path: Path, export_dir: Path | None = None,
                 snapshot: Path | None | bool = True, log=print):
        self.dir = Path(devnet_dir)
        self.db_path = Path(db_path)
        self.export_dir = Path(export_dir) if export_dir else None
        self.snapshot_path = (self.db_path.with_suffix(".replica") if snapshot is True else
                              Path(snapshot) if snapshot else None)
        self.log = log
        self.lock = threading.RLock()
        self.m = manifest_for(self.dir)
        from .devnet import QUALIFICATION
        self.rule = QUALIFICATION.get(json.loads((self.dir / MARKER).read_text()).get("profile", "dev"))
        self.conn = connect(self.db_path)
        self.syncer = Syncer(self.conn)
        self.replica: Replica | None = None
        self.offset = 0
        self.tail_sig = ""
        self.db_offset = get_meta(self.conn, "journal_offset", 0)
        self._deployment: tuple[float, dict] = (-1.0, {})
        self._snap_at = time.monotonic()
        self.caught_up = False
        if self.db_offset:
            with open(self.dir / JOURNAL, "rb") as j:
                size = os.fstat(j.fileno()).st_size
                if size < self.db_offset or self._sig(j, self.db_offset) != get_meta(self.conn, "journal_sig"):
                    self.log("readmodel: the database indexes another journal; starting it afresh")
                    self._wipe()
        self._resume()

    # -- state ---------------------------------------------------------------

    def _sig(self, f, offset: int) -> str:
        start = max(0, offset - 256)
        f.seek(start)
        return hashlib.sha256(f.read(offset - start)).hexdigest()

    def _resume(self):
        """Load the snapshot when it belongs to this code and this journal; else start from byte 0."""
        self.replica, self.offset, self.tail_sig = Replica(self.m), 0, ""
        if not self.snapshot_path or not self.snapshot_path.exists():
            return
        try:
            # pickle runs code from the file it loads. This file is private
            # state this process wrote itself (mode 0600, next to the database,
            # never served or uploaded); anything else is refused unread.
            st = self.snapshot_path.stat()
            private = (st.st_uid == os.getuid() and not st.st_mode & 0o077) if os.name == "posix" else True
            if not private:
                self.log("readmodel: snapshot is not a private file of this user; ignoring it")
                return
            with open(self.snapshot_path, "rb") as f:
                snap = pickle.load(f)
            ok = snap.get("code") == code_version() and snap.get("network") == self.m.network_id.hex()
            if ok:
                with open(self.dir / JOURNAL, "rb") as j:
                    size = os.fstat(j.fileno()).st_size
                    ok = snap["offset"] <= size and self._sig(j, snap["offset"]) == snap["tail_sig"]
            if ok:
                self.replica, self.offset, self.tail_sig = snap["replica"], snap["offset"], snap["tail_sig"]
                self.log(f"readmodel: resumed replica at byte {self.offset} (tick {self.replica.tick})")
            else:
                self.log("readmodel: snapshot is for other code or another journal; replaying from the start")
        except Exception as exc:                     # a bad snapshot costs a replay, never the service
            self.log(f"readmodel: snapshot unreadable ({exc}); replaying from the start")

    def _wipe(self):
        """Forget every row: the journal they came from is gone."""
        with self.conn:
            for t in TABLES:
                self.conn.execute(f"DELETE FROM {t}")
            self.conn.execute("DELETE FROM meta WHERE key != 'schema'")
        self.syncer = Syncer(self.conn)
        self.db_offset = 0

    def save_snapshot(self):
        if not self.snapshot_path or self.replica is None or self.replica.contract is None:
            return
        with self.lock:
            blob = pickle.dumps({"code": code_version(), "network": self.m.network_id.hex(), "offset": self.offset,
                                 "tail_sig": self.tail_sig, "replica": self.replica}, protocol=5)
        tmp = self.snapshot_path.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.snapshot_path)
        self._snap_at = time.monotonic()

    def deployment(self) -> dict:
        if self.export_dir is None:
            return {}
        try:
            mtime = (self.export_dir / "index.json").stat().st_mtime
        except OSError:
            return self._deployment[1]
        if mtime != self._deployment[0]:
            self._deployment = (mtime, load_deployment(self.export_dir))
        return self._deployment[1]

    def sales(self) -> list | None:
        """Every sale of the simulated market: the arena's own market.json (all
        sales; the export's market.json has only the latest). Market payments
        are journal records ("xfer"); the sale itself is host state."""
        try:
            return json.loads((self.dir / "market.json").read_text()).get("sales")
        except (OSError, ValueError):
            return None

    def economics(self) -> dict | None:
        if self.export_dir is None:
            return None
        try:
            doc = json.loads((self.export_dir / "economics.json").read_text())
        except (OSError, ValueError):
            return None
        return {k: v for k, v in doc.items() if k not in ("schema", "network_id", "contract_id", "source")}

    # -- the loop ---------------------------------------------------------------

    def poll(self, max_bytes: int = READ_CHUNK) -> int:
        """Apply the journal's new complete lines (up to max_bytes). Returns records applied."""
        path = self.dir / JOURNAL
        with open(path, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            if size < self.offset or (self.offset and self._sig(f, self.offset) != self.tail_sig):
                self.log("readmodel: the journal was replaced or truncated; rebuilding from its start")
                with self.lock:
                    self.replica, self.offset, self.tail_sig = Replica(self.m), 0, ""
                    self.caught_up = False
                    self._wipe()
            f.seek(self.offset)
            data = f.read(min(max_bytes, size - self.offset))
        end = data.rfind(b"\n")
        if end < 0:
            return 0
        lines = data[:end + 1].splitlines()
        with self.lock:
            n = 0
            for line in lines:
                if line.strip():
                    self.replica.apply(json.loads(line))
                    n += 1
            self.offset += end + 1
            with open(path, "rb") as f:
                self.tail_sig = self._sig(f, self.offset)
        return n

    def sync(self):
        """Write the replica's state, unless it is still behind what the database already shows."""
        if self.replica.contract is None:
            return False
        if self.offset < self.db_offset:
            return False                  # catching up after a restart: never show older state
        with self.lock:
            self.syncer.sync(self.replica.contract, self.deployment(),
                             {"journal_offset": self.offset, "journal_sig": self.tail_sig,
                              "journal_records": self.replica.records,
                              "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                             rule=self.rule, sales=self.sales(), economics=self.economics())
        self.db_offset = self.offset
        return True

    def step(self) -> int:
        """Catch up completely (in chunks), then sync once."""
        total = 0
        while True:
            n = self.poll()
            total += n
            if n == 0:
                break
        before = self._deployment[0]
        self.deployment()
        if total or not self.caught_up or self._deployment[0] != before:   # new records, or new names/owners
            self.sync()
            self.caught_up = True
        if time.monotonic() - self._snap_at > SNAPSHOT_EVERY_S:
            self.save_snapshot()
        return total

    def run(self, stop: threading.Event, interval: float = 1.0):
        while not stop.is_set():
            try:
                self.step()
            except Exception as exc:          # keep serving the last good database
                self.log(f"readmodel: sync failed: {exc!r}")
                stop.wait(10)
            stop.wait(interval)
        try:
            self.save_snapshot()
        except Exception as exc:
            self.log(f"readmodel: snapshot on exit failed: {exc!r}")


def rebuild(devnet_dir: Path, db_path: Path, export_dir: Path | None = None, log=print) -> dict:
    """Build a fresh database from the whole journal and swap it in atomically."""
    db_path = Path(db_path)
    tmp = db_path.with_name(db_path.name + ".rebuild")
    for p in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
        p.unlink(missing_ok=True)
    t0 = time.monotonic()
    fl = Follower(devnet_dir, tmp, export_dir, snapshot=False, log=log)
    while fl.poll():
        pass
    t1 = time.monotonic()
    fl.sync()
    fl.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    fl.conn.close()
    os.replace(tmp, db_path)
    for suffix in ("-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
        Path(str(tmp) + suffix).unlink(missing_ok=True)
    snap = db_path.with_suffix(".replica")
    snap.unlink(missing_ok=True)             # a snapshot must never be ahead of or unrelated to the db
    t2 = time.monotonic()
    stats = {"records": fl.replica.records, "tick": fl.replica.tick, "fights": len(fl.replica.contract.fights),
             "replay_s": round(t1 - t0, 1), "index_s": round(t2 - t1, 1), "bytes": db_path.stat().st_size}
    log(f"readmodel: rebuilt {db_path}: {stats}")
    return stats
