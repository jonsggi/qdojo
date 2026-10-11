'use strict';
/* An LLM fighter whose model is offline (driver_status state "fallback") is
 * shown as offline, with the policy that plays and why; with no status, or
 * state "ok", the driver badge renders exactly as before. The badge, the
 * fighter page's note and the roster card's driver word are built in
 * logic.js with the page's esc(), so this file checks the page's HTML. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const L = require('../combat/logic.js');

const SAMPLE = path.join(__dirname, '../data/combat/v1/sample');
const OUT_OF_CREDIT = { state: 'fallback', reason: 'provider out of credit (HTTP 402)', since: '2026-10-11T08:12:00Z', last_answer: '2026-09-28T13:26:00Z', retry_at: '2026-10-11T08:42:00Z', plays: 'mixed-v1' };
const OFFLINE_TEXT = 'The model google/gemini-3.1-flash-lite is offline since 2026-10-11 08:12 UTC: provider out of credit (HTTP 402); ' +
  'it last answered at 2026-09-28 13:26 UTC. The scripted mixed-v1 policy chooses this fighter\'s plans until the model answers again ' +
  '(next try after 2026-10-11 08:42 UTC).';

// The page's escaper (app.js): the source below must be app.js's own.
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
// The badge and the roster word as the page built them before driver_status
// (app.js at b3e3f71a), for drivers with nothing to disclose.
function badgeBefore(d) {
  if (!d) return '';
  if (/^llm:/.test(d)) return '<span class="drv drv-llm" title="An LLM chooses this fighter\'s plans">MODEL: ' + esc(d.slice(4)) + '</span>';
  if (d === 'planner') return '<span class="drv drv-planner" title="The owner\'s own planner program">PLANNER</span>';
  if (d === 'builder') return '<span class="drv drv-planner" title="The outside builder runs this bot on their own machine; its code never runs on the arena">BUILDER\'S OWN BOT</span>';
  return '<span class="drv drv-policy" title="A disclosed policy chooses this fighter\'s plans">POLICY: ' + esc(d) + '</span>';
}
const kindBefore = d => (/^llm:/.test(d || '') ? 'llm' : d === 'planner' || d === 'builder' ? 'builder' : 'script');
const rosterBefore = (d, kit) => esc({ llm: 'LLM', script: 'SCRIPTED', builder: 'BUILDER BOT' }[kindBefore(d)] || '') + ' &middot; ' + esc(kit);

const sampleFighters = () => Object.values(JSON.parse(fs.readFileSync(path.join(SAMPLE, 'index.json'), 'utf8')).deployment.fighters);

test('the escaper here is the page\'s own', () => {
  const app = fs.readFileSync(path.join(__dirname, '../combat/app.js'), 'utf8');
  assert.ok(app.includes('const esc = ' + esc.toString() + ';'), 'app.js defines esc differently: update this test\'s copy');
});

test('nothing to disclose: no status (older exports, the sample), state ok, or not an LLM driver', () => {
  assert.equal(L.driverOffline('llm:google/gemini-3.1-flash-lite'), null);
  assert.equal(L.driverOffline('llm:google/gemini-3.1-flash-lite', null), null);
  assert.equal(L.driverOffline('llm:google/gemini-3.1-flash-lite', { state: 'ok' }), null);
  assert.equal(L.driverOffline('llm:x', 'fallback'), null);
  for (const d of ['mixed-v1', 'planner', 'builder', '', null, undefined]) assert.equal(L.driverOffline(d, OUT_OF_CREDIT), null, String(d));
  // The sample's fighters, and each as an LLM fighter from before driver_status.
  for (const m of sampleFighters()) {
    assert.equal(L.driverOffline(m.driver, m.driver_status), null, m.name);
    const llm = Object.assign(JSON.parse(JSON.stringify(m)), { driver: 'llm:x' });
    assert.ok(!('driver_status' in llm));
    assert.equal(L.driverOffline(llm.driver, llm.driver_status), null, m.name);
    assert.equal(L.driverBadge(llm.driver, llm.driver_status, esc), badgeBefore('llm:x'), m.name);
    assert.equal(L.driverNote(llm.driver, llm.driver_status, esc), '', m.name);
  }
});

test('with nothing to disclose the badge, note and roster word are exactly the page\'s from before driver_status', () => {
  const drivers = sampleFighters().map(m => m.driver).concat(['llm:google/gemini-3.1-flash-lite', 'llm:<b>x</b> "q"', 'planner', 'builder',
    'pol"icy<i>', '', null, undefined]);
  for (const d of drivers) {
    for (const st of [undefined, null, { state: 'ok' }, 'fallback', { state: 'ok', reason: 'ignored' }]) {
      const what = String(d) + ' / ' + JSON.stringify(st);
      assert.equal(L.driverBadge(d, st, esc), badgeBefore(d), what);
      assert.equal(L.driverNote(d, st, esc), '', what);
      assert.equal(L.rosterDriver(d || '', st, 'brawler', esc), rosterBefore(d || '', 'brawler'), what);
    }
    // A policy, planner or builder driver never reads a status as offline.
    if (!/^llm:/.test(d || '')) assert.equal(L.driverBadge(d, OUT_OF_CREDIT, esc), badgeBefore(d), String(d));
  }
  assert.equal(L.rosterDriver('mixed-v1', undefined, 'brawler', esc), 'SCRIPTED &middot; brawler');
  assert.equal(L.rosterDriver('llm:x', undefined, 'tank', esc), 'LLM &middot; tank');
  assert.equal(L.DRIVER_LABEL[L.driverKind('builder')], 'BUILDER BOT');
});

test('an offline model says so, names the fallback that plays, why, since when, its last answer and the next try, in UTC', () => {
  const off = L.driverOffline('llm:google/gemini-3.1-flash-lite', OUT_OF_CREDIT);
  assert.equal(off.label, 'MODEL OFFLINE · PLAYS MIXED-V1');
  assert.equal(off.short, 'LLM OFFLINE');
  assert.equal(off.model, 'google/gemini-3.1-flash-lite');
  assert.equal(off.text, OFFLINE_TEXT);
  const budget = L.driverOffline('llm:anthropic/claude-sonnet-5', { state: 'fallback', reason: 'daily model budget spent', retry_at: '2026-10-11T00:00:00Z', plays: 'mixed-v1' });
  assert.match(budget.text, /^The model anthropic\/claude-sonnet-5 is offline: daily model budget spent\. .* \(next try after 2026-10-11 00:00 UTC\)\.$/);
  const noKey = L.driverOffline('llm:x/y', { state: 'fallback', reason: 'no model API key configured', last_answer: '2026-09-28T13:26:00Z', plays: 'mixed-v1' });
  assert.match(noKey.text, /^The model x\/y is offline: no model API key configured; it last answered at 2026-09-28 13:26 UTC\. The scripted/);
});

test('the offline badge, note and roster word, as the page shows them', () => {
  const d = 'llm:google/gemini-3.1-flash-lite', title = esc(OFFLINE_TEXT);
  assert.equal(L.driverBadge(d, OUT_OF_CREDIT, esc), '<span class="drv drv-off" title="' + title + '">MODEL OFFLINE · PLAYS MIXED-V1</span>');
  assert.equal(L.driverNote(d, OUT_OF_CREDIT, esc), '<p class="drv-note">' + title + '</p>');
  assert.equal(L.rosterDriver(d, OUT_OF_CREDIT, 'brawler', esc), '<span><span class="ff-off" title="' + title + '">LLM OFFLINE</span> &middot; brawler</span>');
  assert.match(title, /fighter&#39;s plans/);
});

test('everything an offline status shows is escaped, in text and in title attributes', () => {
  const evil = '<img src=x onerror=alert(1)> "quoted" \'single\' & more';
  const st = { state: 'fallback', reason: evil, since: '2026-10-11T08:12:00Z', last_answer: '2026-09-28T13:26:00Z', plays: 'mixed"-v1<script>', retry_at: evil };
  const d = 'llm:evil"model<i>';
  const html = [L.driverBadge(d, st, esc), L.driverNote(d, st, esc), L.rosterDriver(d, st, 'kit<b>"', esc)];
  for (const h of html) {
    assert.doesNotMatch(h, /<img|<script|<i>|<b>/, h);
    // Every attribute value is one quoted run with no raw quote inside it.
    for (const [, value] of h.matchAll(/ [a-z]+="([^"]*)"/g)) assert.doesNotMatch(value, /[<>'"]/, value);
    assert.equal(h.split('"').length % 2, 1, 'balanced quotes: ' + h);
  }
  assert.match(html[0], /^<span class="drv drv-off" title="[^"]*">MODEL OFFLINE · PLAYS MIXED&quot;-V1&lt;SCRIPT&gt;<\/span>$/);
  assert.match(html[1], /^<p class="drv-note">The model evil&quot;model&lt;i&gt; is offline since 2026-10-11 08:12 UTC: &lt;img src=x onerror=alert\(1\)&gt; &quot;quoted&quot; &#39;single&#39; &amp; more; it last answered at 2026-09-28 13:26 UTC\. /);
  assert.match(html[2], /&middot; kit&lt;b&gt;&quot;<\/span>$/);
});

test('a status with missing or odd fields still reads as a sentence', () => {
  const off = L.driverOffline('llm:qwen/qwen3-235b-a22b-2507', { state: 'fallback', since: 'yesterday', last_answer: 42, retry_at: 7, plays: '' });
  assert.equal(off.label, 'MODEL OFFLINE · PLAYS A SCRIPTED FALLBACK');
  assert.equal(off.text, 'The model qwen/qwen3-235b-a22b-2507 is offline. A scripted fallback policy chooses this fighter\'s plans until the model answers again.');
  assert.doesNotMatch(off.text + off.label, /undefined|null|NaN/);
});
