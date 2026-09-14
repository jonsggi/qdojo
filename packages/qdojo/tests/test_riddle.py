import json

import pytest

from qdojo import riddle as R, hashing


def authored(tmp_path, **over):
    d = {"round_id": 1, "title": "Warm up", "statement": "What is 6 times 7?", "input": "",
         "answer_format": "integer", "answer": " 42 "}
    d.update(over)
    p = tmp_path / "r.json"
    p.write_text(json.dumps(d))
    return str(p)


def test_load_authored_canonicalises_answer_and_makes_salt(tmp_path):
    r, s = R.load_authored(authored(tmp_path))
    assert r.round_id == 1 and s.answer == "42" and len(s.dojo_salt) == 16
    assert R.check_answer(r, s, "042") and not R.check_answer(r, s, "43") and not R.check_answer(r, s, "x")


def test_hash_covers_only_public_fields(tmp_path):
    r, _ = R.load_authored(authored(tmp_path))
    r2, _ = R.load_authored(authored(tmp_path, answer="99"))
    assert r.hash() == r2.hash()
    r3, _ = R.load_authored(authored(tmp_path, statement="What is 7 times 7?"))
    assert r.hash() != r3.hash()
    assert r.hash() == hashing.riddle_hash(r.public())


def test_commitment_matches_hashing(tmp_path):
    r, s = R.load_authored(authored(tmp_path))
    assert R.commitment_for(r, s) == hashing.answer_commitment(1, s.dojo_salt, "42")


def test_validation_errors(tmp_path):
    with pytest.raises(R.RiddleError):
        R.load_authored(authored(tmp_path, round_id=0))
    with pytest.raises(R.RiddleError):
        R.load_authored(authored(tmp_path, answer_format="float"))
    with pytest.raises(R.RiddleError):
        R.from_public({"round_id": 1})
    with pytest.raises(hashing.CanonicalError):
        R.load_authored(authored(tmp_path, answer="forty-two"))
