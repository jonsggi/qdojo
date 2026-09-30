#!/usr/bin/env python3
"""Contract parity journals for the later rulesets (candidates 2 and 3).

Writes, under packages/qdojo/tests/combat/fixtures/contract/:

  fuzz-c3.journal    random traffic (scripts' test_contract_fuzz.traffic) on
                     candidate 3: plans drawn from its nine-action alphabet,
                     LAST_STAND and FEINT included, some with a power slot;
  fuzz-c2.journal    the same on candidate 2 (six actions, 120 HP, 48 stamina);
  season-c3.journal  NPC bots on the demo-c3 devnet profile (the live arena's
                     manifest shape: timing 9/8, two tiers, two fee profiles,
                     3 starts per pair per epoch, 60-tick rematch gap).

The candidate-1 journals (fuzz-1/2, season, scenarios, demo-profile) come from
scripts/combat-sample-data.py. Every journal ends with the reference's final
event digest; contracts/combat_contract (make contract-test) and
contracts/qubic (core_harness.py test) replay them. Deterministic.
"""
from __future__ import annotations

import datetime as dt
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/qdojo/src"))
sys.path.insert(0, str(ROOT / "packages/qdojo/tests"))

from qdojo.combat import evaluate as E  # noqa: E402
from qdojo.combat import store  # noqa: E402
from qdojo.combat.bot import Bot, Budget, policy_chooser  # noqa: E402
from qdojo.combat.contract import development_manifest  # noqa: E402
from qdojo.combat.devnet import Devnet  # noqa: E402
from qdojo.combat.rules import candidate_2, candidate_3  # noqa: E402
from qdojo.combat.sim import World  # noqa: E402
from qdojo.combat.types import submitted  # noqa: E402
from combat.test_contract import ADMIN, DEV, HOUSE, SHARE  # noqa: E402
from combat.test_contract_fuzz import traffic  # noqa: E402

OUT = ROOT / "packages/qdojo/tests/combat/fixtures/contract"
NOON = dt.datetime(2026, 9, 23, 12, tzinfo=dt.timezone.utc)
LINEUP = {"tanuki": "reader-v1", "kappa": "mixed-v1", "oni": "script-vs-scout-v1", "kitsune": "scout-v1",
          "raiju": "kicker-v1", "kirin": "jabber-v1"}


class FixedSalt:
    """Derived, labelled salts so the journal is reproducible (never for live bots)."""

    def __init__(self, label):
        self.label, self.n = label, 0

    def __call__(self, k):
        from qdojo.hashing import sha256
        self.n += 1
        return sha256(b"qdojo/journal-salt/v1\0", self.label.encode(), self.n.to_bytes(8, "little"))[:k]


def fuzz(rules, ticks, seed, out):
    w = World(development_manifest(rules, ADMIN, HOUSE, DEV, SHARE))
    w.mint(ADMIN, 10**9)
    traffic(w, ticks, seed=seed, check=True, actions=submitted(rules), power=True)
    w.check_conservation()
    store.write(out, w.manifest, w.journal, w.contract.event_digest)
    return w


def season(ticks, out):
    tmp = Path(tempfile.mkdtemp(prefix="qdojo-journal-"))
    try:
        net = Devnet(tmp / "net", profile="demo-c3")
        rules = net.m.ruleset
        bots = []
        for label, policy in LINEUP.items():
            fid, owner = net.ensure_fighter(label)
            b = Bot(net.client(owner), rules, fid, owner, owner,
                    policy_chooser(rules, E.policy_by_name(policy, rules), bytes(32)),
                    Budget(ruleset_digest=rules.digest.hex(), max_stake=5000, max_total_escrow=10**12,
                           max_fights_per_day=10**6, max_daily_committed=10**12, max_daily_net_loss=10**12,
                           stop_after_faults=10**6),
                    tmp / "bots" / label, clock=lambda: NOON)
            b.salt_source = FixedSalt(label)
            bots.append(b)
        for _ in range(ticks):
            for b in bots:
                b.step()
            net.world.end()
        net.world.check_conservation()
        store.write(out, net.m, net.world.journal, net.world.contract.event_digest)
        return net.world
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def summary(name, w):
    """Journal size, and how often each action appears in the revealed plans."""
    from qdojo.combat import codec
    c, moves = w.contract, {}
    for rec in w.journal:
        if rec["k"] != "call":
            continue
        try:
            req = codec.decode_frame(bytes.fromhex(rec["frame"]))
        except codec.CodecError:
            continue
        if req.op is codec.Op.REVEAL:
            for a in req.fields["plan"].actions:
                moves[a.name] = moves.get(a.name, 0) + 1
    kinds = sorted({x.result["kind"] for x in c.contests.values() if x.result})
    print(f"{name}: {len(w.journal)} records, {c.event_seq} events, {len(c.fights)} fights, contests {kinds}")
    print(f"    revealed actions {dict(sorted(moves.items()))}")
    print(f"    event digest {c.event_digest.hex()}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary("fuzz-c3", fuzz(candidate_3(), 2000, 3, OUT / "fuzz-c3.journal"))
    summary("fuzz-c2", fuzz(candidate_2(), 1000, 4, OUT / "fuzz-c2.journal"))
    summary("season-c3", season(1500, OUT / "season-c3.journal"))


if __name__ == "__main__":
    main()
