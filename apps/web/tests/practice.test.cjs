// Practice support (combat/practice.js): shared replay links reproduce the
// completed fight and refuse anything else, the debrief only reports what the
// traces show, and the local record survives bad data and counts once.
// No dependencies: node --test apps/web/tests/practice.test.cjs
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

require('../combat/ruleset.js');
const RS = globalThis.QDojoRulesets;
const C3 = RS.find(r => r.semantic_version === 'combat-v1-candidate-3');
const L = require('../combat/logic.js');
const P = require('../combat/practice.js');
const SHA = L.defaultSha256();
const SAMPLE = path.join(__dirname, '..', 'data/combat/v1/sample');
const SEED = 'ab'.repeat(32);

const play = (rules, npc, plans, seed = SEED) => {
  const s = L.practiceStart(rules, npc, seed, 1);
  for (const p of plans) { if (s.outcome) break; L.practicePlay(rules, s, p); }
  return s;
};
const KO_PLANS = [{ actions: [3, 3, 3, 1, 3, 3], power_slot: 3 }, { actions: [3, 3, 1, 1, 3, 5], power_slot: -1 }, { actions: [3, 3, 3, 1, 3, 3], power_slot: -1 }];
const FULL_PLANS = [{ actions: [2, 2, 5, 2, 3, 5], power_slot: -1 }, { actions: [2, 3, 5, 2, 3, 5], power_slot: -1 }, { actions: [2, 2, 5, 3, 3, 5], power_slot: -1 }];
const rulesets = () => Promise.all(RS.map(async rules => ({ rules, digest: await L.rulesetDigest(rules, SHA) })));

test('a share link re-derives the same completed fight, including a knockout before round 3', async () => {
  const list = await rulesets(), d3 = list.find(x => x.rules === C3).digest;
  for (const [npc, plans] of [['jabber-v1', KO_PLANS], ['scout-v1', FULL_PLANS], ['turtle-v1', FULL_PLANS], ['random-v1', KO_PLANS]]) {
    const s = play(C3, npc, plans);
    assert.ok(s.outcome, npc + ' finished');
    const code = await P.shareCode(s, d3, SHA);
    assert.ok(code.length <= 64, 'compact: ' + code);
    const parsed = P.parseShare(npc, SEED, code);
    assert.ok(parsed.ok, parsed.error);
    const rep = await P.replayShare(parsed, list, SHA);
    assert.ok(rep.ok && rep.match, npc + ': ' + rep.error);
    assert.equal(rep.rules, C3);
    assert.deepEqual(rep.s.outcome, s.outcome);
    assert.deepEqual(rep.s.rounds.map(r => r.result.beats), s.rounds.map(r => r.result.beats));
  }
  const ko = play(C3, 'jabber-v1', KO_PLANS);
  assert.ok(ko.rounds.length < 3 && ko.outcome.result === 'KO', 'the KO fixture ends early');
});

test('a share link names its ruleset: an older ruleset replays under its own rules, an unknown one is refused', async () => {
  const list = await rulesets();
  const c1 = list.find(x => x.rules.semantic_version === 'combat-v1-candidate-1');
  const s = play(c1.rules, 'jabber-v1', FULL_PLANS);
  const rep = await P.replayShare(P.parseShare('jabber-v1', SEED, await P.shareCode(s, c1.digest, SHA)), list, SHA);
  assert.ok(rep.ok && rep.match);
  assert.equal(rep.rules, c1.rules, 'not reinterpreted under the active ruleset');
  const unknown = (await P.shareCode(s, c1.digest, SHA)).replace(/^p1\.1\.[0-9a-f]{16}/, 'p1.1.' + '0'.repeat(16));
  const r2 = await P.replayShare(P.parseShare('jabber-v1', SEED, unknown), list, SHA);
  assert.equal(r2.ok, false);
  assert.match(r2.error, /does not carry/);
});

test('a tampered check value replays the plans but reports a mismatch; a changed plan changes the check', async () => {
  const list = await rulesets(), d3 = list.find(x => x.rules === C3).digest;
  const s = play(C3, 'scout-v1', FULL_PLANS);
  const code = await P.shareCode(s, d3, SHA);
  const t1 = await P.replayShare(P.parseShare('scout-v1', SEED, code.replace(/[0-9a-f]{8}$/, '00000000')), list, SHA);
  assert.ok(t1.ok && !t1.match);
  // a different, still legal, round 3 plan: the derived fight differs, so the old check fails
  const alt = code.replace(/-([0-8]{6})n\./, '-222222n.');
  const t2 = await P.replayShare(P.parseShare('scout-v1', SEED, alt), list, SHA);
  if (t2.ok) assert.equal(t2.match, false);
});

test('malformed, oversized, unfinished and over-long links are refused with a reason', async () => {
  const list = await rulesets(), d3 = list.find(x => x.rules === C3).digest;
  const bad = (npc, seed, tail, re) => { const p = P.parseShare(npc, seed, tail); assert.equal(p.ok, false, tail); assert.match(p.error, re); };
  bad('jabber-v1', SEED, 'p9.1.' + d3.slice(0, 16) + '.0000000.00000000', /format/);
  bad('jabber-v1', SEED, 'p1.' + 'x'.repeat(200), /too long/);
  bad('nobody-v1', SEED, 'p1.1.' + d3.slice(0, 16) + '.000000n.00000000', /Unknown practice opponent/);
  bad('jabber-v1', 'zz', 'p1.1.' + d3.slice(0, 16) + '.000000n.00000000', /seed/);
  bad('jabber-v1', SEED, 'p1.1.' + d3.slice(0, 16) + '.0000009.00000000', /six moves/);
  bad('jabber-v1', SEED, 'p1.1.' + d3.slice(0, 16) + '.000000n-000000n-000000n-000000n.00000000', /one to three/);
  bad('jabber-v1', SEED, 'p1.0.' + d3.slice(0, 16) + '.000000n.00000000', /fight number/);
  // syntactically fine but not a finished fight / not legal / rounds after a KO
  const one = await P.replayShare(P.parseShare('turtle-v1', SEED, 'p1.1.' + d3.slice(0, 16) + '.222222n.00000000'), list, SHA);
  assert.equal(one.ok, false); assert.match(one.error, /unfinished/);
  const illegal = await P.replayShare(P.parseShare('turtle-v1', SEED, 'p1.1.' + d3.slice(0, 16) + '.2222220.00000000'), list, SHA);
  assert.equal(illegal.ok, false); assert.match(illegal.error, /not a legal fight/);
  const ko = play(C3, 'jabber-v1', KO_PLANS);
  const extra = (await P.shareCode(ko, d3, SHA)).replace(/\.([0-9a-f]{8})$/, '-222222n.$1');
  const ex = await P.replayShare(P.parseShare('jabber-v1', SEED, extra), list, SHA);
  assert.equal(ex.ok, false); assert.match(ex.error, /already over/);
  await assert.rejects(P.shareCode(L.practiceStart(C3, 'jabber-v1', SEED, 1), d3, SHA));
});

test('the debrief is counted from the traces: key beats, causes, habits, hindsight and a tip', () => {
  const s = play(C3, 'jabber-v1', KO_PLANS);
  const d = P.debrief(s.rounds, s.outcome, { rules: C3, mySide: 'A', names: { A: 'YOU', B: 'JABBER' } });
  const beats = s.rounds.flatMap(r => r.result.beats);
  assert.equal(d.played, beats.length);
  assert.ok(d.key.length >= 1 && d.key.length <= 4);
  assert.ok(d.key.some(k => k.finish), 'the knockout beat is a key beat');
  for (const k of d.key) {
    const b = s.rounds.find(r => r.round_index === k.round).result.beats[k.beat];
    assert.equal(k.swing, b.b.actual_hp_lost - b.a.actual_hp_lost, 'swing from the trace');
  }
  const h = d.habits[0];
  assert.equal(h.total, beats.length);
  assert.equal(h.top.reduce((n, t) => n + t.n, 0), beats.length, 'habits count only executed beats');
  assert.ok(d.tip && d.tip.text);
  if (d.better) {
    // the hindsight plan, replayed by the engine against the recorded NPC plan, gives exactly the stated numbers
    const r = s.rounds.find(x => x.round_index === d.better.round);
    const E = require('../combat/engine.js');
    const res = E.resolveRound(C3, r.start, d.better.plan, r.plans.B);
    assert.equal(res.beats.reduce((n, b) => n + b.b.actual_hp_lost, 0), d.better.dealt);
    assert.equal(res.beats.reduce((n, b) => n + b.a.actual_hp_lost, 0), d.better.taken);
    assert.ok(d.better.dealt - d.better.taken > d.better.actualDealt - d.better.actualTaken);
  }
});

test('debrief on every sample replay: forfeits are flagged, nothing comes from unplayed beats', () => {
  const R1 = RS[0];
  const index = JSON.parse(fs.readFileSync(path.join(SAMPLE, 'index.json'), 'utf8'));
  let n = 0, forfeits = 0;
  for (const id of index.fights) {
    const f = path.join(SAMPLE, 'fights', String(id), 'replay.json');
    if (!fs.existsSync(f)) continue;
    const rp = JSON.parse(fs.readFileSync(f, 'utf8'));
    const der = L.deriveReplay(R1, rp);
    if (der.error) continue;
    const ff = L.isForfeit(rp);
    const d = P.debrief(der.rounds, der.outcome, { rules: R1, mySide: null, names: { A: 'A', B: 'B' }, forfeit: ff ? L.outcomeLabel(rp).text : null });
    const played = der.rounds.reduce((k, r) => k + r.result.beats.length, 0);
    assert.equal(d.played, played);
    if (!played) assert.equal(d.key.length, 0, 'no key beat invented for an unplayed fight');
    for (const k of d.key) assert.ok(der.rounds.find(r => r.round_index === k.round).result.beats[k.beat], 'key beat was executed');
    if (ff) { forfeits++; assert.ok(d.forfeit); }
    if (played) assert.ok(d.practice && d.practice.npc); else assert.equal(d.practice, null, 'no practice advice from an unplayed fight');
    n++;
  }
  assert.ok(n > 5, 'replays checked: ' + n + ' (forfeits ' + forfeits + ')');
});

test('the record: once per fight, per ruleset, ladder order, best result, bad data and versions', () => {
  const p = P.emptyProgress();
  assert.equal(P.nextChallenge(p, C3.semantic_version).npc, 'jabber-v1');
  const s = play(C3, 'jabber-v1', KO_PLANS);
  const r1 = P.recordResult(p, s, 'k1');
  assert.ok(r1.added && r1.rec.w === 1 && r1.milestone && r1.milestone.npc === 'jabber-v1');
  assert.match(r1.rec.best.label, /^WIN · KO R\d$/);
  const r2 = P.recordResult(p, s, 'k1');
  assert.equal(r2.added, false); assert.equal(r2.rec.w, 1, 'recorded once');
  assert.equal(P.nextChallenge(p, C3.semantic_version).npc, 'kicker-v1');
  // another ruleset is kept apart and does not complete the C3 ladder
  const s1 = play(RS[0], 'kicker-v1', FULL_PLANS);
  P.recordResult(p, s1, 'k2');
  assert.equal(P.nextChallenge(p, C3.semantic_version).npc, 'kicker-v1');
  assert.deepEqual(P.otherRulesets(p, C3.semantic_version).map(x => x.rules), ['combat-v1-candidate-1']);
  // round trip, and bad data
  const back = P.parseProgress(JSON.stringify(p));
  assert.equal(back.damaged, false);
  assert.deepEqual(back.p.rules, p.rules);
  for (const junk of ['{bad', '[]', '{"v":0,"rules":{},"seen":[]}', 'null']) assert.equal(P.parseProgress(junk).damaged, true, junk);
  assert.equal(P.parseProgress(null).damaged, false);
  const odd = P.parseProgress(JSON.stringify({ v: 1, rules: { 'combat-v1-candidate-3': { 'jabber-v1': { w: -1, l: 0, d: 0 }, 'nobody': { w: 1, l: 0, d: 0 } } }, seen: [1, 'ok'] }));
  assert.deepEqual(odd.p.rules, {}); assert.deepEqual(odd.p.seen, ['ok']);
});

test('wasted power on a move that became EXHAUSTED is not blamed on the opponent', () => {
  const RECOVER = { actions: [5, 5, 5, 5, 5, 5], power_slot: -1 };
  for (const rules of RS) {
    // KICK on every beat, the power strike on the sixth: by then the kick is unaffordable.
    const s = play(rules, 'turtle-v1', [{ actions: [1, 1, 1, 1, 1, 1], power_slot: 5 }, RECOVER, RECOVER]);
    const t = s.rounds[0].result.beats[5].a;
    assert.ok(t.effective === L.ID.EXHAUSTED && t.reasons.includes('POWER_WASTED'), rules.semantic_version + ': the sixth kick is EXHAUSTED with its power wasted');
    const mine = P.debrief(s.rounds, s.outcome, { rules, mySide: 'A', names: { A: 'YOU', B: 'TURTLE' } }).causes.find(c => c.kind === 'power');
    assert.match(mine.text, /^You spent the power strike on an unaffordable KICK \(R1 B6\): the move became EXHAUSTED and was never made/, rules.semantic_version);
    assert.doesNotMatch(mine.text, /stopped/, rules.semantic_version);
    const replay = P.debrief(s.rounds, s.outcome, { rules, mySide: null, names: { A: 'ALPHA', B: 'TURTLE' } }).causes.find(c => c.kind === 'power' && c.side === 'A');
    assert.match(replay.text, /^ALPHA spent the power strike on an unaffordable KICK \(R1 B6\)/, rules.semantic_version);
    // A strike the opponent did stop still says so: a powered JAB into TURTLE's opening BLOCK.
    const blocked = play(rules, 'turtle-v1', [{ actions: [0, 3, 3, 3, 3, 3], power_slot: 0 }, RECOVER, RECOVER]);
    const stopped = P.debrief(blocked.rounds, blocked.outcome, { rules, mySide: 'A', names: { A: 'YOU', B: 'TURTLE' } }).causes.find(c => c.kind === 'power');
    assert.match(stopped.text, /^You spent the power strike on a JAB that the BLOCK stopped \(R1 B1\)/, rules.semantic_version);
  }
});

test('a replay a missed deadline stopped suggests practice for the side behind on HP, not corner A', () => {
  const E = require('../combat/engine.js');
  const roundsOf = (rules, plans) => {
    let state = E.newFight(rules);
    return plans.map(([A, B]) => { const res = E.resolveRound(rules, state, A, B); const r = { round_index: state.round_index, start: state, plans: { A, B }, result: res }; state = res.end; return r; });
  };
  const plan = actions => ({ actions, power_slot: -1 });
  const names = { A: 'ALPHA', B: 'BRAVO' };
  for (const rules of RS) {
    // Both sides are caught recovering; A is far ahead on HP when the deadline stops the fight.
    const ahead = roundsOf(rules, [[plan([0, 5, 0, 0, 0, 0]), plan([5, 0, 5, 5, 5, 5])]]);
    const end = ahead[0].result.end;
    assert.ok(end.a.hp > end.b.hp, rules.semantic_version + ': A ahead');
    const d = P.debrief(ahead, null, { rules, mySide: null, names, forfeit: 'TIMEOUT' });
    assert.deepEqual(d.causes.filter(c => c.kind === 'punished').map(c => c.side), ['A', 'B'], 'both sides have the habit, A listed first');
    assert.equal(d.practice.why, 'rehearse what BRAVO struggled with: punished', rules.semantic_version);
    // A decided fight still follows its loser; with level HP, both sides.
    assert.equal(P.debrief(ahead, { result: 'KO', winner: 'B' }, { rules, mySide: null, names }).practice.why, 'rehearse what ALPHA struggled with: punished');
    const level = roundsOf(rules, [[plan([0, 5, 2, 2, 2, 2]), plan([5, 0, 2, 2, 2, 2])]]);
    assert.equal(level[0].result.end.a.hp, level[0].result.end.b.hp);
    assert.equal(P.debrief(level, null, { rules, mySide: null, names, forfeit: 'TIMEOUT' }).practice.why, 'rehearse what ALPHA struggled with: punished');
  }
});

test('a stored ruleset named like an Object member stays an ordinary record', () => {
  try {
    const r = P.parseProgress(JSON.stringify({ v: 1, rules: { constructor: { 'jabber-v1': { w: 1, l: 0, d: 0 } } }, seen: [] }));
    assert.equal(r.damaged, false);
    assert.equal(Object['jabber-v1'], undefined, 'nothing is written onto Object');
    assert.deepEqual(r.p.rules.constructor, { 'jabber-v1': { w: 1, l: 0, d: 0, best: null } });
    assert.deepEqual(JSON.parse(JSON.stringify(r.p)).rules, { constructor: { 'jabber-v1': { w: 1, l: 0, d: 0, best: null } } }, 'kept by the next save');
    assert.deepEqual(P.otherRulesets(r.p, C3.semantic_version), [{ rules: 'constructor', fights: 1 }]);
    // A result recorded under such a name lands in its own record as well.
    const p = P.emptyProgress();
    P.recordResult(p, Object.assign(play(C3, 'kicker-v1', FULL_PLANS), { rules_version: 'constructor' }), 'k1');
    assert.equal(Object['kicker-v1'], undefined);
    assert.equal(Object.keys(p.rules.constructor).join(), 'kicker-v1');
  } finally {
    delete Object['jabber-v1']; delete Object['kicker-v1'];
  }
});
