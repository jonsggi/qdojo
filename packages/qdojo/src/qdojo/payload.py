"""Wire encoding of dojo messages (docs/protocol.md). Pure, no I/O."""
import struct
from dataclasses import dataclass

from .hashing import SALT_LEN, HASH_LEN

MAGIC = b"DOJO"
VERSION = 0
INPUT_TYPE = 0x444F
MAX_PAYLOAD = 1024
MAX_NAME = 32
MAX_URI = 255
MAX_ANSWER = 512

KIND_BOW, KIND_PUBLISH, KIND_COMMIT, KIND_REVEAL, KIND_SETTLE, KIND_LOBBY, KIND_ENTER = 1, 2, 3, 4, 5, 6, 7
KIND_DOC = 8   # the house signing a published document: its hash, and where to read it
MODE_SPLIT, MODE_FIRST, MODE_PODIUM = 0, 1, 2   # payout modes (docs/spec.md §5)
MODE_NAMES = {0: "split", 1: "first", 2: "podium"}
PODIUM_WEIGHTS = (5, 3, 2)                       # first, second, third correct commit
KIND_NAMES = {1: "BOW", 2: "PUBLISH", 3: "COMMIT", 4: "REVEAL", 5: "SETTLE", 6: "LOBBY", 7: "ENTER",
               8: "DOC"}
MAX_BELT = 16


class PayloadError(ValueError):
    pass


@dataclass(frozen=True)
class Bow:
    name: str
    kind = KIND_BOW


@dataclass(frozen=True)
class Publish:
    round_id: int
    entry_fee: int
    commit_window: int
    reveal_window: int
    riddle_hash: bytes
    answer_commitment: bytes
    uri: str
    payout_mode: int = MODE_FIRST
    seed_cap: int = 0        # the most the house adds to this round's pot
    match_bps: int = 10000   # house seed = min(seed_cap, stakes * match_bps / 10000); 0 = fixed seed_cap
    bond_bps: int = 0        # share of every win held as the winner's bond
    bond_rounds: int = 0     # rounds the winner must fight before the bond is released
    sensei: int = 0          # 1: a fighter above this belt may sit as a sensei
    kind = KIND_PUBLISH


@dataclass(frozen=True)
class Commit:
    round_id: int
    commitment: bytes
    kind = KIND_COMMIT


@dataclass(frozen=True)
class Reveal:
    round_id: int
    salt: bytes
    answer: str
    kind = KIND_REVEAL


@dataclass(frozen=True)
class Settle:
    round_id: int
    dojo_salt: bytes
    settlement_hash: bytes
    uri: str
    kind = KIND_SETTLE


@dataclass(frozen=True)
class Lobby:
    """The table opens: buy your entry before the riddle exists."""
    round_id: int
    entry_fee: int
    min_players: int
    lobby_window: int
    commit_window: int
    reveal_window: int
    payout_mode: int
    seed_cap: int
    match_bps: int
    belt: str
    bond_bps: int = 0
    bond_rounds: int = 0
    sensei: int = 0
    kind = KIND_LOBBY


@dataclass(frozen=True)
class Enter:
    round_id: int
    kind = KIND_ENTER


@dataclass(frozen=True)
class Doc:
    """The house putting its name to a document. The tick this lands in is the
    publication date and the signature on the transaction is the signature."""
    doc_hash: bytes
    uri: str
    kind = KIND_DOC


Message = Bow | Publish | Commit | Reveal | Settle | Lobby | Enter | Doc


def _hdr(kind: int) -> bytes:
    return MAGIC + bytes([VERSION, kind])


def _bytes(b, n, what):
    if not isinstance(b, (bytes, bytearray)) or len(b) != n:
        raise PayloadError(f"{what} must be {n} bytes")
    return bytes(b)


def _text(s, limit, what, width=1):
    raw = s.encode("utf-8")
    if len(raw) > limit:
        raise PayloadError(f"{what} longer than {limit} bytes")
    return (struct.pack("<B", len(raw)) if width == 1 else struct.pack("<H", len(raw))) + raw


def _u(n, bits, what):
    if not isinstance(n, int) or n < 0 or n >= (1 << bits):
        raise PayloadError(f"{what} out of range for u{bits}: {n!r}")
    return n


def _mode(n):
    if n not in MODE_NAMES:
        raise PayloadError(f"unknown payout mode {n!r}")
    return n


def encode(m: Message) -> bytes:
    if isinstance(m, Bow):
        out = _hdr(KIND_BOW) + _text(m.name, MAX_NAME, "name")
    elif isinstance(m, Publish):
        out = (_hdr(KIND_PUBLISH)
               + struct.pack("<IQHHBQHHHB", _u(m.round_id, 32, "round_id"), _u(m.entry_fee, 64, "entry_fee"),
                             _u(m.commit_window, 16, "commit_window"), _u(m.reveal_window, 16, "reveal_window"),
                             _mode(m.payout_mode), _u(m.seed_cap, 64, "seed_cap"), _u(m.match_bps, 16, "match_bps"),
                             _u(m.bond_bps, 16, "bond_bps"), _u(m.bond_rounds, 16, "bond_rounds"),
                             _u(m.sensei, 8, "sensei"))
               + _bytes(m.riddle_hash, HASH_LEN, "riddle_hash")
               + _bytes(m.answer_commitment, HASH_LEN, "answer_commitment")
               + _text(m.uri, MAX_URI, "uri"))
    elif isinstance(m, Commit):
        out = _hdr(KIND_COMMIT) + struct.pack("<I", _u(m.round_id, 32, "round_id")) + _bytes(m.commitment, HASH_LEN, "commitment")
    elif isinstance(m, Reveal):
        out = (_hdr(KIND_REVEAL) + struct.pack("<I", _u(m.round_id, 32, "round_id"))
               + _bytes(m.salt, SALT_LEN, "salt") + _text(m.answer, MAX_ANSWER, "answer", width=2))
    elif isinstance(m, Settle):
        out = (_hdr(KIND_SETTLE) + struct.pack("<I", _u(m.round_id, 32, "round_id"))
               + _bytes(m.dojo_salt, SALT_LEN, "dojo_salt") + _bytes(m.settlement_hash, HASH_LEN, "settlement_hash")
               + _text(m.uri, MAX_URI, "uri"))
    elif isinstance(m, Lobby):
        out = (_hdr(KIND_LOBBY)
               + struct.pack("<IQHHHHBQHHHB", _u(m.round_id, 32, "round_id"), _u(m.entry_fee, 64, "entry_fee"),
                             _u(m.min_players, 16, "min_players"), _u(m.lobby_window, 16, "lobby_window"),
                             _u(m.commit_window, 16, "commit_window"), _u(m.reveal_window, 16, "reveal_window"),
                             _mode(m.payout_mode), _u(m.seed_cap, 64, "seed_cap"), _u(m.match_bps, 16, "match_bps"),
                             _u(m.bond_bps, 16, "bond_bps"), _u(m.bond_rounds, 16, "bond_rounds"),
                             _u(m.sensei, 8, "sensei"))
               + _text(m.belt, MAX_BELT, "belt"))
    elif isinstance(m, Enter):
        out = _hdr(KIND_ENTER) + struct.pack("<I", _u(m.round_id, 32, "round_id"))
    elif isinstance(m, Doc):
        out = _hdr(KIND_DOC) + _bytes(m.doc_hash, HASH_LEN, "doc_hash") + _text(m.uri, MAX_URI, "uri")
    else:
        raise PayloadError(f"not a dojo message: {m!r}")
    if len(out) > MAX_PAYLOAD:
        raise PayloadError("payload exceeds 1024 bytes")
    return out


class _Reader:
    def __init__(self, b: bytes):
        self.b, self.i = b, 0

    def take(self, n, what):
        if self.i + n > len(self.b):
            raise PayloadError(f"truncated at {what}")
        v = self.b[self.i:self.i + n]
        self.i += n
        return v

    def unpack(self, fmt, what):
        return struct.unpack(fmt, self.take(struct.calcsize(fmt), what))

    def text(self, limit, what, width=1):
        (n,) = self.unpack("<B" if width == 1 else "<H", what)
        if n > limit:
            raise PayloadError(f"{what} longer than {limit} bytes")
        try:
            return self.take(n, what).decode("utf-8")
        except UnicodeDecodeError as e:
            raise PayloadError(f"{what} is not utf-8") from e

    def done(self, what):
        if self.i != len(self.b):
            raise PayloadError(f"trailing bytes after {what}")


def decode(b: bytes) -> Message:
    """Strict decode. Raises PayloadError on anything that is not a well-formed dojo message."""
    if len(b) > MAX_PAYLOAD:
        raise PayloadError("payload exceeds 1024 bytes")
    r = _Reader(bytes(b))
    if r.take(4, "magic") != MAGIC:
        raise PayloadError("not a dojo payload")
    version, kind = r.unpack("<BB", "header")
    if version != VERSION:
        raise PayloadError(f"unsupported version {version}")
    if kind == KIND_BOW:
        m = Bow(name=r.text(MAX_NAME, "name"))
    elif kind == KIND_PUBLISH:
        rid, fee, wc, wr, mode, cap, bps, bb, br, sen = r.unpack("<IQHHBQHHHB", "publish header")
        m = Publish(rid, fee, wc, wr, r.take(HASH_LEN, "riddle_hash"), r.take(HASH_LEN, "answer_commitment"),
                    r.text(MAX_URI, "uri"), _mode(mode), cap, bps, bb, br, sen)
    elif kind == KIND_COMMIT:
        (rid,) = r.unpack("<I", "round_id")
        m = Commit(rid, r.take(HASH_LEN, "commitment"))
    elif kind == KIND_REVEAL:
        (rid,) = r.unpack("<I", "round_id")
        m = Reveal(rid, r.take(SALT_LEN, "salt"), r.text(MAX_ANSWER, "answer", width=2))
    elif kind == KIND_SETTLE:
        (rid,) = r.unpack("<I", "round_id")
        m = Settle(rid, r.take(SALT_LEN, "dojo_salt"), r.take(HASH_LEN, "settlement_hash"), r.text(MAX_URI, "uri"))
    elif kind == KIND_LOBBY:
        rid, fee, mp, lw, wc, wr, mode, cap, bps, bb, br, sen = r.unpack("<IQHHHHBQHHHB", "lobby header")
        m = Lobby(rid, fee, mp, lw, wc, wr, _mode(mode), cap, bps, r.text(MAX_BELT, "belt"), bb, br, sen)
    elif kind == KIND_ENTER:
        (rid,) = r.unpack("<I", "round_id")
        m = Enter(rid)
    elif kind == KIND_DOC:
        m = Doc(r.take(HASH_LEN, "doc_hash"), r.text(MAX_URI, "uri"))
    else:
        raise PayloadError(f"unknown kind {kind}")
    r.done(KIND_NAMES[kind])
    return m


def try_decode(b: bytes):
    """A message, or None. Never raises: foreign payloads are simply not ours."""
    try:
        return decode(b)
    except PayloadError:
        return None


def is_dojo(b: bytes) -> bool:
    return len(b) >= 6 and bytes(b[:4]) == MAGIC
