"""An in-memory chain for tests and dry runs. Deterministic, tick-driven."""
from ..round import Observed
from .base import SendResult, Unknown, ChainError


class FakeChain:
    def __init__(self, identity: str = "", tick: int = 1000, balances: dict | None = None, schedule_offset: int = 5):
        self.identity = identity
        self.tick = tick
        self.balances = dict(balances or {})
        self.schedule_offset = schedule_offset
        self.pending: list[tuple[int, Observed]] = []
        self.ledger: list[Observed] = []
        self.n = 0
        self.fail_reads = False
        self.drop_next_send = False

    # --- test controls
    def advance(self, n: int = 1):
        for _ in range(n):
            self.tick += 1
            due = [o for t, o in self.pending if t == self.tick]
            self.pending = [(t, o) for t, o in self.pending if t != self.tick]
            for o in due:
                if self.balances.get(o.source, 0) < o.amount:
                    continue  # the node drops an unfunded transfer
                self.balances[o.source] = self.balances.get(o.source, 0) - o.amount
                self.balances[o.dest] = self.balances.get(o.dest, 0) + o.amount
                self.ledger.append(o)

    def inject(self, source: str, dest: str, amount: int, payload: bytes, input_type: int, at_tick: int | None = None):
        """Another party's transaction, landing at `at_tick` (default: next tick)."""
        self.n += 1
        o = Observed(tick=at_tick or self.tick + 1, tx_id=f"fake{self.n:05d}", source=source, dest=dest,
                     amount=amount, input_type=input_type, payload=payload)
        self.pending.append((o.tick, o))
        return o

    # --- Chain
    def current_tick(self) -> int:
        if self.fail_reads:
            raise Unknown("fake: reads failing")
        return self.tick

    def balance(self, identity: str) -> int:
        if self.fail_reads:
            raise Unknown("fake: reads failing")
        return self.balances.get(identity, 0)

    def send(self, dest: str, amount: int, payload: bytes = b"", input_type: int = 0) -> SendResult:
        if not self.identity:
            raise ChainError("fake: read-only chain cannot send")
        if self.drop_next_send:
            self.drop_next_send = False
            self.n += 1
            return SendResult(f"lost{self.n:05d}", self.tick + self.schedule_offset)
        o = self.inject(self.identity, dest, amount, payload, input_type, at_tick=self.tick + self.schedule_offset)
        return SendResult(o.tx_id, o.tick)

    def confirm(self, tx_id: str, tick: int) -> bool:
        if self.fail_reads:
            raise Unknown("fake: reads failing")
        if tick > self.tick:
            raise Unknown(f"fake: tick {tick} not yet processed")
        return any(o.tx_id == tx_id and o.tick == tick for o in self.ledger)

    def transactions_to(self, identity: str, start_tick: int, end_tick: int) -> list[Observed]:
        if self.fail_reads:
            raise Unknown("fake: reads failing")
        if end_tick > self.tick:
            raise Unknown(f"fake: tick {end_tick} not yet processed")
        return sorted(o for o in self.ledger if o.dest == identity and start_tick <= o.tick <= end_tick)
