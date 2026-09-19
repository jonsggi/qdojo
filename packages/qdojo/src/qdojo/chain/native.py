"""The chain, spoken directly. No qubic-cli, no seed conf handed to anyone.

This is the same `Chain` interface `QubicCli` implements, with the binary
taken out of the middle. Transactions are built, signed and written to nodes
in this process; ticks and balances come from the node's own protocol.

Three differences from the qubic-cli path, each deliberate:

  the seed is a value, not a file. `QubicCli` needs a 0600 conf because a
  separate process has to read the key. Here it is passed in and kept in
  memory, and the identity it signs as is DERIVED and compared -- never
  taken on trust from a caller. A conf whose identity does not match what
  the bot thinks it is pays into nothing, silently, for as long as it runs.

  a send goes to several nodes. `QubicCli` deliberately signs against the
  primary only, so that a retry cannot become a second transaction. That
  guard is about signing twice, not about writing twice: the same signed
  bytes, same tick, same nonce, are one transaction however many nodes see
  them -- that is what gossip does with it anyway. A round is time-boxed, so
  a single node quietly dropping the packet costs the round.

  confirmation reads the tick's transactions. A transaction is valid for
  exactly the one tick signed into it, so once that tick is safely past and
  its data is available, "not in the tick" means "never landed and never
  can" -- a definite False rather than an endless maybe.
"""
from ..qubic import ids
from ..qubic.node import Node, NodeError
from ..qubic.tx import Transaction
from ..round import Observed
from .base import ChainError, SendResult, Unknown

DEFAULT_SCHEDULE_OFFSET = 20
DEAD_TICK_MARGIN = 50   # ticks past the scheduled tick before "absent" means "never landed"


def read_seed_conf(path: str) -> str:
    """The seed out of a 0600 conf, checked the way the conf path checks it.

    Kept so an existing bot's conf keeps working. Nothing here ever WRITES a
    conf, and a bot set up from now on need not have one at all.
    """
    from .cli import check_seed_conf
    check_seed_conf(path)
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("seed="):
                return line.strip()[5:]
    raise ChainError(f"conf {path}: no seed= line")   # check_seed_conf already ruled this out


class NativeChain:
    """Chain over the node protocol. Read-only unless a seed is given."""

    def __init__(self, node_ip: str, node_port: int = 21841, seed: str | None = None,
                 conf: str | None = None, identity: str = "",
                 schedule_offset: int = DEFAULT_SCHEDULE_OFFSET, timeout: float = 10.0,
                 indexer=None, fallback_nodes=()):
        self.node_ip, self.node_port = node_ip, int(node_port)
        self.schedule_offset, self.timeout = int(schedule_offset), float(timeout)
        self.indexer = indexer
        self.fallback_nodes = tuple(fallback_nodes)

        if seed and conf:
            raise ChainError("give a seed or a conf, not both")
        if conf:
            seed = read_seed_conf(conf)

        self._subseed: bytes | None = None
        self._public_key: bytes | None = None
        if seed:
            try:
                subseed, _private, public = ids.keys_from_seed(seed)
            except ValueError as e:
                raise ChainError(f"bad seed: {e}") from e
            derived = ids.identity_from_public_key(public)
            if derived == ids.PUBLIC_DEFAULT_IDENTITY:
                raise ChainError("that seed derives the public default identity, "
                                 "which anyone can spend from -- refusing to sign")
            if identity and identity != derived:
                raise ChainError(f"the seed signs as {derived}, not {identity} -- "
                                 "refusing to sign as an identity it does not own")
            self._subseed, self._public_key, self.identity = subseed, public, derived
        else:
            self.identity = identity   # read-only instance

    # ------------------------------------------------------------- plumbing
    @property
    def nodes(self) -> tuple[str, ...]:
        return (self.node_ip,) + self.fallback_nodes

    def _read(self, call, what: str):
        """Run `call(node)` against each node until one answers usably.

        A node that answers badly is as useless as one that does not answer,
        so both move us on -- and running out of nodes is Unknown, never a
        zero.
        """
        for ip in self.nodes:
            try:
                with Node(ip, self.node_port, self.timeout) as n:
                    return call(n)
            except (NodeError, ValueError):
                continue
        raise Unknown(f"no usable {what} from any of {len(self.nodes)} nodes")

    def _signing(self) -> tuple[bytes, bytes]:
        if self._subseed is None or self._public_key is None:
            raise ChainError("no seed: this chain is read-only")
        return self._subseed, self._public_key

    # ---------------------------------------------------------------- reads
    def current_tick(self) -> int:
        return self._read(lambda n: n.tick_info()["tick"], "tick")

    def tick_context(self) -> dict:
        """Tick, epoch and the epoch's initial tick, from one node."""
        return self._read(lambda n: n.tick_info(), "tick context")

    def balance(self, identity: str) -> int:
        if not ids.check_identity(identity):
            raise ChainError(f"{identity[:12]}… is not a valid identity (checksum)")
        pub = ids.public_key_from_identity(identity)
        return self._read(lambda n: n.entity(pub)["balance"], f"balance for {identity[:8]}…")

    def indexed_tick(self) -> int:
        if self.indexer is None:
            raise ChainError("no indexer configured")
        return self.indexer.indexed_tick()

    def transactions_to(self, identity: str, start_tick: int, end_tick: int) -> list[Observed]:
        if self.indexer is None:
            raise ChainError("no indexer configured for transaction discovery")
        return self.indexer.transactions_to(identity, start_tick, end_tick)

    # ---------------------------------------------------------------- sends
    def send(self, dest: str, amount: int, payload: bytes = b"", input_type: int = 0) -> SendResult:
        """Sign here, write to every node we know, return what was scheduled.

        Returning a SendResult means the bytes reached at least one node. It
        is never a claim that the transaction landed; `confirm` is.
        """
        subseed, public = self._signing()
        if not ids.check_identity(dest):
            raise ChainError(f"destination {dest[:12]}… fails its checksum")

        tick = self.current_tick() + self.schedule_offset
        tx = Transaction.to_identity(public, dest, amount, tick, input_type, payload)
        signed = tx.sign(subseed)
        if not signed.verify():
            raise ChainError("the signature does not verify against our own public "
                             "key -- not broadcasting")

        body = signed.payload()
        accepted, errors = [], []
        for ip in self.nodes:
            try:
                with Node(ip, self.node_port, self.timeout) as n:
                    n.broadcast(body)
                accepted.append(ip)
            except NodeError as e:
                errors.append(f"{ip}: {e}")
        if not accepted:
            raise ChainError("no node accepted the transaction; treat as NOT sent "
                             "until proven otherwise (" + "; ".join(errors) + ")")
        return SendResult(signed.tx_hash(), tick)

    def confirm(self, tx_id: str, tick: int) -> bool:
        """Did `tx_id` land in `tick`? Unknown while it is still undecidable."""
        from ..qubic.ids import tx_hash_from_digest
        from ..qubic.k12 import k12

        answered = False
        for ip in self.nodes:
            try:
                with Node(ip, self.node_port, self.timeout) as n:
                    bodies = n.tick_transactions(tick)
            except NodeError:
                continue
            answered = True
            for body in bodies:
                if tx_hash_from_digest(k12(body, 32)) == tx_id:
                    return True

        if not answered:
            raise Unknown(f"no node answered for tick {tick}")

        # Nobody has it. That is only a definite "no" once the tick is behind
        # us by a safe margin AND still inside this epoch -- before the
        # epoch's initial tick the data is simply gone, and there we stay
        # undecided rather than call a transaction dead on missing evidence.
        ctx = self.tick_context()
        if tick >= ctx["initial_tick"] and ctx["tick"] > tick + DEAD_TICK_MARGIN:
            return False
        raise Unknown(f"tick {tick} not answerable yet for {tx_id[:8]}…")
