// The cockpit's pure helpers, lifted out of dash.js and run in a vm: no
// browser, no DOM, no fetch. The block between the two markers is the
// contract; anything that needs `document` stays outside it. Same trick as
// help.test.cjs, and for the same reason: Python reads markdown, node reads
// JavaScript, neither guesses at the other's escaping.
// node --test apps/web/tests/dash.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const { createContext, runInContext } = require('node:vm');

const src = readFileSync(path.join(__dirname, '../dash.js'), 'utf8');
const html = readFileSync(path.join(__dirname, '../dash.html'), 'utf8');
const py = readFileSync(path.join(__dirname, '../../../packages/qdojo/src/qdojo/dash.py'), 'utf8');

const start = src.indexOf('// ---- pure helpers');
const end = src.indexOf('// ---- end pure helpers');
assert.ok(start > 0 && end > start, 'the pure-helpers block is not delimited in dash.js');
const H = runInContext(src.slice(start, end) + '\n({ esc, fmt, pct, signed, ageText, upText, sparkPath, settingControl, sourceBadge, rowState });',
  createContext({}));

test('the helpers block touches neither the DOM nor the network', () => {
  const block = src.slice(start, end);
  for (const word of ['document', 'fetch(', 'location', 'window', 'setInterval']) {
    assert.ok(!block.includes(word), `${word} inside the pure block`);
  }
});

test('ageText reads like a human wrote it', () => {
  assert.equal(H.ageText(3), '3s');
  assert.equal(H.ageText(65), '1m05s');
  assert.equal(H.ageText(3725), '1h02m');
  assert.equal(H.ageText(null), '—');
  assert.equal(H.ageText(-4), '0s');
});

test('upText: a live counter only while running, frozen at the last heartbeat once stale', () => {
  // A stale bot is dead; showing Date.now() - started_at keeps "UP" growing
  // for a bot the same panel calls STALE (#WEB-4). RAN is the span it was
  // actually alive: started_at up to its last heartbeat, and no further.
  assert.equal(H.upText({ state: 'running', started_at: 100 }, 3725 + 100), '1h02m');
  assert.equal(H.upText({ state: 'stale', started_at: 100, heartbeat_at: 3825 }, 999999), '1h02m');
  assert.equal(H.upText({ state: 'stale', started_at: 100, heartbeat_at: 3825 }, 1000999),
    H.upText({ state: 'stale', started_at: 100, heartbeat_at: 3825 }, 999999), 'stale UP does not grow with now');
  assert.equal(H.upText({ state: 'idle' }, 1000), '—');
  assert.equal(H.upText({ state: 'running' }, 1000), '—');
});

test('sparkPath needs two points and puts zero where zero is', () => {
  assert.equal(H.sparkPath([]), null);
  assert.equal(H.sparkPath([[1, 500]]), null);
  const sp = H.sparkPath([[1, -100], [2, 0], [3, 100]], 600, 80);
  assert.equal(sp.points.split(' ').length, 3);
  assert.equal(sp.last, 100);
  assert.ok(sp.zeroY > 0 && sp.zeroY < 80, 'the zero line is inside the box');
  const [x0] = sp.points.split(' ')[0].split(',').map(Number);
  const [x2] = sp.points.split(' ')[2].split(',').map(Number);
  assert.equal(x0, 0); assert.equal(x2, 600);
  const flat = H.sparkPath([[1, 0], [2, 0]]);
  assert.ok(flat.points.split(' ').every(p => Number(p.split(',')[1]) === 40), 'a flat series sits mid-box');
});

test('settingControl builds the right control per type and escapes everything', () => {
  const sel = H.settingControl({ key: 'PI_THINKING', type: 'enum', choices: ['off', 'low'], default: 'low', value: null }, false);
  assert.match(sel, /<select data-key="PI_THINKING"/);
  assert.match(sel, /value="low" selected/);
  const tools = H.settingControl({ key: 'PI_TOOLS', type: 'enum', choices: ['', 'bash'], default: '', value: 'bash' }, false);
  assert.match(tools, /\(none\)/); assert.match(tools, /value="bash" selected/);
  const num = H.settingControl({ key: 'N', type: 'int', min: 1, max: 9, default: 3, value: '5' }, false);
  assert.match(num, /type="number"/); assert.match(num, /min="1"/); assert.match(num, /step="1"/); assert.match(num, /value="5"/);
  const flt = H.settingControl({ key: 'F', type: 'float', value: null }, false);
  assert.match(flt, /step="any"/);
  const b = H.settingControl({ key: 'B', type: 'bool', default: 'true', value: null }, false);
  assert.match(b, /<option value="true" selected/);
  const s = H.settingControl({ key: 'M', type: 'string', suggestions: ['a/b', 'c'], value: '"><script>' }, false);
  assert.match(s, /list="dl-M"/); assert.match(s, /<datalist id="dl-M">/);
  assert.ok(!s.includes('<script>'), 'a value is escaped');
  assert.match(s, /&quot;&gt;&lt;script&gt;/);
  const ro = H.settingControl({ key: 'M', type: 'string', value: 'x' }, true);
  assert.match(ro, /disabled/);
});

test('a secret control shows the variable name and whether it is set, never a value', () => {
  const c = H.settingControl({ key: 'OPENAI_API_KEY', type: 'secret', default: 'OPENROUTER_API_KEY', value: null,
    env_name: 'OPENROUTER_API_KEY', set_in_env: true }, false);
  assert.match(c, /\$OPENROUTER_API_KEY is SET/);
  assert.match(c, /placeholder="OPENROUTER_API_KEY"/);
  const n = H.settingControl({ key: 'K', type: 'secret', value: 'MY_VAR', env_name: 'MY_VAR', set_in_env: false }, false);
  assert.match(n, /\$MY_VAR is NOT SET/);
  assert.match(n, /value="MY_VAR"/);
});

test('rowState is the verdict once settled and what the bot did before', () => {
  assert.equal(H.rowState({ verdict: 'winner', skipped: false }), 'winner');
  assert.equal(H.rowState({ skipped: true }), 'sat out');
  assert.equal(H.rowState({ entered: true }), 'pending');
  assert.equal(H.rowState({ solver_failures: 2 }), 'no answer');
  assert.equal(H.rowState({ dead: true, entered: true }), 'dead');
  assert.equal(H.rowState({}), 'seen');
});

test('signed and pct format an unknown as an unknown', () => {
  assert.equal(H.signed(1500), '+1,500'); assert.equal(H.signed(-3), '-3'); assert.equal(H.signed(null), '—');
  assert.equal(H.pct(0.754), '75%'); assert.equal(H.pct(undefined), '—');
  assert.match(H.sourceBadge('shell'), /SHELL/);
});

test('the page polls the routes the server actually serves', () => {
  const routes = [...py.matchAll(/path == "(\/api\/[a-z]+)"/g)].map(m => m[1]);
  for (const r of ['/api/status', '/api/metrics', '/api/settings', '/api/log', '/api/fighter', '/api/prompt']) {
    assert.ok(routes.includes(r), `${r} is not a route in dash.py`);
    assert.ok(src.includes(`'${r}`), `dash.js never calls ${r}`);
  }
  for (const m of src.matchAll(/api\('(\/api\/[a-z]+)/g)) assert.ok(routes.includes(m[1]), `dash.js calls ${m[1]} which dash.py does not serve`);
  for (const m of src.matchAll(/put\('(\/api\/[a-z]+)/g)) assert.ok(routes.includes(m[1]), `dash.js writes ${m[1]} which dash.py does not serve`);
});

test('the page pulls no web font and no third-party script', () => {
  assert.ok(!/fonts\.googleapis|fonts\.gstatic|https?:\/\//.test(html), 'dash.html reaches out to the network');
  assert.match(html, /<script src="dash\.js">/);
  assert.match(html, /id="hud-bot"/);
});

test('every settings write goes through the token header', () => {
  // The only writer is put(); it must send X-QDojo-Token, and nothing else may call fetch with PUT.
  assert.match(src, /'X-QDojo-Token': T/);
  assert.equal((src.match(/method: 'PUT'/g) || []).length, 1);
});
