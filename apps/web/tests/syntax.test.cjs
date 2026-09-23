'use strict';
// Every script the page loads must parse as a whole file. The other tests
// lift helper blocks into a VM, which is exactly how an unescaped backtick
// inside a template literal in the rules screen (2026-09-21, app.js) passed
// every test and shipped a page that did not run at all.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const WEB = path.join(__dirname, '..');
for (const name of ['app.js', 'dash.js', 'anim.js', 'avatars.js', 'combat/engine.js']) {
  test(`${name} parses as a whole file`, () => {
    const src = fs.readFileSync(path.join(WEB, name), 'utf8');
    assert.doesNotThrow(() => new vm.Script(src, { filename: name }), `${name} has a syntax error`);
  });
}

test('index.html and dash.html load only scripts that exist', () => {
  for (const page of ['index.html', 'dash.html']) {
    const html = fs.readFileSync(path.join(WEB, page), 'utf8');
    for (const m of html.matchAll(/<script src="([a-z]+\.js)"/g)) {
      assert.ok(fs.existsSync(path.join(WEB, m[1])), `${page} loads ${m[1]}, which is missing`);
    }
  }
});
