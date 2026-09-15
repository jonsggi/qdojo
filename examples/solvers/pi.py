#!/usr/bin/env python3
"""An LLM-driven solver using the `pi` coding agent (default model from pi's
settings). Env: PI_TOOLS ("" = pure LLM, "bash" = agent with a shell),
PI_THINKING (off/low/medium/high), PI_TIMEOUT seconds, PI_MODEL optional."""
import json
import os
import subprocess
import sys
import tempfile

riddle = json.load(sys.stdin)
tools = os.environ.get("PI_TOOLS", "")
thinking = os.environ.get("PI_THINKING", "low")
timeout = float(os.environ.get("PI_TIMEOUT", "150"))
model = os.environ.get("PI_MODEL")

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
with tempfile.TemporaryDirectory() as cwd:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        print("pi timed out", file=sys.stderr); sys.exit(2)
lines = [l.strip() for l in p.stdout.splitlines() if l.strip()]
for line in reversed(lines):
    if line.startswith("{") and line.endswith("}"):
        try:
            d = json.loads(line)
            if "answer" in d:
                print(json.dumps({"answer": d["answer"]})); sys.exit(0)
        except json.JSONDecodeError:
            continue
print("no JSON answer in pi output: " + " | ".join(lines[-3:])[:300], file=sys.stderr)
sys.exit(1)
