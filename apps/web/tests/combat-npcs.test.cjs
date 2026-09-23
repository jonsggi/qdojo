// The browser NPC roster against every frozen Python fixture, and its
// synchronous SHA-256 against node:crypto.
// No dependencies: node --test apps/web/tests/combat-npcs.test.cjs
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { createContext, runInContext } = require('node:vm');

const ROOT = path.join(__dirname, '../../..');
const E = require('../combat/engine.js');
const N = require('../combat/npcs.js');
const rules = JSON.parse(fs.readFileSync(path.join(ROOT, 'docs/combat-v1.json'), 'utf8'));
const FIX = JSON.parse(fs.readFileSync(path.join(ROOT, 'packages/qdojo/tests/combat/fixtures/npcs-v1.json'), 'utf8'));

test('sha256 matches node:crypto on lengths around every block boundary', () => {
  for (let len = 0; len < 200; len++) {
    const buf = Buffer.alloc(len);
    for (let i = 0; i < len; i++) buf[i] = (i * 131 + len) & 255;
    assert.equal(N.toHex(N.sha256(buf)), crypto.createHash('sha256').update(buf).digest('hex'), 'length ' + len);
  }
  assert.equal(N.toHex(N.sha256([])), 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855');
});

test('uniform draws reject biased bytes and weighted uses cumulative buckets', () => {
  const s = N.Stream('00'.repeat(32), 1, 0);
  for (let i = 0; i < 200; i++) { const v = s.uniform(6); assert.ok(v >= 0 && v < 6); }
  const w = N.Stream('11'.repeat(32), 7, 2);
  for (let i = 0; i < 200; i++) assert.notEqual(w.weighted([1, 0, 2, 2, 0, 5]), 1);
  assert.throws(() => N.Stream('00', 1, 0));
});

test('fixture ruleset is the one the page embeds', () => {
  assert.equal(FIX.ruleset_digest, '12085c86a61ffd106430b6690acbd522c5a94f90ed8024585817f4939fe4842c');
});

test('every npcs-v1 fixture case reproduces exactly', () => {
  const mismatches = [];
  const perNpc = {};
  for (const c of FIX.cases) {
    const obs = {
      round_index: c.round,
      self: E.decodeState(c.self, rules),
      opponent: E.decodeState(c.opponent, rules),
      opponent_history: c.opponent_history,
    };
    const plan = N.planFor(c.npc, rules, obs, c.seed, c.fight);
    const got = E.encodePlan(plan);
    perNpc[c.npc] = (perNpc[c.npc] || 0) + 1;
    if (got !== c.plan) mismatches.push(`${c.npc} seed=${c.seed.slice(0, 8)} fight=${c.fight} round=${c.round}: ${got} != ${c.plan}`);
  }
  assert.deepEqual(mismatches.slice(0, 10), [], `${mismatches.length} of ${FIX.cases.length} cases differ`);
  assert.equal(mismatches.length, 0);
  assert.deepEqual(Object.keys(perNpc).sort(), N.ROSTER.map(n => n.id).sort(), 'every roster NPC has fixtures');
  assert.equal(FIX.cases.length, 900);
});

test('loads as a plain browser script after engine.js', () => {
  const ctx = createContext({});
  runInContext(fs.readFileSync(path.join(__dirname, '../combat/engine.js'), 'utf8'), ctx);
  runInContext(fs.readFileSync(path.join(__dirname, '../combat/npcs.js'), 'utf8'), ctx);
  const api = runInContext('QDojoNpcs', ctx);
  assert.equal(api.ROSTER.length, 6);
  const plan = api.planFor('jabber-v1', rules, { round_index: 2, self: E.newFight(rules).a, opponent: E.newFight(rules).b, opponent_history: [] }, '00'.repeat(32), 1);
  assert.deepEqual([...plan.actions], [0, 0, 0, 5, 0, 0]);
  assert.equal(plan.power_slot, 0);
});
