#!/usr/bin/env python3
"""Freeze NPC plan fixtures: (npc, seed, fight, round, states, history) -> plan.

Other implementations of the disclosed roster (the browser's practice mode)
must reproduce these exactly. Regenerate only with a new policy version.
One file per packaged ruleset (NPCs project with the ruleset's numbers):
npcs-v1.json for candidate 1, npcs-v1-<digest16>.json for any other.

  combat-npc-fixtures.py [--ruleset combat-v1-candidate-2] [--check]
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
from qdojo.combat.rules import CANDIDATE_1, KNOWN, by_version  # noqa: E402
from qdojo.combat.types import SUBMITTED, Action, FighterState  # noqa: E402

FIXDIR = ROOT / "packages/qdojo/tests/combat/fixtures"


def out_path(rules) -> Path:
    return FIXDIR / ("npcs-v1.json" if rules.semantic_version == CANDIDATE_1 else f"npcs-v1-{rules.digest.hex()[:16]}.json")


def generate(per_npc: int = 150, seed: int = 99, rules=None):
    rules = rules or by_version(CANDIDATE_1)
    hp, st = rules.max_hp, rules.max_stamina
    rng = random.Random(seed)
    cases = []
    for npc_id in npcs.ROSTER:
        for _ in range(per_npc):
            r = rng.randrange(3)
            me = FighterState(rng.randint(1, hp), rng.randint(0, st), rng.randint(0, 1), rng.randint(0, 3),
                              rng.randint(0, 1))
            opp = FighterState(rng.randint(1, hp), rng.randint(0, st), rng.randint(0, 1), rng.randint(0, 3),
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
    version = sys.argv[sys.argv.index("--ruleset") + 1] if "--ruleset" in sys.argv else CANDIDATE_1
    if version not in KNOWN:
        sys.exit(f"unknown ruleset {version!r}; known: {', '.join(KNOWN)}")
    rules = by_version(version)
    doc = generate(rules=rules)
    text = json.dumps(doc, separators=(",", ":")) + "\n"
    out = out_path(rules)
    if "--check" in sys.argv:
        sys.exit(0 if out.read_text() == text else f"{out} drifted")
    out.write_text(text)
    print(f"wrote {out.relative_to(ROOT)}: {len(doc['cases'])} cases")
