"""Seeds, keys and the 60-character identity encoding. Pure, no I/O.

The derivation chain, from Qubic's reference `key_utils.cpp`:

    seed (55 chars a-z)  -> bytes c-'a'      -> K12 -> subseed     (32 bytes)
    subseed              -> K12              ->       private key  (32 bytes)
    private key          -> private_key * G  ->       public key   (32 bytes)
    public key           -> base-26 + checksum ->     identity     (60 chars)

The identity encoding is NOT base-26 over the whole 32 bytes: it is four
independent little-endian uint64s, each written as 14 base-26 digits
least-significant first, then 4 characters carrying 18 bits of
K12(public key, 3). 26^14 > 2^64, so the mapping is injective and reversible.

A SEED THAT IS NOT 55 LOWERCASE LETTERS RAISES. qubic-cli's own derivation
returns false and leaves the buffer as it found it, and its callers do not
check -- which is how a missing seed becomes a silent derivation from 55 'a's
and a signature by the publicly controllable BZBQFLLB...QEXK identity. Here
it is an exception, every time.
"""
from .fourq import encode, scalar_mul
from .k12 import k12

SEED_LEN = 55
IDENTITY_LEN = 60

# The identity a missing or all-'a' seed derives. Public, and therefore
# spendable by anyone: never sign as this.
PUBLIC_DEFAULT_IDENTITY = "BZBQFLLBNCXEMGLOBHUVFTLUPLVCPQUASSILFABOFFBCADQSSUPNWLZBQEXK"


def subseed_from_seed(seed: str | bytes) -> bytes:
    """32-byte subseed from 55 lowercase letters."""
    if isinstance(seed, str):
        seed = seed.encode("ascii", "strict")
    if len(seed) != SEED_LEN:
        raise ValueError(f"seed must be {SEED_LEN} characters, got {len(seed)}")
    if any(not (0x61 <= c <= 0x7A) for c in seed):
        raise ValueError("seed must be lowercase a-z only")
    return k12(bytes(c - 0x61 for c in seed), 32)


def private_key_from_subseed(subseed: bytes) -> bytes:
    if len(subseed) != 32:
        raise ValueError("subseed must be 32 bytes")
    return k12(subseed, 32)


def public_key_from_private_key(private_key: bytes) -> bytes:
    if len(private_key) != 32:
        raise ValueError("private key must be 32 bytes")
    return encode(scalar_mul(int.from_bytes(private_key, "little")))


def keys_from_seed(seed: str | bytes) -> tuple[bytes, bytes, bytes]:
    """(subseed, private_key, public_key) -- the whole chain in one call."""
    subseed = subseed_from_seed(seed)
    private_key = private_key_from_subseed(subseed)
    return subseed, private_key, public_key_from_private_key(private_key)


def identity_from_seed(seed: str | bytes) -> str:
    """The identity a seed signs as. Replaces `qubic-cli -showkeys`."""
    return identity_from_public_key(keys_from_seed(seed)[2])


def identity_from_public_key(public_key: bytes, lower: bool = False) -> str:
    """60-character identity. Upper case for addresses, lower for tx hashes."""
    if len(public_key) != 32:
        raise ValueError("public key must be 32 bytes")
    base = ord("a") if lower else ord("A")
    out: list[str] = []
    for i in range(4):
        frag = int.from_bytes(public_key[8 * i:8 * i + 8], "little")
        for _ in range(14):
            out.append(chr(frag % 26 + base))
            frag //= 26
    checksum = int.from_bytes(k12(public_key, 3), "little") & 0x3FFFF
    for _ in range(4):
        out.append(chr(checksum % 26 + base))
        checksum //= 26
    return "".join(out)


def public_key_from_identity(identity: str) -> bytes:
    """The 32 bytes behind an identity. The checksum is NOT verified here."""
    if len(identity) != IDENTITY_LEN:
        raise ValueError(f"identity must be {IDENTITY_LEN} characters, got {len(identity)}")
    base = ord("a") if identity[0].islower() else ord("A")
    out = bytearray()
    for i in range(4):
        v = 0
        for j in range(13, -1, -1):
            d = ord(identity[i * 14 + j]) - base
            if not 0 <= d < 26:
                raise ValueError(f"identity character {identity[i * 14 + j]!r} out of range")
            v = v * 26 + d
        if v >= 1 << 64:
            raise ValueError(f"identity fragment {i} does not fit in 64 bits")
        out += v.to_bytes(8, "little")
    return bytes(out)


def check_identity(identity: str) -> bool:
    """True if the identity is well formed AND its checksum matches.

    Every destination that came from outside this process goes through here.
    A mistyped identity with a valid-looking shape is a payment into nothing.
    """
    try:
        pub = public_key_from_identity(identity)
    except (ValueError, IndexError):
        return False
    return identity_from_public_key(pub, lower=identity[0].islower()) == identity


def tx_hash_from_digest(digest: bytes) -> str:
    """A transaction hash is its digest run through the identity encoding."""
    return identity_from_public_key(digest, lower=True)
