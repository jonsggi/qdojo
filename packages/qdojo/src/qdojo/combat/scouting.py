"""Opponent scouting for planner observations (docs/api.md §1, "opponent_history").

Built only from what was public before the current round started: fights that
had finished (phase DONE) strictly before the round's start tick, and the
plans those fights revealed. Never the fight being played, never a live or
sealed plan. Deterministic for a given contract state and round: fights are
taken newest first by fight id, and the size is bounded (MAX_FIGHTS fights,
MAX_PLANS revealed plans, MAX_BYTES of JSON), so the whole observation stays
under planner.OBSERVATION_CAP.
"""
from __future__ import annotations

import json

from . import codec
from .engine import resolve_round
from .types import SUBMITTED

SCHEMA = "qdojo.combat.scouting.v1"
MAX_FIGHTS = 10
MAX_PLANS = 60          # revealed plans of the scouted fighter, summed over the fights
MAX_BYTES = 24 * 1024


def _outcome(fight, slot: str) -> str:
    """The fight's result from the scouted fighter's side: W, L, D, FW/FL (won/lost by forfeit), DF, VOID."""
    r = fight.result or {}
    kind, winner = r.get("kind"), r.get("winner")
    if kind == "VOID":
        return "VOID"
    if kind == "DOUBLE_FAULT":
        return "DF"
    if kind == "FORFEIT":
        return "FW" if winner == slot else "FL"
    if winner is None:
        return "D"
    return "W" if winner == slot else "L"


def fight_summary(c, fight, slot: str) -> dict:
    """One finished fight from `slot`'s side: its revealed plans and what executed."""
    other = "B" if slot == "A" else "A"
    rounds = []
    for r in fight.rounds:
        start = r["start"]
        plans = {s: codec.decode_plan(r["plans"][s]) for s in "AB"}
        res = resolve_round(c.m.ruleset, start, plans["A"], plans["B"])
        mine = start.a if slot == "A" else start.b
        rounds.append({
            "round_index": start.round_index,
            "start": {"hp": mine.hp, "stamina": mine.stamina, "power_available": bool(mine.power_available)},
            "plan": plans[slot].to_json(),
            "executed": [(b.a if slot == "A" else b.b).effective.name for b in res.beats],
            "versus": [(b.b if slot == "A" else b.a).effective.name for b in res.beats],
        })
    ctx = fight.context
    opp = ctx.participant_b if slot == "A" else ctx.participant_a
    r = fight.result or {}
    return {"fight_id": str(fight.fight_id), "mode": codec.Mode(ctx.mode).name.lower(), "slot": slot,
            "opponent_id": opp.fighter_id.hex(), "outcome": _outcome(fight, slot),
            "result": r.get("result") or r.get("kind"), "rounds": rounds}


def summarize(fights: list[dict]) -> dict:
    """Action counts of the scouted fighter's revealed plans, per round index; power timing."""
    by_round: dict[str, dict[str, int]] = {}
    power = {"used_in_round": {}, "never": 0}
    for f in fights:
        used = False
        for r in f["rounds"]:
            counts = by_round.setdefault(str(r["round_index"]), {a.name: 0 for a in SUBMITTED})
            for a in r["plan"]["actions"]:
                counts[a] += 1
            if r["plan"]["power_slot"] != -1:
                used = True
                k = str(r["round_index"])
                power["used_in_round"][k] = power["used_in_round"].get(k, 0) + 1
        if f["rounds"] and not used:
            power["never"] += 1
    record = {}
    for f in fights:
        record[f["outcome"]] = record.get(f["outcome"], 0) + 1
    return {"fights": len(fights), "record": record, "plan_actions_by_round": by_round, "power": power}


class Scout:
    """Per-contract cache of finished-fight summaries (a DONE fight never changes)."""

    def __init__(self):
        self.cache: dict[tuple[int, str], dict] = {}

    def history(self, c, fighter_id: bytes, exclude_fight: int, as_of_tick: int) -> dict:
        fights, plans = [], 0
        for fid in reversed(list(c.fights)):
            if len(fights) >= MAX_FIGHTS or plans >= MAX_PLANS:
                break
            f = c.fights[fid]
            if fid == exclude_fight or f.phase != "DONE" or not f.result or f.result.get("tick", as_of_tick) >= as_of_tick:
                continue
            slot = f.slot_of(fighter_id)
            if slot is None:
                continue
            key = (fid, slot)
            summary = self.cache.get(key)
            if summary is None:
                if len(self.cache) > 20_000:               # bounded on a long-running arena
                    self.cache.clear()
                summary = self.cache[key] = fight_summary(c, f, slot)
            if plans + len(summary["rounds"]) > MAX_PLANS:
                break
            fights.append(summary)
            plans += len(summary["rounds"])
        doc = {"schema": SCHEMA, "fighter_id": fighter_id.hex(), "as_of_tick": str(as_of_tick),
               "fights": fights, "summary": summarize(fights)}
        while fights and len(json.dumps(doc, separators=(",", ":"))) > MAX_BYTES:
            fights.pop()                                   # drop the oldest until it fits
            doc["summary"] = summarize(fights)
        return doc


def empty(fighter_id: bytes | None, as_of_tick=None) -> dict:
    return {"schema": SCHEMA, "fighter_id": fighter_id.hex() if fighter_id else None,
            "as_of_tick": None if as_of_tick is None else str(as_of_tick), "fights": [], "summary": summarize([])}


def action_frequencies(history: dict) -> dict[str, dict[str, float]]:
    """Share of each action in the scouted plans, per round index (for prompts and simple planners)."""
    out = {}
    for k, counts in history.get("summary", {}).get("plan_actions_by_round", {}).items():
        total = sum(counts.values())
        if total:
            out[k] = {a: counts[a] / total for a in counts}
    return out


__all__ = ["SCHEMA", "MAX_FIGHTS", "MAX_PLANS", "MAX_BYTES", "Scout", "empty", "fight_summary", "summarize",
           "action_frequencies"]
