'use strict';
// Every script a page loads must parse as a whole file, and every page must
// load only files that exist. The other tests lift helper blocks into a VM,
// which is exactly how an unescaped backtick inside a template literal in the
// rules screen (2026-09-21, app.js) passed every test and shipped a page that
// did not run at all.
//
// Layout: index.html is the combat site, combat.html a redirect to / for old
// links, anim.html the sprite ring. The riddle arcade (legacy.html, app.js)
// was removed on 2026-09-27 and the local riddle fighter page (dash.html) on
// 2026-09-28.
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

for (const name of ['anim.js', 'avatars.js', 'combat/engine.js', 'combat/ruleset.js',
  'combat/npcs.js', 'combat/logic.js', 'combat/stages.js', 'combat/app.js', 'tests/e2e/run.cjs']) {
  test(`${name} parses as a whole file`, () => {
    // a leading #! line is valid for node but not for vm.Script
    assert.doesNotThrow(() => new vm.Script(read(name).replace(/^#!.*/, ''), { filename: name }), `${name} has a syntax error`);
  });
}

test('every page loads only scripts and styles that exist', () => {
  for (const page of ['index.html', 'anim.html']) {
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
  assert.doesNotMatch(read('index.html'), /legacy\.html/, 'the riddle arcade is gone');
});

test('combat.html redirects to / and keeps the hash route', () => {
  const html = read('combat.html');
  assert.match(html, /location\.replace\('\.\/' \+ location\.hash\)/);
  assert.match(html, /http-equiv="refresh" content="0; url=\.\/"/);
  assert.deepEqual(scriptsOf(html), []);
});

test('llms.txt is the combat briefing and says it is unsigned', () => {
  const llms = read('llms.txt');
  assert.match(llms.split('\n').slice(0, 8).join('\n'), /NOT YET SIGNED ON CHAIN/);
  assert.match(llms, /paid play is NOT live yet/);
  assert.doesNotMatch(llms, /legacy\.html/);
});

test('the served planner example is the repository example', () => {
  assert.equal(read('combat/planner_minimal.py'), fs.readFileSync(path.join(ROOT, 'examples/combat/planner_minimal.py'), 'utf8'));
});

test('the Dockerfile stamps every page, including nested script paths, and serves the briefing as text', () => {
  const docker = fs.readFileSync(path.join(ROOT, 'Dockerfile'), 'utf8');
  assert.match(docker, /for f in \/usr\/share\/nginx\/html\/\*\.html/);
  assert.match(docker, /combat\/app\.js\?v=\$v/);
  assert.match(docker, /location = \/llms\.txt \{ default_type text\/plain; \}/);
  assert.match(docker, /location = \/legacy\.html \{ return 301/);
  // Run the same sed expression (as a JS regex) over the real pages.
  const m = docker.match(/s#\(src\|href\)=\\"(.+?)\\"#/);
  assert.ok(m, 'stamping expression not found');
  const re = new RegExp('(src|href)="' + m[1].replace(/\\\\/g, '\\') + '"', 'g');
  for (const page of ['index.html']) {
    const html = read(page);
    const stamped = html.replace(re, (_, attr, url) => attr + '="' + url + '?v=1"');
    for (const src of scriptsOf(html)) assert.ok(stamped.includes(src + '?v=1'), page + ': ' + src + ' is not stamped');
    for (const css of stylesOf(html)) assert.ok(stamped.includes(css + '?v=1'), page + ': ' + css + ' is not stamped');
    assert.ok(!stamped.includes('fonts.googleapis.com/css2?family=Press+Start+2P&display=swap?v=1'), 'absolute URLs are left alone');
  }
});
