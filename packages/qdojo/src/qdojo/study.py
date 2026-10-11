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
import re
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
HANDS_ON = "hands_on"            # help that disqualifies a first fight from the H3 target
ASSISTANCE = ("none", "docs", "hint", HANDS_ON)          # validation-protocol.md §4 T3; a blank cell is none
# Coded answers (validation-protocol.md §4): house_or_test, second_submission and returned_week_2 are y or n,
# explained_improvement y, partial or n. TRUE/FALSE (a spreadsheet's checkbox) and 1/0 read as y and n; blank is n.
YES, NO = ("y", "yes", "true", "1"), ("n", "no", "false", "0", "")
T6 = {"second_submission": ("y", "n"), "returned_week_2": ("y", "n"), "explained_improvement": ("y", "partial", "n")}
SURVEY = ("clarity", "counterplay", "replay_desire")      # H8: whole numbers from 1 to 5; a blank cell is no answer
# A date and a time to the minute (seconds and a UTC offset may follow); a date alone is midnight to fromisoformat.
STAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


class CohortLogError(ValueError):
    """A cohort log value the report cannot count without guessing (a timestamp it
    cannot read, a coded answer or survey score the protocol does not define), or
    a column it cannot find."""


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def read_cohort_log(path: Path) -> list[dict]:
    """The cohort log's rows, its header checked first. Column names are compared
    without case or surrounding spaces, and a spreadsheet's byte-order mark is
    not part of the first. A row whose cells are all blank (a spreadsheet's
    trailing lines) is no participant and is left out. A header without a
    column of COHORT_FIELDS or with one of them twice, or a row with more
    cells than the header, raises CohortLogError
    naming each: a column the report cannot find reads as blank in every row
    (n, none, no answer), so 'asssistance' made H3 5 of 10, a pass, for 4 of 10
    and the T6 columns kept in another sheet read as 0 of 10; of two columns
    with one name only the last was read; and an unquoted comma in a cell moves
    every cell after it."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = [h.strip().lower() for h in reader.fieldnames or ()]
        reader.fieldnames = header
        rows = [r for r in reader if r.get(None) or any(str(v or "").strip() for k, v in r.items() if k is not None)]
    problems = []
    missing = [c for c in COHORT_FIELDS if c not in header]
    if missing:
        unknown = ", ".join(repr(h) for h in header if h not in COHORT_FIELDS)
        problems.append(f"the header has no {', '.join(missing)}"
                        + (f" (it has {unknown}, which the template does not: misspelt?)" if unknown else ""))
    twice = sorted(c for c in COHORT_FIELDS if header.count(c) > 1)     # the team's own columns are never read
    if twice:
        problems.append(f"the header names {', '.join(twice)} more than once")
    for r in rows:
        if None in r:                                 # DictReader keeps the cells past the header under None
            problems.append(f"{_cell(r, 'participant') or '?'}: {len(header) + len(r[None])} cells under a header "
                            f"of {len(header)} (a comma in a cell that is not quoted?)")
    if problems:
        raise CohortLogError("the cohort log's columns cannot be read without guessing: " + "; ".join(problems))
    return rows


def _cell(r: dict, col: str) -> str:
    return str(r.get(col) or "").strip()


def _answer(r: dict, col: str, codes: tuple[str, ...] = ("y", "n")) -> str:
    """A coded answer, spelling folded (Yes and TRUE are y, a blank cell is n). One
    the protocol does not define raises CohortLogError: read as n, "house" in
    house_or_test made the operator's smoke test a participant, and TRUE in
    explained_improvement hid every improvement from H4."""
    v = _cell(r, col).lower()
    a = "y" if v in YES else "n" if v in NO else v
    if a not in codes:
        raise CohortLogError(f"{_cell(r, 'participant') or '?'}: {col} {_cell(r, col)!r} is not "
                             f"{', '.join(codes[:-1])} or {codes[-1]}")
    return a


def _score(r: dict, col: str) -> int | None:
    """A survey answer from 1 to 5, or None for a blank cell. Anything else raises
    CohortLogError: a 2.5 left out moved a median from 2.5 to 3 (the H8 finding
    gone), and a 7 counted in the median but not in the distribution."""
    v = _cell(r, col)
    if not v:
        return None
    if not re.fullmatch(r"[1-5]", v):
        raise CohortLogError(f"{_cell(r, 'participant') or '?'}: {col} {v!r} is not a whole number from 1 to 5")
    return int(v)


def _assistance(r: dict) -> str:
    """The help level, spelling normalised (Hands-On is hands_on). One the protocol
    does not define raises CohortLogError: counted as unaided it would raise H3."""
    a = "_".join(_cell(r, "assistance").lower().replace("-", " ").split()) or "none"
    if a not in ASSISTANCE:
        raise CohortLogError(f"{_cell(r, 'participant') or '?'}: assistance {_cell(r, 'assistance')!r} is not one "
                             f"of {', '.join(ASSISTANCE)}")
    return a


def _stamp(r: dict, col: str) -> datetime | None:
    v = _cell(r, col)
    if not v:
        return None
    if STAMP_RE.match(v):
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            pass
    raise CohortLogError(f"{_cell(r, 'participant') or '?'}: {col} {v!r} is not a date and time "
                         "(write YYYY-MM-DDTHH:MM)")


def _minutes(r: dict) -> float | None:
    """Minutes from started_at to first_fight_at, or None when no first fight is
    logged. A time that does not parse, a UTC offset on one side only, or a
    first fight before the start raises CohortLogError: the participant would
    otherwise drop out of the funnel without a word."""
    who = _cell(r, "participant") or "?"
    stamps, bad = [], []
    for col in ("started_at", "first_fight_at"):
        try:
            stamps.append(_stamp(r, col))
        except CohortLogError as exc:
            bad.append(str(exc))
    if bad:
        raise CohortLogError("; ".join(bad))
    a, b = stamps
    if a is None:
        if b is not None:
            raise CohortLogError(f"{who}: first_fight_at without started_at")
        return None
    if b is None:
        return None
    if (a.tzinfo is None) != (b.tzinfo is None):
        raise CohortLogError(f"{who}: started_at and first_fight_at must both have a UTC offset or both have none")
    minutes = (b - a).total_seconds() / 60
    if minutes < 0:
        raise CohortLogError(f"{who}: first_fight_at is before started_at")
    return minutes


def _phase(r: dict) -> str:
    """The cohort phase; a stray space or capital (a spreadsheet's) does not split a phase in two."""
    return _cell(r, "cohort_phase").lower() or "main"


def _rate(k: int, n: int) -> dict:
    return {"count": k, "of": n, "rate": round(k / n, 3) if n else None, "rate_95ci": _wilson(k, n)}


def _over(minutes: float) -> float | str:
    """A participant's minutes, or "over" for one who never reached a fight (counted as infinite)."""
    return "over" if minutes == float("inf") else round(minutes, 1)


def cohort_report(rows: list[dict]) -> dict:
    """Aggregate the cohort log as docs/validation-protocol.md §3 defines its
    measures. House and test identities (house_or_test = y) are counted and
    then excluded. Everyone who started is in the denominator of every rate
    (H2-H6), whether or not they reached a fight. H3 counts a first fight
    within the target only without `hands_on` help (the count including it is
    reported under its own key), and the minutes to a first fight are taken
    over everyone who started, a dropout counting as "over" (the median is the
    lower one: always a participant's own time, never an average with a
    dropout). H4 counts explained_improvement = y, not partial. Raises
    CohortLogError, naming every bad cell, when a timestamp cannot be read or a
    coded answer (house_or_test, assistance, the T6 answers) or a survey score
    is not one the protocol defines. A row without a column reads as a blank
    cell there: read a log file with read_cohort_log, which checks its header."""
    unknown = sorted(set().union(*(r.keys() for r in rows)) - set(COHORT_FIELDS)) if rows else []
    problems: list[str] = []

    def check(read, r, *args):
        try:
            return read(r, *args)
        except CohortLogError as exc:
            problems.append(str(exc))
    house = {id(r): check(_answer, r, "house_or_test") for r in rows}
    excluded = [r for r in rows if house[id(r)] == "y"]
    people = [r for r in rows if house[id(r)] != "y"]       # an unreadable flag: the row is checked as a participant's
    minutes = {}
    for r in people:
        minutes[id(r)] = check(_minutes, r)
        check(_assistance, r)
        for col, codes in T6.items():
            check(_answer, r, col, codes)
        for q in SURVEY:
            check(_score, r, q)
    if problems:
        raise CohortLogError("the cohort log has values the report cannot count without guessing: "
                             + "; ".join(problems))
    out = {"rows": len(rows), "excluded_house_or_test": len(excluded), "participants": len(people),
           "unknown_columns": unknown}
    phases = sorted({_phase(r) for r in people})
    out["phases"] = {}
    for ph in phases:
        grp = [r for r in people if _phase(r) == ph]
        started = [r for r in grp if _cell(r, "started_at")]
        reached = [r for r in started if minutes[id(r)] is not None]
        within = [r for r in reached if minutes[id(r)] <= ONBOARDING_TARGET_MIN]
        unaided = sum(1 for r in within if _assistance(r) != HANDS_ON)
        to_fight = sorted(minutes[id(r)] if minutes[id(r)] is not None else float("inf") for r in started)
        assistance: dict[str, int] = {}
        for r in started:
            a = _assistance(r)
            assistance[a] = assistance.get(a, 0) + 1
        drops: dict[str, int] = {}
        for r in started:
            if minutes[id(r)] is not None:
                continue
            k = f"{_cell(r, 'dropped_at_step') or 'unknown step'}: {_cell(r, 'drop_reason') or 'no reason given'}"
            drops[k] = drops.get(k, 0) + 1
        approaches: dict[str, int] = {}
        for r in reached:
            a = (r.get("approach") or "unrecorded").strip().lower()
            approaches[a] = approaches.get(a, 0) + 1
        answers = {col: _rate(sum(1 for r in started if _answer(r, col, codes) == "y"), len(started))
                   for col, codes in T6.items()}
        survey = {}
        for q in SURVEY:
            vals = [v for v in (_score(r, q) for r in grp) if v is not None]
            survey[q] = {"answers": len(vals), "median": statistics.median(vals) if vals else None,
                         "distribution": {str(v): vals.count(v) for v in range(1, 6)}}
        out["phases"][ph] = {
            "recruited": len(grp), "started": len(started),
            "first_fight": _rate(len(reached), len(started)),
            "first_fight_within_target": {**_rate(unaided, len(started)), "target_minutes": ONBOARDING_TARGET_MIN,
                                          "without": HANDS_ON},
            "first_fight_within_target_including_hands_on": _rate(len(within), len(started)),
            "minutes_to_first_fight": {"median": _over(statistics.median_low(to_fight)) if to_fight else None,
                                       "max": _over(to_fight[-1]) if to_fight else None, "of": len(started)},
            "assistance": dict(sorted(assistance.items())),
            "drop_offs": dict(sorted(drops.items(), key=lambda kv: -kv[1])),
            "approach": dict(sorted(approaches.items())),
            **answers,                                    # second_submission, returned_week_2, explained_improvement
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
