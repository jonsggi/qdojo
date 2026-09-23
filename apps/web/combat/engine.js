/* qdojo combat-v1 engine for the browser and Node.
 *
 * An independent implementation of docs/combat.md (sections 2-9) that takes
 * the parsed ruleset (docs/combat-v1.json) as a parameter: every number comes
 * from the ruleset, only the meaning of the named actions is fixed here.
 * Integers only; no clock, no randomness, no floating point. Impossible
 * states and plans throw; nothing is clamped into plausibility.
 *
 * Wire encodings follow docs/protocol.md section 2, as lowercase hex:
 *   state (8 bytes): hp u16 LE, stamina u16 LE, opening u8, guard_streak u8,
 *                    power_available u8, reserved u8 = 0
 *   plan  (7 bytes): six action ids in beat order, then power slot (255 = none)
 *
 * <script src="combat/engine.js"> defines window.QDojoCombat;
 * in Node, require() returns the same object.
 */
'use strict';
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module && module.exports) module.exports = api;
  if (root) root.QDojoCombat = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const ACTIONS = Object.freeze(['JAB', 'KICK', 'BLOCK', 'DUCK', 'THROW', 'RECOVER', 'EXHAUSTED']);
  const NO_POWER = 255;

  function fail(msg) { throw new Error('combat: ' + msg); }
  function isInt(v) { return typeof v === 'number' && Number.isInteger(v); }
  function needInt(v, lo, hi, what) {
    if (!isInt(v) || v < lo || v > hi) fail(what + ' must be an integer in ' + lo + '..' + hi + ', got ' + v);
    return v;
  }

  // ---- ruleset --------------------------------------------------------------

  // Checks the ruleset once per object and derives the action indices.
  const compiled = new WeakMap();
  function compile(rules) {
    if (!rules || typeof rules !== 'object') fail('ruleset must be an object');
    const hit = compiled.get(rules);
    if (hit) return hit;
    const names = rules.action_names;
    if (!Array.isArray(names)) fail('ruleset action_names missing');
    const id = {};
    for (const n of ACTIONS) {
      const i = names.indexOf(n);
      if (i < 0) fail('ruleset lacks action ' + n);
      id[n] = i;
    }
    const count = names.length;
    const nonneg = (v, what) => needInt(v, 0, Number.MAX_SAFE_INTEGER, 'ruleset ' + what);
    const damage = rules.damage;
    if (!Array.isArray(damage) || damage.length !== count) fail('ruleset damage must be ' + count + ' rows');
    damage.forEach((row, r) => {
      if (!Array.isArray(row) || row.length !== count) fail('ruleset damage row ' + r + ' has wrong length');
      row.forEach((v, c) => nonneg(v, 'damage[' + r + '][' + c + ']'));
    });
    if (!Array.isArray(rules.base_costs) || rules.base_costs.length !== count) fail('ruleset base_costs has wrong length');
    rules.base_costs.forEach((v, i) => nonneg(v, 'base_costs[' + i + ']'));
    const submitted = rules.submitted_action_ids;
    if (!Array.isArray(submitted) || submitted.length === 0) fail('ruleset submitted_action_ids missing');
    submitted.forEach(v => needInt(v, 0, count - 1, 'ruleset submitted action id'));
    if (submitted.indexOf(id.EXHAUSTED) >= 0) fail('EXHAUSTED cannot be a submitted action');
    const limits = rules.limits || {};
    const initial = rules.initial || {};
    for (const k of ['hp', 'stamina', 'guard_streak']) nonneg(limits[k], 'limits.' + k);
    if (limits.hp < 1) fail('ruleset limits.hp must be positive');
    for (const k of ['block_streak_cost', 'block_strain', 'ordinary_recovery', 'recover_unhit', 'recover_hit',
      'exhausted_recovery', 'break_recovery', 'opening_damage', 'power_damage', 'power_cost']) nonneg(rules[k], k);
    needInt(rules.rounds, 1, 255, 'ruleset rounds');
    needInt(rules.beats_per_round, 1, 254, 'ruleset beats_per_round');
    const c = {
      rules, id, count, damage, limits,
      costs: rules.base_costs,
      submitted: new Set(submitted),
      // An attack is an action that can deal damage to something.
      attacks: new Set(damage.map((row, i) => (row.some(v => v > 0) ? i : -1)).filter(i => i >= 0)),
    };
    c.initial = checkState(c, {
      hp: initial.hp, stamina: initial.stamina, opening: initial.opening,
      guard_streak: initial.guard_streak, power_available: initial.power_available,
    }, 'ruleset initial');
    compiled.set(rules, c);
    return c;
  }

  // ---- states and plans -----------------------------------------------------

  function checkState(c, s, what) {
    if (!s || typeof s !== 'object') fail(what + ' state must be an object');
    needInt(s.hp, 0, c.limits.hp, what + '.hp');
    needInt(s.stamina, 0, c.limits.stamina, what + '.stamina');
    needInt(s.opening, 0, 1, what + '.opening');
    needInt(s.guard_streak, 0, c.limits.guard_streak, what + '.guard_streak');
    needInt(s.power_available, 0, 1, what + '.power_available');
    return copyState(s);
  }
  function copyState(s) {
    return { hp: s.hp, stamina: s.stamina, opening: s.opening, guard_streak: s.guard_streak, power_available: s.power_available };
  }

  function newFight(rules) {
    const c = compile(rules);
    return { round_index: 0, a: copyState(c.initial), b: copyState(c.initial) };
  }

  // Whole-plan validation before any beat runs (combat.md section 3).
  function checkPlan(c, plan, state, what) {
    if (!plan || typeof plan !== 'object' || !Array.isArray(plan.actions)) fail(what + ' plan must have an actions array');
    if (plan.actions.length !== c.rules.beats_per_round) fail(what + ' plan must have exactly ' + c.rules.beats_per_round + ' actions');
    const actions = plan.actions.map((a, i) => {
      if (!isInt(a) || !c.submitted.has(a)) fail(what + ' action ' + i + ' is not a submitted action id: ' + a);
      return a;
    });
    const slot = plan.power_slot;
    if (!isInt(slot) || slot < -1 || slot >= actions.length) fail(what + ' power_slot must be -1 or 0..' + (actions.length - 1));
    if (slot >= 0) {
      if (!c.attacks.has(actions[slot])) fail(what + ' power slot ' + slot + ' is not an attack');
      if (state && state.power_available !== 1) fail(what + ' power already spent');
    }
    return { actions, power_slot: slot };
  }

  function validatePlan(rules, plan, state) {
    const c = compile(rules);
    return checkPlan(c, plan, state ? checkState(c, state, 'plan owner') : null, 'plan');
  }

  // ---- one beat (combat.md section 6) ---------------------------------------

  function resolveBeat(rules, a, b, intentA, intentB, powerA, powerB) {
    const c = compile(rules);
    const before = [checkState(c, a, 'A'), checkState(c, b, 'B')];
    const intent = [intentA, intentB];
    const power = [powerA, powerB];
    const { id, rules: R } = c;
    const side = [0, 1].map(i => {
      const s = before[i], act = intent[i], pw = power[i];
      if (pw !== true && pw !== false) fail('power flag must be boolean');
      if (!isInt(act) || !c.submitted.has(act)) fail('intended action is not a submitted action id: ' + act);
      if (s.hp === 0) fail('a knocked-out fighter cannot act');
      if (pw) {
        if (!c.attacks.has(act)) fail('power strike must be an attack');
        if (s.power_available !== 1) fail('power already spent');
      }
      // 1. cost from pre-beat guard streak, plus the power surcharge
      const cost = c.costs[act] + (act === id.BLOCK ? R.block_streak_cost * s.guard_streak : 0) + (pw ? R.power_cost : 0);
      // 3. effective action; an unaffordable move becomes EXHAUSTED and pays nothing
      const affordable = s.stamina >= cost;
      return { s, act, pw, cost, eff: affordable ? act : id.EXHAUSTED, paid: affordable ? cost : 0 };
    });
    // 4-5. both damages from the same pre-damage snapshot
    for (let i = 0; i < 2; i++) {
      const me = side[i], them = side[1 - i];
      me.base = c.damage[me.eff][them.eff];
      me.openingBonus = me.base > 0 && me.s.opening === 1 ? R.opening_damage : 0;
      me.powerBonus = me.base > 0 && me.pw && me.eff === me.act ? R.power_damage : 0;
      me.computed = me.base + me.openingBonus + me.powerBonus;
    }
    const trace = [];
    const after = [];
    for (let i = 0; i < 2; i++) {
      const me = side[i], them = side[1 - i], s = me.s;
      const incoming = them.computed;
      // 6. simultaneous damage
      const hp = Math.max(0, s.hp - incoming);
      // 7. block strain after paying the cost
      let stamina = s.stamina - me.paid;
      const strain = me.eff === id.BLOCK && them.eff === id.KICK ? Math.min(stamina, R.block_strain) : 0;
      stamina -= strain;
      // 8. recovery alternatives, capped
      let gain;
      if (me.eff === id.RECOVER) gain = incoming === 0 ? R.recover_unhit : R.recover_hit;
      else if (me.eff === id.EXHAUSTED) gain = R.exhausted_recovery;
      else gain = R.ordinary_recovery;
      const recovered = Math.min(c.limits.stamina, stamina + gain) - stamina;
      stamina += recovered;
      // 9. opening is replaced every beat
      const opening = (me.eff === id.DUCK && (them.eff === id.JAB || them.eff === id.THROW)) ||
        (me.eff === id.JAB && me.computed > 0 && incoming === 0) ? 1 : 0;
      // 10. guard streak
      const guard = me.eff === id.BLOCK ? Math.min(c.limits.guard_streak, s.guard_streak + 1) : 0;
      // 2. power is spent on the designated slot whatever happens
      const next = { hp, stamina, opening, guard_streak: guard, power_available: me.pw ? 0 : s.power_available };
      after.push(next);
      trace.push({
        before: copyState(s), after: copyState(next),
        intended: me.act, effective: me.eff, power: me.pw,
        cost: me.cost, cost_paid: me.paid,
        base_damage: me.base, bonus_damage: me.openingBonus + me.powerBonus,
        opening_bonus: me.openingBonus, power_bonus: me.powerBonus,
        computed_damage: me.computed, actual_hp_lost: s.hp - hp,
        strain, recovered, reasons: null,
      });
    }
    // 11. reasons, from the finished paired update (explanation only, never logic)
    for (let i = 0; i < 2; i++) trace[i].reasons = reasonsFor(c, side[i], side[1 - i], trace[i], after[1 - i]);
    return { a: after[0], b: after[1], trace };
  }

  function reasonsFor(c, me, them, t, themAfter) {
    const { id } = c;
    const out = [];
    const incoming = them.computed;
    if (me.eff === id.EXHAUSTED) out.push('INSUFFICIENT_STAMINA');
    else if (c.attacks.has(me.eff)) {
      if (me.computed > 0) out.push('HIT');
      else if (me.eff === id.THROW && them.eff === id.THROW) out.push('THROW_CLASH');
      else if (me.eff === id.THROW && c.attacks.has(them.eff) && incoming > 0) out.push('THROW_INTERRUPTED');
      else if (them.eff === id.BLOCK) out.push('BLOCKED');
      else if (them.eff === id.DUCK) out.push('EVADED');
    } else if (me.eff === id.RECOVER && incoming > 0) out.push('RECOVERY_PUNISHED');
    else if (me.eff === id.BLOCK && them.eff === id.KICK) out.push('GUARD_STRAIN');
    if (t.before.opening === 1) out.push(t.opening_bonus > 0 ? 'OPENING_USED' : 'OPENING_EXPIRED');
    if (me.pw) out.push(t.power_bonus > 0 ? 'POWER_USED' : 'POWER_WASTED');
    if (t.after.opening === 1) out.push('OPENING_EARNED');
    const mineOut = t.after.hp === 0, theirsOut = themAfter.hp === 0;
    if (mineOut && theirsOut) out.push('DOUBLE_KO');
    else if (mineOut) out.push('KO');
    return out;
  }

  // ---- a round and a fight (combat.md section 7) ----------------------------

  function outcomeOf(a, b, final) {
    if (a.hp === 0 && b.hp === 0) return { winner: null, result: 'DOUBLE_KO' };
    if (a.hp === 0) return { winner: 'B', result: 'KO' };
    if (b.hp === 0) return { winner: 'A', result: 'KO' };
    if (!final) return null;
    if (a.hp === b.hp) return { winner: null, result: 'HP_TIE' };
    return { winner: a.hp > b.hp ? 'A' : 'B', result: 'HP' };
  }

  function resolveRound(rules, start, planA, planB) {
    const c = compile(rules);
    if (!start || typeof start !== 'object') fail('round start must be an object');
    const round = needInt(start.round_index, 0, c.rules.rounds - 1, 'round_index');
    let a = checkState(c, start.a, 'A'), b = checkState(c, start.b, 'B');
    if (a.hp === 0 || b.hp === 0) fail('round start is terminal');
    const pa = checkPlan(c, typeof planA === 'string' ? decodePlan(planA) : planA, a, 'A');
    const pb = checkPlan(c, typeof planB === 'string' ? decodePlan(planB) : planB, b, 'B');
    const beats = [];
    for (let beat = 0; beat < pa.actions.length; beat++) {
      const r = resolveBeat(rules, a, b, pa.actions[beat], pb.actions[beat], pa.power_slot === beat, pb.power_slot === beat);
      a = r.a; b = r.b;
      beats.push({ beat, a: r.trace[0], b: r.trace[1] });
      const ko = outcomeOf(a, b, false);
      if (ko) return { round_index: round, plans: [pa, pb], beats, executed: beats.length, end: { round_index: round, a, b }, outcome: ko, break_recovery: null };
    }
    if (round === c.rules.rounds - 1) {
      return { round_index: round, plans: [pa, pb], beats, executed: beats.length, end: { round_index: round, a, b }, outcome: outcomeOf(a, b, true), break_recovery: null };
    }
    const na = breakRecovery(rules, a), nb = breakRecovery(rules, b);
    return {
      round_index: round, plans: [pa, pb], beats, executed: beats.length,
      before_break: { a, b },
      end: { round_index: round + 1, a: na, b: nb },
      outcome: null,
      break_recovery: { a: na.stamina - a.stamina, b: nb.stamina - b.stamina },
    };
  }

  // The fixed inter-round break: stamina +break_recovery capped; all else carries.
  function breakRecovery(rules, state) {
    const c = compile(rules);
    const s = checkState(c, state, 'break');
    s.stamina = Math.min(c.limits.stamina, s.stamina + c.rules.break_recovery);
    return s;
  }

  // roundsOfPlans: [[planA, planB], ...] as plan objects or 7-byte hex strings.
  function replayFight(rules, roundsOfPlans) {
    if (!Array.isArray(roundsOfPlans)) fail('rounds must be an array');
    let state = newFight(rules);
    const rounds = [];
    let outcome = null;
    for (const pair of roundsOfPlans) {
      if (outcome) fail('plans supplied after the fight ended');
      if (!Array.isArray(pair) || pair.length < 2) fail('each round needs [planA, planB]');
      const r = resolveRound(rules, state, pair[0], pair[1]);
      rounds.push(r);
      state = r.end;
      outcome = r.outcome;
    }
    return { rounds, end: state, outcome };
  }

  // ---- hex codecs (protocol.md section 2) -----------------------------------

  function bytesOf(hex, n, what) {
    if (typeof hex !== 'string' || hex.length !== 2 * n || !/^[0-9a-f]*$/.test(hex)) fail(what + ' must be ' + (2 * n) + ' lowercase hex digits');
    const out = [];
    for (let i = 0; i < n; i++) out.push(parseInt(hex.substr(2 * i, 2), 16));
    return out;
  }
  function hexOf(bytes) { return bytes.map(v => (v < 16 ? '0' : '') + v.toString(16)).join(''); }

  function decodeState(hex, rules) {
    const x = bytesOf(hex, 8, 'state');
    if (x[7] !== 0) fail('state reserved byte must be 0');
    const s = { hp: x[0] | (x[1] << 8), stamina: x[2] | (x[3] << 8), opening: x[4], guard_streak: x[5], power_available: x[6] };
    if (s.opening > 1 || s.power_available > 1) fail('state flag out of range');
    return rules ? checkState(compile(rules), s, 'decoded') : s;
  }
  function encodeState(s, rules) {
    if (rules) checkState(compile(rules), s, 'encoded');
    needInt(s.hp, 0, 0xffff, 'hp'); needInt(s.stamina, 0, 0xffff, 'stamina');
    needInt(s.opening, 0, 1, 'opening'); needInt(s.guard_streak, 0, 0xff, 'guard_streak');
    needInt(s.power_available, 0, 1, 'power_available');
    return hexOf([s.hp & 0xff, s.hp >> 8, s.stamina & 0xff, s.stamina >> 8, s.opening, s.guard_streak, s.power_available, 0]);
  }
  function decodePlan(hex, rules, state) {
    const x = bytesOf(hex, 7, 'plan');
    const plan = { actions: x.slice(0, 6), power_slot: x[6] === NO_POWER ? -1 : x[6] };
    if (rules) return validatePlan(rules, plan, state);
    // Without a ruleset still refuse what the wire format forbids.
    plan.actions.forEach(a => { if (a > 5) fail('plan action id ' + a + ' is not legal on the wire'); });
    if (plan.power_slot > 5) fail('plan power slot ' + x[6] + ' is not legal on the wire');
    return plan;
  }
  function encodePlan(plan, rules, state) {
    const p = rules ? validatePlan(rules, plan, state) : plan;
    if (!Array.isArray(p.actions) || p.actions.length !== 6) fail('plan must have six actions');
    p.actions.forEach(a => needInt(a, 0, 5, 'plan action'));
    needInt(p.power_slot, -1, 5, 'power_slot');
    return hexOf(p.actions.concat([p.power_slot < 0 ? NO_POWER : p.power_slot]));
  }

  return Object.freeze({
    ACTIONS, NO_POWER,
    newFight, validatePlan, resolveBeat, resolveRound, breakRecovery, replayFight,
    decodeState, encodeState, decodePlan, encodePlan,
  });
});
