"""An LLM-driven combat planner process (docs/api.md §1) via OpenRouter.

  OPEN_ROUTER_API_KEY=... python -m qdojo.combat.llm_planner --model deepseek/deepseek-v4-flash \
      --state ~/.qdojo/combat/llm/ken --daily-usd 1.00

Reads one observation on stdin, prints one plan. A model answer is used only
if it parses as a legal plan. Otherwise, and whenever the day's spend cap is
reached, the plan comes from the local mixed-v1 policy, with the reason on
stderr. That keeps the fighter playing instead of falling back to six idle
RECOVERs. Spend is read from OpenRouter's usage accounting and kept per UTC
day in the state directory. No key, seed or salt is ever printed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

from . import npcs, planner
from .rules import candidate_1
from .types import FighterState

PROMPT = Path(__file__).resolve().parents[5] / "prompts/combat/planner-system.md"
URL = "https://openrouter.ai/api/v1/chat/completions"


def _user_prompt(obs: dict) -> str:
    me, opp = obs["self"], obs["opponent"]
    other = "B" if obs["self_slot"] == "A" else "A"
    lines = [f"Round {obs['round_index'] + 1} of 3.",
             f"You: HP {me['hp']}, stamina {me['stamina']}, opening {me['opening']}, "
             f"block streak {me['guard_streak']}, power {'available' if me['power_available'] else 'used'}.",
             f"Opponent: HP {opp['hp']}, stamina {opp['stamina']}, opening {opp['opening']}, "
             f"block streak {opp['guard_streak']}, power {'available' if opp['power_available'] else 'used'}."]
    for r in obs.get("prior_rounds", []):
        mine = [b[obs["self_slot"]]["effective"] for b in r["beats"]]
        theirs = [b[other]["effective"] for b in r["beats"]]
        lines.append(f"Round {r['round_index'] + 1}: you played {' '.join(mine)}; opponent played {' '.join(theirs)}.")
    lines.append("Choose your six actions for this round.")
    return "\n".join(lines)


def _extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise planner.PlannerError("BAD_PLAN", "no JSON object in the model reply")
    return text[start:end + 1]


def _fallback(obs: dict, why: str) -> dict:
    print(f"fallback to mixed-v1: {why}", file=sys.stderr)
    rules = candidate_1()
    me, opp = obs["self"], obs["opponent"]
    s = FighterState(me["hp"], me["stamina"], me["opening"], me["guard_streak"], int(me["power_available"]))
    o = FighterState(opp["hp"], opp["stamina"], opp["opening"], opp["guard_streak"], int(opp["power_available"]))
    seed = hashlib.sha256(json.dumps(obs, sort_keys=True).encode()).digest()
    plan = npcs.mixed_v1(rules, npcs.Observation(obs["round_index"], s, o), npcs.Stream(seed, 0, obs["round_index"]))
    return planner.plan_json(plan)


class Spend:
    def __init__(self, state: Path):
        self.path = state / "spend.json"
        self.day = dt.datetime.now(dt.timezone.utc).date().isoformat()
        try:
            doc = json.loads(self.path.read_text())
        except (OSError, ValueError):
            doc = {}
        self.today = float(doc.get(self.day, 0.0))
        self.doc = {self.day: self.today}

    def add(self, usd: float):
        self.today += usd
        self.doc[self.day] = self.today
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.doc))
        os.replace(tmp, self.path)


def ask(model: str, obs: dict, timeout: float, spend: "Spend") -> dict:
    """One model call. Its cost is recorded even when the reply is unusable."""
    key = os.environ.get("OPEN_ROUTER_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise planner.PlannerError("NOT_STARTED", "no OpenRouter key in the environment")
    # JSON mode where the provider supports it, and little hidden reasoning: a
    # reasoning model otherwise spends the whole token budget before answering.
    body = {"model": model, "temperature": 0.7, "max_tokens": 1200, "usage": {"include": True},
            "response_format": {"type": "json_object"}, "reasoning": {"effort": "low", "exclude": True},
            "messages": [{"role": "system", "content": PROMPT.read_text()},
                         {"role": "user", "content": _user_prompt(obs) + "\nAnswer with the JSON object only."}]}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "X-Title": "qdojo combat demo"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        doc = json.loads(resp.read())
    cost = float((doc.get("usage") or {}).get("cost") or 0.0)
    spend.add(cost)
    print(f"{model}: ${cost:.5f} (today ${spend.today:.4f})", file=sys.stderr)
    text = doc["choices"][0]["message"].get("content") or ""
    plan = planner.parse_plan(json.dumps({"schema": planner.PLAN_SCHEMA, **json.loads(_extract_json(text))}))
    return planner.plan_json(plan)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", required=True)
    p.add_argument("--state", required=True, help="directory for the daily spend record")
    p.add_argument("--daily-usd", type=float, default=1.0)
    p.add_argument("--timeout", type=float, default=20.0)
    a = p.parse_args()
    obs = json.load(sys.stdin)
    state = Path(os.path.expanduser(a.state))
    state.mkdir(parents=True, exist_ok=True)
    spend = Spend(state)
    if spend.today >= a.daily_usd:
        out = _fallback(obs, f"daily cap ${a.daily_usd:.2f} reached")
    else:
        try:
            out = ask(a.model, obs, a.timeout, spend)
        except Exception as exc:        # any model, network or parse failure: play the local policy
            out = _fallback(obs, f"{type(exc).__name__}: {str(exc)[:160]}")
    print(json.dumps(out))


if __name__ == "__main__":
    main()
