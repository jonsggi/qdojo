"""SchnorrQ signing, exactly as `sign()` / `verify()` in the reference do it.

THE SIGNATURE IS DETERMINISTIC. The nonce is K12 of (the second half of the
expanded subseed ‖ the message digest) -- no randomness anywhere. Signing the
same digest with the same seed twice must give the same 64 bytes, and so must
qubic-cli. That is what makes this module testable at all: the check is not
"does the signature verify" (many different signatures would) but "is it the
same 64 bytes the reference produced", which `scripts/crosscheck-signer.py`
asserts against `qubic-cli -print-only hex`.

The Montgomery arithmetic in the reference (`signWithNonceK`) is plain
modular arithmetic in disguise: every Montgomery_multiply_mod_order there has
one operand below the curve order, so the product stays under 2N and the
single conditional subtraction always reduces fully. s = (r - h*k0) mod N.
"""

from .fourq import N, decode, encode, pt_add, scalar_mul
from .k12 import k12


def _le(b):
    return int.from_bytes(b, "little")


def sign(subseed, public_key, message_digest):
    """64-byte SchnorrQ signature over a 32-byte digest.

    Inputs are the 32-byte subseed (NOT the seed, NOT the private key), the
    signer's 32-byte public key, and the 32-byte digest of what is signed.
    """
    if len(subseed) != 32 or len(public_key) != 32 or len(message_digest) != 32:
        raise ValueError("schnorrq.sign: subseed, public key and digest are 32 bytes each")

    k = k12(subseed, 64)                       # k[0:32] secret scalar, k[32:64] nonce key
    r = _le(k12(k[32:64] + message_digest, 64)[0:32]) % N
    sig_r = encode(scalar_mul(r))              # R = r*G, encoded -- the first half
    h = _le(k12(sig_r + public_key + message_digest, 64)[0:32]) % N
    s = (r - h * _le(k[0:32])) % N
    return sig_r + s.to_bytes(32, "little")


def verify(public_key, message_digest, signature):
    """True if `signature` is a valid SchnorrQ signature by `public_key`.

    The three range checks come straight from the reference and are part of
    the acceptance rule, not defensive padding: a public key or R with bit 127
    of its low field element set, or a scalar s that is not 254-bit, is
    rejected before any curve work.
    """
    if len(public_key) != 32 or len(message_digest) != 32 or len(signature) != 64:
        return False
    if (public_key[15] & 0x80) or (signature[15] & 0x80) \
            or (signature[62] & 0xC0) or signature[63]:
        return False

    a = decode(public_key)
    if a is None:
        return False

    h = _le(k12(signature[0:32] + public_key + message_digest, 64)[0:32]) % N
    s = _le(signature[32:64])
    # s*G + h*A must re-encode to R. The reference folds this into one double
    # scalar multiplication; two multiplications and an add are the same point.
    r = pt_add(scalar_mul(s), scalar_mul(h, a))
    return encode(r) == signature[0:32]
