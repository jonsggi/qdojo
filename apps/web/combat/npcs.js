/* The disclosed practice roster (docs/npcs.md sections 2-3) for the browser.
 *
 * A port of packages/qdojo/src/qdojo/combat/npcs.py, checked against every
 * case in packages/qdojo/tests/combat/fixtures/npcs-v1.json. An NPC sees only
 * the public observation (both round-start states and the opponent's executed
 * actions from earlier rounds of this fight) and returns a legal plan. It
 * never sees the human's plan for the round it is planning.
 *
 * The PRNG is SHA256("qdojo/npc/v1\0" || seed[32] || fight u64 LE || round u8
 * || counter u32 LE), bytes consumed in order. crypto.subtle is async, so a
 * small synchronous SHA-256 lives here; it is for practice only. A live
 * commitment salt never comes from this file.
 *
 * <script src="combat/npcs.js"> (after combat/engine.js) defines
 * window.QDojoNpcs; in Node, require() returns the same object.
 */
'use strict';
(function (root, factory) {
  const engine = typeof module === 'object' && module && module.exports ? require('./engine.js') : root.QDojoCombat;
  const api = factory(engine);
  if (typeof module === 'object' && module && module.exports) module.exports = api;
  if (root) root.QDojoNpcs = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (E) {
  // ---- SHA-256 (FIPS 180-4), synchronous, byte arrays in and out -----------

  const K = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ]);

  function sha256(bytes) {
    const data = bytes instanceof Uint8Array ? bytes : Uint8Array.from(bytes);
    const bitLen = data.length * 8;
    const padded = new Uint8Array(((data.length + 9 + 63) >> 6) << 6);
    padded.set(data);
    padded[data.length] = 0x80;
    // Lengths here are far below 2^32 bits; the high word stays zero.
    const n = padded.length;
    padded[n - 4] = (bitLen >>> 24) & 255; padded[n - 3] = (bitLen >>> 16) & 255;
    padded[n - 2] = (bitLen >>> 8) & 255; padded[n - 1] = bitLen & 255;
    padded[n - 5] = Math.floor(bitLen / 0x100000000) & 255;
    const H = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
    const W = new Uint32Array(64);
    const rotr = (x, r) => (x >>> r) | (x << (32 - r));
    for (let off = 0; off < n; off += 64) {
      for (let i = 0; i < 16; i++) {
        const j = off + 4 * i;
        W[i] = (padded[j] << 24) | (padded[j + 1] << 16) | (padded[j + 2] << 8) | padded[j + 3];
      }
      for (let i = 16; i < 64; i++) {
        const s0 = rotr(W[i - 15], 7) ^ rotr(W[i - 15], 18) ^ (W[i - 15] >>> 3);
        const s1 = rotr(W[i - 2], 17) ^ rotr(W[i - 2], 19) ^ (W[i - 2] >>> 10);
        W[i] = (W[i - 16] + s0 + W[i - 7] + s1) | 0;
      }
      let a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7];
      for (let i = 0; i < 64; i++) {
        const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
        const ch = (e & f) ^ (~e & g);
        const t1 = (h + S1 + ch + K[i] + W[i]) | 0;
        const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
        const maj = (a & b) ^ (a & c) ^ (b & c);
        const t2 = (S0 + maj) | 0;
        h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
      }
      H[0] += a; H[1] += b; H[2] += c; H[3] += d; H[4] += e; H[5] += f; H[6] += g; H[7] += h;
    }
    const out = new Uint8Array(32);
    for (let i = 0; i < 8; i++) {
      out[4 * i] = H[i] >>> 24; out[4 * i + 1] = (H[i] >>> 16) & 255;
      out[4 * i + 2] = (H[i] >>> 8) & 255; out[4 * i + 3] = H[i] & 255;
    }
    return out;
  }

  function fromHex(hex) {
    if (typeof hex !== 'string' || hex.length % 2 || !/^[0-9a-f]*$/.test(hex)) throw new Error('npc: expected lowercase hex');
    const out = new Uint8Array(hex.length / 2);
    for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(2 * i, 2), 16);
    return out;
  }
  function toHex(bytes) { return Array.from(bytes, v => (v < 16 ? '0' : '') + v.toString(16)).join(''); }

  // ---- PRNG stream (npcs.md section 3) --------------------------------------

  const TAG = Array.from('qdojo/npc/v1\0', ch => ch.charCodeAt(0));

  function u64le(n) {
    if (!Number.isSafeInteger(n) || n < 0) throw new Error('npc: fight number must be a safe nonnegative integer');
    const out = [];
    for (let i = 0; i < 8; i++) { out.push(n % 256); n = Math.floor(n / 256); }
    return out;
  }

  function Stream(seed, fightNumber, roundIndex) {
    const s = typeof seed === 'string' ? fromHex(seed) : Uint8Array.from(seed);
    if (s.length !== 32) throw new Error('npc: a seed is 32 bytes');
    if (!Number.isInteger(roundIndex) || roundIndex < 0 || roundIndex > 255) throw new Error('npc: bad round index');
    const prefix = TAG.concat(Array.from(s), u64le(fightNumber), [roundIndex]);
    let counter = 0, buf = new Uint8Array(0), at = 0;
    function byte() {
      if (at === buf.length) {
        buf = sha256(prefix.concat([counter & 255, (counter >>> 8) & 255, (counter >>> 16) & 255, (counter >>> 24) & 255]));
        counter++;
        at = 0;
      }
      return buf[at++];
    }
    function uniform(n) {
      if (!Number.isInteger(n) || n < 1 || n > 256) throw new Error('npc: uniform takes 1..256');
      const limit = 256 - (256 % n);
      for (;;) { const v = byte(); if (v < limit) return v % n; }
    }
    function weighted(weights) {
      let x = uniform(weights.reduce((s, w) => s + w, 0));
      for (let i = 0; i < weights.length; i++) { if (x < weights[i]) return i; x -= weights[i]; }
      throw new Error('npc: unreachable');
    }
    return { byte, uniform, weighted };
  }

  // ---- policies (npcs.md section 2) -----------------------------------------

  const [J, KK, B, D, T, R, X] = [0, 1, 2, 3, 4, 5, 6];
  const SUBMITTED = [J, KK, B, D, T, R];
  const ATTACKS = new Set([J, KK, T]);
  const MIXED_WEIGHTS = [3, 2, 2, 2, 1, 2];
  const MIXED_LOW_WEIGHTS = [1, 0, 2, 2, 0, 5];
  const MIXED_LOW_STAMINA = 12;
  const POWER_MARGIN = 4;
  const POWER_ROUND = 2;

  const copy = s => ({ hp: s.hp, stamina: s.stamina, opening: s.opening, guard_streak: s.guard_streak, power_available: s.power_available });
  const hpFloor = s => (s.hp > 0 ? s : Object.assign(copy(s), { hp: 1 }));

  function actionCost(rules, s, action) {
    return rules.base_costs[action] + (action === B ? rules.block_streak_cost * s.guard_streak : 0);
  }
  function project(rules, me, opp, action, oppAction, power) {
    const r = E.resolveBeat(rules, me, opp, action, oppAction, power, false);
    return [hpFloor(r.a), hpFloor(r.b)];
  }
  function wantsPower(rules, obs, me, action, haveSlot) {
    return obs.round_index === POWER_ROUND && !haveSlot && me.power_available === 1 &&
      ATTACKS.has(action) && me.stamina >= actionCost(rules, me, action) + POWER_MARGIN;
  }

  function fixed(pattern) {
    return function (rules, obs) {
      let slot = -1;
      if (obs.round_index === POWER_ROUND && obs.self.power_available === 1) slot = pattern.findIndex(a => ATTACKS.has(a));
      return { actions: pattern.slice(), power_slot: slot };
    };
  }

  function randomV1(rules, obs, rng) {
    const actions = [];
    for (let i = 0; i < 6; i++) actions.push(SUBMITTED[rng.uniform(6)]);
    let slot = -1;
    if (obs.self.power_available === 1) {
      const eligible = [-1].concat(actions.map((a, i) => (ATTACKS.has(a) ? i : -1)).filter(i => i >= 0));
      slot = eligible[rng.uniform(eligible.length)];
    }
    return { actions, power_slot: slot };
  }

  function mixedAction(me, rng) {
    return SUBMITTED[rng.weighted(me.stamina < MIXED_LOW_STAMINA ? MIXED_LOW_WEIGHTS : MIXED_WEIGHTS)];
  }

  // The projection assumes an opponent who only RECOVERs: a resource estimate,
  // not a prediction of the opponent.
  function mixedV1(rules, obs, rng) {
    let me = obs.self, opp = obs.opponent, slot = -1;
    const actions = [];
    for (let i = 0; i < 6; i++) {
      const a = mixedAction(me, rng);
      const power = wantsPower(rules, obs, me, a, slot !== -1);
      if (power) slot = i;
      actions.push(a);
      [me, opp] = project(rules, me, opp, a, R, power);
    }
    return { actions, power_slot: slot };
  }

  function opponentCounts(history) {
    const counts = [1, 1, 1, 1, 1, 1];
    for (const round of history) for (const a of round) if (a !== X) counts[a]++;
    return counts;
  }

  function scoutV1(rules, obs, rng) {
    if (!obs.opponent_history || obs.opponent_history.length === 0) return mixedV1(rules, obs, rng);
    const counts = opponentCounts(obs.opponent_history);
    let modal = 0;
    for (let i = 1; i < 6; i++) if (counts[i] > counts[modal]) modal = i;
    let me = obs.self, opp = obs.opponent, slot = -1;
    const actions = [];
    for (let i = 0; i < 6; i++) {
      let a;
      if (rng.uniform(4) < 3) {
        // Every candidate is scored from the same projected snapshot.
        const scores = SUBMITTED.map(cand => {
          let total = 0;
          for (const oa of SUBMITTED) {
            const r = E.resolveBeat(rules, me, opp, cand, oa, false, false);
            total += counts[oa] * (4 * (r.trace[0].computed_damage - r.trace[1].computed_damage) + r.a.stamina - me.stamina);
          }
          return total;
        });
        const best = Math.max.apply(null, scores);
        const tied = SUBMITTED.filter((_, k) => scores[k] === best);
        a = tied.length > 1 ? tied[rng.uniform(tied.length)] : tied[0];
      } else {
        a = mixedAction(me, rng);
      }
      const power = wantsPower(rules, obs, me, a, slot !== -1);
      if (power) slot = i;
      actions.push(a);
      [me, opp] = project(rules, me, opp, a, modal, power);
    }
    return { actions, power_slot: slot };
  }

  const ROSTER = Object.freeze([
    { id: 'random-v1', name: 'RANDOM', behavior: 'Uniform independent actions, optional random power timing', lesson: 'Learn rules; benchmark against an unstructured opponent', policy: randomV1 },
    { id: 'jabber-v1', name: 'JABBER', behavior: 'JAB,JAB,JAB,RECOVER,JAB,JAB each round', lesson: 'Punish predictable highs with duck/counter', policy: fixed([J, J, J, R, J, J]) },
    { id: 'turtle-v1', name: 'TURTLE', behavior: 'BLOCK,BLOCK,RECOVER,BLOCK,DUCK,RECOVER', lesson: 'Use throw, low attacks and guard pressure', policy: fixed([B, B, R, B, D, R]) },
    { id: 'kicker-v1', name: 'KICKER', behavior: 'KICK,RECOVER,KICK,RECOVER,KICK,RECOVER', lesson: 'Punish expensive attacks and recovery timing', policy: fixed([KK, R, KK, R, KK, R]) },
    { id: 'mixed-v1', name: 'MIXED', behavior: 'Stateful weighted policy', lesson: 'Test basic resource-aware optimization', policy: mixedV1 },
    { id: 'scout-v1', name: 'SCOUT', behavior: 'Adapt next-round action distribution from past observations', lesson: 'Train against an opponent that changes strategy', policy: scoutV1 },
  ].map(Object.freeze));

  /* obs = { round_index, self: state, opponent: state, opponent_history: [[effective action ids], ...] }
   * seed: 64 hex digits or 32 bytes. Returns { actions: [ids], power_slot }. */
  function planFor(npcId, rules, obs, seed, fightNumber) {
    const npc = ROSTER.find(n => n.id === npcId);
    if (!npc) throw new Error('npc: unknown NPC ' + npcId + '; known: ' + ROSTER.map(n => n.id).join(', '));
    return npc.policy(rules, obs, Stream(seed, fightNumber, obs.round_index));
  }

  return Object.freeze({ ROSTER, planFor, Stream, sha256, fromHex, toHex, opponentCounts });
});
