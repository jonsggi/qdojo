/* The packaged combat-v1 rulesets, embedded for offline pages (practice,
 * rules) and as the fallback when an export lacks its ruleset artifact.
 *
 * Logical copies of docs/combat-v1.json (candidate 1) and
 * docs/combat-v1-candidate-2.json (candidate 2). The page never trusts a copy
 * on its own word: it recomputes SHA256("qdojo/combat/rules/v1\0" ||
 * canonical JSON) and uses the copy whose digest equals the manifest's
 * ruleset_digest, so replays of either candidate verify.
 * tests/combat-app.test.cjs checks both copies against docs/.
 *
 * <script src="combat/ruleset.js"> defines window.QDojoRuleset (candidate 1,
 * the default before an export names one) and window.QDojoRulesets (every
 * embedded ruleset); in Node, require() returns candidate 1 and the list is
 * globalThis.QDojoRulesets.
 */
'use strict';
(function (root, factory) {
  const all = factory();
  if (typeof module === 'object' && module && module.exports) module.exports = all[0];
  if (root) { root.QDojoRuleset = all[0]; root.QDojoRulesets = all; }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const deepFreeze = o => { Object.values(o).forEach(v => { if (v && typeof v === 'object') deepFreeze(v); }); return Object.freeze(o); };
  const candidate1 = {
    semantic_version: 'combat-v1-candidate-1',
    rounds: 3,
    beats_per_round: 6,
    initial: { hp: 100, stamina: 60, opening: 0, guard_streak: 0, power_available: 1 },
    limits: { hp: 100, stamina: 60, guard_streak: 3 },
    action_names: ['JAB', 'KICK', 'BLOCK', 'DUCK', 'THROW', 'RECOVER', 'EXHAUSTED'],
    submitted_action_ids: [0, 1, 2, 3, 4, 5],
    base_costs: [6, 12, 4, 4, 9, 0, 0],
    block_streak_cost: 3,
    block_strain: 6,
    ordinary_recovery: 2,
    recover_unhit: 18,
    recover_hit: 6,
    exhausted_recovery: 6,
    break_recovery: 10,
    opening_damage: 4,
    power_damage: 4,
    power_cost: 4,
    damage: [
      [8, 8, 0, 0, 8, 12, 12],
      [14, 14, 0, 18, 14, 18, 18],
      [0, 0, 0, 0, 0, 0, 0],
      [0, 0, 0, 0, 0, 0, 0],
      [0, 0, 14, 0, 0, 18, 18],
      [0, 0, 0, 0, 0, 0, 0],
      [0, 0, 0, 0, 0, 0, 0],
    ],
  };
  // Candidate 2 (docs/combat.md "Candidate 2"): jab out-trades kick, duck
  // counters a jab, throw breaks a block for 20, opening +8, power +12, 120 HP,
  // 48 stamina.
  const candidate2 = {
    semantic_version: 'combat-v1-candidate-2',
    rounds: 3,
    beats_per_round: 6,
    initial: { hp: 120, stamina: 48, opening: 0, guard_streak: 0, power_available: 1 },
    limits: { hp: 120, stamina: 48, guard_streak: 3 },
    action_names: ['JAB', 'KICK', 'BLOCK', 'DUCK', 'THROW', 'RECOVER', 'EXHAUSTED'],
    submitted_action_ids: [0, 1, 2, 3, 4, 5],
    base_costs: [6, 12, 4, 4, 9, 0, 0],
    block_streak_cost: 3,
    block_strain: 6,
    ordinary_recovery: 2,
    recover_unhit: 18,
    recover_hit: 6,
    exhausted_recovery: 6,
    break_recovery: 10,
    opening_damage: 8,
    power_damage: 12,
    power_cost: 4,
    damage: [
      [8, 10, 0, 0, 8, 12, 12],
      [4, 14, 0, 18, 14, 18, 18],
      [0, 0, 0, 0, 0, 0, 0],
      [4, 0, 0, 0, 0, 0, 0],
      [0, 0, 20, 0, 0, 18, 18],
      [0, 0, 0, 0, 0, 0, 0],
      [0, 0, 0, 0, 0, 0, 0],
    ],
  };
  return deepFreeze([candidate1, candidate2]);
});
