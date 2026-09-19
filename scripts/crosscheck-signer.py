#!/usr/bin/env python3
"""Prove the native signer against qubic-cli, byte for byte.

qdojo signs its own transactions now. This is what earns that the right to
move money: random seeds are derived and real transactions are signed both
ways -- here, and by the reference C++ implementation -- and every one of the
144 bytes must match.

It works at all because SchnorrQ signing in Qubic is DETERMINISTIC: the nonce
is K12(expanded subseed ‖ digest), with no randomness anywhere. So the test is
not "both signatures verify" (two different signatures would both verify and
both be correct); it is "the bytes are identical". A one-bit error anywhere in
the field arithmetic shows up immediately.

NOTHING IS BROADCAST. `-print-only hex` makes qubic-cli print the packet and
skip the send. A node still has to be reachable, because qubic-cli opens the
socket before it builds the transaction -- but no packet crosses it, and every
amount is sent to a throwaway identity nobody holds the seed for anyway.

    scripts/crosscheck-signer.py --node 1.2.3.4 [--cli ./qubic-cli] [--seeds 20]

Requires a qubic-cli binary: scripts/build-qubic-cli.sh, or --cli PATH. The
binary is needed ONLY for this check -- qdojo itself no longer uses it.
"""
import argparse
import os
import random
import re
import string
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "packages", "qdojo", "src"))

from qdojo.qubic import ids                      # noqa: E402
from qdojo.qubic.tx import Transaction           # noqa: E402

RED, GRN, YEL, DIM, RST = "\033[31m", "\033[32m", "\033[33m", "\033[2m", "\033[0m"
HEX_RE = re.compile(r"-+ hex -+\s*\n([0-9a-f]+)", re.I)

# Deliberately awkward: zero, one, either side of 2^32, and ticks around the
# 32-bit boundary -- every shape a naive port gets wrong.
#
# tick=None means "let the node choose the tick". Amounts at or above 2^32
# cannot be expressed through -sendtoaddressintick, which casts the parsed
# amount to uint32_t and silently truncates it; -sendtoaddress keeps the full
# int64, so the large vectors go through that and the tick is read back out of
# the reference's own output.
VECTORS = [(0, 1), (1, 80000000), (12345, 4294967295), (1000000000, 2),
           (4294967295, 2147483648), (8000000000, None), (999999999999999, None)]

# Payload transactions. EVERY dojo message is one of these -- BOW, COMMIT,
# REVEAL and SETTLE all ride in `input` under type 0x444F -- so a conformance
# run over bare transfers alone would leave the format the game actually uses
# completely unchecked. Sizes are chosen at the boundaries: empty, one byte,
# an odd length, and MAX_INPUT_SIZE exactly.
PAYLOAD_VECTORS = [(0x444F, 0), (0x444F, 1), (0x444F, 37), (0x444F, 512),
                   (0x444F, 1023), (0x444F, 1024), (0, 64), (65535, 100)]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--node", default=os.environ.get("QDOJO_NODE"),
                   help="node IP qubic-cli connects to (nothing is sent)")
    p.add_argument("--port", type=int, default=21841)
    p.add_argument("--cli", default=os.environ.get("QUBIC_CLI", "qubic-cli"))
    p.add_argument("--seeds", type=int, default=20, help="random seeds to test")
    p.add_argument("--rng-seed", type=int, default=0, help="make the run reproducible")
    return p.parse_args()


def main():
    a = parse_args()
    if not a.node:
        sys.exit("a node is required (nothing is broadcast): --node IP")
    ip = a.node.partition(":")[0]

    rng = random.Random(a.rng_seed)
    seeds = ["".join(rng.choice(string.ascii_lowercase) for _ in range(55))
             for _ in range(a.seeds)]
    # A destination nobody holds: derived from a seed generated here and
    # discarded. Distinct from every source, so a swapped-field bug cannot hide.
    dest = ids.identity_from_seed("".join(rng.choice(string.ascii_lowercase) for _ in range(55)))

    fd, conf = tempfile.mkstemp(suffix=".conf")
    os.close(fd)
    os.chmod(conf, 0o600)

    def write_conf(seed):
        with open(os.open(conf, os.O_WRONLY | os.O_TRUNC, 0o600), "w") as f:
            f.write(f"seed={seed}\n")

    def cli_showkeys(seed):
        write_conf(seed)
        out = subprocess.run([a.cli, "-conf", conf, "-showkeys"],
                             capture_output=True, text=True, timeout=30).stdout
        for line in out.splitlines():
            if line.startswith("Identity: "):
                return line[10:].strip()
        return None

    def cli_sign_custom(seed, amount, input_type, payload):
        """The reference's payload transaction. -sendcustomtransaction takes
        the tick from the node, so it is read back out of the output."""
        write_conf(seed)
        argv = [a.cli, "-conf", conf, "-nodeip", ip, "-nodeport", str(a.port),
                "-print-only", "hex", "-scheduletick", "20",
                "-sendcustomtransaction", dest, str(input_type), str(amount),
                str(len(payload)), payload.hex() or "00"]
        assert "-print-only" in argv, "refusing to run qubic-cli without -print-only"
        p = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        m = HEX_RE.search(p.stdout or "")
        if not m:
            return None
        raw = bytes.fromhex(m.group(1).strip())
        return (raw, int.from_bytes(raw[64:72], "little"),
                int.from_bytes(raw[72:76], "little"),
                int.from_bytes(raw[78:80], "little"))

    def cli_sign(seed, amount, tick):
        """(hex, amount_used, tick_used) from the reference, or None."""
        write_conf(seed)
        argv = [a.cli, "-conf", conf, "-nodeip", ip, "-nodeport", str(a.port),
                "-print-only", "hex"]
        if tick is None:
            argv += ["-scheduletick", "20", "-sendtoaddress", dest, str(amount)]
        else:
            argv += ["-sendtoaddressintick", dest, str(amount), str(tick)]
        assert "-print-only" in argv, "refusing to run qubic-cli without -print-only"
        p = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        m = HEX_RE.search(p.stdout or "")
        if not m:
            return None
        raw = bytes.fromhex(m.group(1).strip())
        return (raw, int.from_bytes(raw[64:72], "little"),
                int.from_bytes(raw[72:76], "little"))

    print(f"{YEL}== native signer vs qubic-cli =={RST}")
    print(f"   {len(seeds)} seeds x {len(VECTORS)} transactions via {ip} "
          f"{DIM}(print-only, nothing is broadcast){RST}\n")

    derive_bad, sign_bad, unexpressible, ok_d, ok_s = [], [], [], 0, 0
    for seed in seeds:
        ref_id = cli_showkeys(seed)
        got_id = ids.identity_from_seed(seed)
        if ref_id != got_id:
            derive_bad.append((ref_id, got_id))
        else:
            ok_d += 1

        subseed, _priv, public = ids.keys_from_seed(seed)
        for amount, tick in VECTORS:
            out = cli_sign(seed, amount, tick)
            if out is None:
                sign_bad.append((got_id, amount, tick, None, None))
                continue
            ref, ref_amount, ref_tick = out
            if ref_amount != amount:
                # The reference's own argument parsing, not a signing
                # difference. Saying so plainly stops the next reader hunting
                # for a bug in the field arithmetic that is not there.
                unexpressible.append((amount, ref_amount))
                continue
            got = Transaction.to_identity(public, dest, amount, ref_tick).sign(subseed).payload()
            if got != ref:
                sign_bad.append((got_id, amount, ref_tick, ref.hex(), got.hex()))
            else:
                ok_s += 1
        for input_type, size in PAYLOAD_VECTORS:
            body = bytes((i * 7 + size) & 0xFF for i in range(size))
            out = cli_sign_custom(seed, 3, input_type, body)
            if out is None:
                sign_bad.append((got_id, f"payload/{size}", None, None, None))
                continue
            ref, _ref_amount, ref_tick, ref_size = out
            if ref_size != size:
                unexpressible.append((size, ref_size))
                continue
            got = Transaction.to_identity(public, dest, 3, ref_tick,
                                          input_type=input_type, payload=body).sign(subseed).payload()
            if got != ref:
                sign_bad.append((got_id, f"payload/{size}", ref_tick, ref.hex(), got.hex()))
            else:
                ok_s += 1
        print(f"   {got_id[:12]}…  {GRN if not (derive_bad or sign_bad) else YEL}"
              f"{ok_d} derived, {ok_s} signed{RST}")

    os.unlink(conf)

    print(f"\n   {GRN if not derive_bad else RED}derivations: {ok_d}/{len(seeds)}{RST}")
    print(f"   {GRN if not sign_bad else RED}signatures:  {ok_s} byte-identical{RST}")
    for ref_id, got_id in derive_bad[:3]:
        print(f"     {RED}reference {ref_id} vs native {got_id}{RST}")
    for ident, amount, tick, ref, got in sign_bad[:3]:
        print(f"     {RED}{ident[:12]}… amount={amount} tick={tick}{RST}")
        if ref is None:
            print(f"       {RED}the reference printed no hex{RST}")
            continue
        for off in range(0, max(len(ref), len(got)), 64):
            if ref[off:off + 64] != got[off:off + 64]:
                print(f"       byte {off // 2}: ref {ref[off:off + 64]}")
                print(f"                 py  {got[off:off + 64]}")
    if unexpressible:
        print(f"   {YEL}{len(unexpressible)} vector(s) the reference could not express{RST} "
              f"{DIM}(its argument parsing truncates, not a signing difference){RST}")
        for asked, built in unexpressible[:2]:
            print(f"     {YEL}asked {asked:,}, qubic-cli built {built:,}{RST}")

    if derive_bad or sign_bad:
        print(f"\n{RED}CONFORMANCE FAILED. The native signer is NOT safe to use.{RST}")
        return 1
    print(f"\n{GRN}CONFORMANCE GREEN: {ok_d} derivations and {ok_s} signatures "
          f"agree with qubic-cli, byte for byte.{RST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
