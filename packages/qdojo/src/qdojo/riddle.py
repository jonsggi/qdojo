"""Riddle documents: the public part bots see, the secret part the house keeps."""
import json
import secrets
from dataclasses import dataclass, asdict

from . import hashing

PUBLIC_FIELDS = ("round_id", "title", "statement", "input", "answer_format")


class RiddleError(ValueError):
    pass


@dataclass(frozen=True)
class Riddle:
    round_id: int
    title: str
    statement: str
    input: str
    answer_format: str

    def public(self) -> dict:
        return {k: getattr(self, k) for k in PUBLIC_FIELDS}

    def hash(self) -> bytes:
        return hashing.riddle_hash(self.public())


@dataclass(frozen=True)
class RiddleSecret:
    """What the house keeps until settlement. Never leaves the house data dir."""
    answer: str
    dojo_salt: bytes

    def canonical(self, fmt: str) -> str:
        return hashing.canonical_answer(self.answer, fmt)


def validate(d: dict) -> Riddle:
    missing = [k for k in PUBLIC_FIELDS if k not in d]
    if missing:
        raise RiddleError(f"riddle missing fields: {missing}")
    if not isinstance(d["round_id"], int) or d["round_id"] < 1:
        raise RiddleError("round_id must be a positive integer")
    if d["answer_format"] not in hashing.ANSWER_FORMATS:
        raise RiddleError(f"answer_format must be one of {hashing.ANSWER_FORMATS}")
    for k in ("title", "statement", "input"):
        if not isinstance(d[k], str):
            raise RiddleError(f"{k} must be a string")
    if len(d["title"]) > 120:
        raise RiddleError("title longer than 120 chars")
    return Riddle(**{k: d[k] for k in PUBLIC_FIELDS})


def load_authored(path: str) -> tuple[Riddle, RiddleSecret]:
    """An authored riddle file: public fields plus `answer`. The salt is
    generated here, once, and must be persisted by the caller."""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    r = validate(d)
    if "answer" not in d:
        raise RiddleError("authored riddle needs an answer")
    canonical = hashing.canonical_answer(d["answer"], r.answer_format)
    return r, RiddleSecret(answer=canonical, dojo_salt=secrets.token_bytes(hashing.SALT_LEN))


def from_public(d: dict) -> Riddle:
    return validate(d)


def commitment_for(r: Riddle, secret: RiddleSecret) -> bytes:
    return hashing.answer_commitment(r.round_id, secret.dojo_salt, secret.canonical(r.answer_format))


def check_answer(r: Riddle, secret: RiddleSecret, candidate) -> bool:
    try:
        return hashing.canonical_answer(candidate, r.answer_format) == secret.canonical(r.answer_format)
    except hashing.CanonicalError:
        return False


def to_json(r: Riddle) -> str:
    return json.dumps(asdict(r), ensure_ascii=False, indent=2)
