"""The read API (docs/api.md §3.2) and the static export, from one small server.

  qdojo combat api --db ~/.qdojo/combat/readmodel.sqlite --export ~/.qdojo/combat/public/combat/v1 \\
      --devnet ~/.qdojo/combat/arena --host 100.101.145.63 --port 8790

- `/api/v1/...` answers from the SQLite read model (readmodel.py): full
  history, pagination, search. Read-only: every read opens the database with
  mode=ro.
- Every other path is a file from the static export directory, exactly what
  `python -m http.server` served before, so /data/combat/v1/ keeps working.
- With --devnet it also follows the arena's journal and keeps the database
  current (a background thread; see readmodel.Follower).
- With --join-inbox (off by default) it accepts outside-builder registrations
  and signed transactions for the simulated chain (join.py, docs/build-a-bot.md §8).

Stdlib only. Errors are JSON; CORS answers only the configured origins.
"""
from __future__ import annotations

import email.utils
import gzip
import hashlib
import ipaddress
import json
import mimetypes
import os
import re
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from . import readmodel as rm

API = "/api/v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DEC = re.compile(r"^[0-9]{1,19}$")
MODES = ("ranked", "duel", "cup")
PER_PAGE, MAX_PER_PAGE = 50, 200
MAX_REPLAYS = 100
MAX_BODY = 8192
LIVE_CACHE = "public, max-age=5"
FINAL_CACHE = "public, max-age=86400"
DEFAULT_ORIGINS = ("https://qdojo.jonsggi.com",)

# Direct peers allowed to name the client (the site's nginx reaches the API
# over the tailnet or a private network). Exact CIDRs, not string prefixes.
TRUSTED_PROXIES = tuple(ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "::1/128", "100.64.0.0/10", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))


def _trusted_peer(peer: str) -> bool:
    try:
        ip = ipaddress.ip_address(peer)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in n for n in TRUSTED_PROXIES)



class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _schema(kind: str) -> str:
    return f"qdojo.combat.api.{kind}.v1"


def _int(q: dict, key: str, default: int, lo: int, hi: int) -> int:
    raw = q.get(key, [None])[-1]
    if raw is None or raw == "":
        return default
    if not DEC.match(raw):
        raise ApiError(400, "bad_query", f"{key} must be a decimal integer")
    return max(lo, min(hi, int(raw)))


def _one(q: dict, key: str) -> str | None:
    v = q.get(key, [None])[-1]
    return v if v not in (None, "") else None


# ---- queries --------------------------------------------------------------------

class Reader:
    """All reads for one request, over one read-only connection."""

    def __init__(self, conn: sqlite3.Connection):
        self.c = conn
        self.tick = rm.get_meta(conn, "tick")
        if self.tick is None:
            raise ApiError(503, "not_ready", "the read model has not indexed anything yet")

    def env(self, kind: str, body: dict, tick=None) -> dict:
        return {"schema": _schema(kind), "generated_tick": str(self.tick if tick is None else tick), **body}

    # -- fighters --------------------------------------------------------------

    def _records(self, fighter: str | None = None) -> dict:
        sql = "SELECT fighter_id, mode, outcome, COUNT(*) FROM fight_sides WHERE outcome IS NOT NULL"
        args: tuple = ()
        if fighter:
            sql += " AND fighter_id = ?"
            args = (fighter,)
        out: dict = {}
        for fid, mode, outcome, n in self.c.execute(sql + " GROUP BY fighter_id, mode, outcome", args):
            r = out.setdefault(fid, {}).setdefault(mode, {"W": 0, "D": 0, "L": 0, "FW": 0, "FL": 0, "N": 0})
            r[outcome] = n
        return out

    def form(self, fighter: str, n: int = 5) -> list[dict]:
        rows = self.c.execute(
            "SELECT s.fight_id, s.outcome, f.kind, f.result FROM fight_sides s JOIN fights f USING(fight_id) "
            "WHERE s.fighter_id = ? AND s.outcome IS NOT NULL ORDER BY s.fight_id DESC LIMIT ?", (fighter, n))
        out = []
        for fid, outcome, kind, result in rows:
            mark = {"W": "W", "FW": "W", "L": "L", "FL": "L", "D": "D"}.get(outcome, "N")
            out.append({"fight_id": str(fid), "mark": mark, "how": (result or "") if kind == "COMBAT" else kind,
                        "forfeit": kind == "FORFEIT"})
        return out

    def fighter_row(self, r, records: dict | None = None, form: bool = True) -> dict:
        fid = r["fighter_id"]
        by_mode = (records if records is not None else self._records(fid)).get(fid, {})
        total = {k: sum(m.get(k, 0) for m in by_mode.values()) for k in ("W", "D", "L", "FW", "FL", "N")}
        live = self.c.execute("SELECT COUNT(*) FROM fight_sides WHERE fighter_id = ? AND outcome IS NULL",
                              (fid,)).fetchone()[0]
        doc = {"fighter_id": fid, "name": r["name"], "origin": r["origin"], "driver": r["driver"],
               "house_npc": bool(r["house_npc"]), "owner": r["owner"], "operator": r["operator"],
               "auth_version": r["auth_version"], "lock": r["lock"], "lifetime_rating": r["lifetime_rating"],
               "provisional": bool(r["provisional"]), "belt": r["belt"], "placement_fights": r["placement"],
               "record": json.loads(r["record"]), "records_by_mode": by_mode, "career": total,
               "fights_total": sum(total.values()) + live, "fights_live": live,
               "faults_by_epoch": json.loads(r["faults"]), "season_ratings": json.loads(r["season_ratings"]),
               "cooldown_until": str(r["cooldown_until"]), "asset": json.loads(r["asset"]) if r["asset"] else None}
        if form:
            doc["form"] = self.form(fid)
        return doc

    def fighters(self) -> list[dict]:
        records = self._records()
        return [self.fighter_row(r, records) for r in self.c.execute("SELECT * FROM fighters ORDER BY fighter_id")]

    def fighter(self, hexid: str) -> dict:
        r = self.c.execute("SELECT * FROM fighters WHERE fighter_id = ?", (hexid,)).fetchone()
        if r is None:
            raise ApiError(404, "not_found", "no such fighter")
        doc = self.fighter_row(r)
        doc["form"] = self.form(hexid, 10)
        doc["fights"] = [str(x[0]) for x in self.c.execute(
            "SELECT fight_id FROM fight_sides WHERE fighter_id = ? ORDER BY fight_id DESC LIMIT 64", (hexid,))][::-1]
        first = self.c.execute("SELECT MIN(fight_id) FROM fight_sides WHERE fighter_id = ?", (hexid,)).fetchone()[0]
        doc["first_fight"] = str(first) if first is not None else None
        doc["ratings_recent"] = [self._rating(x) for x in self.c.execute(
            "SELECT * FROM ratings WHERE fighter_id = ? ORDER BY tick DESC, contest_id DESC LIMIT 100", (hexid,))][::-1]
        return self.env("fighter", doc)

    @staticmethod
    def _rating(x) -> dict:
        return {"contest_id": str(x["contest_id"]), "fight_id": str(x["fight_id"]), "tick": str(x["tick"]),
                "season": x["season"], "kind": x["kind"], "lifetime": [x["lifetime_before"], x["lifetime_after"]],
                "season_rating": [x["season_before"], x["season_after"]]}

    def leaderboard(self) -> dict:
        rows = self.fighters()

        def faults(f):
            return sum(int(v) for v in f["faults_by_epoch"].values())
        rows.sort(key=lambda f: (-f["lifetime_rating"], -f["record"].get("W", 0), faults(f), f["fighter_id"]))
        for i, f in enumerate(rows):
            f["rank"] = i + 1
            f["faults"] = faults(f)
        return self.env("leaderboard", {"fighters": rows})

    # -- fights ------------------------------------------------------------------

    def _page(self, q: dict, total: int) -> tuple[int, int, int]:
        per = _int(q, "per_page", PER_PAGE, 1, MAX_PER_PAGE)
        pages = max(1, -(-total // per))
        page = _int(q, "page", 1, 1, 10**9)
        return page, per, pages

    def fights(self, q: dict) -> dict:
        fighter, mode, status = _one(q, "fighter"), _one(q, "mode"), _one(q, "status") or "all"
        if fighter is not None and not HEX64.match(fighter):
            raise ApiError(400, "bad_query", "fighter must be 64 lowercase hex digits")
        if mode is not None and mode not in MODES:
            raise ApiError(400, "bad_query", "mode must be one of " + ", ".join(MODES))
        if status not in ("all", "done", "live"):
            raise ApiError(400, "bad_query", "status must be all, done or live")
        where, args = [], []
        if fighter:
            src = "fight_sides s JOIN fights f USING(fight_id)"
            where.append("s.fighter_id = ?")
            args.append(fighter)
            if mode:
                where.append("s.mode = ?")
                args.append(mode)
        else:
            src = "fights f"
            if mode:
                where.append("f.mode = ?")
                args.append(mode)
        if status == "done":
            where.append("f.phase = 'DONE'")
        elif status == "live":
            where.append("f.phase != 'DONE'")
        w = (" WHERE " + " AND ".join(where)) if where else ""
        total = self.c.execute(f"SELECT COUNT(*) FROM {src}{w}", args).fetchone()[0]
        page, per, pages = self._page(q, total)
        cols = "f.fight_id, f.summary" + (", s.slot, s.outcome" if fighter else "")
        items = []
        for r in self.c.execute(f"SELECT {cols} FROM {src}{w} ORDER BY f.fight_id DESC LIMIT ? OFFSET ?",
                                args + [per, (page - 1) * per]):
            doc = rm.unpack(r["summary"])
            if fighter:
                doc["slot"], doc["outcome"] = r["slot"], r["outcome"]
            items.append(doc)
        return self.env("fights", {"filters": {"fighter": fighter, "mode": mode, "status": status},
                                   "page": page, "per_page": per, "pages": pages, "total": total, "items": items})

    def fight(self, fid: int, replay: bool = False) -> tuple[dict, bool]:
        r = self.c.execute("SELECT final, end_tick, summary, replay FROM fights WHERE fight_id = ?",
                           (fid,)).fetchone()
        if r is None:
            raise ApiError(404, "not_found", "no such fight")
        blob = r["replay"] if replay else r["summary"]
        if blob is None:
            raise ApiError(404, "not_found", "no round of this fight has resolved yet")
        doc = rm.unpack(blob)
        final = bool(r["final"])
        # A final document never changes: its tick is when it last changed, so it caches forever.
        doc["generated_tick"] = str(r["end_tick"] if final and r["end_tick"] is not None else self.tick)
        return doc, final

    def replays(self, hexid: str, q: dict) -> dict:
        if self.c.execute("SELECT 1 FROM fighters WHERE fighter_id = ?", (hexid,)).fetchone() is None:
            raise ApiError(404, "not_found", "no such fighter")
        before = _int(q, "before", 2**62, 0, 2**62)
        limit = _int(q, "limit", 50, 1, MAX_REPLAYS)
        rows = self.c.execute(
            "SELECT f.fight_id, f.replay FROM fight_sides s JOIN fights f USING(fight_id) WHERE s.fighter_id = ? "
            "AND f.final = 1 AND f.replay IS NOT NULL AND f.fight_id < ? ORDER BY f.fight_id DESC LIMIT ?",
            (hexid, before, limit)).fetchall()
        total = self.c.execute("SELECT COUNT(*) FROM fight_sides s JOIN fights f USING(fight_id) WHERE "
                               "s.fighter_id = ? AND f.final = 1 AND f.replay IS NOT NULL", (hexid,)).fetchone()[0]
        items = [{"fight_id": str(r[0]), "replay": rm.unpack(r[1])} for r in rows]
        return self.env("replays", {"fighter_id": hexid, "total": total, "items": items,
                                    "next_before": items[-1]["fight_id"] if len(items) == limit else None})

    def ratings(self, hexid: str, q: dict) -> dict:
        total = self.c.execute("SELECT COUNT(*) FROM ratings WHERE fighter_id = ?", (hexid,)).fetchone()[0]
        page, per, pages = self._page(q, total)
        rows = self.c.execute("SELECT * FROM ratings WHERE fighter_id = ? ORDER BY tick DESC, contest_id DESC "
                              "LIMIT ? OFFSET ?", (hexid, per, (page - 1) * per))
        return self.env("ratings", {"fighter_id": hexid, "page": page, "per_page": per, "pages": pages,
                                    "total": total, "items": [self._rating(x) for x in rows]})

    # -- seasons, cups, duels, owners, search ------------------------------------------

    def seasons(self) -> dict:
        d = rm.get_meta(self.c, "deployment", {})
        items = [json.loads(r[0]) for r in self.c.execute("SELECT doc FROM seasons ORDER BY season DESC")]
        return self.env("seasons", {"profile": d.get("profile"), "seasons": items})

    def season(self, n: int) -> dict:
        r = self.c.execute("SELECT doc FROM seasons WHERE season = ?", (n,)).fetchone()
        if r is None:
            raise ApiError(404, "not_found", "no such season")
        return self.env("season", json.loads(r[0]))

    def _docs(self, kind: str, sql_count: str, sql_page: str, q: dict, args=()) -> dict:
        total = self.c.execute(sql_count, args).fetchone()[0]
        page, per, pages = self._page(q, total)
        items = [json.loads(r[0]) for r in self.c.execute(sql_page, (*args, per, (page - 1) * per))]
        return self.env(kind, {"page": page, "per_page": per, "pages": pages, "total": total, "items": items})

    def cups(self, q: dict) -> dict:
        return self._docs("cups", "SELECT COUNT(*) FROM cups",
                          "SELECT doc FROM cups ORDER BY cup_id DESC LIMIT ? OFFSET ?", q)

    def cup(self, n: int) -> dict:
        r = self.c.execute("SELECT doc FROM cups WHERE cup_id = ?", (n,)).fetchone()
        if r is None:
            raise ApiError(404, "not_found", "no such cup")
        return self.env("cup", json.loads(r[0]))

    def duels(self, q: dict) -> dict:
        return self._docs("duels", "SELECT COUNT(*) FROM contests WHERE mode = 'duel'",
                          "SELECT doc FROM contests WHERE mode = 'duel' ORDER BY contest_id DESC LIMIT ? OFFSET ?", q)

    def duel(self, n: int) -> dict:
        r = self.c.execute("SELECT doc FROM contests WHERE contest_id = ? AND mode = 'duel'", (n,)).fetchone()
        if r is None:
            raise ApiError(404, "not_found", "no such duel")
        return self.env("duel", json.loads(r[0]))

    def owner(self, hexid: str) -> dict:
        now = [r[0] for r in self.c.execute("SELECT fighter_id FROM fighters WHERE owner = ? ORDER BY fighter_id",
                                            (hexid,))]
        past = [r[0] for r in self.c.execute("SELECT DISTINCT fighter_id FROM ownership WHERE to_owner = ? "
                                             "ORDER BY fighter_id", (hexid,)) if r[0] not in now]
        if not now and not past:
            raise ApiError(404, "not_found", "this identity owns and owned no fighter")
        return self.env("owner", {"owner": hexid, "owned": now, "previously_owned": past})

    def search(self, q: dict) -> dict:
        text = (_one(q, "q") or "").strip()
        if not 1 <= len(text) <= 64:
            raise ApiError(400, "bad_query", "q must be 1 to 64 characters")
        low = text.lower()
        like = "%" + low.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        fighters = [{"fighter_id": r[0], "name": r[1], "origin": r[2], "lifetime_rating": r[3]} for r in self.c.execute(
            "SELECT fighter_id, name, origin, lifetime_rating FROM fighters WHERE lower(name) LIKE ? ESCAPE '\\' "
            "OR fighter_id LIKE ? ESCAPE '\\' ORDER BY lifetime_rating DESC LIMIT 20",
            (like, (low if re.fullmatch(r"[0-9a-f]{4,64}", low) else "\0") + "%"))]
        fights = []
        if DEC.match(text):
            fights = [str(r[0]) for r in self.c.execute("SELECT fight_id FROM fights WHERE fight_id = ?", (int(text),))]
        owners = []
        if re.fullmatch(r"[0-9a-f]{8,64}", low):
            owners = [r[0] for r in self.c.execute(
                "SELECT owner FROM fighters WHERE owner LIKE ? UNION SELECT to_owner FROM ownership WHERE to_owner "
                "LIKE ? LIMIT 10", (low + "%", low + "%"))]
        return self.env("search", {"q": text, "fighters": fighters, "fights": fights, "owners": owners})

    def status(self, extra: dict) -> dict:
        m = {k: rm.get_meta(self.c, k) for k in ("journal_offset", "journal_records", "synced_at", "event_seq",
                                                 "network_id", "contract_id", "deployment")}
        counts = {t: self.c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("fighters", "fights", "contests", "cups", "seasons")}
        return self.env("status", {**m, "counts": counts, **extra})


# ---- the HTTP layer ------------------------------------------------------------------

class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, db: Path, export_dir: Path | None, origins=DEFAULT_ORIGINS, join=None,
                 follower=None, access_log=False):
        super().__init__(addr, Handler)
        self.db, self.export_dir = Path(db), (Path(export_dir).resolve() if export_dir else None)
        self.origins = tuple(origins)
        self.join, self.follower, self.access_log = join, follower, access_log


class Handler(BaseHTTPRequestHandler):
    server: Server
    server_version = "qdojo-api"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = 15

    def log_message(self, fmt, *args):
        if self.server.access_log:
            super().log_message(fmt, *args)

    # -- plumbing ---------------------------------------------------------------

    def _cors(self) -> dict:
        origin = self.headers.get("Origin")
        allowed = self.server.origins
        if origin and ("*" in allowed or origin in allowed):
            methods = "GET, HEAD, OPTIONS" + (", POST" if self.server.join else "")
            return {"Access-Control-Allow-Origin": "*" if "*" in allowed else origin,
                    "Access-Control-Allow-Methods": methods, "Access-Control-Allow-Headers": "Content-Type",
                    "Access-Control-Max-Age": "600", "Vary": "Origin"}
        return {"Vary": "Origin"}

    def _send(self, status: int, body: bytes, ctype: str, cache: str, extra: dict | None = None):
        headers = {"Content-Type": ctype, "Cache-Control": cache, "X-Content-Type-Options": "nosniff",
                   **self._cors(), **(extra or {})}
        if status == 200:
            etag = '"' + hashlib.sha1(body).hexdigest()[:20] + '"'
            headers["ETag"] = etag
            if etag in [t.strip() for t in self.headers.get("If-None-Match", "").split(",")]:
                self.send_response(304)
                for k, v in headers.items():
                    if k not in ("Content-Type",):
                        self.send_header(k, v)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        if len(body) > 1024 and "gzip" in self.headers.get("Accept-Encoding", ""):
            body = gzip.compress(body, 5)
            headers["Content-Encoding"] = "gzip"
            headers["Vary"] = headers["Vary"] + ", Accept-Encoding"
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, doc: dict, cache: str = LIVE_CACHE):
        self._send(status, json.dumps(doc, separators=(",", ":")).encode(), "application/json; charset=utf-8", cache)

    def _error(self, e: ApiError):
        self._json(e.status, {"schema": _schema("error"),
                              "error": {"status": e.status, "code": e.code, "message": e.message}}, "no-store")

    def client_ip(self) -> str:
        """The client address for per-IP limits.

        Only the site's nginx is trusted to name the client: it resolves the
        real address (walking X-Forwarded-For through known proxy and
        Cloudflare ranges only) and overwrites X-Real-Client-IP with it. That
        header is read only when the direct peer is inside TRUSTED_PROXIES;
        anything else a client sends, X-Forwarded-For included, is ignored."""
        peer = self.client_address[0]
        named = self.headers.get("X-Real-Client-IP", "").strip()
        if named and _trusted_peer(peer):
            try:
                return str(ipaddress.ip_address(named))
            except ValueError:
                return peer
        return peer

    # -- verbs -------------------------------------------------------------------

    def do_OPTIONS(self):
        self._send(204, b"", "text/plain", "public, max-age=600")

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlsplit(self.path)
        path = unquote(url.path)
        try:
            if path == API or path.startswith(API + "/"):
                self._api("GET", path[len(API):].strip("/"), parse_qs(url.query, keep_blank_values=True))
            else:
                self._static(path)
        except ApiError as e:
            self._error(e)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:                  # never a stack trace to a client
            self.log_error("internal error on %s: %r", self.path, exc)
            self._error(ApiError(500, "internal", "internal error"))

    def do_POST(self):
        url = urlsplit(self.path)
        path = unquote(url.path)
        try:
            if not (path.startswith(API + "/") and self.server.join):
                raise ApiError(404 if not path.startswith(API) else 405, "not_found" if not path.startswith(API)
                               else "read_only", "this server is read-only" if path.startswith(API) else "no such path")
            n = self.headers.get("Content-Length")
            if n is None or not n.isdigit():
                raise ApiError(411, "length_required", "Content-Length is required")
            if int(n) > MAX_BODY:
                raise ApiError(413, "too_large", f"bodies are at most {MAX_BODY} bytes")
            raw = self.rfile.read(int(n))
            try:
                body = json.loads(raw)
            except ValueError:
                raise ApiError(400, "bad_json", "the body must be one JSON object") from None
            if not isinstance(body, dict):
                raise ApiError(400, "bad_json", "the body must be one JSON object")
            status, doc = self.server.join.post(path[len(API):].strip("/").split("/"), body, self.client_ip())
            self._json(status, doc, "no-store")
        except ApiError as e:
            self._error(e)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self.log_error("internal error on POST %s: %r", self.path, exc)
            self._error(ApiError(500, "internal", "internal error"))

    # -- routes ---------------------------------------------------------------------

    def _reader(self) -> tuple[sqlite3.Connection, Reader]:
        if not self.server.db.exists():
            raise ApiError(503, "not_ready", "the read model has not been built yet")
        conn = rm.connect(self.server.db, readonly=True)
        try:
            return conn, Reader(conn)
        except Exception:
            conn.close()
            raise

    def _api(self, method: str, rest: str, q: dict):
        parts = rest.split("/") if rest else []
        if parts[:1] in (["tx"], ["join"], ["chain"]):
            if not self.server.join:
                raise ApiError(404, "join_disabled", "outside-builder entry is not enabled on this arena")
            status, doc = self.server.join.get(parts, q, self.client_ip())
            return self._json(status, doc, "no-store")
        conn, r = self._reader()
        try:
            doc, cache = self._route(r, parts, q)
        finally:
            conn.close()
        self._json(200, doc, cache)

    def _route(self, r: Reader, p: list[str], q: dict) -> tuple[dict, str]:
        n = len(p)
        head = p[0] if p else ""
        if head == "status" and n == 1:
            fl = self.server.follower
            extra = {"following": bool(fl), "caught_up": bool(fl and fl.caught_up),
                     "join_enabled": bool(self.server.join)}
            return r.status(extra), "no-store"
        if head == "fighters":
            if n == 1:
                return r.env("fighters", {"fighters": r.fighters()}), LIVE_CACHE
            if not HEX64.match(p[1]):
                raise ApiError(400, "bad_id", "a fighter ID is 64 lowercase hex digits")
            if n == 2:
                return r.fighter(p[1]), LIVE_CACHE
            if n == 3 and p[2] == "fights":
                q = {**q, "fighter": [p[1]]}
                return r.fights(q), LIVE_CACHE
            if n == 3 and p[2] == "replays":
                return r.replays(p[1], q), LIVE_CACHE
            if n == 3 and p[2] == "ratings":
                return r.ratings(p[1], q), LIVE_CACHE
        if head == "fights":
            if n == 1:
                return r.fights(q), LIVE_CACHE
            if not DEC.match(p[1]):
                raise ApiError(400, "bad_id", "a fight ID is a decimal number")
            if n == 2 or (n == 3 and p[2] == "replay"):
                doc, final = r.fight(int(p[1]), replay=n == 3)
                return doc, FINAL_CACHE if final else LIVE_CACHE
        if head == "leaderboard" and n == 1:
            return r.leaderboard(), LIVE_CACHE
        if head == "seasons":
            if n == 1:
                return r.seasons(), LIVE_CACHE
            if n == 2 and DEC.match(p[1]):
                return r.season(int(p[1])), LIVE_CACHE
        if head == "cups":
            if n == 1:
                return r.cups(q), LIVE_CACHE
            if n == 2 and DEC.match(p[1]):
                return r.cup(int(p[1])), LIVE_CACHE
        if head == "duels":
            if n == 1:
                return r.duels(q), LIVE_CACHE
            if n == 2 and DEC.match(p[1]):
                return r.duel(int(p[1])), LIVE_CACHE
        if head == "owners" and n == 2:
            if not HEX64.match(p[1]):
                raise ApiError(400, "bad_id", "an owner ID is 64 lowercase hex digits")
            return r.owner(p[1]), LIVE_CACHE
        if head == "search" and n == 1:
            return r.search(q), LIVE_CACHE
        raise ApiError(404, "not_found", "no such endpoint; see docs/api.md §3.2")

    def _static(self, path: str):
        """A file from the export, as http.server served it (no listings, no traversal)."""
        root = self.server.export_dir
        if root is None:
            raise ApiError(404, "not_found", "no static export configured")
        rel = path.lstrip("/")
        if rel.startswith("data/combat/v1/"):
            rel = rel[len("data/combat/v1/"):]          # the site's own path, when nothing strips it
        target = (root / rel).resolve()
        if root != target and root not in target.parents:
            raise ApiError(404, "not_found", "no such file")
        if not target.is_file():
            raise ApiError(404, "not_found", "no such file")
        try:
            body = target.read_bytes()
            mtime = target.stat().st_mtime
        except OSError:
            raise ApiError(404, "not_found", "no such file") from None
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype == "application/json":
            ctype += "; charset=utf-8"
        self._send(200, body, ctype, LIVE_CACHE, {"Last-Modified": email.utils.formatdate(mtime, usegmt=True)})


def serve(db: Path, export_dir: Path | None, host: str, port: int, origins=DEFAULT_ORIGINS, devnet: Path | None = None,
          join=None, rebuild: bool = False, interval: float = 1.0, access_log: bool = False, log=print):
    follower, stop, thread = None, threading.Event(), None
    if devnet is not None:
        if rebuild:
            for p in (Path(db), Path(str(db) + "-wal"), Path(str(db) + "-shm"), Path(db).with_suffix(".replica")):
                p.unlink(missing_ok=True)
        follower = rm.Follower(devnet, db, export_dir, log=log)
        if join is not None:
            join.attach(follower)            # chain reads for remote bots come from the followed replica
        thread = threading.Thread(target=follower.run, args=(stop, interval), name="readmodel", daemon=True)
        thread.start()
    srv = Server((host, port), db, export_dir, origins, join=join, follower=follower, access_log=access_log)
    log(f"qdojo combat api on http://{host}:{srv.server_address[1]}{API}/ (db {db}, export {export_dir}, "
        f"join {'ON' if join else 'off'})")
    import signal

    def _stop(*_):
        threading.Thread(target=srv.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, _stop)
    try:
        srv.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if thread:
            thread.join(timeout=60)
        srv.server_close()
    return srv


def add_parser(s):
    d = s.add_parser("api", help="serve the read API and the static export; follow the arena journal")
    d.add_argument("--db", default=os.path.expanduser("~/.qdojo/combat/readmodel.sqlite"),
                   help="SQLite read model (created if missing)")
    d.add_argument("--export", help="static export directory (.../combat/v1), served on every non-API path")
    d.add_argument("--devnet", help="arena directory to follow; without it the server only reads --db")
    d.add_argument("--host", default="127.0.0.1")
    d.add_argument("--port", type=int, default=8790)
    d.add_argument("--cors-origin", action="append", help="allowed browser origin, repeatable "
                                                          f"(default {DEFAULT_ORIGINS[0]})")
    d.add_argument("--rebuild", action="store_true", help="drop the database and its snapshot, rebuild on start")
    d.add_argument("--interval", type=float, default=1.0, help="seconds between journal polls")
    d.add_argument("--access-log", action="store_true")
    d.add_argument("--join-inbox", help="ENABLE outside-builder writes: the arena's inbox database "
                                        "(off by default; docs/build-a-bot.md §8)")
    d.add_argument("--join-config", help="JSON file with join limits (see join.Limits)")
    d.set_defaults(fn=cmd_api)

    r = s.add_parser("readmodel", help="build the SQLite read model from an arena journal")
    r.add_argument("action", choices=("rebuild",))
    r.add_argument("--devnet", required=True, help="arena directory (holds devnet.journal)")
    r.add_argument("--db", default=os.path.expanduser("~/.qdojo/combat/readmodel.sqlite"))
    r.add_argument("--export", help="the arena's export directory, for names, drivers and ownership")
    r.set_defaults(fn=cmd_readmodel)


def cmd_api(a):
    import time
    join = None
    if a.join_inbox:
        if not a.devnet:
            raise SystemExit("qdojo: --join-inbox needs --devnet (chain reads come from the followed replica)")
        from . import join as J
        limits = J.Limits.load(Path(a.join_config)) if a.join_config else J.Limits()
        join = J.JoinService(Path(a.join_inbox), limits)
    serve(Path(a.db), Path(a.export) if a.export else None, a.host, a.port, a.cors_origin or DEFAULT_ORIGINS,
          devnet=Path(a.devnet) if a.devnet else None, join=join, rebuild=a.rebuild, interval=a.interval,
          access_log=a.access_log, log=lambda m: print(time.strftime("%H:%M:%S"), m, flush=True))


def cmd_readmodel(a):
    rm.rebuild(Path(a.devnet), Path(a.db), Path(a.export) if a.export else None)
