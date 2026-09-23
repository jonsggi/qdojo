#!/usr/bin/env python3
"""Freeze NPC plan fixtures: (npc, seed, fight, round, states, history) -> plan.

Other implementations of the disclosed roster (the browser's practice mode)
must reproduce these exactly. Regenerate only with a new policy version.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/qdojo/src"))

from qdojo.combat import npcs  # noqa: E402
from qdojo.combat.codec import encode_plan, encode_state  # noqa: E402
from qdojo.combat.rules import candidate_1  # noqa: E402
from qdojo.combat.types import SUBMITTED, Action, FighterState  # noqa: E402

OUT = ROOT / "packages/qdojo/tests/combat/fixtures/npcs-v1.json"


def generate(per_npc: int = 150, seed: int = 99):
    rules = candidate_1()
    rng = random.Random(seed)
    cases = []
    for npc_id in npcs.ROSTER:
        for _ in range(per_npc):
            r = rng.randrange(3)
            me = FighterState(rng.randint(1, 100), rng.randint(0, 60), rng.randint(0, 1), rng.randint(0, 3),
                              rng.randint(0, 1))
            opp = FighterState(rng.randint(1, 100), rng.randint(0, 60), rng.randint(0, 1), rng.randint(0, 3),
                               rng.randint(0, 1))
            history = tuple(tuple(rng.choice(list(SUBMITTED) + [Action.EXHAUSTED]) for _ in range(rng.randint(1, 6)))
                            for _ in range(r))
            seed_bytes = bytes(rng.getrandbits(8) for _ in range(32))
            fight = rng.randint(1, 10**6)
            plan = npcs.plan_for(npc_id, rules, npcs.Observation(r, me, opp, history), seed_bytes, fight)
            cases.append({"npc": npc_id, "seed": seed_bytes.hex(), "fight": fight, "round": r,
                          "self": encode_state(me).hex(), "opponent": encode_state(opp).hex(),
                          "opponent_history": [[int(a) for a in rnd] for rnd in history],
                          "plan": encode_plan(plan).hex()})
    return {"schema": "qdojo.combat.npc-fixtures.v1", "ruleset_digest": rules.digest.hex(),
            "note": "opponent_history holds executed effective action ids per prior round (6 = EXHAUSTED)",
            "cases": cases}


if __name__ == "__main__":
    doc = generate()
    text = json.dumps(doc, separators=(",", ":")) + "\n"
    if "--check" in sys.argv:
        sys.exit(0 if OUT.read_text() == text else f"{OUT} drifted")
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(doc['cases'])} cases")
