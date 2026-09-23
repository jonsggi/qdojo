"""A fake chain around the reference contract: explicit ticks, fake QU, asset owners.

Total QU is conserved across the world: external balances plus the contract
balance never change except through `mint`. Transactions submitted during a
tick run in submission order, then END_TICK runs — the order the protocol
specifies for Qubic. Nothing here touches a real network or key.
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


@dataclass
class World:
    manifest: Manifest
    tick: int = 1
    balances: dict[bytes, int] = field(default_factory=dict)
    owners: dict[bytes, bytes | None] = field(default_factory=dict)     # fighter/asset id -> owner
    transfer_fails: set[bytes] = field(default_factory=set)
    nonces: dict[bytes, int] = field(default_factory=dict)
    minted: int = 0
    pending: list = field(default_factory=list)

    def __post_init__(self):
        self.contract = CombatContract(self.manifest, self.owners.get, self._transfer, self.tick)

    # -- money --------------------------------------------------------------

    def mint(self, who: bytes, amount: int):
        self.balances[who] = self.balances.get(who, 0) + amount
        self.minted += amount

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
        frame = codec.encode_frame(op, nonce, fields)
        return self.raw(who, frame, amount)

    def raw(self, who: bytes, frame: bytes, amount: int = 0) -> CallResult:
        if self.balances.get(who, 0) < amount:
            raise ValueError("insufficient external balance")
        self.balances[who] = self.balances.get(who, 0) - amount
        return self.contract.call(who, frame, amount, self.tick)

    def end(self):
        """END_TICK for the current tick, then open the next."""
        self.contract.end_tick(self.tick)
        self.tick += 1
        self.contract.begin_tick(self.tick)

    def run_until(self, tick: int):
        while self.tick < tick:
            self.end()

    def skip_ticks(self, n: int):
        """Simulate a contract that did not run for n ticks (reserve outage)."""
        self.tick += n
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
