#!/usr/bin/env python3
"""Parity journal for a non-default manifest: the devnet "demo" profile.

Writes packages/qdojo/tests/combat/fixtures/contract/demo-profile.journal.
Four fighters queue ranked over and over against the demo profile's matchmaking
values (devnet.LEGACY_PROFILES["demo"], the ones this fixture was made with:
pair_starts_per_epoch 6, pair_rematch_ticks 60, ticks_per_epoch 2400,
season_closeout_ticks 300), so the same pairs meet again and again: rematches
inside 60..120 ticks and more than two starts per pair and epoch happen, which
the default 2/120 would refuse. Occasional missed commits and reveals add
forfeits, faults and suspensions. The chain starts at tick 1500 so the run
crosses the epoch boundary at 2400, where pair-start and fault counts reset.

Deterministic (seeded plans and salts): regeneration is byte-identical. The
script checks that replaying the journal under the default 2/120 gives a
different event digest, so a port that ignores the header values fails.
"""
from __future__ import annotations

import dataclasses
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/qdojo/src"))
sys.path.insert(0, str(ROOT / "packages/qdojo/tests"))

from qdojo.combat import store  # noqa: E402
from qdojo.combat.codec import Op  # noqa: E402
from qdojo.combat.contract import development_manifest  # noqa: E402
from qdojo.combat.devnet import LEGACY_PROFILES  # noqa: E402
from qdojo.combat.rules import candidate_1  # noqa: E402
from qdojo.combat.sim import World, commit_fields, reveal_fields  # noqa: E402
from qdojo.combat.types import SUBMITTED, Plan  # noqa: E402
from combat.test_contract import ADMIN, DEV, HOUSE, SHARE, Player  # noqa: E402

OUT = ROOT / "packages/qdojo/tests/combat/fixtures/contract/demo-profile.journal"
SEED = 6060
START, TICKS = 1500, 1300


def build():
    rng = random.Random(SEED)
    m = development_manifest(candidate_1(), ADMIN, HOUSE, DEV, SHARE, **LEGACY_PROFILES["demo"])
    assert (m.pair_starts_per_epoch, m.pair_rematch_ticks) != (2, 120), "the point is a non-default profile"
    w = World(m, tick=START)
    w.mint(ADMIN, 10**9)
    c = w.contract
    players = [Player(w, f"demo{i}") for i in range(4)]
    pending = {}
    for _ in range(TICKS):
        t = w.tick
        for p in players:
            if p.f.lock == "IDLE" and rng.random() < 0.5:
                p.enter(expires_in=rng.choice([40, 120]), max_gap=200)
        for fight in list(c.fights.values()):
            for side in (fight.context.participant_a, fight.context.participant_b):
                slot = fight.slot_of(side.fighter_id)
                key = (fight.fight_id, fight.state.round_index, slot)
                if fight.phase == "COMMIT" and fight.start_tick < t <= fight.commit_last:
                    if slot in fight.commits or key in pending or rng.random() < 0.4:
                        continue
                    if rng.random() < 0.03:
                        pending[key] = None               # this side never commits this round
                        continue
                    plan = Plan.of([rng.choice(SUBMITTED) for _ in range(6)])
                    salt = bytes(rng.getrandbits(8) for _ in range(32))
                    fields, salt = commit_fields(w, fight.fight_id, side.fighter_id, side.operator, plan, salt=salt)
                    w.send(side.operator, Op.COMMIT, **fields)
                    pending[key] = (plan, salt, side)
                elif fight.phase == "REVEAL" and pending.get(key) and slot not in fight.reveals:
                    if rng.random() < 0.4:
                        continue
                    plan, salt, s = pending[key]
                    w.send(s.operator, Op.REVEAL, **reveal_fields(w, fight.fight_id, s.fighter_id, plan, salt))
        w.end()
    w.check_conservation()
    return m, w


def main(out: Path = OUT):
    m, w = build()
    c = w.contract
    out.parent.mkdir(parents=True, exist_ok=True)
    store.write(out, m, w.journal, c.event_digest)
    top = max(c.pair_starts.values(), default=0)
    head, records = store.load(out)
    default = dataclasses.replace(m, pair_starts_per_epoch=2, pair_rematch_ticks=120)
    head_default = dict(head, pair_starts_per_epoch=2, pair_rematch_ticks=120)
    try:
        store.replay(default, head_default, records)
        differs = False
    except store.StoreError:
        differs = True
    size = out.stat().st_size
    print(f"demo-profile: {len(w.journal)} records, {c.event_seq} events, {size} bytes; "
          f"epochs {m.epoch(START)}..{m.epoch(w.tick)}; most ranked starts by one pair in an epoch: {top}; "
          f"digest under the default 2/120 differs: {differs}")
    print(f"event digest {c.event_digest.hex()}")
    assert size < 1_000_000, size
    assert top > 2 and differs


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT)
