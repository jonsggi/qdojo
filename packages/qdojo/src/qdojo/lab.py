"""Publishable statistics about the self-evolving fighters' toolboxes.

Every `evo.py` bot keeps one generated Python tool per riddle kind under
$EVO_DIR/tools/, a snapshot beside it on each rewrite, and a line-per-round
evo.log. That tree is the only record of how the dojo's kinds were actually
learned: how many rewrites a kind cost, how many rounds passed before a belt
fell, and whether independently prompted bots converged on the same program.

The tools themselves are never published. A tool IS the answer — shipping one
hands every future opponent a solved belt — and the sources carry model
prompts and the absolute paths of the box they ran on. So this module emits
counts, rounds, sizes and a truncated sha256 fingerprint; the fingerprint
alone answers "did they write the same program?" without showing it. No
source, no path, no prompt ever reaches the returned dict.

Dates are deliberately absent. evo.log carries HH:MM:SS with no date and
wraps past midnight, so rounds are the clock here; the `.v<unix_ts>` snapshot
names are the only wall-clock facts in the tree.
"""
import hashlib
import json
import os
import re
import statistics
from datetime import datetime, timezone

DEFAULT_EVO_DIR = "~/.qdojo/evo"
ANSWER_FORMATS = ("integer", "string", "hex")
NOTE = "Summaries and statistics only. No tool source is published."

# "20:41:41 round 112 white_belt_sum_the_numbers_integer: -1533", optionally
# "learned round N". Keys never contain a space or a colon.
_LINE = re.compile(r"^(\d\d:\d\d:\d\d) (learned )?round (\d+) (\S+?): (.*)$")
_PATH = re.compile(r"/[\w./-]+")
_SNAPSHOT = re.compile(r"^(.+)\.py\.v(\d+)$")


def scrub(text: str) -> str:
    """Drop anything path-shaped, keep the exception class and message."""
    return re.sub(r"\s+", " ", _PATH.sub("", text)).strip()


def find_evo_dirs(root: str | None = None) -> list[str]:
    root = os.path.expanduser(root or os.environ.get("QDOJO_EVO_DIR") or DEFAULT_EVO_DIR)
    if os.path.isdir(os.path.join(root, "tools")):
        return [root]                      # the root is itself one bot
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    out = []
    for name in names:
        path = os.path.join(root, name)
        if os.path.isdir(path) and (os.path.isdir(os.path.join(path, "tools"))
                                    or os.path.isfile(os.path.join(path, "evo.log"))):
            out.append(path)
    return out


def parse_log(text: str) -> list[dict]:
    """One record per logged round. A line without a timestamp is the spill of
    a traceback from the line before — it carries paths and tool source, so it
    is dropped whole rather than parsed."""
    out = []
    for line in text.splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        hms, learned, round_id, key, rest = m.groups()
        rec = {"hms": hms, "kind": "solve", "round_id": int(round_id), "key": key}
        if learned:
            rec["kind"] = "learn"
            rec["value"] = scrub(rest)
        elif rest.startswith("no answer"):
            rec["kind"] = "fail"
            rec["error_head"] = scrub(_error_head(rest))
        else:
            rec["value"] = _value(rest)
        out.append(rec)
    return out


def _error_head(rest: str) -> str:
    head = rest[len("no answer"):].strip().removeprefix("(")
    if head.endswith(")") and head.count("(") < head.count(")"):
        head = head[:-1]
    return head[:200]


def _value(rest: str):
    s = rest.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1]
    try:
        return int(s)
    except ValueError:
        return s


def belt_of(key: str) -> str | None:
    return key.split("_belt_")[0] if "_belt_" in key else None


def format_of(key: str) -> str | None:
    tail = key.rsplit("_", 1)[-1]
    return tail if tail in ANSWER_FORMATS else None


def read_bot(path: str, identity: str | None = None, model: str | None = None) -> dict:
    name = os.path.basename(os.path.normpath(path))
    meta = _read_json(os.path.join(path, "bot.json"))
    records = parse_log(_read_text(os.path.join(path, "evo.log")))
    tools, snaps = _read_tools(os.path.join(path, "tools"))

    kinds = {}
    for key in sorted(set(tools) | set(snaps) | {r["key"] for r in records}):
        mine = [r for r in records if r["key"] == key]
        rounds = [r["round_id"] for r in mine]
        repairs = [r["round_id"] for r in mine if r["kind"] == "learn"]
        size, fingerprint = tools.get(key, (None, None))
        stamps = sorted(snaps.get(key, ()))
        kinds[key] = {
            "belt": belt_of(key),
            "answer_format": format_of(key),
            # evo.py writes a snapshot and the live file on every write, so the
            # snapshot count already is the number of times the tool was written.
            "revisions": len(stamps),
            "first_ts": stamps[0] if stamps else None,
            "last_ts": stamps[-1] if stamps else None,
            "bytes": size,
            "fingerprint": fingerprint,
            "solved": sum(r["kind"] == "solve" for r in mine),
            "failed": sum(r["kind"] == "fail" for r in mine),
            "repairs": len(repairs),
            # the round the kind was first met, which is when its tool was written
            "learned_round": min(rounds) if rounds else None,
            "last_repair_round": max(repairs) if repairs else None,
        }

    rounds = [r["round_id"] for r in records]
    belts = {}
    for key, k in kinds.items():
        if k["belt"] is None:
            continue
        b = belts.setdefault(k["belt"], {"kinds": 0, "solves": 0, "failures": 0, "first_solve_round": None})
        b["kinds"] += 1
        b["solves"] += k["solved"]
        b["failures"] += k["failed"]
    for r in records:
        b = belts.get(belt_of(r["key"]))
        if b is not None and r["kind"] == "solve":
            if b["first_solve_round"] is None or r["round_id"] < b["first_solve_round"]:
                b["first_solve_round"] = r["round_id"]

    return {
        "name": (meta.get("name") if meta else None) or name,
        "identity": identity or (meta.get("identity") if meta else None),
        "model": model or (meta.get("model") if meta else None),
        "tool_count": len(tools),
        "snapshot_count": sum(len(v) for v in snaps.values()),
        "kinds": kinds,
        "solves": sum(r["kind"] == "solve" for r in records),
        "failures": sum(r["kind"] == "fail" for r in records),
        "repairs": sum(r["kind"] == "learn" for r in records),
        "first_round": min(rounds) if rounds else None,
        "last_round": max(rounds) if rounds else None,
        "rounds_seen": len(set(rounds)),
        "day_rollovers": _rollovers(records),
        "belts": {b: belts[b] for b in sorted(belts)},
    }


def _rollovers(records) -> int:
    """The log has no dates; a clock that goes backwards is a new day."""
    stamps = [r["hms"] for r in records]
    return sum(b < a for a, b in zip(stamps, stamps[1:]))


def _read_tools(tools_dir):
    tools, snaps = {}, {}
    try:
        names = os.listdir(tools_dir)
    except OSError:
        return tools, snaps
    for name in names:
        m = _SNAPSHOT.match(name)
        if m:
            snaps.setdefault(m.group(1), []).append(int(m.group(2)))
        elif name.endswith(".py"):
            data = _read_bytes(os.path.join(tools_dir, name))
            if data is not None:
                tools[name[:-3]] = (len(data), hashlib.sha256(data).hexdigest()[:16])
    return tools, snaps


def _read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _read_text(path):
    data = _read_bytes(path)
    return data.decode("utf-8", "replace") if data else ""


def _read_json(path):
    try:
        return json.loads(_read_text(path))
    except (ValueError, OSError):
        return None


def aggregate(bots: list[dict]) -> dict:
    by_key = {}
    for b in bots:
        for key, k in b["kinds"].items():
            by_key.setdefault(key, []).append(k)

    taxonomy = []
    for key in sorted(by_key):
        ks = by_key[key]
        revs = [k["revisions"] for k in ks]
        stamps = [k["first_ts"] for k in ks if k["first_ts"] is not None]
        taxonomy.append({
            "key": key,
            "belt": belt_of(key),
            "answer_format": format_of(key),
            "bots": len(ks),
            "avg_revisions": round(statistics.fmean(revs), 2),
            "min_revisions": min(revs),
            "max_revisions": max(revs),
            # the headline: how many genuinely different programs the bots wrote
            "distinct_implementations": len({k["fingerprint"] for k in ks if k["fingerprint"]}),
            "first_ts": min(stamps) if stamps else None,
            "solved": sum(k["solved"] for k in ks),
            "failed": sum(k["failed"] for k in ks),
        })

    by_belt = {}
    for t in taxonomy:
        if t["belt"] is None:
            continue    # a key with no "_belt_" in it belongs to no belt ladder
        by_belt.setdefault(t["belt"], {"kinds": 0, "bots_that_solved": 0,
                                       "median_rounds_to_first_solve": None,
                                       "min_rounds_to_first_solve": None,
                                       "avg_revisions": 0.0, "repairs": 0, "failures": 0})["kinds"] += 1
    for belt, row in by_belt.items():
        revs = [k["revisions"] for b in bots for k in b["kinds"].values() if k["belt"] == belt]
        row["avg_revisions"] = round(statistics.fmean(revs), 2) if revs else 0.0
        row["repairs"] = sum(k["repairs"] for b in bots for k in b["kinds"].values() if k["belt"] == belt)
        row["failures"] = sum(k["failed"] for b in bots for k in b["kinds"].values() if k["belt"] == belt)
        # time to first solve is counted in ROUNDS from the bot's own first round
        spans = [b["belts"][belt]["first_solve_round"] - b["first_round"]
                 for b in bots
                 if belt in b["belts"] and b["belts"][belt]["first_solve_round"] is not None]
        row["bots_that_solved"] = len(spans)
        if spans:
            row["median_rounds_to_first_solve"] = round(statistics.median(spans), 1)
            row["min_rounds_to_first_solve"] = min(spans)

    n = len(bots)
    counts = [t["bots"] for t in taxonomy]
    return {
        "convergence": {
            "keys_total": len(by_key),
            "keys_all_bots": sum(c == n for c in counts) if n else 0,
            "keys_one_bot": sum(c == 1 for c in counts),
            "mean_bots_per_kind": round(statistics.fmean(counts), 2) if counts else 0.0,
        },
        "taxonomy": taxonomy,
        "by_belt": {b: by_belt[b] for b in sorted(by_belt)},
    }


def build(root: str | None = None, identities: dict | None = None,
          models: dict | None = None, now_tick: int | None = None) -> dict:
    """The lab.json document. Deterministic for a given tree but for
    generated_at."""
    identities, models = identities or {}, models or {}
    bots = []
    for path in find_evo_dirs(root):
        name = os.path.basename(os.path.normpath(path))
        bots.append(read_bot(path, identities.get(name), models.get(name)))
    bots.sort(key=lambda b: b["name"])
    agg = aggregate(bots)
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_tick": now_tick,
        "note": NOTE,
        "totals": {
            "bots": len(bots),
            "kinds": agg["convergence"]["keys_total"],
            "tools": sum(b["tool_count"] for b in bots),
            "snapshots": sum(b["snapshot_count"] for b in bots),
            "solves": sum(b["solves"] for b in bots),
            "failures": sum(b["failures"] for b in bots),
            "repairs": sum(b["repairs"] for b in bots),
        },
        "convergence": agg["convergence"],
        "taxonomy": agg["taxonomy"],
        "by_belt": agg["by_belt"],
        "bots": bots,
    }
