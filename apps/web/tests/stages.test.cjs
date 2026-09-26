// Fight stages (combat/stages.js): decoration that must be deterministic.
// A fight ID always picks the same arena and paints the same pixels; no
// stage throws at any size, still or animated. No browser needed: the
// canvas is a stub that records every draw call.
// node --test apps/web/tests/stages.test.cjs
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SRC = fs.readFileSync(path.join(__dirname, '../combat/stages.js'), 'utf8');
// A fresh runtime per load, so no state can leak between runs.
const load = () => vm.runInContext(SRC + '\nQDojoStages;', vm.createContext({}));
const S = load();

// A 2D context stub: every call and style change goes into one log.
function stubCanvas(w, h, log) {
  const ctx = {
    _fill: '', _alpha: 1,
    set fillStyle(v) { this._fill = v; }, get fillStyle() { return this._fill; },
    set globalAlpha(v) { this._alpha = v; }, get globalAlpha() { return this._alpha; },
    fillRect(x, y, a, b) {
      for (const v of [x, y, a, b]) assert.ok(Number.isFinite(v), 'fillRect got ' + v);
      log.push('r' + x + ',' + y + ',' + a + ',' + b + this._fill + '@' + this._alpha);
    },
    drawImage(cv, x, y) { assert.ok(Number.isFinite(x) && Number.isFinite(y)); log.push('i' + cv.id + ',' + x + ',' + y); },
  };
  return { width: w, height: h, id: log.n = (log.n || 0) + 1, getContext: () => ctx, ctx };
}
function paintHash(stages, W, H, index, seed, t) {
  const log = [];
  const main = stubCanvas(W, H, log);
  stages.paint(main.ctx, W, H, index, seed, t, (w, h) => stubCanvas(w, h, log));
  return { hash: createHash('sha256').update(log.join('\n')).digest('hex'), calls: log.length };
}

test('the ten robot-dojo arenas, in order', () => {
  assert.deepEqual(Array.from(S.list, s => s.key), ['scrapyard', 'arcade', 'rooftop', 'mall', 'harbour', 'freeway', 'drivein', 'refinery', 'reactor', 'bunker']);
  for (const s of S.list) assert.match(s.name, /^[A-Za-z][A-Za-z -]+$/, 'a plain display name: ' + s.name);
});

test('a fight ID always picks the same stage, and every stage is reachable', () => {
  assert.ok(S.list.length >= 6, 'at least six stages');
  assert.equal(new Set(S.list.map(s => s.key)).size, S.list.length, 'unique keys');
  const seen = new Set();
  for (let id = 1; id <= 2000; id++) {
    const i = S.pick(String(id));
    assert.ok(Number.isInteger(i) && i >= 0 && i < S.list.length);
    assert.equal(load().pick(String(id)), i, 'same pick in a fresh runtime');
    seen.add(i);
  }
  assert.equal(seen.size, S.list.length, 'all stages appear over 2000 fight IDs');
});

test('every stage paints, still and animated, at desktop, card and tiny sizes', () => {
  for (let i = 0; i < S.list.length; i++) {
    // desktop replay, compact arena card, phone replay, title card, and degenerate sizes
    for (const [W, H] of [[360, 110], [359, 120], [240, 90], [106, 100], [262, 92], [160, 70], [40, 30]]) {
      for (const t of [0, 1.234, 97.5]) {
        const r = paintHash(S, W, H, i, 'fight-' + i, t);
        assert.ok(r.calls > 50, S.list[i].name + ' draws something at ' + W + 'x' + H);
      }
    }
  }
});

test('same seed and time give the same pixels, in a fresh runtime too; seeds and times differ', () => {
  for (let i = 0; i < S.list.length; i++) {
    const a = paintHash(S, 300, 110, i, '4079', 2.5);
    assert.equal(paintHash(load(), 300, 110, i, '4079', 2.5).hash, a.hash, S.list[i].name + ' is deterministic');
    assert.notEqual(paintHash(S, 300, 110, i, '4079', 0).hash, a.hash, S.list[i].name + ' moves over time');
  }
  const hashes = new Set(S.list.map((_, i) => paintHash(S, 300, 110, i, 'x', 0).hash));
  assert.equal(hashes.size, S.list.length, 'every stage looks different');
  assert.notEqual(paintHash(S, 300, 110, 0, 'a', 0).hash, paintHash(S, 300, 110, 0, 'b', 0).hash, 'the seed varies the details');
});

test('no randomness or clock inside the renderer: Math.random and Date are never used', () => {
  assert.doesNotMatch(SRC, /Math\.random|Date\.now|new Date/);
  assert.doesNotMatch(SRC, /url\(|<img|new Image|fetch\(/, 'no external images');
});

test('the still frame (t = 0) is stable and differs from motion; phone and desktop layouts both deterministic', () => {
  for (let i = 0; i < S.list.length; i++) {
    for (const [W, H] of [[359, 120], [106, 100]]) {
      const a = paintHash(S, W, H, i, '5021', 0), b = paintHash(load(), W, H, i, '5021', 0);
      assert.equal(a.hash, b.hash, S.list[i].name + ' still frame at ' + W + 'x' + H);
      assert.notEqual(paintHash(S, W, H, i, '5021', 3.3).hash, a.hash, S.list[i].name + ' animates at ' + W + 'x' + H);
    }
  }
});

test('every draw stays finite and inside a sane range around the canvas', () => {
  for (let i = 0; i < S.list.length; i++) {
    for (const [W, H] of [[359, 120], [106, 100], [40, 30]]) {
      const bad = [];
      const ctx = { fillStyle: '', globalAlpha: 1, drawImage() {}, fillRect(x, y, w, h) { if (x < -200 || y < -200 || x > W + 200 || y > H + 200 || w < 0 || h < 0) bad.push([x, y, w, h]); } };
      S.paint(ctx, W, H, i, 'range', 1.5, (w, h) => ({ width: w, height: h, getContext: () => ctx }));
      assert.deepEqual(bad, [], S.list[i].name + ' draws near the canvas at ' + W + 'x' + H);
    }
  }
});
