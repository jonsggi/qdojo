"""The beta study instruments (docs/validation-protocol.md): readability sheets, cohort log, adaptation."""
import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from qdojo import study

ROOT = Path(__file__).resolve().parents[3]
SAMPLE = ROOT / "apps" / "web" / "data" / "combat" / "v1" / "sample"


def _beat(a, b, lost_a=0, lost_b=0, ra=(), rb=(), ea=None, eb=None):
    side = lambda act, eff, lost, rs: {"intended": act, "effective": eff or act, "actual_hp_lost": lost,  # noqa: E731
                                       "reasons": list(rs)}
    return {"beat": 0, "A": side(a, ea, lost_a, ra), "B": side(b, eb, lost_b, rb)}


def test_beat_causes_follow_the_engine_detail():
    assert study.beat_causes(_beat("LAST_STAND", "JAB", 0, 18, ra=["STAND_BONUS", "HIT"])) == ["last_stand"]
    assert "feint_guard_break" in study.beat_causes(_beat("FEINT", "BLOCK", rb=["FEINT_BAITED"]))
    assert study.beat_causes(_beat("KICK", "JAB", 8, 0, ea="EXHAUSTED", rb=["HIT"])) == ["resource_failure"]
    assert study.beat_causes(_beat("JAB", "JAB", 8, 8, ra=["HIT"], rb=["HIT"])) == ["simultaneous_trade"]
    assert study.beat_causes(_beat("JAB", "BLOCK", ra=["BLOCKED"])) == ["block_evade"]
    assert study.beat_causes(_beat("JAB", "THROW", 0, 8, ra=["HIT"])) == ["clean_hit"]


def test_decisive_exchanges_of_ko_decision_forfeit_and_draw():
    ko = {"fight_id": 1, "result": {"kind": "COMBAT", "winner": "A", "result": "KO"},
          "rounds": [{"round_index": 0, "beats": [_beat("JAB", "JAB", 0, 30), dict(_beat("KICK", "JAB", 0, 18, ra=["KO"]), beat=1)]}]}
    x = study.decisive_exchange(ko)
    assert (x["round"], x["beat"]) == (1, 2)
    dec = {"fight_id": 2, "result": {"kind": "COMBAT", "winner": "B", "result": "HP"},
           "rounds": [{"round_index": 2, "beats": [_beat("JAB", "JAB", 8, 0), dict(_beat("KICK", "THROW", 20, 0), beat=4)]}]}
    assert (study.decisive_exchange(dec)["round"], study.decisive_exchange(dec)["beat"]) == (3, 5)
    ff = {"fight_id": 3, "result": {"kind": "FORFEIT", "winner": "A"}, "forfeit_round": 1, "rounds": []}
    assert study.decisive_exchange(ff) == {"fight_id": "3", "round": 2, "beat": None, "causes": ["forfeit"],
                                           "key": "B did not commit or reveal its plan in time and forfeited"}
    assert study.decisive_exchange({"fight_id": 4, "result": {"kind": "COMBAT", "winner": None, "result": "HP_TIE"}}) is None


def test_sheets_from_the_sample_export_and_scoring(tmp_path):
    replays = study.load_replays(SAMPLE)
    assert len(replays) > 20
    doc = study.sample_sheets(replays, reviewers=3, seed=7)
    assert len(doc["sheets"]) == len(doc["key"]) == 30
    for rv in ("R01", "R02", "R03"):
        mine = [s for s in doc["sheets"] if s["reviewer"] == rv]
        assert len(mine) == 10 and sum(s["reduced_motion"] for s in mine) == 2
        causes = {c for s in mine for c in next(k["causes"] for k in doc["key"] if k["item"] == s["item"])}
        assert set(study.REQUIRED) - set(doc["missing_required"]) <= causes, rv
    assert doc == study.sample_sheets(replays, reviewers=3, seed=7), "deterministic for a seed"
    # Reviewer 1 gets all ten, reviewer 2 eight, reviewer 3 seven (one left blank): the gate fails.
    key = {k["item"]: k["causes"] for k in doc["key"]}
    answers = []
    for s in doc["sheets"]:
        n = int(s["item"])
        wrong = (s["reviewer"] == "R02" and n in (11, 12)) or (s["reviewer"] == "R03" and n in (21, 22))
        if s["reviewer"] == "R03" and n == 23:
            continue
        pick = next(c for c in study.CAUSES if c not in key[n]) if wrong else key[n][0]
        answers.append({"reviewer": s["reviewer"], "item": n, "causes": pick})
    r = study.score_answers(doc["key"], doc["sheets"], answers)
    assert r["reviewer_scores"] == [10, 8, 7] and r["identified"] == 25 and r["unanswered"] == 1
    assert r["gate"]["passed"] is False and r["reduced_motion"]["items"] == 6
    assert "R01" not in json.dumps(r), "aggregate only"
    answers = [a for a in answers if a["reviewer"] != "R03"]
    sheets = [s for s in doc["sheets"] if s["reviewer"] != "R03"]
    keep = {s["item"] for s in sheets}
    assert study.score_answers([k for k in doc["key"] if k["item"] in keep], sheets, answers)["gate"]["passed"] is True


def test_cohort_report_keeps_drop_offs_in_the_denominator(tmp_path):
    rows = [
        {"participant": "P01", "started_at": "2026-10-20T10:00", "first_fight_at": "2026-10-20T10:08",
         "assistance": "none", "approach": "starter", "second_submission": "y", "returned_week_2": "y",
         "explained_improvement": "y", "clarity": "4", "counterplay": "3", "replay_desire": "5"},
        {"participant": "P02", "started_at": "2026-10-20T11:00", "first_fight_at": "2026-10-20T11:25",
         "assistance": "hint", "approach": "independent", "second_submission": "n", "returned_week_2": "n",
         "explained_improvement": "partial", "clarity": "2"},
        {"participant": "P03", "started_at": "2026-10-21T09:00", "dropped_at_step": "install",
         "drop_reason": "python version"},
        {"participant": "P04"},                                       # recruited, never started
        {"participant": "H01", "house_or_test": "y", "started_at": "2026-10-20T09:00",
         "first_fight_at": "2026-10-20T09:03"},
        {"participant": "P05", "cohort_phase": "after-correction", "started_at": "2026-10-28T10:00",
         "first_fight_at": "2026-10-28T10:05"},
    ]
    path = tmp_path / "cohort.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=study.COHORT_FIELDS)
        w.writeheader()
        w.writerows(rows)
    r = study.cohort_report(study.read_csv(path))
    assert r["excluded_house_or_test"] == 1 and r["participants"] == 5 and r["unknown_columns"] == []
    m = r["phases"]["main"]
    assert m["recruited"] == 4 and m["started"] == 3
    assert m["first_fight"]["count"] == 2 and m["first_fight"]["of"] == 3
    assert m["first_fight_within_target"]["count"] == 1 and m["first_fight_within_target"]["of"] == 3
    # P03 dropped out: counted as over, so the median is P02's 25 minutes and the max is over.
    assert m["minutes_to_first_fight"] == {"median": 25.0, "max": "over", "of": 3}
    assert m["drop_offs"] == {"install: python version": 1}
    for k in ("second_submission", "returned_week_2", "explained_improvement"):
        assert (m[k]["count"], m[k]["of"]) == (1, 3), k
    assert m["survey"]["clarity"]["median"] == 3.0
    assert r["phases"]["after-correction"]["first_fight"]["count"] == 1
    assert "P01" not in json.dumps(r)
    # The committed template parses with the same columns.
    assert study.cohort_report(study.read_csv(ROOT / "docs" / "fixtures" / "beta-cohort-template.csv"))["unknown_columns"] == []


def _cohort(*rows):
    return study.cohort_report(list(rows))["phases"]["main"]


def _person(p, fight_min=None, assistance="none", **kw):
    """A participant who started at 10:00 and reached a first fight `fight_min` minutes later (None: dropped out)."""
    r = {"participant": p, "started_at": "2026-10-20T10:00", "assistance": assistance, **kw}
    if fight_min is None:
        r.setdefault("dropped_at_step", "install")
        r.setdefault("drop_reason", "gave up")
    else:
        r["first_fight_at"] = f"2026-10-20T10:{fight_min:02d}"
    return r


def test_h3_counts_a_first_fight_within_target_only_without_hands_on_help():
    """validation-protocol.md §3 H3: >= 50% within 10 minutes without hands_on help,
    everyone who started in the denominator, dropouts counted as over."""
    reached = [_person("P01", 5, "hands_on")] + [_person(f"P0{i}", 5) for i in range(2, 6)]
    dropped = [_person(f"P{i:02d}") for i in range(6, 11)]
    m = _cohort(*reached, *dropped)
    assert (m["first_fight_within_target"]["count"], m["first_fight_within_target"]["of"]) == (4, 10)
    assert m["first_fight_within_target"]["rate"] == 0.4                     # fails the 50% gate
    assert m["first_fight_within_target_including_hands_on"]["count"] == 5
    # The same log with the hands-on help given to a dropout instead passes: the report must tell them apart.
    other = _cohort(*[_person(f"P0{i}", 5) for i in range(1, 6)], _person("P06", None, "hands_on"), *dropped[1:])
    assert other["first_fight_within_target"]["rate"] == 0.5
    assert other["first_fight_within_target_including_hands_on"]["count"] == 5
    # Spelling of the help level does not matter.
    assert _cohort(_person("P01", 5, "Hands-On"))["first_fight_within_target"]["count"] == 0
    # 4 reach a fight (2 with hands-on help), 6 drop out: H3 is 2 of 10 and the median lands on a dropout.
    m = _cohort(_person("P01", 3, "hands_on"), _person("P02", 4), _person("P03", 6, "hands_on"), _person("P04", 7),
                *[_person(f"P{i:02d}") for i in range(5, 11)])
    assert m["first_fight_within_target"]["count"] == 2
    assert m["minutes_to_first_fight"] == {"median": "over", "max": "over", "of": 10}
    # Exactly half within target: the lower median is a participant's own time, not an average with a dropout.
    m = _cohort(*[_person(f"P0{i}", 9) for i in range(1, 6)], *[_person(f"P{i:02d}") for i in range(6, 11)])
    assert m["first_fight_within_target"]["rate"] == 0.5 and m["minutes_to_first_fight"]["median"] == 9.0


def test_h4_to_h6_count_everyone_who_started():
    """Every participant counts in the denominator of every rate from the moment
    they start (validation-protocol.md §3), and so in the count when they meet it."""
    fought = [_person(f"P0{i}", 5, second_submission="y", returned_week_2="y", explained_improvement="y")
              for i in range(1, 5)]
    m = _cohort(*fought, *[_person(f"P{i:02d}") for i in range(5, 11)])
    for k in ("second_submission", "returned_week_2", "explained_improvement"):
        assert m[k] == {"count": 4, "of": 10, "rate": 0.4, "rate_95ci": [0.168, 0.687]}, k
    # An improvement shown against an NPC in practice counts though that participant never reached the arena.
    m = _cohort(_person("P01", 5, explained_improvement="y"), _person("P02", explained_improvement="y"), _person("P03"))
    assert (m["explained_improvement"]["count"], m["explained_improvement"]["of"]) == (2, 3)


def test_a_timestamp_the_report_cannot_read_stops_it(tmp_path):
    bad = [
        {**_person("P01"), "first_fight_at": "2026-10-20T10:07+02:00"},          # offset on one side only
        {**_person("P02"), "first_fight_at": "10:09"},                            # a time without a date
        {**_person("P03"), "first_fight_at": "2026-10-19T10:05"},                 # before the start
        {"participant": "P04", "first_fight_at": "2026-10-20T10:05"},              # never started
        {**_person("P05"), "started_at": "20.10.2026 10:00"},                     # a locale date
        {**_person("P06", 5), "started_at": "2026-10-20", "first_fight_at": "2026-10-20"},   # dates, no times
        {**_person("P07", 5), "started_at": "2026-10-20"},                        # 607 minutes if read as midnight
        {**_person("P08", 5), "first_fight_at": "2026-10-20T10"},                 # no minutes
        {**_person("P09", 5), "first_fight_at": "2026-W43-2T10:05"},              # an ISO week date
    ]
    with pytest.raises(study.CohortLogError) as exc:
        study.cohort_report(bad)
    for p in ("P01", "P02", "P03", "P04", "P05", "P06", "P07", "P08", "P09"):
        assert p in str(exc.value)
    assert "P06: started_at '2026-10-20'" in str(exc.value) and "P06: first_fight_at '2026-10-20'" in str(exc.value)
    # A date alone (the time not noted) read as midnight made 0 minutes: H3 5 of 10, a pass, where 4 of 10 is known.
    with pytest.raises(study.CohortLogError, match="P05: started_at '2026-10-20' is not a date and time"):
        _cohort(*[_person(f"P0{i}", 5) for i in range(1, 5)],
                {**_person("P05", 5), "started_at": "2026-10-20", "first_fight_at": "2026-10-20"},
                *[_person(f"P{i:02d}") for i in range(6, 11)])
    # A space for the T, seconds, and an offset on both sides are a date and a time.
    m = _cohort({**_person("P01", 5), "started_at": "2026-10-20 10:00:30", "first_fight_at": "2026-10-20 10:05:30"},
                {**_person("P02", 5), "started_at": "2026-10-20T10:00+02:00", "first_fight_at": "2026-10-20T08:09Z"})
    assert m["first_fight_within_target"]["count"] == 2 and m["minutes_to_first_fight"]["max"] == 9.0
    # Offsets on both sides are fine, and a blank cell is an empty one: a dropout keeps its reason.
    m = _cohort({"participant": "P01", "started_at": "2026-10-20T10:00Z", "first_fight_at": "2026-10-20T12:07+02:00"},
                {**_person("P02"), "first_fight_at": "  "})
    assert m["first_fight"]["count"] == 1 and m["first_fight_within_target"]["count"] == 1
    assert m["drop_offs"] == {"install: gave up": 1}
    # The script says what is wrong instead of printing a miscounted report.
    path = tmp_path / "cohort.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=study.COHORT_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(bad[1:2])
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "beta-study.py"), "cohort", str(path)],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 2 and "P02" in out.stderr and "'10:09'" in out.stderr and out.stdout == ""


def test_an_assistance_level_the_protocol_does_not_define_stops_the_report():
    """validation-protocol.md §4 T3 logs none, docs, hint or hands_on. Any other
    value counted as unaided would raise H3: 'hands-on help' on one of five fast
    first fights turned a 4 of 10 fail into a 5 of 10 pass."""
    dropped = [_person(f"P{i:02d}") for i in range(6, 11)]
    for value in ("hands-on help", "handson", "hands\u2013on", "hands_on (typed install)", "HO"):
        with pytest.raises(study.CohortLogError) as exc:
            _cohort(_person("P01", 5, value), *[_person(f"P0{i}", 5) for i in range(2, 6)], *dropped)
        assert f"P01: assistance {value!r} is not one of none, docs, hint, hands_on" in str(exc.value)
    # Case, spaces and hyphens do not matter, and a blank cell is none.
    m = _cohort(_person("P01", 5, " Hands-On "), _person("P02", 5, "HINT"), _person("P03", 5, "Docs"),
                _person("P04", 5, ""), *dropped)
    assert m["assistance"] == {"docs": 1, "hands_on": 1, "hint": 1, "none": 6}
    assert m["first_fight_within_target"]["count"] == 3


def test_a_coded_answer_or_score_the_protocol_does_not_define_stops_the_report():
    """validation-protocol.md §4: house_or_test, second_submission and returned_week_2
    are y or n, explained_improvement y, partial or n, and a survey answer a whole
    number from 1 to 5. Read any other way, a value moved a measure without a word."""
    fast, dropped = [_person(f"P0{i}", 5) for i in range(1, 5)], [_person(f"P0{i}") for i in range(5, 10)]
    # "house" (the column's own word) read as n made the smoke test a participant: H3 5 of 10, a pass, for 4 of 9.
    for value in ("house", "test", "x"):
        with pytest.raises(study.CohortLogError) as exc:
            study.cohort_report([*fast, *dropped, _person("T01", 3, house_or_test=value)])
        assert f"T01: house_or_test {value!r} is not y or n" in str(exc.value)
    r = study.cohort_report([*fast, *dropped, _person("T01", 3, house_or_test=" Yes ")])
    h3 = r["phases"]["main"]["first_fight_within_target"]
    assert r["participants"] == 9 and (h3["count"], h3["of"]) == (4, 9)
    # A checkbox export (TRUE/FALSE) reads the same in all three T6 columns: H4 read 0 of 10 beside H5 and H6 at 7.
    ticked = [dict.fromkeys(study.T6, "TRUE")] * 7 + [dict.fromkeys(study.T6, "FALSE")] * 3
    m = _cohort(*[_person(f"P{i:02d}", 5, **t6) for i, t6 in enumerate(ticked, 1)])
    assert [(m[k]["count"], m[k]["of"]) for k in study.T6] == [(7, 10)] * 3
    # partial is an answer of explained_improvement only, and H4 does not count it.
    m = _cohort(_person("P01", 5, explained_improvement=" Partial"), _person("P02", 5, explained_improvement="yes"))
    assert m["explained_improvement"]["count"] == 1
    for col, value, codes in (("explained_improvement", "y - jabber 0.40 -> 0.70", "y, partial or n"),
                              ("explained_improvement", "maybe", "y, partial or n"),
                              ("second_submission", "partial", "y or n"), ("returned_week_2", "2", "y or n")):
        with pytest.raises(study.CohortLogError) as exc:
            _cohort(_person("P01", 5, **{col: value}))
        assert f"P01: {col} {value!r} is not {codes}" in str(exc.value)
    # Left out, a 2.5 moved the clarity median from 2.5 to 3 (no H8 finding); a 7 was in the median but not
    # the distribution.
    clarity = ["2", "2", "2", "2", None, "4", "4", "4", "4"]
    for value in ("2.5", "7", "0", "four", "4/5"):
        with pytest.raises(study.CohortLogError) as exc:
            _cohort(*[_person(f"P0{i}", 5, clarity=v or value) for i, v in enumerate(clarity, 1)])
        assert f"P05: clarity {value!r} is not a whole number from 1 to 5" in str(exc.value)
    m = _cohort(*[_person(f"P0{i}", 5, clarity=v or " 3 ") for i, v in enumerate(clarity, 1)],
                _person("P10", clarity=""))                                       # a blank cell is no answer
    assert m["survey"]["clarity"] == {"answers": 9, "median": 3,
                                      "distribution": {"1": 0, "2": 4, "3": 1, "4": 4, "5": 0}}
    # Every bad cell is named at once, those of a row whose house_or_test is unreadable too.
    with pytest.raises(study.CohortLogError) as exc:
        study.cohort_report([_person("T01", 3, house_or_test="house", clarity="7"),
                             _person("P01", 5, returned_week_2="TRUE?", counterplay="3.5")])
    for cell in ("T01: house_or_test 'house'", "T01: clarity '7'", "P01: returned_week_2 'TRUE?'",
                 "P01: counterplay '3.5'"):
        assert cell in str(exc.value)


def test_a_phase_is_read_without_case_or_stray_spaces():
    """A spreadsheet's stray space or capital does not split a phase in two
    (7 of 10 reaching a fight would read as 6 of 9 and 1 of 1)."""
    rows = [_person(f"P{i:02d}", 5 if i <= 7 else None, cohort_phase="main") for i in range(1, 11)]
    rows[0]["cohort_phase"], rows[1]["cohort_phase"], rows[2]["cohort_phase"] = "main ", "Main", ""
    rows += [_person("P11", 5, cohort_phase=" After-Correction"), _person("P12", cohort_phase="after-correction")]
    r = study.cohort_report(rows)
    assert sorted(r["phases"]) == ["after-correction", "main"]
    assert (r["phases"]["main"]["first_fight"]["count"], r["phases"]["main"]["first_fight"]["of"]) == (7, 10)
    assert r["phases"]["after-correction"]["started"] == 2


def test_adaptation_to_a_style_switch():
    res = [(t, "W") for t in range(0, 100, 10)] + [(100, "L"), (110, "L"), (120, "FL"), (130, "L"), (140, "W"),
                                                    (150, "L"), (160, "W"), (170, "W"), (180, "W"), (190, "W")]
    r = study.adaptation(res, switch_tick=100, window=5)
    assert r["fights_before"] == 10 and r["fights_after"] == 9 and r["forfeits_excluded"] == 1
    assert r["score_before"] == 1.0 and r["score_first_window_after"] == 0.2 and r["stale_cost"] == 0.8
    assert r["adaptation_fights"] is None                 # never back within 0.1 of a perfect record
    # Within 0.2: the window ending at the eighth fight after the switch (W L W W W) scores 0.8.
    assert study.adaptation(res, switch_tick=100, window=5, tolerance=0.2)["adaptation_fights"] == 8


def test_the_script_runs(tmp_path):
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "beta-study.py"), "sample", "--export", str(SAMPLE),
                          "--reviewers", "2", "--out", str(tmp_path)], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "sheets.md").read_text().count("## R0") == 2 and json.loads(out.stdout)["pool"] > 20
