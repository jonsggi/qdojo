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
// Identities with the wanted traits, found by scanning.
function find(want, limit = 40000) {
  for (let i = 0; i < limit; i++) {
    const id = `probe-${i}`, t = avatars.traits(id);
    if (Object.entries(want).every(([k, v]) => t[k] === v)) return id;
  }
  throw new Error('no identity for ' + JSON.stringify(want));
}
const TRAIT_KEYS = ['archetype', 'martialArt', 'formerJob', 'designation', 'modelYear', 'chassis', 'build', 'stance', 'finish',
  'rust', 'paint', 'outfit', 'headUnit', 'eyeGlow', 'accent', 'salvagedLimb', 'topper', 'quirk', 'headgear', 'headband',
  'gloves', 'shoulders', 'palette', 'sash', 'pattern', 'emblem', 'backdrop', 'signature'];

test('art is byte-for-byte deterministic, across fresh runtimes and cache eviction', () => {
  const expected = avatars.svg(identity);
  const fresh = load();
  assert.equal(fresh.svg(identity), expected);
  assert.equal(fresh.strip(identity, 'kick'), avatars.strip(identity, 'kick'));
  for (let i = 0; i < 300; i++) avatars.svg(`cache-${i}`);
  assert.equal(avatars.svg(identity), expected);
  assert.equal(avatars.svg(identity, 'sprite'), fresh.svg(identity, 'sprite'));
  assert.equal(fresh.bio(identity), avatars.bio(identity));
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
  for (let i = 0; i < 400; i++) {
    const id = `traits-${i}`, t = avatars.traits(id);
    assert.ok(Object.isFrozen(t));
    assert.deepEqual(Object.keys(t).sort(), [...TRAIT_KEYS].sort());
    assert.equal(JSON.stringify(t), JSON.stringify(load().traits(id)));
    for (const k of ['outfit', 'accent']) assert.match(t[k], /^#[0-9a-f]{6}$/, k);
    assert.equal(typeof t.headband, 'boolean');
    assert.ok(Number.isInteger(t.modelYear) && t.modelYear >= 2029 && t.modelYear <= 2047);
    assert.match(t.designation, /^[A-Z]{2}-\d{3}$/);
    assert.ok(t.emblem === null || t.pattern === 'Emblem');
    assert.equal(t.build, t.chassis);
    for (const [k, v] of Object.entries(t)) {
      if (typeof v !== 'string' || v.startsWith('#') || k === 'designation') continue;
      if (k === 'formerJob' || k === 'martialArt') assert.match(v, /^[A-Za-z][a-z -]*[a-z]$|^Muay Thai$/, `${k}: ${v}`);
      else assert.match(v, /^[A-Z][A-Za-z -]*$|^[a-z]+$/, `${k}: ${v}`);
    }
    for (const name of ['rank', 'belt', 'wins', 'rarity', 'owner', 'score', 'value', 'character', 'skin']) assert.equal(name in t, false);
  }
  assert.match(avatars.version, /preview$/);
});

test('every trait takes all of its values, each from its own hash domain', () => {
  const seen = {};
  for (let i = 0; i < 4000; i++) {
    const t = avatars.traits(`spread-${i}`);
    for (const [k, v] of Object.entries(t)) (seen[k] = seen[k] || new Set()).add(String(v));
  }
  const exact = {
    archetype: 12, stance: 3, chassis: 3, finish: 5, rust: 4, paint: 14, headUnit: 8, eyeGlow: 8, topper: 5, quirk: 10,
    palette: 14, sash: 4, pattern: 4, emblem: 6, backdrop: 12, signature: 4, modelYear: 19,
  };
  for (const [k, n] of Object.entries(exact)) assert.equal(seen[k].size, n, `${k}: ${[...seen[k]]}`);
  assert.deepEqual([...seen.finish].sort(), ['Factory Chrome', 'Polished Paint', 'Rust Bucket', 'Scrap-Built', 'Weathered']);
  assert.deepEqual([...seen.headUnit].sort(), ['Bucket helmet', 'CRT monitor', 'Masked', 'Painted smile', 'Radio grille', 'Single lens', 'Skull faceplate', 'Visor']);
  assert.deepEqual([...seen.quirk].sort(), ['Band-aid', 'Duct-tape patch', 'Exhaust flower', 'Headphones', 'Name sticker', 'Necktie', 'None',
    'Rubber duck', 'Toaster slot', 'Traffic-cone hat']);
  assert.deepEqual([...seen.topper].sort(), ['Drone rotor', 'Exhaust stack', 'None', 'Rabbit ears', 'Whip antenna']);
  assert.ok(seen.salvagedLimb.size >= 13, [...seen.salvagedLimb].join());
  assert.equal(seen.headgear.size, 19, [...seen.headgear].join());
  assert.ok(seen.gloves.size >= 7 && seen.shoulders.size >= 6 && seen.formerJob.size === 36 && seen.designation.size > 3000);
  // Independence: kit, paint and head unit do not predict each other.
  const pairs = new Set(), heads = new Set();
  for (let i = 0; i < 4000; i++) { const t = avatars.traits(`spread-${i}`); pairs.add(t.archetype + t.paint); heads.add(t.archetype + t.headUnit); }
  assert.ok(pairs.size > 12 * 14 * 0.8, String(pairs.size));
  assert.ok(heads.size > 12 * 7 * 0.85, String(heads.size));
});

test('shiny and rusty machines both appear across every kit and chassis', () => {
  const groups = new Map();
  for (let i = 0; i < 4000; i++) {
    const t = avatars.traits(`coverage-${i}`);
    for (const key of [`kit:${t.archetype}`, `chassis:${t.chassis}`, `head:${t.headUnit}`]) {
      if (!groups.has(key)) groups.set(key, new Set());
      groups.get(key).add(t.rust === 'None' ? 'shiny' : 'rusty');
    }
    if (t.finish === 'Factory Chrome') assert.equal(t.rust, 'None');
    if (t.finish === 'Rust Bucket') assert.ok(['Patchy', 'Heavy'].includes(t.rust));
    if (t.archetype === 'Sumo loader') assert.equal(t.chassis, 'Heavy');
    if (t.archetype === 'Drone monk') { assert.equal(t.chassis, 'Lean'); assert.equal(t.topper, 'Drone rotor'); }
    if (t.archetype === 'Luchador wrestle-bot') assert.notEqual(t.chassis, 'Lean');
    if (t.quirk === 'Exhaust flower') assert.equal(t.topper, 'Exhaust stack');
    if (t.headUnit === 'Masked') assert.match(t.headgear, /mask$/);
  }
  assert.equal(groups.size, 12 + 3 + 8);
  for (const [key, kinds] of groups) assert.equal(kinds.size, 2, key);
});

test('standalone SVG needs no external assets, fonts, scripts, IDs, or filters', () => {
  for (let i = 0; i < 100; i++) {
    for (const mode of ['artwork', 'sprite', 'portrait']) {
      const svg = avatars.svg(`sample-${i}`, mode);
      assert.match(svg, /^<svg xmlns="http:\/\/www.w3.org\/2000\/svg"/);
      assert.match(svg, /shape-rendering="crispEdges"/);
      assert.doesNotMatch(svg, /<(script|image|foreignObject|text|filter|linearGradient|radialGradient)|\bid=|href=|url\(|onload=/i);
      assert.doesNotMatch(svg, /undefined|NaN|null/);
      for (const [, color] of svg.matchAll(/fill="([^"]*)"/g)) assert.match(color, /^#[0-9a-f]{6}$/);
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
  assert.equal(avatars.bio(null), avatars.bio(''));
  assert.doesNotMatch(avatars.bio('<b>x</b>'), /<|>/);
});

test('each sprite uses compact colour paths with bounded integer pixel runs', () => {
  for (let i = 0; i < 200; i++) {
    const svg = avatars.svg(`sample-${i}`, 'sprite');
    assert.ok((svg.match(/<path/g) || []).length <= 80);
    assert.ok(svg.length < 16000, String(svg.length));
    for (const run of svg.matchAll(/M(\d+) (\d+)h(\d+)v1h-\d+z/g)) {
      const [, x, y, width] = run.map(Number);
      assert.ok(x >= 0 && x + width <= SIZE && y >= 0 && y < SIZE);
    }
  }
});

test('versioned preview fixtures', () => {
  assert.equal(avatars.version, 'qdojo-fighters-v5-preview');
  for (const [id, expected] of [
    [identity, '3f2bdb60dedf86e9b1a01aa0b23e065e48c069133d4df4b2ff353cde68e22407'],
    ['fixture-0', 'dc3dd893ee146cc22e11daa31c17f45883555f4c861ec12665a1965e5800a53a'],
  ]) assert.equal(sha(avatars.svg(id)), expected, id);
});

// Identities covering every kit, chassis, finish and head unit, plus the
// quirks and toppers that add parts outside the body.
function coverageIds() {
  const ids = [identity, 'fixture-0'];
  for (const archetype of new Set(Array.from({ length: 400 }, (_, i) => avatars.traits(`probe-${i}`).archetype))) ids.push(find({ archetype }));
  for (const chassis of ['Lean', 'Standard', 'Heavy']) for (const finish of ['Factory Chrome', 'Rust Bucket', 'Scrap-Built']) ids.push(find({ chassis, finish }));
  for (const headUnit of ['Visor', 'CRT monitor', 'Skull faceplate', 'Painted smile', 'Bucket helmet', 'Single lens', 'Radio grille', 'Masked']) ids.push(find({ headUnit }));
  for (const quirk of ['Traffic-cone hat', 'Rubber duck', 'Exhaust flower', 'Headphones', 'Toaster slot', 'Necktie']) ids.push(find({ quirk }));
  for (const topper of ['Whip antenna', 'Rabbit ears']) ids.push(find({ topper }));
  for (const shoulders of ['Parcel box', 'Wok', 'Robe', 'Towel']) ids.push(find({ shoulders }));
  ids.push(find({ salvagedLimb: 'Chrome lead leg' }), find({ salvagedLimb: 'Rusty rear arm' }));
  return [...new Set(ids)];
}

test('every clip works for every kit, chassis, finish and head: frames stay inside the canvas and differ from idle', () => {
  const clips = Object.keys(avatars.clips);
  for (const name of ['idle', 'jab', 'kick', 'hit', 'bow', 'win', 'lose', 'block', 'duck', 'throw', 'recover', 'exhausted']) assert.ok(clips.includes(name), name);
  for (const id of coverageIds()) {
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

test('no floating pixels: every frame is one connected figure', () => {
  // Treat any painted pixel as solid and flood from the first; the whole
  // sprite (outline included) must be reached.
  const grid = body => {
    const g = new Uint8Array(SIZE * SIZE);
    for (const [, x, y, w] of body.matchAll(/M(\d+) (\d+)h(\d+)v1/g)) for (let i = 0; i < +w; i++) g[+y * SIZE + +x + i] = 1;
    return g;
  };
  const ids = [...coverageIds(), 'sample-3', 'sample-9', 'sample-21', 'sample-40'];
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

test('originality guards keep famous robot and character looks out of the trait space', () => {
  for (let i = 0; i < 20000; i++) {
    const t = avatars.traits(`guard-${i}`);
    // No red-eyed chrome menace, skull soldier or scanning red visor.
    if (t.eyeGlow === 'Warning red') {
      assert.notEqual(t.finish, 'Factory Chrome');
      assert.ok(!['Skull faceplate', 'Visor'].includes(t.headUnit), t.headUnit);
      assert.notEqual(t.archetype, 'Endoskeleton trooper');
    }
    if (t.archetype === 'Endoskeleton trooper') assert.notEqual(t.headUnit, 'Skull faceplate');
    // No gold protocol droid.
    if (t.paint === 'Brass') assert.ok(!['Factory Chrome', 'Polished Paint'].includes(t.finish));
    // No red-versus-blue toy boxing robots.
    if (t.archetype === 'Boxer bot') assert.ok(!['Fire-engine red', 'Navy', 'Sky blue'].includes(t.paint), t.paint);
    // No bucket-headed robot with a single whip antenna.
    if (t.headUnit === 'Bucket helmet') assert.notEqual(t.topper, 'Whip antenna');
    // No visored police cyborg.
    if (t.archetype === 'Mall-security unit') assert.notEqual(t.headUnit, 'Visor');
    // No jackets at all, leather or otherwise.
    for (const v of Object.values(t)) assert.doesNotMatch(String(v), /jacket|leather/i);
  }
  // A white gi never gets a red headband: the band takes the dark second colour.
  const id = find({ archetype: 'Kata unit', palette: 'Classic white', headgear: 'Hachimaki', quirk: 'None', pattern: 'Plain' }, 400000);
  assert.doesNotMatch(avatars.svg(id, 'sprite'), /fill="#c8343c"/);
});

test('bios are short, deterministic, varied, built from traits and kind', () => {
  const bios = new Set(), openers = new Set(), habits = new Set();
  for (let i = 0; i < 600; i++) {
    const id = `bio-${i}`, b = avatars.bio(id), t = avatars.traits(id);
    assert.equal(b, load().bio(id));
    assert.equal(typeof b, 'string');
    assert.ok(b.length <= 240, b);
    const sentences = b.split(/(?<=\.)\s+(?=[A-Z])/);
    assert.ok(sentences.length >= 1 && sentences.length <= 2, b);
    assert.ok(b.includes(String(t.modelYear)), b);
    assert.ok(b.includes(t.formerJob), b);
    assert.ok(b.includes(t.martialArt), b);
    assert.match(b, /^[A-Z]/);
    assert.match(b, /\.$/);
    assert.doesNotMatch(b, /undefined|null|NaN|  /);
    assert.doesNotMatch(b, /\b(kill|blood|die|dead|stupid|ugly|hate|idiot)\b/i);
    bios.add(b); openers.add(b.split(/[ ,]/)[0]); habits.add(b.split(' and ').pop());
  }
  assert.ok(bios.size >= 595, String(bios.size));
  assert.ok(openers.size >= 10, [...openers].join());
  assert.ok(habits.size >= 25, String(habits.size));
});
