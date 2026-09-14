import os
import secrets

import pytest

from qdojo import hashing, payload
from qdojo.round import Observed

HOUSE = "H" * 60
ALICE = "A" * 60
BOB = "B" * 60
CARL = "C" * 60


def ident(letter):
    return letter.upper() * 60


@pytest.fixture
def house():
    return HOUSE


class TxFactory:
    """Builds Observed transactions in a stable order."""

    def __init__(self, house):
        self.house = house
        self.n = 0

    def _next(self):
        self.n += 1
        return f"tx{self.n:04d}"

    def tx(self, source, tick, msg, amount=0, dest=None, input_type=payload.INPUT_TYPE, raw=None):
        return Observed(tick=tick, tx_id=self._next(), source=source, dest=dest or self.house,
                        amount=amount, input_type=input_type,
                        payload=raw if raw is not None else payload.encode(msg))

    def commit(self, source, tick, round_id, salt, answer, fmt="integer", amount=0):
        canon = hashing.canonical_answer(answer, fmt)
        c = hashing.player_commitment(round_id, source, salt, canon)
        return self.tx(source, tick, payload.Commit(round_id, c), amount=amount)

    def reveal(self, source, tick, round_id, salt, answer, amount=0):
        return self.tx(source, tick, payload.Reveal(round_id, salt, str(answer)), amount=amount)


@pytest.fixture
def txf(house):
    return TxFactory(house)


@pytest.fixture
def salt():
    return secrets.token_bytes(16)
