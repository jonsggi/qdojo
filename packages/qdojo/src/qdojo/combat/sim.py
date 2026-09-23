"""A fake chain around the reference contract: explicit ticks, fake QU, asset owners.

Total QU is conserved across the world: external balances plus the contract
balance never change except through `mint`. Transactions submitted during a
tick run in submission order, then END_TICK runs — the order the protocol
specifies for Qubic. Nothing here touches a real network or key.

Every input that can change the contract — calls, ticks, asset transfers,
failing recipients — is appended to `journal`. Replaying a journal rebuilds
the identical contract (store.py), and the same journals drive the C++ port's
parity test.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from ..hashing import sha256
from . import codec
from .codec import Op
from .contract import CallResult, CombatContract, Manifest
from .types import Plan


def identity(label: str) -> bytes:
    """A synthetic 32-byte public identity for tests and local simulation."""
    return sha256(b"qdojo/combat/sim-identity/v1\0", label.encode())


class _Owners(dict):
    """Asset ownership as the contract sees it; writes are journalled."""

    def __init__(self, world):
        super().__init__()
        self.world = world

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.world.journal.append({"k": "owner", "t": self.world.tick, "id": key.hex(),
                                   "owner": value.hex() if value else None})


class _Failing(set):
    def add(self, who):
        super().add(who)
        self.world.journal.append({"k": "fail", "t": self.world.tick, "who": who.hex(), "on": True})

    def discard(self, who):
        super().discard(who)
        self.world.journal.append({"k": "fail", "t": self.world.tick, "who": who.hex(), "on": False})

    def clear(self):
        for who in list(self):
            self.discard(who)


@dataclass
class World:
    manifest: Manifest
    tick: int = 1
    balances: dict[bytes, int] = field(default_factory=dict)
    nonces: dict[bytes, int] = field(default_factory=dict)
    minted: int = 0
    journal: list = field(default_factory=list)

    def __post_init__(self):
        self.owners = _Owners(self)
        self.transfer_fails = _Failing()
        self.transfer_fails.world = self
        self.journal.append({"k": "start", "t": self.tick})
        self.contract = CombatContract(self.manifest, self.owners.get, self._transfer, self.tick)

    # -- money --------------------------------------------------------------

    def mint(self, who: bytes, amount: int):
        self.balances[who] = self.balances.get(who, 0) + amount
        self.minted += amount
        self.journal.append({"k": "mint", "t": self.tick, "who": who.hex(), "amount": amount})

    @classmethod
    def replay(cls, manifest: Manifest, records: list) -> "World":
        """Rebuild a whole world (balances too) from its journal."""
        start = next(r for r in records if r["k"] == "start")
        w = cls(manifest, tick=start["t"])
        for rec in records:
            k = rec["k"]
            if k == "mint":
                w.mint(bytes.fromhex(rec["who"]), rec["amount"])
            elif k == "owner":
                w.owners[bytes.fromhex(rec["id"])] = bytes.fromhex(rec["owner"]) if rec["owner"] else None
            elif k == "fail":
                who = bytes.fromhex(rec["who"])
                (w.transfer_fails.add if rec["on"] else w.transfer_fails.discard)(who)
            elif k == "call":
                w.raw(bytes.fromhex(rec["who"]), bytes.fromhex(rec["frame"]), rec["amount"])
            elif k == "end":
                w.end()
            elif k == "begin":
                w.skip_ticks(rec["t"] - w.tick)
        w.nonces = {who: last[0] for who, last in w.contract.nonces.items()}
        return w

    def _transfer(self, to: bytes, amount: int) -> bool:
        if to in self.transfer_fails:
            return False
        self.balances[to] = self.balances.get(to, 0) + amount
        return True

    def total(self) -> int:
        return sum(self.balances.values()) + self.contract.ledger.balance

    def check_conservation(self):
        assert self.total() == self.minted, (self.total(), self.minted)
        self.contract.ledger.check()

    # -- transactions -------------------------------------------------------

    def next_nonce(self, who: bytes) -> int:
        n = self.nonces.get(who, 0) + 1
        self.nonces[who] = n
        return n

    def send(self, who: bytes, op: Op, amount: int = 0, nonce: int | None = None, **fields) -> CallResult:
        """Submit and execute within the current tick (after BEGIN_TICK)."""
        if nonce is None:
            nonce = 0 if op is Op.ADVANCE else self.next_nonce(who)
        return self.raw(who, codec.encode_frame(op, nonce, fields), amount)

    def raw(self, who: bytes, frame: bytes, amount: int = 0) -> CallResult:
        if self.balances.get(who, 0) < amount:
            raise ValueError("insufficient external balance")
        self.balances[who] = self.balances.get(who, 0) - amount
        self.journal.append({"k": "call", "t": self.tick, "who": who.hex(), "frame": frame.hex(), "amount": amount})
        return self.contract.call(who, frame, amount, self.tick)

    def end(self):
        """END_TICK for the current tick, then BEGIN_TICK of the next."""
        self.journal.append({"k": "end", "t": self.tick})
        self.contract.end_tick(self.tick)
        self.tick += 1
        self.contract.begin_tick(self.tick)

    def run_until(self, tick: int):
        while self.tick < tick:
            self.end()

    def skip_ticks(self, n: int):
        """Simulate a contract that did not run for n ticks (reserve outage)."""
        self.tick += n
        self.journal.append({"k": "begin", "t": self.tick})
        self.contract.begin_tick(self.tick)


def commit_fields(world: World, fight_id: int, fighter_id: bytes, operator: bytes, plan: Plan,
                  salt: bytes | None = None) -> tuple[dict, bytes]:
    """Build a Commit body for the fight's current round. Returns (fields, salt)."""
    c = world.contract
    fight = c.fights[fight_id]
    slot = fight.slot_of(fighter_id)
    part = fight.context.participant_a if slot == "A" else fight.context.participant_b
    salt = salt or secrets.token_bytes(32)
    digest = fight.round_state_digest()
    commitment = codec.commitment(
        network_id=world.manifest.network_id, contract_id=world.manifest.contract_id, fight_id=fight_id,
        round_index=fight.state.round_index, context_digest=fight.context_digest, round_state_digest=digest,
        fighter_id=fighter_id, operator=operator, auth_version=part.auth_version, salt=salt, plan=plan)
    return dict(fight_id=fight_id, round_index=fight.state.round_index, fighter_id=fighter_id,
                auth_version=part.auth_version, round_state_digest=digest, commitment=commitment), salt


def reveal_fields(world: World, fight_id: int, fighter_id: bytes, plan: Plan, salt: bytes) -> dict:
    fight = world.contract.fights[fight_id]
    slot = fight.slot_of(fighter_id)
    part = fight.context.participant_a if slot == "A" else fight.context.participant_b
    return dict(fight_id=fight_id, round_index=fight.state.round_index, fighter_id=fighter_id,
                auth_version=part.auth_version, round_state_digest=fight.round_state_digest(),
                salt=salt, plan=plan)
