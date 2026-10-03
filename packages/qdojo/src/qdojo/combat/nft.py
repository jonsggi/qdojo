"""Fighter NFTs (docs/nft.md): one port, the game's NFT rules, a simulated Qubic backend.

Everything that issues, moves, lists or reads a fighter NFT goes through
`FighterNFTs`. Two backends implement it:

- `SimFighterNFTs` (here): the whole behaviour on the simulated chain. Its
  state is `AssetLedger`, a deterministic state machine that models what the
  real chain would hold: Qubic assets (issuer, a 1-7 character name, one
  share, an owner, a possessor and a managing contract) and a QX-style order
  book run by the QDOJO contract (asks, escrowed bids, maker-price matching,
  a market fee, a creator royalty, transfers only between contests). Every
  executed operation is one journal record ({"k": "nft"}), so a restart, a
  snapshot and the read model rebuild the identical ledger.
- `nft_qubic.QubicFighterNFTs`: the place the real RPC calls go. A stub that
  builds the exact transaction payloads and refuses to send anything.

`AssetLedger.apply` is the only code that changes NFT state; the sim backend
reaches it through `World.nft_call` (immediately, for house setup) or through
`SimChain` (a transaction with latency and drops, like any other). Nothing
here touches a real network, key or coin.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Callable

from ..hashing import sha256

SCHEMA = "qdojo.nft.v1"
QDOJO, QX = "QDOJO", "QX"            # managing contracts a fighter share can be under
QBAY = "QBAY"                        # a token mirrored from a QBAY NFT on another network (nft_qbay.py)
MAX_AMOUNT = 1_000_000_000_000_000   # Qubic's MAX_AMOUNT (QU); prices and escrow stay below it
NAME_RE = re.compile(r"^[A-Z][A-Z0-9]{0,6}$")   # Qubic asset name: 1-7 chars, A-Z first, then A-Z or 0-9
BASE36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
QX_TRANSFER_FEE = 100                # Qx.h _transferFee since epoch 138; QX pays it out to its shareholders
QX_SHAREHOLDERS = sha256(b"qdojo/sim/qx-shareholders\0")   # where the simulation sends QX's fees

# Result codes of a ledger operation (a rejected operation changes nothing).
OK = "OK"
CODES = (OK, "UNKNOWN_TOKEN", "BAD_NAME", "DUPLICATE", "NOT_ISSUER", "NOT_OWNER", "NOT_POSSESSOR", "LOCKED",
         "RESERVED", "INSUFFICIENT_FUNDS", "BAD_PRICE", "NO_ORDER", "NOT_MANAGED", "SELF_TRADE", "BOOK_FULL",
         "BAD_ARGS", "NOT_CONFIGURED", "TRADE_ON_QUBICBAY")
# Operations of the in-game market and of the asset layer that a mirrored
# token refuses: its NFT trades on QubicBay, never here (docs/nft.md §5.4).
MARKET_OPS = ("transfer", "ask", "cancel_ask", "bid", "cancel_bid", "settle", "custody", "release", "manage",
              "qx_transfer")


@dataclass(frozen=True)
class NFTPolicy:
    """The collection's economic and transfer rules (docs/nft.md §3). Recorded
    in the genesis record, so a replay never picks up changed defaults."""
    market_fee_bps: int = 250        # of each sale, to the house (the QDOJO market's fee)
    royalty_bps: int = 250           # of each secondary sale, to the token's creator
    transfer_fee: int = 100          # QU per gift transfer (QX charges 100 QU; Qx.h _transferFee)
    lock_transfers: bool = True      # a fighter changes hands only while IDLE (between contests)
    max_bids: int = 16               # open bids per token
    name_prefix: str = "QF"          # asset names QF00001, QF00002, ...


def asset_name(serial: int, prefix: str = "QF") -> str:
    """The token's Qubic asset name: prefix + base-36 serial, 7 characters."""
    width = 7 - len(prefix)
    if not 0 < serial < 36 ** width:
        raise ValueError(f"serial {serial} does not fit {width} base-36 digits")
    digits = ""
    n = serial
    while n:
        n, r = divmod(n, 36)
        digits = BASE36[r] + digits
    return prefix + digits.rjust(width, "0")


def valid_name(name: str) -> bool:
    return bool(NAME_RE.match(name or ""))


def name_u64(name: str) -> int:
    """The asset name as the chain stores it: ASCII bytes, zero padded, little-endian uint64."""
    if not valid_name(name):
        raise ValueError(f"not a Qubic asset name: {name!r}")
    return int.from_bytes(name.encode("ascii").ljust(8, b"\0"), "little")


# ---- ledger state ------------------------------------------------------------

@dataclass
class Token:
    fighter_id: bytes
    serial: int
    name: str
    issuer: bytes
    creator: bytes
    founding: bool
    owner: bytes
    possessor: bytes
    minted_tick: int
    manager: str = QDOJO
    shares: int = 1
    metadata: dict = field(default_factory=dict)
    events: list = field(default_factory=list)       # seqs of this token's events, oldest first
    mirror: dict | None = None                       # QBAY mirror state (nft_id, seq, missing, ...), else None


@dataclass
class Order:
    who: bytes
    price: int
    tick: int
    seq: int


class Reject(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


@dataclass
class Env:
    """What the ledger needs from its host, passed per call (never stored, so
    the ledger pickles cleanly into snapshots): external balances, the
    fighter's contract lock (None when not registered), and where ownership
    changes go (the contract's owner table)."""
    balances: dict
    lock_of: Callable[[bytes], str | None]
    set_owner: Callable[[bytes, bytes], None]


def _h(b: bytes | None) -> str | None:
    return b.hex() if b is not None else None


def _b(s: str | None, what: str = "identity") -> bytes:
    try:
        raw = bytes.fromhex(s or "")
    except (TypeError, ValueError):
        raise Reject("BAD_ARGS", f"{what} is not hex") from None
    if len(raw) != 32:
        raise Reject("BAD_ARGS", f"{what} is not 32 bytes")
    return raw


def _price(v) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or not 0 < v < MAX_AMOUNT:
        raise Reject("BAD_PRICE", "price must be a whole number of QU, 1 .. MAX_AMOUNT-1")
    return v


class AssetLedger:
    """The simulated chain's fighter assets and the QDOJO market's order book.

    Deterministic: the same records applied in the same order give the same
    state, results and events. Operations validate everything before they
    change anything, so a rejected one is a no-op."""

    def __init__(self):
        self.configured = False
        self.issuer = self.house = self.escrow = None
        self.backend = "sim"
        self.source: dict | None = None             # qbay-mirror: the source collection (network, id, creator)
        self.policy = NFTPolicy()
        self.tokens: dict[bytes, Token] = {}
        self.names: dict[str, bytes] = {}
        self.asks: dict[bytes, Order] = {}
        self.bids: dict[bytes, list[Order]] = {}
        self.crossed: set[bytes] = set()             # books that cross while the fighter is busy
        self.events: list[dict] = []
        self.sales: list[dict] = []
        self.anchors: list[dict] = []
        self.serial = 0
        self.seq = 0
        self.totals = {"volume": 0, "fees": 0, "royalties": 0, "royalties_to_house": 0, "transfer_fees": 0}

    # -- entry points -------------------------------------------------------

    def apply(self, env: Env, who: bytes, op: str, args: dict, amount: int, tick: int) -> dict:
        """Execute one operation. Returns {"code": ..., ...}; never raises for a bad request."""
        handler = getattr(self, "_op_" + op, None) if re.fullmatch(r"[a-z_]{1,24}", op or "") else None
        if handler is None:
            return {"code": "BAD_ARGS", "detail": f"unknown operation {op!r}"}
        if op != "genesis" and not self.configured:
            return {"code": "NOT_CONFIGURED"}
        if amount < 0 or env.balances.get(who, 0) < amount:
            return {"code": "INSUFFICIENT_FUNDS", "detail": "the attached amount exceeds the balance"}
        if op in MARKET_OPS:
            try:
                tok = self.tokens.get(bytes.fromhex(str((args or {}).get("fighter_id", ""))))
            except ValueError:
                tok = None
            if tok is not None and tok.manager == QBAY:
                return {"code": "TRADE_ON_QUBICBAY",
                        "detail": f"this fighter is QBAY NFT {tok.mirror['nft_id']}: trade it on QubicBay "
                                  f"(https://qubicbay.io/nft/{tok.mirror['nft_id']}); the in-game market is off"}
        try:
            out = handler(env, who, dict(args or {}), amount, tick) or {}
        except Reject as r:
            return {"code": r.code, **({"detail": r.detail} if r.detail else {})}
        return {"code": OK, **out}

    def end_tick(self, env: Env, tick: int):
        """The QDOJO contract's END_TICK duty: settle every crossed book whose
        fighter has become idle (a sale agreed while it fought)."""
        for fid in sorted(self.crossed):
            tok = self.tokens.get(fid)
            if tok is not None and not self._locked(env, fid):
                self._match(env, tok, tick, taker=None)

    # -- helpers ------------------------------------------------------------

    def _event(self, tick: int, kind: str, tok: Token | None, **kw) -> dict:
        self.seq += 1
        ev = {"seq": self.seq, "tick": tick, "kind": kind, "fighter_id": _h(tok.fighter_id) if tok else None,
              **{k: (_h(v) if isinstance(v, bytes) else v) for k, v in kw.items()}}
        self.events.append(ev)
        if tok is not None:
            tok.events.append(self.seq)
        return ev

    def _token(self, args: dict) -> Token:
        fid = _b(args.get("fighter_id"), "fighter_id")
        tok = self.tokens.get(fid)
        if tok is None:
            raise Reject("UNKNOWN_TOKEN")
        return tok

    def _locked(self, env: Env, fid: bytes) -> bool:
        return self.policy.lock_transfers and env.lock_of(fid) not in (None, "IDLE")

    def _holder(self, tok: Token, who: bytes):
        """The caller must own AND possess the share, under QDOJO's management."""
        if who != tok.owner:
            raise Reject("NOT_OWNER")
        if tok.possessor != tok.owner:
            raise Reject("NOT_POSSESSOR", "possession is with a custodian")
        if tok.manager != QDOJO:
            raise Reject("NOT_MANAGED", f"the share is managed by {tok.manager}")

    @staticmethod
    def _pay(env: Env, frm: bytes, to: bytes, amount: int):
        if amount <= 0:
            return
        have = env.balances.get(frm, 0)
        if have < amount:                             # the ledger's own accounting broke: never paper over it
            raise AssertionError(f"ledger payment of {amount} exceeds balance {have}")
        env.balances[frm] = have - amount
        env.balances[to] = env.balances.get(to, 0) + amount

    def _change_owner(self, env: Env, tok: Token, to: bytes):
        tok.owner = tok.possessor = to
        env.set_owner(tok.fighter_id, to)
        mine = [o for o in self.bids.get(tok.fighter_id, []) if o.who == to]
        for o in mine:                                # the new owner's own bid is moot: refund it
            self._drop_bid(env, tok, o)

    def _drop_bid(self, env: Env, tok: Token, o: Order):
        self.bids[tok.fighter_id].remove(o)
        if not self.bids[tok.fighter_id]:
            del self.bids[tok.fighter_id]
        self._pay(env, self.escrow, o.who, o.price)

    def best_bid(self, fid: bytes) -> Order | None:
        book = self.bids.get(fid)
        return min(book, key=lambda o: (-o.price, o.seq)) if book else None

    def _match(self, env: Env, tok: Token, tick: int, taker: str | None) -> dict | None:
        """Trade when the best bid meets the ask. The price is the resting
        (maker) order's, as on QX; for a crossed book settled later, the older
        order's. A busy fighter defers the trade to the first idle END_TICK."""
        fid = tok.fighter_id
        ask, bid = self.asks.get(fid), self.best_bid(fid)
        if ask is None or bid is None or bid.price < ask.price:
            self.crossed.discard(fid)
            return None
        if self._locked(env, fid):
            self.crossed.add(fid)
            return {"deferred": True}
        self.crossed.discard(fid)
        if taker == "ask":
            price = bid.price
        elif taker == "bid":
            price = ask.price
        else:
            price = ask.price if ask.seq < bid.seq else bid.price
        return {"sale": self._trade(env, tok, ask, bid, price, tick)}

    def _trade(self, env: Env, tok: Token, ask: Order, bid: Order, price: int, tick: int) -> dict:
        seller, buyer, p = ask.who, bid.who, self.policy
        fee = price * p.market_fee_bps // 10_000
        royalty = 0 if tok.creator == seller else price * p.royalty_bps // 10_000
        del self.asks[tok.fighter_id]
        self.bids[tok.fighter_id].remove(bid)
        if not self.bids[tok.fighter_id]:
            del self.bids[tok.fighter_id]
        self._pay(env, self.escrow, seller, price - fee - royalty)
        self._pay(env, self.escrow, self.house, fee)
        self._pay(env, self.escrow, tok.creator, royalty)
        self._pay(env, self.escrow, buyer, bid.price - price)          # a bid above the ask pays the ask
        self._change_owner(env, tok, buyer)
        self.totals["volume"] += price
        self.totals["fees"] += fee
        self.totals["royalties"] += royalty
        if tok.creator == self.house:
            self.totals["royalties_to_house"] += royalty
        ev = self._event(tick, "SALE", tok, **{"from": seller, "to": buyer}, price=price, fee=fee, royalty=royalty,
                         ask=ask.price, bid=bid.price)
        sale = {"seq": len(self.sales) + 1, "event": ev["seq"], "tick": tick, "fighter_id": tok.fighter_id.hex(),
                "name": tok.name, "seller": seller.hex(), "buyer": buyer.hex(), "price": price, "fee": fee,
                "royalty": royalty, "creator": tok.creator.hex(), "ask": ask.price, "bid": bid.price}
        self.sales.append(sale)
        return sale

    # -- operations -------------------------------------------------------------

    def _op_genesis(self, env, who, a, amount, t):
        if self.configured:
            raise Reject("DUPLICATE", "the collection is configured already")
        issuer = _b(a.get("issuer"), "issuer")
        if who != issuer:
            raise Reject("NOT_ISSUER")
        known = set(NFTPolicy.__dataclass_fields__)
        pol = a.get("policy") or {}
        if set(pol) - known:
            raise Reject("BAD_ARGS", f"unknown policy keys {sorted(set(pol) - known)}")
        policy = NFTPolicy(**pol)
        if not valid_name(policy.name_prefix + "0") or len(policy.name_prefix) > 3:
            raise Reject("BAD_NAME", "name prefix")
        self.issuer, self.house, self.escrow = issuer, _b(a.get("house"), "house"), _b(a.get("escrow"), "escrow")
        self.policy, self.backend = policy, str(a.get("backend", "sim"))
        src = a.get("source")
        if self.backend == "qbay-mirror" and not isinstance(src, dict):
            raise Reject("BAD_ARGS", "a qbay-mirror collection names its source (network, collection)")
        self.source = dict(src) if isinstance(src, dict) else None
        self.configured = True
        self._event(t, "GENESIS", None, issuer=issuer, house=self.house, policy=asdict(policy))
        return {}

    def _op_issue(self, env, who, a, amount, t):
        if who != self.issuer:
            raise Reject("NOT_ISSUER")
        if self.backend == "qbay-mirror":
            raise Reject("TRADE_ON_QUBICBAY", "tokens of a qbay-mirror arena come from the QBAY mirror only")
        fid, to = _b(a.get("fighter_id"), "fighter_id"), _b(a.get("to"), "to")
        creator = _b(a["creator"], "creator") if a.get("creator") else self.house
        if fid in self.tokens:
            raise Reject("DUPLICATE", "this fighter has a token")
        name = a.get("name") or asset_name(self.serial + 1, self.policy.name_prefix)
        if not valid_name(name):
            raise Reject("BAD_NAME", "1-7 characters, A-Z first, then A-Z or 0-9")
        if name in self.names:
            raise Reject("DUPLICATE", "asset name taken for this issuer")
        meta = a.get("metadata") or {}
        if not isinstance(meta, dict):
            raise Reject("BAD_ARGS", "metadata")
        self.serial += 1
        tok = Token(fid, self.serial, name, self.issuer, creator, bool(a.get("founding")), to, to, t, metadata=meta)
        self.tokens[fid], self.names[name] = tok, fid
        env.set_owner(fid, to)
        legacy = a.get("legacy_history")
        self._event(t, "MINT", tok, to=to, name=name, creator=creator, founding=tok.founding,
                    **({"legacy_history": legacy} if legacy else {}))
        return {"name": name, "serial": self.serial}

    def _op_transfer(self, env, who, a, amount, t):
        tok = self._token(a)
        to = _b(a.get("to"), "to")
        self._holder(tok, who)
        if to == who:
            raise Reject("SELF_TRADE", "already the owner")
        if tok.fighter_id in self.asks:
            raise Reject("RESERVED", "the share is reserved by an open ask; cancel it first")
        if self._locked(env, tok.fighter_id):
            raise Reject("LOCKED", "the fighter is in a contest, queue, offer or cup")
        fee = self.policy.transfer_fee
        if amount < fee:
            raise Reject("INSUFFICIENT_FUNDS", f"attach the transfer fee ({fee} QU)")
        self._pay(env, who, self.house, fee)
        self.totals["transfer_fees"] += fee
        self._change_owner(env, tok, to)
        self._event(t, "TRANSFER", tok, **{"from": who, "to": to}, fee=fee)
        return {}

    def _op_ask(self, env, who, a, amount, t):
        tok = self._token(a)
        price = _price(a.get("price"))
        self._holder(tok, who)
        old = self.asks.get(tok.fighter_id)
        self.asks[tok.fighter_id] = Order(who, price, t, self.seq + 1)
        self._event(t, "ASK", tok, **{"from": who}, price=price, **({"replaces": old.price} if old else {}))
        return self._match(env, tok, t, taker="ask") or {}

    def _op_cancel_ask(self, env, who, a, amount, t):
        tok = self._token(a)
        ask = self.asks.get(tok.fighter_id)
        if ask is None or ask.who != who:
            raise Reject("NO_ORDER")
        del self.asks[tok.fighter_id]
        self.crossed.discard(tok.fighter_id)
        self._event(t, "DELIST", tok, **{"from": who}, price=ask.price)
        return {}

    def _op_bid(self, env, who, a, amount, t):
        tok = self._token(a)
        price = _price(a.get("price"))
        if who == tok.owner:
            raise Reject("SELF_TRADE", "the owner cannot bid on its own fighter")
        if tok.manager != QDOJO:
            raise Reject("NOT_MANAGED", f"the share is managed by {tok.manager}")
        book = self.bids.get(tok.fighter_id, [])
        old = next((o for o in book if o.who == who), None)
        if old is None and len(book) >= self.policy.max_bids:
            raise Reject("BOOK_FULL")
        credit = old.price if old else 0
        if amount < price or env.balances.get(who, 0) + credit < price:
            raise Reject("INSUFFICIENT_FUNDS", "attach the full bid; it is held in escrow")
        if old:
            self._drop_bid(env, tok, old)
        self._pay(env, who, self.escrow, price)
        self.bids.setdefault(tok.fighter_id, []).append(Order(who, price, t, self.seq + 1))
        self._event(t, "BID", tok, **{"from": who}, price=price, **({"replaces": old.price} if old else {}))
        return self._match(env, tok, t, taker="bid") or {}

    def _op_cancel_bid(self, env, who, a, amount, t):
        tok = self._token(a)
        o = next((x for x in self.bids.get(tok.fighter_id, []) if x.who == who), None)
        if o is None:
            raise Reject("NO_ORDER")
        self._drop_bid(env, tok, o)
        ask, bid = self.asks.get(tok.fighter_id), self.best_bid(tok.fighter_id)
        if ask is None or bid is None or bid.price < ask.price:
            self.crossed.discard(tok.fighter_id)     # the book no longer crosses
        self._event(t, "CANCEL_BID", tok, **{"from": who}, price=o.price)
        return {}

    def _op_settle(self, env, who, a, amount, t):
        """Anyone may settle a crossed book once its fighter is idle (what the
        contract's END_TICK does by itself; a keeper call for a chain without it)."""
        tok = self._token(a)
        if tok.fighter_id not in self.crossed:
            raise Reject("NO_ORDER", "the book does not cross")
        if self._locked(env, tok.fighter_id):
            raise Reject("LOCKED")
        return self._match(env, tok, t, taker=None) or {}

    def _op_custody(self, env, who, a, amount, t):
        """The owner hands POSSESSION to a custodian (a lending desk, an escrow
        contract). Ownership, and every game right with it, stays."""
        tok = self._token(a)
        to = _b(a.get("to"), "to")
        self._holder(tok, who)
        if to == who:
            raise Reject("SELF_TRADE")
        if tok.fighter_id in self.asks:
            raise Reject("RESERVED")
        tok.possessor = to
        self._event(t, "CUSTODY", tok, **{"from": who, "to": to})
        return {}

    def _op_release(self, env, who, a, amount, t):
        tok = self._token(a)
        if who != tok.possessor or tok.possessor == tok.owner:
            raise Reject("NOT_POSSESSOR")
        tok.possessor = tok.owner
        self._event(t, "RELEASE", tok, **{"from": who, "to": tok.owner})
        return {}

    def _op_manage(self, env, who, a, amount, t):
        """Move the share's management rights (QX's TransferShareManagementRights):
        to QX it trades on QX's book, outside QDOJO's lock and royalty; back
        to QDOJO it trades here again. Open bids are refunded on the way out."""
        tok = self._token(a)
        to = a.get("manager")
        if to not in (QDOJO, QX) or to == tok.manager:
            raise Reject("BAD_ARGS", "manager must be the other of QDOJO / QX")
        if who != tok.owner or tok.possessor != tok.owner:
            raise Reject("NOT_OWNER")
        if tok.fighter_id in self.asks:
            raise Reject("RESERVED")
        if to == QX and self._locked(env, tok.fighter_id):
            raise Reject("LOCKED")
        if to == QX:
            for o in list(self.bids.get(tok.fighter_id, [])):
                self._drop_bid(env, tok, o)
            self.crossed.discard(tok.fighter_id)
        frm, tok.manager = tok.manager, to
        self._event(t, "MANAGE", tok, **{"from": frm, "to": to})
        return {}

    def _op_qx_transfer(self, env, who, a, amount, t):
        """QX's TransferShareOwnershipAndPossession for a share QX manages:
        QX knows nothing of contests, so no lock applies. The contract's
        ownership snapshots still protect payouts (protocol.md §3)."""
        tok = self._token(a)
        to = _b(a.get("to"), "to")
        if tok.manager != QX:
            raise Reject("NOT_MANAGED", "only a QX-managed share moves through QX")
        if who != tok.owner or tok.possessor != tok.owner:
            raise Reject("NOT_OWNER")
        if to == who:
            raise Reject("SELF_TRADE")
        fee = QX_TRANSFER_FEE
        if amount < fee:
            raise Reject("INSUFFICIENT_FUNDS", f"attach QX's transfer fee ({fee} QU)")
        self._pay(env, who, QX_SHAREHOLDERS, fee)
        self._change_owner(env, tok, to)
        self._event(t, "TRANSFER", tok, **{"from": who, "to": to}, fee=fee, via=QX)
        return {}

    def _op_mirror(self, env, who, a, amount, t):
        """The bridge records what it observed on the source chain for one QBAY
        NFT (nft_qbay.py): the first observation binds a token to the fighter,
        later ones move it to the new possessor or mark it gone. Only the
        issuer (the bridge's identity) may call it, only in a qbay-mirror
        collection, and only with a change (a repeat is DUPLICATE). The record
        carries the observed values, so replay never needs the network."""
        if who != self.issuer:
            raise Reject("NOT_ISSUER")
        if self.backend != "qbay-mirror":
            raise Reject("BAD_ARGS", "mirror records belong to a qbay-mirror collection")
        fid = _b(a.get("fighter_id"), "fighter_id")
        nft_id = a.get("nft_id")
        if not isinstance(nft_id, int) or isinstance(nft_id, bool) or not 0 <= nft_id < 2_097_152:
            raise Reject("BAD_ARGS", "nft_id")
        possessor = _b(a["possessor"], "possessor") if a.get("possessor") else None
        mainnet_tick = a.get("mainnet_tick")
        tok = self.tokens.get(fid)
        if tok is None:
            if possessor is None:
                raise Reject("UNKNOWN_TOKEN", "a missing NFT cannot be bound")
            if any(x.mirror and x.mirror["nft_id"] == nft_id for x in self.tokens.values()):
                raise Reject("DUPLICATE", "that NFT is bound to another fighter")
            creator = _b(a.get("creator"), "creator")
            name = _mirror_name(nft_id)
            if name in self.names:
                raise Reject("DUPLICATE", "asset name taken")
            meta = a.get("metadata") or {}
            if not isinstance(meta, dict):
                raise Reject("BAD_ARGS", "metadata")
            self.serial += 1
            tok = Token(fid, self.serial, name, self.issuer, creator, False, possessor, possessor, t, manager=QBAY,
                        metadata=meta)
            tok.mirror = {"source": QBAY, "nft_id": nft_id, "collection_id": a.get("collection_id"),
                          "network": a.get("network", "mainnet"), "seq": 1, "missing": False,
                          "observed_tick": t, "mainnet_tick": mainnet_tick}
            self.tokens[fid], self.names[name] = tok, fid
            env.set_owner(fid, possessor)
            self._event(t, "MIRROR_BIND", tok, to=possessor, nft_id=nft_id, mainnet_tick=mainnet_tick)
            return {"name": name, "serial": self.serial, "seq": 1}
        if tok.mirror is None or tok.mirror["nft_id"] != nft_id:
            raise Reject("BAD_ARGS", "the fighter is not mirrored from that NFT")
        m = tok.mirror
        if possessor is None:
            if m["missing"]:
                raise Reject("DUPLICATE", "already marked missing")
            m["missing"] = True
            env.set_owner(fid, None)
            kind, extra = "MIRROR_MISSING", {"from": tok.owner}
        else:
            if possessor == tok.owner and not m["missing"]:
                raise Reject("DUPLICATE", "no change")
            frm = tok.owner
            tok.owner = tok.possessor = possessor
            m["missing"] = False
            env.set_owner(fid, possessor)
            kind, extra = "MIRROR", {"from": frm, "to": possessor}
        m["seq"] += 1
        m["observed_tick"], m["mainnet_tick"] = t, mainnet_tick
        self._event(t, kind, tok, **extra, nft_id=nft_id, mainnet_tick=mainnet_tick)
        return {"seq": m["seq"]}

    def _op_anchor(self, env, who, a, amount, t):
        """The issuer records a frozen art manifest's root hash (AUD-009)."""
        if who != self.issuer:
            raise Reject("NOT_ISSUER")
        root = a.get("root")
        if not isinstance(root, str) or not re.fullmatch(r"[0-9a-f]{64}", root):
            raise Reject("BAD_ARGS", "root is a sha256 hex digest")
        anchor = {"root": root, "renderer": str(a.get("renderer", "")), "tokens": int(a.get("tokens", 0)), "tick": t}
        self.anchors.append(anchor)
        self._event(t, "ANCHOR", None, root=root, renderer=anchor["renderer"], tokens=anchor["tokens"])
        return {}

    # -- reads (public documents) ---------------------------------------------------

    def ownership(self, fid: bytes) -> list[tuple[int, bytes | None, bytes]]:
        """[(tick, from | None, to)]: the mint, then every change of owner."""
        tok = self.tokens[fid]
        out = []
        for seq in tok.events:
            e = self.events[seq - 1]
            if e["kind"] in ("MINT", "MIRROR_BIND"):
                out.append((e["tick"], None, bytes.fromhex(e["to"])))
            elif e["kind"] in ("SALE", "TRANSFER", "MIRROR"):
                out.append((e["tick"], bytes.fromhex(e["from"]), bytes.fromhex(e["to"])))
        return out

    def token_doc(self, fid: bytes) -> dict | None:
        tok = self.tokens.get(fid)
        if tok is None:
            return None
        ask, bid = self.asks.get(fid), self.best_bid(fid)
        last = next((self.events[s - 1] for s in reversed(tok.events) if self.events[s - 1]["kind"] == "SALE"), None)
        return {"fighter_id": fid.hex(), "serial": tok.serial, "name": tok.name, "issuer": tok.issuer.hex(),
                "shares": tok.shares, "creator": tok.creator.hex(), "founding": tok.founding,
                "owner": tok.owner.hex(), "possessor": tok.possessor.hex(), "manager": tok.manager,
                "minted_tick": str(tok.minted_tick), "metadata": dict(tok.metadata),
                "ask": {"price": str(ask.price), "seller": ask.who.hex(), "tick": str(ask.tick)} if ask else None,
                "best_bid": {"price": str(bid.price), "bidder": bid.who.hex(), "tick": str(bid.tick)} if bid else None,
                "bids": len(self.bids.get(fid, [])), "sale_pending": fid in self.crossed,
                "last_sale": {"price": str(last["price"]), "tick": str(last["tick"])} if last else None,
                "transfers": sum(1 for s in tok.events if self.events[s - 1]["kind"] in ("SALE", "TRANSFER", "MIRROR")),
                **({"mirror": dict(tok.mirror)} if tok.mirror else {})}

    def book_doc(self, fid: bytes) -> dict:
        ask = self.asks.get(fid)
        bids = sorted(self.bids.get(fid, []), key=lambda o: (-o.price, o.seq))
        return {"asks": [{"price": str(ask.price), "who": ask.who.hex(), "tick": str(ask.tick)}] if ask else [],
                "bids": [{"price": str(o.price), "who": o.who.hex(), "tick": str(o.tick)} for o in bids]}

    def history_doc(self, fid: bytes) -> list[dict]:
        tok = self.tokens[fid]
        return [_public_event(self.events[s - 1]) for s in tok.events]

    def stats(self) -> dict:
        prices = sorted(s["price"] for s in self.sales)
        return {"tokens": len(self.tokens), "listed": len(self.asks), "bids": sum(len(v) for v in self.bids.values()),
                "sales": len(prices), "volume": self.totals["volume"], "fees": self.totals["fees"],
                "royalties": self.totals["royalties"], "transfer_fees": self.totals["transfer_fees"],
                "median_price": prices[len(prices) // 2] if prices else None,
                "min_price": prices[0] if prices else None, "max_price": prices[-1] if prices else None,
                "escrow": sum(o.price for v in self.bids.values() for o in v)}


def _mirror_name(nft_id: int) -> str:
    """A mirrored token's 7-character name: QB + the QBAY NFT id in base 36."""
    digits, n = "", nft_id
    while n:
        n, r = divmod(n, 36)
        digits = BASE36[r] + digits
    return "QB" + digits.rjust(5, "0")


def _public_event(e: dict) -> dict:
    return {k: (str(v) if isinstance(v, int) and not isinstance(v, bool) else v) for k, v in e.items()}


def check(ledger: AssetLedger, balances: dict) -> list[str]:
    """Ledger invariants: escrow equals open bids; asks belong to owners; every
    token has one owner and possessor; names valid and unique; nothing crossed
    that does not cross."""
    out = []
    if not ledger.configured:
        return [] if not ledger.tokens else ["tokens exist without a genesis"]
    escrow = sum(o.price for v in ledger.bids.values() for o in v)
    if balances.get(ledger.escrow, 0) != escrow:
        out.append(f"nft escrow holds {balances.get(ledger.escrow, 0)}, open bids {escrow}")
    for fid, ask in ledger.asks.items():
        tok = ledger.tokens.get(fid)
        if tok is None or ask.who != tok.owner or tok.possessor != tok.owner:
            out.append(f"ask on {fid.hex()[:12]} is not the holder's")
    for fid, book in ledger.bids.items():
        tok = ledger.tokens.get(fid)
        if tok is None or any(o.who == tok.owner for o in book) or len({o.who for o in book}) != len(book):
            out.append(f"bad bid book on {fid.hex()[:12]}")
    seen = set()
    for fid, tok in ledger.tokens.items():
        if not valid_name(tok.name) or tok.name in seen or ledger.names.get(tok.name) != fid:
            out.append(f"bad or duplicate asset name {tok.name!r}")
        seen.add(tok.name)
        if tok.shares != 1:
            out.append(f"{tok.name} has {tok.shares} shares")
        if tok.manager == QBAY and (tok.mirror is None or fid in ledger.asks or fid in ledger.bids):
            out.append(f"mirrored {tok.name} has in-game orders or no mirror state")
    for fid in ledger.crossed:
        ask, bid = ledger.asks.get(fid), ledger.best_bid(fid)
        if ask is None or bid is None or bid.price < ask.price:
            out.append(f"{fid.hex()[:12]} marked crossed but does not cross")
    return out


# ---- the port -----------------------------------------------------------------

@dataclass(frozen=True)
class Receipt:
    """What a write returns: a transaction to poll, never a result."""
    tx_id: int
    target_tick: int
    backend: str


class FighterNFTs(ABC):
    """The one interface to fighter NFTs. Writes are transactions (poll their
    receipts); reads are confirmed state as public JSON documents. A backend
    may reject anything the rules forbid; docs/nft.md is the contract."""

    backend: str = "?"

    # -- writes ------------------------------------------------------------------
    @abstractmethod
    def issue(self, signer: bytes, fighter_id: bytes, to: bytes, *, creator: bytes | None = None,
              founding: bool = False, name: str | None = None, metadata: dict | None = None) -> Receipt: ...

    @abstractmethod
    def transfer(self, signer: bytes, fighter_id: bytes, to: bytes) -> Receipt: ...

    @abstractmethod
    def ask(self, signer: bytes, fighter_id: bytes, price: int) -> Receipt: ...

    @abstractmethod
    def cancel_ask(self, signer: bytes, fighter_id: bytes) -> Receipt: ...

    @abstractmethod
    def bid(self, signer: bytes, fighter_id: bytes, price: int) -> Receipt: ...

    @abstractmethod
    def cancel_bid(self, signer: bytes, fighter_id: bytes) -> Receipt: ...

    @abstractmethod
    def settle(self, signer: bytes, fighter_id: bytes) -> Receipt: ...

    @abstractmethod
    def poll(self, receipt: Receipt):
        """The result dict once included, "dropped" once it cannot be, None while pending."""

    # -- reads ---------------------------------------------------------------------
    @abstractmethod
    def token(self, fighter_id: bytes) -> dict | None: ...

    @abstractmethod
    def collection(self) -> list[dict]: ...

    @abstractmethod
    def book(self, fighter_id: bytes) -> dict: ...

    @abstractmethod
    def history(self, fighter_id: bytes) -> list[dict]: ...

    @abstractmethod
    def sales(self, fighter_id: bytes | None = None) -> list[dict]: ...

    def owner(self, fighter_id: bytes) -> bytes | None:
        t = self.token(fighter_id)
        return bytes.fromhex(t["owner"]) if t else None

    def possessor(self, fighter_id: bytes) -> bytes | None:
        t = self.token(fighter_id)
        return bytes.fromhex(t["possessor"]) if t else None

    def tokens_of(self, who: bytes) -> list[dict]:
        return [t for t in self.collection() if t["owner"] == who.hex()]


class SimFighterNFTs(FighterNFTs):
    """The simulated backend: `world.nft` is the ledger. With a `SimChain`,
    writes are transactions with latency, reordering and drops; without one
    (or with `immediate=True`) they execute at once (house setup, tests)."""

    backend = "sim"

    def __init__(self, world, chain=None, issuer: bytes | None = None):
        self.world, self.chain = world, chain
        self.issuer = issuer or (world.nft.issuer if world.nft.configured else None)
        self._done: dict[int, dict] = {}
        self._next = -1                               # immediate receipts count down, chain receipts up

    @property
    def ledger(self) -> AssetLedger:
        return self.world.nft

    def genesis(self, issuer: bytes, house: bytes, escrow: bytes, policy: NFTPolicy | None = None) -> dict:
        """Configure the collection (once per chain; a no-op when already done)."""
        self.issuer = issuer
        if self.ledger.configured:
            return {"code": OK, "detail": "already configured"}
        return self.world.nft_call(issuer, "genesis", {"issuer": issuer.hex(), "house": house.hex(),
                                                       "escrow": escrow.hex(),
                                                       "policy": asdict(policy or NFTPolicy()), "backend": "sim"})

    # -- writes ------------------------------------------------------------------

    def _write(self, signer: bytes, op: str, args: dict, amount: int = 0, immediate: bool = False) -> Receipt:
        if self.chain is None or immediate:
            rid = self._next
            self._next -= 1
            self._done[rid] = self.world.nft_call(signer, op, args, amount)
            return Receipt(rid, self.world.tick, self.backend)
        p = self.chain.submit_nft(signer, op, args, amount)
        return Receipt(p.tx_id, p.target_tick, self.backend)

    def issue(self, signer, fighter_id, to, *, creator=None, founding=False, name=None, metadata=None,
              immediate=False, legacy_history=None) -> Receipt:
        args = {"fighter_id": fighter_id.hex(), "to": to.hex(), "founding": bool(founding)}
        if creator is not None:
            args["creator"] = creator.hex()
        if name:
            args["name"] = name
        if metadata:
            args["metadata"] = metadata
        if legacy_history:
            args["legacy_history"] = legacy_history
        return self._write(signer, "issue", args, immediate=immediate)

    def transfer(self, signer, fighter_id, to, immediate=False) -> Receipt:
        return self._write(signer, "transfer", {"fighter_id": fighter_id.hex(), "to": to.hex()},
                           self.ledger.policy.transfer_fee, immediate)

    def ask(self, signer, fighter_id, price, immediate=False) -> Receipt:
        return self._write(signer, "ask", {"fighter_id": fighter_id.hex(), "price": int(price)}, 0, immediate)

    def cancel_ask(self, signer, fighter_id, immediate=False) -> Receipt:
        return self._write(signer, "cancel_ask", {"fighter_id": fighter_id.hex()}, 0, immediate)

    def bid(self, signer, fighter_id, price, immediate=False) -> Receipt:
        return self._write(signer, "bid", {"fighter_id": fighter_id.hex(), "price": int(price)}, int(price), immediate)

    def cancel_bid(self, signer, fighter_id, immediate=False) -> Receipt:
        return self._write(signer, "cancel_bid", {"fighter_id": fighter_id.hex()}, 0, immediate)

    def settle(self, signer, fighter_id, immediate=False) -> Receipt:
        return self._write(signer, "settle", {"fighter_id": fighter_id.hex()}, 0, immediate)

    def custody(self, signer, fighter_id, to, immediate=False) -> Receipt:
        return self._write(signer, "custody", {"fighter_id": fighter_id.hex(), "to": to.hex()}, 0, immediate)

    def release(self, signer, fighter_id, immediate=False) -> Receipt:
        return self._write(signer, "release", {"fighter_id": fighter_id.hex()}, 0, immediate)

    def manage(self, signer, fighter_id, manager, immediate=False) -> Receipt:
        return self._write(signer, "manage", {"fighter_id": fighter_id.hex(), "manager": manager}, 0, immediate)

    def qx_transfer(self, signer, fighter_id, to, immediate=False) -> Receipt:
        return self._write(signer, "qx_transfer", {"fighter_id": fighter_id.hex(), "to": to.hex()},
                           QX_TRANSFER_FEE, immediate)

    def anchor(self, root: str, renderer: str, tokens: int) -> dict:
        return self.world.nft_call(self.issuer, "anchor", {"root": root, "renderer": renderer, "tokens": tokens})

    def poll(self, receipt: Receipt):
        if receipt.tx_id < 0:
            return self._done.get(receipt.tx_id)
        return self.chain.poll(receipt)

    # -- reads ---------------------------------------------------------------------

    def token(self, fighter_id):
        return self.ledger.token_doc(fighter_id)

    def collection(self):
        return [self.ledger.token_doc(f) for f in sorted(self.ledger.tokens, key=lambda f: self.ledger.tokens[f].serial)]

    def book(self, fighter_id):
        return self.ledger.book_doc(fighter_id)

    def history(self, fighter_id):
        return self.ledger.history_doc(fighter_id) if fighter_id in self.ledger.tokens else []

    def sales(self, fighter_id=None):
        return [s for s in self.ledger.sales if fighter_id is None or s["fighter_id"] == fighter_id.hex()]

    def owner(self, fighter_id):
        t = self.ledger.tokens.get(fighter_id)
        return t.owner if t else None

    def possessor(self, fighter_id):
        t = self.ledger.tokens.get(fighter_id)
        return t.possessor if t else None

    # -- the arena's labelled fighters (the id scheme join.py shares) ----------------

    def id_for(self, label: str) -> bytes:
        return label_fighter_id(self.issuer, label)

    def public(self, fid: bytes) -> dict | None:
        """The deployment block's per-fighter asset summary (the site's fighter page reads it)."""
        doc = self.ledger.token_doc(fid)
        if doc is None:
            return None
        hist = [{"tick": str(t), "from": f.hex() if f else None, "to": to.hex()} for t, f, to in self.ledger.ownership(fid)]
        return {**{k: doc[k] for k in ("issuer", "name", "founding", "owner", "possessor", "serial", "creator",
                                       "manager", "ask", "best_bid", "last_sale")}, "history": hist,
                **({"mirror": doc["mirror"], "qbay": doc["metadata"].get("qbay")} if "mirror" in doc else {})}


def label_fighter_id(issuer: bytes, label: str) -> bytes:
    """A labelled arena fighter's ID (unchanged since the first simulated registry)."""
    return sha256(b"qdojo/combat/sim-asset/v1\0", issuer, b"QDOJOF", label.encode())


def make_backend(name: str, world=None, chain=None, **kw) -> FighterNFTs:
    """The configured backend (`nft_backend: sim | qubic | qbay-mirror`)."""
    if name == "sim":
        return SimFighterNFTs(world, chain, **kw)
    if name == "qbay-mirror":
        from .nft_qbay import QbayMirrorNFTs
        return QbayMirrorNFTs(world, **kw)
    if name == "qubic":
        from .nft_qubic import QubicFighterNFTs
        return QubicFighterNFTs(**kw)
    raise ValueError(f"unknown nft backend {name!r} (sim | qubic | qbay-mirror)")
