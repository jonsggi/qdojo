"""Your fighter's cockpit, on your own machine.

The spectator site shows everyone. This shows you: whether your bot is
running and what it is doing about the round on the board, the metrics it
recorded for you, its settings, the record the house publishes about your
identity, the rounds this machine actually played, the training fights that
never touched the chain -- and your prompt files, which you can edit here and
have live on the next round.

THIS WRITES FILES TO DISK FROM A BROWSER. That is the whole risk, so:

* It binds 127.0.0.1 and there is deliberately NO flag to change that. The
  moment such a flag exists somebody sets it to 0.0.0.0 "just to check from my
  phone" and has published an unauthenticated file editor.
* There is no generic static handler. Four literal URLs map to four files
  resolved at startup. No request path is ever turned into a path to read.
* Two things can be written, and neither is a path. A prompt: edit only, .md
  only, and the write must land inside the prompts directory's realpath, so a
  symlink planted there cannot escape. A setting: one key the solver's
  manifest knows, checked by settings.py, into bot.json's solver_env or
  secret_env -- a secret setting is the NAME of a variable, and a value with
  the shape of a key is refused.
* It refuses to start if the prompts directory contains a seed conf.
* No create, no delete, no upload. A file the solver never reads would be a
  trap for the user.
* A per-run token, a Host check, no Access-Control-Allow-* header on any
  response, and a body-size cap. Together those stop a page in another tab
  writing your prompts or your settings.
* The state directory is never a route. This module opens no .conf. It reads
  the profile for the identity, the name, the model and the solver argv; the
  settings rows it serves carry stored values (never a key: check_no_secrets
  guards that store) and, for a secret, the variable's name and whether it
  is set in this process's environment -- never what it holds. The
  heartbeat, the metrics and the log tail are read through cockpit.py, and
  the log carries what bot run printed, including a failing solver's stderr.
"""
import hmac
import html
import json
import os
import re
import secrets
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import cockpit, portable, prompts as P, settings as SETTINGS, wizard

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.md$")
MAX_BODY = 65536
BOARD_TTL = 60.0


class DashError(Exception):
    pass


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def prompts_root(state_dir: str) -> str:
    """The one writable directory, and it must not be holding a seed."""
    for d in P.search_path(state_dir):
        if os.path.isdir(d):
            root = os.path.realpath(d)
            break
    else:
        raise DashError("no prompts directory yet; run `qdojo prompts install`")
    if any(f.endswith(".conf") for f in os.listdir(root)):
        raise DashError(f"refusing to serve {root}: it holds a .conf, and a prompts directory "
                        f"must never share a directory with a seed")
    return root


class Fighter:
    """Everything the page shows, gathered in Python so the browser never has
    to reach across origins -- and so the seed is never on a route."""

    def __init__(self, state_dir: str, board: str = ""):
        self.state = os.path.abspath(os.path.expanduser(state_dir))
        self.board = board
        self.root = prompts_root(self.state)
        self._cache = (0.0, None)

    def profile(self) -> dict:
        p = _read_json(os.path.join(self.state, "bot.json"), {}) or {}
        # Only ever these. key_source is the NAME of a place, never a value.
        return {k: p.get(k) for k in ("identity", "name", "provider", "model", "key_source")}

    def training(self) -> dict:
        return _read_json(os.path.join(self.state, "training.json"), {}) or {}

    # ---- the cockpit: status, metrics, settings, log (cockpit.py, settings.py)

    def status(self) -> dict:
        return cockpit.status(self.state)

    def metrics(self) -> dict:
        return cockpit.summary(self.state, last=40)

    def settings(self) -> dict:
        """The merged manifest with current values. A secret row carries the
        NAME of the variable and whether it is set, never its value."""
        return SETTINGS.describe(self.state, wizard.load_profile(self.state))

    def set_setting(self, key, value) -> dict:
        if not isinstance(key, str) or not SETTINGS.KEY_RE.match(key):
            raise DashError("that is not a setting key")
        if not isinstance(value, (str, int, float, bool)):
            raise DashError("a value is a string, a number or a boolean")
        if isinstance(value, str) and len(value) > SETTINGS.MAX_VALUE:
            raise DashError("that is too long for a setting")
        try:
            return SETTINGS.set_value(self.state, key, value)
        except SETTINGS.SettingsError as e:
            raise DashError(str(e))

    def unset_setting(self, key) -> None:
        if not isinstance(key, str) or not SETTINGS.KEY_RE.match(key):
            raise DashError("that is not a setting key")
        try:
            SETTINGS.unset_value(self.state, key)
        except SETTINGS.SettingsError as e:
            raise DashError(str(e))

    def log_tail(self, n) -> list:
        try:
            n = max(1, min(int(n or 50), 500))
        except (TypeError, ValueError):
            n = 50
        return cockpit.log_tail(self.state, n)

    def local_rounds(self) -> list:
        rounds = _read_json(os.path.join(self.state, "rounds.json"), {}) or {}
        out = []
        for rid, r in sorted(rounds.items(), key=lambda kv: -int(kv[0])):
            out.append({"round_id": int(rid), "entered": bool(r.get("entered")),
                        "skipped": bool(r.get("skipped")), "stake": r.get("stake"),
                        "answer": r.get("answer"), "commit_tick": r.get("commit_tick"),
                        "reveal_tick": r.get("reveal_tick"),
                        "solver_failures": r.get("solver_failures", 0)})
        return out[:40]

    def house_row(self) -> dict | None:
        """This identity's row from the house's fighters.json, fetched here
        because a browser on 127.0.0.1 cannot read a foreign origin."""
        import time
        idn = (self.profile() or {}).get("identity")
        if not idn or not self.board:
            return None
        now = time.time()
        if self._cache[1] is not None and now - self._cache[0] < BOARD_TTL:
            rows = self._cache[1]
        else:
            url = portable.sibling(self.board, "fighters.json")
            try:
                if url.startswith(("http://", "https://")):
                    with urllib.request.urlopen(url, timeout=10) as r:
                        doc = json.loads(r.read().decode("utf-8"))
                else:
                    doc = _read_json(url, {})
                rows = (doc or {}).get("fighters", [])
            except (urllib.error.URLError, OSError, ValueError):
                rows = self._cache[1] or []
            self._cache = (now, rows)
        return next((f for f in rows if f.get("identity") == idn), None)

    def prompt_list(self) -> list:
        out = []
        for r in P.listing(self.state):
            out.append({"name": r["name"], "mine": os.path.realpath(r["dir"]) == self.root,
                        "bytes": r["bytes"]})
        return out

    def prompt_text(self, name: str) -> str:
        if not NAME_RE.match(name or ""):
            raise DashError("that is not a prompt name")
        path = P.find(name, self.state)
        with open(path, encoding="utf-8") as f:
            return f.read()

    def save_prompt(self, name: str, text: str) -> str:
        """Edit only, inside the prompts root, .md only, realpath-checked."""
        if not NAME_RE.match(name or ""):
            raise DashError("that is not a prompt name")
        if len(text) > MAX_BODY:
            raise DashError("that is too long for a prompt")
        target = os.path.realpath(os.path.join(self.root, name))
        if os.path.dirname(target) != self.root:
            raise DashError("outside the prompts directory")
        if not os.path.exists(target):
            raise DashError(f"{name} is not one of your prompts; `qdojo prompts install` first")
        P.check(name, P.body(text), target)          # do not let an edit break the parser contract
        with open(target + ".bak", "w", encoding="utf-8") as f:
            f.write(open(target, encoding="utf-8").read())
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, target)
        return target


def make_handler(fighter: Fighter, token: str, port: int, assets: dict, read_only: bool):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class H(BaseHTTPRequestHandler):
        server_version = "qdojo"

        def log_message(self, *a):
            pass

        def _head(self, code, ctype, n):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(n))
            # No Access-Control-Allow-* on any response, ever: a cross-origin
            # write is then impossible even if the token leaked.
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                             "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()

        def _send(self, code, ctype, body):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self._head(code, ctype, len(body))
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, "application/json", json.dumps(obj))

        def _ok_host(self):
            # A DNS-rebound request arrives carrying the attacker's hostname.
            return (self.headers.get("Host") or "") in hosts

        def _ok_token(self, given):
            return hmac.compare_digest(given or "", token)

        def do_OPTIONS(self):
            self._send(405, "text/plain", "no")      # force a preflight failure

        def do_GET(self):
            if not self._ok_host():
                return self._send(403, "text/plain", "not a loopback host")
            path, _, query = self.path.partition("?")
            q = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
            if path in assets:
                ctype, data = assets[path]
                return self._send(200, ctype, data)
            if not self._ok_token(q.get("t")):
                return self._send(403, "text/plain", "this page needs the link the command printed")
            if path == "/api/fighter":
                return self._json(200, {"profile": fighter.profile(), "house": fighter.house_row(),
                                        "training": fighter.training(), "rounds": fighter.local_rounds(),
                                        "prompts": fighter.prompt_list(), "read_only": read_only})
            if path == "/api/prompt":
                try:
                    return self._json(200, {"name": q.get("name"), "text": fighter.prompt_text(q.get("name", ""))})
                except (DashError, P.PromptError) as e:
                    return self._json(400, {"error": str(e)})
            if path == "/api/status":
                return self._json(200, fighter.status())
            if path == "/api/metrics":
                return self._json(200, fighter.metrics())
            if path == "/api/settings":
                try:
                    return self._json(200, {**fighter.settings(), "read_only": read_only})
                except SETTINGS.SettingsError as e:
                    return self._json(200, {"error": str(e), "settings": [], "read_only": read_only})
            if path == "/api/log":
                return self._json(200, {"lines": fighter.log_tail(q.get("n"))})
            return self._send(404, "text/plain", "no")

        def do_PUT(self):
            if not self._ok_host():
                return self._send(403, "text/plain", "not a loopback host")
            if read_only:
                return self._json(403, {"error": "started with --read-only"})
            if not self._ok_token(self.headers.get("X-QDojo-Token")):
                return self._json(403, {"error": "bad token"})
            if self.headers.get("Transfer-Encoding"):
                return self._json(411, {"error": "send a Content-Length"})
            try:
                n = int(self.headers.get("Content-Length") or "")
            except ValueError:
                return self._json(411, {"error": "send a Content-Length"})
            if n > MAX_BODY:
                return self._json(413, {"error": "too long"})
            try:
                doc = json.loads(self.rfile.read(n).decode("utf-8"))
                if not isinstance(doc, dict):
                    raise ValueError("expected an object")
            except (ValueError, TypeError) as e:
                return self._json(400, {"error": f"bad body: {e}"})
            route = self.path.partition("?")[0]
            if route == "/api/settings":
                try:
                    if doc.get("unset"):
                        fighter.unset_setting(doc.get("key"))
                        return self._json(200, {"unset": doc.get("key"), "live": "next poll"})
                    row = fighter.set_setting(doc.get("key"), doc.get("value"))
                except DashError as e:
                    return self._json(400, {"error": str(e)})
                return self._json(200, {"saved": row["key"], "row": row, "live": "next poll"})
            if route != "/api/prompt":
                return self._send(404, "text/plain", "no")
            try:
                name, text = doc["name"], doc["text"]
                if not isinstance(text, str):
                    raise ValueError("text must be a string")
            except (ValueError, KeyError, TypeError) as e:
                return self._json(400, {"error": f"bad body: {e}"})
            try:
                path = fighter.save_prompt(name, text)
            except (DashError, P.PromptError) as e:
                return self._json(400, {"error": str(e)})
            return self._json(200, {"saved": os.path.basename(path), "live": "next round"})

    return H


def serve(state_dir: str, board: str = "", port: int = 7777, read_only: bool = False,
          asset_dir: str = "") -> tuple:
    """(httpd, url). Caller runs serve_forever."""
    fighter = Fighter(state_dir, board)
    token = secrets.token_hex(16)
    assets = _assets(asset_dir)

    # Bind FIRST, then build the handler: the Host allow-list needs the real
    # port, and with --port 0 (or a port already in use) we do not know it until
    # the socket exists. Getting this backwards made every request fail the
    # Host check, which is exactly the sort of bug the check exists to cause.
    class _Later(BaseHTTPRequestHandler):
        def handle(self):                      # replaced below, before any request
            pass

    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), _Later)
    except OSError:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Later)
    port = httpd.server_address[1]
    httpd.RequestHandlerClass = make_handler(fighter, token, port, assets, read_only)
    httpd.daemon_threads = True
    return httpd, f"http://127.0.0.1:{port}/?t={token}"


def _assets(asset_dir: str) -> dict:
    """Four literal URLs, four files resolved now. No request path is ever
    turned into a filesystem path."""
    d = asset_dir or _web_dir()
    out = {}
    for url, fn, ctype in (("/", "dash.html", "text/html; charset=utf-8"),
                           ("/dash.js", "dash.js", "text/javascript"),
                           ("/style.css", "style.css", "text/css"),
                           ("/avatars.js", "avatars.js", "text/javascript")):
        path = os.path.join(d, fn)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                out[url] = (ctype, f.read())
    if "/" not in out:
        raise DashError(f"dash.html not found in {d}")
    return out


def _web_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "..", "..", "..", "..", "apps", "web"),
                 os.path.join(os.getcwd(), "apps", "web")):
        if os.path.isdir(cand):
            return os.path.abspath(cand)
    return os.path.abspath(os.path.join(here, "..", "..", "..", "..", "apps", "web"))
