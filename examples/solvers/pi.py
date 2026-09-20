#!/usr/bin/env python3
"""An LLM-driven solver using the `pi` coding agent (default model from pi's
settings). Env: PI_TOOLS ("" = pure LLM, "bash" = agent with a shell),
PI_THINKING (off/low/medium/high), PI_TIMEOUT seconds, PI_MODEL optional."""
import json
import os
import re
import subprocess
import sys
import tempfile
import time

riddle = json.load(sys.stdin)
tools = os.environ.get("PI_TOOLS", "")
thinking = os.environ.get("PI_THINKING", "low")
timeout = float(os.environ.get("PI_TIMEOUT", "150"))
model = os.environ.get("PI_MODEL")

def answer_from(text):
    """The answer in a model's output, or None. Models are asked for ONE line,
    {"answer": VALUE}, and most comply; the rest wrap it in a code fence or
    pretty-print it over several lines (round 121: KEN-2 printed the right
    answer as three lines and was scored no_commit for it). So this scans the
    whole output for the LAST JSON object that carries an "answer" key,
    across lines, and takes that -- the last, because a model that thinks
    aloud tends to revise and then finish with its final word."""
    for m in reversed(re.findall(r"\{[^{}]*\}", text, re.S)):
        try:
            d = json.loads(m)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict) and "answer" in d:
            return d["answer"]
    return None
if not model:
    print("pi.py: set PI_MODEL — refusing to fall back to pi's default model", file=sys.stderr)
    sys.exit(2)

system = ("You are a fighter in a riddle dojo. Solve the riddle exactly as stated. "
          "Think and compute as needed" + (" (you may run shell commands)" if tools else "") + ". "
          "Your FINAL line must be ONLY a JSON object of the form {\"answer\": VALUE}: VALUE is a JSON number "
          "for integer format, a JSON string for string or hex format. Nothing after that line.")
prompt = (f"Title: {riddle['title']}\nAnswer format: {riddle['answer_format']}\n\n"
          f"Statement:\n{riddle['statement']}\n\nInput:\n{riddle['input']}\n")
args = ["pi", "-p", "--no-session", "--thinking", thinking, "--system-prompt", system]
args += ["--tools", tools] if tools else ["--no-tools"]
if model:
    args += ["--model", model]
args.append(prompt)
# ---- concurrency limit: the box cannot host every fighter's model process at once
# One lock file per slot under the system temp directory. flock where the OS
# has it; on Windows msvcrt.locking on the first byte does the same job. Both
# are released when the process exits, however it exits.
try:
    import fcntl as _fcntl

    def _try_lock(f):
        _fcntl.flock(f, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
except ImportError:                                     # Windows
    import msvcrt as _msvcrt

    def _try_lock(f):
        f.seek(0)
        _msvcrt.locking(f.fileno(), _msvcrt.LK_NBLCK, 1)

SLOTS = os.path.join(tempfile.gettempdir(), "qdojo-pi-slots")


def _slot(max_slots=int(os.environ.get("PI_MAX_CONCURRENT", "4")), wait=float(os.environ.get("PI_SLOT_WAIT", "90"))):
    """Hold one of max_slots file locks; wait up to `wait` seconds for one."""
    os.makedirs(SLOTS, exist_ok=True)
    deadline = time.time() + wait
    while True:
        for i in range(max_slots):
            try:
                f = open(os.path.join(SLOTS, str(i)), "a")     # never truncate: a locked file cannot be, on Windows
            except OSError:
                continue
            try:
                _try_lock(f)
                return f
            except OSError:
                f.close()
        if time.time() > deadline:
            print("no model slot free", file=sys.stderr); sys.exit(3)
        time.sleep(1.0)


_held = _slot()
with tempfile.TemporaryDirectory() as cwd:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        print("pi timed out", file=sys.stderr); sys.exit(2)
answer = answer_from(p.stdout)
if answer is not None:
    print(json.dumps({"answer": answer})); sys.exit(0)
lines = [l.strip() for l in p.stdout.splitlines() if l.strip()]
print("no JSON answer in pi output: " + " | ".join(lines[-3:])[:300], file=sys.stderr)
sys.exit(1)
