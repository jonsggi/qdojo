'use strict';
/* An LLM fighter whose model is offline (driver_status state "fallback") is
 * shown as offline, with the policy that plays and why; with no status, or
 * state "ok", the driver badge renders exactly as before. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const L = require('../combat/logic.js');

const SAMPLE = path.join(__dirname, '../data/combat/v1/sample');
const OUT_OF_CREDIT = { state: 'fallback', reason: 'provider out of credit (HTTP 402)', since: '2026-09-29T08:12:00Z', retry_at: '2026-10-10T23:12:00Z', plays: 'mixed-v1' };

test('nothing to disclose: no status (older exports, the sample), state ok, or not an LLM driver', () => {
  assert.equal(L.driverOffline('llm:google/gemini-3.1-flash-lite'), null);
  assert.equal(L.driverOffline('llm:google/gemini-3.1-flash-lite', null), null);
  assert.equal(L.driverOffline('llm:google/gemini-3.1-flash-lite', { state: 'ok' }), null);
  assert.equal(L.driverOffline('llm:x', 'fallback'), null);
  for (const d of ['mixed-v1', 'planner', 'builder', '', null, undefined]) assert.equal(L.driverOffline(d, OUT_OF_CREDIT), null, String(d));
  const dep = JSON.parse(fs.readFileSync(path.join(SAMPLE, 'index.json'), 'utf8')).deployment;
  for (const m of Object.values(dep.fighters)) assert.equal(L.driverOffline(m.driver, m.driver_status), null, m.name);
});

test('an offline model says so, names the fallback that plays, why, since when and the next try, in UTC', () => {
  const off = L.driverOffline('llm:google/gemini-3.1-flash-lite', OUT_OF_CREDIT);
  assert.equal(off.label, 'MODEL OFFLINE · PLAYS MIXED-V1');
  assert.equal(off.short, 'LLM OFFLINE');
  assert.equal(off.model, 'google/gemini-3.1-flash-lite');
  assert.equal(off.text, 'The model google/gemini-3.1-flash-lite is offline since 2026-09-29 08:12 UTC: provider out of credit (HTTP 402). ' +
    'The scripted mixed-v1 policy chooses this fighter\'s plans until the model answers again (next try after 2026-10-10 23:12 UTC).');
  const budget = L.driverOffline('llm:anthropic/claude-sonnet-5', { state: 'fallback', reason: 'daily budget spent ($1.00)', retry_at: '2026-10-11T00:00:00Z', plays: 'mixed-v1' });
  assert.match(budget.text, /^The model anthropic\/claude-sonnet-5 is offline: daily budget spent \(\$1\.00\)\. .* \(next try after 2026-10-11 00:00 UTC\)\.$/);
});

test('a status with missing or odd fields still reads as a sentence', () => {
  const off = L.driverOffline('llm:qwen/qwen3-235b-a22b-2507', { state: 'fallback', since: 'yesterday', retry_at: 7, plays: '' });
  assert.equal(off.label, 'MODEL OFFLINE · PLAYS A SCRIPTED FALLBACK');
  assert.equal(off.text, 'The model qwen/qwen3-235b-a22b-2507 is offline. A scripted fallback policy chooses this fighter\'s plans until the model answers again.');
  assert.doesNotMatch(off.text + off.label, /undefined|null|NaN/);
});
