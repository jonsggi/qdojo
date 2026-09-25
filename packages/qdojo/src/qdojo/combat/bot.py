"""The owner's combat bot: spend only within limits, commit, reveal, resume.

Rules this module keeps (docs/api.md §2, matchmaking.md §5):
- A plan and its salt are written to the private journal BEFORE the Commit is
  sent, and a restart reuses exactly that plan. Losing the salt never
  authorises a substitute plan; the bot stops and says so.
- Spending is decided by the scheduler against owner budgets. Any failure to
  read state, balance or settings means DENY, never allow.
- A planner failure inside a fight falls back to six RECOVERs so a slow model
  does not become a missed reveal.
- Every chosen plan is checked with the engine's validate_plan against the
  fighter's round-start state before it is journalled: a spent power slot is
  dropped, any other illegal plan becomes the fallback. The contract would
  reject it at reveal, which is a forfeit.
- A call the contract rejected for good (a bad plan, a late reveal) is never
  re-sent; a rejection that may clear (wrong phase, a busy fighter) is retried
  with exponential backoff; the bot observes its fault cooldown and ranked
  suspension instead of queueing into a rejection every tick.
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
from .engine import resolve_round
from .rules import Ruleset
from .types import Action, FighterState, FightState, Plan, RoundResult

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
    fault_window_ticks: int = 0       # count faults over this many recent ticks; 0 = over the bot's lifetime
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
    fault_ticks: list[int] = field(default_factory=list)   # tick each fault was seen (newest last)

    @classmethod
    def load(cls, path: Path) -> "BudgetState":
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        return cls([Spend(**s) for s in raw["spends"]], raw["faults"], raw["last_entry_tick"],
                   list(raw.get("fault_ticks", [])))

    def save(self, path: Path):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"spends": [asdict(s) for s in self.spends], "faults": self.faults,
                                   "last_entry_tick": self.last_entry_tick,
                                   "fault_ticks": self.fault_ticks[-64:]}))
        os.replace(tmp, path)

    def recent_faults(self, tick: int, window: int) -> int:
        """Faults that count against stop_after_faults: all of them, or those in the last `window` ticks."""
        if window <= 0:
            return self.faults
        return sum(1 for t in self.fault_ticks if tick - t < window)


def decide(budget: Budget, st: BudgetState, day: str, tick: int, stake: int, tier: int,
           wallet: int | None, rules_digest: str) -> tuple[bool, str]:
    """The participation scheduler. Returns (allow, reason); unknowns deny."""
    if wallet is None:
        return False, "wallet balance unreadable"
    if not budget.ruleset_digest or budget.ruleset_digest != rules_digest:
        return False, "ruleset not pinned to this contract's"
    faults = st.recent_faults(tick, budget.fault_window_ticks)
    if faults >= budget.stop_after_faults:
        within = f" in the last {budget.fault_window_ticks} ticks" if budget.fault_window_ticks > 0 else ""
        return False, f"stopped after {faults} protocol fault(s){within}"
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

# A rejection that may clear by itself: retry later, with backoff. Every other
# rejection of a commit or reveal is final for that round and is not re-sent.
RETRYABLE = frozenset({Code.WRONG_PHASE, Code.FULL, Code.NONCE_CONFLICT})
BACKOFF_FIRST, BACKOFF_MAX = 4, 240


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
    play_cups: bool = False          # register for open cups (entry fee within budget), check in, fight
    accept_duels: bool = False       # accept named challenges whose stake is within budget
    ranked: bool = True              # enter the ranked queue when idle

    def __post_init__(self):
        self.journal = PlanJournal(self.state_dir)
        self.bpath = Path(self.state_dir) / BUDGET_STATE
        self.bstate = BudgetState.load(self.bpath)
        self.salt_source = secrets.token_bytes
        # On a real chain a send is a receipt, not a result. In-flight sends by
        # purpose ("enter", ("commit", key), ("reveal", key)); a synchronous
        # client's result counts as included at once.
        self.inflight: dict = {}
        # Backoff after a rejection that may clear: purpose -> (not before tick, delay).
        self.backoff: dict = {}
        self.skip_cups: set = set()          # cups whose registration was rejected

    def planning(self) -> bool:
        """True while a background planner decision is outstanding (started, not yet used)."""
        return bool(self.__dict__.get("_planning"))

    def _backing_off(self, purpose, tick: int) -> bool:
        b = self.backoff.get(purpose)
        return b is not None and tick < b[0]

    def _back_off(self, purpose, tick: int):
        delay = min(BACKOFF_MAX, 2 * self.backoff[purpose][1]) if purpose in self.backoff else BACKOFF_FIRST
        self.backoff[purpose] = (tick + delay, delay)

    def _plan(self, key, fight, slot) -> Plan | None:
        """The plan for this round, checked against this fighter's round-start
        state. A slow chooser (a planner process, maybe a model call) runs in
        the background: None means "not ready yet", so one slow bot never stalls
        the others or the tick. A crashed planner yields the fallback plan, as a
        timed-out one does."""
        planning = self.__dict__.setdefault("_planning", {})
        if not getattr(self.choose, "slow", False):
            obs = fight["observation"](slot)
            try:
                plan = self.choose(obs)
            except Exception as exc:            # a policy bug must not become a missed commit
                self.log(f"fight {fight['fight_id']} round {fight['round_index']}: chooser failed ({exc}); fallback")
                plan = planner.FALLBACK
        else:
            job = planning.get(key)
            if job is None:
                obs = fight["observation"](slot)
                planning[key] = (_planning_pool().submit(self.choose, obs), obs)
                return None
            fut, obs = job
            if not fut.done():
                return None
            del planning[key]
            try:
                plan = fut.result()
            except Exception:
                plan = planner.FALLBACK
        plan, why = planner.legal_plan(self.rules, planner.fighter_state(obs["self"]), plan)
        if why:
            self.log(f"fight {fight['fight_id']} round {fight['round_index']}: {why}")
        return plan

    def _submit(self, purpose, op: Op, amount: int = 0, extra=None, **fields):
        r = self.client.send(op, amount, **fields)
        if getattr(r, "code", None) is None:
            self.inflight[purpose] = (r, extra)
            return None
        return r

    def _poll(self, purpose):
        """(state, extra): state is a CallResult, "dropped", "pending" or None (nothing in flight)."""
        if purpose not in self.inflight:
            return None, None
        receipt, extra = self.inflight[purpose]
        st = self.client.poll(receipt)
        if st is None:
            return "pending", extra
        del self.inflight[purpose]
        return st, extra

    def step(self) -> str:
        """One observation/action cycle. Returns what it did."""
        try:
            tick = self.client.tick()
            me = self.client.fighter(self.fighter_id)
        except Exception as exc:                            # unreadable state: do nothing
            return f"state unreadable: {exc}"
        if me is None:
            return "fighter not registered"
        drained = self._drain_entry()
        if drained is not None and "enter" in self.inflight:
            return drained                                  # still waiting: don't act on stale state
        self._settle_known(tick)
        if me["lock"] == "CONTEST":
            return self._fight_step(me, tick)
        if me["lock"] == "TOURNAMENT":
            return self._tournament_step(me, tick)
        if me["lock"] == "IDLE":
            cooldown = int(me.get("cooldown_until") or 0)
            if tick < cooldown:                             # every paid entry would be rejected
                return f"cooling down after a fault until tick {cooldown}"
            if self.accept_duels:
                done = self._maybe_accept_duel(me, tick)
                if done:
                    return done
            if self.play_cups:
                done = self._maybe_join_cup(me, tick)
                if done:
                    return done
            if not self.ranked:
                return "idle"
            if me.get("suspended"):
                return "ranked admission suspended for this epoch"
            return self._maybe_enter(me, tick)
        return f"waiting ({me['lock']})"

    # -- duels and cups -------------------------------------------------------

    def _spend_allowed(self, tick: int, amount: int) -> tuple[bool, str, str]:
        try:
            wallet = self.client.balance(self.wallet)
        except Exception:
            wallet = None
        day = self.clock().astimezone(dt.timezone.utc).date().isoformat()
        ok, why = decide(self.budget, self.bstate, day, tick, amount, self.tier, wallet, self.rules.digest.hex())
        return ok, why, day

    def _maybe_accept_duel(self, me: dict, tick: int) -> str | None:
        st, extra = self._poll("duel")
        if st == "pending":
            return "duel acceptance waiting for inclusion"
        if st is not None and st != "dropped":
            spend = extra
            if st.code.name in ("OK", "DUPLICATE"):
                spend.contest_or_offer = f"contest:{st.data['contest_id']}"
            else:
                spend.returned = spend.stake
            self.bstate.save(self.bpath)
            return f"duel accept {st.code.name}"
        if st == "dropped":
            extra.returned = extra.stake
            self.bstate.save(self.bpath)
        offers = getattr(self.client, "duel_offers_for", lambda _f: [])(self.fighter_id)
        for o in offers:
            ok, why, day = self._spend_allowed(tick, o["stake"])
            if not ok:
                continue
            spend = Spend(day, "pending", o["stake"])
            self.bstate.spends.append(spend)
            self.bstate.last_entry_tick = tick
            self.bstate.save(self.bpath)
            r = self._submit("duel", Op.DUEL_ACCEPT, o["stake"], extra=spend, offer_id=o["offer_id"],
                             fighter_id=self.fighter_id, auth_version=me["auth_version"])
            if r is None:
                return f"accepting duel offer {o['offer_id']}"
            if r.code.name in ("OK", "DUPLICATE"):
                spend.contest_or_offer = f"contest:{r.data['contest_id']}"
            else:
                spend.returned = spend.stake
            self.bstate.save(self.bpath)
            return f"duel accept {r.code.name}"
        return None

    def _maybe_join_cup(self, me: dict, tick: int) -> str | None:
        st, extra = self._poll("cup")
        if st == "pending":
            return "cup entry waiting for inclusion"
        if st is not None:
            if st == "dropped" or st.code.name not in ("OK", "DUPLICATE"):
                extra.returned = extra.stake
                self.bstate.save(self.bpath)
                if st != "dropped":
                    self.skip_cups.add(int(extra.contest_or_offer.split(":")[1]))
            return None if st == "dropped" else f"cup entry {st.code.name}"
        for k in getattr(self.client, "open_cups", lambda: [])():
            if k["entries"] >= k["max_entrants"] or k["cup_id"] in self.skip_cups:
                continue
            ok, why, day = self._spend_allowed(tick, k["entry_fee"])
            if not ok:
                continue
            spend = Spend(day, f"cup:{k['cup_id']}", k["entry_fee"])
            self.bstate.spends.append(spend)
            self.bstate.last_entry_tick = tick
            self.bstate.save(self.bpath)
            r = self._submit("cup", Op.CUP_REGISTER, k["entry_fee"], extra=spend, cup_id=k["cup_id"],
                             fighter_id=self.fighter_id, auth_version=me["auth_version"])
            if r is None:
                return f"registering for cup {k['cup_id']}"
            if r.code.name not in ("OK", "DUPLICATE"):
                spend.returned = spend.stake
                self.bstate.save(self.bpath)
                self.skip_cups.add(k["cup_id"])
            return f"cup entry {r.code.name}"
        return None

    def _tournament_step(self, me: dict, tick: int) -> str:
        if me.get("active_fight"):
            return self._fight_step(me, tick)
        cup = me.get("cup") or {}
        pid = cup.get("pairing_id")
        if pid is None or cup.get("checked_in"):
            return "waiting in cup"
        if not cup["level_start"] <= tick < cup["level_start"] + cup["checkin_ticks"]:
            return "waiting for check-in"
        st, _ = self._poll(("checkin", cup["cup_id"], pid))
        if st == "pending":
            return "check-in waiting for inclusion"
        r = self._submit(("checkin", cup["cup_id"], pid), Op.CUP_CHECK_IN, cup_id=cup["cup_id"], pairing_id=pid,
                         fighter_id=self.fighter_id, auth_version=me["auth_version"])
        return "check-in sent" if r is None else f"check-in {r.code.name}"

    # -- spending -----------------------------------------------------------

    def _entry_result(self, r, spend: Spend) -> str:
        if r.code not in (Code.OK, Code.DUPLICATE):
            spend.returned = spend.stake                    # rejected: the attachment came back as credit
            self.bstate.save(self.bpath)
            self._back_off("enter", self.client.tick())     # do not re-queue into the same rejection
            return f"entry rejected: {r.code.name}"
        self.backoff.pop("enter", None)
        spend.contest_or_offer = f"offer:{r.data['offer_id']}"
        self.bstate.save(self.bpath)
        return f"entered offer {r.data['offer_id']}"

    def _drain_entry(self) -> str | None:
        """Settle an in-flight queue entry, whatever the fighter's lock says now."""
        st, spend = self._poll("enter")
        if st is None:
            return None
        if st == "pending":
            return "entry waiting for inclusion"
        if st == "dropped":
            spend.returned = spend.stake                    # never included: nothing left the wallet
            self.bstate.save(self.bpath)
            return "entry dropped by the chain; will retry"
        return self._entry_result(st, spend)

    def _maybe_enter(self, me: dict, tick: int) -> str:
        if "enter" in self.inflight:
            return "entry waiting for inclusion"
        if self._backing_off("enter", tick):
            return f"entry backing off until tick {self.backoff['enter'][0]}"
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
        r = self._submit("enter", Op.QUEUE_ENTER, stake, extra=spend, fighter_id=self.fighter_id,
                         auth_version=me["auth_version"], ruleset_digest=self.rules.digest,
                         timing_profile_id=self.budget.timing_profile_id, fee_profile_id=self.budget.fee_profile_id,
                         tier_id=self.tier, max_gap=self.budget.max_rating_gap,
                         expires_tick=tick + self.budget.offer_lifetime)
        if r is None:
            return "entry sent"
        return self._entry_result(r, spend)

    def _settle_known(self, tick: int | None = None):
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
                self.bstate.fault_ticks.append(self.client.tick() if tick is None else tick)
                self.log(f"fault in {s.contest_or_offer}: {self.bstate.faults} in total")
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
                plan = self._plan(key, fight, slot)
                if plan is None:
                    return "planning"
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
            st, _ = self._poll(("commit", key))
            if st == "pending":
                return "commit waiting for inclusion"
            if st is not None and st != "dropped" and st.code not in (Code.OK, Code.DUPLICATE):
                return self._rejected("commit", key, rec, st, tick)
            held = self._holding("commit", key, rec, tick)
            if held:
                return held
            # Not committed yet and nothing in flight (or it was dropped): send. A
            # resend carries the same commitment, which the contract treats as a
            # harmless duplicate, so retrying is always safe.
            r = self._submit(("commit", key), Op.COMMIT, fight_id=fight["fight_id"],
                             round_index=fight["round_index"], fighter_id=self.fighter_id,
                             auth_version=fight["auth_version"][slot],
                             round_state_digest=bytes.fromhex(rec["round_state_digest"]),
                             commitment=bytes.fromhex(rec["commitment"]))
            if r is not None and r.code not in (Code.OK, Code.DUPLICATE):
                return self._rejected("commit", key, rec, r, tick)
            status = "sent" if r is None else r.code.name
            self.journal.put({**rec, "status": f"commit:{status}"})
            return f"commit {status}" + (" (resent after a drop)" if st == "dropped" else "")
        if fight["phase"] == "REVEAL":
            if slot in fight["revealed"]:
                return "revealed; waiting for resolution"
            if rec is None:
                raise BotStop("committed plan/salt missing from the journal; cannot reveal (no substitute)")
            st, _ = self._poll(("reveal", key))
            if st == "pending":
                return "reveal waiting for inclusion"
            if st is not None and st != "dropped" and st.code not in (Code.OK, Code.DUPLICATE):
                return self._rejected("reveal", key, rec, st, tick)
            held = self._holding("reveal", key, rec, tick)
            if held:
                return held
            r = self._submit(("reveal", key), Op.REVEAL, fight_id=fight["fight_id"],
                             round_index=fight["round_index"], fighter_id=self.fighter_id,
                             auth_version=fight["auth_version"][slot],
                             round_state_digest=bytes.fromhex(rec["round_state_digest"]),
                             salt=bytes.fromhex(rec["salt"]), plan=codec.decode_plan(bytes.fromhex(rec["plan"])))
            if r is not None and r.code not in (Code.OK, Code.DUPLICATE):
                return self._rejected("reveal", key, rec, r, tick)
            status = "sent" if r is None else r.code.name
            self.journal.put({**rec, "status": f"reveal:{status}"})
            return f"reveal {status}" + (" (resent after a drop)" if st == "dropped" else "")
        return fight["phase"]

    def _holding(self, what: str, key, rec: dict, tick: int) -> str | None:
        """Why not to send `what` now: rejected for good, or backing off."""
        if rec.get("status", "").startswith(f"{what}:rejected:"):
            return f"{what} was rejected ({rec['status'].rsplit(':', 1)[1]}); not re-sending"
        if self._backing_off((what, key), tick):
            return f"{what} backing off until tick {self.backoff[(what, key)][0]}"
        return None

    def _rejected(self, what: str, key, rec: dict, result, tick: int) -> str:
        """A commit or reveal the contract refused. Retry later only if it may clear."""
        code = result.code
        detail = getattr(result, "detail", "") or ""
        if code in RETRYABLE:
            self._back_off((what, key), tick)
            return f"{what} {code.name}; retrying from tick {self.backoff[(what, key)][0]}"
        self.journal.put({**rec, "status": f"{what}:rejected:{code.name}"})
        self.log(f"fight {key[2]} round {key[3]}: {what} rejected {code.name}"
                 + (f" ({detail})" if detail else "") + "; not re-sending")
        return f"{what} rejected: {code.name}"


def prior_results(rules: Ruleset, prior_rounds: list[dict]) -> tuple[RoundResult, ...]:
    """This fight's completed rounds as engine RoundResults, re-derived from the
    observation's confirmed round-start states and revealed plans. A round that
    does not re-derive to the recorded trace is not trusted, and history stops there."""
    out = []
    for r in prior_rounds:
        start = FightState(r["start"]["round_index"], *(FighterState(**{k: int(v) for k, v in r["start"][s].items()})
                                                         for s in "AB"))
        plans = [Plan.of(r["plans"][s]["actions"], r["plans"][s]["power_slot"]) for s in "AB"]
        res = resolve_round(rules, start, *plans)
        if [b.to_json() for b in res.beats] != r["beats"]:
            break
        out.append(res)
    return tuple(out)


def policy_chooser(rules: Ruleset, policy: npcs.Policy, seed: bytes) -> Choose:
    """Adapt an in-process policy to the observation dict, history included:
    history-based policies (reader-v1, repeat-last-winner, search-v1) read
    `prior`, scouting ones read `opponent_history`."""
    def choose(obs: dict) -> Plan:
        s, o = planner.fighter_state(obs["self"]), planner.fighter_state(obs["opponent"])
        other = "B" if obs["self_slot"] == "A" else "A"
        history = tuple(tuple(Action[b[other]["effective"]] for b in r["beats"]) for r in obs["prior_rounds"])
        prior = prior_results(rules, obs["prior_rounds"])
        view = npcs.Observation(obs["round_index"], s, o, history, obs["self_slot"], prior)
        return policy(rules, view, npcs.Stream(seed, int(obs["fight_id"]), obs["round_index"]))
    return choose


def planner_chooser(command: list[str], budget_ms: int = planner.DEFAULT_BUDGET_MS,
                    log: Callable[[str], None] | None = None) -> Choose:
    """A planner subprocess. With `log`, a failed run and the planner's own
    fallback/adjustment notes (stderr lines starting "fallback" or "adjusted")
    are reported, so an operator can see them."""
    def choose(obs: dict) -> Plan:
        ran, err = planner.run_or_fallback(command, obs, budget_ms)
        if log is not None:
            where = f"fight {obs.get('fight_id')} round {obs.get('round_index')}"
            if err is not None:
                log(f"{where}: planner {err}; six RECOVERs")
            for line in ran.stderr.splitlines():
                if line.startswith(("fallback", "adjusted")):
                    log(f"{where}: planner {line[:200]}")
        return ran.plan
    choose.slow = True          # a subprocess (maybe a model call): plan in the background
    return choose


_PLANNING = None


def _planning_pool():
    global _PLANNING
    if _PLANNING is None:
        from concurrent.futures import ThreadPoolExecutor
        _PLANNING = ThreadPoolExecutor(max_workers=8, thread_name_prefix="qdojo-plan")
    return _PLANNING
