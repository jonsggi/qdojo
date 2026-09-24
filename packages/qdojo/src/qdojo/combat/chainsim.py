"""A realistic simulated Qubic chain around the reference contract.

`sim.World` executes a call the moment it is sent. A real chain does not:
- a transaction targets a future tick;
- it is included then, or never (dropped);
- transactions in one tick run in an order the sender does not control;
- the sender learns the outcome only by polling after the target tick;
- the contract runs only while its execution reserve covers the fees.

`SimChain` adds exactly these behaviours, deterministically from a seed, so
bots, the CLI and the live arena run the code path a real node will need.

Also simulated here, never on a real network:
- `AssetRegistry`: fighter NFTs (issuer, name, one unit), owners and transfer
  history, founding status.
- `FeeModel`: per-call and per-tick execution costs burned from the contract's
  reserve. A dry reserve stops END_TICK, which the contract's heartbeat then
  sees as an objective service gap.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..hashing import sha256
from . import codec
from .codec import Op
from .contract import CallResult
from .sim import World


# ---- fighter assets --------------------------------------------------------

@dataclass
class Asset:
    fighter_id: bytes
    issuer: bytes
    name: str
    founding: bool
    history: list = field(default_factory=list)      # [(tick, from_owner | None, to_owner)]

    @property
    def owner(self) -> bytes:
        return self.history[-1][2]


class AssetRegistry:
    """Simulated fighter NFTs. Ownership changes flow into the World's owner
    table, which the contract queries (and the journal records)."""

    def __init__(self, world: World, issuer: bytes, name: str = "QDOJOF"):
        self.world, self.issuer, self.name = world, issuer, name
        self.assets: dict[bytes, Asset] = {}

    def issue(self, label: str, owner: bytes, founding: bool = False) -> bytes:
        fid = sha256(b"qdojo/combat/sim-asset/v1\0", self.issuer, self.name.encode(), label.encode())
        if fid in self.assets:
            raise ValueError(f"asset {label!r} already issued")
        self.assets[fid] = Asset(fid, self.issuer, self.name, founding, [(self.world.tick, None, owner)])
        self.world.owners[fid] = owner
        return fid

    def transfer(self, fid: bytes, frm: bytes, to: bytes):
        a = self.assets[fid]
        if a.owner != frm:
            raise ValueError("only the current owner can transfer")
        a.history.append((self.world.tick, frm, to))
        self.world.owners[fid] = to

    def public(self, fid: bytes) -> dict | None:
        a = self.assets.get(fid)
        if a is None:
            return None
        return {"issuer": a.issuer.hex(), "name": a.name, "founding": a.founding,
                "owner": a.owner.hex(), "history": [{"tick": str(t), "from": f.hex() if f else None, "to": to.hex()}
                                                    for t, f, to in a.history]}


# ---- execution fees --------------------------------------------------------

@dataclass(frozen=True)
class FeeModel:
    """Candidate cost model in QU; replace with measured Core costs later."""
    per_call: int = 10
    per_tick: int = 1
    per_resolved_round: int = 20


# ---- transactions ----------------------------------------------------------

@dataclass
class Tx:
    tx_id: int
    who: bytes
    frame: bytes
    amount: int
    target_tick: int
    status: str = "pending"          # pending, included, dropped
    result: CallResult | None = None


@dataclass
class Pending:
    """What a send returns on a real chain: not a result, a receipt to poll."""
    tx_id: int
    target_tick: int
    code: None = None


class SimChain:
    def __init__(self, world: World, seed: int = 0, latency: tuple[int, int] = (1, 3), drop_rate: float = 0.0,
                 fees: FeeModel | None = None, reserve: int | None = None):
        self.world = world
        self.rng = random.Random(seed)
        self.latency, self.drop_rate = latency, drop_rate
        self.fees, self.reserve = fees, reserve
        self.txs: dict[int, Tx] = {}
        self.queue: dict[int, list[int]] = {}
        self.next_id = 1
        self.burned = 0
        self.halted_ticks = 0
        self.nonces: dict[bytes, int] = {}

    # -- sending ------------------------------------------------------------

    def submit(self, who: bytes, frame: bytes, amount: int = 0) -> Pending:
        lo, hi = self.latency
        target = self.world.tick + self.rng.randint(lo, hi)
        tx = Tx(self.next_id, who, frame, amount, target)
        self.next_id += 1
        self.txs[tx.tx_id] = tx
        self.queue.setdefault(target, []).append(tx.tx_id)
        return Pending(tx.tx_id, target)

    def send(self, who: bytes, op: Op, amount: int = 0, **fields) -> Pending:
        nonce = 0
        if op is not Op.ADVANCE:
            nonce = max(self.nonces.get(who, 0), self.world.contract.nonces.get(who, (0,))[0]) + 1
            self.nonces[who] = nonce
        return self.submit(who, codec.encode_frame(op, nonce, fields), amount)

    def poll(self, receipt: Pending) -> CallResult | str | None:
        """The included result, "dropped" once the target tick has passed without it, or None while pending."""
        tx = self.txs[receipt.tx_id]
        if tx.status == "included":
            return tx.result
        if tx.status == "dropped":
            return "dropped"
        return None

    # -- ticking ------------------------------------------------------------

    def fund_reserve(self, amount: int):
        self.reserve = (self.reserve or 0) + amount

    def _cost(self, qu: int) -> bool:
        if self.fees is None:
            return True
        if self.reserve is not None and self.reserve < qu:
            return False
        if self.reserve is not None:
            self.reserve -= qu
        self.burned += qu
        return True

    def advance(self):
        """Run the current tick: include its transactions in chain order, then END_TICK."""
        w = self.world
        ids = self.queue.pop(w.tick, [])
        self.rng.shuffle(ids)
        halted = self.fees is not None and self.reserve is not None and self.reserve < self.fees.per_tick
        for tx_id in ids:
            tx = self.txs[tx_id]
            if self.rng.random() < self.drop_rate or halted:
                tx.status = "dropped"
                continue
            if w.balances.get(tx.who, 0) < tx.amount:
                tx.status = "dropped"          # a real node rejects an unfunded transfer
                continue
            if self.fees is not None and not self._cost(self.fees.per_call):
                tx.status = "dropped"
                continue
            tx.result = w.raw(tx.who, tx.frame, tx.amount)
            tx.status = "included"
        if halted or (self.fees is not None and not self._cost(self.fees.per_tick)):
            # The contract could not run this tick: no END_TICK. Its heartbeat
            # sees the gap when it next runs and voids unfinished work.
            self.halted_ticks += 1
            w.skip_ticks(1)
            return
        before = sum(len(f.rounds) for f in w.contract.fights.values())
        w.end()
        if self.fees is not None:
            resolved = sum(len(f.rounds) for f in w.contract.fights.values()) - before
            self._cost(self.fees.per_resolved_round * resolved)


class SimQubicClient:
    """A bot's view of the simulated chain: sends return receipts, reads are
    confirmed contract state. Mirrors what a real node client will offer."""

    def __init__(self, chain: SimChain, signer: bytes, devnet_client):
        self.chain, self.signer = chain, signer
        self.view = devnet_client                 # confirmed-state reads (same shapes as QDOJO queries)
        self.network_id, self.contract_id = devnet_client.network_id, devnet_client.contract_id

    def tick(self) -> int:
        return self.chain.world.tick

    def send(self, op: Op, amount: int = 0, **fields) -> Pending:
        return self.chain.send(self.signer, op, amount, **fields)

    def poll(self, receipt: Pending):
        return self.chain.poll(receipt)

    def __getattr__(self, name):
        return getattr(self.view, name)
