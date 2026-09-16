"""Round evaluation: observed transactions in, a settlement plan out. Pure.

Everything here is deterministic given the same inputs, so a settlement can
be recomputed by anyone from the published data and the revealed dojo salt.
"""
from dataclasses import dataclass, field

from . import hashing, payload

MAX_TX_PER_ROUND = 8  # more than this in one round is a strike (docs/spec.md §6)

VERDICTS = ("pending", "winner", "solved", "wrong", "no_reveal", "no_commit", "late", "underpaid", "duplicate", "bad_reveal", "void", "outranked")
# "outranked": sat down at a table below its belt; refused and refunded
# "no_commit": bought a seat in the lobby, never committed; the stake stays in the pot
# "solved": a correct reveal that the payout mode did not pay (first-wins, not first)


@dataclass(frozen=True, order=True)
class Observed:
    """One transaction as seen on chain. Ordered by (tick, tx_id) for determinism."""
    tick: int
    tx_id: str
    source: str
    dest: str
    amount: int
    input_type: int
    payload: bytes


@dataclass(frozen=True)
class RoundSpec:
    round_id: int
    publish_tick: int | None
    entry_fee: int
    commit_window: int
    reveal_window: int
    riddle_hash: bytes
    answer_commitment: bytes
    answer_format: str
    house_seed: int = 0          # fixed seed when match_bps == 0, else the cap
    rake_bps: int = 0
    payout_mode: int = payload.MODE_FIRST
    match_bps: int = 0           # 10000 = the house matches stakes 1:1 up to house_seed
    carry_in: int = 0            # pot money carried from earlier rounds, always in
    lobby_tick: int | None = None   # set: entries are bought in a lobby before publish (docs/spec.md §2)
    lobby_window: int = 0
    min_players: int = 0
    belt_rank: int | None = None    # the riddle's belt; None = no belt gate on this round
    bond_bps: int = 0               # held back from every win, released after bond_rounds fights
    bond_rounds: int = 0
    house_fighters: tuple = ()      # identities the house funds; their stakes join the pot but are not matched
    rake_house_bps: int = 10000     # split of the rake: house / dev / shareholders, sum 10000
    rake_dev_bps: int = 0
    rake_share_bps: int = 0

    @property
    def lobby(self) -> bool:
        return self.lobby_tick is not None

    @property
    def lobby_end(self):
        return self.lobby_tick + self.lobby_window

    def seed_for(self, stakes: int) -> int:
        matched = min(self.house_seed, stakes * self.match_bps // 10000) if self.match_bps else self.house_seed
        return self.carry_in + matched

    @property
    def commit_start(self):
        return (self.publish_tick or 0) + 1

    @property
    def commit_end(self):
        return (self.publish_tick or 0) + self.commit_window

    @property
    def reveal_start(self):
        return self.commit_end + 1

    @property
    def reveal_end(self):
        return self.commit_end + self.reveal_window

    def state_at(self, tick: int) -> str:
        if self.lobby and self.publish_tick is None:
            return "lobby" if tick <= self.lobby_end else "lobby_closed"
        if tick <= self.commit_end:
            return "commit"
        if tick <= self.reveal_end:
            return "reveal"
        return "settling"


@dataclass
class Entry:
    identity: str
    commit_tick: int | None
    commit_tx: str | None
    stake: int
    enter_tick: int | None = None
    enter_tx: str | None = None
    reveal_tick: int | None = None
    reveal_tx: str | None = None
    answer: str | None = None
    verdict: str = "pending"


@dataclass
class Payout:
    identity: str
    amount: int
    kind: str  # win | refund | bond_release


@dataclass
class Bond:
    identity: str
    amount: int


@dataclass
class Evaluation:
    round_id: int
    entries: list[Entry] = field(default_factory=list)
    strikes: dict[str, list[str]] = field(default_factory=dict)  # identity -> reasons
    pot: int = 0
    seed_used: int = 0
    rake: int = 0
    rake_split: dict = field(default_factory=dict)   # {"house":.., "dev":.., "shareholders":..}
    carry: int = 0
    winners: list[str] = field(default_factory=list)
    payouts: list[Payout] = field(default_factory=list)
    bonds: list[Bond] = field(default_factory=list)      # held this round, from the winners' shares

    def strike(self, identity: str, reason: str):
        self.strikes.setdefault(identity, []).append(reason)

    @property
    def total_out(self) -> int:
        return sum(p.amount for p in self.payouts)


def dojo_messages(observed, house: str, round_id: int):
    """(Observed, Message) pairs addressed to the house for this round, in chain order."""
    out = []
    for o in sorted(observed):
        if o.dest != house or o.input_type != payload.INPUT_TYPE:
            continue
        m = payload.try_decode(o.payload)
        if m is None or isinstance(m, payload.Bow):
            continue
        if getattr(m, "round_id", None) != round_id:
            continue
        out.append((o, m))
    return out


def evaluate(spec: RoundSpec, observed, house: str, dojo_salt: bytes | None, canonical_answer: str | None,
             final: bool = True, belts: dict | None = None) -> Evaluation:
    """Evaluate a round.

    With `final=False` (a mid-round view for the page) no verdict beyond
    `pending`, `late`, `underpaid`, `duplicate` is given and no money is
    planned. With `final=True` the dojo salt and canonical answer are required,
    and the answer must reproduce the published commitment: a house that lost
    its secret cannot settle, it can only refund.
    """
    ev = Evaluation(round_id=spec.round_id)
    if final:
        if dojo_salt is None or canonical_answer is None:
            raise ValueError("final evaluation needs the dojo salt and the answer")
        if hashing.answer_commitment(spec.round_id, dojo_salt, canonical_answer) != spec.answer_commitment:
            raise ValueError("answer and salt do not reproduce the published commitment")

    by_identity: dict[str, Entry] = {}
    refunds: list[Payout] = []
    tx_count: dict[str, int] = {}

    for o, m in dojo_messages(observed, house, spec.round_id):
        src = o.source
        if not hashing.is_identity(src):
            continue
        tx_count[src] = tx_count.get(src, 0) + 1
        if tx_count[src] == MAX_TX_PER_ROUND + 1:
            ev.strike(src, "too_many_transactions")

        if isinstance(m, payload.Enter):
            if not spec.lobby:
                ev.strike(src, "enter_without_lobby")
                if o.amount > 0:
                    refunds.append(Payout(src, o.amount, "refund"))
                continue
            if src in by_identity:
                ev.strike(src, "duplicate_enter")
                if o.amount > 0:
                    refunds.append(Payout(src, o.amount, "refund"))
                continue
            if _outranked(spec, belts, src):
                ev.entries.append(Entry(src, None, None, o.amount, o.tick, o.tx_id, verdict="outranked"))
                if o.amount > 0:
                    refunds.append(Payout(src, o.amount, "refund"))
                continue
            if not (spec.lobby_tick + 1 <= o.tick <= spec.lobby_end):
                ev.entries.append(Entry(src, None, None, o.amount, o.tick, o.tx_id, verdict="late"))
                if o.amount > 0:
                    refunds.append(Payout(src, o.amount, "refund"))
                continue
            if o.amount < spec.entry_fee:
                ev.entries.append(Entry(src, None, None, o.amount, o.tick, o.tx_id, verdict="underpaid"))
                if o.amount > 0:
                    refunds.append(Payout(src, o.amount, "refund"))
                continue
            e = Entry(src, None, None, o.amount, o.tick, o.tx_id)
            by_identity[src] = e
            ev.entries.append(e)

        elif isinstance(m, payload.Commit) and spec.lobby:
            # In a lobby round the seat was bought with ENTER; a commit carries no stake.
            if o.amount > 0:
                refunds.append(Payout(src, o.amount, "refund"))
            e = by_identity.get(src)
            if e is None:
                ev.strike(src, "commit_without_entry")
                continue
            if e.commit_tx is not None:
                ev.strike(src, "duplicate_commit")
                continue
            if spec.publish_tick is None or not (spec.commit_start <= o.tick <= spec.commit_end):
                ev.strike(src, "commit_outside_window")
                continue
            e.commit_tick, e.commit_tx = o.tick, o.tx_id

        elif isinstance(m, payload.Commit):
            in_window = spec.commit_start <= o.tick <= spec.commit_end
            if src not in by_identity and _outranked(spec, belts, src):
                ev.entries.append(Entry(src, o.tick, o.tx_id, o.amount, verdict="outranked"))
                if o.amount > 0:
                    refunds.append(Payout(src, o.amount, "refund"))
                continue
            if src in by_identity:
                ev.strike(src, "duplicate_commit")
                if o.amount > 0:
                    refunds.append(Payout(src, o.amount, "refund"))
                continue
            if not in_window:
                ev.entries.append(Entry(src, o.tick, o.tx_id, o.amount, verdict="late"))
                if o.amount > 0:
                    refunds.append(Payout(src, o.amount, "refund"))
                continue
            if o.amount < spec.entry_fee:
                ev.entries.append(Entry(src, o.tick, o.tx_id, o.amount, verdict="underpaid"))
                if o.amount > 0:
                    refunds.append(Payout(src, o.amount, "refund"))
                continue
            e = Entry(src, o.tick, o.tx_id, o.amount)
            by_identity[src] = e
            ev.entries.append(e)

        elif isinstance(m, payload.Reveal):
            if o.amount > 0:
                refunds.append(Payout(src, o.amount, "refund"))
            e = by_identity.get(src)
            if e is None or e.commit_tx is None:
                ev.strike(src, "reveal_without_commit")
                continue
            if e.reveal_tx is not None:
                ev.strike(src, "duplicate_reveal")
                continue
            if not (spec.reveal_start <= o.tick <= spec.reveal_end):
                ev.strike(src, "reveal_outside_window")
                continue
            # The reveal must reproduce the identity's own commitment.
            try:
                canon = hashing.canonical_answer(m.answer, spec.answer_format)
                ok = hashing.player_commitment(spec.round_id, src, m.salt, canon) == _commitment_of(observed, e)
            except (hashing.CanonicalError, ValueError):
                ok, canon = False, None
            if not ok:
                ev.strike(src, "bad_reveal")
                e.verdict = "bad_reveal"
                continue
            e.reveal_tick, e.reveal_tx, e.answer = o.tick, o.tx_id, canon
            if final:
                e.verdict = "winner" if canon == canonical_answer else "wrong"

    if not final:
        return ev

    for e in ev.entries:
        if e.verdict == "pending":
            e.verdict = "no_reveal" if e.commit_tx else "no_commit"

    counted = [e for e in ev.entries if e.verdict in ("winner", "solved", "wrong", "no_reveal", "no_commit", "bad_reveal")]
    stakes = sum(e.stake for e in counted)
    matchable = sum(e.stake for e in counted if e.identity not in spec.house_fighters)
    ev.seed_used = spec.seed_for(matchable)
    ev.pot = ev.seed_used + stakes
    ev.rake = stakes * spec.rake_bps // 10000
    dev = ev.rake * spec.rake_dev_bps // 10000
    share = ev.rake * spec.rake_share_bps // 10000
    ev.rake_split = {"house": ev.rake - dev - share, "dev": dev, "shareholders": share}
    distributable = ev.pot - ev.rake
    solved = sorted((e for e in ev.entries if e.verdict == "winner"), key=lambda e: (e.commit_tick, e.commit_tx))
    if spec.payout_mode == payload.MODE_FIRST and solved:
        first_tick = solved[0].commit_tick
        for e in solved:
            if e.commit_tick != first_tick:
                e.verdict = "solved"
    if spec.payout_mode == payload.MODE_PODIUM and solved:
        podium = solved[:len(payload.PODIUM_WEIGHTS)]
        for e in solved[len(podium):]:
            e.verdict = "solved"
        weights = payload.PODIUM_WEIGHTS[:len(podium)]
        total_w = sum(weights)
        wins = [Payout(e.identity, distributable * w // total_w, "win") for e, w in zip(podium, weights)]
        ev.winners = [e.identity for e in podium]
        ev.payouts = [p for p in wins if p.amount > 0]
        ev.carry = distributable - sum(p.amount for p in wins)
    else:
        ev.winners = [e.identity for e in solved if e.verdict == "winner"]
        if ev.winners:
            share = distributable // len(ev.winners)
            ev.payouts = [Payout(w, share, "win") for w in ev.winners if share > 0]
            ev.carry = distributable - share * len(ev.winners)
        else:
            ev.carry = distributable
    if spec.bond_bps:
        for p in ev.payouts:
            held = p.amount * spec.bond_bps // 10000
            if held:
                ev.bonds.append(Bond(p.identity, held))
                p.amount -= held
    ev.payouts += refunds
    held_total = sum(b.amount for b in ev.bonds)
    assert ev.total_out + ev.rake + ev.carry + held_total == ev.pot + sum(r.amount for r in refunds), "money must balance"
    return ev


def _outranked(spec: RoundSpec, belts: dict | None, identity: str) -> bool:
    if spec.belt_rank is None or not belts:
        return False
    from . import belts as B
    return not B.may_enter(belts, identity, spec.belt_rank)


def _commitment_of(observed, e: Entry) -> bytes:
    if e.commit_tx is None:
        return b""
    for o in observed:
        if o.tx_id == e.commit_tx:
            m = payload.try_decode(o.payload)
            return m.commitment if isinstance(m, payload.Commit) else b""
    return b""


def void(spec: RoundSpec, observed, house: str) -> Evaluation:
    """A lobby that did not fill: refund every entrant, nothing else moves."""
    ev = evaluate(spec, observed, house, None, None, final=False)
    ev.payouts = [Payout(e.identity, e.stake, "refund") for e in ev.entries if e.stake > 0]
    for e in ev.entries:
        e.verdict = "void"
    return ev


def to_dict(ev: Evaluation, dojo_salt: bytes | None = None, answer: str | None = None) -> dict:
    d = {
        "round_id": ev.round_id,
        "entries": [vars(e) for e in ev.entries],
        "strikes": ev.strikes,
        "pot": ev.pot, "seed_used": ev.seed_used, "rake": ev.rake, "rake_split": ev.rake_split, "carry": ev.carry,
        "winners": list(ev.winners),
        "payouts": [vars(p) for p in ev.payouts],
        "bonds_held": [vars(b) for b in ev.bonds],
    }
    if dojo_salt is not None:
        d["dojo_salt"] = dojo_salt.hex()
    if answer is not None:
        d["answer"] = answer
    return d
