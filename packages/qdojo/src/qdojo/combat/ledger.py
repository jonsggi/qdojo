"""Exact QU accounting for the combat contract (docs/spec.md §5).

Every accepted QU sits in exactly one bucket: an open offer's escrow, a
contest's escrow, a cup's reserve, or a recipient's withdrawable credit
(players, refunds and the house/developer/shareholder rake allocations
alike). `check()` asserts that the contract's balance equals their sum after
every operation. Nothing is ever taken from a liability to cover a cost.
"""
from __future__ import annotations

from dataclasses import dataclass, field

BPS = 10_000
MAX_STAKE = 1_000_000_000_000
I64_MAX = (1 << 63) - 1


class LedgerError(RuntimeError):
    """A conservation or overflow violation: a bug, never a player outcome."""


@dataclass(frozen=True)
class FeeProfile:
    id: int
    rake_bps: int
    house_bps: int
    dev_bps: int
    share_bps: int
    house: bytes
    dev: bytes
    share: bytes

    def __post_init__(self):
        for v in (self.rake_bps, self.house_bps, self.dev_bps, self.share_bps):
            if type(v) is not int or not 0 <= v <= BPS:
                raise ValueError("bps values are integers in 0..10000")
        if self.house_bps + self.dev_bps + self.share_bps != BPS:
            raise ValueError("rake allocations must sum to 10000 bps")


def split_purse(gross: int, fee: FeeProfile) -> tuple[int, int, int, int, int]:
    """(winner_credit, rake, house, dev, share); rounding belongs to the house."""
    if not 0 <= gross <= I64_MAX:
        raise LedgerError("purse overflow")
    rake = gross * fee.rake_bps // BPS
    dev = rake * fee.dev_bps // BPS
    share = rake * fee.share_bps // BPS
    return gross - rake, rake, rake - dev - share, dev, share


@dataclass
class Ledger:
    balance: int = 0
    offers: dict[int, tuple[bytes, int]] = field(default_factory=dict)       # offer_id -> (payer, amount)
    contests: dict[int, dict[bytes, int]] = field(default_factory=dict)      # contest_id -> payer -> amount
    cups: dict[int, dict[bytes, int]] = field(default_factory=dict)          # cup_id -> payer -> amount
    credits: dict[bytes, int] = field(default_factory=dict)                  # recipient -> withdrawable
    paid_out: int = 0

    # -- invariant ----------------------------------------------------------

    def liabilities(self) -> int:
        return (sum(a for _, a in self.offers.values())
                + sum(sum(v.values()) for v in self.contests.values())
                + sum(sum(v.values()) for v in self.cups.values())
                + sum(self.credits.values()))

    def check(self):
        if self.balance != self.liabilities():
            raise LedgerError(f"balance {self.balance} != liabilities {self.liabilities()}")
        if any(v < 0 for v in self.credits.values()) or self.balance < 0:
            raise LedgerError("negative bucket")

    # -- inflow -------------------------------------------------------------

    def receive(self, amount: int):
        if type(amount) is not int or not 0 <= amount <= I64_MAX or self.balance + amount > I64_MAX:
            raise LedgerError("attachment overflow")
        self.balance += amount

    def credit(self, who: bytes, amount: int):
        if amount:
            self.credits[who] = self.credits.get(who, 0) + amount

    def refund_attachment(self, who: bytes, amount: int):
        """A rejected operation's attached QU becomes the invocator's credit."""
        self.credit(who, amount)

    # -- offers -------------------------------------------------------------

    def escrow_offer(self, offer_id: int, payer: bytes, amount: int):
        if offer_id in self.offers:
            raise LedgerError("offer escrow exists")
        self.offers[offer_id] = (payer, amount)

    def release_offer(self, offer_id: int):
        """Cancel/expiry/invalidation: back to the original payer, no rake."""
        payer, amount = self.offers.pop(offer_id)
        self.credit(payer, amount)

    def offers_to_contest(self, contest_id: int, offer_ids):
        pot = self.contests.setdefault(contest_id, {})
        for oid in offer_ids:
            payer, amount = self.offers.pop(oid)
            pot[payer] = pot.get(payer, 0) + amount

    # -- contests -----------------------------------------------------------

    def contest_gross(self, contest_id: int) -> int:
        return sum(self.contests.get(contest_id, {}).values())

    def settle_win(self, contest_id: int, winner: bytes, fee: FeeProfile):
        pot = self.contests.pop(contest_id)
        credit, _, house, dev, share = split_purse(sum(pot.values()), fee)
        self.credit(winner, credit)
        self.credit(fee.house, house)
        self.credit(fee.dev, dev)
        self.credit(fee.share, share)

    def settle_refund(self, contest_id: int):
        for payer, amount in self.contests.pop(contest_id).items():
            self.credit(payer, amount)

    # -- cups ---------------------------------------------------------------

    def reserve_cup(self, cup_id: int, payer: bytes, amount: int):
        pot = self.cups.setdefault(cup_id, {})
        pot[payer] = pot.get(payer, 0) + amount

    def release_cup_entry(self, cup_id: int, payer: bytes, amount: int):
        pot = self.cups[cup_id]
        if pot.get(payer, 0) < amount:
            raise LedgerError("cup entry not reserved")
        pot[payer] -= amount
        if not pot[payer]:
            del pot[payer]
        self.credit(payer, amount)

    def refund_cup(self, cup_id: int):
        for payer, amount in self.cups.pop(cup_id, {}).items():
            self.credit(payer, amount)

    def pay_cup(self, cup_id: int, champion: bytes, entry_gross: int, fee: FeeProfile):
        """Champion gets sponsorship + entries - entry rake; rake splits once."""
        pot = self.cups.pop(cup_id)
        gross = sum(pot.values())
        rake = entry_gross * fee.rake_bps // BPS
        dev = rake * fee.dev_bps // BPS
        share = rake * fee.share_bps // BPS
        self.credit(champion, gross - rake)
        self.credit(fee.house, rake - dev - share)
        self.credit(fee.dev, dev)
        self.credit(fee.share, share)

    # -- withdrawal ---------------------------------------------------------

    def begin_withdraw(self, who: bytes) -> int:
        """Debit first; the caller restores with `restore` if the transfer fails."""
        amount = self.credits.pop(who, 0)
        self.balance -= amount
        self.paid_out += amount
        return amount

    def restore(self, who: bytes, amount: int):
        self.balance += amount
        self.paid_out -= amount
        self.credit(who, amount)
