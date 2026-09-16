import json
import os

import pytest

from qdojo import lab

REAL = os.path.expanduser("~/.qdojo/evo")

TRACEBACK = """03:03:49 round 36 blue_belt_fix_count_evens_integer: no answer (Traceback (most recent call last):
  File "/home/someone/.qdojo/evo/qdojo_evo1/tools/blue_belt_fix_count_evens_integer.py", line 90, in <module>
    main()
ValueError: Could not fix the function
)
03:41:44 round 41 blue_belt_fix_odd_product_integer: 316234143225
"""


def bot(tmp_path, name, tools=None, log=""):
    """Builds one evo bot dir: {key: [(unix_ts, source), ...]} plus a log."""
    d = tmp_path / name
    (d / "tools").mkdir(parents=True)
    for key, revs in (tools or {}).items():
        for ts, src in revs:
            (d / "tools" / f"{key}.py.v{ts}").write_text(src)
        (d / "tools" / f"{key}.py").write_text(revs[-1][1])
    if log:
        (d / "evo.log").write_text(log)
    return str(d)


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)


def test_a_missing_root_is_empty_not_an_error(tmp_path):
    assert lab.find_evo_dirs(str(tmp_path / "nope")) == []
    assert lab.build(str(tmp_path / "nope"))["totals"]["bots"] == 0


def test_a_root_that_is_itself_a_bot(tmp_path):
    bot(tmp_path, "qdojo_solo", {"white_belt_sum_the_numbers_integer": [(1789517836, "x=1\n")]})
    root = str(tmp_path / "qdojo_solo")
    assert lab.find_evo_dirs(root) == [root]
    assert lab.build(root)["bots"][0]["name"] == "qdojo_solo"


def test_a_subdir_with_only_a_log_still_counts_as_a_bot(tmp_path):
    (tmp_path / "qdojo_x").mkdir()
    (tmp_path / "qdojo_x" / "evo.log").write_text("00:00:01 round 1 white_belt_a_integer: 1\n")
    assert lab.find_evo_dirs(str(tmp_path)) == [str(tmp_path / "qdojo_x")]


def test_revisions_come_from_the_snapshots_not_the_live_file(tmp_path):
    p = bot(tmp_path, "b", {"blue_belt_fix_dot_mod_integer":
                            [(1789523024, "v1\n"), (1789580945, "v2\n"), (1789590797, "v3\n")]})
    k = lab.read_bot(p)["kinds"]["blue_belt_fix_dot_mod_integer"]
    assert k["revisions"] == 3
    assert (k["first_ts"], k["last_ts"]) == (1789523024, 1789590797)
    assert k["bytes"] == 3 and len(k["fingerprint"]) == 16
    assert lab.read_bot(p)["tool_count"] == 1 and lab.read_bot(p)["snapshot_count"] == 3


def test_no_tool_source_or_path_ever_reaches_the_output(tmp_path):
    bot(tmp_path, "qdojo_evo1",
        {"blue_belt_fix_dot_mod_integer": [(1789523024, "SECRETCANARY = 'do not publish'\n")]},
        log=TRACEBACK)
    doc = lab.build(str(tmp_path))
    blob = json.dumps(doc)
    assert "SECRETCANARY" not in blob
    assert str(tmp_path) not in blob
    assert not [s for s in strings(doc) if "/" in s]


def test_a_traceback_spill_is_one_failure_and_the_continuation_is_dropped():
    recs = lab.parse_log(TRACEBACK)
    assert [r["kind"] for r in recs] == ["fail", "solve"]
    assert recs[0]["round_id"] == 36 and recs[0]["error_head"] == "Traceback (most recent call last):"
    assert "ValueError" not in json.dumps(recs)   # only the first line survives


def test_a_learned_line_is_a_repair():
    line = "04:54:25 learned round 46 blue_belt_fix_dot_mod_integer: repaired tool now says 208 (want '208')\n"
    r, = lab.parse_log(line)
    assert r["kind"] == "learn" and r["round_id"] == 46
    assert r["key"] == "blue_belt_fix_dot_mod_integer" and r["hms"] == "04:54:25"


def test_values_negative_integers_and_quoted_strings():
    recs = lab.parse_log("20:41:41 round 112 white_belt_sum_the_numbers_integer: -1533\n"
                         "00:39:14 round 17 yellow_belt_undo_a_caesar_shift_string: 'juniper tide yarrow'\n"
                         "06:04:01 round 60 blue_belt_fix_sum_to_n_integer: no answer (no tool yet)\n")
    assert recs[0]["value"] == -1533
    assert recs[1]["value"] == "juniper tide yarrow"
    assert recs[2]["error_head"] == "no tool yet"


def test_scrub_drops_paths_and_keeps_the_exception():
    assert lab.scrub('File "/home/joel/.qdojo/evo/b/tools/x.py", line 90, in <module>') == 'File "", line 90, in <module>'
    assert lab.scrub("ValueError: Could not fix the function") == "ValueError: Could not fix the function"
    assert "/" not in lab.scrub("/usr/lib/python3.12/ast.py")


def test_belt_and_answer_format_come_out_of_the_key():
    assert lab.belt_of("blue_belt_fix_dot_mod_integer") == "blue"
    assert lab.format_of("blue_belt_fix_dot_mod_integer") == "integer"
    assert (lab.belt_of("green_belt_sha_#_of_a_string_hex"),
            lab.format_of("green_belt_sha_#_of_a_string_hex")) == ("green", "hex")
    assert (lab.belt_of("yellow_belt_reverse_the_string_string"),
            lab.format_of("yellow_belt_reverse_the_string_string")) == ("yellow", "string")
    assert (lab.belt_of("mystery_riddle"), lab.format_of("mystery_riddle")) == (None, None)


def test_convergence_counts_bots_and_distinct_implementations(tmp_path):
    same = "print(1)\n"
    bot(tmp_path, "qdojo_a", {"white_belt_sum_the_numbers_integer": [(100, same)],
                              "blue_belt_fix_dot_mod_integer": [(101, "a\n"), (102, "aa\n")]},
        log="00:10:00 round 5 white_belt_sum_the_numbers_integer: 1\n"
            "00:20:00 round 6 blue_belt_fix_dot_mod_integer: no answer (no tool yet)\n")
    bot(tmp_path, "qdojo_b", {"white_belt_sum_the_numbers_integer": [(200, same)]},
        log="00:11:00 round 5 white_belt_sum_the_numbers_integer: 1\n")
    doc = lab.build(str(tmp_path))
    tax = {t["key"]: t for t in doc["taxonomy"]}
    assert tax["white_belt_sum_the_numbers_integer"]["bots"] == 2
    assert tax["white_belt_sum_the_numbers_integer"]["distinct_implementations"] == 1
    assert tax["white_belt_sum_the_numbers_integer"]["first_ts"] == 100
    assert tax["blue_belt_fix_dot_mod_integer"]["bots"] == 1
    assert tax["blue_belt_fix_dot_mod_integer"]["avg_revisions"] == 2.0
    assert doc["convergence"] == {"keys_total": 2, "keys_all_bots": 1, "keys_one_bot": 1,
                                 "mean_bots_per_kind": 1.5}
    assert doc["by_belt"]["white"]["bots_that_solved"] == 2
    assert doc["by_belt"]["blue"]["failures"] == 1
    assert doc["totals"] == {"bots": 2, "kinds": 2, "tools": 3, "snapshots": 4,
                             "solves": 2, "failures": 1, "repairs": 0}


def test_a_log_across_midnight_stays_sane(tmp_path):
    p = bot(tmp_path, "b", log="23:50:00 round 100 white_belt_a_integer: 1\n"
                               "23:59:00 round 101 white_belt_a_integer: 2\n"
                               "00:04:00 round 102 white_belt_a_integer: 3\n"
                               "00:40:00 round 103 white_belt_a_integer: 4\n")
    b = lab.read_bot(p)
    assert b["day_rollovers"] == 1
    assert (b["first_round"], b["last_round"], b["rounds_seen"], b["solves"]) == (100, 103, 4, 4)


def test_build_is_stable_across_two_runs(tmp_path):
    bot(tmp_path, "qdojo_a", {"white_belt_sum_the_numbers_integer": [(100, "x\n")]},
        log="00:10:00 round 5 white_belt_sum_the_numbers_integer: 1\n")
    bot(tmp_path, "qdojo_b", {"green_belt_sha_#_of_a_string_hex": [(101, "y\n")]},
        log="00:11:00 round 6 green_belt_sha_#_of_a_string_hex: 'ab'\n")
    one, two = lab.build(str(tmp_path)), lab.build(str(tmp_path))
    one.pop("generated_at"), two.pop("generated_at")
    assert json.dumps(one) == json.dumps(two)


def test_bot_json_names_the_bot_and_explicit_args_win(tmp_path):
    p = bot(tmp_path, "dirname", {"white_belt_a_integer": [(1, "x\n")]})
    (tmp_path / "dirname" / "bot.json").write_text(
        json.dumps({"name": "fighter", "identity": "A" * 60, "model": "some-model"}))
    assert lab.read_bot(p)["name"] == "fighter"
    assert lab.read_bot(p)["identity"] == "A" * 60
    assert lab.read_bot(p, model="other")["model"] == "other"


@pytest.mark.skipif(not os.path.isdir(REAL), reason="no real evo dirs on this box")
def test_the_real_toolboxes_build_and_leak_nothing():
    doc = lab.build(REAL)
    assert 1 <= doc["totals"]["bots"] <= 100
    assert doc["totals"]["kinds"] >= 5
    assert doc["totals"]["snapshots"] >= doc["totals"]["tools"]
    assert all(t["distinct_implementations"] <= t["bots"] for t in doc["taxonomy"])
    blob = json.dumps(doc)
    assert os.path.expanduser("~") not in blob and "def " not in blob
    # No filesystem path may reach the page. A bare "/" is not the test: a model
    # id is legitimately "vendor/model" and appears here once bot.json exists.
    assert not [s for s in strings(doc)
                if s.startswith(("/", "~", "./", "../")) or "/home/" in s or "\\" in s]
