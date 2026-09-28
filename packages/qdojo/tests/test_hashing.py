import hashlib

from qdojo import hashing


def test_sha256_concatenates_its_parts():
    assert hashing.sha256(b"ab", b"c") == hashlib.sha256(b"abc").digest()
    assert hashing.sha256() == hashlib.sha256(b"").digest()
