// No dependencies or browser required: node --test apps/web/tests/avatars.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { createContext, runInContext } = require('node:vm');
const { createHash } = require('node:crypto');
const source = readFileSync(require('node:path').join(__dirname, '../avatars.js'), 'utf8');
const load = () => runInContext(source + '\nQDojoAvatars;', createContext({}));
const avatars = load();
const identity = 'A'.repeat(60);

test('art is byte-for-byte deterministic, across fresh runtimes and cache eviction', () => {
  const expected = avatars.svg(identity);
  assert.equal(load().svg(identity), expected);
  for (let i = 0; i < 300; i++) avatars.svg(`cache-${i}`);
  assert.equal(avatars.svg(identity), expected);
});

test('all published fighters have distinct artwork in this snapshot', () => {
  const { fighters } = JSON.parse(readFileSync(require('node:path').join(__dirname, '../data/fighters.json'), 'utf8'));
  const images = fighters.map(f => avatars.svg(f.identity));
  assert.equal(new Set(images).size, fighters.length);
});

test('traits are frozen, stable, and contain no financial or rarity claims', () => {
  const traits = avatars.traits(identity);
  assert.ok(Object.isFrozen(traits));
  assert.equal(JSON.stringify(traits), JSON.stringify(load().traits(identity)));
  assert.ok(traits.archetype && traits.backdrop && traits.outfit);
  for (const name of ['rank', 'belt', 'wins', 'rarity', 'owner']) assert.equal(name in traits, false);
  assert.match(avatars.version, /preview$/);
});

test('standalone SVG needs no external assets, fonts, scripts, IDs, or filters', () => {
  for (let i = 0; i < 100; i++) {
    const svg = avatars.svg(`sample-${i}`);
    assert.match(svg, /^<svg xmlns="http:\/\/www.w3.org\/2000\/svg"/);
    assert.match(svg, /viewBox="0 0 64 64"/);
    assert.match(svg, /shape-rendering="crispEdges"/);
    assert.doesNotMatch(svg, /<(script|image|foreignObject|text|filter)|\bid=|href=|url\(|onload=/i);
    assert.doesNotMatch(svg, /undefined|NaN/);
  }
});

test('render chooses detail appropriate to the existing avatar sizes', () => {
  assert.match(avatars.render(identity, 'avatar-xl'), /viewBox="0 0 64 64"/);
  assert.match(avatars.render(identity, 'avatar-sm'), /viewBox="6 0 24 24"/);
  assert.match(avatars.render(identity, 'avatar-lg'), /viewBox="0 0 32 32"/);
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
    assert.ok((svg.match(/<path/g) || []).length <= 40);
    for (const run of svg.matchAll(/M(\d+) (\d+)h(\d+)v1h-\d+z/g)) {
      const [, x, y, width] = run.map(Number);
      assert.ok(x >= 0 && x + width <= 32 && y >= 0 && y < 32);
    }
  }
});

test('both character variants appear across all kits, guards, and palettes', () => {
  const groups = new Map(), styles = new Set();
  for (let i = 0; i < 1000; i++) {
    const t = avatars.traits(`coverage-${i}`);
    assert.ok(['Female', 'Male'].includes(t.character));
    for (const key of [`kit:${t.archetype}`, `guard:${t.stance}`, `outfit:${t.outfit}`]) {
      if (!groups.has(key)) groups.set(key, new Set());
      groups.get(key).add(t.character);
    }
    if (t.character === 'Female') {
      styles.add(t.hairstyle);
      assert.match(t.hair, /^#[0-9a-f]{6}$/);
      if (['Circuit sentinel', 'Neon shinobi'].includes(t.archetype)) {
        assert.equal(t.hairstyle, 'Armoured braid');
        assert.match(t.headgear, /helmet|hood/i);
      }
    }
  }
  assert.equal(groups.size, 4 + 3 + 10);
  for (const [key, characters] of groups) assert.equal(characters.size, 2, key);
  assert.deepEqual([...styles].sort(), ['Armoured braid', 'Combat bob', 'High ponytail', 'Long braid', 'Sidecut']);
});

test('the public roster includes female and male fighters', () => {
  const { fighters } = JSON.parse(readFileSync(require('node:path').join(__dirname, '../data/fighters.json'), 'utf8'));
  const characters = new Set(fighters.map(f => avatars.traits(f.identity).character));
  assert.deepEqual([...characters].sort(), ['Female', 'Male']);
});

test('versioned preview fixtures cover both character variants', () => {
  assert.equal(avatars.version, 'qdojo-fighters-v2-preview');
  for (const [id, character, expected] of [
    [identity, 'Female', '340d0d6c26cb28afec5df527e937cb43b6f3e4589443af2a1e754fc2fb201dea'],
    ['fixture-0', 'Male', '90da6b9bc6ac1e136f459ed980e0fd34ca0021cdf668a3d4b9a2f8bc571b74cf'],
  ]) {
    assert.equal(avatars.traits(id).character, character);
    assert.equal(createHash('sha256').update(avatars.svg(id)).digest('hex'), expected);
  }
});
