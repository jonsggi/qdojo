"""Instruments for the builder beta and the human validation study
(docs/validation-protocol.md, AUD-038 and AUD-039).

Three measurements, each aggregate-only:

- readability: sample decisive exchanges from finished replays into review
  sheets with an answer key derived from the engine's own per-beat detail
  (reason codes, intended vs effective action, HP lost), then score reviewers'
  answers against the key (model.md §3: causes of at least 8 of 10);
- cohort: summarise the manual cohort log (one row per pseudonymous
  participant) with drop-offs in every denominator;
- adaptation: a builder fighter's score against an opponent before and after
  that opponent changes style (model.md §2, "adaptation time and the cost of
  stale assumptions").

Inputs are public replays, the read model and a log the study team keeps.
The log holds pseudonyms (P01, R01), never names, contacts or addresses, and
every report prints counts, rates and distributions, never a row.
"""
from __future__ import annotations

import csv
import json
import random
import statistics
from datetime import datetime
from math import sqrt
from pathlib import Path

# ---- readability ---------------------------------------------------------------------

# Causes a reviewer picks from (the sheet lists them with one-line descriptions).
CAUSES = {
    "last_stand": "A LAST STAND landed or was stopped (stand bonus, a trailing fighter's power strike)",
    "feint_guard_break": "A FEINT baited a guard, or a guard broke or strained",
    "resource_failure": "A fighter lacked stamina or power (EXHAUSTED, insufficient stamina, power wasted)",
    "simultaneous_trade": "Both fighters lost HP in the same beat (a trade, a throw clash, a double KO)",
    "opening_punish": "An earned opening or a punished recovery added damage",
    "block_evade": "A block, duck or evade stopped or interrupted the attack",
    "clean_hit": "A plain hit with nothing else going on",
    "forfeit": "A fighter failed to commit or reveal and forfeited",
}
# Categories the protocol requires in every reviewer's set of ten (docs/model.md §3, AUD-038).
REQUIRED = ("last_stand", "feint_guard_break", "resource_failure", "simultaneous_trade", "forfeit")
REDUCED_MOTION_PER_SET = 2
GATE_CORRECT, GATE_OF = 8, 10


def beat_causes(beat: dict) -> list[str]:
    """The cause categories one beat's engine detail supports (never empty)."""
    out: list[str] = []
    sides = [beat[s] for s in ("A", "B") if s in beat]
    reasons = {r for x in sides for r in x.get("reasons", [])}
    eff = {x.get("effective") for x in sides}
    if "LAST_STAND" in eff or "STAND_BONUS" in reasons:
        out.append("last_stand")
    if reasons & {"FEINT_BAITED", "GUARD_BROKEN", "GUARD_STRAIN"} or "FEINT" in eff:
        out.append("feint_guard_break")
    if "EXHAUSTED" in eff or reasons & {"INSUFFICIENT_STAMINA", "POWER_WASTED"}:
        out.append("resource_failure")
    if all(x.get("actual_hp_lost", 0) > 0 for x in sides) or reasons & {"THROW_CLASH", "DOUBLE_KO"}:
        out.append("simultaneous_trade")
    if reasons & {"OPENING_USED", "RECOVERY_PUNISHED"}:
        out.append("opening_punish")
    if reasons & {"BLOCKED", "EVADED", "THROW_INTERRUPTED"}:
        out.append("block_evade")
    if not out:
        out.append("clean_hit")
    return out


def _describe(beat: dict) -> str:
    parts = []
    for s in ("A", "B"):
        x = beat[s]
        act = x["intended"] if x["intended"] == x["effective"] else f"{x['intended']} (became {x['effective']})"
        parts.append(f"{s} {act}, lost {x.get('actual_hp_lost', 0)} HP"
                     + (f" [{', '.join(x['reasons'])}]" if x.get("reasons") else ""))
    return "; ".join(parts)


def decisive_exchange(replay: dict) -> dict | None:
    """The exchange that decided a finished fight, or None for draws and unfinished fights.

    A forfeit: the round it happened in. A knockout: the beat that ended it.
    A decision on HP: the beat with the largest HP swing towards the winner."""
    res = replay.get("result") or {}
    fid = str(replay.get("fight_id"))
    if res.get("kind") == "FORFEIT":
        rnd = replay.get("forfeit_round")
        loser = "B" if res.get("winner") == "A" else "A"
        return {"fight_id": fid, "round": int(rnd) + 1 if rnd is not None else None, "beat": None,
                "causes": ["forfeit"], "key": f"{loser} did not commit or reveal its plan in time and forfeited"}
    if res.get("kind") != "COMBAT" or (res.get("winner") not in ("A", "B") and res.get("result") != "DOUBLE_KO"):
        return None
    best = None
    win = res.get("winner")
    for r in replay.get("rounds") or []:
        for b in r.get("beats") or []:
            if not all(s in b for s in ("A", "B")):
                continue
            reasons = set(b["A"].get("reasons", [])) | set(b["B"].get("reasons", []))
            if res.get("result") in ("KO", "DOUBLE_KO") and reasons & {"KO", "DOUBLE_KO"}:
                best = (float("inf"), r, b)
                break
            lost = {s: b[s].get("actual_hp_lost", 0) for s in ("A", "B")}
            swing = (lost["B"] - lost["A"]) if win == "A" else (lost["A"] - lost["B"])
            if best is None or swing > best[0]:
                best = (swing, r, b)
        if best and best[0] == float("inf"):
            break
    if best is None:
        return None
    _, r, b = best
    return {"fight_id": fid, "round": int(r["round_index"]) + 1, "beat": int(b["beat"]) + 1,
            "causes": beat_causes(b), "key": _describe(b)}


def load_replays(export_dir: Path) -> list[dict]:
    """Every finished replay in an export directory (fights/<id>/replay.json)."""
    out = []
    for p in sorted(Path(export_dir).glob("fights/*/replay.json")):
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if d.get("final"):
            out.append(d)
    return out


def sample_sheets(replays: list[dict], reviewers: int, seed: int = 0, per_set: int = GATE_OF) -> dict:
    """One set of `per_set` decisive exchanges per reviewer, each covering the
    REQUIRED categories when the replays contain them, two of them marked for
    reduced motion. Returns sheets (for reviewers) and the key (for scoring),
    plus the categories the pool could not supply."""
    rng = random.Random(seed)
    pool = [x for x in (decisive_exchange(r) for r in replays) if x]
    by_cause: dict[str, list[dict]] = {}
    for x in pool:
        for c in x["causes"]:
            by_cause.setdefault(c, []).append(x)
    missing = [c for c in REQUIRED if not by_cause.get(c)]
    sheets, key = [], []
    item = 0
    for rv in range(1, reviewers + 1):
        chosen: list[dict] = []
        for c in REQUIRED:
            cands = [x for x in by_cause.get(c, []) if x not in chosen]
            if cands and len(chosen) < per_set:
                chosen.append(rng.choice(cands))
        rest = [x for x in pool if x not in chosen]
        rng.shuffle(rest)
        chosen += rest[:per_set - len(chosen)]
        rng.shuffle(chosen)
        reduced = set(rng.sample(range(len(chosen)), min(REDUCED_MOTION_PER_SET, len(chosen))))
        reviewer = f"R{rv:02d}"
        for i, x in enumerate(chosen):
            item += 1
            where = (f"round {x['round']}, beat {x['beat']}" if x["beat"] else
                     f"round {x['round']}" if x["round"] else "the end of the fight")
            sheets.append({"reviewer": reviewer, "item": item, "fight_id": x["fight_id"], "link": f"#fight/{x['fight_id']}",
                           "where": where, "reduced_motion": i in reduced,
                           "question": f"What caused the decisive exchange at {where}? Pick one or more causes."})
            key.append({"item": item, "causes": x["causes"], "explanation": x["key"]})
    return {"causes": CAUSES, "sheets": sheets, "key": key, "pool": len(pool),
            "pool_by_cause": {c: len(v) for c, v in sorted(by_cause.items())}, "missing_required": missing}


def _wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)]


def score_answers(key: list[dict], sheets: list[dict], answers: list[dict]) -> dict:
    """Score answers (reviewer, item, causes "a;b") against the key.

    An item counts as identified when the reviewer's first-named cause is one
    the engine detail supports. An unanswered item counts as missed. The gate
    (model.md §3) passes when every reviewer identifies at least 8 of 10."""
    k = {int(x["item"]): set(x["causes"]) for x in key}
    owner = {int(s["item"]): s["reviewer"] for s in sheets}
    reduced = {int(s["item"]) for s in sheets if s.get("reduced_motion")}
    given = {}
    for a in answers:
        causes = [c.strip() for c in str(a.get("causes") or "").split(";") if c.strip()]
        given[int(a["item"])] = causes
    per_reviewer: dict[str, list[int]] = {}
    per_cause: dict[str, list[int]] = {}
    rm_hits = [0, 0]
    for item, truth in k.items():
        ok = int(bool(given.get(item)) and given[item][0] in truth)
        per_reviewer.setdefault(owner.get(item, "?"), []).append(ok)
        for c in truth:
            per_cause.setdefault(c, []).append(ok)
        if item in reduced:
            rm_hits[0] += ok
            rm_hits[1] += 1
    scores = sorted((sum(v) for v in per_reviewer.values()), reverse=True)
    total, n = sum(scores), sum(len(v) for v in per_reviewer.values())
    sets = [len(v) for v in per_reviewer.values()]
    passed = bool(scores) and all(len(v) >= GATE_OF and sum(v) >= GATE_CORRECT for v in per_reviewer.values())
    return {"reviewers": len(per_reviewer), "items": n, "identified": total,
            "rate": round(total / n, 3) if n else 0.0, "rate_95ci": _wilson(total, n),
            "reviewer_scores": scores, "set_sizes": sorted(set(sets)),
            "by_cause": {c: {"identified": sum(v), "items": len(v)} for c, v in sorted(per_cause.items())},
            "reduced_motion": {"identified": rm_hits[0], "items": rm_hits[1]},
            "unanswered": sum(1 for i in k if not given.get(i)),
            "gate": {"rule": f"every reviewer identifies at least {GATE_CORRECT} of {GATE_OF}", "passed": passed}}


# ---- cohort log ------------------------------------------------------------------------

COHORT_FIELDS = ("participant", "cohort_phase", "house_or_test", "started_at", "first_fight_at", "assistance",
                 "dropped_at_step", "drop_reason", "approach", "second_submission", "returned_week_2",
                 "explained_improvement", "clarity", "counterplay", "replay_desire")
ONBOARDING_TARGET_MIN = 10


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _yes(v) -> bool:
    return str(v or "").strip().lower() in ("y", "yes", "1", "true")


def _minutes(a: str, b: str) -> float | None:
    try:
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60
    except (TypeError, ValueError):
        return None


def _rate(k: int, n: int) -> dict:
    return {"count": k, "of": n, "rate": round(k / n, 3) if n else None, "rate_95ci": _wilson(k, n)}


def cohort_report(rows: list[dict]) -> dict:
    """Aggregate the cohort log. House and test identities (house_or_test = y)
    are counted and then excluded. Everyone who started is in the onboarding
    denominator, including those who never reached a fight."""
    unknown = sorted(set().union(*(r.keys() for r in rows)) - set(COHORT_FIELDS)) if rows else []
    excluded = [r for r in rows if _yes(r.get("house_or_test"))]
    people = [r for r in rows if not _yes(r.get("house_or_test"))]
    out = {"rows": len(rows), "excluded_house_or_test": len(excluded), "participants": len(people),
           "unknown_columns": unknown}
    phases = sorted({r.get("cohort_phase") or "main" for r in people})
    out["phases"] = {}
    for ph in phases:
        grp = [r for r in people if (r.get("cohort_phase") or "main") == ph]
        started = [r for r in grp if r.get("started_at")]
        times = [_minutes(r["started_at"], r.get("first_fight_at")) for r in started]
        reached = [t for t in times if t is not None]
        within = sum(1 for t in reached if t <= ONBOARDING_TARGET_MIN)
        assistance: dict[str, int] = {}
        for r in started:
            a = (r.get("assistance") or "none").strip().lower()
            assistance[a] = assistance.get(a, 0) + 1
        drops: dict[str, int] = {}
        for r in started:
            if r.get("first_fight_at"):
                continue
            k = f"{r.get('dropped_at_step') or 'unknown step'}: {r.get('drop_reason') or 'no reason given'}"
            drops[k] = drops.get(k, 0) + 1
        fought = [r for r in started if r.get("first_fight_at")]
        approaches: dict[str, int] = {}
        for r in fought:
            a = (r.get("approach") or "unrecorded").strip().lower()
            approaches[a] = approaches.get(a, 0) + 1
        explained = sum(1 for r in fought if str(r.get("explained_improvement") or "").lower() in ("y", "yes"))
        survey = {}
        for q in ("clarity", "counterplay", "replay_desire"):
            vals = [int(r[q]) for r in grp if str(r.get(q) or "").strip().isdigit()]
            survey[q] = {"answers": len(vals), "median": statistics.median(vals) if vals else None,
                         "distribution": {str(v): vals.count(v) for v in range(1, 6)}}
        out["phases"][ph] = {
            "recruited": len(grp), "started": len(started),
            "first_fight": _rate(len(reached), len(started)),
            "first_fight_within_target": {**_rate(within, len(started)), "target_minutes": ONBOARDING_TARGET_MIN},
            "minutes_to_first_fight": {"median": round(statistics.median(reached), 1) if reached else None,
                                       "max": round(max(reached), 1) if reached else None},
            "assistance": dict(sorted(assistance.items())),
            "drop_offs": dict(sorted(drops.items(), key=lambda kv: -kv[1])),
            "approach": dict(sorted(approaches.items())),
            "second_submission": _rate(sum(1 for r in fought if _yes(r.get("second_submission"))), len(fought)),
            "returned_week_2": _rate(sum(1 for r in fought if _yes(r.get("returned_week_2"))), len(fought)),
            "explained_improvement": _rate(explained, len(fought)),
            "survey": survey,
        }
    return out


# ---- adaptation to a style switch --------------------------------------------------------

SCORE = {"W": 1.0, "FW": 1.0, "D": 0.5, "L": 0.0, "FL": 0.0}


def adaptation(results: list[tuple[int, str]], switch_tick: int, window: int = 5, tolerance: float = 0.1) -> dict:
    """A fighter's results against one opponent, as (tick, outcome W/D/L/FW/FL),
    around the tick that opponent switched style. Forfeits are excluded from the
    scores (model.md §1: a forfeit is not strategic evidence) but counted.

    - stale_cost: mean score before the switch minus the mean of the first
      `window` fights after it;
    - adaptation_fights: fights after the switch until a rolling mean over
      `window` fights is back within `tolerance` of the pre-switch mean
      (None if it never recovers in the data)."""
    fought = [(t, SCORE[o]) for t, o in sorted(results) if o in ("W", "D", "L")]
    forfeits = sum(1 for _, o in results if o in ("FW", "FL"))
    before = [s for t, s in fought if t < switch_tick]
    after = [s for t, s in fought if t >= switch_tick]
    pre = statistics.mean(before) if before else None
    first = statistics.mean(after[:window]) if len(after) >= window else None
    recovered = None
    if pre is not None:
        for i in range(window, len(after) + 1):
            if statistics.mean(after[i - window:i]) >= pre - tolerance:
                recovered = i
                break
    return {"fights_before": len(before), "fights_after": len(after), "forfeits_excluded": forfeits,
            "score_before": round(pre, 3) if pre is not None else None,
            "score_first_window_after": round(first, 3) if first is not None else None,
            "stale_cost": round(pre - first, 3) if pre is not None and first is not None else None,
            "adaptation_fights": recovered, "window": window, "tolerance": tolerance}


def results_from_readmodel(db: Path, fighter: str, opponent: str) -> list[tuple[int, str]]:
    import sqlite3
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return [(int(t), o) for t, o in conn.execute(
            "SELECT tick, outcome FROM fight_sides WHERE fighter_id = ? AND opponent_id = ? AND outcome IS NOT NULL",
            (fighter, opponent))]
    finally:
        conn.close()
