// The help dictionary is the single source for BOTH the hover tooltips and the
// RULES screen. If they were ever allowed to drift, the disagreement would be
// about money. These tests are the lock.
// No dependencies or browser required: node --test apps/web/tests/help.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const { createContext, runInContext } = require('node:vm');

const src = readFileSync(path.join(__dirname, '../app.js'), 'utf8');
const html = readFileSync(path.join(__dirname, '../legacy.html'), 'utf8');

// Lift the HELP literal out of the browser file and evaluate just that.
const block = src.match(/const HELP = \{[\s\S]*?\n\};/);
assert.ok(block, 'HELP dictionary not found in app.js');
const HELP = runInContext(block[0] + '\nHELP;', createContext({}));

const usedKeys = new Set([
  ...[...src.matchAll(/\bh\('([a-z_]+)'\)/g)].map(m => m[1]),
  ...[...src.matchAll(/data-help="([a-z_]+)"/g)].map(m => m[1]),
  ...[...html.matchAll(/data-help="([a-z_]+)"/g)].map(m => m[1]),
  ...[...src.matchAll(/ruleTerm\('([a-z_]+)'/g)].map(m => m[1]),
]);

test('every data-help key the page renders exists in HELP', () => {
  const missing = [...usedKeys].filter(k => !HELP[k]);
  assert.deepEqual(missing, [], `keys used but not defined: ${missing}`);
});

test('every HELP entry is actually reachable on the page', () => {
  const orphans = Object.keys(HELP).filter(k => !usedKeys.has(k));
  assert.deepEqual(orphans, [], `defined but never rendered: ${orphans}`);
});

test('every HELP entry is a usable sentence', () => {
  for (const [key, d] of Object.entries(HELP)) {
    assert.ok(d.label && d.label === d.label.toUpperCase(), `${key}: label must be upper case`);
    assert.ok(d.text.length > 40, `${key}: text is too short to explain anything`);
    assert.ok(/[.!]$/.test(d.text.trim()), `${key}: text must end in a full stop`);
    assert.ok(!/\$\{/.test(d.text), `${key}: an unformatted template reached the dictionary`);
  }
});

test('the rules screen defines its terms from HELP, never by retyping them', () => {
  // ruleTerm() is the only way prose from the dictionary may reach #rules.
  const rules = src.slice(src.indexOf('function renderRules'));
  for (const [key, d] of Object.entries(HELP)) {
    const firstWords = d.text.split(' ').slice(0, 6).join(' ');
    assert.ok(!rules.includes(firstWords),
      `renderRules retypes the ${key} definition instead of calling ruleTerm('${key}')`);
  }
});

test('the HELP chip and the tooltip node exist in the markup', () => {
  assert.match(html, /id="btn-help"/);
  assert.match(html, /id="tip"[^>]*role="tooltip"/);
});

test('the help chip is excluded from the attract-mode killer', () => {
  // Turning help on mid-attract must not stop the cabinet cycling.
  assert.match(src, /closest\('#btn-attract,#btn-help'\)/);
});

test('hover uses pointerover, which is not the attract killer', () => {
  assert.match(src, /addEventListener\('pointerover'/);
  assert.ok(!/addEventListener\('pointerdown', *e *=> *\{[^}]*showTipFor/.test(src));
});
