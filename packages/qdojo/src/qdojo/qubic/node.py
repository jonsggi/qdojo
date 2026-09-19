"""The Qubic node protocol over TCP: the only I/O in this package.

A node speaks framed packets:

    3 bytes  size, little-endian, INCLUDING this 8-byte header
    1 byte   message type
    4 bytes  dejavu -- a gossip de-duplication id, 0 on anything we originate

Two things about reading that are easy to get wrong and expensive to debug.
A node sends unsolicited packets: EXCHANGE_PUBLIC_PEERS arrives immediately
on connect, and a node short of a computor list will ask for one. So a reader
must SKIP any packet whose type it did not ask for rather than treat the
first thing it receives as the answer. And a multi-packet response ends with
an END_RESPOND packet, not with a count -- reading until the socket goes
quiet instead would spend the whole timeout on every call.

Nothing here interprets money. `balance` returns what the node said; whether
that is trustworthy is the caller's problem, and `chain/native.py` treats a
single node's answer as exactly one opinion.
"""
import secrets
import socket
import struct

HEADER_SIZE = 8
DEFAULT_PORT = 21841
MAX_PACKET = 2 << 20            # a sane ceiling; the size field is 24 bits

EXCHANGE_PUBLIC_PEERS = 0
BROADCAST_TRANSACTION = 24
REQUEST_CURRENT_TICK_INFO = 27
RESPOND_CURRENT_TICK_INFO = 28
REQUEST_TICK_TRANSACTIONS = 29
REQUEST_ENTITY = 31
RESPOND_ENTITY = 32
END_RESPOND = 35
REQUEST_OWNED_ASSETS = 38
RESPOND_OWNED_ASSETS = 39
REQUEST_CONTRACT_FUNCTION = 42
RESPOND_CONTRACT_FUNCTION = 43
REQUEST_ASSETS = 52
RESPOND_ASSETS = 53

NUMBER_OF_TRANSACTIONS_PER_TICK = 4096
MAX_ASSET_RECORDS = 1 << 16     # a bound on a multi-packet asset answer, not a protocol limit
NUMBER_OF_EXCHANGED_PEERS = 4
SPECTRUM_DEPTH = 24


class NodeError(Exception):
    """The node could not be reached, or did not answer usably."""


def header(size: int, msg_type: int, dejavu: int = 0) -> bytes:
    return bytes([size & 0xFF, (size >> 8) & 0xFF, (size >> 16) & 0xFF, msg_type]) \
        + struct.pack("<I", dejavu)


def packet(msg_type: int, body: bytes = b"", dejavu: int | None = None) -> bytes:
    """Frame a message. `dejavu=None` randomises it, which is what a REQUEST
    wants: a repeated id can be dropped as a duplicate by the node."""
    if dejavu is None:
        dejavu = secrets.randbelow(0xFFFFFFFF) + 1
    return header(HEADER_SIZE + len(body), msg_type, dejavu) + body


class Node:
    """One TCP conversation with one node. Use as a context manager."""

    def __init__(self, ip: str, port: int = DEFAULT_PORT, timeout: float = 10.0):
        self.ip, self.port, self.timeout = ip, int(port), float(timeout)
        self._sock: socket.socket | None = None

    def __enter__(self) -> "Node":
        try:
            self._sock = socket.create_connection((self.ip, self.port), timeout=self.timeout)
        except OSError as e:
            raise NodeError(f"cannot reach {self.ip}:{self.port}: {e}") from e
        self._sock.settimeout(self.timeout)
        return self

    def __exit__(self, *exc) -> bool:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        return False

    # ------------------------------------------------------------------ io
    def _send(self, data: bytes) -> None:
        if self._sock is None:
            raise NodeError("Node must be used as a context manager")
        try:
            self._sock.sendall(data)
        except OSError as e:
            raise NodeError(f"send to {self.ip} failed: {e}") from e

    def _recv_exactly(self, n: int) -> bytes:
        if self._sock is None:
            raise NodeError("Node must be used as a context manager")
        buf = bytearray()
        while len(buf) < n:
            try:
                chunk = self._sock.recv(n - len(buf))
            except OSError as e:
                raise NodeError(f"read from {self.ip} failed: {e}") from e
            if not chunk:
                raise NodeError(f"{self.ip} closed the connection after "
                                f"{len(buf)} of {n} bytes")
            buf += chunk
        return bytes(buf)

    def _next_packet(self) -> tuple[int, bytes]:
        """(type, body) of the next packet, whatever it is."""
        head = self._recv_exactly(HEADER_SIZE)
        size = int.from_bytes(head[0:3], "little")
        msg_type = head[3]
        if size < HEADER_SIZE or size > MAX_PACKET:
            raise NodeError(f"{self.ip} sent a {size}-byte packet of type {msg_type}")
        return msg_type, self._recv_exactly(size - HEADER_SIZE)

    def _await(self, wanted: int, max_skip: int = 32) -> bytes:
        """The body of the next packet of type `wanted`, skipping others.

        `max_skip` bounds the skipping: a node that only ever sends us its
        peer list would otherwise keep us here until the socket timeout on
        every single call.
        """
        for _ in range(max_skip):
            msg_type, body = self._next_packet()
            if msg_type == wanted:
                return body
            if msg_type == END_RESPOND:
                raise NodeError(f"{self.ip} ended the response without sending "
                                f"a type-{wanted} packet")
        raise NodeError(f"{self.ip} sent {max_skip} packets, none of type {wanted}")

    # ----------------------------------------------------------- messages
    def public_peers(self, max_skip: int = 4) -> list[str]:
        """The peers the node volunteers on connect.

        A node sends EXCHANGE_PUBLIC_PEERS unprompted as soon as the socket
        opens -- four IPv4 addresses, the same list `qubic-cli -getnodeiplist`
        asks for. Reading what already arrived costs nothing, so discovery
        needs no extra request and no binary.

        Call it before anything else on a fresh connection: once another
        request has been made, the peers packet may already have been skipped
        past. An empty list is a normal answer, not an error.
        """
        for _ in range(max_skip):
            try:
                msg_type, body = self._next_packet()
            except NodeError:
                return []
            if msg_type == EXCHANGE_PUBLIC_PEERS:
                return [".".join(str(b) for b in body[i:i + 4])
                        for i in range(0, min(len(body), 4 * NUMBER_OF_EXCHANGED_PEERS), 4)
                        if body[i:i + 4] != b"\0\0\0\0"]
        return []

    def tick_info(self) -> dict:
        """{tick, epoch, initial_tick, aligned_votes, misaligned_votes}."""
        self._send(packet(REQUEST_CURRENT_TICK_INFO))
        body = self._await(RESPOND_CURRENT_TICK_INFO)
        if len(body) < 16:
            raise NodeError(f"{self.ip} sent a {len(body)}-byte tick info")
        duration, epoch, tick, aligned, misaligned, initial = struct.unpack("<HHIHHI", body[:16])
        if not tick or not initial or initial > tick:
            raise NodeError(f"{self.ip} sent an incoherent tick info "
                            f"(tick={tick}, initial={initial})")
        return {"tick": tick, "epoch": epoch, "initial_tick": initial,
                "tick_duration": duration, "aligned_votes": aligned,
                "misaligned_votes": misaligned}

    def entity(self, public_key: bytes) -> dict:
        """The spectrum record for one identity: balance and transfer counts.

        Balance is incoming - outgoing, which is how Qubic stores it; there is
        no balance field to read directly.
        """
        if len(public_key) != 32:
            raise ValueError("public key must be 32 bytes")
        self._send(packet(REQUEST_ENTITY, public_key))
        body = self._await(RESPOND_ENTITY)
        if len(body) < 68:
            raise NodeError(f"{self.ip} sent a {len(body)}-byte entity record")
        (pub, incoming, outgoing, n_in, n_out,
         latest_in, latest_out, tick) = struct.unpack("<32sqqIIIII", body[:68])
        if pub != public_key:
            raise NodeError(f"{self.ip} answered about a different identity")
        return {"balance": incoming - outgoing, "incoming": incoming,
                "outgoing": outgoing, "n_incoming": n_in, "n_outgoing": n_out,
                "latest_incoming_tick": latest_in, "latest_outgoing_tick": latest_out,
                "tick": tick}

    def broadcast(self, signed_payload: bytes) -> None:
        """Write a signed transaction. Dejavu is 0, as the reference does.

        There is no reply to this message in the protocol, so returning
        without an exception means the bytes were written -- never that the
        transaction will be included. Only a later tick read proves that.
        """
        self._send(packet(BROADCAST_TRANSACTION, signed_payload, dejavu=0))

    def tick_transactions(self, tick: int, limit: int = NUMBER_OF_TRANSACTIONS_PER_TICK) -> list[bytes]:
        """Every transaction the node has for `tick`, as raw signed payloads.

        The flag array is a request mask and its sense is inverted: a ZERO bit
        asks for that slot. All-zero therefore asks for everything, and the
        node answers with a stream of BROADCAST_TRANSACTION packets closed by
        END_RESPOND.
        """
        flags = bytearray(NUMBER_OF_TRANSACTIONS_PER_TICK // 8)
        for i in range((limit + 7) // 8, len(flags)):
            flags[i] = 0xFF
        self._send(packet(REQUEST_TICK_TRANSACTIONS, struct.pack("<I", tick) + bytes(flags)))

        out: list[bytes] = []
        while len(out) < limit:
            msg_type, body = self._next_packet()
            if msg_type == END_RESPOND:
                break
            if msg_type == BROADCAST_TRANSACTION:
                out.append(body)
        return out

    # ---------------------------------------------------- contracts, assets
    def contract_function(self, contract_index: int, function: int, data: bytes = b"") -> bytes:
        """Call a contract's read-only function and return its raw output.

        The node answers a function it could not run -- none registered under
        that number, or one that timed out -- with an EMPTY body, not an
        error. qubic-cli zero-fills its output struct and reads a fee of 0
        out of that. Here it is an exception: an unknown is never a zero.
        """
        from .contracts import contract_function_request
        self._send(packet(REQUEST_CONTRACT_FUNCTION,
                          contract_function_request(contract_index, function, data)))
        body = self._await(RESPOND_CONTRACT_FUNCTION)
        if not body:
            raise NodeError(f"{self.ip} could not run contract {contract_index} "
                            f"function {function} (empty answer)")
        return body

    def _collect(self, wanted: int, limit: int = MAX_ASSET_RECORDS) -> list[bytes]:
        """Every packet of type `wanted` until END_RESPOND, skipping others."""
        out: list[bytes] = []
        while len(out) < limit:
            msg_type, body = self._next_packet()
            if msg_type == END_RESPOND:
                break
            if msg_type == wanted:
                out.append(body)
        return out

    def owned_assets(self, public_key: bytes) -> list[dict]:
        """Every asset ownership record of one identity, with the issuance
        each is of: [{issuer, name, shares, managing_contract, tick, ...}].
        Multi-packet, closed by END_RESPOND; nothing owned is an empty list."""
        from .contracts import decode_owned_asset
        if len(public_key) != 32:
            raise ValueError("public key must be 32 bytes")
        self._send(packet(REQUEST_OWNED_ASSETS, public_key))
        try:
            return [decode_owned_asset(b) for b in self._collect(RESPOND_OWNED_ASSETS)]
        except ValueError as e:
            raise NodeError(f"{self.ip} sent a malformed asset record: {e}") from e

    def asset_records(self, request: bytes) -> list[dict]:
        """Asset records matching a RequestAssets filter (contracts.py builds
        them): issuance, ownership or possession records as decoded dicts."""
        from .contracts import decode_asset_response
        self._send(packet(REQUEST_ASSETS, request))
        try:
            return [decode_asset_response(b) for b in self._collect(RESPOND_ASSETS)]
        except ValueError as e:
            raise NodeError(f"{self.ip} sent a malformed asset record: {e}") from e
