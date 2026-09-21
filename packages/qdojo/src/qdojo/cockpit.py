"""What `bot run` records for its owner, and how it is read back.

Three files in the state directory, written by bot run and nothing else:

* heartbeat.json -- rewritten every poll, removed on exit. Who is running
  (pid, when it started, the board, the solver), the last tick it saw, the
  rounds on the board and what it did about each, the last few action lines.
  A file that is there but old means the process died without cleaning up.
  That is reported as "stale", never as "running", and no signal is ever
  sent to the pid to find out: on Windows os.kill(pid, 0) terminates it.
* metrics.jsonl -- one line per round, appended each time something about
  that round is learned: seen, sat out and why, entered, the answer and how
  long the solver took, the commit and reveal ticks, and finally the verdict
  and what it paid once the house's history.json shows the settlement.
  Every line is the round's whole row as known at that moment, so the LAST
  line per round_id is the current row and the earlier ones are its history.
  A reader merges by round_id, last wins.
* bot.log -- what bot run printed, with a timestamp, rotated at 1 MB.

dash.py and `bot status | metrics | log` read these. Nothing here opens the
seed conf, and nothing here reads bot.json.
"""
import collections
import json
import logging
import logging.handlers
import os
import re
import time

HEARTBEAT = "heartbeat.json"
METRICS = "metrics.jsonl"
LOG = "bot.log"

STALE_MIN = 30.0            # seconds; a heartbeat older than max(this, 3 polls) is a dead bot
HISTORY_EVERY = 120.0       # seconds between looks at history.json while a round awaits settlement
LOG_BYTES = 1_000_000
LOG_KEEP = 3
KEEP_ACTIONS = 12
SOLVED = ("winner", "solved")
PAID = ("win", "bond_release")


def _now():
    return time.time()


def _write_json(path: str, doc: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def kind_of(title) -> str:
    """'White belt: sum the numbers' -> 'sum the numbers'. The belt is its
    own column. Digits stay: a title says SHA-256, not an instance number."""
    t = re.sub(r"^\s*\w+\s+belt\s*:\s*", "", str(title or ""), flags=re.I).lower()
    return re.sub(r"\s+", " ", t).strip()[:60]


# ---------------------------------------------------------------- heartbeat

def _brief(rd: dict) -> dict:
    r = rd.get("riddle") or {}
    return {"round_id": rd.get("round_id"), "belt": rd.get("belt"), "state": rd.get("state"),
            "title": r.get("title"), "kind": kind_of(r.get("title")) if r.get("title") else None,
            "publish_tick": rd.get("publish_tick"), "lobby_tick": rd.get("lobby_tick"),
            "commit_window": rd.get("commit_window"), "reveal_window": rd.get("reveal_window"),
            "entry_fee": rd.get("entry_fee"), "payout_mode": rd.get("payout_mode")}


class Heartbeat:
    """Written by bot run. `beat()` every poll, `close()` on the way out."""

    def __init__(self, state_dir: str, interval: float, board: str = "", solver=()):
        self.path = os.path.join(state_dir, HEARTBEAT)
        self.interval = float(interval)
        self.started = _now()
        self.pid = os.getpid()
        self.board = board
        self.solver = [os.path.basename(str(x)) for x in (solver or [])]
        self.actions = collections.deque(maxlen=KEEP_ACTIONS)
        self.rounds, self.tick, self.error, self.beats = [], None, None, 0

    def beat(self, board: dict | None = None, actions=(), error=None) -> None:
        now = _now()
        for a in actions:
            self.actions.append({"at": now, "text": str(a)})
        if board is not None:
            self.rounds = [_brief(rd) for rd in board.get("rounds", [])]
            self.tick = board.get("generated_tick")
        if error is not None:
            self.error = {"at": now, "text": str(error)[:300]}
        self.beats += 1
        _write_json(self.path, {"pid": self.pid, "started_at": self.started, "at": now, "beats": self.beats,
                                "interval": self.interval, "board": self.board, "solver": self.solver,
                                "tick": self.tick, "rounds": self.rounds, "last_actions": list(self.actions),
                                "last_error": self.error})

    def close(self) -> None:
        try:
            os.remove(self.path)
        except OSError:
            pass


def _did(mine: dict | None, row: dict | None) -> str:
    """What the bot did about a round, in one phrase, from rounds.json and
    the metrics row. rounds.json is the authority on what was SENT."""
    why = (row or {}).get("why") or ""
    if not mine:
        return why or "nothing yet"
    if mine.get("skipped"):
        return "sat out" + (f": {why}" if why else "")
    if mine.get("dead"):
        return "commit never landed, sitting out"
    if mine.get("reveal_tick"):
        return f"revealed for tick {mine['reveal_tick']}"
    if mine.get("commit_tick"):
        return f"committed for tick {mine['commit_tick']}" + (f", answer {mine['answer']!r}" if "answer" in mine else "")
    if mine.get("solver_failures"):
        return f"solver failed {mine['solver_failures']}x" + (f": {why}" if why else "")
    if mine.get("entered"):
        return "seated in the lobby, waiting for the riddle"
    return why or "nothing yet"


def status(state_dir: str, now: float | None = None) -> dict:
    """running / stale / idle, and the rounds the bot is looking at."""
    now = _now() if now is None else now
    hb = _read_json(os.path.join(state_dir, HEARTBEAT))
    played = _read_json(os.path.join(state_dir, "rounds.json"), {}) or {}
    rows = load_rows(os.path.join(state_dir, METRICS))
    out = {"state": "idle", "pid": None, "started_at": None, "heartbeat_at": None, "age": None,
           "interval": None, "board": None, "solver": [], "tick": None, "rounds": [], "last_actions": [],
           "last_error": None, "beats": 0}
    if isinstance(hb, dict) and hb.get("at"):
        age = max(0.0, now - float(hb["at"]))
        stale_after = max(STALE_MIN, 3 * float(hb.get("interval") or 0))
        out.update(state="stale" if age > stale_after else "running", pid=hb.get("pid"),
                   started_at=hb.get("started_at"), heartbeat_at=hb.get("at"), age=round(age, 1),
                   interval=hb.get("interval"), board=hb.get("board"), solver=hb.get("solver") or [],
                   tick=hb.get("tick"), last_actions=hb.get("last_actions") or [],
                   last_error=hb.get("last_error"), beats=hb.get("beats", 0))
        briefs = hb.get("rounds") or []
    else:
        # Nothing running: show the newest round this machine has a record of.
        newest = max((int(k) for k in played), default=None)
        briefs = [{"round_id": newest}] if newest is not None else []
        if newest is not None and rows.get(newest):
            r = rows[newest]
            briefs[0].update(belt=r.get("belt"), title=r.get("title"), kind=r.get("kind"))
    for b in briefs:
        rid = b.get("round_id")
        mine = played.get(str(rid))
        row = rows.get(int(rid)) if rid is not None else None
        out["rounds"].append({**b, "mine": mine, "did": _did(mine, row)})
    return out


# ----------------------------------------------------------------- metrics

def load_rows(path: str) -> dict:
    """{round_id: row}, last line per round wins. A torn last line (the
    process died mid-write) is skipped, not fatal."""
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and "round_id" in row:
                    out[int(row["round_id"])] = row
    except OSError:
        pass
    return out


class Recorder:
    """Given to Bot; `note()` is called at every decision. A line is appended
    only when something changed, so a poll that sees the same board twice
    writes nothing."""

    def __init__(self, state_dir: str):
        os.makedirs(state_dir, mode=0o700, exist_ok=True)
        self.path = os.path.join(state_dir, METRICS)
        self.rows = load_rows(self.path)

    def note(self, round_id: int, **fields) -> dict | None:
        rid = int(round_id)
        row = dict(self.rows.get(rid) or {"round_id": rid, "seen_at": _now(), "entered": False, "skipped": False})
        changed = rid not in self.rows
        for k, v in fields.items():
            if v is None:
                continue                          # never erase a fact with an absence
            if row.get(k) != v:
                row[k] = v
                changed = True
        if "title" in row and row.get("kind") != kind_of(row["title"]):
            row["kind"] = kind_of(row["title"])
            changed = True
        if not changed:
            return None
        row["at"] = _now()
        self.rows[rid] = row
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return row

    def pending(self) -> list[int]:
        """Rounds entered and not yet settled: the ones worth a look at history."""
        return sorted(rid for rid, r in self.rows.items() if r.get("entered") and not r.get("verdict"))

    def settle_from_history(self, history: dict, identity: str) -> list[dict]:
        """Fill verdict, earned, bond and net from the published settlement.
        Returns the rows it completed."""
        done = []
        want = set(self.pending())
        for rd in history.get("rounds", []):
            rid = rd.get("round_id")
            if rid not in want or rd.get("state") not in ("settled", "void"):
                continue
            doc = rd.get("settlement") or {}
            mine = next((e for e in rd.get("entries", []) if e.get("identity") == identity), None)
            verdict = (mine or {}).get("verdict") or "absent"
            earned = sum(int(p.get("amount") or 0) for p in doc.get("payouts", [])
                         if p.get("identity") == identity and p.get("kind") in PAID)
            refunded = sum(int(p.get("amount") or 0) for p in doc.get("payouts", [])
                           if p.get("identity") == identity and p.get("kind") == "refund")
            bond = sum(int(b.get("amount") or 0) for b in doc.get("bonds_held", []) if b.get("identity") == identity)
            stake = int((mine or {}).get("stake") or self.rows[rid].get("stake") or 0)
            row = self.note(rid, verdict=verdict, earned=earned, refunded=refunded, bond_held=bond,
                            net=earned + refunded + bond - stake, stake=stake, truth=doc.get("answer"),
                            settle_tick=doc.get("settle_tick"), belt=rd.get("belt"),
                            title=(rd.get("riddle") or {}).get("title"),
                            publish_tick=rd.get("publish_tick"))
            done.append(row or self.rows[rid])
        return done


def summary(state_dir: str, last: int = 20) -> dict:
    """The numbers the cockpit and `bot metrics` show. Solve rate is over
    SETTLED rounds the bot entered; a round still open is pending, not a
    miss. Solve time is the solver's wall time on every round it answered."""
    rows = sorted(load_rows(os.path.join(state_dir, METRICS)).values(), key=lambda r: int(r["round_id"]))
    entered = [r for r in rows if r.get("entered")]
    settled = [r for r in entered if r.get("verdict")]
    solved = [r for r in settled if r.get("verdict") in SOLVED]
    wins = [r for r in settled if r.get("verdict") == "winner"]
    times = [float(r["solver_seconds"]) for r in rows if r.get("solver_seconds") is not None and r.get("answer") is not None]

    def rate(n, d):
        return round(n / d, 2) if d else None

    streak, best, run = 0, 0, 0
    for r in settled:                              # oldest to newest, so `run` ends at the current streak
        if r.get("verdict") in SOLVED:
            run = run + 1 if run >= 0 else 1
            best = max(best, run)
        else:
            run = run - 1 if run <= 0 else -1
    streak = run

    def bucket(key):
        out = {}
        for r in rows:
            k = r.get(key) or "?"
            b = out.setdefault(k, {"seen": 0, "entered": 0, "settled": 0, "solved": 0, "wins": 0, "net": 0})
            b["seen"] += 1
            if r.get("entered"):
                b["entered"] += 1
            if r.get("entered") and r.get("verdict"):
                b["settled"] += 1
                b["net"] += int(r.get("net") or 0)
                if r.get("verdict") in SOLVED:
                    b["solved"] += 1
                if r.get("verdict") == "winner":
                    b["wins"] += 1
        for b in out.values():
            b["solve_rate"] = rate(b["solved"], b["settled"])
        return out

    series, total = [], 0
    for r in settled:
        total += int(r.get("net") or 0)
        series.append([int(r["round_id"]), total])
    return {
        "rounds_seen": len(rows), "entered": len(entered), "skipped": sum(1 for r in rows if r.get("skipped")),
        "settled": len(settled), "pending": len(entered) - len(settled),
        "solved": len(solved), "wins": len(wins), "solve_rate": rate(len(solved), len(settled)),
        "win_rate": rate(len(wins), len(settled)),
        "solver_failed": sum(1 for r in rows if r.get("solver_failures")),
        "avg_solve_seconds": round(sum(times) / len(times), 2) if times else None,
        "best_solve_seconds": round(min(times), 2) if times else None,
        "staked": sum(int(r.get("stake") or 0) for r in settled),
        "earned": sum(int(r.get("earned") or 0) for r in settled),
        "refunded": sum(int(r.get("refunded") or 0) for r in settled),
        "bond_held": sum(int(r.get("bond_held") or 0) for r in settled),
        "net": total, "streak": streak, "best_streak": best,
        "by_kind": bucket("kind"), "by_belt": bucket("belt"),
        "net_series": series,
        "last": list(reversed(rows[-last:])) if last else [],
    }


# --------------------------------------------------------------------- log

class _PrivateRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Created 0600 like the other diary files (heartbeat.json, metrics.jsonl,
    rounds.json). `_open` is what FileHandler's constructor AND doRollover
    both call, so the live file and every rotated-in file get the mode; the
    chmod also tightens a bot.log an earlier, unfixed run already left at
    whatever the umask gave it."""
    def _open(self):
        fd = os.open(self.baseFilename, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.chmod(self.baseFilename, 0o600)
        except OSError:
            pass
        return os.fdopen(fd, self.mode, encoding=self.encoding, errors=self.errors)


def open_log(state_dir: str) -> logging.Logger:
    """A plain-text log in the state dir, rotated at LOG_BYTES. The logger
    does not propagate, so nothing is printed twice.

    bot.log carries every action line, including a failing solver's stderr
    tail (see bot.py / solver.py) -- the same text metrics.jsonl and
    heartbeat.json store at 0600. It is created 0600 here too, matching the
    rest of the diary."""
    os.makedirs(state_dir, mode=0o700, exist_ok=True)
    log = logging.getLogger(f"qdojo.bot.{os.path.abspath(state_dir)}")
    log.setLevel(logging.INFO)
    log.propagate = False
    if not log.handlers:
        h = _PrivateRotatingFileHandler(os.path.join(state_dir, LOG), maxBytes=LOG_BYTES,
                                        backupCount=LOG_KEEP, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        log.addHandler(h)
    return log


def log_tail(state_dir: str, n: int = 50) -> list[str]:
    """The last n lines of the current log file. Reads the tail of the file,
    not the file, so a log near the rotation limit is still cheap."""
    path = os.path.join(state_dir, LOG)
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - 256 * 1024))
            data = f.read()
    except OSError:
        return []
    lines = data.decode("utf-8", "replace").splitlines()
    if size > 256 * 1024 and lines:
        lines = lines[1:]                            # the first line is probably torn
    return lines[-n:] if n else lines
