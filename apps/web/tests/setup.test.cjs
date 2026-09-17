// The drift guard a comment in app.js used to CLAIM existed, while the page
// shipped `qdojo bot init --full` and no such flag was ever defined.
//
// Division of labour, worth keeping: a guard that needs the real argparse
// lives in packages/qdojo/tests/test_docs_commands.py, which feeds every
// command in the markdown surfaces to the actual parser. This one covers the
// page, whose commands live in escaped JS template literals that Python should
// not try to unescape. Python reads markdown; node reads JavaScript.
// No dependencies, no browser: node --test apps/web/tests/setup.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync, statSync, existsSync } = require('node:fs');
const path = require('node:path');
const { createContext, runInContext } = require('node:vm');

const ROOT = path.join(__dirname, '..', '..', '..');
const src = readFileSync(path.join(ROOT, 'apps/web/app.js'), 'utf8');
const cli = readFileSync(path.join(ROOT, 'packages/qdojo/src/qdojo/cli.py'), 'utf8');

const block = src.match(/const REPO_URL = [\s\S]*?\nconst CMD = \{[\s\S]*?\n\};/);
assert.ok(block, 'REPO_URL/CMD literal not found in app.js');
const CMD = runInContext(block[0] + '\nCMD;', createContext({}));

const parsers = new Set([...cli.matchAll(/add_parser\("([a-z-]+)"/g)].map(m => m[1]));
const flags = new Set([...cli.matchAll(/add_argument\("(--[a-z-]+)"/g)].map(m => m[1]));

// Every qdojo INVOCATION the page prints. `git clone <url>/qdojo qdojo` is not
// one: its second "qdojo" is the directory to clone into, and reading that as a
// subcommand is how this guard starts failing on correct pages.
function published() {
  const out = new Set();
  for (const c of Object.values(CMD)) if (/^(uv run )?qdojo\s/.test(c)) out.add(c);
  for (const m of src.matchAll(/(?:^|[\s`>])((?:uv run )?qdojo [a-z][^`'"<\n]*)/g)) out.add(m[1].trim());
  return [...out];
}

test('the page prints no flag the CLI does not define', () => {
  for (const cmd of published()) {
    for (const f of cmd.match(/--[a-z][a-z-]*/g) || []) {
      assert.ok(flags.has(f), `the page prints ${f} but cli.py defines no such flag\n  in: ${cmd}`);
    }
  }
});

test('the page names no subcommand the CLI does not define', () => {
  for (const cmd of published()) {
    const m = cmd.match(/qdojo\s+([a-z-]+)(?:\s+([a-z-]+))?/);
    if (!m) continue;
    assert.ok(parsers.has(m[1]), `no such command: qdojo ${m[1]}`);
    if (m[2] && !m[2].startsWith('-')) {
      assert.ok(parsers.has(m[2]), `no such subcommand: qdojo ${m[1]} ${m[2]}`);
    }
  }
});

test('--full is gone from the page, and named so the regression is obvious', () => {
  // It was here, in README, docs/api.md and the on-chain-signed llms.txt, and
  // every one of them died with `unrecognized arguments`.
  assert.ok(flags.has('--full'), 'cli.py must keep honouring --full: llms.txt is signed on chain with it');
});

test('./dojo exists and is executable, or the headline command is a lie', () => {
  const p = path.join(ROOT, 'dojo');
  assert.ok(existsSync(p), './dojo is missing but the JOIN screen tells people to run it');
  assert.ok(statSync(p).mode & 0o111, './dojo is not executable');
});

test('the start command really is clone-then-run', () => {
  assert.match(CMD.start, /^git clone https:\/\/\S+ qdojo && cd qdojo && \.\/dojo$/);
  assert.ok(!/curl .*\| *sh/.test(src), 'the page must never tell anyone to pipe a URL into a shell');
});

test('the page prints no API key, no seed and no key-bearing export', () => {
  assert.ok(!/sk-[A-Za-z0-9]{8}/.test(src), 'something key-shaped is on the page');
  assert.ok(!/\b[a-z]{55}\b/.test(src), 'something seed-shaped is on the page');
  assert.ok(!/export [A-Z_]*API_KEY=[^\s.…]/.test(src), 'the page assigns a key a value');
});

test('the solver choices on the page are the three the CLI offers', () => {
  const onPage = [...src.matchAll(/data-solver="([a-z]+)"/g)].map(m => m[1]).sort();
  const wizard = readFileSync(path.join(ROOT, 'packages/qdojo/src/qdojo/wizard.py'), 'utf8');
  const inCli = [...wizard.matchAll(/\{"key": "([a-z]+)", "label": "[^"]*—/g)].map(m => m[1]).sort();
  assert.deepEqual(onPage, ['bare', 'byo', 'prompt']);
  assert.deepEqual(onPage, inCli, 'the page and the wizard disagree about the solver choices');
});
