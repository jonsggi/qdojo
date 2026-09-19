"""Building, signing and hashing a Qubic transaction. Pure, no I/O.

Wire layout, from Qubic's `transactions.h` and `wallet_utils.cpp`:

    tx      32  source public key
            32  destination public key
             8  amount (int64)
             4  tick (uint32)
             2  input type
             2  input size
     input  inputSize bytes
       sig  64

The digest that is SIGNED covers the 80-byte transaction plus its input, and
nothing else. The digest that becomes the TRANSACTION HASH covers the same
bytes plus the 64-byte signature. Two different hashes of overlapping
buffers: confusing them produces a hash that names no transaction, so they
are two clearly separate functions here.

A dojo transaction carries its payload in `input`, so every round message --
BOW, COMMIT, REVEAL, SETTLE -- is one of these with input_type 0x444F.
"""
import struct
from dataclasses import dataclass

from . import schnorrq
from .ids import public_key_from_identity, tx_hash_from_digest
from .k12 import k12

TX_SIZE = 80
SIGNATURE_SIZE = 64
MAX_INPUT_SIZE = 1024
MAX_AMOUNT = 1_000_000_000_000_000


@dataclass(frozen=True)
class Transaction:
    """One unsigned transaction. Frozen: change anything and you build a new
    one, because a signature is only ever valid for exact bytes."""

    source_public_key: bytes
    destination_public_key: bytes
    amount: int
    tick: int
    input_type: int = 0
    input_bytes: bytes = b""

    def __post_init__(self):
        if len(self.source_public_key) != 32 or len(self.destination_public_key) != 32:
            raise ValueError("public keys must be 32 bytes")
        if not 0 <= self.amount <= MAX_AMOUNT:
            raise ValueError(f"amount {self.amount!r} out of range 0..{MAX_AMOUNT}")
        if not 0 <= self.tick < (1 << 32):
            raise ValueError(f"tick {self.tick!r} out of range")
        if not 0 <= self.input_type < (1 << 16):
            raise ValueError(f"input type {self.input_type!r} out of range")
        if len(self.input_bytes) > MAX_INPUT_SIZE:
            raise ValueError(f"input is {len(self.input_bytes)} bytes, max is {MAX_INPUT_SIZE}")

    @classmethod
    def to_identity(cls, source_public_key: bytes, destination: str, amount: int,
                    tick: int, input_type: int = 0, payload: bytes = b"") -> "Transaction":
        return cls(source_public_key, public_key_from_identity(destination),
                   amount, tick, input_type, payload)

    def body(self) -> bytes:
        """The 80-byte struct plus its input -- the bytes that get signed."""
        return struct.pack(
            "<32s32sqIHH",
            self.source_public_key, self.destination_public_key,
            self.amount, self.tick, self.input_type, len(self.input_bytes),
        ) + self.input_bytes

    def digest(self) -> bytes:
        """The 32 bytes a signature commits to."""
        return k12(self.body(), 32)

    def sign(self, subseed: bytes) -> "SignedTransaction":
        """Sign with the subseed whose public key is this transaction's source.

        The source public key is re-derived and compared first. Signing as
        someone else produces a transaction no node will accept, and nothing
        downstream would tell you why.
        """
        from .ids import private_key_from_subseed, public_key_from_private_key
        derived = public_key_from_private_key(private_key_from_subseed(subseed))
        if derived != self.source_public_key:
            raise ValueError("subseed derives a different identity than this "
                             "transaction's source -- refusing to sign")
        return SignedTransaction(self, schnorrq.sign(subseed, self.source_public_key,
                                                     self.digest()))


@dataclass(frozen=True)
class SignedTransaction:
    transaction: Transaction
    signature: bytes

    def __post_init__(self):
        if len(self.signature) != SIGNATURE_SIZE:
            raise ValueError(f"signature must be {SIGNATURE_SIZE} bytes")

    def payload(self) -> bytes:
        """Transaction + input + signature: the broadcast body."""
        return self.transaction.body() + self.signature

    def tx_hash(self) -> str:
        """The 60-char lowercase hash used to look the transaction up later."""
        return tx_hash_from_digest(k12(self.payload(), 32))

    def verify(self) -> bool:
        """Check our own signature before it goes anywhere. Cheap next to a
        transfer that cannot be undone."""
        return schnorrq.verify(self.transaction.source_public_key,
                               self.transaction.digest(), self.signature)
