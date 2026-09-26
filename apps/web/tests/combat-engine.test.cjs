// Browser combat engine against the spec and the frozen Python fixtures.
// No dependencies: node --test apps/web/tests/combat-engine.test.cjs
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createContext, runInContext } = require('node:vm');

const ROOT = path.join(__dirname, '../../..');
const ENGINE = path.join(__dirname, '../combat/engine.js');
const E = require(ENGINE);
const rules = JSON.parse(fs.readFileSync(path.join(ROOT, 'docs/combat-v1.json'), 'utf8'));
const FIXDIR = path.join(ROOT, 'packages/qdojo/tests/combat/fixtures');

const [JAB, KICK, BLOCK, DUCK, THROW, RECOVER, EXHAUSTED] = [0, 1, 2, 3, 4, 5, 6];
const fresh = (over = {}) => Object.assign({ hp: 100, stamina: 60, opening: 0, guard_streak: 0, power_available: 1 }, over);
const beat = (a, b, ia, ib, pa = false, pb = false) => E.resolveBeat(rules, a, b, ia, ib, pa, pb);
const tuple = s => [s.hp, s.stamina, s.opening, s.guard_streak];
const plan = (actions, power_slot = -1) => ({ actions, power_slot });

test('loads as a plain script and defines QDojoCombat', () => {
  const api = runInContext(fs.readFileSync(ENGINE, 'utf8') + '\nQDojoCombat;', createContext({}));
  assert.deepEqual([...api.ACTIONS], ['JAB', 'KICK', 'BLOCK', 'DUCK', 'THROW', 'RECOVER', 'EXHAUSTED']);
  assert.equal(typeof api.resolveRound, 'function');
});

test('section 8 single-beat table', () => {
  const rows = [
    [JAB, BLOCK, [100, 56, 0, 0], [100, 58, 0, 1]],
    [JAB, KICK, [86, 56, 0, 0], [92, 50, 0, 0]],
    [DUCK, JAB, [100, 58, 1, 0], [100, 56, 0, 0]],
    [KICK, DUCK, [100, 50, 0, 0], [82, 58, 0, 0]],
    [THROW, BLOCK, [100, 53, 0, 0], [86, 58, 0, 1]],
    [BLOCK, KICK, [100, 52, 0, 1], [100, 50, 0, 0]],
    [RECOVER, JAB, [88, 60, 0, 0], [100, 56, 1, 0]],
    [THROW, THROW, [100, 53, 0, 0], [100, 53, 0, 0]],
  ];
  for (const [ia, ib, ea, eb] of rows) {
    const r = beat(fresh(), fresh(), ia, ib);
    const label = E.ACTIONS[ia] + '/' + E.ACTIONS[ib];
    assert.deepEqual(tuple(r.a), ea, label + ' A');
    assert.deepEqual(tuple(r.b), eb, label + ' B');
  }
});

test('section 8 stateful vectors', () => {
  // DUCK/JAB then KICK/JAB: the opening adds 4 to the kick
  const r1 = beat(fresh(), fresh(), DUCK, JAB);
  const r2 = beat(r1.a, r1.b, KICK, JAB);
  assert.deepEqual(tuple(r2.a), [92, 48, 0, 0]);
  assert.deepEqual(tuple(r2.b), [82, 52, 0, 0]);
  assert.equal(r2.trace[0].computed_damage, 18);

  // stamina 11 KICK into JAB: exhausted
  let r = beat(fresh({ stamina: 11 }), fresh(), KICK, JAB);
  assert.equal(r.trace[0].effective, EXHAUSTED);
  assert.equal(r.trace[0].cost, 12);
  assert.equal(r.trace[0].cost_paid, 0);
  assert.ok(r.trace[0].reasons.includes('INSUFFICIENT_STAMINA'));
  assert.deepEqual(tuple(r.a), [88, 17, 0, 0]);
  assert.deepEqual(tuple(r.b), [100, 56, 1, 0]);

  // stamina 12 KICK executes, ending at 2
  r = beat(fresh({ stamina: 12 }), fresh(), KICK, BLOCK);
  assert.equal(r.trace[0].effective, KICK);
  assert.equal(r.trace[0].cost_paid, 12);
  assert.equal(r.a.stamina, 2);

  // opening + powered KICK into DUCK
  r = beat(fresh({ opening: 1 }), fresh(), KICK, DUCK, true, false);
  assert.equal(r.a.stamina, 46);
  assert.equal(r.a.power_available, 0);
  assert.equal(r.trace[1].actual_hp_lost, 26);
  assert.equal(r.trace[0].actual_hp_lost, 0);

  // powered JAB into BLOCK
  r = beat(fresh(), fresh(), JAB, BLOCK, true, false);
  assert.equal(r.a.stamina, 52);
  assert.equal(r.a.power_available, 0);
  assert.equal(r.a.hp, 100);
  assert.equal(r.b.hp, 100);
  assert.ok(r.trace[0].reasons.includes('POWER_WASTED'));

  // stamina 9 powered JAB into JAB: cost 10, exhausted, power still spent
  r = beat(fresh({ stamina: 9 }), fresh(), JAB, JAB, true, false);
  assert.equal(r.trace[0].cost, 10);
  assert.equal(r.trace[0].effective, EXHAUSTED);
  assert.equal(r.a.hp, 88);
  assert.equal(r.a.stamina, 15);
  assert.equal(r.a.power_available, 0);

  // guard fatigue: four BLOCKs into RECOVER, then a fifth costs 13 again
  let a = fresh(), b = fresh();
  const seen = [];
  for (let i = 0; i < 4; i++) {
    const x = beat(a, b, BLOCK, RECOVER);
    a = x.a; b = x.b;
    seen.push([a.stamina, a.guard_streak]);
  }
  assert.deepEqual(seen, [[58, 1], [53, 2], [45, 3], [34, 3]]);
  assert.equal(beat(a, b, BLOCK, RECOVER).trace[0].cost, 13);

  // BLOCK at stamina 4 into KICK
  r = beat(fresh({ stamina: 4 }), fresh(), BLOCK, KICK);
  assert.equal(r.trace[0].effective, BLOCK);
  assert.equal(r.trace[0].cost_paid, 4);
  assert.equal(r.trace[0].strain, 0);
  assert.equal(r.trace[0].recovered, 2);
  assert.deepEqual(tuple(r.a), [100, 2, 0, 1]);
  const next = beat(r.a, r.b, BLOCK, RECOVER);
  assert.equal(next.trace[0].cost, 7);
  assert.equal(next.trace[0].effective, EXHAUSTED);

  // double KOs
  r = beat(fresh({ hp: 8 }), fresh({ hp: 8 }), JAB, JAB);
  assert.equal(r.trace[0].computed_damage, 8);
  assert.equal(r.trace[1].computed_damage, 8);
  assert.equal(r.a.hp + r.b.hp, 0);
  assert.ok(r.trace[0].reasons.includes('DOUBLE_KO'));
  r = beat(fresh({ hp: 14 }), fresh({ hp: 8 }), JAB, KICK);
  assert.equal(r.a.hp + r.b.hp, 0);
  let round = E.resolveRound(rules, { round_index: 0, a: fresh({ hp: 14 }), b: fresh({ hp: 8 }) },
    plan([JAB, JAB, JAB, JAB, JAB, JAB]), plan([KICK, JAB, JAB, JAB, JAB, JAB]));
  assert.deepEqual(round.outcome, { winner: null, result: 'DOUBLE_KO' });
  assert.equal(round.executed, 1);
});

test('section 8 whole-fight vectors', () => {
  const rec = plan([RECOVER, RECOVER, RECOVER, RECOVER, RECOVER, RECOVER]);
  const idle = E.replayFight(rules, [[rec, rec], [rec, rec], [rec, rec]]);
  assert.deepEqual(idle.outcome, { winner: null, result: 'HP_TIE' });
  assert.deepEqual(tuple(idle.end.a), [100, 60, 0, 0]);
  assert.deepEqual(tuple(idle.end.b), [100, 60, 0, 0]);

  const jabs = plan([JAB, JAB, JAB, JAB, JAB, JAB]);
  const fight = E.replayFight(rules, [[jabs, jabs], [jabs, jabs], [jabs, jabs]]);
  const [r0, r1, r2] = fight.rounds;
  assert.deepEqual(tuple(r0.before_break.a), [52, 36, 0, 0]);
  assert.deepEqual(tuple(r0.end.a), [52, 46, 0, 0]);
  assert.deepEqual(r0.break_recovery, { a: 10, b: 10 });
  assert.deepEqual(tuple(r1.before_break.b), [4, 22, 0, 0]);
  assert.deepEqual(tuple(r1.end.b), [4, 32, 0, 0]);
  assert.equal(r2.executed, 1);
  assert.equal(r2.beats.length, 1);
  assert.deepEqual(r2.plans[0].actions, jabs.actions, 'unexecuted intentions stay revealed');
  assert.deepEqual(fight.outcome, { winner: null, result: 'DOUBLE_KO' });
  assert.throws(() => E.replayFight(rules, [[jabs, jabs], [jabs, jabs], [jabs, jabs], [jabs, jabs]]));

  // opening and guard streak carry through the break; stamina gets +10 capped.
  // (opening=1 with guard_streak=3 cannot arise from one beat, so the section 8
  // vector is checked on the break itself.)
  assert.deepEqual(E.breakRecovery(rules, fresh({ stamina: 55, opening: 1, guard_streak: 3 })),
    fresh({ stamina: 60, opening: 1, guard_streak: 3 }));
  const end = E.resolveRound(rules, { round_index: 0, a: fresh(), b: fresh() },
    plan([RECOVER, RECOVER, RECOVER, RECOVER, RECOVER, DUCK]), plan([RECOVER, RECOVER, RECOVER, RECOVER, RECOVER, JAB]));
  assert.deepEqual(tuple(end.before_break.a), [100, 58, 1, 0]);
  assert.deepEqual(tuple(end.end.a), [100, 60, 1, 0]);
  assert.deepEqual(end.break_recovery, { a: 2, b: 4 });

  // power slot after a KO is never executed and costs nothing
  const ko = E.resolveRound(rules, { round_index: 1, a: fresh({ hp: 8 }), b: fresh() },
    plan([BLOCK, BLOCK, BLOCK, BLOCK, BLOCK, BLOCK]), plan([THROW, JAB, JAB, JAB, KICK, JAB], 4));
  assert.equal(ko.executed, 1);
  assert.equal(ko.end.b.power_available, 1);
  assert.deepEqual(ko.outcome, { winner: 'B', result: 'KO' });
});

test('rejects impossible states and plans instead of clamping', () => {
  const ok = { round_index: 0, a: fresh(), b: fresh() };
  const p = plan([JAB, JAB, JAB, JAB, JAB, JAB]);
  const bad = [
    () => E.resolveRound(rules, { round_index: 0, a: fresh({ hp: 101 }), b: fresh() }, p, p),
    () => E.resolveRound(rules, { round_index: 0, a: fresh({ stamina: 61 }), b: fresh() }, p, p),
    () => E.resolveRound(rules, { round_index: 0, a: fresh({ opening: 2 }), b: fresh() }, p, p),
    () => E.resolveRound(rules, { round_index: 0, a: fresh({ guard_streak: 4 }), b: fresh() }, p, p),
    () => E.resolveRound(rules, { round_index: 0, a: fresh({ hp: 1.5 }), b: fresh() }, p, p),
    () => E.resolveRound(rules, { round_index: 0, a: fresh({ hp: 0 }), b: fresh() }, p, p),
    () => E.resolveRound(rules, { round_index: 3, a: fresh(), b: fresh() }, p, p),
    () => E.resolveRound(rules, ok, plan([JAB, JAB, JAB, JAB, JAB]), p),
    () => E.resolveRound(rules, ok, plan([JAB, JAB, JAB, JAB, JAB, JAB, JAB]), p),
    () => E.resolveRound(rules, ok, plan([JAB, JAB, JAB, JAB, JAB, EXHAUSTED]), p),
    () => E.resolveRound(rules, ok, plan([JAB, JAB, JAB, JAB, JAB, BLOCK], 5), p),
    () => E.resolveRound(rules, ok, plan([JAB, JAB, JAB, JAB, JAB, JAB], 6), p),
    () => E.resolveRound(rules, { round_index: 0, a: fresh({ power_available: 0 }), b: fresh() }, plan([JAB, JAB, JAB, JAB, JAB, JAB], 0), p),
    () => E.decodeState('640000000000000001'),
    () => E.decodeState('6400000000000001'),
    () => E.decodeState('6500000000000100', rules),
    () => E.decodePlan('00000000000006'),
    () => E.decodePlan('00000000000007'),
    () => E.decodePlan('060000000000ff'),
  ];
  bad.forEach((f, i) => assert.throws(f, /combat:/, 'case ' + i));
});

test('codecs round-trip', () => {
  const s = fresh({ hp: 300 & 0xff, stamina: 17, opening: 1, guard_streak: 2, power_available: 0 });
  assert.equal(E.encodeState(fresh()), '64003c0000000100');
  assert.deepEqual(E.decodeState(E.encodeState(s)), s);
  assert.equal(E.encodePlan(plan([0, 3, 1, 5, 2, 4], 2)), '00030105020402');
  assert.equal(E.encodePlan(plan([0, 3, 1, 5, 2, 4])), '000301050204ff');
  assert.deepEqual(E.decodePlan('000301050204ff'), plan([0, 3, 1, 5, 2, 4]));
});

// ---- frozen full-fight fixtures ------------------------------------------

const fixtureFiles = fs.readdirSync(FIXDIR).filter(n => /^fights-[0-9a-f]+\.json$/.test(n));
// One parity set per packaged ruleset; each replays under its own numbers.
const RULESETS = ['docs/combat-v1.json', 'docs/combat-v1-candidate-2.json']
  .map(p => JSON.parse(fs.readFileSync(path.join(ROOT, p), 'utf8')));
const rulesFor = doc => {
  const r = RULESETS.find(x => x.semantic_version === doc.semantic_version);
  assert.ok(r, 'fixture ruleset ' + doc.semantic_version + ' is packaged');
  return r;
};

function sideDetail(t) {
  return {
    after: E.encodeState(t.after), effective: t.effective, cost_paid: t.cost_paid, base: t.base_damage,
    dealt: t.computed_damage, lost: t.actual_hp_lost, strain: t.strain, recovered: t.recovered, reasons: t.reasons,
  };
}

for (const name of fixtureFiles) {
  test(`replays every fight in ${name} with zero mismatches`, () => {
    const doc = JSON.parse(fs.readFileSync(path.join(FIXDIR, name), 'utf8'));
    const rules = rulesFor(doc);
    assert.deepEqual(doc.action_ids, Object.fromEntries(rules.action_names.map((n, i) => [n, i])));
    assert.ok(doc.fights.length >= 10000, 'at least 10,000 frozen fights');
    const mismatches = [];
    let beats = 0, tracedBeats = 0;
    doc.fights.forEach((fx, i) => {
      const fight = E.replayFight(rules, fx.rounds.map(r => [r[0], r[1]]));
      fx.rounds.forEach((rx, ri) => {
        const rr = fight.rounds[ri];
        beats += rr.executed;
        if (E.encodePlan(rr.plans[0]) !== rx[0] || E.encodePlan(rr.plans[1]) !== rx[1]) mismatches.push([i, ri, 'plan']);
        if (rr.executed !== rx[2]) mismatches.push([i, ri, 'executed', rr.executed, rx[2]]);
        const end = E.encodeState(rr.end.a) + E.encodeState(rr.end.b);
        if (end !== rx[3]) mismatches.push([i, ri, 'end', end, rx[3]]);
        if (i < doc.traced.length) {
          const want = doc.traced[i][ri];
          if (want.length !== rr.beats.length) mismatches.push([i, ri, 'traced beats']);
          want.forEach((pair, bi) => {
            const b = rr.beats[bi];
            if (!b) return;
            tracedBeats++;
            [b.a, b.b].forEach((t, s) => {
              const got = sideDetail(t);
              for (const k of Object.keys(pair[s])) {
                if (JSON.stringify(got[k]) !== JSON.stringify(pair[s][k])) mismatches.push([i, ri, bi, 'AB'[s], k, got[k], pair[s][k]]);
              }
            });
          });
        }
      });
      const outcome = fight.outcome ? [fight.outcome.winner, fight.outcome.result] : null;
      if (JSON.stringify(outcome) !== JSON.stringify(fx.outcome)) mismatches.push([i, 'outcome', outcome, fx.outcome]);
    });
    assert.deepEqual(mismatches.slice(0, 10), [], `${mismatches.length} mismatches`);
    assert.ok(tracedBeats > 1000 && beats > 100000, `checked ${beats} beats, ${tracedBeats} in detail`);
  });

  test(`slot symmetry on a sample of ${name}`, () => {
    const doc = JSON.parse(fs.readFileSync(path.join(FIXDIR, name), 'utf8'));
    const rules = rulesFor(doc);
    const swapWinner = { A: 'B', B: 'A' };
    for (let i = 0; i < doc.fights.length; i += 25) {
      const rounds = doc.fights[i].rounds;
      const ab = E.replayFight(rules, rounds.map(r => [r[0], r[1]]));
      const ba = E.replayFight(rules, rounds.map(r => [r[1], r[0]]));
      assert.deepEqual(ba.outcome, { winner: ab.outcome.winner && swapWinner[ab.outcome.winner], result: ab.outcome.result });
      ab.rounds.forEach((r, ri) => {
        const q = ba.rounds[ri];
        assert.deepEqual(q.end.a, r.end.b);
        assert.deepEqual(q.end.b, r.end.a);
        r.beats.forEach((bt, bi) => {
          assert.deepEqual(q.beats[bi].a, bt.b, `fight ${i} round ${ri} beat ${bi}`);
          assert.deepEqual(q.beats[bi].b, bt.a);
        });
      });
    }
  });
}

test('there is one fixture file per packaged ruleset', () => {
  const versions = fixtureFiles.map(n => JSON.parse(fs.readFileSync(path.join(FIXDIR, n), 'utf8')).semantic_version).sort();
  assert.deepEqual(versions, RULESETS.map(r => r.semantic_version).sort());
});

test('candidate 2 hand vectors (docs/combat.md "Candidate 2")', () => {
  const c2 = RULESETS[1];
  const f2 = (over = {}) => Object.assign({ hp: 120, stamina: 48, opening: 0, guard_streak: 0, power_available: 1 }, over);
  const b2 = (a, b, ia, ib, pa = false, pb = false) => E.resolveBeat(c2, a, b, ia, ib, pa, pb);
  const rows = [
    [JAB, BLOCK, [120, 44, 0, 0], [120, 46, 0, 1]],
    [JAB, KICK, [116, 44, 0, 0], [110, 38, 0, 0]],
    [DUCK, JAB, [120, 46, 1, 0], [116, 44, 0, 0]],
    [KICK, DUCK, [120, 38, 0, 0], [102, 46, 0, 0]],
    [THROW, BLOCK, [120, 41, 0, 0], [100, 46, 0, 1]],
    [BLOCK, KICK, [120, 40, 0, 1], [120, 38, 0, 0]],
    [RECOVER, JAB, [108, 48, 0, 0], [120, 44, 1, 0]],
    [THROW, THROW, [120, 41, 0, 0], [120, 41, 0, 0]],
  ];
  for (const [ia, ib, ea, eb] of rows) {
    const t = b2(f2(), f2(), ia, ib);
    assert.deepEqual([tuple(t.a), tuple(t.b)], [ea, eb], `${ia}/${ib}`);
  }
  const t1 = b2(f2(), f2(), DUCK, JAB);
  assert.deepEqual(t1.trace[0].reasons, ['HIT', 'OPENING_EARNED']);   // the duck counter
  assert.deepEqual(t1.trace[1].reasons, ['EVADED']);
  const t2 = b2(t1.a, t1.b, KICK, JAB);
  assert.deepEqual([tuple(t2.a), tuple(t2.b)], [[110, 36, 0, 0], [104, 40, 0, 0]]);
  const pk = b2(f2({ opening: 1 }), f2(), KICK, DUCK, true, false);
  assert.equal(pk.trace[1].actual_hp_lost, 38);
  assert.equal(pk.a.stamina, 34);
  assert.throws(() => b2(f2(), f2(), DUCK, JAB, true, false), /attack/);   // no power on a duck
});
