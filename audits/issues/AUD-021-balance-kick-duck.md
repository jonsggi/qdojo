# AUD-021 — Kick dominates; duck and throw are near useless

- **Status:** Fixed by combat-v1 candidate 2 (digest `231607f8…`) in code; the live arena still runs candidate 1 until the orchestrator starts a `demo-c2` arena
- **Priority:** P2 — strategic depth
- **Type:** Rules balance
- **Evidence:** Net HP per beat in the live field: KICK +7.5, DUCK −4.8, THROW −0.1; power and opening add about 4 HP per fight
- **Scope:** `docs/combat.md`, `docs/combat-v1.json` (a new ruleset digest)

## Finding

Measured in a field where half the bots played blind (AUD-014); may shift once history bots adapt ([simulation audit](../reports/2026-09-25-simulation-audit.md) §3.2–3.3).

## Acceptance criteria

- [x] Re-measure with the fixed field. It persists: in an 11-policy field with
  history-aware reader, search, scout and repeat-last-winner (4,400 fights),
  KICK earns +7.2 HP per beat and DUCK −5.6; KICK weakly dominates JAB in every
  column of the matrix, and the one-beat equilibrium is KICK 50% / BLOCK 49%.
  A fixed script (script-vs-scout) tops the field at 0.84.
- [x] Trial a candidate-2 ruleset behind a new digest and the full model.md
  campaign: `combat-v1-candidate-2`, digest
  `231607f823153747f4c922fd5976c1ac06622542cd5a39eab088874d886b8b74`
  ([combat.md §11](../../docs/combat.md#11-candidate-2)); results in
  [model.md §8](../../docs/model.md#8-balance-measurements-candidate-1-and-candidate-2).

## Resolution

Candidate 2 changes numbers only (same engine, actions, plan bytes):
jab out-trades kick 10 to 4 (was 8 to 14), duck counters a jab for 4, throw
breaks a block for 20 (was 14), opening +8 (was 4), power +12 (was 4), HP 120
(was 100). It was chosen over about forty variants measured with a fast
simulator of the live field and confirmed with the model.md campaign.

| Field measure (11 policies, 4,400 fights) | Candidate 1 | Candidate 2 |
|---|---:|---:|
| KICK / JAB / THROW net HP per beat | +7.2 / +1.5 / +1.9 | +5.4 / +4.1 / +2.7 |
| DUCK / BLOCK net HP per beat | −5.6 / −1.3 | −3.6 / −2.0 |
| One-beat equilibrium support | KICK, BLOCK | JAB, KICK, BLOCK, DUCK |
| Opening + power bonus per fighter and fight | 2.9 HP | 12.3 HP |
| KO / decision / draw | 82% / 17% / 5% | 68% / 32% / 5% |
| Fights reaching round 3 | 54% | 83% |
| Trailer after round 1 wins | 20% | 26% |
| History value (reader minus history-blind reader) | +0.05 | +0.23 |
| Best fixed script against the field | 0.84 (top of the field) | 0.62 (fifth) |

Not improved: the leader after round 2 still wins about 83% (84% before),
and close finishes (margin ≤ 8 HP) are 16% (18% before). BLOCK and THROW stay
situational: THROW is the hindsight-best reply on 30% of beats (against blocks
and recoveries) but is chosen on 7-14%; BLOCK is the safe hedge the one-beat
equilibrium plays 35% of the time.

### Shape and new-move proposals (not adopted)

- **More beats or rounds.** Measured on candidate 1 and candidate 2 with HP
  scaled: 8×3, 6×4, 5×4 and 4×4 did not raise comebacks or history value,
  made margins wider (median 48-54 vs 36 HP), and pushed exhaustion to 10-11%
  in 8-beat rounds; 6×4 adds a fourth commit window per fight (AUD-022). Only
  8×3 has a pacing upside (more action per window). Not worth changing the
  plan bytes, contract, site planner and every bot.
- **FEINT** (cost 2): deals nothing; if the opponent BLOCKs or DUCKs, the
  feinter earns an opening. A cheap answer to turtling that is not THROW.
- **PARRY** (cost 5): stops a JAB or KICK and deals 6 back; loses to THROW
  and does not strain; a sharper, riskier BLOCK.
- **CHARGE** (cost 0): gains +8 stamina and an opening, takes full damage;
  a riskier RECOVER that sets up the next beat.

Each would need a new action id (EXHAUSTED is id 6 today), codec, contract,
site palette, sprite clips, NPCs and prompts. Candidate 2 already gives every
action a role, so they stay proposals for a candidate 3 if the live meta
settles again.

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
