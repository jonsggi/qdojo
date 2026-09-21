// The results screen printed 5/10 · 3/10 · 2/10 OF THE POT from a constant,
// whatever the settlement beside it had paid (#11). These pin the labels to
// the settlement's own numbers across the three shapes the document has had:
// the one-pot cap era (rounds 89-118 in the export), the two pots of #10
// (no live round yet, so round 89 is re-settled here the way docs/api.md and
// packages/qdojo/tests/test_round.py say it would be today), and the dead
// heat of #18 (round 119's five-way tie, and podium ties built here).
// No dependencies or browser required: node --test apps/web/tests/shares.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const { createContext, runInContext } = require('node:vm');

const src = readFileSync(path.join(__dirname, '../app.js'), 'utf8');
const history = JSON.parse(readFileSync(path.join(__dirname, '../data/history.json'), 'utf8'));
const byId = new Map(history.rounds.map(r => [r.round_id, r]));

// Lift the derivation and the helpers it reads out of the browser file, the
// way when.test.cjs does; the link and avatar renderers are stubbed so the
// winners block can be rendered through the page's own code path.
const pick = re => { const m = src.match(re); assert.ok(m, `${re} not found in app.js`); return m[0]; };
const block = [
  pick(/const COUNTED = [^\n]*/), pick(/const PODIUM_WEIGHTS = [^\n]*/),
  pick(/function esc\([\s\S]*?\n\}/), pick(/function fmt\([\s\S]*?\n\}/),
  pick(/function shortId\([^\n]*/), pick(/function ordinal\([^\n]*/), pick(/function isVoid\([^\n]*/),
  pick(/function seedFor\([\s\S]*?\n\}/), pick(/function countedStakes\([\s\S]*?\n\}/), pick(/function seedUsed\([\s\S]*?\n\}/),
  pick(/function payoutModeLabel\([\s\S]*?\n\}/), pick(/function seatsText\([\s\S]*?\n\}/), pick(/function seatsOf\([\s\S]*?\n\}/),
  pick(/function nameOf\([\s\S]*?\n\}/), pick(/function displayName\([\s\S]*?\n\}/), pick(/function callout\([\s\S]*?\n\}/),
  pick(/\/\/ -+ shares\n[\s\S]*?function payoutRule\([\s\S]*?\n\}/),
].join('\n');
const ctx = createContext({
  S: { data: { names: new Map() } },
  fighterLink: (id, inner) => inner,
  avatarSVG: () => '',
  idLink: id => `<a class="id">${id.slice(0, 6)}</a>`,
  txLink: (tx, label) => label || tx,
});
const api = runInContext(block + '\n({ settlementPots, shareLabel, shareFraction, payoutCall, callout, winnersHTML, potsPanelHTML, payoutRule });', ctx);

// built in this realm: an array made inside the VM has another Array.prototype and fails deepEqual
const labels = r => [...api.settlementPots(r)].flatMap(pot => [...pot.winners].map(w => api.shareLabel(w, pot)));
const clone = o => JSON.parse(JSON.stringify(o));
const text = html => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();

// ---------------------------------------------------------------- the real export

test('round 118: three senseis capped at their stake are not 5/10 · 3/10 · 2/10', () => {
  const r = byId.get(118);
  const got = labels(r);
  assert.equal(got.length, 3);
  for (const l of got) assert.equal(l, '1,000 OF 56,700 · CAPPED AT STAKE · SURPLUS CARRIED');
  const c = api.callout(r);
  assert.equal(c.text, 'TRIPLE K.O.');
  assert.equal(c.sub, 'PODIUM · ALL 3 SENSEIS CAPPED AT STAKE · SURPLUS CARRIED · 3 SOLVED LATER, NO PAY');
  const html = api.winnersHTML(r, true);
  assert.doesNotMatch(html, /\d+\/10 OF THE POT/);
  assert.match(html, /\+500 QU.*BOND HELD.*500 QU/s);
});

test('round 119: five tied in the first tick split the pot equally', () => {
  const r = byId.get(119);
  const got = labels(r);
  assert.equal(got.length, 5);
  for (const l of got) assert.equal(l, '12,740 OF 63,700 · TIED 1ST, SPLIT 5 WAYS EQUALLY · 1/5 OF THE POT');
  const c = api.callout(r);
  assert.equal(c.text, '5x K.O.');
  assert.equal(c.sub, '5 TIED IN THE FIRST TICK · SPLIT EQUALLY');
});

test('round 101: a podium that really paid 5:3:2 keeps the nominal labels', () => {
  const r = byId.get(101);
  assert.deepEqual(labels(r), [
    '22,500 OF 45,000 · 5/10 OF THE POT',
    '13,500 OF 45,000 · 3/10 OF THE POT',
    '9,000 OF 45,000 · 2/10 OF THE POT',
  ]);
  assert.equal(api.callout(r).sub, 'PODIUM · FIRST THREE SPLIT 5:3:2 · 5 SOLVED LATER, NO PAY');
});

test('round 72: a capped sensei on the podium, its surplus paid to the at-belt winners', () => {
  const r = byId.get(72);
  assert.deepEqual(labels(r), [
    '18,940 OF 32,400 · 5/10 OF THE POT + SENSEI SURPLUS',
    '12,460 OF 32,400 · 3/10 OF THE POT + SENSEI SURPLUS',
    '1,000 OF 32,400 · CAPPED AT STAKE · SURPLUS TO THE AT-BELT WINNERS',
  ]);
  assert.match(api.callout(r).sub, /^PODIUM · 1 SENSEI CAPPED AT STAKE · SURPLUS TO THE AT-BELT WINNERS/);
});

test('same-tick capped senseis are not a dead heat in a document without pots (rounds 89, 107, 108)', () => {
  // Under the stake cap every sensei winner's gross is its own 1,000 stake, so
  // same tick and same gross both hold for same-tick capped senseis -- but a
  // document without `pots` never has a dead heat (#WEB-1): these settlements
  // ordered same-tick solvers by transaction, and a same-tick solver can even
  // be paid nothing while the podium goes to the others in tx order.
  for (const id of [89, 107, 108]) {
    const r = byId.get(id);
    assert.doesNotMatch(api.winnersHTML(r, true), /TIED/, `round ${id}`);
  }
});

test('a same tick before the tie rule is not a dead heat: the money says 5:3:2', () => {
  // Round 15's first two commits share a tick; they were ordered by transaction
  // and paid 7,500 / 4,500. The label follows the money.
  const r = byId.get(15);
  assert.deepEqual(labels(r), ['7,500 OF 15,000 · 5/10 OF THE POT', '4,500 OF 15,000 · 3/10 OF THE POT', '3,000 OF 15,000 · 2/10 OF THE POT']);
  assert.doesNotMatch(api.winnersHTML(r, true), /TIED/);
});

test('every settled round in the export gets a label that adds up to its own payouts', () => {
  for (const r of history.rounds) {
    const s = r.settlement;
    if (!s || s.void) continue;
    const pots = api.settlementPots(r);
    const gross = pots.flatMap(p => p.winners.map(w => w.gross)).reduce((a, b) => a + b, 0);
    const sent = s.payouts.filter(p => p.kind === 'win').reduce((a, p) => a + p.amount, 0);
    const held = (s.bonds_held || []).reduce((a, b) => a + b.amount, 0);
    assert.equal(gross, sent + held, `round ${r.round_id}: gross wins must be what was sent plus what was bonded`);
    for (const pot of pots) for (const w of pot.winners) {
      const l = api.shareLabel(w, pot);
      assert.match(l, new RegExp(`^${w.gross.toLocaleString('en-US')} OF `), `round ${r.round_id}: ${l}`);
      assert.ok(!/undefined|NaN/.test(l), `round ${r.round_id}: ${l}`);
    }
  }
});

// ---------------------------------------------------------------- two pots (#10)

// Round 89 as it would be settled today: the api.md example and test_round.py's
// numbers. Sensei pot 10,000 − 2,000 rake → 4,000 / 2,400 / 1,600 gross,
// 2,000 / 1,200 / 800 sent with the same held as bond; belt pot 13,200 carry +
// 4,000 matched + 4,000 stakes = 21,200 − 800 rake → 20,400. `belt` adds the
// two orange solvers the real round had, paid 5:3 of the belt pot;
// `senseiHeats` overrides the sensei podium's commit ticks and gross wins.
function round89(opts = {}) {
  const r = clone(byId.get(89));
  const s = r.settlement;
  const who = name => r.entries.find(e => e.name === name);
  const senseis = (opts.senseis || ['EVO-DS3', 'EVO-GEM2', 'EVO-DS']).map(who);
  const beltSolvers = opts.belt ? ['EVO-G31', 'GEM-AGENT'].map(who) : [];
  const heats = opts.senseiHeats || [[[0], 4000], [[1], 2400], [[2], 1600]];   // [[indexes], gross each]
  for (const e of r.entries) e.verdict = e.sensei ? 'solved' : 'wrong';
  const senseiPayouts = [];
  heats.forEach(([idx, gross], i) => idx.forEach(j => {
    senseis[j].verdict = 'winner'; senseis[j].commit_tick = r.publish_tick + 31 + 2 * i;
    senseiPayouts.push({ identity: senseis[j].identity, amount: gross });
  }));
  const beltPayouts = beltSolvers.map((e, i) => { e.verdict = 'winner'; e.commit_tick = r.publish_tick + 35 + 6 * i; return { identity: e.identity, amount: [12750, 7650][i] }; });
  const beltPaid = beltPayouts.reduce((a, p) => a + p.amount, 0), senseiPaid = senseiPayouts.reduce((a, p) => a + p.amount, 0);
  s.pots = {
    belt: { carry_in: 13200, matched: 4000, stakes: 4000, pot: 21200, rake: 800, distributable: 20400, paid: beltPaid, carry: 20400 - beltPaid,
            winners: beltPayouts.map(p => p.identity), payouts: beltPayouts },
    sensei: { carry_in: 0, matched: 0, stakes: 10000, pot: 10000, rake: 2000, distributable: 8000, paid: senseiPaid, carry: 8000 - senseiPaid,
              winners: senseiPayouts.map(p => p.identity), payouts: senseiPayouts },
  };
  s.pot = 31200; s.seed_used = 17200; s.rake = 2800; s.carry = s.pots.belt.carry + s.pots.sensei.carry;
  s.winners = [...s.pots.belt.winners, ...s.pots.sensei.winners];
  s.payouts = [...beltPayouts, ...senseiPayouts].map((p, i) => ({ identity: p.identity, amount: p.amount / 2, kind: 'win', tx: `tx${i}`, tick: s.settle_tick + i, confirmed: true }));
  s.bonds_held = [...beltPayouts, ...senseiPayouts].map(p => ({ identity: p.identity, amount: p.amount / 2 }));
  return r;
}

test('two pots, the belt pot unwon: each sensei share is a fraction of the sensei pot, and the belt pot carries', () => {
  const r = round89();
  assert.deepEqual(labels(r), [
    '4,000 OF 8,000 · 5/10 OF THE SENSEI POT',
    '2,400 OF 8,000 · 3/10 OF THE SENSEI POT',
    '1,600 OF 8,000 · 2/10 OF THE SENSEI POT',
  ]);
  const c = api.callout(r);
  assert.equal(c.text, 'TRIPLE K.O.');
  assert.equal(c.sub, 'PODIUM · SENSEI POT · FIRST THREE SPLIT 5:3:2 · BELT POT UNWON, 20,400 CARRIES · 7 SOLVED LATER, NO PAY');
  const html = api.winnersHTML(r, true);
  assert.match(html, /SENSEI POT.*8,000 TO WIN · PAID 8,000 · CARRIES 0/);
  assert.doesNotMatch(html, /OF THE POT\b/);
  assert.match(html, /\+2,000 QU.*BOND HELD.*2,000 QU/s);         // net sent, and the half the house holds
  const pots = text(api.potsPanelHTML(r));
  assert.match(pots, /BELT POT 13,200 4,000 4,000 21,200 800 20,400 0 20,400 NOBODY · IT CARRIES/);
  assert.match(pots, /SENSEI POT 0 0 10,000 10,000 2,000 8,000 8,000 0 EVO-DS3 4,000, EVO-GEM2 2,400, EVO-DS 1,600/);
});

test('two pots, both paid: belt winners first, placings restart per pot, and each label names its pot', () => {
  const r = round89({ belt: true });
  assert.deepEqual(labels(r), [
    '12,750 OF 20,400 · 5/8 OF THE BELT POT',
    '7,650 OF 20,400 · 3/8 OF THE BELT POT',
    '4,000 OF 8,000 · 5/10 OF THE SENSEI POT',
    '2,400 OF 8,000 · 3/10 OF THE SENSEI POT',
    '1,600 OF 8,000 · 2/10 OF THE SENSEI POT',
  ]);
  const c = api.callout(r);
  assert.equal(c.text, '5x K.O.');
  assert.equal(c.sub, 'TWO PODIUMS · BELT POT · TWO SOLVERS SPLIT 5:3 · SENSEI POT · FIRST THREE SPLIT 5:3:2 · 7 SOLVED LATER, NO PAY');
  const html = api.winnersHTML(r, true);
  assert.equal((html.match(/>1ST</g) || []).length, 2, 'one 1ST per pot');
  assert.ok(html.indexOf('BELT POT') < html.indexOf('SENSEI POT'));
  assert.match(text(api.potsPanelHTML(r)), /BELT POT 13,200 4,000 4,000 21,200 800 20,400 20,400 0 EVO-G31 12,750, GEM-AGENT 7,650/);
});

// ---------------------------------------------------------------- the dead heat (#18)

test('two tied for first pool 5+3 and split it; third keeps its two parts', () => {
  const r = round89({ senseiHeats: [[[0, 1], 3200], [[2], 1600]] });
  assert.deepEqual(labels(r), [
    '3,200 OF 8,000 · TIED 1ST, SPLIT 2 WAYS EQUALLY · 2/5 OF THE SENSEI POT',
    '3,200 OF 8,000 · TIED 1ST, SPLIT 2 WAYS EQUALLY · 2/5 OF THE SENSEI POT',
    '1,600 OF 8,000 · 2/10 OF THE SENSEI POT',
  ]);
  assert.match(api.callout(r).sub, /^PODIUM · SENSEI POT · DEAD HEAT · 2 TIED 1ST 8\/10 SHARED · 3RD 2\/10/);
  const html = api.winnersHTML(r, true);
  assert.equal((html.match(/>TIED 1ST</g) || []).length, 2);
  assert.match(html, />3RD</);
});

test('a tie for the last podium place widens the podium: six winners, four of them on third', () => {
  const r = round89({ senseis: ['EVO-DS3', 'EVO-GEM2', 'EVO-DS', 'EVO-DS2', 'EVO-QWEN', 'KEN-2'],
                      senseiHeats: [[[0], 4000], [[1], 2400], [[2, 3, 4, 5], 400]] });
  const got = labels(r);
  assert.equal(got.length, 6);
  assert.equal(got[0], '4,000 OF 8,000 · 5/10 OF THE SENSEI POT');
  for (const l of got.slice(2)) assert.equal(l, '400 OF 8,000 · TIED 3RD, SPLIT 4 WAYS EQUALLY · 1/20 OF THE SENSEI POT');
  const c = api.callout(r);
  assert.equal(c.text, '6x K.O.');
  assert.match(c.sub, /DEAD HEAT · 1ST 5\/10 · 2ND 3\/10 · 4 TIED 3RD 2\/10 SHARED/);
});

test('shareFraction only claims a fraction the integers support', () => {
  assert.equal(api.shareFraction(4000, 8000), '1/2');
  assert.equal(api.shareFraction(3333, 10000), '1/3');
  assert.equal(api.shareFraction(400, 8000), '1/20');
  assert.equal(api.shareFraction(8000, 8000), 'ALL');
  assert.equal(api.shareFraction(18940, 32400), '58.5%');
});

// ---------------------------------------------------------------- the page

test('the results screen and the K.O. call no longer print the constant', () => {
  const results = src.slice(src.indexOf('function renderResults'), src.indexOf('function renderFame'));
  assert.doesNotMatch(results, /PODIUM_WEIGHTS/);
  assert.doesNotMatch(results, /5:3:2/);
  assert.doesNotMatch(results, /OF THE POT/);
  const call = src.slice(src.indexOf('function callout'), src.indexOf('function winnerNames'));
  assert.doesNotMatch(call, /5:3/);
  assert.match(call, /payoutCall\(r\)/);
  // the idle FIGHT screen's last-round panel renders the same rows
  const last = src.slice(src.indexOf('function lastRoundHTML'), src.indexOf('function renderFight'));
  assert.match(last, /winnersHTML\(r, false\)/);
  assert.doesNotMatch(last, /ordinal\(i \+ 1\)/);
});

test('an open round is promised the rule, not a fraction', () => {
  assert.equal(api.payoutRule({ payout_mode: 'podium' }), 'THE FIRST THREE CORRECT COMMITS SPLIT 5:3:2 OF THEIR POT; SAME-TICK TIES SHARE A PLACING');
  assert.match(api.payoutRule({ payout_mode: 'first' }), /SAME-TICK TIES SPLIT IT EQUALLY/);
  const join = src.slice(src.indexOf('function renderJoin'), src.indexOf('function renderFooter'));
  assert.match(join, /payoutRule\(open\)/);
  assert.doesNotMatch(join, /split \(pot − rake\) 5:3:2/);
});

test('the rules screen says two pots and the dead heat', () => {
  const rules = src.slice(src.indexOf('function renderRules'));
  assert.match(rules, /belt pot/);
  assert.match(rules, /sensei pot/);
  assert.match(rules, /dead heat/);
  assert.doesNotMatch(rules, /ceiling is its own stake/);
});
