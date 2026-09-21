import sys

import pytest

from qdojo.solver import run_solver, SolverError

RIDDLE = {"round_id": 1, "title": "t", "statement": "s", "input": "1\n2\n3", "answer_format": "integer"}


def py(code):
    return [sys.executable, "-c", code]


def test_solver_roundtrip_canonicalises():
    cmd = py("import json,sys; r=json.load(sys.stdin); print(json.dumps({'answer': ' 0' + str(sum(map(int, r['input'].split())))}))")
    assert run_solver(cmd, RIDDLE) == "6"


def test_solver_last_line_is_the_answer():
    cmd = py("print('debug noise'); print('{\"answer\": 7}')")
    assert run_solver(cmd, RIDDLE) == "7"


def test_solver_failures_are_solver_errors():
    with pytest.raises(SolverError) as e:
        run_solver(py("import sys; print('why', file=sys.stderr); sys.exit(3)"), RIDDLE)
    assert e.value.exit_code == 3 and e.value.stderr.strip() == "why"    # filed by the bot's recorder
    with pytest.raises(SolverError):
        run_solver(py("print('not json')"), RIDDLE)
    with pytest.raises(SolverError):
        run_solver(py("print('{\"nope\": 1}')"), RIDDLE)
    with pytest.raises(SolverError):
        run_solver(py("print('{\"answer\": \"abc\"}')"), RIDDLE)  # integer format
    with pytest.raises(SolverError):
        run_solver(py("import time; time.sleep(3)"), RIDDLE, timeout=0.5)
    with pytest.raises(SolverError):
        run_solver(["/nonexistent/solver"], RIDDLE)


def test_a_swapped_interpreter_is_named_in_the_failure(monkeypatch):
    """A BYO solver's own venv that has moved is swapped for qdojo's own
    Python (portable.resolve_command); when it then fails, the message must
    say the recorded interpreter is not here rather than leave the failure
    looking like an unrelated bug in the wrong Python."""
    gone = "/definitely/gone/solver-venv/bin/python3"
    with pytest.raises(SolverError) as e:
        run_solver([gone, "-c", "import sys; sys.exit(5)"], RIDDLE)
    assert gone in str(e.value) and "ran under" in str(e.value) and sys.executable in str(e.value)
    # a python that IS runnable is left alone, and no swap note appears
    with pytest.raises(SolverError) as e2:
        run_solver(py("import sys; sys.exit(5)"), RIDDLE)
    assert "ran under" not in str(e2.value)
