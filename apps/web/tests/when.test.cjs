// The tick screen printed "11215.8 h AGO" for a tick a year old (#4). These
// pin the units of the relative-time formatter: seconds under 90 s, minutes
// under 90 min, whole hours under 48 h, whole days after that, and no clock
// arithmetic at all for a tick older than the dojo's first round.
// No dependencies or browser required: node --test apps/web/tests/when.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const { createContext, runInContext } = require('node:vm');

const src = readFileSync(path.join(__dirname, '../app.js'), 'utf8');

// Lift the two pure helpers and the one constant they read out of the browser
// file and evaluate just those, the way help.test.cjs lifts HELP.
const pick = re => { const m = src.match(re); assert.ok(m, `${re} not found in app.js`); return m[0]; };
const block = [pick(/const TICK_MS = [^\n]*/), pick(/function ageText\([\s\S]*?\n\}/), pick(/function tickWhen\([\s\S]*?\n\}/)].join('\n');
const { ageText, tickWhen } = runInContext(block + '\n({ ageText, tickWhen });', createContext({}));

const TICK_S = 0.5;                       // TICK_MS / 1000, what the page assumes
const NOW = 80833613;                     // generated_tick of the export in apps/web/data
const FIRST = 80127049;                   // publish_tick of round 1 in that export
const ago = secs => NOW - Math.round(secs / TICK_S);

test('seconds under 90 s, then minutes', () => {
  assert.equal(ageText(0), '0 s');
  assert.equal(ageText(89), '89 s');
  assert.equal(ageText(90), '2 min');
  assert.equal(ageText(12 * 60), '12 min');
});

test('minutes under 90 min, then whole hours', () => {
  assert.equal(ageText(89 * 60), '89 min');
  assert.equal(ageText(90 * 60), '2 h');
  assert.equal(ageText(5 * 3600 + 1700), '5 h');
});

test('hours under 48 h, then whole days', () => {
  assert.equal(ageText(47 * 3600), '47 h');
  assert.equal(ageText(48 * 3600), '2 d');
  // 11215.8 h, the number the issue quoted, is 467 days
  assert.equal(ageText(11215.8 * 3600), '467 d');
});

test('nothing the formatter prints carries a decimal point', () => {
  for (const s of [0.4, 1.5, 89.9, 90.5, 5399.9, 5400.5, 172799.9, 172800.5, 40376743.5, 1e9]) {
    assert.doesNotMatch(ageText(s), /\./, `ageText(${s}) = ${ageText(s)}`);
  }
});

test('the tick screen says AGO in the same units', () => {
  assert.equal(tickWhen(ago(30), NOW, FIRST), '30 s AGO');
  assert.equal(tickWhen(ago(5 * 60), NOW, FIRST), '5 min AGO');
  assert.equal(tickWhen(ago(3 * 3600), NOW, FIRST), '3 h AGO');
  assert.equal(tickWhen(FIRST, NOW, FIRST), '4 d AGO');   // 706,564 ticks at half a second
});

test('a tick still ahead of the clock is IN, not AGO', () => {
  assert.equal(tickWhen(NOW + 10, NOW, FIRST), 'IN 5 s');
  assert.equal(tickWhen(NOW, NOW, FIRST), '0 s AGO');
});

test('a tick older than round 1 says so instead of counting days it cannot know', () => {
  // #tick/80126 is 80 million ticks before the dojo existed. The export has
  // one wall-clock anchor (generated_at) and the tick rate drifts, so a date
  // extrapolated that far would be months off. The page says what it knows.
  assert.equal(tickWhen(80126, NOW, FIRST), 'BEFORE ROUND 1');
  assert.equal(tickWhen(FIRST - 1, NOW, FIRST), 'BEFORE ROUND 1');
  // with no round at all there is no "before": fall back to the day count
  assert.equal(tickWhen(80126, NOW, null), '467 d AGO');
  assert.equal(tickWhen(80126, NOW, undefined), '467 d AGO');
});

test('the tick screen really uses the formatter', () => {
  assert.match(src, /const when = tickWhen\(t, now, firstRoundTick\(\)\)/);
  assert.doesNotMatch(src, /toFixed\(1\)\} h AGO/, 'the decimal-hours branch is back');
});
