"""The qbay-mirror NFT backend: fighter ownership mirrored from a real QBAY collection.

The game runs on testnet (today: the simulated devnet) while each fighter's
ownership comes from a QBAY NFT on Qubic MAINNET, read by a bridge the
operator runs (docs/nft.md §5.4). The bridge is READ-ONLY toward mainnet: it
calls contract functions through the public RPC (qdojo.qubic.rpc, which
refuses every other path) and never signs or sends anything.

Pieces:
- `QbayConfig`: network and RPC, the collection id, its pinned NFT ids (the
  mapping order), explicit overrides, poll interval and staleness bound.
- `pin_collection` / `validate`: which NFTs form the collection (QBAY records
  carry no collection id: the creator's own NFTs when the creator has one
  collection, else QubicBay's catalogue verified on chain), and whether the
  configured collection still matches the chain.
- `Bridge`: polls the mapped NFTs, confirms a disappearance over several
  polls, and hands the arena the latest observations; tracks staleness.
  The network is touched here only, never during replay.
- `QbayMirrorNFTs`: the `FighterNFTs` port over the arena's ledger. Reads
  are the mirrored state; every in-game market write is refused with
  TRADE_ON_QUBICBAY.
- `apply_observations`: turns observed changes into journal records, one
  ledger `mirror` record and one AdminMirrorOwner (104) contract call per
  change, so replays, snapshots, the read model and the invariants see
  only journalled data.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..qubic import qbay
from ..qubic.rpc import MAINNET_RPC, TESTNET_RPC, RpcClient, RpcError
from .codec import Op
from .nft import QBAY, FighterNFTs, Receipt

SCHEMA = "qdojo.qbay-mirror.v1"
QUBICBAY = "https://qubicbay.io"
QUBICBAY_API = "https://api.qubicbay.io/v1"
RPCS = {"mainnet": MAINNET_RPC, "testnet": TESTNET_RPC}


def nft_url(nft_id: int) -> str:
    """QubicBay's page for an NFT (its router: `nft/:id`, the on-chain id)."""
    return f"{QUBICBAY}/nft/{nft_id}"


def collection_url(collection_id: int) -> str:
    return f"{QUBICBAY}/collections/{collection_id}"


class ConfigError(ValueError):
    """The mirror's configuration does not match the chain (or itself)."""


# ---- configuration --------------------------------------------------------------

@dataclass
class QbayConfig:
    collection_id: int
    nfts: list[int]                       # the collection's NFT ids, ascending: fighter i <-> nfts[i]
    network: str = "mainnet"
    rpc_url: str | None = None
    map: dict[str, int] = field(default_factory=dict)   # label -> NFT id, overrides the order rule
    poll_seconds: float = 20.0
    stale_after_seconds: float | None = None            # default 3 polls
    missing_confirmations: int = 2
    collection_name: str | None = None
    membership: str = "explicit"          # chain-creator | qubicbay-api+chain | explicit
    schema: str = SCHEMA

    def __post_init__(self):
        if self.network not in RPCS:
            raise ConfigError(f"network is mainnet or testnet, not {self.network!r}")
        if not isinstance(self.collection_id, int) or self.collection_id < 0:
            raise ConfigError("collection_id is a non-negative integer")
        ids = list(self.nfts) + list(self.map.values())
        if any(not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < qbay.QBAY_MAX_NUMBER_NFT for i in ids):
            raise ConfigError("NFT ids are integers below 2,097,152")
        if len(set(self.nfts)) != len(self.nfts):
            raise ConfigError("an NFT id is listed twice")
        if len(set(self.map.values())) != len(self.map):
            raise ConfigError("the explicit map gives one NFT to two fighters")
        if self.poll_seconds < 2:
            raise ConfigError("poll_seconds >= 2 (the public RPC is shared)")
        if self.missing_confirmations < 1:
            raise ConfigError("missing_confirmations >= 1")

    @property
    def rpc(self) -> str:
        return self.rpc_url or RPCS[self.network]

    @property
    def stale_after(self) -> float:
        return self.stale_after_seconds if self.stale_after_seconds is not None else 3 * self.poll_seconds

    @classmethod
    def from_doc(cls, doc: dict) -> "QbayConfig":
        known = set(cls.__dataclass_fields__)
        if set(doc) - known:
            raise ConfigError(f"unknown keys {sorted(set(doc) - known)}")
        try:
            return cls(**doc)
        except TypeError as exc:
            raise ConfigError(str(exc)) from None

    @classmethod
    def load(cls, path: Path) -> "QbayConfig":
        try:
            return cls.from_doc(json.loads(Path(path).read_text()))
        except (OSError, ValueError) as exc:
            if isinstance(exc, ConfigError):
                raise
            raise ConfigError(f"{path}: {exc}") from None

    def doc(self) -> dict:
        return asdict(self)

    def assign(self, labels: list[str]) -> dict[str, int]:
        """Fighter label -> NFT id. Explicit entries first; every other label,
        in lineup order, takes the next unused NFT of the collection in id order
        (the fighter's serial order equals the NFT's index in the collection)."""
        out = {lb: self.map[lb] for lb in labels if lb in self.map}
        free = [i for i in self.nfts if i not in out.values()]
        for lb in labels:
            if lb in out:
                continue
            if not free:
                raise ConfigError(f"the collection has {len(self.nfts)} pinned NFTs; fighter {lb!r} has none")
            out[lb] = free.pop(0)
        return out


# ---- membership and validation ----------------------------------------------------

def qubicbay_collection_ids(collection_id: int, opener=None) -> list[int]:
    """The NFT ids QubicBay's off-chain catalogue files under a collection
    (GET api.qubicbay.io/v1/nfts?collectionId=; read-only). Callers verify them on chain."""
    opener = opener or urllib.request.urlopen
    ids, page = [], 1
    while True:
        req = urllib.request.Request(f"{QUBICBAY_API}/nfts?collectionId={collection_id}&limit=100&page={page}",
                                     headers={"User-Agent": "qdojo-qbay-mirror/1 (read-only)",
                                              "Accept": "application/json"})
        with opener(req, timeout=30) as resp:
            doc = json.loads(resp.read())
        ids += [int(r["id"]) for r in doc.get("results", []) if int(r.get("collectionId", -1)) == collection_id]
        if page >= int(doc.get("totalPages", 1)):
            break
        page += 1
        time.sleep(0.3)
    return sorted(set(ids))


def pin_collection(reader: qbay.QbayReader, collection_id: int, api_ids: list[int] | None = None,
                   verify: bool = True) -> dict:
    """Which NFTs form a collection, checked on chain. Returns {nfts, membership,
    collection}. A creator with one collection: its created NFTs (chain only).
    Otherwise QubicBay's catalogue ids. Each id is then verified (creator and
    royalty; one read per NFT): `verify=False` skips that for the creator walk,
    whose ids carry the creator by construction."""
    mk = reader.marketplace()
    coll = reader.collection(collection_id)
    if not coll.exists or collection_id >= mk["numberOfCollection"]:
        raise ConfigError(f"QBAY collection {collection_id} does not exist")
    colls = reader.created_collections(coll.creator, mk["numberOfCollection"])
    if colls == [collection_id]:
        ids, how = reader.created_nfts(coll.creator, mk["numberOfNFT"]), "chain-creator"
    elif api_ids is not None:
        ids, how = sorted(set(api_ids)), "qubicbay-api+chain"
    else:
        raise ConfigError(f"the creator of collection {collection_id} has collections {colls}: QBAY records carry "
                          "no collection id, so membership needs QubicBay's catalogue (pass its ids)")
    for i in ids if (verify or how != "chain-creator") else ():
        info = reader.nft(i)
        _check_member(coll, info)
    return {"nfts": ids, "membership": how, "collection": coll.doc()}


def _check_member(coll: qbay.CollectionInfo, info: qbay.NftInfo):
    if not info.exists:
        raise ConfigError(f"QBAY NFT {info.nft_id} does not exist")
    if info.creator != coll.creator:
        raise ConfigError(f"QBAY NFT {info.nft_id} is not in collection {coll.collection_id}: its creator differs")
    if info.royalty != coll.royalty:
        raise ConfigError(f"QBAY NFT {info.nft_id} is not in collection {coll.collection_id}: royalty "
                          f"{info.royalty}% differs from the collection's {coll.royalty}%")


def validate(reader: qbay.QbayReader, cfg: QbayConfig, mapping: dict[str, int]) -> dict:
    """The configured collection against the chain, before an arena binds to it:
    the collection exists, every mapped NFT exists, belongs to it (creator,
    royalty) and is held. Returns {collection, nfts: {id: NftInfo}, tick}."""
    tick = reader.tick()
    mk = reader.marketplace()
    coll = reader.collection(cfg.collection_id)
    if not coll.exists or cfg.collection_id >= mk["numberOfCollection"]:
        raise ConfigError(f"QBAY collection {cfg.collection_id} does not exist on {cfg.network}")
    infos = {}
    for label, i in mapping.items():
        if i >= mk["numberOfNFT"]:
            raise ConfigError(f"fighter {label!r}: QBAY NFT {i} does not exist (QBAY has {mk['numberOfNFT']})")
        info = reader.nft(i)
        _check_member(coll, info)
        if not info.held:
            raise ConfigError(f"fighter {label!r}: QBAY NFT {i} has no possessor")
        infos[i] = info
    return {"collection": coll, "nfts": infos, "tick": tick, "marketplace": mk}


# ---- the bridge -------------------------------------------------------------------

@dataclass(frozen=True)
class Observation:
    nft_id: int
    possessor: bytes | None               # None: the NFT is gone (confirmed over missing_confirmations polls)
    mainnet_tick: int | None


class Bridge:
    """Polls the mapped NFTs on the source chain. `poll()` never raises: a
    failure keeps the last known owners and marks the data stale once the last
    good poll is older than `stale_after`. `take()` hands the arena the latest
    observation of every NFT since the previous take."""

    def __init__(self, reader: qbay.QbayReader, cfg: QbayConfig, nft_ids: list[int], creator: bytes | None,
                 clock=time.time, log=print):
        self.reader, self.cfg, self.ids, self.creator = reader, cfg, sorted(set(nft_ids)), creator
        self.clock, self.log = clock, log
        self._lock = threading.Lock()
        self._pending: dict[int, Observation] = {}
        self._gone: dict[int, int] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.state = {"last_ok": None, "last_attempt": None, "mainnet_tick": None, "epoch": None,
                      "failures": 0, "last_error": None, "polls": 0, "mismatch": None, "applied": 0}

    def poll(self) -> bool:
        now = self.clock()
        self.state["last_attempt"] = now
        try:
            tick = self.reader.tick() if hasattr(self.reader, "tick") else {}
            obs, problems = [], []
            for i in self.ids:
                info = self.reader.nft(i, cache=False)
                if not info.exists or not info.held:
                    self._gone[i] = self._gone.get(i, 0) + 1
                    if self._gone[i] >= self.cfg.missing_confirmations:
                        obs.append(Observation(i, None, tick.get("tick")))
                    continue
                self._gone.pop(i, None)
                if self.creator is not None and info.creator != self.creator:
                    problems.append(f"NFT {i}: creator differs from collection {self.cfg.collection_id}'s")
                    continue
                obs.append(Observation(i, info.possessor, tick.get("tick")))
        except (RpcError, qbay.LayoutError, OSError) as exc:
            self.state["failures"] += 1
            self.state["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
            return False
        with self._lock:
            for o in obs:
                self._pending[o.nft_id] = o
        self.state.update(last_ok=now, mainnet_tick=tick.get("tick"), epoch=tick.get("epoch"), failures=0,
                          last_error=None, polls=self.state["polls"] + 1,
                          mismatch="; ".join(problems) if problems else None)
        return True

    def take(self) -> list[Observation]:
        with self._lock:
            out = [self._pending[k] for k in sorted(self._pending)]
            self._pending.clear()
        return out

    # -- background polling --------------------------------------------------------

    def start(self):
        if self._thread is not None:
            return
        def loop():
            while not self._stop.is_set():
                self.poll()
                self._stop.wait(self.cfg.poll_seconds)
        self._thread = threading.Thread(target=loop, name="qbay-bridge", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=30)
            self._thread = None

    # -- status (the export's staleness indicator) ------------------------------------

    def status(self) -> dict:
        now = self.clock()
        s = self.state
        age = None if s["last_ok"] is None else round(now - s["last_ok"], 1)
        if s["mismatch"]:
            status = "mismatch"
        elif age is None:
            status = "stale" if s["last_attempt"] is not None else "starting"
        else:
            status = "stale" if age > self.cfg.stale_after else "live"
        iso = (lambda x: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(x)) if x is not None else None)
        return {"source": QBAY, "network": self.cfg.network, "contract_index": qbay.QBAY_CONTRACT_INDEX,
                "collection_id": self.cfg.collection_id, "status": status, "stale": status != "live",
                "last_ok_at": iso(s["last_ok"]), "age_seconds": age, "mainnet_tick": s["mainnet_tick"],
                "epoch": s["epoch"], "consecutive_failures": s["failures"], "last_error": s["last_error"],
                "mismatch": s["mismatch"], "poll_seconds": self.cfg.poll_seconds,
                "stale_after_seconds": self.cfg.stale_after, "polls": s["polls"], "applied_changes": s["applied"],
                "nfts": len(self.ids)}


# ---- applying observations: journal records only ---------------------------------------

def bind_record(fid: bytes, cfg: QbayConfig, coll: qbay.CollectionInfo, info: qbay.NftInfo,
                mainnet_tick: int | None) -> dict:
    """The ledger `mirror` arguments that bind a fighter to its NFT."""
    meta = {"qbay": {"nft_id": info.nft_id, "collection_id": cfg.collection_id,
                     "collection_name": cfg.collection_name, "network": cfg.network,
                     "contract_index": qbay.QBAY_CONTRACT_INDEX, "cid": info.uri, "uri": info.uri,
                     "royalty_percent": info.royalty, "creator_identity": qbay.identity(info.creator),
                     "url": nft_url(info.nft_id), "collection_url": collection_url(cfg.collection_id)}}
    return {"fighter_id": fid.hex(), "nft_id": info.nft_id, "possessor": info.possessor.hex(),
            "creator": info.creator.hex(), "collection_id": cfg.collection_id, "network": cfg.network,
            "mainnet_tick": mainnet_tick, "metadata": meta}


def mirror_owner_fields(fid: bytes, tok, owner: bytes | None) -> dict:
    """AdminMirrorOwner (104) for a mirrored token's current state."""
    return dict(fighter_id=fid, registry_version=1, house_npc=0, source_contract=qbay.QBAY_CONTRACT_INDEX,
                source_id=tok.mirror["nft_id"], owner=owner or bytes(32), mirror_seq=tok.mirror["seq"])


def apply_observations(world, issuer: bytes, admin: bytes, observations: list[Observation], log=print) -> int:
    """Each observed CHANGE becomes two journalled records in the same tick: the
    ledger's `mirror` op (export, read model, history) and AdminMirrorOwner on
    the contract (what a testnet QDOJO receives). Unchanged and unmapped NFTs
    are skipped. Returns the number of changes applied."""
    by_nft = {t.mirror["nft_id"]: (fid, t) for fid, t in world.nft.tokens.items() if t.mirror}
    applied = 0
    for o in observations:
        hit = by_nft.get(o.nft_id)
        if hit is None:
            log(f"tick {world.tick}: qbay mirror: NFT {o.nft_id} is not mapped to a fighter; ignored")
            continue
        fid, tok = hit
        if o.possessor is None and tok.mirror["missing"]:
            continue
        if o.possessor is not None and o.possessor == tok.owner and not tok.mirror["missing"]:
            continue
        r = world.nft_call(issuer, "mirror", {"fighter_id": fid.hex(), "nft_id": o.nft_id,
                                              "possessor": o.possessor.hex() if o.possessor else None,
                                              "mainnet_tick": o.mainnet_tick})
        if r["code"] != "OK":
            log(f"tick {world.tick}: qbay mirror: NFT {o.nft_id}: {r}")
            continue
        c = world.send(admin, Op.ADMIN_MIRROR_OWNER, **mirror_owner_fields(fid, tok, o.possessor))
        if not c.ok:
            log(f"tick {world.tick}: qbay mirror: AdminMirrorOwner for NFT {o.nft_id} refused ({c.code.name})")
        who = qbay.identity(o.possessor)[:12] + "..." if o.possessor else "nobody (gone)"
        log(f"tick {world.tick}: qbay mirror: NFT {o.nft_id} now held by {who}")
        applied += 1
    return applied


# ---- the port ---------------------------------------------------------------------------

class QbayMirrorNFTs(FighterNFTs):
    """`FighterNFTs` over the arena ledger's mirrored tokens. Ownership comes
    only from the bridge; every write of the in-game market is refused."""

    backend = "qbay-mirror"

    def __init__(self, world, issuer: bytes | None = None):
        self.world = world
        self.issuer = issuer or (world.nft.issuer if world.nft.configured else None)
        self._done: dict[int, dict] = {}
        self._next = -1

    @property
    def ledger(self):
        return self.world.nft

    def genesis(self, issuer: bytes, house: bytes, escrow: bytes, source: dict) -> dict:
        self.issuer = issuer
        if self.ledger.configured:
            return {"code": "OK", "detail": "already configured"}
        return self.world.nft_call(issuer, "genesis", {"issuer": issuer.hex(), "house": house.hex(),
                                                       "escrow": escrow.hex(), "backend": self.backend,
                                                       "source": source})

    # -- writes: refused -------------------------------------------------------------

    def _refuse(self, fighter_id: bytes | None = None) -> Receipt:
        tok = self.ledger.tokens.get(fighter_id) if fighter_id else None
        where = nft_url(tok.mirror["nft_id"]) if tok is not None and tok.mirror else QUBICBAY
        rid = self._next
        self._next -= 1
        self._done[rid] = {"code": "TRADE_ON_QUBICBAY",
                           "detail": f"ownership is mirrored from mainnet QBAY: trade on QubicBay ({where}); "
                                     "the in-game market is off"}
        return Receipt(rid, self.world.tick, self.backend)

    def issue(self, signer, fighter_id, to, **kw) -> Receipt:
        return self._refuse(fighter_id)

    def transfer(self, signer, fighter_id, to, **kw) -> Receipt:
        return self._refuse(fighter_id)

    def ask(self, signer, fighter_id, price, **kw) -> Receipt:
        return self._refuse(fighter_id)

    def cancel_ask(self, signer, fighter_id, **kw) -> Receipt:
        return self._refuse(fighter_id)

    def bid(self, signer, fighter_id, price, **kw) -> Receipt:
        return self._refuse(fighter_id)

    def cancel_bid(self, signer, fighter_id, **kw) -> Receipt:
        return self._refuse(fighter_id)

    def settle(self, signer, fighter_id, **kw) -> Receipt:
        return self._refuse(fighter_id)

    def poll(self, receipt: Receipt):
        return self._done.get(receipt.tx_id)

    # -- reads -------------------------------------------------------------------------

    def token(self, fighter_id):
        return self.ledger.token_doc(fighter_id)

    def collection(self):
        led = self.ledger
        return [led.token_doc(f) for f in sorted(led.tokens, key=lambda f: led.tokens[f].serial)]

    def book(self, fighter_id):
        return {"asks": [], "bids": []}

    def history(self, fighter_id):
        return self.ledger.history_doc(fighter_id) if fighter_id in self.ledger.tokens else []

    def sales(self, fighter_id=None):
        return []

    def owner(self, fighter_id):
        """owner = possessor = the QBAY possessor; None while the NFT is gone."""
        t = self.ledger.tokens.get(fighter_id)
        if t is None or (t.mirror and t.mirror["missing"]):
            return None
        return t.owner

    def possessor(self, fighter_id):
        return self.owner(fighter_id)

    def nft_of(self, fighter_id) -> int | None:
        t = self.ledger.tokens.get(fighter_id)
        return t.mirror["nft_id"] if t is not None and t.mirror else None

    def fighter_of(self, nft_id: int) -> bytes | None:
        """The fighter an NFT is mapped to, or None for an unmapped NFT."""
        return next((f for f, t in self.ledger.tokens.items() if t.mirror and t.mirror["nft_id"] == nft_id), None)

    def id_for(self, label: str) -> bytes:
        from .nft import label_fighter_id
        return label_fighter_id(self.issuer, label)

    def public(self, fid: bytes) -> dict | None:
        from .nft import SimFighterNFTs
        return SimFighterNFTs.public(self, fid)


def make_reader(cfg: QbayConfig) -> qbay.QbayReader:
    return qbay.QbayReader(RpcClient(cfg.rpc))


# ---- CLI: qdojo combat qbay pin | show (read-only) ------------------------------------------

def cmd_pin(a):
    """Write a qbay-mirror configuration for an existing collection, membership checked on chain."""
    rpc = RpcClient(a.rpc or RPCS[a.network])
    reader = qbay.QbayReader(rpc)
    api_ids = qubicbay_collection_ids(a.collection) if a.api else None
    try:
        pin = pin_collection(reader, a.collection, api_ids)
    except (ConfigError, RpcError) as exc:
        raise SystemExit(f"qbay pin: {exc}") from None
    ids = pin["nfts"][: a.count] if a.count else pin["nfts"]
    cfg = QbayConfig(collection_id=a.collection, nfts=ids, network=a.network, rpc_url=a.rpc,
                     collection_name=a.name, membership=pin["membership"], poll_seconds=a.poll_seconds)
    Path(a.out).write_text(json.dumps(cfg.doc(), indent=1) + "\n")
    c = pin["collection"]
    print(f"collection {a.collection}: creator {c['creator_identity']}, royalty {c['royalty']}%, {c['type']}; "
          f"{len(pin['nfts'])} NFTs ({pin['membership']}); pinned {len(ids)} to {a.out}")


def cmd_show(a):
    """Print a collection's (or one NFT's) on-chain QBAY record."""
    reader = qbay.QbayReader(RpcClient(a.rpc or RPCS[a.network]))
    if a.nft is not None:
        print(json.dumps(reader.nft(a.nft).doc(), indent=1))
    if a.collection is not None:
        print(json.dumps(reader.collection(a.collection).doc(), indent=1))
    if a.nft is None and a.collection is None:
        print(json.dumps({**reader.marketplace(), "tick": reader.tick()}, indent=1))


def add_parser(s):
    p = s.add_parser("qbay", help="read-only QBAY (QubicBay) reads for the qbay-mirror NFT backend")
    sub = p.add_subparsers(dest="qbay_cmd", required=True)
    d = sub.add_parser("pin", help="write a qbay-mirror config for an existing QBAY collection")
    d.add_argument("--collection", type=int, required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--count", type=int, help="pin only the first N NFTs (by id)")
    d.add_argument("--name", help="the collection's display name")
    d.add_argument("--api", action="store_true",
                   help="take membership from QubicBay's catalogue (needed when the creator has several collections)")
    d.add_argument("--network", default="mainnet", choices=tuple(RPCS))
    d.add_argument("--rpc", help="RPC base URL (default: the network's public RPC)")
    d.add_argument("--poll-seconds", type=float, default=20.0)
    d.set_defaults(fn=cmd_pin)
    d = sub.add_parser("show", help="print an NFT, a collection or the marketplace counters")
    d.add_argument("--nft", type=int)
    d.add_argument("--collection", type=int)
    d.add_argument("--network", default="mainnet", choices=tuple(RPCS))
    d.add_argument("--rpc")
    d.set_defaults(fn=cmd_show)
