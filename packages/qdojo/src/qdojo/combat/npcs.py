"""Disclosed practice opponents (docs/npcs.md §2) and their training PRNG (§3).

An NPC is an ordinary planner: it sees the same public observation a player
bot sees and returns a legal six-action plan. It gets no extra HP, no view of
the opponent's live plan and no move a player lacks; difficulty is policy.

The PRNG is for reproducible practice only. Live commitment salts come from
secrets.token_bytes, never from here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Sequence

from ..hashing import sha256
from .engine import action_cost, resolve_beat
from .rules import Ruleset
from .types import ATTACKS, NO_POWER, SUBMITTED, Action, FighterState, Plan

TAG_NPC = b"qdojo/npc/v1\0"

J, K, B, D, T, R = Action.JAB, Action.KICK, Action.BLOCK, Action.DUCK, Action.THROW, Action.RECOVER
MIXED_WEIGHTS = (3, 2, 2, 2, 1, 2)
MIXED_LOW_WEIGHTS = (1, 0, 2, 2, 0, 5)
MIXED_LOW_STAMINA = 12
POWER_MARGIN = 4
POWER_ROUND = 2


class Stream:
    """SHA256(tag || seed || fight u64 || round u8 || counter u32), bytes consumed in order."""

    def __init__(self, seed: bytes, fight_number: int, round_index: int):
        if len(seed) != 32:
            raise ValueError("an NPC seed is 32 bytes")
        self.prefix = TAG_NPC + seed + fight_number.to_bytes(8, "little") + bytes([round_index])
        self.counter = 0
        self.buf = b""
        self.at = 0

    def byte(self) -> int:
        if self.at == len(self.buf):
            self.buf = sha256(self.prefix, self.counter.to_bytes(4, "little"))
            self.counter += 1
            self.at = 0
        self.at += 1
        return self.buf[self.at - 1]

    def uniform(self, n: int) -> int:
        if not 1 <= n <= 256:
            raise ValueError("uniform takes 1..256")
        limit = 256 - (256 % n)
        while True:
            v = self.byte()
            if v < limit:
                return v % n

    def weighted(self, weights: Sequence[int]) -> int:
        """Index by cumulative integer buckets in order."""
        x = self.uniform(sum(weights))
        for i, w in enumerate(weights):
            if x < w:
                return i
            x -= w
        raise AssertionError("unreachable")


@dataclass(frozen=True)
class Observation:
    """What an NPC may use: public, confirmed, this fight only."""
    round_index: int
    self_state: FighterState
    opponent_state: FighterState
    opponent_history: tuple[tuple[Action, ...], ...] = ()   # executed effective actions per prior round
    slot: str = "A"
    prior: tuple = ()     # this fight's completed RoundResults, A/B orientation


Policy = Callable[[Ruleset, Observation, Stream], Plan]


def _hp_floor(s: FighterState) -> FighterState:
    """Projection only: keep a projected KO from shortening a six-action plan."""
    return s if s.hp > 0 else replace(s, hp=1)


def _project(rules, me, opp, action, opp_action, power):
    me2, opp2, trace = resolve_beat(rules, me, opp, action, opp_action, power, False)
    return _hp_floor(me2), _hp_floor(opp2), trace


def _wants_power(rules, obs, me, action, have_slot) -> bool:
    return (obs.round_index == POWER_ROUND and not have_slot and me.power_available
            and action in ATTACKS and me.stamina >= action_cost(rules, me, action, False) + POWER_MARGIN)


def fixed(pattern: Sequence[Action]) -> Policy:
    pattern = tuple(pattern)

    def policy(rules, obs, rng):
        slot = NO_POWER
        if obs.round_index == POWER_ROUND and obs.self_state.power_available:
            slot = next((i for i, a in enumerate(pattern) if a in ATTACKS), NO_POWER)
        return Plan.of(pattern, slot)
    return policy


def random_v1(rules, obs, rng):
    actions = [SUBMITTED[rng.uniform(6)] for _ in range(6)]
    slot = NO_POWER
    if obs.self_state.power_available:
        eligible = [NO_POWER] + [i for i, a in enumerate(actions) if a in ATTACKS]
        slot = eligible[rng.uniform(len(eligible))]
    return Plan.of(actions, slot)


def _mixed_action(me, rng):
    weights = MIXED_LOW_WEIGHTS if me.stamina < MIXED_LOW_STAMINA else MIXED_WEIGHTS
    return SUBMITTED[rng.weighted(weights)]


def mixed_v1(rules, obs, rng):
    """Weighted draws, re-weighted when its own projected stamina runs low.
    The projection assumes an opponent who only RECOVERs: a resource estimate,
    not a prediction of the opponent."""
    me, opp = obs.self_state, obs.opponent_state
    actions, slot = [], NO_POWER
    for i in range(6):
        a = _mixed_action(me, rng)
        power = _wants_power(rules, obs, me, a, slot != NO_POWER)
        if power:
            slot = i
        actions.append(a)
        me, opp, _ = _project(rules, me, opp, a, R, power)
    return Plan.of(actions, slot)


def opponent_counts(history) -> list[int]:
    """One pseudocount per legal action plus every executed effective action; EXHAUSTED omitted."""
    counts = [1] * 6
    for round_actions in history:
        for a in round_actions:
            if a is not Action.EXHAUSTED:
                counts[int(a)] += 1
    return counts


def scout_v1(rules, obs, rng):
    """Best one-beat reply to the opponent's observed action mix, 3/4 of the time.

    Per beat the draws are, in order: uniform(4) for greedy-vs-mixed; then
    either uniform(#maximisers) or the mixed-v1 weighted draw.
    """
    if not obs.opponent_history:
        return mixed_v1(rules, obs, rng)
    counts = opponent_counts(obs.opponent_history)
    modal = SUBMITTED[max(range(6), key=lambda i: (counts[i], -i))]
    me, opp = obs.self_state, obs.opponent_state
    actions, slot = [], NO_POWER
    for i in range(6):
        if rng.uniform(4) < 3:
            scores = []
            for cand in SUBMITTED:
                total = 0
                for opp_action in SUBMITTED:
                    n = counts[int(opp_action)]
                    me2, _, tr = resolve_beat(rules, me, opp, cand, opp_action)
                    total += n * (4 * (tr.a.computed_damage - tr.b.computed_damage) + me2.stamina - me.stamina)
                scores.append(total)
            best = max(scores)
            tied = [SUBMITTED[k] for k, s in enumerate(scores) if s == best]
            a = tied[rng.uniform(len(tied))] if len(tied) > 1 else tied[0]
        else:
            a = _mixed_action(me, rng)
        power = _wants_power(rules, obs, me, a, slot != NO_POWER)
        if power:
            slot = i
        actions.append(a)
        me, opp, _ = _project(rules, me, opp, a, modal, power)
    return Plan.of(actions, slot)


@dataclass(frozen=True)
class NPC:
    id: str
    behavior: str
    lesson: str
    policy: Policy


ROSTER: dict[str, NPC] = {n.id: n for n in (
    NPC("random-v1", "Uniform independent actions, optional random power timing",
        "Learn rules; benchmark against an unstructured opponent", random_v1),
    NPC("jabber-v1", "JAB,JAB,JAB,RECOVER,JAB,JAB each round",
        "Punish predictable highs with duck/counter", fixed((J, J, J, R, J, J))),
    NPC("turtle-v1", "BLOCK,BLOCK,RECOVER,BLOCK,DUCK,RECOVER",
        "Use throw, low attacks and guard pressure", fixed((B, B, R, B, D, R))),
    NPC("kicker-v1", "KICK,RECOVER,KICK,RECOVER,KICK,RECOVER",
        "Punish expensive attacks and recovery timing", fixed((K, R, K, R, K, R))),
    NPC("mixed-v1", "Stateful weighted policy", "Test basic resource-aware optimization", mixed_v1),
    NPC("scout-v1", "Adapt next-round action distribution from past observations",
        "Train against an opponent that changes strategy", scout_v1),
)}


def plan_for(npc_id: str, rules: Ruleset, obs: Observation, seed: bytes, fight_number: int) -> Plan:
    if npc_id not in ROSTER:
        raise KeyError(f"unknown NPC {npc_id!r}; known: {', '.join(ROSTER)}")
    return ROSTER[npc_id].policy(rules, obs, Stream(seed, fight_number, obs.round_index))
