import pytest

from qdojo import hashing


def test_canonical_integer_forms():
    assert hashing.canonical_answer(42, "integer") == "42"
    assert hashing.canonical_answer(" 042 ", "integer") == "42"
    assert hashing.canonical_answer("-7", "integer") == "-7"
    with pytest.raises(hashing.CanonicalError):
        hashing.canonical_answer("4 2", "integer")
    with pytest.raises(hashing.CanonicalError):
        hashing.canonical_answer(True, "integer")


def test_canonical_string_nfc_and_strip():
    assert hashing.canonical_answer("  café ", "string") == "café"
    with pytest.raises(hashing.CanonicalError):
        hashing.canonical_answer("   ", "string")


def test_canonical_hex():
    assert hashing.canonical_answer("0xDEADbeef", "hex") == "deadbeef"
    with pytest.raises(hashing.CanonicalError):
        hashing.canonical_answer("xyz", "hex")


def test_unknown_format_rejected():
    with pytest.raises(hashing.CanonicalError):
        hashing.canonical_answer("1", "float")


def test_commitments_are_domain_separated_and_bound():
    salt = b"\x01" * 16
    a = hashing.answer_commitment(1, salt, "42")
    p = hashing.player_commitment(1, "A" * 60, salt, "42")
    assert a != p
    assert hashing.player_commitment(1, "B" * 60, salt, "42") != p
    assert hashing.player_commitment(2, "A" * 60, salt, "42") != p
    assert hashing.player_commitment(1, "A" * 60, b"\x02" * 16, "42") != p


def test_salt_length_enforced():
    with pytest.raises(ValueError):
        hashing.answer_commitment(1, b"short", "42")


def test_identity_check():
    assert hashing.is_identity("A" * 60)
    assert not hashing.is_identity("a" * 60)
    assert not hashing.is_identity("A" * 59)


def test_settlement_hash_ignores_its_own_field():
    d = {"round_id": 1, "pot": 5}
    h = hashing.settlement_hash(d)
    assert hashing.settlement_hash({**d, "hash": h.hex()}) == h
    assert hashing.settlement_hash({**d, "settle_tx": "x" * 60, "settle_tick": 9}) == h
    assert hashing.settlement_hash({**d, "pot": 6}) != h


def test_canonical_json_is_stable():
    assert hashing.canonical_json({"b": 1, "a": [1, 2]}) == b'{"a":[1,2],"b":1}'


def test_doc_hash_covers_the_body_only():
    """The provenance block names the tick the document was signed in, so it is
    written after signing and must not change the hash."""
    body = "the document\n"
    signed = body + "\n" + hashing.DOC_MARKER + "\n  published  tick 80437002\n"
    assert hashing.doc_hash(body) == hashing.doc_hash(signed)
    assert hashing.doc_hash(body) != hashing.doc_hash("the document, edited\n")


def test_doc_hash_normalises_line_endings_and_trailing_space():
    assert hashing.doc_hash("a\r\nb\r\n") == hashing.doc_hash("a\nb\n")
    assert hashing.doc_hash("a\nb\n\n\n") == hashing.doc_hash("a\nb")


def test_doc_hash_is_domain_tagged():
    assert hashing.doc_hash("x") != hashing.sha256(b"x\n")
