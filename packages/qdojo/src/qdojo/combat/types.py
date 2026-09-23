"""Combat values: actions, fighter state, plans, traces and outcomes.

All of it is immutable and integer. A state outside its range is rejected,
never clamped into plausibility (docs/combat.md §7).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum

from .rules import Ruleset


class Action(IntEnum):
    JAB = 0
    KICK = 1
    BLOCK = 2
    DUCK = 3
    THROW = 4
    RECOVER = 5
    EXHAUSTED = 6   # internal: an unaffordable action; never submitted


SUBMITTED = tuple(Action)[:6]
ATTACKS = frozenset({Action.JAB, Action.KICK, Action.THROW})
NO_POWER = -1


class Reason(str, Enum):
    HIT = "HIT"
    BLOCKED = "BLOCKED"
    EVADED = "EVADED"
    THROW_INTERRUPTED = "THROW_INTERRUPTED"
    THROW_CLASH = "THROW_CLASH"
    INSUFFICIENT_STAMINA = "INSUFFICIENT_STAMINA"
    RECOVERY_PUNISHED = "RECOVERY_PUNISHED"
    GUARD_STRAIN = "GUARD_STRAIN"
    OPENING_EARNED = "OPENING_EARNED"
    OPENING_USED = "OPENING_USED"
    OPENING_EXPIRED = "OPENING_EXPIRED"
    POWER_USED = "POWER_USED"
    POWER_WASTED = "POWER_WASTED"
    KO = "KO"
    DOUBLE_KO = "DOUBLE_KO"


class Result(str, Enum):
    KO = "KO"                 # exactly one fighter at zero HP
    DOUBLE_KO = "DOUBLE_KO"   # both at zero on the same beat: a draw
    HP = "HP"                 # after the last round, higher HP wins
    HP_TIE = "HP_TIE"         # after the last round, equal HP: a draw


class StateError(ValueError):
    """An impossible fighter or fight state."""


class PlanError(ValueError):
    """A plan that makes its reveal invalid: wrong length, unknown action, bad power slot."""


def _check(name, value, cap):
    if type(value) is not int or not 0 <= value <= cap:
        raise StateError(f"{name}={value!r} is outside 0..{cap}")


@dataclass(frozen=True)
class FighterState:
    hp: int
    stamina: int
    opening: int
    guard_streak: int
    power_available: int

    @classmethod
    def initial(cls, rules: Ruleset) -> "FighterState":
        return cls(*rules.initial)

    def validate(self, rules: Ruleset) -> "FighterState":
        _check("hp", self.hp, rules.max_hp)
        _check("stamina", self.stamina, rules.max_stamina)
        _check("opening", self.opening, 1)
        _check("guard_streak", self.guard_streak, rules.max_guard_streak)
        _check("power_available", self.power_available, 1)
        return self

    def to_json(self) -> dict:
        return {"hp": self.hp, "stamina": self.stamina, "opening": self.opening,
                "guard_streak": self.guard_streak, "power_available": self.power_available}


@dataclass(frozen=True)
class Plan:
    actions: tuple[Action, ...]
    power_slot: int = NO_POWER

    @classmethod
    def of(cls, actions, power_slot: int = NO_POWER) -> "Plan":
        """Build from action IDs or names. Shape is checked here; state-dependent
        legality (power still available) is checked by engine.validate_plan."""
        actions = tuple(actions)
        if len(actions) != 6:
            raise PlanError(f"a plan has exactly six actions, got {len(actions)}")
        out = []
        for a in actions:
            if isinstance(a, str):
                if a not in Action.__members__ or a == "EXHAUSTED":
                    raise PlanError(f"unknown action {a!r}")
                out.append(Action[a])
            elif type(a) is int or isinstance(a, Action):
                if not 0 <= int(a) <= 5:
                    raise PlanError(f"unknown action id {a!r}")
                out.append(Action(int(a)))
            else:
                raise PlanError(f"unknown action {a!r}")
        if type(power_slot) is not int or not NO_POWER <= power_slot <= 5:
            raise PlanError(f"power_slot must be -1 or 0..5, got {power_slot!r}")
        if power_slot != NO_POWER and out[power_slot] not in ATTACKS:
            raise PlanError(f"power_slot {power_slot} selects {out[power_slot].name}, not an attack")
        return cls(tuple(out), power_slot)

    def to_json(self) -> dict:
        return {"actions": [a.name for a in self.actions], "power_slot": self.power_slot}


@dataclass(frozen=True)
class SideTrace:
    """One fighter's half of a beat, in that fighter's own orientation."""
    before: FighterState
    after: FighterState
    intended: Action
    effective: Action
    power: bool             # this was the designated power slot (spent even if it failed)
    cost: int               # full cost of the intended action, including power
    cost_paid: int          # 0 when exhausted
    base_damage: int        # dealt, from the matrix
    bonus_damage: int       # opening + power, only when base > 0
    computed_damage: int    # dealt, base + bonus
    actual_hp_lost: int     # received, after clamping at zero
    strain: int             # stamina actually removed by guard strain
    recovered: int          # stamina actually gained after the cap
    reasons: tuple[Reason, ...]

    def to_json(self) -> dict:
        return {
            "before": self.before.to_json(), "after": self.after.to_json(),
            "intended": self.intended.name, "effective": self.effective.name,
            "power": self.power, "cost": self.cost, "cost_paid": self.cost_paid,
            "base_damage": self.base_damage, "bonus_damage": self.bonus_damage,
            "computed_damage": self.computed_damage, "actual_hp_lost": self.actual_hp_lost,
            "strain": self.strain, "recovered": self.recovered,
            "reasons": [r.value for r in self.reasons],
        }


@dataclass(frozen=True)
class BeatTrace:
    index: int
    a: SideTrace
    b: SideTrace

    def to_json(self) -> dict:
        return {"beat": self.index, "A": self.a.to_json(), "B": self.b.to_json()}


@dataclass(frozen=True)
class Outcome:
    winner: str | None    # "A", "B" or None for a draw
    result: Result

    def to_json(self) -> dict:
        return {"winner": self.winner, "result": self.result.value}


@dataclass(frozen=True)
class FightState:
    """Round-start state: the thing a round's commitments are bound to."""
    round_index: int
    a: FighterState
    b: FighterState
    outcome: Outcome | None = None

    def to_json(self) -> dict:
        return {"round_index": self.round_index, "A": self.a.to_json(), "B": self.b.to_json(),
                "outcome": self.outcome.to_json() if self.outcome else None}


@dataclass(frozen=True)
class RoundResult:
    start: FightState
    plan_a: Plan
    plan_b: Plan
    beats: tuple[BeatTrace, ...]
    end: FightState                     # next round's start, or the terminal state
    break_recovery: tuple[int, int] = field(default=(0, 0))   # stamina actually added, A and B

    @property
    def executed(self) -> int:
        return len(self.beats)

    def to_json(self) -> dict:
        return {
            "round_index": self.start.round_index,
            "start": self.start.to_json(),
            "plans": {"A": self.plan_a.to_json(), "B": self.plan_b.to_json()},
            "executed_beats": self.executed,
            "beats": [b.to_json() for b in self.beats],
            "break_recovery": {"A": self.break_recovery[0], "B": self.break_recovery[1]},
            "end": self.end.to_json(),
        }
