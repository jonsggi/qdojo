"""The owner's combat bot: spend only within limits, commit, reveal, resume.

Rules this module keeps (docs/api.md §2, matchmaking.md §5):
- A plan and its salt are written to the private journal BEFORE the Commit is
  sent, and a restart reuses exactly that plan. Losing the salt never
  authorises a substitute plan; the bot stops and says so.
- Spending is decided by the scheduler against owner budgets. Any failure to
  read state, balance or settings means DENY, never allow.
- A planner failure inside a fight falls back to six RECOVERs so a slow model
  does not become a missed reveal.
- Salts come from `secrets`, never from the training PRNG.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from . import codec, npcs, planner
from .codec import Code, Op
from .rules import Ruleset
from .types import FighterState, Plan

JOURNAL = "secret-plans.jsonl"
BUDGET_STATE = "budget.json"


class BotStop(RuntimeError):
    """A condition that must stop autonomous play until the owner looks."""


# ---- chain access ----------------------------------------------------------

class Client(Protocol):
    network_id: bytes
    contract_id: bytes

    def tick(self) -> int: ...
    def send(self, op: Op, amount: int = 0, **fields): ...
    def fighter(self, fid: bytes) -> dict | None: ...
    def fight(self, fight_id: int) -> dict | None: ...
    def contest(self, contest_id: int) -> dict | None: ...
    def credit(self, who: bytes) -> int: ...
    def balance(self, who: bytes) -> int: ...


# ---- budgets ---------------------------------------------------------------

@dataclass
class Budget:
    """Owner limits. Wins never offset committed stakes."""
    allowed_tiers: tuple[int, ...] = (1,)
    max_stake: int = 1000
    max_total_escrow: int = 1000
    max_daily_committed: int = 10_000
    max_daily_net_loss: int = 5_000
    max_fights_per_day: int = 20
    min_ticks_between_fights: int = 0
    stop_after_faults: int = 1
    min_wallet_reserve: int = 0
    max_rating_gap: int = 200
    offer_lifetime: int = 240
    ruleset_digest: str = ""          # pinned; empty means refuse to enter
    timing_profile_id: int = 1
    fee_profile_id: int = 1


@dataclass
class Spend:
    day: str
    contest_or_offer: str
    stake: int
    returned: int | None = None       # QU credited back to us at settlement, once known


@dataclass
class BudgetState:
    spends: list[Spend] = field(default_factory=list)
    faults: int = 0
    last_entry_tick: int = -10**9

    @classmethod
    def load(cls, path: Path) -> "BudgetState":
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        return cls([Spend(**s) for s in raw["spends"]], raw["faults"], raw["last_entry_tick"])

    def save(self, path: Path):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"spends": [asdict(s) for s in self.spends], "faults": self.faults,
                                   "last_entry_tick": self.last_entry_tick}))
        os.replace(tmp, path)


def decide(budget: Budget, st: BudgetState, day: str, tick: int, stake: int, tier: int,
           wallet: int | None, rules_digest: str) -> tuple[bool, str]:
    """The participation scheduler. Returns (allow, reason); unknowns deny."""
    if wallet is None:
        return False, "wallet balance unreadable"
    if not budget.ruleset_digest or budget.ruleset_digest != rules_digest:
        return False, "ruleset not pinned to this contract's"
    if st.faults >= budget.stop_after_faults:
        return False, f"stopped after {st.faults} protocol fault(s)"
    if tier not in budget.allowed_tiers or stake > budget.max_stake:
        return False, "tier or stake not allowed"
    outstanding = sum(s.stake for s in st.spends if s.returned is None)
    if outstanding + stake > budget.max_total_escrow:
        return False, "total escrow limit"
    today = [s for s in st.spends if s.day == day]
    if sum(s.stake for s in today) + stake > budget.max_daily_committed:
        return False, "daily committed-stake limit"
    # Unsettled stakes count as lost until proven otherwise.
    net = sum((s.returned or 0) - s.stake for s in today)
    if -net + stake > budget.max_daily_net_loss:
        return False, "daily net-loss limit"
    if len(today) >= budget.max_fights_per_day:
        return False, "daily fight limit"
    if tick - st.last_entry_tick < budget.min_ticks_between_fights:
        return False, "cooldown between fights"
    if wallet - stake < budget.min_wallet_reserve:
        return False, "wallet reserve"
    return True, "ok"


# ---- the secret plan journal -------------------------------------------------

class PlanJournal:
    """Private, append-only, fsynced. Never exported, never logged."""

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.dir, 0o700)
        self.path = self.dir / JOURNAL
        self.records: dict[tuple, dict] = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue          # torn tail
                    self.records[(rec["network"], rec["contract"], rec["fight_id"], rec["round"])] = rec

    def get(self, key):
        return self.records.get(key)

    def put(self, rec: dict):
        key = (rec["network"], rec["contract"], rec["fight_id"], rec["round"])
        self.records[key] = rec
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (json.dumps(rec, separators=(",", ":")) + "\n").encode())
            os.fsync(fd)
        finally:
            os.close(fd)


# ---- the bot ---------------------------------------------------------------

Choose = Callable[[dict], Plan]


@dataclass
class Bot:
    client: Client
    rules: Ruleset
    fighter_id: bytes
    operator: bytes
    wallet: bytes
    choose: Choose                     # observation dict -> Plan
    budget: Budget
    state_dir: Path
    clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.timezone.utc)
    tier: int = 1
    log: Callable[[str], None] = lambda m: None

    def __post_init__(self):
        self.journal = PlanJournal(self.state_dir)
        self.bpath = Path(self.state_dir) / BUDGET_STATE
        self.bstate = BudgetState.load(self.bpath)
        self.salt_source = secrets.token_bytes

    def step(self) -> str:
        """One observation/action cycle. Returns what it did."""
        try:
            tick = self.client.tick()
            me = self.client.fighter(self.fighter_id)
        except Exception as exc:                            # unreadable state: do nothing
            return f"state unreadable: {exc}"
        if me is None:
            return "fighter not registered"
        self._settle_known()
        if me["lock"] == "CONTEST":
            return self._fight_step(me, tick)
        if me["lock"] == "IDLE":
            return self._maybe_enter(me, tick)
        return f"waiting ({me['lock']})"

    # -- spending -----------------------------------------------------------

    def _maybe_enter(self, me: dict, tick: int) -> str:
        stake = self.client.tier_amount(self.tier) if hasattr(self.client, "tier_amount") else None
        if stake is None:
            return "deny: tier price unknown"
        try:
            wallet = self.client.balance(self.wallet)
        except Exception:
            wallet = None
        day = self.clock().astimezone(dt.timezone.utc).date().isoformat()
        ok, why = decide(self.budget, self.bstate, day, tick, stake, self.tier, wallet, self.rules.digest.hex())
        if not ok:
            return "deny: " + why
        spend = Spend(day, "pending", stake)
        self.bstate.spends.append(spend)
        self.bstate.last_entry_tick = tick
        self.bstate.save(self.bpath)                        # reserve before sending
        r = self.client.send(Op.QUEUE_ENTER, stake, fighter_id=self.fighter_id, auth_version=me["auth_version"],
                             ruleset_digest=self.rules.digest, timing_profile_id=self.budget.timing_profile_id,
                             fee_profile_id=self.budget.fee_profile_id, tier_id=self.tier,
                             max_gap=self.budget.max_rating_gap, expires_tick=tick + self.budget.offer_lifetime)
        if r.code not in (Code.OK, Code.DUPLICATE):
            spend.returned = stake                          # rejected: the attachment came back as credit
            self.bstate.save(self.bpath)
            return f"entry rejected: {r.code.name}"
        spend.contest_or_offer = f"offer:{r.data['offer_id']}"
        self.bstate.save(self.bpath)
        return f"entered offer {r.data['offer_id']}"

    def _settle_known(self):
        changed = False
        for s in self.bstate.spends:
            if s.returned is not None or s.contest_or_offer == "pending":
                continue
            outcome = self.client.spend_outcome(s.contest_or_offer, self.fighter_id)
            if outcome is not None and outcome[0] == "contest":
                s.contest_or_offer = outcome[1]
                changed = True
                outcome = self.client.spend_outcome(s.contest_or_offer, self.fighter_id)
            if outcome is None:
                continue
            kind, value = outcome
            s.returned = value
            if kind == "fault":
                self.bstate.faults += 1
            changed = True
        if changed:
            self.bstate.save(self.bpath)

    # -- fighting -----------------------------------------------------------

    def _fight_step(self, me: dict, tick: int) -> str:
        fight = self.client.fight(me["active_fight"]) if me.get("active_fight") else None
        if fight is None or fight["phase"] == "DONE":
            return "contest between fights"
        key = (self.client.network_id.hex(), self.client.contract_id.hex(), fight["fight_id"], fight["round_index"])
        rec = self.journal.get(key)
        slot = fight["slot_of"][self.fighter_id.hex()]
        if fight["phase"] == "COMMIT":
            if slot in fight["committed"]:
                return "committed; waiting for the reveal window"
            if tick <= fight["start_tick"] or tick > fight["commit_last"]:
                return "outside the commit window"
            if rec is None:
                obs = fight["observation"](slot)
                plan = self.choose(obs)
                salt = self.salt_source(32)
                commitment = codec.commitment(
                    network_id=self.client.network_id, contract_id=self.client.contract_id,
                    fight_id=fight["fight_id"], round_index=fight["round_index"],
                    context_digest=bytes.fromhex(fight["context_digest"]),
                    round_state_digest=bytes.fromhex(fight["round_state_digest"]),
                    fighter_id=self.fighter_id, operator=self.operator, auth_version=fight["auth_version"][slot],
                    salt=salt, plan=plan)
                rec = {"network": key[0], "contract": key[1], "fight_id": key[2], "round": key[3],
                       "round_state_digest": fight["round_state_digest"], "plan": codec.encode_plan(plan).hex(),
                       "salt": salt.hex(), "commitment": commitment.hex(), "status": "persisted"}
                self.journal.put(rec)                        # BEFORE sending
            if rec["round_state_digest"] != fight["round_state_digest"]:
                raise BotStop("journalled plan belongs to a different round-start state; not substituting")
            r = self.client.send(Op.COMMIT, fight_id=fight["fight_id"], round_index=fight["round_index"],
                                 fighter_id=self.fighter_id, auth_version=fight["auth_version"][slot],
                                 round_state_digest=bytes.fromhex(rec["round_state_digest"]),
                                 commitment=bytes.fromhex(rec["commitment"]))
            self.journal.put({**rec, "status": f"commit:{r.code.name}"})
            return f"commit {r.code.name}"
        if fight["phase"] == "REVEAL":
            if slot in fight["revealed"]:
                return "revealed; waiting for resolution"
            if rec is None:
                raise BotStop("committed plan/salt missing from the journal; cannot reveal (no substitute)")
            r = self.client.send(Op.REVEAL, fight_id=fight["fight_id"], round_index=fight["round_index"],
                                 fighter_id=self.fighter_id, auth_version=fight["auth_version"][slot],
                                 round_state_digest=bytes.fromhex(rec["round_state_digest"]),
                                 salt=bytes.fromhex(rec["salt"]), plan=codec.decode_plan(bytes.fromhex(rec["plan"])))
            self.journal.put({**rec, "status": f"reveal:{r.code.name}"})
            return f"reveal {r.code.name}"
        return fight["phase"]


def policy_chooser(rules: Ruleset, policy: npcs.Policy, seed: bytes) -> Choose:
    """Adapt an in-process policy to the observation dict."""
    def choose(obs: dict) -> Plan:
        me, opp = obs["self"], obs["opponent"]
        s = FighterState(me["hp"], me["stamina"], me["opening"], me["guard_streak"], int(me["power_available"]))
        o = FighterState(opp["hp"], opp["stamina"], opp["opening"], opp["guard_streak"], int(opp["power_available"]))
        other = "B" if obs["self_slot"] == "A" else "A"
        from .types import Action
        history = tuple(tuple(Action[b[other]["effective"]] for b in r["beats"]) for r in obs["prior_rounds"])
        view = npcs.Observation(obs["round_index"], s, o, history, obs["self_slot"])
        return policy(rules, view, npcs.Stream(seed, int(obs["fight_id"]), obs["round_index"]))
    return choose


def planner_chooser(command: list[str], budget_ms: int = planner.DEFAULT_BUDGET_MS) -> Choose:
    def choose(obs: dict) -> Plan:
        ran, err = planner.run_or_fallback(command, obs, budget_ms)
        return ran.plan
    return choose
