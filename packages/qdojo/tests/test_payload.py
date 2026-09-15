import pytest

from qdojo import payload as P


def roundtrip(m):
    b = P.encode(m)
    assert len(b) <= P.MAX_PAYLOAD
    assert P.decode(b) == m
    return b


def test_bow_roundtrip():
    b = roundtrip(P.Bow("RYUBOT"))
    assert b[:4] == b"DOJO" and b[4] == 0 and b[5] == P.KIND_BOW


def test_publish_roundtrip():
    roundtrip(P.Publish(7, 1000, 600, 300, b"\x11" * 32, b"\x22" * 32, "https://dojo.example/r/7.json"))
    roundtrip(P.Publish(7, 1000, 600, 300, b"\x11" * 32, b"\x22" * 32, "", P.MODE_SPLIT))
    roundtrip(P.Publish(7, 1000, 600, 300, b"\x11" * 32, b"\x22" * 32, "", P.MODE_FIRST, 5000, 10000))
    with pytest.raises(P.PayloadError):
        P.encode(P.Publish(7, 1000, 600, 300, b"\x11" * 32, b"\x22" * 32, "", 9))


def test_commit_reveal_settle_roundtrip():
    roundtrip(P.Commit(7, b"\x33" * 32))
    roundtrip(P.Reveal(7, b"\x44" * 16, "42"))
    roundtrip(P.Reveal(7, b"\x44" * 16, "café ☃"))
    roundtrip(P.Settle(7, b"\x44" * 16, b"\x55" * 32, "https://dojo.example/s/7.json"))


def test_limits_enforced():
    with pytest.raises(P.PayloadError):
        P.encode(P.Bow("x" * 33))
    with pytest.raises(P.PayloadError):
        P.encode(P.Reveal(1, b"\x00" * 16, "x" * 513))
    with pytest.raises(P.PayloadError):
        P.encode(P.Commit(1, b"\x00" * 31))
    with pytest.raises(P.PayloadError):
        P.encode(P.Publish(1 << 32, 0, 1, 1, b"\x00" * 32, b"\x00" * 32, ""))


def test_decode_rejects_garbage_and_trailing_bytes():
    with pytest.raises(P.PayloadError):
        P.decode(b"NOPE\x00\x01")
    with pytest.raises(P.PayloadError):
        P.decode(P.encode(P.Commit(1, b"\x00" * 32)) + b"\x00")
    with pytest.raises(P.PayloadError):
        P.decode(P.encode(P.Commit(1, b"\x00" * 32))[:-1])
    with pytest.raises(P.PayloadError):
        P.decode(b"DOJO\x01\x03" + b"\x00" * 36)  # wrong version
    with pytest.raises(P.PayloadError):
        P.decode(b"DOJO\x00\x09")  # unknown kind


def test_try_decode_never_raises():
    assert P.try_decode(b"") is None
    assert P.try_decode(b"\x00" * 544) is None
    assert P.try_decode(P.encode(P.Bow("KEN.EXE"))) == P.Bow("KEN.EXE")


def test_invalid_utf8_in_text_is_rejected():
    raw = b"DOJO\x00\x01" + bytes([2]) + b"\xff\xfe"
    with pytest.raises(P.PayloadError):
        P.decode(raw)


def test_lobby_and_enter_roundtrip():
    roundtrip(P.Lobby(9, 1000, 3, 240, 300, 120, P.MODE_FIRST, 5000, 10000, "white"))
    roundtrip(P.Enter(9))
    with pytest.raises(P.PayloadError):
        P.encode(P.Lobby(9, 1000, 3, 240, 300, 120, P.MODE_FIRST, 5000, 10000, "x" * 17))
