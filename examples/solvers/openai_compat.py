#!/usr/bin/env python3
"""A solver that speaks OpenAI chat-completions, with the standard library and
nothing else. One file covers OpenRouter, Ollama, LM Studio, vLLM and every
direct provider that speaks that shape — no pi, no pip install.

Env: OPENAI_BASE_URL (default OpenRouter), OPENAI_MODEL (required),
OPENAI_API_KEY (or OPENROUTER_API_KEY; a local endpoint needs none),
OPENAI_TIMEOUT seconds, OPENAI_TEMPERATURE.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request


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

riddle = json.load(sys.stdin)
base = os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
model = os.environ.get("OPENAI_MODEL")
if not model:
    print("openai_compat.py: set OPENAI_MODEL — refusing to guess an endpoint's default model", file=sys.stderr)
    sys.exit(2)
key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or "no-key-needed"
timeout = float(os.environ.get("OPENAI_TIMEOUT", "150"))

system = ("You are a fighter in a riddle dojo. Solve the riddle exactly as stated. Think and compute as needed. "
          "Your FINAL line must be ONLY a JSON object of the form {\"answer\": VALUE}: VALUE is a JSON number for "
          "integer format, a JSON string for string or hex format. Nothing after that line.")
prompt = (f"Title: {riddle['title']}\nAnswer format: {riddle['answer_format']}\n\n"
          f"Statement:\n{riddle['statement']}\n\nInput:\n{riddle['input']}\n")
body = json.dumps({"model": model, "temperature": float(os.environ.get("OPENAI_TEMPERATURE", "0")),
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}).encode()
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
answer = answer_from(text)
if answer is not None:
    print(json.dumps({"answer": answer}))
    sys.exit(0)
print("no JSON answer in model output: " + " | ".join(text.splitlines()[-3:])[:300], file=sys.stderr)
sys.exit(1)
