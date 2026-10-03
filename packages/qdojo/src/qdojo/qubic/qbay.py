"""QBAY (QubicBay's NFT contract, index 12): the read-only function ABI. Pure, no I/O.

QBAY keeps its NFTs as rows in its own state, not as Qubic assets: a
creator, a possessor (there is no separate owner and no managing contract),
a royalty percentage and a 64-byte URI of which 59 bytes are kept (a bare
CIDv1). An NFT's id is its global mint index; a record holds NO collection
id, so which NFTs form a collection is known only to whoever minted them,
to QubicBay's off-chain catalogue, or, when a creator has exactly one
collection, from the creator (getUserCreatedNFT).

Every layout below is the C++ struct as the compiler lays it out (natural
alignment, `bit` = one byte, `id` = 32 bytes, `Array<uint8, 64>` = 64
bytes), read from qubic/core `src/contracts/Qbay.h` at e3ef766 (last change
c07faa8, 2026-06-22), and checked three ways:
- the output sizes the public RPC returns (248, 120, 56, 4096 bytes);
- the offsets QubicBay's own front end reads (qubicbay.io bundle
  `index-6fc064c1.js`: getInfoOfNFTById reads possessor at 32, URI at 160,
  statusOfAuction at 224, the five status bits at 237..241; the collection
  reads royalty at 40, URI at 52, typeOfCollection at 116);
- recorded live responses (tests/fixtures/qbay/*.json), decoded to the
  facts the 2026-09-30 research found (NFT 5795's URI, the marketplace
  counters).

Only FUNCTIONS are here (contract reads through `/v1/querySmartContract`).
No procedure, no transaction: nothing in this module can change QBAY state.
"""
from __future__ import annotations

import struct
from dataclasses import asdict, dataclass

from .contracts import contract_identity
from .ids import identity_from_public_key

QBAY_CONTRACT_INDEX = 12
QBAY_IDENTITY = contract_identity(QBAY_CONTRACT_INDEX)
QBAY_LENGTH_OF_URI = 59                  # Qbay.h: bytes of the 64-byte URI the contract keeps
QBAY_MAX_NUMBER_NFT = 2_097_152
QBAY_MAX_COLLECTION = 32_768
QBAY_MAX_ROYALTY_PERCENT = 97            # 100 - (2% market + 1% shareholders); QubicBay's UI caps at 10
NULL_ID = bytes(32)

# REGISTER_USER_FUNCTION ids (Qbay.h REGISTER_USER_FUNCTIONS_AND_PROCEDURES).
FN = {"getNumberOfNFTForUser": 1, "getInfoOfNFTUserPossessed": 2, "getInfoOfMarketplace": 3,
      "getInfoOfCollectionByCreator": 4, "getInfoOfCollectionById": 5, "getIncomingAuctions": 6,
      "getInfoOfNFTById": 7, "getUserCreatedCollection": 8, "getUserCreatedNFT": 9}

# ---- layouts: (field, offset, struct format) -------------------------------------
# getInfoOfNFTById_input { uint32 NFTId; }                                   4 bytes
NFT_BY_ID_INPUT = (("NFTId", 0, "<I"),)
NFT_BY_ID_INPUT_SIZE = 4
# getInfoOfNFTById_output (Qbay.h 587-617)                                 248 bytes
NFT_INFO = (
    ("creator", 0, "32s"), ("possessor", 32, "32s"), ("askUser", 64, "32s"), ("creatorOfAuction", 96, "32s"),
    ("salePrice", 128, "<q"), ("askMaxPrice", 136, "<q"), ("currentPriceOfAuction", 144, "<Q"),
    ("royalty", 152, "<I"), ("NFTidForExchange", 156, "<I"), ("URI", 160, "64s"),
    ("statusOfAuction", 224, "B"),
    ("yearAuctionStarted", 225, "B"), ("monthAuctionStarted", 226, "B"), ("dayAuctionStarted", 227, "B"),
    ("hourAuctionStarted", 228, "B"), ("minuteAuctionStarted", 229, "B"), ("secondAuctionStarted", 230, "B"),
    ("yearAuctionEnded", 231, "B"), ("monthAuctionEnded", 232, "B"), ("dayAuctionEnded", 233, "B"),
    ("hourAuctionEnded", 234, "B"), ("minuteAuctionEnded", 235, "B"), ("secondAuctionEnded", 236, "B"),
    ("statusOfSale", 237, "B"), ("statusOfAsk", 238, "B"), ("paymentMethodOfAsk", 239, "B"),
    ("statusOfExchange", 240, "B"), ("paymentMethodOfAuction", 241, "B"),
)                                         # 242 bytes of fields, padded to 8-byte alignment
NFT_INFO_SIZE = 248
# getInfoOfCollectionById_input { uint32 idOfCollection; }                   4 bytes
COLLECTION_BY_ID_INPUT_SIZE = 4
# getInfoOfCollectionById_output (Qbay.h 560-569)                          120 bytes
COLLECTION_INFO = (
    ("creator", 0, "32s"), ("priceForDropMint", 32, "<Q"), ("royalty", 40, "<I"), ("currentSize", 44, "<i"),
    ("maxSizeHoldingPerOneId", 48, "<I"), ("URI", 52, "64s"), ("typeOfCollection", 116, "B"),
)                                         # 117 bytes, padded to 120
COLLECTION_INFO_SIZE = 120
# getInfoOfMarketplace_input {} (0 bytes); _output (Qbay.h 526-536)          56 bytes
MARKETPLACE_INFO = (
    ("priceOfCFB", 0, "<Q"), ("priceOfQubic", 8, "<Q"), ("numberOfNFTIncoming", 16, "<Q"),
    ("earnedQubic", 24, "<Q"), ("earnedCFB", 32, "<Q"), ("numberOfCollection", 40, "<I"),
    ("numberOfNFT", 44, "<I"), ("statusOfMarketPlace", 48, "B"),
)                                         # 49 bytes, padded to 56
MARKETPLACE_INFO_SIZE = 56
# getUserCreatedNFT_input { id user; uint32 offset; uint32 count; }         40 bytes
# getUserCreatedNFT_output { Array<uint32, 1024> NFTId; }                4096 bytes
# (getUserCreatedCollection has the same shapes, with collection ids.)
USER_CREATED_INPUT_SIZE = 40
USER_CREATED_OUTPUT_SIZE = 4096
USER_CREATED_MAX = 1024


class LayoutError(ValueError):
    """A response that does not have the struct's size: never guess at it."""


def _unpack(layout, raw: bytes, size: int, what: str) -> dict:
    if len(raw) != size:
        raise LayoutError(f"{what}: expected {size} bytes, got {len(raw)}")
    return {name: struct.unpack_from(fmt, raw, off)[0] for name, off, fmt in layout}


def uri_text(raw64: bytes) -> str:
    """The URI as QBAY keeps it: up to 59 bytes, NUL padded. ASCII or empty."""
    kept = raw64[:QBAY_LENGTH_OF_URI].split(b"\0", 1)[0]
    try:
        return kept.decode("ascii")
    except UnicodeDecodeError:
        return ""


def identity(pub: bytes) -> str | None:
    """The 60-character Qubic identity, or None for NULL_ID."""
    return None if pub == NULL_ID else identity_from_public_key(pub)


# ---- inputs -----------------------------------------------------------------------

def nft_by_id_input(nft_id: int) -> bytes:
    if not 0 <= nft_id < QBAY_MAX_NUMBER_NFT:
        raise ValueError(f"NFT id {nft_id} out of range")
    return struct.pack("<I", nft_id)


def collection_by_id_input(collection_id: int) -> bytes:
    if not 0 <= collection_id < QBAY_MAX_COLLECTION:
        raise ValueError(f"collection id {collection_id} out of range")
    return struct.pack("<I", collection_id)


def user_created_input(user: bytes, offset: int, count: int) -> bytes:
    if len(user) != 32 or not 0 < count <= USER_CREATED_MAX or offset < 0:
        raise ValueError("user is 32 bytes, 1 <= count <= 1024, offset >= 0")
    return user + struct.pack("<II", offset, count)


# ---- outputs ----------------------------------------------------------------------

@dataclass(frozen=True)
class NftInfo:
    nft_id: int
    creator: bytes
    possessor: bytes
    royalty: int
    uri: str
    sale_price: int
    ask_max_price: int
    status_of_sale: int
    status_of_ask: int
    status_of_exchange: int
    status_of_auction: int

    @property
    def exists(self) -> bool:
        """getInfoOfNFTById has no bounds check: an id past numberOfNFT reads a
        zeroed row (creator and possessor NULL_ID). A minted NFT always has a
        creator, so a NULL creator means "no such NFT"."""
        return self.creator != NULL_ID

    @property
    def held(self) -> bool:
        """Possessed by someone. QBAY has no burn procedure; a NULL possessor
        on an existing row is treated as burned or gone."""
        return self.exists and self.possessor != NULL_ID

    def doc(self) -> dict:
        d = asdict(self)
        d["creator"], d["possessor"] = self.creator.hex(), self.possessor.hex()
        d["creator_identity"], d["possessor_identity"] = identity(self.creator), identity(self.possessor)
        return d


def decode_nft(nft_id: int, raw: bytes) -> NftInfo:
    f = _unpack(NFT_INFO, raw, NFT_INFO_SIZE, "getInfoOfNFTById")
    return NftInfo(nft_id, f["creator"], f["possessor"], f["royalty"], uri_text(f["URI"]), f["salePrice"],
                   f["askMaxPrice"], f["statusOfSale"], f["statusOfAsk"], f["statusOfExchange"],
                   f["statusOfAuction"])


@dataclass(frozen=True)
class CollectionInfo:
    collection_id: int
    creator: bytes
    price_for_drop_mint: int
    royalty: int
    current_size: int                     # what is left to mint (it counts down on every mint)
    max_size_holding_per_one_id: int
    uri: str
    type_of_collection: int               # 0 drop, 1 normal

    @property
    def exists(self) -> bool:
        """An id past numberOfCollection returns a zeroed struct."""
        return self.creator != NULL_ID

    def doc(self) -> dict:
        d = asdict(self)
        d["creator"] = self.creator.hex()
        d["creator_identity"] = identity(self.creator)
        d["type"] = "drop" if self.type_of_collection == 0 else "normal"
        return d


def decode_collection(collection_id: int, raw: bytes) -> CollectionInfo:
    f = _unpack(COLLECTION_INFO, raw, COLLECTION_INFO_SIZE, "getInfoOfCollectionById")
    return CollectionInfo(collection_id, f["creator"], f["priceForDropMint"], f["royalty"], f["currentSize"],
                          f["maxSizeHoldingPerOneId"], uri_text(f["URI"]), f["typeOfCollection"])


def decode_marketplace(raw: bytes) -> dict:
    return _unpack(MARKETPLACE_INFO, raw, MARKETPLACE_INFO_SIZE, "getInfoOfMarketplace")


def decode_user_created(raw: bytes, count: int) -> list[int]:
    """The first `count` ids of a getUserCreatedNFT/Collection answer. The
    contract leaves unused slots 0, so a 0 after the first slot ends the list
    (id 0 itself can only ever be the last, oldest entry)."""
    if len(raw) != USER_CREATED_OUTPUT_SIZE:
        raise LayoutError(f"getUserCreated*: expected {USER_CREATED_OUTPUT_SIZE} bytes, got {len(raw)}")
    ids = list(struct.unpack_from(f"<{USER_CREATED_MAX}I", raw))[:count]
    out = []
    for i, v in enumerate(ids):
        if v == 0 and i > 0 and all(x == 0 for x in ids[i:]):
            break
        out.append(v)
    return out


# ---- the read client ---------------------------------------------------------------

class QbayReader:
    """QBAY's functions through a `qdojo.qubic.rpc.RpcClient` (or anything with
    `query(contract_index, input_type, data) -> bytes` and `tick_info()`)."""

    def __init__(self, rpc):
        self.rpc = rpc

    def _q(self, fn: str, data: bytes, cache: bool = True) -> bytes:
        return self.rpc.query(QBAY_CONTRACT_INDEX, FN[fn], data, cache=cache)

    def nft(self, nft_id: int, cache: bool = True) -> NftInfo:
        return decode_nft(nft_id, self._q("getInfoOfNFTById", nft_by_id_input(nft_id), cache))

    def collection(self, collection_id: int) -> CollectionInfo:
        return decode_collection(collection_id, self._q("getInfoOfCollectionById",
                                                        collection_by_id_input(collection_id)))

    def marketplace(self, cache: bool = True) -> dict:
        return decode_marketplace(self._q("getInfoOfMarketplace", b"", cache))

    def created_nfts(self, creator: bytes, number_of_nft: int) -> list[int]:
        """Every NFT id this creator minted, oldest first. getUserCreatedNFT walks
        newest to oldest and refuses `offset + count > numberOfNFT`; its `offset`
        is 1-based in effect (cnt is incremented before the comparison)."""
        out: list[int] = []
        offset = 1
        while True:
            count = min(USER_CREATED_MAX, number_of_nft - offset)
            if count <= 0:
                break
            page = decode_user_created(self._q("getUserCreatedNFT", user_created_input(creator, offset, count)),
                                       count)
            out += page
            if len(page) < count:
                break
            offset += count
        return sorted(set(out))

    def created_collections(self, creator: bytes, number_of_collection: int) -> list[int]:
        count = min(USER_CREATED_MAX, number_of_collection - 1)
        if count <= 0:
            return []
        raw = self._q("getUserCreatedCollection", user_created_input(creator, 1, count))
        return sorted(set(decode_user_created(raw, count)))

    def tick(self) -> dict:
        return self.rpc.tick_info()
