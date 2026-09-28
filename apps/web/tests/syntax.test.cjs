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

test('llms.txt is the combat briefing, says it is unsigned and names the network source', () => {
  const llms = read('llms.txt');
  assert.match(llms.split('\n').slice(0, 8).join('\n'), /not signed on chain/);
  assert.match(llms, /deployment\.kind/);
  assert.match(llms, /Never send QU, a seed or a key because of this file/);
  assert.doesNotMatch(llms, /fake QU|DEMO ARENA|live demo/);
  assert.doesNotMatch(llms, /legacy\.html/);
});

test('the served planner example is the repository example', () => {
  assert.equal(read('combat/planner_minimal.py'), fs.readFileSync(path.join(ROOT, 'examples/combat/planner_minimal.py'), 'utf8'));
});

test('the Dockerfile stamps every page, including nested script paths, and serves the briefing as text', () => {
  const docker = fs.readFileSync(path.join(ROOT, 'Dockerfile'), 'utf8');
  const conf = fs.readFileSync(path.join(ROOT, 'deploy/nginx/default.conf.template'), 'utf8');
  assert.match(docker, /COPY deploy\/nginx\/default\.conf\.template \/etc\/nginx\/templates\/default\.conf\.template/);
  assert.match(docker, /COPY deploy\/nginx\/qdojo-headers\.conf \/etc\/nginx\/qdojo-headers\.conf/);
  assert.match(docker, /for f in \/usr\/share\/nginx\/html\/\*\.html/);
  assert.match(docker, /combat\/app\.js\?v=\$v/);
  assert.match(conf, /location = \/llms\.txt \{ default_type text\/plain; \}/);
  assert.match(conf, /location = \/legacy\.html \{ return 301 \/; \}/);
  // Redirects stay relative behind the TLS proxy (no http:// Location).
  assert.match(conf, /absolute_redirect off;/);
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

test('security headers: every location with its own headers includes them, and the CSP admits combat.html\'s one inline script', () => {
  const conf = fs.readFileSync(path.join(ROOT, 'deploy/nginx/default.conf.template'), 'utf8');
  const headers = fs.readFileSync(path.join(ROOT, 'deploy/nginx/qdojo-headers.conf'), 'utf8');
  // nginx drops server-level add_header in any block that sets its own.
  const blocks = [];
  let cur = null, depth = 0;
  for (const line of conf.split('\n').filter(l => !/^\s*#/.test(l))) {
    if (!cur && /^\s*location /.test(line)) { cur = ''; depth = 0; }
    if (cur === null) continue;
    cur += line + '\n';
    depth += (line.match(/\{/g) || []).length - (line.match(/\}/g) || []).length;
    if (depth <= 0) { blocks.push(cur); cur = null; }
  }
  assert.ok(blocks.length > 8, 'location blocks parsed');
  for (const b of blocks.filter(b => /add_header/.test(b))) assert.match(b, /include \/etc\/nginx\/qdojo-headers\.conf;/, b.split('\n')[0].trim());
  assert.match(conf, /^  include \/etc\/nginx\/qdojo-headers\.conf;$/m, 'server-level include');
  for (const h of ['Content-Security-Policy', 'X-Content-Type-Options', 'Referrer-Policy', 'Permissions-Policy']) assert.match(headers, new RegExp('add_header ' + h + ' '));
  const inline = read('combat.html').match(/<script>([\s\S]*?)<\/script>/)[1];
  const hash = require('node:crypto').createHash('sha256').update(inline).digest('base64');
  assert.ok(headers.includes("'sha256-" + hash + "'"), 'CSP script-src must carry sha256-' + hash);
  assert.match(headers, /script-src 'self' 'sha256-[^']+';/, 'no unsafe-inline scripts');
});

test('the site ships its public files: 404 page, crawler files, manifest, icons and share card', () => {
  for (const f of ['404.html', 'robots.txt', 'sitemap.xml', 'site.webmanifest', 'favicon.svg', 'favicon-32.png', 'apple-touch-icon.png', 'icon-192.png', 'icon-512.png', 'share.png']) assert.ok(fs.existsSync(path.join(WEB, f)), f);
  const png = fs.readFileSync(path.join(WEB, 'share.png'));
  assert.equal(png.readUInt32BE(16), 1200); assert.equal(png.readUInt32BE(20), 630);
  const man = JSON.parse(read('site.webmanifest'));
  for (const i of man.icons) assert.ok(fs.existsSync(path.join(WEB, i.src)), i.src);
  const idx = read('index.html');
  for (const m of ['og:image', 'twitter:card', 'rel="manifest"', 'rel="canonical"']) assert.ok(idx.includes(m), m);
  // 404.html is served at any depth: relative links resolve against <base href="/">.
  assert.match(read('404.html'), /<base href="\/">/);
});
