"""Aggregate participation measurements for the builder beta (AUD-039, docs/beta.md §7).

Every number comes from the read model, which holds only public chain and
arena data: fighters and their disclosed origin (house/outside), finished
fights, the simulated NFT ledger's ownership records, and which identity sent
an included transaction when (`activity`, `bot_runs`; readmodel.py). Nothing
here sees an IP address, an e-mail, a page view or a site visit, and the
output holds counts only: no identity, fighter ID or name.

What the numbers can and cannot say:

- An *outside builder* is the identity that registered an outside fighter (its
  NFT's creator; join.py allows one fighter per key). One person may hold
  several identities; several people may share one. Counts are identities,
  not people.
- *Active* means the builder's bot sent at least one included transaction in
  that arena day. A bot runs unattended, so activity is NOT a human visit;
  returning humans are measured in the cohort log (docs/validation-protocol.md).
- A *bot run* starts with an identity's first transaction and again after a
  silence of readmodel.RUN_GAP_TICKS. A new run usually means the builder
  stopped and restarted the bot, typically after changing the planner; it is a
  proxy for revisions, not proof of one (a crash or a network outage also
  restarts a run; a hot reload does not).
- An *arena day* is DAY_SECONDS of arena time at the deployment's tick length.
  Ticks stop while the arena is down, so arena days drift from calendar days.
- Outside fighters named test-... are the operator's smoke tests (docs/beta.md
  §5): reported as `operator_tests`, counted with the house in pairings.
"""
from __future__ import annotations

import sqlite3

from . import readmodel as rm

SCHEMA = "qdojo.combat.api.community.v1"
DAY_SECONDS = 86_400
DEFAULT_TICK_SECONDS = 1.5
DAYS_SHOWN = 14
WEEKS_SHOWN = 8
CLASSES = ("house_vs_house", "outside_vs_house", "outside_vs_outside")
# Outside fighters the operator registers to test the entry path (docs/beta.md §5)
# are named test-...; they count as house in the pairings and never as builders.
TEST_PREFIX = "test-"


def measure(conn: sqlite3.Connection) -> dict:
    """The community document body (without schema and generated_tick)."""
    tick = int(rm.get_meta(conn, "tick") or 0)
    dep = rm.get_meta(conn, "deployment") or {}
    try:
        tick_seconds = float(dep.get("tick_seconds") or DEFAULT_TICK_SECONDS)
    except (TypeError, ValueError):
        tick_seconds = DEFAULT_TICK_SECONDS
    day_ticks = max(1, round(DAY_SECONDS / tick_seconds))
    today = tick // day_ticks
    day = lambda t: int(t) // day_ticks            # noqa: E731
    week = lambda d: (today - d) // 7              # 0 = the last seven arena days, today included  # noqa: E731

    # Fighters and builders.
    origin: dict[str, str] = {}
    builder_of: dict[str, str] = {}
    tests = 0
    for fid, org, owner, creator, name in conn.execute(
            "SELECT f.fighter_id, f.origin, f.owner, t.creator, f.name FROM fighters f "
            "LEFT JOIN nft_tokens t ON t.fighter_id = f.fighter_id"):
        if org == "outside" and str(name or "").lower().startswith(TEST_PREFIX):
            org, tests = "test", tests + 1     # the operator's own smoke tests: never a builder
        origin[fid] = org
        if org == "outside":
            builder_of[fid] = creator or owner
    builders = set(builder_of.values())
    first_owned = {fid: t for fid, t in conn.execute(
        "SELECT fighter_id, MIN(tick) FROM ownership GROUP BY fighter_id")}
    registered_days = sorted(day(first_owned[f]) for f in builder_of if f in first_owned)

    # Activity of outside builders' identities, by arena day.
    active_days: dict[str, set[int]] = {b: set() for b in builders}
    calls = 0
    if builders:
        marks = ",".join("?" * len(builders))
        for who, first, last, n in conn.execute(
                f"SELECT who, first_tick, last_tick, calls FROM activity WHERE who IN ({marks})", tuple(builders)):
            active_days[who].update((day(first), day(last)))
            calls += n
    runs: dict[str, list[int]] = {b: [] for b in builders}
    if builders:
        marks = ",".join("?" * len(builders))
        for who, start in conn.execute(
                f"SELECT who, start_tick FROM bot_runs WHERE who IN ({marks}) ORDER BY who, seq", tuple(builders)):
            runs[who].append(int(start))

    by_day = [{"day": d, "builders": sum(1 for s in active_days.values() if d in s)}
              for d in range(max(0, today - DAYS_SHOWN + 1), today + 1)]
    by_week = [{"weeks_ago": w, "builders": sum(1 for s in active_days.values() if any(week(d) == w for d in s))}
               for w in range(WEEKS_SHOWN - 1, -1, -1) if today - 7 * w >= 0]

    # Finished fights by pairing (house or outside on each side).
    fights_total = dict.fromkeys(CLASSES, 0)
    fights_day = dict.fromkeys(CLASSES, 0)
    fights_week = dict.fromkeys(CLASSES, 0)
    fights_by_day = {d: dict.fromkeys(CLASSES, 0) for d in range(max(0, today - DAYS_SHOWN + 1), today + 1)}
    outside_ids = [f for f, o in origin.items() if o == "outside"]
    for d, cls, n in _fight_counts(conn, day_ticks, outside_ids):
        fights_total[cls] += n
        if d == today:
            fights_day[cls] += n
        if 0 <= today - d < 7:
            fights_week[cls] += n
        if d in fights_by_day:
            fights_by_day[d][cls] += n

    # Retention: a builder whose first active day is d0 is eligible once day
    # d0 + 13 is over; retained if active (or, stricter, started a new bot run)
    # on any day d0 + 7 .. d0 + 13.
    eligible = active_again = new_run_again = 0
    for b, s in active_days.items():
        if not s:
            continue
        d0 = min(s)
        if today < d0 + 14:
            continue
        eligible += 1
        window = range(d0 + 7, d0 + 14)
        active_again += any(d in s for d in window)
        new_run_again += any(day(t) in window for t in runs[b])

    run_counts = [len(r) for r in runs.values()]
    return {
        "basis": {
            "source": "public chain transactions and arena fights in the read model; no personal data",
            "tick": tick, "tick_seconds": tick_seconds, "day_ticks": day_ticks, "today": today,
            "run_gap_ticks": rm.RUN_GAP_TICKS,
            "note": ("counts of identities, not people; an active bot is not a human visit; "
                     "arena days stop while the arena is down"),
        },
        "fighters": {"house": sum(1 for o in origin.values() if o not in ("outside", "test")),
                     "outside": len(builder_of), "operator_tests": tests},
        "outside": {
            "builders": len(builders),
            "registered_by_day": [{"day": d, "fighters": registered_days.count(d)} for d in sorted(set(registered_days))],
            "transactions": calls,
        },
        "active_builders": {"today": by_day[-1]["builders"] if by_day else 0,
                            "last_7_days": by_week[-1]["builders"] if by_week else 0,
                            "ever": sum(1 for s in active_days.values() if s),
                            "by_day": by_day, "by_week": by_week},
        "fights": {"total": fights_total, "today": fights_day, "last_7_days": fights_week,
                   "by_day": [{"day": d, **v} for d, v in sorted(fights_by_day.items())]},
        "bot_runs": {"total": sum(run_counts),
                     "builders_with_two_or_more": sum(1 for n in run_counts if n >= 2),
                     "last_7_days": sum(1 for r in runs.values() for t in r if 0 <= today - day(t) < 7)},
        "retention": {"week_2_active": {"eligible": eligible, "retained": active_again},
                      "week_2_new_run": {"eligible": eligible, "retained": new_run_again}},
    }


def _fight_counts(conn, day_ticks: int, outside_ids: list[str]):
    """(arena day, pairing class, finished fights), grouped in SQL."""
    if not outside_ids:
        for d, n in conn.execute("SELECT end_tick / ?, COUNT(*) FROM fights WHERE final = 1 AND end_tick IS NOT NULL "
                                 "GROUP BY 1", (day_ticks,)):
            yield int(d), CLASSES[0], n
        return
    marks = ",".join("?" * len(outside_ids))
    sql = (f"SELECT end_tick / ?, (a IN ({marks})) + (b IN ({marks})), COUNT(*) FROM fights "
           "WHERE final = 1 AND end_tick IS NOT NULL GROUP BY 1, 2")
    for d, k, n in conn.execute(sql, (day_ticks, *outside_ids, *outside_ids)):
        yield int(d), CLASSES[int(k)], n
