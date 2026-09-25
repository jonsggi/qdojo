"""The owner-run planner process (docs/api.md §1): observation in, plan out.

One JSON object on stdin, then stdin closes; exactly one JSON object on
stdout, then exit. The response is parsed strictly: an unknown key, a
lowercase action name, a float or boolean power slot, extra output, a
nonzero exit or a timeout all fail. A planner never receives a salt, key or
the opponent's live plan, and its output is never shell-evaluated.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass

from .. import portable
from .engine import validate_plan
from .types import NO_POWER, Action, FighterState, Plan, PlanError

OBSERVATION_SCHEMA = "qdojo.combat.observation.v1"
PLAN_SCHEMA = "qdojo.combat.plan.v1"
DEFAULT_BUDGET_MS = 1500
STDOUT_CAP = 4096
# The observation written to a planner's stdin stays under this. Opponent
# scouting (opponent_history) is the only unbounded-looking part and is trimmed
# to fit well inside it (scouting.MAX_BYTES).
OBSERVATION_CAP = 64 * 1024
STDERR_CAP = 64 * 1024
FALLBACK = Plan.of([Action.RECOVER] * 6)

# Diagnostics are kept locally, but a planner that echoes a seed or key into
# stderr should not get it into a log: 55+ uppercase letters is a Qubic seed
# or identity, 64 hex digits is a salt or private key.
_SECRETISH = re.compile(r"\b(?:[a-z]{55}|[A-Z]{55,60}|[0-9a-fA-F]{64})\b")


class PlannerError(Exception):
    def __init__(self, code: str, detail: str = "", stderr: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.stderr = stderr


def redact(text: str) -> str:
    return _SECRETISH.sub("[redacted]", text)


def parse_plan(text: str) -> Plan:
    """Strict qdojo.combat.plan.v1. Raises PlannerError(BAD_PLAN)."""
    try:
        doc = json.loads(text, parse_float=_no_float, parse_constant=_no_float)
    except (ValueError, TypeError) as exc:
        raise PlannerError("BAD_PLAN", f"not one JSON object: {exc}") from None
    if not isinstance(doc, dict) or set(doc) != {"schema", "actions", "power_slot"}:
        raise PlannerError("BAD_PLAN", "keys must be exactly schema, actions, power_slot")
    if doc["schema"] != PLAN_SCHEMA:
        raise PlannerError("BAD_PLAN", f"schema must be {PLAN_SCHEMA}")
    actions, slot = doc["actions"], doc["power_slot"]
    if not isinstance(actions, list) or not all(isinstance(a, str) for a in actions):
        raise PlannerError("BAD_PLAN", "actions must be a list of action names")
    if type(slot) is not int:
        raise PlannerError("BAD_PLAN", "power_slot must be an integer")
    try:
        return Plan.of(actions, slot)
    except PlanError as exc:
        raise PlannerError("BAD_PLAN", str(exc)) from None


def _no_float(value):
    raise ValueError(f"non-integer number {value!r}")


def plan_json(plan: Plan) -> dict:
    return {"schema": PLAN_SCHEMA, **plan.to_json()}


def fighter_state(side: dict) -> FighterState:
    """The FighterState of an observation's "self" or "opponent" object."""
    return FighterState(side["hp"], side["stamina"], side["opening"], side["guard_streak"],
                        int(side["power_available"]))


def legal_plan(rules, state: FighterState, plan: Plan, fallback: Plan = FALLBACK) -> tuple[Plan, str | None]:
    """The plan the contract will accept for this round-start state, and why it changed.

    Runs the engine's own validate_plan (the check the contract makes at reveal).
    A plan that is legal except for a power slot after the power strike was
    spent keeps its actions and loses the power slot; any other illegal plan is
    replaced by `fallback` (or six RECOVERs if the fallback is illegal too).
    A committed plan the contract rejects at reveal is a forfeit, so nothing
    the bot can know in advance may reach a commitment."""
    try:
        validate_plan(rules, state, plan)
        return plan, None
    except PlanError as exc:
        error = exc
    if isinstance(plan, Plan) and plan.power_slot != NO_POWER and not state.power_available:
        stripped = Plan(plan.actions, NO_POWER)
        try:
            validate_plan(rules, state, stripped)
            return stripped, "power strike already spent: power_slot dropped, actions kept"
        except PlanError:
            pass
    try:
        validate_plan(rules, state, fallback)
    except PlanError:
        fallback = FALLBACK
    return fallback, f"illegal plan ({error}): fallback plan used"


@dataclass(frozen=True)
class PlannerRun:
    plan: Plan
    stderr: str
    elapsed_ms: int


def run(command: list[str], observation: dict, budget_ms: int = DEFAULT_BUDGET_MS) -> PlannerRun:
    """Run once. Raises PlannerError with a stable code; never returns a repaired plan."""
    import time
    resolved = portable.resolve_command(command)
    stdin = json.dumps(observation).encode("utf-8")
    if len(stdin) > OBSERVATION_CAP:
        raise PlannerError("OBSERVATION_TOO_LONG", f"observation is {len(stdin)} bytes; the cap is {OBSERVATION_CAP}")
    started = time.monotonic()
    try:
        p = subprocess.run(resolved, input=stdin,
                           capture_output=True, timeout=budget_ms / 1000, check=False)
    except subprocess.TimeoutExpired:
        raise PlannerError("TIMEOUT", f"no plan within {budget_ms} ms") from None
    except OSError as exc:
        raise PlannerError("NOT_STARTED", str(exc)) from None
    elapsed = int((time.monotonic() - started) * 1000)
    stderr = redact(p.stderr[:STDERR_CAP].decode("utf-8", "replace"))
    if p.returncode != 0:
        raise PlannerError("EXIT", f"planner exited {p.returncode}", stderr)
    if len(p.stdout) > STDOUT_CAP:
        raise PlannerError("TOO_LONG", f"stdout is {len(p.stdout)} bytes; the cap is {STDOUT_CAP}", stderr)
    try:
        text = p.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise PlannerError("BAD_PLAN", "stdout is not UTF-8", stderr) from None
    try:
        plan = parse_plan(text)
    except PlannerError as exc:
        exc.stderr = stderr
        raise
    return PlannerRun(plan, stderr, elapsed)


def run_or_fallback(command, observation, budget_ms=DEFAULT_BUDGET_MS, fallback: Plan = FALLBACK):
    """Inside a fight a planner failure must not become a missed reveal:
    use the owner's fallback (six RECOVERs by default) and say so."""
    try:
        return run(command, observation, budget_ms), None
    except PlannerError as exc:
        return PlannerRun(fallback, exc.stderr, budget_ms), exc
