'use strict';
// Every script a page loads must parse as a whole file, and every page must
// load only files that exist. The other tests lift helper blocks into a VM,
// which is exactly how an unescaped backtick inside a template literal in the
// rules screen (2026-09-21, app.js) passed every test and shipped a page that
// did not run at all.
//
// Layout: index.html is the combat site, legacy.html the retired riddle
// arcade (app.js), combat.html a redirect to / for old links, dash.html the
// local-only fighter page.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const WEB = path.join(__dirname, '..');
const ROOT = path.join(WEB, '../..');
const read = name => fs.readFileSync(path.join(WEB, name), 'utf8');
const scriptsOf = html => [...html.matchAll(/<script src="([a-z0-9_/-]+\.js)"/g)].map(m => m[1]);
const stylesOf = html => [...html.matchAll(/<link rel="stylesheet" href="([a-z0-9_/-]+\.css)"/g)].map(m => m[1]);

for (const name of ['app.js', 'dash.js', 'anim.js', 'avatars.js', 'combat/engine.js', 'combat/ruleset.js',
  'combat/npcs.js', 'combat/logic.js', 'combat/stages.js', 'combat/app.js', 'tests/e2e/run.cjs']) {
  test(`${name} parses as a whole file`, () => {
    // a leading #! line is valid for node but not for vm.Script
    assert.doesNotThrow(() => new vm.Script(read(name).replace(/^#!.*/, ''), { filename: name }), `${name} has a syntax error`);
  });
}

test('every page loads only scripts and styles that exist', () => {
  for (const page of ['index.html', 'legacy.html', 'dash.html', 'anim.html']) {
    const html = read(page);
    for (const src of scriptsOf(html).concat(stylesOf(html))) {
      assert.ok(fs.existsSync(path.join(WEB, src)), `${page} loads ${src}, which is missing`);
    }
  }
});

test('index.html is the combat site: engine before its users', () => {
  const scripts = scriptsOf(read('index.html'));
  const at = n => scripts.indexOf(n);
  for (const n of ['avatars.js', 'anim.js', 'combat/ruleset.js', 'combat/engine.js', 'combat/npcs.js', 'combat/logic.js', 'combat/stages.js', 'combat/app.js']) assert.ok(at(n) >= 0, n);
  assert.ok(at('combat/stages.js') < at('combat/app.js'), 'stages before the app that mounts them');
  assert.ok(at('combat/engine.js') < at('combat/npcs.js') && at('combat/npcs.js') < at('combat/logic.js') && at('combat/logic.js') < at('combat/app.js'));
  assert.equal(at('app.js'), -1, 'the riddle app.js belongs to legacy.html only');
  assert.match(read('index.html'), /href="legacy\.html"/, 'the riddle history stays reachable');
});

test('legacy.html is the retired riddle arcade: LEGACY banner and a link home', () => {
  const html = read('legacy.html');
  assert.deepEqual(scriptsOf(html), ['avatars.js', 'anim.js', 'app.js']);
  assert.match(html, /LEGACY/);
  assert.match(html, /RIDDLES ARE RETIRED/);
  assert.match(html, /href="\.\/"/);
  assert.doesNotMatch(html, /combat\.html/);
});

test('combat.html redirects to / and keeps the hash route', () => {
  const html = read('combat.html');
  assert.match(html, /location\.replace\('\.\/' \+ location\.hash\)/);
  assert.match(html, /http-equiv="refresh" content="0; url=\.\/"/);
  assert.deepEqual(scriptsOf(html), []);
});

test('llms.txt is the combat briefing and says it is unsigned; the signed one is legacy-llms.txt', () => {
  const llms = read('llms.txt');
  const top = llms.split('\n').slice(0, 8).join('\n');
  assert.match(top, /NOT YET SIGNED ON CHAIN/);
  assert.match(top, /legacy-llms\.txt/);
  assert.match(llms, /paid play is NOT live yet/);
  // The signed riddle briefing is kept byte for byte: its on-chain hash covers it.
  assert.equal(read('legacy-llms.txt'), fs.readFileSync(path.join(ROOT, 'docs/archive/riddle-v0/apps/web/llms.txt'), 'utf8'));
  const docs = JSON.parse(read('data/docs.json'));
  assert.match(read('legacy-llms.txt'), new RegExp(docs['llms.txt'].doc_hash));
  // The legacy page points its signature at the file it now serves.
  assert.match(read('app.js'), /const LEGACY_LLMS = 'legacy-llms\.txt'/);
  assert.match(read('app.js'), /docSignature\('llms\.txt', LEGACY_LLMS\)/);
});

test('the served planner example is the repository example', () => {
  assert.equal(read('combat/planner_minimal.py'), fs.readFileSync(path.join(ROOT, 'examples/combat/planner_minimal.py'), 'utf8'));
});

test('the Dockerfile stamps every page, including nested script paths, and serves both briefings as text', () => {
  const docker = fs.readFileSync(path.join(ROOT, 'Dockerfile'), 'utf8');
  assert.match(docker, /for f in \/usr\/share\/nginx\/html\/\*\.html/);
  assert.match(docker, /combat\/app\.js\?v=\$v/);
  assert.match(docker, /location = \/llms\.txt \{ default_type text\/plain; \}/);
  assert.match(docker, /location = \/legacy-llms\.txt \{ default_type text\/plain; \}/);
  // Run the same sed expression (as a JS regex) over the real pages.
  const m = docker.match(/s#\(src\|href\)=\\"(.+?)\\"#/);
  assert.ok(m, 'stamping expression not found');
  const re = new RegExp('(src|href)="' + m[1].replace(/\\\\/g, '\\') + '"', 'g');
  for (const page of ['index.html', 'legacy.html']) {
    const html = read(page);
    const stamped = html.replace(re, (_, attr, url) => attr + '="' + url + '?v=1"');
    for (const src of scriptsOf(html)) assert.ok(stamped.includes(src + '?v=1'), page + ': ' + src + ' is not stamped');
    for (const css of stylesOf(html)) assert.ok(stamped.includes(css + '?v=1'), page + ': ' + css + ' is not stamped');
    assert.ok(!stamped.includes('fonts.googleapis.com/css2?family=Press+Start+2P&display=swap?v=1'), 'absolute URLs are left alone');
  }
});
