#!/usr/bin/env python3
"""A fighter whose whole behaviour is two text files.

Identical plumbing to openai_compat.py -- stdlib urllib, any OpenAI-compatible
endpoint -- with one difference that is the entire point: it does not contain
its prompts. It reads `solver-system.md` and `solver-user.md`, so the thing you
change to get better is prose, not Python.

Because the dojo runs a solver as a fresh process per riddle, an edit is live
on the very next round. Nothing to restart.

There is deliberately NO fallback prompt baked in here. A default string would
be a second copy of the prompt, and the two would drift; a missing file is a
loud, obvious failure instead.

Env: OPENAI_BASE_URL (default OpenRouter), OPENAI_MODEL (required),
OPENAI_API_KEY (or OPENROUTER_API_KEY; a local endpoint needs none),
OPENAI_TIMEOUT, OPENAI_TEMPERATURE, QDOJO_PROMPTS (where your prompts live).
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "packages", "qdojo", "src"))
try:
    from qdojo import prompts
except ImportError:
    print("prompted.py: cannot import qdojo.prompts — run me through `uv run` from the checkout,"
          " or set PYTHONPATH to packages/qdojo/src", file=sys.stderr)
    sys.exit(2)

riddle = json.load(sys.stdin)
base = os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
model = os.environ.get("OPENAI_MODEL")
if not model:
    print("prompted.py: set OPENAI_MODEL — refusing to guess an endpoint's default model", file=sys.stderr)
    sys.exit(2)
key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or "no-key-needed"
timeout = float(os.environ.get("OPENAI_TIMEOUT", "150"))

try:
    system_t, system_p = prompts.load("solver-system.md")
    user_t, user_p = prompts.load("solver-user.md")
except prompts.PromptError as e:
    print(f"prompted.py: {e}", file=sys.stderr)
    sys.exit(2)

values = {k: riddle.get(k, "") for k in ("title", "statement", "input", "answer_format", "round_id")}
system = prompts.render(system_t, values)
prompt = prompts.render(user_t, values)

body = json.dumps({"model": model, "temperature": float(os.environ.get("OPENAI_TEMPERATURE", "0")),
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": prompt}]}).encode()
req = urllib.request.Request(base + "/chat/completions", data=body, method="POST", headers={
    "Content-Type": "application/json", "Authorization": "Bearer " + key,
    "HTTP-Referer": "https://github.com/qdojo", "X-Title": "qdojo"})
try:
    with urllib.request.urlopen(req, timeout=timeout) as r:
        doc = json.loads(r.read().decode("utf-8"))
except urllib.error.HTTPError as e:                 # the body says WHY: no credit, unknown model, bad key
    print(f"{base}: HTTP {e.code} {e.read().decode('utf-8', 'replace')[:300]}", file=sys.stderr)
    sys.exit(1)
except (urllib.error.URLError, OSError, ValueError) as e:
    print(f"{base}: {e}", file=sys.stderr)
    sys.exit(1)

try:
    text = doc["choices"][0]["message"]["content"] or ""
except (KeyError, IndexError, TypeError):
    print("no choices in response: " + json.dumps(doc)[:300], file=sys.stderr)
    sys.exit(1)
for line in reversed([l.strip().strip("`") for l in text.splitlines() if l.strip()]):
    if line.startswith("{") and line.endswith("}"):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "answer" in d:
            print(json.dumps({"answer": d["answer"]}))
            sys.exit(0)
# The contract sentence in solver-system.md is what makes this work. If you
# edited it away, this is where it shows up.
print(f"no JSON answer in model output (prompts: {os.path.basename(system_p)}, "
      f"{os.path.basename(user_p)}): " + " | ".join(text.splitlines()[-3:])[:300], file=sys.stderr)
sys.exit(1)
