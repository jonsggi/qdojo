"""An LLM-driven combat planner process (docs/api.md §1) via OpenRouter.

  OPEN_ROUTER_API_KEY=... python -m qdojo.combat.llm_planner --model deepseek/deepseek-v4-flash \
      --state ~/.qdojo/combat/llm/ken --daily-usd 1.00
  ... --model anthropic/claude-sonnet-5 --prompt planner-system-claude.md --reasoning off

Reads one observation on stdin, prints one plan. A model answer is used only
if it parses as a plan; it is then checked against the fighter's state with
the engine's validate_plan (a spent power slot is dropped, anything else
illegal falls back). Otherwise, and whenever the day's spend cap is
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

from . import npcs, planner, scouting
from .engine import resolve_beat
from .rules import CANDIDATE_1, RulesetError, by_digest, candidate_1
from .types import Action, FighterState

PROMPTS = Path(__file__).resolve().parents[5] / "prompts/combat"
PROMPT = PROMPTS / "planner-system.md"
URL = "https://openrouter.ai/api/v1/chat/completions"


def _rules(obs: dict):
    """The ruleset the observation names (candidate 1 when it names none this
    package knows): projections, fallbacks and the legality check use it."""
    try:
        return by_digest(str(obs.get("ruleset_digest")))
    except RulesetError:
        return candidate_1()


def prompt_for(prompt: Path, obs: dict) -> Path:
    """A ruleset other than candidate 1 uses the prompt's "-<ruleset suffix>"
    sibling when one exists (planner-system.md -> planner-system-candidate-2.md),
    so the model is told the numbers of the game it is actually playing."""
    rules = _rules(obs)
    if rules.semantic_version == CANDIDATE_1:
        return prompt
    variant = prompt.with_name(f"{prompt.stem}-{rules.semantic_version.removeprefix('combat-v1-')}{prompt.suffix}")
    return variant if variant.exists() else prompt


def _power_line(side: dict, who: str) -> str:
    if side["power_available"]:
        return f"{who} power_available: true (the once-per-fight power strike is still unused)"
    if who == "Your":
        return ("Your power_available: false — you have ALREADY USED your power strike; "
                "power_slot must be -1")
    return f"{who} power_available: false (already used)"


def _pct(counts: dict) -> str:
    total = sum(counts.values())
    if not total:
        return "none"
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ", ".join(f"{a} {100 * n // total}%" for a, n in ranked if n)


def _scouting_lines(obs: dict) -> list[str]:
    """A compact scouting report from observation.opponent_history."""
    hist = obs.get("opponent_history") or {}
    fights = hist.get("fights") or []
    if not fights:
        return ["Scouting: no finished fights of this opponent on record."]
    summ = hist.get("summary") or scouting.summarize(fights)
    rec = summ.get("record", {})
    record = " ".join(f"{k}{v}" for k, v in sorted(rec.items()))
    lines = [f"Scouting: opponent's last {len(fights)} finished fight(s), newest first; their record {record}."]
    for k, counts in sorted(summ.get("plan_actions_by_round", {}).items()):
        lines.append(f"  Round {int(k) + 1} plans: {_pct(counts)}.")
    power = summ.get("power", {})
    used = power.get("used_in_round", {})
    if used or power.get("never"):
        where = ", ".join(f"round {int(k) + 1} in {n}" for k, n in sorted(used.items()))
        lines.append(f"  Power strike used: {where or 'never'}; unused in {power.get('never', 0)} fight(s).")
    r = obs["round_index"]
    same = [(f, x) for f in fights for x in f["rounds"] if x["round_index"] == r][:4]
    if same:
        lines.append(f"  Their recent round-{r + 1} plans (newest first):")
        for f, x in same:
            p = x["plan"]
            power_txt = f", power on beat {p['power_slot'] + 1}" if p["power_slot"] != -1 else ""
            lines.append(f"    fight {f['fight_id']} ({f['outcome']}): {' '.join(p['actions'])}{power_txt}")
    distinct = {tuple(x["plan"]["actions"]) for f in fights for x in f["rounds"]}
    total = sum(len(f["rounds"]) for f in fights)
    if total >= 3 and len(distinct) == 1:
        lines.append("  They played the SAME plan in every scouted round: expect it again.")
    elif total >= 3:
        lines.append(f"  {len(distinct)} distinct plans in {total} scouted rounds.")
    return lines


def _expected_plan(obs: dict) -> tuple[list[str], str] | None:
    """The opponent plan most worth projecting: their plan last round in this
    fight, else their most recent scouted plan for this round index."""
    other = "B" if obs["self_slot"] == "A" else "A"
    if obs.get("prior_rounds"):
        return obs["prior_rounds"][-1]["plans"][other]["actions"], "their plan from last round"
    for f in (obs.get("opponent_history") or {}).get("fights", []):
        for r in f["rounds"]:
            if r["round_index"] == obs["round_index"]:
                return r["plan"]["actions"], f"their round-{obs['round_index'] + 1} plan from fight {f['fight_id']}"
    return None


def _projection_line(obs: dict) -> str | None:
    """Their stamina, beat by beat, if they repeat that plan and are never hit
    (their best case): where they would be EXHAUSTED, and open to 18 from a KICK."""
    guess = _expected_plan(obs)
    if guess is None:
        return None
    actions, source = guess
    rules = _rules(obs)
    them = planner.fighter_state(obs["opponent"])
    # A fresh, blocking stand-in each beat: it never hits them, so their
    # recoveries are the unhit kind and nothing but their own plan moves them.
    wall = FighterState(rules.max_hp, rules.max_stamina, 0, 0, 0)
    staminas, exhausted = [them.stamina], []
    for i, name in enumerate(actions):
        them, _, tr = resolve_beat(rules, them, wall, Action[name], Action.BLOCK)
        staminas.append(them.stamina)
        if tr.a.effective is Action.EXHAUSTED:
            exhausted.append(i + 1)
    line = (f"Projection: if the opponent repeats {source} ({' '.join(actions)}) and is never hit, "
            f"their stamina goes {'->'.join(map(str, staminas))}")
    if exhausted:
        line += f"; they could NOT pay for beat(s) {', '.join(map(str, exhausted))} and would be EXHAUSTED there"
    return line + "."


def _user_prompt(obs: dict) -> str:
    me, opp = obs["self"], obs["opponent"]
    me_slot = obs["self_slot"]
    other = "B" if me_slot == "A" else "A"
    lines = [f"Round {obs['round_index'] + 1} of 3.",
             f"You: HP {me['hp']}, stamina {me['stamina']}, opening {me['opening']}, "
             f"block streak {me['guard_streak']}.",
             _power_line(me, "Your") + ".",
             f"Opponent: HP {opp['hp']}, stamina {opp['stamina']}, opening {opp['opening']}, "
             f"block streak {opp['guard_streak']}.",
             _power_line(opp, "Opponent") + "."]
    for r in obs.get("prior_rounds", []):
        plans = r.get("plans", {})
        mine = [b[me_slot]["effective"] for b in r["beats"]]
        theirs = [b[other]["effective"] for b in r["beats"]]
        start, end = r.get("start", {}), r.get("end", {})
        line = f"Round {r['round_index'] + 1}: you played {' '.join(mine)}; opponent played {' '.join(theirs)}."
        if plans:
            pp = plans[other]
            line += (f" Opponent's revealed plan: {' '.join(pp['actions'])}"
                     + (f" (power on beat {pp['power_slot'] + 1})" if pp["power_slot"] != -1 else "") + ".")
        if start and end:
            line += (f" HP you {start[me_slot]['hp']}->{end[me_slot]['hp']},"
                     f" opponent {start[other]['hp']}->{end[other]['hp']}.")
        lines.append(line)
    lines += _scouting_lines(obs)
    projection = _projection_line(obs)
    if projection:
        lines.append(projection)
    lines.append("Choose your six actions for this round.")
    return "\n".join(lines)


def _extract_json(text: str) -> str:
    """The last JSON object in the reply that has an "actions" key (a model may
    think aloud before it), else the outermost {...} span."""
    dec, found, i = json.JSONDecoder(), None, text.find("{")
    while i >= 0:
        try:
            doc, end = dec.raw_decode(text, i)
        except ValueError:
            i = text.find("{", i + 1)
            continue
        if isinstance(doc, dict) and "actions" in doc:
            found = text[i:end]
        i = text.find("{", end)
    if found is not None:
        return found
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise planner.PlannerError("BAD_PLAN", "no JSON object in the model reply")
    return text[start:end + 1]


def _model_plan(text: str):
    """The plan in a model reply. Only "actions" and "power_slot" are read; a
    short free-text key such as "read" is allowed and ignored."""
    try:
        doc = json.loads(_extract_json(text))
    except ValueError as exc:
        raise planner.PlannerError("BAD_PLAN", f"reply is not JSON: {exc}") from None
    if not isinstance(doc, dict) or "actions" not in doc:
        raise planner.PlannerError("BAD_PLAN", "reply lacks actions")
    actions, power_slot, notes = _normalise(doc["actions"], doc.get("power_slot", -1))
    for n in notes:
        print(f"repaired: {n}", file=sys.stderr)
    body = {"schema": planner.PLAN_SCHEMA, "actions": actions, "power_slot": power_slot}
    return planner.parse_plan(json.dumps(body)), doc.get("read")


ATTACKS = ("JAB", "KICK", "THROW")


def _normalise(actions, power_slot):
    """Repair the harmless slips models make, so a sound read of the fight is
    not thrown away for a spelling: lower case and spaces in names, a
    "POWER JAB" style name (becomes the power slot when none is set), a power
    slot as a string, and a power slot on a move that cannot carry power
    (dropped). Anything else is left for parse_plan to reject."""
    notes = []
    if not isinstance(actions, list):
        return actions, power_slot, notes
    out = []
    for i, a in enumerate(actions):
        if isinstance(a, str):
            name = a.strip().upper().replace("-", " ").replace("_", " ")
            if name.startswith("POWER ") or name.endswith(" POWER") or name.endswith("*"):
                base = name.replace("POWER", "").replace("*", "").strip()
                if base in ATTACKS:
                    if power_slot in (-1, None, "-1"):
                        power_slot = i
                    notes.append(f"action {a!r} read as {base} with the power slot")
                    name = base
            if name != a:
                a = name
        out.append(a)
    if isinstance(power_slot, str) and power_slot.lstrip("-").isdigit():
        power_slot = int(power_slot)
    if power_slot is None:
        power_slot = -1
    if isinstance(power_slot, int) and 0 <= power_slot < len(out) and out[power_slot] not in ATTACKS:
        notes.append(f"power_slot {power_slot} selects {out[power_slot]}, not an attack: dropped")
        power_slot = -1
    return out, power_slot, notes


def _fallback(obs: dict, why: str) -> dict:
    print(f"fallback to mixed-v1: {why}", file=sys.stderr)
    rules = _rules(obs)
    s, o = planner.fighter_state(obs["self"]), planner.fighter_state(obs["opponent"])
    seed = hashlib.sha256(json.dumps(obs, sort_keys=True).encode()).digest()
    plan = npcs.mixed_v1(rules, npcs.Observation(obs["round_index"], s, o), npcs.Stream(seed, 0, obs["round_index"]))
    return planner.plan_json(plan)


class Spend:
    """USD spent per UTC day, from OpenRouter's usage accounting; the last 60 days are kept."""

    def __init__(self, state: Path):
        self.path = state / "spend.json"
        self.day = dt.datetime.now(dt.timezone.utc).date().isoformat()
        try:
            doc = json.loads(self.path.read_text())
        except (OSError, ValueError):
            doc = {}
        self.doc = {k: float(v) for k, v in doc.items() if isinstance(v, (int, float))}
        self.today = self.doc.get(self.day, 0.0)

    def add(self, usd: float):
        self.today += usd
        self.doc[self.day] = self.today
        self.doc = dict(sorted(self.doc.items())[-60:])
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.doc))
        os.replace(tmp, self.path)


def request_body(model: str, obs: dict, prompt: Path = PROMPT, reasoning: str = "low",
                 max_tokens: int = 1200) -> dict:
    system = prompt.read_text()
    anthropic = model.startswith("anthropic/")
    body = {"model": model, "max_tokens": max_tokens, "usage": {"include": True},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": _user_prompt(obs)}]}
    if anthropic:
        # The system prompt is the same for every round: cache it (a cache read
        # costs a tenth of an input token), and leave sampling at the model
        # default. The Claude prompt lets the model reason briefly in the reply
        # before the JSON object; the last JSON object with "actions" is read.
        body["messages"][0]["content"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        body["messages"][1]["content"] += "\nThink briefly if you need to, then end with the JSON object."
    else:
        body["temperature"] = 0.7
        body["response_format"] = {"type": "json_object"}
        body["messages"][1]["content"] += "\nAnswer with the JSON object only."
    # Little or no hidden reasoning: a reasoning model otherwise spends the
    # whole token budget before answering.
    # "none" sends no setting (the model's default); "off" turns reasoning off
    # outright (a Claude model otherwise thinks adaptively, ~500 tokens a call).
    if reasoning == "off":
        body["reasoning"] = {"enabled": False}
    elif reasoning != "none":
        body["reasoning"] = {"effort": reasoning, "exclude": True}
    return body


def ask(model: str, obs: dict, timeout: float, spend: "Spend", prompt: Path = PROMPT, reasoning: str = "low",
        max_tokens: int = 1200) -> dict:
    """One model call. Its cost is recorded even when the reply is unusable.
    The plan is checked against this fighter's state before it is returned."""
    key = os.environ.get("OPEN_ROUTER_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise planner.PlannerError("NOT_STARTED", "no OpenRouter key in the environment")
    import time
    started = time.monotonic()

    def call(reasoning_now: str) -> str:
        body = request_body(model, obs, prompt, reasoning_now, max_tokens)
        req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                              "X-Title": "qdojo combat demo"})
        left = max(1.0, timeout - (time.monotonic() - started))
        with urllib.request.urlopen(req, timeout=left) as resp:
            doc = json.loads(resp.read())
        usage = doc.get("usage") or {}
        cost = float(usage.get("cost") or 0.0)
        spend.add(cost)
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
        choice = doc["choices"][0]
        print(f"{model}: ${cost:.5f} (today ${spend.today:.4f}); tokens in {usage.get('prompt_tokens')}"
              f"{f' ({cached} cached)' if cached else ''}, out {usage.get('completion_tokens')}"
              f", finish {choice.get('finish_reason')}", file=sys.stderr)
        return choice["message"].get("content") or ""

    text = call(reasoning)
    try:
        plan, read = _model_plan(text)
    except planner.PlannerError as exc:
        # An empty or prose-only reply is usually hidden reasoning that used
        # the token budget: one more try with reasoning off, if time allows.
        print(f"unusable reply ({exc}); first 160 chars: {text[:160]!r}", file=sys.stderr)
        if reasoning == "off" or time.monotonic() - started > timeout / 2:
            raise
        text = call("off")
        plan, read = _model_plan(text)
    if read:
        print(f"read: {str(read)[:200]}", file=sys.stderr)
    return legal(obs, plan)


def legal(obs: dict, plan) -> dict:
    """The contract's own plan check, applied before the plan leaves the planner."""
    plan, why = planner.legal_plan(_rules(obs), planner.fighter_state(obs["self"]), plan)
    if why:
        print(f"adjusted: {why}", file=sys.stderr)
    return planner.plan_json(plan)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", required=True, help="OpenRouter model id, e.g. anthropic/claude-sonnet-5")
    p.add_argument("--state", required=True, help="directory for the daily spend record")
    p.add_argument("--daily-usd", type=float, default=1.0)
    p.add_argument("--timeout", type=float, default=20.0)
    p.add_argument("--prompt", help="system prompt: a path, or a name under prompts/combat "
                                    "(default planner-system.md)")
    p.add_argument("--reasoning", default="low", choices=("none", "off", "minimal", "low", "medium", "high"),
                   help="hidden reasoning effort; none sends no reasoning setting, off disables reasoning")
    p.add_argument("--max-tokens", type=int, default=1200)
    a = p.parse_args()
    obs = json.load(sys.stdin)
    prompt = PROMPT
    if a.prompt:
        prompt = Path(os.path.expanduser(a.prompt))
        if not prompt.is_absolute() and not prompt.exists():
            prompt = PROMPTS / a.prompt
    state = Path(os.path.expanduser(a.state))
    state.mkdir(parents=True, exist_ok=True)
    spend = Spend(state)
    if spend.today >= a.daily_usd:
        out = _fallback(obs, f"daily cap ${a.daily_usd:.2f} reached")
    else:
        try:
            out = ask(a.model, obs, a.timeout, spend, prompt_for(prompt, obs), a.reasoning, a.max_tokens)
        except Exception as exc:        # any model, network or parse failure: play the local policy
            out = _fallback(obs, f"{type(exc).__name__}: {str(exc)[:160]}")
    print(json.dumps(out))


if __name__ == "__main__":
    main()
