"""The LLM solvers must accept the answer object however the model wraps it.

Round 121 scored KEN-2 no_commit because its model printed the right answer
pretty-printed over three lines and pi.py only read single-line objects. Each
script is exercised for real here: a fake `pi` on PATH plays the model.
"""
import json
import os
import stat
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PI_PY = os.path.join(ROOT, "examples", "solvers", "pi.py")
RIDDLE = {"title": "t", "statement": "s", "input": "1 2", "answer_format": "integer"}


def _fake_pi(tmp_path, stdout):
    d = tmp_path / "bin"; d.mkdir()
    fake = d / "pi"
    fake.write_text("#!/bin/sh\ncat <<'EOF'\n" + stdout + "\nEOF\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return str(d)


def _run(tmp_path, model_output):
    env = dict(os.environ, PATH=_fake_pi(tmp_path, model_output) + os.pathsep + os.environ.get("PATH", ""),
               PI_MODEL="fake/model", PI_MAX_CONCURRENT="1")
    p = subprocess.run([sys.executable, PI_PY], input=json.dumps(RIDDLE).encode(), capture_output=True, env=env, timeout=30)
    return p.returncode, p.stdout.decode().strip(), p.stderr.decode()


def test_one_line_answer_still_works(tmp_path):
    rc, out, _ = _run(tmp_path, 'thinking...\n{"answer": 277}')
    assert rc == 0 and json.loads(out) == {"answer": 277}


def test_pretty_printed_answer_is_read(tmp_path):
    rc, out, _ = _run(tmp_path, 'Final answer:\n{\n  "answer": 277\n}')
    assert rc == 0 and json.loads(out) == {"answer": 277}


def test_fenced_answer_and_the_last_object_wins(tmp_path):
    rc, out, _ = _run(tmp_path, '{"answer": 1}\n...on reflection...\n```json\n{"answer": "deadbeef"}\n```')
    assert rc == 0 and json.loads(out) == {"answer": "deadbeef"}


def test_no_answer_object_is_a_clean_failure(tmp_path):
    rc, out, err = _run(tmp_path, "I could not solve this. {} {\"not\": 1}")
    assert rc == 1 and out == "" and "no JSON answer" in err
