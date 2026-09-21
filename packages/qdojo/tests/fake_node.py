"""A Qubic node, faked well enough to test the wire against.

The protocol layer is the part that moves money and the part a unit test
usually cannot reach, so this speaks it for real: correct framing, the
unsolicited peer packet on connect, multi-packet responses closed by
END_RESPOND, and a record of every transaction broadcast to it.

It is deliberately able to MISBEHAVE -- silence, garbage sizes, a hang-up
mid-packet, unrelated packets before the answer -- because those are the
cases a live node will eventually produce and a test against a well-behaved
server proves nothing about them.
"""
import socket
import socketserver
import struct
import threading

from qdojo.qubic.contracts import (
    ASSET_ISSUANCE,
    ASSET_OWNERSHIP,
    ASSET_POSSESSION,
    ASSET_REQ_OWNERSHIPS,
    ASSET_REQ_POSSESSIONS,
    asset_name_bytes,
)
from qdojo.qubic.node import (
    BROADCAST_TRANSACTION,
    END_RESPOND,
    EXCHANGE_PUBLIC_PEERS,
    HEADER_SIZE,
    REQUEST_ASSETS,
    REQUEST_CONTRACT_FUNCTION,
    REQUEST_CURRENT_TICK_INFO,
    REQUEST_ENTITY,
    REQUEST_OWNED_ASSETS,
    REQUEST_TICK_TRANSACTIONS,
    RESPOND_ASSETS,
    RESPOND_CONTRACT_FUNCTION,
    RESPOND_CURRENT_TICK_INFO,
    RESPOND_ENTITY,
    RESPOND_OWNED_ASSETS,
)


def frame(msg_type: int, body: bytes = b"", dejavu: int = 0) -> bytes:
    size = HEADER_SIZE + len(body)
    return bytes([size & 0xFF, (size >> 8) & 0xFF, (size >> 16) & 0xFF, msg_type]) \
        + struct.pack("<I", dejavu) + body


def entity_body(public_key: bytes, incoming: int, outgoing: int, tick: int,
                n_in: int = 1, n_out: int = 0) -> bytes:
    """A full RespondEntity: the 64-byte record, tick, spectrum index, and the
    24 sibling hashes a real node appends (840 bytes in total)."""
    rec = struct.pack("<32sqqIIII", public_key, incoming, outgoing, n_in, n_out, tick, 0)
    return rec + struct.pack("<Ii", tick, 0) + bytes(32 * 24)


def issuance_record(issuer_key: bytes, name: str, decimals: int = 0) -> bytes:
    """A 48-byte AssetRecord of type ISSUANCE (structs.h)."""
    return struct.pack("<32sB7sb7s", issuer_key, ASSET_ISSUANCE, asset_name_bytes(name)[:7],
                       decimals, bytes(7))


def ownership_record(owner_key: bytes, shares: int, managing_contract: int = 1, index: int = 0) -> bytes:
    """A 48-byte AssetRecord of type OWNERSHIP."""
    return struct.pack("<32sBxHIq", owner_key, ASSET_OWNERSHIP, managing_contract, index, shares)


def possession_record(possessor_key: bytes, shares: int, managing_contract: int = 1, index: int = 0) -> bytes:
    """A 48-byte AssetRecord of type POSSESSION."""
    return struct.pack("<32sBxHIq", possessor_key, ASSET_POSSESSION, managing_contract, index, shares)


def owned_asset_body(owner_key: bytes, issuer_key: bytes, name: str, shares: int, tick: int) -> bytes:
    """A full RespondOwnedAssets: ownership, issuance, tick, universe index,
    and the 24 sibling hashes a real node appends (872 bytes)."""
    return ownership_record(owner_key, shares) + issuance_record(issuer_key, name) \
        + struct.pack("<II", tick, 0) + bytes(32 * 24)


class FakeNode:
    """A node on 127.0.0.1. Use as a context manager; `.port` is the address.

        with FakeNode(tick=1000) as n:
            ...
            assert n.received          # payloads broadcast to it
    """

    def __init__(self, host="127.0.0.1", port=0, tick=1000, epoch=42, initial_tick=900, balances=None,
                 tick_txs=None, peers=("9.9.9.9", "8.8.8.8"), announce_peers=True,
                 noise_before_answer=0, bad_size=False, hang_up=False, silent=False,
                 lie_about=None, contract_outputs=None, owned=None, holders=None, possessors=None):
        self.host, self.want_port = host, port
        self.ip, self.port = host, port   # known before start when a port was given
        self.tick, self.epoch, self.initial_tick = tick, epoch, initial_tick
        self.balances = dict(balances or {})          # public_key bytes -> (in, out)
        self.tick_txs = dict(tick_txs or {})          # tick -> [payload bytes]
        # (contract index, function) -> output bytes; b"" is the node's way of
        # saying it could not run the function
        self.contract_outputs = dict(contract_outputs or {})
        self.owned = dict(owned or {})                # owner key -> [(issuer key, name, shares)]
        self.holders = dict(holders or {})            # (issuer key, name) -> [(owner key, shares)]
        # (issuer key, name) -> [(possessor key, shares)]; None (the default)
        # means "same as `holders`, read live" -- owner == possessor is the
        # common case: plain Qx holdings that were never transferred
        # separately. A test that mutates `.holders` after construction
        # (to model a holder set discovered later) sees that mutation here
        # too, unless `possessors=` was given explicitly.
        self.possessors = dict(possessors) if possessors is not None else None
        self.contract_calls: list[tuple[int, int, bytes]] = []   # (index, function, input) asked
        self.peers, self.announce_peers = list(peers), announce_peers
        self.noise_before_answer = noise_before_answer
        self.bad_size, self.hang_up, self.silent = bad_size, hang_up, silent
        self.lie_about = lie_about       # answer every entity query about THIS key
        self.received: list[bytes] = []               # broadcast payloads, in order
        self.requests: list[int] = []                 # message types asked of us
        self._srv = None
        self._thread = None

    def wait_for_received(self, n=1, timeout=2.0):
        """Block until `n` broadcasts have arrived, or give up.

        Broadcasting is fire-and-forget by design -- the protocol has no reply
        to BROADCAST_TRANSACTION -- so a test cannot assert on `received`
        the instant `broadcast()` returns. That is the property, not a flaw.
        """
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            if len(self.received) >= n:
                return True
            time.sleep(0.01)
        return False

    # ------------------------------------------------------------ lifecycle
    def __enter__(self):
        outer = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                outer._serve(self.request)

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._srv = Server((self.host, self.want_port), Handler)
        self.ip, self.port = self._srv.server_address
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        if self._srv is not None:
            self._srv.shutdown()
            self._srv.server_close()
        return False

    # -------------------------------------------------------------- serving
    def _serve(self, sock):
        sock.settimeout(5.0)
        if self.hang_up:
            sock.close()
            return
        if self.announce_peers:
            body = b"".join(bytes(int(p) for p in ip.split(".")) for ip in self.peers)
            sock.sendall(frame(EXCHANGE_PUBLIC_PEERS, body.ljust(16, b"\0")))
        while True:
            try:
                head = self._read(sock, HEADER_SIZE)
            except (OSError, ConnectionError):
                return
            if head is None:
                return
            size = int.from_bytes(head[0:3], "little")
            msg_type = head[3]
            body = self._read(sock, size - HEADER_SIZE) if size > HEADER_SIZE else b""
            if body is None:
                return
            self.requests.append(msg_type)
            try:
                self._answer(sock, msg_type, body)
            except (OSError, ConnectionError):
                return

    @staticmethod
    def _read(sock, n):
        buf = b""
        while len(buf) < n:
            try:
                chunk = sock.recv(n - len(buf))
            except (socket.timeout, OSError):
                return None
            if not chunk:
                return None
            buf += chunk
        return buf

    def _answer(self, sock, msg_type, body):
        if msg_type == BROADCAST_TRANSACTION:
            self.received.append(body)          # a real node never replies to this
            return
        if self.silent:
            return
        for _ in range(self.noise_before_answer):
            # A packet we did not ask for. A correct reader skips it.
            sock.sendall(frame(EXCHANGE_PUBLIC_PEERS, bytes(16)))
        if self.bad_size:
            sock.sendall(b"\x00\x00\x00" + bytes([RESPOND_CURRENT_TICK_INFO]) + bytes(4))
            return
        if msg_type == REQUEST_CURRENT_TICK_INFO:
            sock.sendall(frame(RESPOND_CURRENT_TICK_INFO,
                               struct.pack("<HHIHHI", 0, self.epoch, self.tick,
                                           0, 0, self.initial_tick)))
        elif msg_type == REQUEST_ENTITY:
            pub = self.lie_about or body[:32]
            incoming, outgoing = self.balances.get(pub, (0, 0))
            sock.sendall(frame(RESPOND_ENTITY, entity_body(pub, incoming, outgoing, self.tick)))
        elif msg_type == REQUEST_TICK_TRANSACTIONS:
            tick = struct.unpack("<I", body[:4])[0]
            for payload in self.tick_txs.get(tick, []):
                sock.sendall(frame(BROADCAST_TRANSACTION, payload))
            sock.sendall(frame(END_RESPOND))
        elif msg_type == REQUEST_CONTRACT_FUNCTION:
            index, fn, size = struct.unpack("<IHH", body[:8])
            self.contract_calls.append((index, fn, body[8:8 + size]))
            sock.sendall(frame(RESPOND_CONTRACT_FUNCTION, self.contract_outputs.get((index, fn), b"")))
        elif msg_type == REQUEST_OWNED_ASSETS:
            owner = body[:32]
            for issuer, name, shares in self.owned.get(owner, []):
                sock.sendall(frame(RESPOND_OWNED_ASSETS, owned_asset_body(owner, issuer, name, shares, self.tick)))
            sock.sendall(frame(END_RESPOND))
        elif msg_type == REQUEST_ASSETS:
            kind, _flags, _oc, _pc = struct.unpack("<HHHH", body[:8])
            issuer, name = body[8:40], body[40:48]
            if kind == ASSET_REQ_OWNERSHIPS:
                for i, (owner, shares) in enumerate(self.holders.get((issuer, name), [])):
                    sock.sendall(frame(RESPOND_ASSETS, ownership_record(owner, shares, index=i)
                                       + struct.pack("<II", self.tick, i)))
            elif kind == ASSET_REQ_POSSESSIONS:
                table = self.holders if self.possessors is None else self.possessors
                for i, (possessor, shares) in enumerate(table.get((issuer, name), [])):
                    sock.sendall(frame(RESPOND_ASSETS, possession_record(possessor, shares, index=i)
                                       + struct.pack("<II", self.tick, i)))
            sock.sendall(frame(END_RESPOND))


def free_port() -> int:
    """A port free on every loopback address we are about to bind."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def cluster(n: int, **kw):
    """`n` fake nodes on ONE port, at 127.0.0.1, 127.0.0.2, ...

    NativeChain speaks to every node on the same port, exactly as the
    qubic-cli chain does. 127.0.0.0/8 is all loopback on Linux, so a cluster
    that differs only by address is the honest shape to test fan-out against.
    """
    port = free_port()
    return [FakeNode(host=f"127.0.0.{i + 1}", port=port, **kw) for i in range(n)]
