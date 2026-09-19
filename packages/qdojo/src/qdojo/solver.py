"""Run a player's solver: riddle JSON on stdin, {"answer": ...} on stdout."""
import json
import subprocess

from . import hashing


class SolverError(Exception):
    """`exit_code` and `stderr` are filled when a process actually ran and
    failed, so a recorder can file them without parsing the message."""
    exit_code = None
    stderr = ""


def run_solver(command: list[str], riddle_public: dict, timeout: float = 60.0):
    """The canonical answer, or raise SolverError. Never raises anything else."""
    try:
        p = subprocess.run(command, input=json.dumps(riddle_public).encode("utf-8"), capture_output=True,
                           timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise SolverError(f"solver timed out after {timeout}s")
    except OSError as e:
        raise SolverError(f"solver could not start: {e}")
    if p.returncode != 0:
        err = SolverError(f"solver exited {p.returncode}: {p.stderr.decode('utf-8', 'replace')[-300:]}")
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
