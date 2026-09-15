"""The one interface the game talks to the chain through.

Reads that fail raise `Unknown`: an unknown is never a zero. Sends return
what was scheduled, never a claim of success; `confirm` is the only proof.
"""
from dataclasses import dataclass
from typing import Protocol

from ..round import Observed


class ChainError(Exception):
    pass


class Unknown(ChainError):
    """A read that did not produce a trustworthy answer."""


@dataclass(frozen=True)
class SendResult:
    tx_id: str
    scheduled_tick: int


class Chain(Protocol):
    identity: str  # the identity this chain instance signs as, or "" for read-only

    def current_tick(self) -> int: ...
    def indexed_tick(self) -> int: ...   # the last tick the transaction index has fully processed
    def balance(self, identity: str) -> int: ...
    def send(self, dest: str, amount: int, payload: bytes = b"", input_type: int = 0) -> SendResult: ...
    def confirm(self, tx_id: str, tick: int) -> bool: ...
    def transactions_to(self, identity: str, start_tick: int, end_tick: int) -> list[Observed]: ...
