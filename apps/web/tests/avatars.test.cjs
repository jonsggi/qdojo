// No dependencies or browser required: node --test apps/web/tests/avatars.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { createContext, runInContext } = require('node:vm');
const { createHash } = require('node:crypto');
const path = require('node:path');
const source = readFileSync(path.join(__dirname, '../avatars.js'), 'utf8');
const load = () => runInContext(source + '\nQDojoAvatars;', createContext({}));
const avatars = load();
const identity = 'A'.repeat(60);
const SIZE = 48;
const roster = () => JSON.parse(readFileSync(path.join(__dirname, '../data/fighters.json'), 'utf8')).fighters;
const sha = s => createHash('sha256').update(s).digest('hex');
const inner = s => s.replace(/^<svg[^>]*>|<\/svg>$/g, '');
// Identities for a given archetype, character and build, found by scanning.
function find(want, limit = 20000) {
  for (let i = 0; i < limit; i++) {
    const id = `probe-${i}`, t = avatars.traits(id);
    if (Object.entries(want).every(([k, v]) => t[k] === v)) return id;
  }
  throw new Error('no identity for ' + JSON.stringify(want));
}

test('art is byte-for-byte deterministic, across fresh runtimes and cache eviction', () => {
  const expected = avatars.svg(identity);
  const fresh = load();
  assert.equal(fresh.svg(identity), expected);
  assert.equal(fresh.strip(identity, 'kick'), avatars.strip(identity, 'kick'));
  for (let i = 0; i < 300; i++) avatars.svg(`cache-${i}`);
  assert.equal(avatars.svg(identity), expected);
  assert.equal(avatars.svg(identity, 'sprite'), fresh.svg(identity, 'sprite'));
});

test('the renderer uses no randomness, clock, network or DOM', () => {
  assert.doesNotMatch(source, /Math\.random|Date\b|performance\.|fetch\(|document\.|window\.|Math\.(sin|cos|tan|pow|exp|log|sqrt|atan)/);
});

test('all published fighters have distinct artwork in this snapshot', () => {
  const fighters = roster();
  const images = fighters.map(f => avatars.svg(f.identity));
  assert.equal(new Set(images).size, fighters.length);
});

test('traits are frozen, stable, human-readable and contain no financial or rarity claims', () => {
  const keys = ['archetype', 'stance', 'character', 'build', 'outfit', 'palette', 'skin', 'skinTone', 'headgear', 'hairstyle',
    'hair', 'hairColour', 'headband', 'eyes', 'expression', 'facialHair', 'scar', 'gloves', 'shoulders', 'sash', 'markings',
    'pattern', 'emblem', 'accent', 'backdrop', 'signature'];
  for (let i = 0; i < 400; i++) {
    const id = `traits-${i}`, t = avatars.traits(id);
    assert.ok(Object.isFrozen(t));
    assert.deepEqual(Object.keys(t).sort(), [...keys].sort());
    assert.equal(JSON.stringify(t), JSON.stringify(load().traits(id)));
    for (const k of ['outfit', 'skin', 'accent']) assert.match(t[k], /^#[0-9a-f]{6}$/, k);
    assert.ok(t.hair === null || /^#[0-9a-f]{6}$/.test(t.hair));
    assert.equal(t.hair === null, t.hairColour === null);
    assert.equal(typeof t.headband, 'boolean');
    assert.ok(t.emblem === null || t.pattern === 'Emblem');
    for (const [k, v] of Object.entries(t)) {
      if (typeof v === 'string' && !v.startsWith('#')) assert.match(v, /^[A-Z][A-Za-z -]*$|^[a-z]+$/, `${k}: ${v}`);
    }
    for (const name of ['rank', 'belt', 'wins', 'rarity', 'owner', 'score', 'value']) assert.equal(name in t, false);
  }
  assert.match(avatars.version, /preview$/);
});

test('every trait takes several values, each from its own hash domain', () => {
  const seen = {};
  for (let i = 0; i < 3000; i++) {
    const t = avatars.traits(`spread-${i}`);
    for (const [k, v] of Object.entries(t)) (seen[k] = seen[k] || new Set()).add(String(v));
  }
  const min = { archetype: 12, stance: 3, character: 2, build: 3, palette: 14, skinTone: 8, eyes: 6, expression: 4,
    facialHair: 6, scar: 4, gloves: 6, shoulders: 3, sash: 4, markings: 5, pattern: 4, emblem: 5, backdrop: 12, headgear: 17, hairstyle: 17 };
  for (const [k, n] of Object.entries(min)) assert.ok(seen[k].size >= n, `${k}: ${seen[k].size}`);
  // Independence: kit and palette do not predict each other.
  const pairs = new Set();
  for (let i = 0; i < 3000; i++) { const t = avatars.traits(`spread-${i}`); pairs.add(t.archetype + t.palette); }
  assert.ok(pairs.size > 12 * 14 * 0.9, String(pairs.size));
});

test('standalone SVG needs no external assets, fonts, scripts, IDs, or filters', () => {
  for (let i = 0; i < 100; i++) {
    for (const mode of ['artwork', 'sprite', 'portrait']) {
      const svg = avatars.svg(`sample-${i}`, mode);
      assert.match(svg, /^<svg xmlns="http:\/\/www.w3.org\/2000\/svg"/);
      assert.match(svg, /shape-rendering="crispEdges"/);
      assert.doesNotMatch(svg, /<(script|image|foreignObject|text|filter|linearGradient|radialGradient)|\bid=|href=|url\(|onload=/i);
      assert.doesNotMatch(svg, /undefined|NaN|null/);
    }
    assert.match(avatars.svg(`sample-${i}`), /viewBox="0 0 64 64"/);
  }
});

test('render chooses detail appropriate to the existing avatar sizes', () => {
  assert.equal(avatars.size, SIZE);
  assert.match(avatars.render(identity, 'avatar-xl'), /viewBox="0 0 64 64"/);
  assert.match(avatars.render(identity, 'avatar-sm'), /viewBox="12 0 24 24"/);
  assert.match(avatars.render(identity, 'avatar-lg'), /viewBox="0 0 48 48"/);
  assert.match(avatars.render(identity), /aria-hidden="true"/);
});

test('untrusted identities and class names cannot introduce markup', () => {
  const result = avatars.render('<script>alert(1)</script>', 'avatar-xl "><img src=x onerror=alert(1)>');
  assert.doesNotMatch(result, /<script|<img|onerror|src=/);
  assert.match(result, /class="avatar avatar-xl"/);
  assert.equal(avatars.svg(null), avatars.svg(''));
});

test('each sprite uses compact colour paths with bounded integer pixel runs', () => {
  for (let i = 0; i < 100; i++) {
    const svg = avatars.svg(`sample-${i}`, 'sprite');
    assert.ok((svg.match(/<path/g) || []).length <= 64);
    assert.ok(svg.length < 16000, String(svg.length));
    for (const run of svg.matchAll(/M(\d+) (\d+)h(\d+)v1h-\d+z/g)) {
      const [, x, y, width] = run.map(Number);
      assert.ok(x >= 0 && x + width <= SIZE && y >= 0 && y < SIZE);
    }
  }
});

test('both character variants appear across all kits, builds, guards, and palettes', () => {
  const groups = new Map(), styles = new Set();
  for (let i = 0; i < 3000; i++) {
    const t = avatars.traits(`coverage-${i}`);
    assert.ok(['Female', 'Male'].includes(t.character));
    for (const key of [`kit:${t.archetype}`, `guard:${t.stance}`, `palette:${t.palette}`, `build:${t.build}`]) {
      if (!groups.has(key)) groups.set(key, new Set());
      groups.get(key).add(t.character);
    }
    if (t.character === 'Female') {
      styles.add(t.hairstyle);
      assert.match(t.hair, /^#[0-9a-f]{6}$/);
      assert.equal(t.facialHair, 'None');
      if (/helmet|hood|mask$/i.test(t.headgear)) assert.equal(t.hairstyle, 'Armoured braid');
    }
    if (t.archetype === 'Sumo wrestler') assert.equal(t.build, 'Heavy');
    if (t.archetype === 'Mountain mystic') assert.equal(t.build, 'Lean');
  }
  assert.equal(groups.size, 12 + 3 + 14 + 3);
  for (const [key, characters] of groups) assert.equal(characters.size, 2, key);
  assert.deepEqual([...styles].sort(), ['Armoured braid', 'Combat bob', 'High ponytail', 'Long braid', 'Long loose', 'Pixie', 'Sidecut', 'Topknot', 'Twin buns']);
});

test('the public roster includes female and male fighters', () => {
  const characters = new Set(roster().map(f => avatars.traits(f.identity).character));
  assert.deepEqual([...characters].sort(), ['Female', 'Male']);
});

test('versioned preview fixtures cover both character variants', () => {
  assert.equal(avatars.version, 'qdojo-fighters-v4-preview');
  for (const [id, character, expected] of [
    [identity, 'Female', 'c10b7684605c4e723de65ac490f914362b16b1d2cf7ec46b677a13c0a3b45bf7'],
    ['fixture-0', 'Male', '1d0ea0e7f02c0f2aa8015213a8ba0f8f662541050294328e4b0634293e0a58c0'],
  ]) {
    assert.equal(avatars.traits(id).character, character);
    assert.equal(sha(avatars.svg(id)), expected, id);
  }
});

test('every clip works for every kit and build: frames stay inside the canvas and differ from idle', () => {
  const clips = Object.keys(avatars.clips);
  for (const name of ['idle', 'jab', 'kick', 'hit', 'bow', 'win', 'lose', 'block', 'duck', 'throw', 'recover', 'exhausted']) assert.ok(clips.includes(name), name);
  const ids = [identity, 'fixture-0'];
  for (const archetype of new Set(Array.from({ length: 400 }, (_, i) => avatars.traits(`probe-${i}`).archetype))) ids.push(find({ archetype }));
  for (const build of ['Lean', 'Standard', 'Heavy']) for (const character of ['Female', 'Male']) ids.push(find({ build, character }));
  for (const id of ids) {
    const still = inner(avatars.svg(id, 'sprite'));
    const idle = avatars.frames(id, 'idle');
    assert.equal(idle[0], still, 'idle frame zero is the static sprite');
    for (const clip of clips) {
      const spec = avatars.clips[clip], frames = avatars.frames(id, clip);
      assert.equal(frames.length, spec.frames.length);
      assert.ok(spec.fps > 0 && spec.fps <= 12);
      assert.ok(new Set(frames).size > 1, `${clip} moves`);
      if (clip !== 'idle') assert.ok(frames.some(f => f !== still), `${clip} leaves the guard`);
      for (const body of frames) {
        assert.doesNotMatch(body, /undefined|NaN|null/);
        for (const [, x, y, w] of body.matchAll(/M(-?\d+) (-?\d+)h(\d+)v1/g)) {
          assert.ok(+x >= 0 && +x + +w <= SIZE && +y >= 0 && +y < SIZE, `${clip} ${x},${y}`);
        }
      }
      const s = avatars.strip(id, clip);
      assert.equal((s.match(/<g data-frame=/g) || []).length, frames.length);
      assert.match(s, new RegExp(`data-clip="${clip}" data-fps="${spec.fps}" data-frames="${frames.length}"`));
      assert.doesNotMatch(s, /<animate|<script|\bid=/);
    }
    assert.equal(avatars.frames(id, 'win', 'artwork').length, avatars.clips.win.frames.length);
  }
  assert.equal(avatars.frames(identity, 'no-such-clip')[0], inner(avatars.svg(identity, 'sprite')));
  assert.equal(avatars.clips.lose.hold, true);
});

test('no floating limbs: every frame is one connected figure', () => {
  // Treat any painted pixel as solid and flood from the first; the whole
  // sprite (outline included) must be reached.
  const grid = body => {
    const g = new Uint8Array(SIZE * SIZE);
    for (const [, x, y, w] of body.matchAll(/M(\d+) (\d+)h(\d+)v1/g)) for (let i = 0; i < +w; i++) g[+y * SIZE + +x + i] = 1;
    return g;
  };
  const ids = ['fixture-0', identity, 'sample-3', 'sample-9', 'sample-21', 'sample-40'];
  for (const archetype of ['Sumo wrestler', 'Mountain mystic', 'Neon shinobi', 'Prize boxer']) ids.push(find({ archetype }));
  for (const id of ids) for (const clip of Object.keys(avatars.clips)) for (const body of avatars.frames(id, clip)) {
    const g = grid(body), start = g.indexOf(1), seen = new Uint8Array(g.length), stack = [start];
    seen[start] = 1;
    let n = 0;
    while (stack.length) {
      const i = stack.pop(); n++;
      const x = i % SIZE;
      for (const j of [x > 0 ? i - 1 : -1, x < SIZE - 1 ? i + 1 : -1, i - SIZE, i + SIZE]) {
        if (j >= 0 && j < g.length && g[j] && !seen[j]) { seen[j] = 1; stack.push(j); }
      }
    }
    assert.equal(n, g.reduce((a, b) => a + b, 0), `${id} ${clip}`);
  }
});

test('the identity cache is bounded and eviction does not change the art', () => {
  const first = avatars.svg('bounded-0');
  for (let i = 1; i < 700; i++) avatars.svg(`bounded-${i}`);
  assert.equal(avatars.svg('bounded-0'), first);
  // A few hundred identities render quickly enough for a leaderboard page.
  const t0 = process.hrtime.bigint();
  for (let i = 0; i < 100; i++) avatars.svg(`speed-${i}`);
  assert.ok(Number(process.hrtime.bigint() - t0) / 1e6 < 2000);
});
