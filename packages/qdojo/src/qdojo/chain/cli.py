"""qubic-cli wrapper. Every call has a timeout and a marker; nothing trusts
the exit code. The seed lives in a 0600 conf passed with -conf and is never
on argv.
"""
import os
import stat
import subprocess

from ..round import Observed
from . import parse
from .base import SendResult, Unknown, ChainError

DEFAULT_SCHEDULE_OFFSET = 20


class SeedConfError(ChainError):
    pass


def check_seed_conf(path: str) -> None:
    """A conf must exist, be mode 0600, and carry exactly one seed= line of 55
    lowercase letters. Without it qubic-cli silently signs as a public identity."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        raise SeedConfError(f"conf not found: {path}")
    if stat.S_IMODE(st.st_mode) & 0o077:
        raise SeedConfError(f"conf {path} must be mode 0600")
    seeds = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("seed="):
                seeds.append(line.strip()[5:])
    if len(seeds) != 1:
        raise SeedConfError(f"conf {path} must have exactly one seed= line")
    s = seeds[0]
    if len(s) != 55 or not s.islower() or not s.isalpha():
        raise SeedConfError(f"conf {path}: seed is not 55 lowercase letters")


class QubicCli:
    def __init__(self, binary: str, node_ip: str, node_port: int = 21841, identity: str = "",
                 conf: str | None = None, schedule_offset: int = DEFAULT_SCHEDULE_OFFSET, timeout: int = 30,
                 indexer=None):
        self.binary, self.node_ip, self.node_port = binary, node_ip, int(node_port)
        self.identity, self.conf, self.schedule_offset, self.timeout = identity, conf, schedule_offset, timeout
        self.indexer = indexer  # something with transactions_to(); the CLI has no history query
        if conf:
            check_seed_conf(conf)

    def _run(self, args: list[str], signed: bool = False) -> str:
        argv = [self.binary, "-nodeip", self.node_ip, "-nodeport", str(self.node_port)]
        if signed:
            if not self.conf:
                raise ChainError("no seed conf: this chain is read-only")
            argv += ["-conf", self.conf, "-scheduletick", str(self.schedule_offset)]
        argv += args
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=self.timeout, check=False)
        except subprocess.TimeoutExpired:
            raise Unknown(f"qubic-cli timed out after {self.timeout}s: {' '.join(args[:1])}")
        except FileNotFoundError:
            raise ChainError(f"qubic-cli not found at {self.binary}")
        out = p.stdout + ("\n" + p.stderr if p.stderr else "")
        if parse.connection_failed(out):
            raise Unknown(f"qubic-cli could not reach {self.node_ip}:{self.node_port}")
        return out

    def current_tick(self) -> int:
        t = parse.current_tick(self._run(["-getcurrenttick"]))
        if t is None:
            raise Unknown("no Tick/Epoch in -getcurrenttick output")
        return t

    def balance(self, identity: str) -> int:
        b = parse.balance(self._run(["-getbalance", identity]), identity)
        if b is None:
            raise Unknown(f"no usable balance for {identity[:8]}…")
        return b

    def send(self, dest: str, amount: int, payload: bytes = b"", input_type: int = 0) -> SendResult:
        if payload:
            args = ["-sendcustomtransaction", dest, str(input_type), str(amount), str(len(payload)), payload.hex()]
        else:
            args = ["-sendtoaddress", dest, str(amount)]
        r = parse.send_receipt(self._run(args, signed=True))
        if r is None:
            raise ChainError("send produced no receipt; treat as NOT sent until proven otherwise")
        return SendResult(*r)

    def confirm(self, tx_id: str, tick: int) -> bool:
        r = parse.check_tx_on_tick(self._run(["-checktxontick", str(tick), tx_id]), tx_id, tick)
        if r is None:
            raise Unknown(f"tick {tick} not answerable yet for {tx_id[:8]}…")
        return r

    def indexed_tick(self) -> int:
        if self.indexer is None:
            raise ChainError("no indexer configured")
        return self.indexer.indexed_tick()

    def transactions_to(self, identity: str, start_tick: int, end_tick: int) -> list[Observed]:
        if self.indexer is None:
            raise ChainError("no indexer configured for transaction discovery")
        return self.indexer.transactions_to(identity, start_tick, end_tick)
