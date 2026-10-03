"""Record live QBAY (contract 12) function answers from mainnet into test fixtures.

READ-ONLY: it calls `GET /v1/tick-info` and `POST /v1/querySmartContract`
(contract functions) through qdojo.qubic.rpc, which refuses every other path.
Nothing is signed or sent. Run it only to refresh the fixtures; tests never
touch the network.

  uv run python scripts/qbay-record-fixtures.py packages/qdojo/tests/fixtures/qbay
"""
import base64
import json
import sys
import time
from pathlib import Path

from qdojo.qubic import qbay
from qdojo.qubic.rpc import RpcClient

# What the tests decode: the research's NFT 5795, a zeroed row past the end,
# the marketplace counters, three collections (one absent), the first eight
# NFTs of BITE: Ocean Rebels (17, the demo mapping) and of Garth (4), and the
# creator walks that find a collection's NFTs on chain.
NFTS = [5795, 2_000_000]
COLLECTIONS = [4, 17, 19, 999]
DEMO = {17: [5497, 5499, 5500, 5582, 5589, 5590, 5591, 5592], 4: [1671, 1672, 1673, 1674, 1678, 1694, 1695, 1696]}


def main(out: Path):
    rpc = RpcClient(min_interval=0.5)
    reader = qbay.QbayReader(rpc)
    out.mkdir(parents=True, exist_ok=True)
    queries = []

    def rec(fn: str, data: bytes):
        doc = rpc.query_raw(qbay.QBAY_CONTRACT_INDEX, qbay.FN[fn], data)
        queries.append({"contract": qbay.QBAY_CONTRACT_INDEX, "input_type": qbay.FN[fn], "function": fn,
                        "request": base64.b64encode(data).decode(), "response": doc["responseData"]})
        return base64.b64decode(doc["responseData"])

    tick = rpc.tick_info(cache=False)
    mk = qbay.decode_marketplace(rec("getInfoOfMarketplace", b""))
    for n in NFTS + [i for ids in DEMO.values() for i in ids]:
        rec("getInfoOfNFTById", qbay.nft_by_id_input(n))
    creators = {}
    for c in COLLECTIONS:
        info = qbay.decode_collection(c, rec("getInfoOfCollectionById", qbay.collection_by_id_input(c)))
        if info.exists:
            creators[c] = info.creator
    for c in (4, 17):
        cr = creators[c]
        count = min(qbay.USER_CREATED_MAX, mk["numberOfCollection"] - 1)
        rec("getUserCreatedCollection", qbay.user_created_input(cr, 1, count))
        offset = 1
        while True:
            count = min(qbay.USER_CREATED_MAX, mk["numberOfNFT"] - offset)
            if count <= 0:
                break
            ids = qbay.decode_user_created(rec("getUserCreatedNFT", qbay.user_created_input(cr, offset, count)), count)
            if len(ids) < count:
                break
            offset += count
    doc = {"recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "rpc": rpc.base,
           "source": "qubic/core src/contracts/Qbay.h at e3ef766", "tick_info": tick, "queries": queries}
    (out / "mainnet.json").write_text(json.dumps(doc, indent=1) + "\n")
    print(f"recorded {len(queries)} answers at tick {tick['tick']} (epoch {tick['epoch']}); "
          f"{rpc.stats['requests']} requests; marketplace {mk}")
    _ = reader


if __name__ == "__main__":
    main(Path(sys.argv[1]))
