"""The beta study instruments (docs/validation-protocol.md): readability sheets, cohort log, adaptation."""
import csv
import json
import subprocess
import sys
from pathlib import Path

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
    assert m["minutes_to_first_fight"] == {"median": 16.5, "max": 25.0}
    assert m["drop_offs"] == {"install: python version": 1}
    assert m["second_submission"]["count"] == 1 and m["explained_improvement"]["count"] == 1
    assert m["survey"]["clarity"]["median"] == 3.0
    assert r["phases"]["after-correction"]["first_fight"]["count"] == 1
    assert "P01" not in json.dumps(r)
    # The committed template parses with the same columns.
    assert study.cohort_report(study.read_csv(ROOT / "docs" / "fixtures" / "beta-cohort-template.csv"))["unknown_columns"] == []


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
