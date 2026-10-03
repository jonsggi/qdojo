"""QBAY (contract 12) function layouts, byte for byte, against recorded mainnet answers.

The fixture (fixtures/qbay/mainnet.json) holds real `/v1/querySmartContract`
answers recorded read-only by scripts/qbay-record-fixtures.py on 2026-10-03
(epoch 233). No test here touches the network: FixtureRpc raises on any
request it has no recording for.
"""
import base64
import io
import json
import struct
import urllib.error
from pathlib import Path

import pytest

from qdojo.qubic import qbay
from qdojo.qubic.ids import public_key_from_identity
from qdojo.qubic.rpc import ALLOWED, FixtureRpc, RpcClient, RpcError

FIXTURE = Path(__file__).parent / "fixtures" / "qbay" / "mainnet.json"
GARTH = "GARTHFANXMPXMDPEZFQPWFPYMHOAWTKILINCTRMVLFFVATKVJRKEDYXGHJBF"
BITE = "BITEOFQIWBJXQDVLDFRXYJGYNHGAXVBTCYDIMDLLECFFBEUOMOYKENNBXJCB"


@pytest.fixture
def doc():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def reader(doc):
    return qbay.QbayReader(FixtureRpc(doc))


def test_layouts_are_contiguous_and_fit():
    sizes = {"s": None, "B": 1, "<I": 4, "<i": 4, "<q": 8, "<Q": 8}
    for layout, size in ((qbay.NFT_INFO, qbay.NFT_INFO_SIZE), (qbay.COLLECTION_INFO, qbay.COLLECTION_INFO_SIZE),
                         (qbay.MARKETPLACE_INFO, qbay.MARKETPLACE_INFO_SIZE)):
        end = 0
        for name, off, fmt in layout:
            width = struct.calcsize(fmt)
            assert off % min(width, 8) == 0 or fmt.endswith("s"), name      # natural alignment
            assert off >= end, name
            end = off + width
        assert end <= size and size - end < 8 and size % 8 == 0           # padded to 8, never more
    assert qbay.NFT_INFO[-1][1] == 241 and qbay.COLLECTION_INFO[-1][1] == 116


def test_inputs_byte_exact():
    assert qbay.nft_by_id_input(5795) == bytes.fromhex("a3160000")
    assert qbay.collection_by_id_input(17) == bytes.fromhex("11000000")
    user = public_key_from_identity(GARTH)
    raw = qbay.user_created_input(user, 1, 1024)
    assert len(raw) == qbay.USER_CREATED_INPUT_SIZE and raw[:32] == user and raw[32:] == bytes.fromhex("0100000000040000")
    with pytest.raises(ValueError):
        qbay.nft_by_id_input(qbay.QBAY_MAX_NUMBER_NFT)
    with pytest.raises(ValueError):
        qbay.user_created_input(user, 0, 1025)


def test_fixture_requests_match_the_encoders(doc):
    for q in doc["queries"]:
        assert q["contract"] == 12 and q["input_type"] == qbay.FN[q["function"]]
        resp = base64.b64decode(q["response"])
        want = {"getInfoOfNFTById": 248, "getInfoOfCollectionById": 120, "getInfoOfMarketplace": 56,
                "getUserCreatedNFT": 4096, "getUserCreatedCollection": 4096}[q["function"]]
        assert len(resp) == want, q["function"]


def test_nft_5795_is_what_the_research_read(reader):
    """docs/research/qubic-nft-ecosystem-2026-09-30.md §1.4: NFT 5795's URI is
    the bare CIDv1 bafkreiehy5id...; QubicBay's API shows it in BITE's
    Ocean Elements (collection 19, royalty 10%)."""
    n = reader.nft(5795)
    assert n.exists and n.held
    assert n.uri == "bafkreiehy5idpkf2qtqk2u52ufvq265t2vcvxsuxejekt6xoacspacg4hq" and len(n.uri) == 59
    assert n.royalty == 10 and qbay.identity(n.creator) == BITE
    assert qbay.identity(n.possessor) == "OWYWNDEYDYMMZBJYLZQIRQNRCPFDNRQVVGGFCOOSTETFJCRKAXHHLMGHBAYN"
    assert n.sale_price == 2_000_000_000_000_000 and n.status_of_sale == 0     # QBAY_SALE_PRICE: not listed
    d = n.doc()
    assert d["creator_identity"] == BITE and d["possessor"] == n.possessor.hex()


def test_offsets_against_raw_bytes(doc):
    """Field by field on the raw answer, the offsets QubicBay's own front end reads."""
    raw = next(base64.b64decode(q["response"]) for q in doc["queries"]
               if q["function"] == "getInfoOfNFTById" and base64.b64decode(q["request"]) == qbay.nft_by_id_input(5795))
    assert raw[0:32] == public_key_from_identity(BITE)
    assert struct.unpack_from("<I", raw, 152)[0] == 10
    assert raw[160:219] == b"bafkreiehy5idpkf2qtqk2u52ufvq265t2vcvxsuxejekt6xoacspacg4hq" and raw[219:224] == bytes(5)
    assert raw[242:] == bytes(6)                                                # padding


def test_a_row_past_the_end_reads_as_missing(reader):
    n = reader.nft(2_000_000)
    assert not n.exists and not n.held and n.uri == ""


def test_marketplace(reader):
    m = reader.marketplace()
    assert m["numberOfCollection"] == 20 and m["numberOfNFT"] == 5800 and m["statusOfMarketPlace"] == 1
    assert (m["priceOfCFB"], m["priceOfQubic"], m["numberOfNFTIncoming"]) == (454_000, 1_052_631, 26_600)


def test_collections(reader):
    g = reader.collection(4)
    assert g.exists and qbay.identity(g.creator) == GARTH and g.royalty == 10 and g.type_of_collection == 0
    assert g.price_for_drop_mint == 100_000_000 and g.current_size == 0 and len(g.uri) == 59
    r = reader.collection(17)
    assert qbay.identity(r.creator) == BITE and r.royalty == 5 and r.current_size == 177   # 23 of 200 minted
    assert reader.collection(19).royalty == 10
    assert not reader.collection(999).exists


def test_creator_walks(reader):
    mk = reader.marketplace()
    garth = reader.collection(4).creator
    assert reader.created_collections(garth, mk["numberOfCollection"]) == [4]
    ids = reader.created_nfts(garth, mk["numberOfNFT"])
    assert len(ids) == 200 and ids[:3] == [1671, 1672, 1673] and ids == sorted(ids)
    bite = reader.collection(17).creator
    assert reader.created_collections(bite, mk["numberOfCollection"]) == [17, 19]


def test_layout_errors():
    with pytest.raises(qbay.LayoutError):
        qbay.decode_nft(1, bytes(247))
    with pytest.raises(qbay.LayoutError):
        qbay.decode_collection(1, bytes(121))
    assert qbay.decode_user_created(struct.pack("<3I", 9, 5, 0) + bytes(4096 - 12), 10) == [9, 5]
    assert qbay.uri_text(b"\xff" * 64) == ""


def test_fixture_rpc_never_falls_through(doc):
    rpc = FixtureRpc(doc)
    with pytest.raises(RpcError):
        rpc.query(12, 7, qbay.nft_by_id_input(1))
    rpc.down = True
    with pytest.raises(RpcError):
        rpc.tick_info()


# ---- the HTTP client (no network: a fake opener) ------------------------------------

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _client(answers, **kw):
    seen = []

    def opener(req, timeout):
        seen.append(req)
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return _Resp(json.dumps(a).encode())
    slept = []
    c = RpcClient("https://rpc.example", opener=opener, sleep=slept.append, clock=lambda: 0.0, **kw)
    return c, seen, slept


def _http(code, retry_after=None):
    hdrs = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError("u", code, "x", hdrs, None)


def test_rpc_reads_only():
    assert ALLOWED == {("GET", "/v1/tick-info"), ("POST", "/v1/querySmartContract")}
    c, _, _ = _client([])
    with pytest.raises(RpcError, match="refused"):
        c._request("POST", "/v1/broadcast-transaction", {"encodedTransaction": "x"})
    assert not hasattr(c, "broadcast")


def test_rpc_query_body_headers_and_cache():
    out = base64.b64encode(b"\1\2").decode()
    c, seen, _ = _client([{"responseData": out}], min_interval=0)
    assert c.query(12, 7, b"\xa3\x16\0\0") == b"\1\2"
    assert c.query(12, 7, b"\xa3\x16\0\0") == b"\1\2"          # cached
    assert len(seen) == 1 and c.stats["cache_hits"] == 1
    body = json.loads(seen[0].data)
    assert body == {"contractIndex": 12, "inputType": 7, "inputSize": 4, "requestData": "oxYAAA=="}
    assert seen[0].get_header("User-agent").startswith("qdojo-qbay-mirror")
    assert seen[0].full_url == "https://rpc.example/v1/querySmartContract"


def test_rpc_backs_off_on_429_and_5xx_then_succeeds():
    c, seen, slept = _client([_http(429, "7"), _http(503), {"tickInfo": {"tick": 5, "epoch": 233}}],
                             min_interval=0, backoff=1.0)
    assert c.tick_info() == {"tick": 5, "epoch": 233}
    assert len(seen) == 3 and c.stats["retries"] == 2
    assert slept[0] >= 7                                        # Retry-After honoured
    assert 1.0 <= slept[1] <= 2.0                               # 2 ** 1 * [0.5, 1]


def test_rpc_gives_up_and_does_not_retry_client_errors():
    c, seen, _ = _client([_http(403)], min_interval=0)
    with pytest.raises(RpcError, match="403"):
        c.tick_info()
    assert len(seen) == 1
    c, seen, _ = _client([urllib.error.URLError("down")] * 3, min_interval=0, retries=2)
    with pytest.raises(RpcError, match="unreachable"):
        c.query(12, 3, b"")
    assert len(seen) == 3


def test_rpc_spaces_requests():
    now = {"t": 0.0}
    slept = []

    def sleep(d):
        slept.append(d)
        now["t"] += d
    c = RpcClient("https://rpc.example", opener=lambda req, timeout: _Resp(b'{"responseData": ""}'),
                  sleep=sleep, clock=lambda: now["t"], min_interval=0.5, cache_ttl=0)
    c.query(12, 3)
    c.query(12, 3, cache=False)
    assert slept == [0.5]
