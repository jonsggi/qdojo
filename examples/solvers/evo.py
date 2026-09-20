#!/usr/bin/env python3
"""A self-evolving fighter. It keeps a toolbox of small Python solvers, one
per riddle kind, that it writes with an LLM the first time it meets a kind
and repairs from the dojo's published answers when one turns out wrong.
The LLM is only consulted to write or fix a tool; solving is done by the
tools, so the mechanical belts cost nothing once learned.

Env: EVO_DIR (toolbox + memory), EVO_MODEL (pi model id), EVO_THINKING,
EVO_BOARD (board URL, to learn from history.json), EVO_TIMEOUT.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

riddle = json.load(sys.stdin)
EVO_DIR = os.path.expanduser(os.environ.get("EVO_DIR", "~/.qdojo/evo"))
MODEL = os.environ.get("EVO_MODEL")
if not MODEL:
    print("evo.py: set EVO_MODEL — refusing to fall back to pi's default model", file=sys.stderr)
    sys.exit(2)
THINKING = os.environ.get("EVO_THINKING", "low")
BOARD = os.environ.get("EVO_BOARD")
ME = os.environ.get("QDOJO_IDENTITY", "")
TIMEOUT = float(os.environ.get("EVO_TIMEOUT", "120"))
TOOLS = os.path.join(EVO_DIR, "tools")
os.makedirs(TOOLS, exist_ok=True)
LOG = os.path.join(EVO_DIR, "evo.log")

# Who this toolbox belongs to. Nothing else on disk ties an evo directory to a
# chain identity or a model, so `qdojo house lab` cannot cross-link the lab to
# the fighter card without it. Rewritten every run; it is never secret.
# Every text file here is opened as UTF-8 by name: on Windows the default is
# the locale's code page, which cannot write a riddle's answer.
with open(os.path.join(EVO_DIR, "bot.json"), "w", encoding="utf-8") as _f:
    json.dump({"name": os.environ.get("QDOJO_NAME") or os.path.basename(os.path.normpath(EVO_DIR)),
               "identity": ME or None, "model": MODEL}, _f, indent=2)


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


def kind_key(r):
    """Riddle kinds share a title shape; numbers and quoted data vary."""
    t = re.sub(r"[0-9]+", "#", r["title"].lower())
    t = re.sub(r"[^a-z# ]+", " ", t)
    return re.sub(r"\s+", "_", t.strip())[:60] + "_" + r["answer_format"]


def tool_path(key):
    return os.path.join(TOOLS, key + ".py")


def run_tool(path, r, timeout=20):
    try:
        p = subprocess.run([sys.executable, path], input=json.dumps(r).encode(), capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "tool timed out"
    out = p.stdout.decode("utf-8", "replace").strip().splitlines()
    for line in reversed(out):
        try:
            d = json.loads(line)
            if isinstance(d, dict) and "answer" in d and d["answer"] not in (None, ""):
                return d["answer"], None
        except json.JSONDecodeError:
            continue
    return None, (p.stderr.decode("utf-8", "replace")[-400:] or "no JSON answer")


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


def ask_llm(prompt, system):
    args = ["pi", "-p", "--no-session", "--no-tools", "--thinking", THINKING, "--system-prompt", system]
    if MODEL:
        args += ["--model", MODEL]
    args.append(prompt)
    held = _slot()
    with tempfile.TemporaryDirectory() as cwd:
        try:
            p = subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT, cwd=cwd)
        except subprocess.TimeoutExpired:
            return ""
    return p.stdout


def extract_code(text):
    m = re.search(r"```(?:python)?\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip() + "\n"


SYSTEM = ("You write small, robust Python 3 programs. Output ONLY a python code block, no prose. The program reads "
          "a riddle as JSON from stdin with fields title, statement, input, answer_format (integer|string|hex) and "
          "prints exactly one line: a JSON object {\"answer\": VALUE} (number for integer, string otherwise). "
          "It must solve EVERY riddle of this kind, for any input values, by parsing the statement and input; "
          "never hard-code this instance's numbers. Use only the standard library. No network.")


def write_tool(key, r, prev_code=None, failure=None):
    prompt = (f"Riddle kind key: {key}\n\nExample riddle (JSON):\n{json.dumps(r, ensure_ascii=False)}\n")
    if prev_code:
        prompt += f"\nYour previous program:\n```python\n{prev_code}```\nIt failed: {failure}\nFix it so it is correct for this example AND every riddle of the kind."
    else:
        prompt += "\nWrite the program."
    code = extract_code(ask_llm(prompt, SYSTEM))
    if not code.strip() or "answer" not in code:
        return False
    path = tool_path(key)
    with open(path + ".v" + str(int(time.time())), "w", encoding="utf-8") as f:
        f.write(code)
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    return True


def learn():
    """Repair at most one tool per invocation from published results:
    every settled round where I answered wrong is a labelled example."""
    if not BOARD or not ME:
        return
    try:
        base = BOARD.rsplit("/", 1)[0]
        with urllib.request.urlopen(base + "/history.json", timeout=15) as f:
            hist = json.load(f)
    except Exception:
        return
    seen_path = os.path.join(EVO_DIR, "learned.json")
    seen = set(json.load(open(seen_path, encoding="utf-8"))) if os.path.exists(seen_path) else set()
    for rd in reversed(hist.get("rounds", [])):
        if rd["state"] != "settled" or not rd.get("riddle"):
            continue
        mine = next((e for e in rd["entries"] if e["identity"] == ME), None)
        if not mine or mine["verdict"] not in ("wrong",) or rd["round_id"] in seen:
            continue
        key = kind_key(rd["riddle"])
        want = rd["settlement"]["answer"]
        seen.add(rd["round_id"])
        json.dump(sorted(seen), open(seen_path, "w", encoding="utf-8"))
        path = tool_path(key)
        prev = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        failure = f"for the example it answered {mine.get('answer')!r} but the correct answer was {want!r}"
        example = dict(rd["riddle"]); example["known_answer"] = want
        if write_tool(key, example, prev, failure):
            got, err = run_tool(path, rd["riddle"])
            log(f"learned round {rd['round_id']} {key}: repaired tool now says {got!r} (want {want!r})")
        return


learn()
key = kind_key(riddle)
path = tool_path(key)
answer, err = (None, "no tool yet")
if os.path.exists(path):
    answer, err = run_tool(path, riddle)
if answer is None:
    prev = open(path, encoding="utf-8").read() if os.path.exists(path) else None
    if write_tool(key, riddle, prev, err if prev else None):
        answer, err = run_tool(path, riddle)
        if answer is None and prev is None and write_tool(key, riddle, open(path, encoding="utf-8").read(), err):
            answer, err = run_tool(path, riddle)
if answer is None:
    log(f"round {riddle.get('round_id')} {key}: no answer ({err})")
    print("evo: no answer: " + str(err)[:200], file=sys.stderr)
    sys.exit(1)
log(f"round {riddle.get('round_id')} {key}: {answer!r}")
print(json.dumps({"answer": answer}))
