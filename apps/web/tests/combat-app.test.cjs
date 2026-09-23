// Spectator logic for combat.html against the sample export: every fight is
// re-derived from its revealed plans, tampering is caught by the right check,
// forfeits read as timeouts, and no level claims more than its evidence.
// No dependencies: node --test apps/web/tests/combat-app.test.cjs
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '../../..');
const WEB = path.join(__dirname, '..');
const SAMPLE = path.join(WEB, 'data/combat/v1/sample');
const L = require('../combat/logic.js');
const R = require('../combat/ruleset.js');
const N = require('../combat/npcs.js');

const readJson = p => JSON.parse(fs.readFileSync(p, 'utf8'));
const manifest = readJson(path.join(SAMPLE, 'manifest.json'));
const index = readJson(path.join(SAMPLE, 'index.json'));
const replayOf = id => readJson(path.join(SAMPLE, 'fights', String(id), 'replay.json'));
const clone = x => JSON.parse(JSON.stringify(x));
const statusOf = (v, id) => v.checks.find(c => c.id === id).status;
const verify = (rp, man = manifest) => L.verifyReplay(rp, { rules: R, manifest: man });
const fullFight = () => index.fights.map(replayOf).find(rp => rp.rounds.length === 3 && !L.isForfeit(rp));
const koMidRound = () => index.fights.map(replayOf).find(rp => rp.rounds.some(r => r.unexecuted.A.length > 0));

test('embedded ruleset equals docs/combat-v1.json and hashes to the manifest digest', async () => {
  const docs = readJson(path.join(ROOT, 'docs/combat-v1.json'));
  assert.deepEqual(clone(R), docs);
  const d = await L.rulesetDigest(R, L.defaultSha256());
  assert.equal(d, '12085c86a61ffd106430b6690acbd522c5a94f90ed8024585817f4939fe4842c');
  assert.equal(d, manifest.ruleset_digest);
  // the synchronous fallback agrees with crypto.subtle
  assert.equal(await L.rulesetDigest(R, async b => N.toHex(N.sha256(b))), d);
});

test('protocol commitment fixture: context, round state and commitment preimage', async () => {
  const fx = readJson(path.join(ROOT, 'docs/fixtures/commitment-v1.json'));
  const sha = L.defaultSha256();
  const ctx = L.parseContext(fx.context_bytes);
  assert.equal(await sha(L.concat([Buffer.from('qdojo/combat/context/v1\0'), L.fromHex(fx.context_bytes)])), fx.context_digest);
  const init = { hp: 100, stamina: 60, opening: 0, guard_streak: 0, power_available: 1 };
  const rsb = L.roundStateBytes(fx.context_digest, 0, init, init);
  assert.equal(L.toHex(rsb.subarray(22)), fx.round_state_bytes);
  assert.equal(await sha(rsb), fx.round_state_digest);
  const pre = L.commitmentPreimage({
    network_id: ctx.network_id, contract_id: ctx.contract_id, fight_id: ctx.fight_id, round_index: 0,
    context_digest: fx.context_digest, round_state_digest: fx.round_state_digest,
    fighter_id: ctx.participants.A.fighter_id, operator: ctx.participants.A.operator,
    auth_version: ctx.participants.A.auth_version, salt: fx.salt, plan_bytes: fx.plan_bytes,
  });
  assert.equal(L.toHex(pre), fx.commitment_preimage);
  assert.equal(await sha(pre), fx.commitment);
  assert.equal(ctx.fight_id, '42');
});

test('every sample fight re-derives exactly and reaches REPLAY_MATCH, never COMBAT_VERIFIED', async () => {
  let replayed = 0;
  for (const id of index.fights) {
    const rp = replayOf(id);
    const v = await verify(rp);
    assert.equal(statusOf(v, 'ruleset'), 'PASS', 'fight ' + id);
    assert.equal(statusOf(v, 'inputs'), 'UNAVAILABLE', 'fight ' + id + ': a same-source export cannot confirm inclusion');
    assert.notEqual(v.level, 'COMBAT_VERIFIED');
    assert.notEqual(v.level, 'FAILED', 'fight ' + id + ': ' + JSON.stringify(v.checks.filter(c => c.status === 'FAIL')));
    if (rp.rounds.length) {
      replayed++;
      assert.equal(statusOf(v, 'commitments'), 'PASS', 'fight ' + id);
      assert.equal(statusOf(v, 'replay'), 'PASS', 'fight ' + id);
      assert.equal(v.level, 'REPLAY_MATCH');
      assert.deepEqual(v.derived.outcome, L.isForfeit(rp) ? null : { winner: rp.outcome.winner, result: rp.outcome.result });
    }
  }
  assert.ok(replayed >= 20, 'sample has replayable fights');
});

test('a tampered salt fails only the commitment check', async () => {
  const rp = clone(fullFight());
  const s = rp.rounds[1].salts.B;
  rp.rounds[1].salts.B = (s[0] === '0' ? '1' : '0') + s.slice(1);
  const v = await verify(rp);
  assert.equal(statusOf(v, 'commitments'), 'FAIL');
  assert.equal(statusOf(v, 'replay'), 'PASS');
  assert.equal(v.level, 'FAILED');
  assert.ok(v.checks.find(c => c.id === 'commitments').details.some(d => d.startsWith('FAIL round 1 B')));
});

test('a tampered plan fails the commitment and the replay', async () => {
  const rp = clone(fullFight());
  const bytes = rp.rounds[0].plan_bytes.A;
  const first = parseInt(bytes.slice(0, 2), 16);
  rp.rounds[0].plan_bytes.A = '0' + ((first + 1) % 6) + bytes.slice(2);
  const v = await verify(rp);
  assert.equal(statusOf(v, 'commitments'), 'FAIL');
  assert.equal(statusOf(v, 'replay'), 'FAIL');
  assert.equal(v.level, 'FAILED');
});

test('a displayed plan that differs from the committed bytes is caught', async () => {
  const rp = clone(fullFight());
  rp.rounds[2].plans.B.actions[5] = rp.rounds[2].plans.B.actions[5] === 'JAB' ? 'KICK' : 'JAB';
  const v = await verify(rp);
  assert.equal(statusOf(v, 'commitments'), 'FAIL');
});

test('tampered traces, outcome or round-start state fail the replay check', async () => {
  const base = fullFight();
  let rp = clone(base);
  rp.rounds[0].beats[2].B.after.hp -= 1;
  assert.equal(statusOf(await verify(rp), 'replay'), 'FAIL');
  rp = clone(base);
  rp.outcome.winner = rp.outcome.winner === 'A' ? 'B' : 'A';
  assert.equal(statusOf(await verify(rp), 'replay'), 'FAIL');
  rp = clone(base);
  rp.rounds[1].start.A.stamina -= 1;
  assert.equal(statusOf(await verify(rp), 'replay'), 'FAIL');
  rp = clone(base);
  rp.rounds[1].round_state_digest = '00'.repeat(32);
  assert.equal(statusOf(await verify(rp), 'commitments'), 'FAIL');
});

test('a wrong manifest digest fails the ruleset check; a missing one is UNAVAILABLE', async () => {
  const rp = fullFight();
  const bad = Object.assign(clone(manifest), { ruleset_digest: 'ff'.repeat(32) });
  assert.equal(statusOf(await verify(rp, bad), 'ruleset'), 'FAIL');
  const none = await L.verifyReplay(rp, { rules: R, manifest: null });
  assert.equal(statusOf(none, 'ruleset'), 'UNAVAILABLE');
  assert.notEqual(none.level, 'COMBAT_VERIFIED');
});

test('an exporter claiming chain confirmation from the same source is still UNAVAILABLE', async () => {
  const rp = clone(fullFight());
  rp.evidence = { inputs_confirmed: 'PASS', source: 'same-source export' };
  const v = await verify(rp);
  assert.equal(statusOf(v, 'inputs'), 'UNAVAILABLE');
  assert.equal(v.level, 'REPLAY_MATCH');
  // Even if every check passed, the level follows the checks, not a label.
  assert.equal(L.levelOf(v.checks.map(c => Object.assign({}, c, { status: 'PASS' }))), 'COMBAT_VERIFIED');
  assert.equal(L.levelOf(v.checks.map(c => Object.assign({}, c, { status: c.id === 'accounting' ? 'UNAVAILABLE' : 'PASS' }))), 'REPLAY_MATCH');
});

test('forfeit fights render as a timeout with no invented beats', async () => {
  const forfeits = index.fights.map(replayOf).filter(L.isForfeit);
  assert.ok(forfeits.length >= 1);
  for (const rp of forfeits) {
    const label = L.outcomeLabel(rp);
    assert.equal(label.kind, 'timeout');
    assert.equal(label.short, 'TIMEOUT');
    assert.match(label.text, /Not a knockout/);
    assert.doesNotMatch(label.text, /K\.O\./);
    const d = L.deriveReplay(R, rp);
    const tl = L.timeline(rp, d);
    assert.equal(tl[tl.length - 1].kind, 'forfeit');
    assert.equal(tl.filter(f => f.kind === 'beat').length, rp.rounds.reduce((n, r) => n + r.executed_beats, 0));
    assert.ok(!tl.some(f => f.kind === 'end'), 'no KO frame for a forfeit');
    const v = await verify(rp);
    if (!rp.rounds.length) {
      assert.equal(statusOf(v, 'replay'), 'UNAVAILABLE');
      assert.equal(v.level, 'UNVERIFIED');
    }
  }
});

test('timeline states come from the engine and the post-KO suffix is labelled', () => {
  const rp = koMidRound();
  assert.ok(rp, 'sample has a KO before beat 5');
  const d = L.deriveReplay(R, rp);
  const tl = L.timeline(rp, d);
  const last = rp.rounds[rp.rounds.length - 1];
  const un = tl.filter(f => f.kind === 'unexecuted');
  assert.equal(un.length, last.unexecuted.A.length);
  assert.deepEqual(un.map(f => L.NAMES[f.intended.A]), last.unexecuted.A);
  assert.deepEqual(un.map(f => L.NAMES[f.intended.B]), last.unexecuted.B);
  assert.equal(tl[tl.length - 1].kind, 'end');
  // unexecuted frames hold the KO state: nothing changes after the knockout
  for (const f of un) assert.deepEqual(f.a, d.end.a);
  const beats = tl.filter(f => f.kind === 'beat');
  const published = rp.rounds.flatMap(r => r.beats);
  assert.equal(beats.length, published.length);
  beats.forEach((f, i) => { assert.equal(f.a.hp, published[i].A.after.hp); assert.equal(f.b.stamina, published[i].B.after.stamina); });
});

test('explanations show the numbers (combat.md section 9)', () => {
  const E = require('../combat/engine.js');
  const s = { hp: 100, stamina: 11, opening: 0, guard_streak: 0, power_available: 1 };
  const f = { hp: 100, stamina: 60, opening: 0, guard_streak: 0, power_available: 1 };
  const r = E.resolveBeat(R, s, f, 1, 0, false, false);
  const text = L.explainSide(r.trace[0], r.trace[1], 'You', 'NPC').join(' ');
  assert.match(text, /kick cost 12 with only 11 stamina left: EXHAUSTED, paid nothing and stood exposed, taking 12 from the jab/);
  // a block: zero HP damage, strain is a stamina effect
  const b = E.resolveBeat(R, f, f, 2, 1, false, false);
  const bt = L.explainSide(b.trace[0], b.trace[1], 'A', 'B').join(' ');
  assert.match(bt, /Guard strain: -6 stamina/);
  assert.equal(b.trace[0].actual_hp_lost, 0);
  // hindsight is labelled as hindsight
  const h = L.hindsight(R, { a: f, b: f }, 'A', { A: r.trace[1], B: r.trace[0] });
  assert.equal(h, null);
  const j = E.resolveBeat(R, f, f, 5, 0, false, false);
  const hs = L.hindsight(R, { a: f, b: f }, 'A', { A: j.trace[0], B: j.trace[1] });
  assert.match(hs.text, /^HINDSIGHT/);
  assert.match(hs.text, /Not proof/);
});

test('fighter stats count only executed play and agree with the ranked record', () => {
  for (const fid of index.fighters) {
    const f = readJson(path.join(SAMPLE, 'fighters', fid + '.json'));
    const items = f.fights.map(id => { const rp = replayOf(id); return { replay: rp, derived: L.deriveReplay(R, rp) }; });
    const s = L.fighterStats(fid, items);
    const executed = s.perRound.flat().reduce((a, b) => a + b, 0);
    assert.equal(executed, s.beats);
    const suffix = items.reduce((n, { replay }) => n + replay.rounds.reduce((m, r) => m + (replay.fighters.A.fighter_id === fid ? r.unexecuted.A : r.unexecuted.B).length, 0), 0);
    assert.equal(s.unexecuted.reduce((a, b) => a + b, 0), suffix);
    const ranked = s.results.ranked || { W: 0, L: 0, D: 0, FW: 0, FL: 0 };
    assert.deepEqual(ranked, f.record, fid.slice(0, 8) + ' ranked results match the contract record');
    assert.ok(s.opening.converted <= s.opening.held);
    assert.equal(s.power.landed + s.power.wasted, s.power.used);
  }
});

test('practice is reproducible from its seed and the NPC is sealed before the human picks', () => {
  const seed = 'ab'.repeat(32);
  const play = humanPlans => {
    const s = L.practiceStart(R, 'scout-v1', seed, 1);
    const npc = [];
    for (const p of humanPlans) { if (s.outcome) break; npc.push(s.npcPlan.actions.join('')); L.practicePlay(R, s, p); }
    return { s, npc };
  };
  const plans = [
    { actions: [0, 3, 1, 5, 2, 4], power_slot: -1 },
    { actions: [5, 5, 0, 0, 3, 1], power_slot: 2 },
    { actions: [1, 5, 1, 5, 0, 0], power_slot: -1 },
  ];
  const x = play(plans), y = play(plans);
  assert.deepEqual(x.npc, y.npc);
  assert.deepEqual(x.s.state, y.s.state);
  // round 0: same seed gives the same sealed NPC plan whatever the human then submits
  const z = play([{ actions: [2, 2, 2, 2, 2, 2], power_slot: -1 }]);
  assert.equal(z.npc[0], x.npc[0]);
  assert.throws(() => L.practiceStart(R, 'scout-v1', 'nothex', 1));
  assert.throws(() => L.practicePlay(R, L.practiceStart(R, 'jabber-v1', seed, 1), { actions: [2, 2, 2, 2, 2, 2], power_slot: 0 }));
});
