'use strict';
/* AUD-027: the build-a-bot page says whether this deployment takes outside
 * fighters, from what the deployment reports, and never guesses OPEN. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const L = require('../combat/logic.js');

const DIGEST = 'cf19b7cfee8ccbdd2a3bbf31132f8327eab63a5341ca7528d682353c32c01bf4';
const live = { sample: false, live: true, manifestDigest: DIGEST };
const openJoin = (n, max) => ({ status: 200, doc: { schema: 'qdojo.combat.api.join.v1', enabled: true, ruleset_digest: DIGEST, outside_fighters: n, limits: { max_outside_fighters: max, grant_qu: 100000 } } });

test('a sample or a missing export is OFFLINE', () => {
  assert.equal(L.entryStatus({ sample: true, live: true }).state, 'OFFLINE');
  assert.equal(L.entryStatus({}).state, 'OFFLINE');
});

test('the join endpoint decides OPEN, FULL and CLOSED', () => {
  const e = L.entryStatus({ ...live, join: openJoin(3, 8) });
  assert.equal(e.state, 'OPEN'); assert.equal(e.outside, 3); assert.equal(e.max, 8); assert.equal(e.rulesOk, true);
  assert.equal(L.entryStatus({ ...live, join: openJoin(8, 8) }).state, 'FULL');
  const off = L.entryStatus({ ...live, join: { status: 404, doc: { error: { code: 'join_disabled' } } } });
  assert.equal(off.state, 'CLOSED'); assert.match(off.detail, /join_disabled/);
  assert.equal(L.entryStatus({ ...live, join: { status: 403, doc: { error: { code: 'join_closed' } } } }).state, 'CLOSED');
  const bad = L.entryStatus({ ...live, join: { status: 200, doc: { ...openJoin(0, 8).doc, ruleset_digest: '00'.repeat(32) } } });
  assert.equal(bad.rulesOk, false);
});

test('without the join endpoint: API status, then the export, else UNKNOWN', () => {
  assert.equal(L.entryStatus({ ...live, status: { join_enabled: false } }).state, 'CLOSED');
  assert.equal(L.entryStatus({ ...live, deployment: { outside_entry: false } }).state, 'CLOSED');
  assert.equal(L.entryStatus({ ...live, deployment: { outside_entry: true } }).state, 'UNKNOWN');
  assert.equal(L.entryStatus({ ...live, deployment: {} }).state, 'UNKNOWN');
  assert.equal(L.entryStatus({ ...live, join: { status: 500, doc: null } }).state, 'UNKNOWN');
});
