"""The Qubic fighter-NFT backend: where the real RPC calls go (docs/nft.md §5).

A STUB. It implements the `FighterNFTs` port by building the exact
transactions a real backend would send, and then refuses to send them:
every write raises `NetworkDisabled` carrying the planned transaction, and
every read raises `NotConnected` naming the query it would make. There is no
flag that turns sending on; enabling it is a code change with its own review
(the TODOs below), not configuration.

Two realizations, in the order we expect to use them (docs/nft.md §5):

1. **QX assets (testnet first).** One asset per fighter, one share, issued
   and traded through QX (contract index 1). Everything below the "QX"
   heading is QX's real ABI, read from qubic/core `src/contracts/Qx.h`:
   procedure ids, input structs, attached amounts and fees. QX knows nothing
   of QDOJO: no contest lock, no royalty. The QDOJO contract reads the owner
   through `AssetOwnershipIterator` (contracts/qubic/QDOJO.h `ownerOf`) and
   its ownership snapshots keep payouts correct if a share moves mid-contest.
2. **QDOJO-managed assets (the simulated target).** The same assets, but
   issued by and managed by the QDOJO contract, which runs the order book
   with the lock and the royalty the simulation models (nft.AssetLedger).
   Those procedures do not exist yet; `QDOJO_PROCEDURES` is the proposal.

Sources (checked 2026-09-27): https://github.com/qubic/core
src/contracts/Qx.h, src/contract_core/contract_def.h, doc/contracts.md;
https://docs.qubic.org/api/rpc/ ; https://docs.qubic.org/developers/testnet-resources/ .
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from .nft import FighterNFTs, Receipt, valid_name

# ---- QX: contract index 1 (contract_def.h QX_CONTRACT_INDEX) -----------------------
QX_INDEX = 1
QBAY_INDEX = 12                        # Qubic's NFT marketplace contract (Qbay.h); the alternative in docs/nft.md §5
QX_PROC = {"IssueAsset": 1, "TransferShareOwnershipAndPossession": 2, "AddToAskOrder": 5, "AddToBidOrder": 6,
           "RemoveFromAskOrder": 7, "RemoveFromBidOrder": 8, "TransferShareManagementRights": 9}
QX_FUNC = {"Fees": 1, "AssetAskOrders": 2, "AssetBidOrders": 3, "EntityAskOrders": 4, "EntityBidOrders": 5}
# Qx.h INITIALIZE (current since epoch 138). Read them live with QX_FUNC["Fees"] before trusting them.
QX_ISSUANCE_FEE = 1_000_000_000        # QU, attached to IssueAsset
QX_TRANSFER_FEE = 100                  # QU, attached to TransferShareOwnershipAndPossession / management moves
QX_TRADE_FEE_PER_1E9 = 3_000_000       # 0.3%: fee = price * shares * 3e6 / 1e9 + 1, taken from the seller

# ---- the proposed QDOJO market procedures (realization 2; not in protocol.md yet) --------
# Opcodes in the QDOJO frame (protocol.md §3 numbering; 20-29 are free). Bodies mirror
# the sim ledger's operations one for one. TODO(owner): accept, then add to protocol.md.
QDOJO_PROCEDURES = {"NftIssue": 20, "NftTransfer": 21, "NftAsk": 22, "NftCancelAsk": 23, "NftBid": 24,
                    "NftCancelBid": 25, "NftSettle": 26, "NftAnchor": 27}

# ---- public RPC (docs.qubic.org/api/rpc; qubic-http) ---------------------------------
RPC = {"mainnet": "https://rpc.qubic.org", "testnet": "https://testnet-rpc.qubic.org"}
RPC_PATHS = {"tick": "/v1/tick-info", "balance": "/v1/balances/{identity}", "broadcast": "/v1/broadcast-transaction",
             "query": "/v1/querySmartContract", "owned": "/v1/assets/{identity}/owned",
             "possessed": "/v1/assets/{identity}/possessed", "issued": "/v1/assets/{identity}/issued"}


class NetworkDisabled(RuntimeError):
    """A write was planned and deliberately not sent. `.plan` is the transaction."""

    def __init__(self, plan: "TxPlan"):
        super().__init__(f"not sent (the qubic NFT backend is a stub): {plan.note}")
        self.plan = plan


class NotConnected(RuntimeError):
    """A read that needs the network. The message names the exact query."""


@dataclass(frozen=True)
class TxPlan:
    """One unsigned contract call: destination contract, procedure, attached QU, input bytes."""
    contract_index: int
    input_type: int
    amount: int
    payload: bytes
    note: str

    def destination_public_key(self) -> bytes:
        return struct.pack("<Q", self.contract_index) + bytes(24)   # a contract's key: its index, then zeros


def _name(name: str) -> bytes:
    if not valid_name(name):
        raise ValueError(f"not a Qubic asset name: {name!r}")
    return name.encode("ascii").ljust(8, b"\0")


def _key(b: bytes) -> bytes:
    if len(b) != 32:
        raise ValueError("identities are 32-byte public keys")
    return b


# QX input structs, laid out as the C++ compiler lays them out (little-endian, natural alignment).
def qx_issue_input(name: str, shares: int = 1) -> bytes:
    """IssueAsset_input: assetName u64, numberOfShares s64, unitOfMeasurement u64, decimals s8 + 7 pad = 32."""
    return struct.pack("<8sq8sb7x", _name(name), shares, bytes(8), 0)


def qx_transfer_input(issuer: bytes, new_owner: bytes, name: str, shares: int = 1) -> bytes:
    """TransferShareOwnershipAndPossession_input: issuer, newOwnerAndPossessor, assetName, shares = 80."""
    return _key(issuer) + _key(new_owner) + struct.pack("<8sq", _name(name), shares)


def qx_order_input(issuer: bytes, name: str, price: int, shares: int = 1) -> bytes:
    """Add/RemoveFrom Ask/Bid Order input: issuer, assetName, price (QU per share), shares = 56."""
    return _key(issuer) + struct.pack("<8sqq", _name(name), price, shares)


def qx_management_input(issuer: bytes, name: str, new_index: int, shares: int = 1) -> bytes:
    """TransferShareManagementRights_input: Asset{issuer, assetName}, shares, newManagingContractIndex u32 + 4 pad = 56.
    UNCERTAIN: the trailing padding (sizeof 56) is inferred from alignment, not measured."""
    return _key(issuer) + struct.pack("<8sqI4x", _name(name), shares, new_index)


class QubicFighterNFTs(FighterNFTs):
    """The real-network backend, stubbed. `token_names` maps fighter id -> asset
    name (the chain knows assets by issuer + name, the game by fighter id; the
    mapping lives in the QDOJO contract's asset table once AdminRegisterAsset
    carries the name: TODO(protocol), see docs/nft.md §5)."""

    backend = "qubic"

    def __init__(self, network: str = "testnet", issuer: bytes | None = None,
                 token_names: dict[bytes, str] | None = None, **_ignored):
        if network not in RPC:
            raise ValueError(f"network is one of {sorted(RPC)}")
        self.network, self.rpc = network, RPC[network]
        self.issuer = issuer
        self.token_names = dict(token_names or {})

    # -- planning ------------------------------------------------------------------

    def _asset(self, fighter_id: bytes) -> tuple[bytes, str]:
        if self.issuer is None or fighter_id not in self.token_names:
            raise ValueError("unknown token: configure issuer and token_names")
        return self.issuer, self.token_names[fighter_id]

    def _send(self, plan: TxPlan) -> Receipt:
        # TODO(testnet): sign with the signer's seed (qdojo.qubic.tx.Transaction.sign) for tick
        # current+~10, broadcast (qdojo.chain.native.NativeChain.send, or POST RPC_PATHS["broadcast"]
        # with {"encodedTransaction": base64}), return Receipt(tx hash, target tick). Never before the
        # owner signs off the testnet run; never on mainnet without a release manifest.
        raise NetworkDisabled(plan)

    def issue(self, signer, fighter_id, to, *, creator=None, founding=False, name=None, metadata=None) -> Receipt:
        # Realization 1: QX IssueAsset puts the one share with the ISSUER (the signer); a second
        # call, TransferShareOwnershipAndPossession, gives it to `to`. Realization 2: QDOJO NftIssue.
        name = name or self.token_names.get(fighter_id)
        if not name:
            raise ValueError("a Qubic asset needs its name")
        return self._send(TxPlan(QX_INDEX, QX_PROC["IssueAsset"], QX_ISSUANCE_FEE, qx_issue_input(name),
                                 f"QX IssueAsset {name} x1 (fee {QX_ISSUANCE_FEE} QU), then transfer to {to.hex()[:12]}"))

    def transfer(self, signer, fighter_id, to) -> Receipt:
        issuer, name = self._asset(fighter_id)
        return self._send(TxPlan(QX_INDEX, QX_PROC["TransferShareOwnershipAndPossession"], QX_TRANSFER_FEE,
                                 qx_transfer_input(issuer, to, name), f"QX transfer {name} to {to.hex()[:12]}"))

    def ask(self, signer, fighter_id, price) -> Receipt:
        issuer, name = self._asset(fighter_id)
        return self._send(TxPlan(QX_INDEX, QX_PROC["AddToAskOrder"], 0, qx_order_input(issuer, name, price),
                                 f"QX ask {name} at {price} QU"))

    def cancel_ask(self, signer, fighter_id, price: int | None = None) -> Receipt:
        # QX removes an order by (price, shares): the caller must know its ask price
        # (TODO: read it with QX_FUNC["EntityAskOrders"] first).
        issuer, name = self._asset(fighter_id)
        if price is None:
            raise NotConnected("RemoveFromAskOrder needs the ask's price: query QX EntityAskOrders (function 4)")
        return self._send(TxPlan(QX_INDEX, QX_PROC["RemoveFromAskOrder"], 0, qx_order_input(issuer, name, price),
                                 f"QX cancel ask {name} at {price}"))

    def bid(self, signer, fighter_id, price) -> Receipt:
        issuer, name = self._asset(fighter_id)
        return self._send(TxPlan(QX_INDEX, QX_PROC["AddToBidOrder"], price, qx_order_input(issuer, name, price),
                                 f"QX bid {name} at {price} QU (price x shares attached as escrow)"))

    def cancel_bid(self, signer, fighter_id, price: int | None = None) -> Receipt:
        issuer, name = self._asset(fighter_id)
        if price is None:
            raise NotConnected("RemoveFromBidOrder needs the bid's price: query QX EntityBidOrders (function 5)")
        return self._send(TxPlan(QX_INDEX, QX_PROC["RemoveFromBidOrder"], 0, qx_order_input(issuer, name, price),
                                 f"QX cancel bid {name} at {price}"))

    def settle(self, signer, fighter_id) -> Receipt:
        # QX matches when an order arrives; nothing to settle. Realization 2: QDOJO NftSettle
        # (or its END_TICK sweep) once a busy fighter is idle.
        raise NotConnected("QX settles on arrival; QDOJO NftSettle (opcode 26) is not deployed")

    def manage(self, signer, fighter_id, new_index: int) -> Receipt:
        issuer, name = self._asset(fighter_id)
        return self._send(TxPlan(QX_INDEX, QX_PROC["TransferShareManagementRights"], QX_TRANSFER_FEE,
                                 qx_management_input(issuer, name, new_index),
                                 f"QX move management of {name} to contract {new_index}"))

    def poll(self, receipt: Receipt):
        # TODO(testnet): after receipt.target_tick, NativeChain.confirm(tx_hash, tick) says whether it
        # was INCLUDED; whether the procedure SUCCEEDED is only visible in its effect (re-read the
        # owner/orders). A tx not included in its target tick is dropped: resend with a new tick.
        raise NotConnected(f"poll: GET {self.rpc}{RPC_PATHS['tick']}, then the node's tick transactions")

    # -- reads -----------------------------------------------------------------------

    def token(self, fighter_id):
        # TODO(testnet): NativeChain.asset_holders(issuer_identity, name) (RequestAssets ownerships) and
        # asset_possessors(...) (possessions); exactly one owner with 1 share, else "unavailable".
        raise NotConnected(f"token: RequestAssets ownerships/possessions for {self.token_names.get(fighter_id)!r}, "
                           f"or GET {self.rpc}{RPC_PATHS['owned']}")

    def collection(self):
        raise NotConnected(f"collection: GET {self.rpc}{RPC_PATHS['issued']} for the issuer")

    def book(self, fighter_id):
        raise NotConnected("book: QX AssetAskOrders / AssetBidOrders (functions 2, 3) via "
                           f"POST {self.rpc}{RPC_PATHS['query']} {{contractIndex: 1, inputType: 2|3, ...}}")

    def history(self, fighter_id):
        raise NotConnected("history: QX logs trades (LOG_INFO _tradeMessage); needs an event indexer or archiver")

    def sales(self, fighter_id=None):
        raise NotConnected("sales: from QX trade logs (an indexer)")
