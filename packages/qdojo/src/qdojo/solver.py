"""Run a player's solver: riddle JSON on stdin, {"answer": ...} on stdout."""
import json
import subprocess

from . import hashing, portable


class SolverError(Exception):
    """`exit_code` and `stderr` are filled when a process actually ran and
    failed, so a recorder can file them without parsing the message."""
    exit_code = None
    stderr = ""


def run_solver(command: list[str], riddle_public: dict, timeout: float = 60.0):
    """The canonical answer, or raise SolverError. Never raises anything else.

    The command is resolved for this machine first (portable.resolve_command):
    a leading `python3` on a Windows box, or `python` on a Linux one, means
    the Python qdojo runs on, so one profile works on both. When that swaps
    the recorded interpreter for a different one (a BYO venv that has moved
    or vanished, not just the routine bare-token case), a failure says so,
    so it reads as a missing interpreter rather than an unrelated error from
    the wrong Python."""
    resolved = portable.resolve_command(command)
    swap = f"{command[0]} is not on this machine, ran under {resolved[0]}: " \
        if resolved and command and resolved[0] != command[0] else ""
    try:
        p = subprocess.run(resolved, input=json.dumps(riddle_public).encode("utf-8"),
                           capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise SolverError(f"solver timed out after {timeout}s")
    except OSError as e:
        raise SolverError(f"{swap}solver could not start: {e}")
    if p.returncode != 0:
        err = SolverError(f"{swap}solver exited {p.returncode}: {p.stderr.decode('utf-8', 'replace')[-300:]}")
        err.exit_code, err.stderr = p.returncode, p.stderr.decode("utf-8", "replace")[-300:]
        raise err
    line = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if not line:
        raise SolverError("solver printed nothing")
    try:
        d = json.loads(line[-1])
    except json.JSONDecodeError:
        raise SolverError(f"solver output is not JSON: {line[-1][:100]!r}")
    if not isinstance(d, dict) or "answer" not in d:
        raise SolverError("solver JSON has no 'answer'")
    try:
        return hashing.canonical_answer(d["answer"], riddle_public["answer_format"])
    except hashing.CanonicalError as e:
        raise SolverError(f"solver answer rejected: {e}")
