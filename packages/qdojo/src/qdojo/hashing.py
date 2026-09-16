"""Pure hashing and canonicalisation. No I/O. Every hash carries a domain tag."""
import hashlib
import json
import re
import struct
import unicodedata

TAG_RIDDLE = b"qdojo/riddle/v0"
TAG_ANSWER = b"qdojo/answer/v0"
TAG_COMMIT = b"qdojo/commit/v0"
TAG_SETTLE = b"qdojo/settlement/v0"
TAG_DOC = b"qdojo/doc/v0"

ANSWER_FORMATS = ("integer", "string", "hex")
IDENTITY_RE = re.compile(r"^[A-Z]{60}$")
SALT_LEN = 16
HASH_LEN = 32


class CanonicalError(ValueError):
    """An answer that cannot be canonicalised under the riddle's format."""


def sha256(*parts: bytes) -> bytes:
    h = hashlib.sha256()
    for p in parts:
        h.update(p)
    return h.digest()


def canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def is_identity(s) -> bool:
    return isinstance(s, str) and bool(IDENTITY_RE.match(s))


def canonical_answer(answer, fmt: str) -> str:
    """Canonical text of an answer under `fmt`. Raises CanonicalError."""
    if fmt not in ANSWER_FORMATS:
        raise CanonicalError(f"unknown answer format {fmt!r}")
    if answer is None or isinstance(answer, bool):
        raise CanonicalError("answer must be a string or an integer")
    if fmt == "integer":
        if isinstance(answer, int):
            return str(answer)
        s = str(answer).strip()
        if not re.fullmatch(r"[+-]?\d+", s):
            raise CanonicalError(f"not an integer: {answer!r}")
        return str(int(s))
    if fmt == "hex":
        s = str(answer).strip().lower()
        if s.startswith("0x"):
            s = s[2:]
        if not s or not re.fullmatch(r"[0-9a-f]+", s):
            raise CanonicalError(f"not hex: {answer!r}")
        return s
    s = unicodedata.normalize("NFC", str(answer)).strip()
    if not s:
        raise CanonicalError("empty answer")
    return s


def _u32(n: int) -> bytes:
    if not 0 <= n <= 0xFFFFFFFF:
        raise ValueError(f"round_id out of range: {n}")
    return struct.pack("<I", n)


def _salt(salt: bytes) -> bytes:
    if not isinstance(salt, (bytes, bytearray)) or len(salt) != SALT_LEN:
        raise ValueError(f"salt must be {SALT_LEN} bytes")
    return bytes(salt)


def riddle_hash(public_fields: dict) -> bytes:
    return sha256(TAG_RIDDLE, canonical_json(public_fields))


def answer_commitment(round_id: int, dojo_salt: bytes, canonical: str) -> bytes:
    return sha256(TAG_ANSWER, _u32(round_id), _salt(dojo_salt), canonical.encode("utf-8"))


def player_commitment(round_id: int, identity: str, salt: bytes, canonical: str) -> bytes:
    if not is_identity(identity):
        raise ValueError(f"not an identity: {identity!r}")
    return sha256(TAG_COMMIT, _u32(round_id), identity.encode("ascii"), _salt(salt), canonical.encode("utf-8"))


SETTLEMENT_UNHASHED = ("hash", "settle_tx", "settle_tick")  # only known after the hash is sent


# Everything below this line in a published document is provenance the house
# adds AFTER hashing, so the hash is taken over the body alone -- exactly as a
# settlement hashes itself without its own hash, settle_tx and settle_tick.
DOC_MARKER = "-- signed by the house ------------------------------------------------------"


def doc_body(text: str) -> str:
    """The part of a document that is hashed: everything above the marker."""
    i = text.find(DOC_MARKER)
    return text if i < 0 else text[:i]


def doc_hash(text: str) -> bytes:
    """Domain-tagged hash of a document's body. Newlines are normalised so a
    checkout with different line endings still verifies."""
    body = doc_body(text).replace("\r\n", "\n").rstrip() + "\n"
    return sha256(TAG_DOC, body.encode("utf-8"))


def settlement_hash(settlement: dict) -> bytes:
    body = {k: v for k, v in settlement.items() if k not in SETTLEMENT_UNHASHED}
    return sha256(TAG_SETTLE, canonical_json(body))
