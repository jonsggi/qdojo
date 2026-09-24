#!/usr/bin/env node
/* Browser end-to-end check of the combat site on the committed sample export.
 *
 *   node apps/web/tests/e2e/run.cjs        (or: make web-e2e)
 *
 * Serves apps/web from a tiny static server on 127.0.0.1, drives the cached
 * Chromium through every view, and fails on any page error, any console error
 * or failed request other than the expected 404 for the live manifest (the
 * site then falls back to the SAMPLE export), or a missing key element. It
 * also re-runs a replay against a tampered temp copy of the export and
 * requires FAIL, checks reduced-motion parity and a 375 px phone width, and
 * saves screenshots to apps/web/tests/e2e/shots/ (gitignored).
 *
 * Needs the Playwright package and its Chromium; without them it prints why
 * and exits 0, so it never breaks a machine that cannot run a browser. It is
 * deliberately not part of `node --test` / `make test`.
 *
 * Environment: QDOJO_PLAYWRIGHT (path to a playwright package),
 * QDOJO_CHROMIUM (browser binary), QDOJO_E2E_TMP (temp dir root),
 * QDOJO_E2E_ONLY (comma-separated step names).
 */
'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');

const WEB = path.resolve(__dirname, '../..');
const SAMPLE = path.join(WEB, 'data/combat/v1/sample');
const SHOTS = path.join(__dirname, 'shots');
const HOME = os.homedir();
const LIVE_MANIFEST = '/data/combat/v1/manifest.json';

// ---- find the browser ------------------------------------------------------------

function findPlaywright() {
  const tries = [process.env.QDOJO_PLAYWRIGHT, 'playwright', 'playwright-core'].filter(Boolean);
  const npx = path.join(HOME, '.npm/_npx');
  if (fs.existsSync(npx)) {
    for (const d of fs.readdirSync(npx)) {
      for (const name of ['playwright', 'playwright-core']) {
        const p = path.join(npx, d, 'node_modules', name);
        if (fs.existsSync(path.join(p, 'package.json'))) tries.push(p);
      }
    }
  }
  for (const t of tries) {
    try { return { pw: require(t), from: t }; } catch (e) { /* next */ }
  }
  return null;
}

function findChromium() {
  if (process.env.QDOJO_CHROMIUM && fs.existsSync(process.env.QDOJO_CHROMIUM)) return process.env.QDOJO_CHROMIUM;
  const root = path.join(HOME, '.cache/ms-playwright');
  if (!fs.existsSync(root)) return null;
  const dirs = fs.readdirSync(root).filter(d => /^chromium-\d+$/.test(d)).sort((a, b) => Number(b.split('-')[1]) - Number(a.split('-')[1]));
  for (const d of dirs) {
    for (const rel of ['chrome-linux64/chrome', 'chrome-linux/chrome', 'chrome-mac/Chromium.app/Contents/MacOS/Chromium', 'chrome-win/chrome.exe']) {
      const p = path.join(root, d, rel);
      if (fs.existsSync(p)) return p;
    }
  }
  return null;
}

// ---- a static server with an optional overlay directory ----------------------------

const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.txt': 'text/plain; charset=utf-8', '.py': 'text/plain; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.md': 'text/plain; charset=utf-8' };

// The site prefers a live export at data/combat/v1/ over the sample. A live
// runner may be writing one into this checkout, so apps/web's own live
// directory is hidden: the run is always on the committed sample, unless an
// overlay root (the tampered copy) provides a live export of its own.
const LIVE_PREFIX = '/data/combat/v1/', SAMPLE_PREFIX = '/data/combat/v1/sample/';
function serve(roots) {
  const server = http.createServer((req, res) => {
    let rel = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    if (rel.endsWith('/')) rel += 'index.html';
    for (const root of roots) {
      if (root === WEB && rel.startsWith(LIVE_PREFIX) && !rel.startsWith(SAMPLE_PREFIX)) continue;
      const file = path.join(root, rel);
      if (!file.startsWith(root)) break;
      if (fs.existsSync(file) && fs.statSync(file).isFile()) {
        res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream', 'Last-Modified': fs.statSync(file).mtime.toUTCString(), 'Cache-Control': 'no-cache' });
        fs.createReadStream(file).pipe(res);
        return;
      }
    }
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('not found');
  });
  return new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve({ server, base: 'http://127.0.0.1:' + server.address().port + '/' })));
}

// ---- sample facts, found by kind (never fixed IDs) ---------------------------------

const readJson = p => JSON.parse(fs.readFileSync(p, 'utf8'));
function sampleFacts() {
  const index = readJson(path.join(SAMPLE, 'index.json'));
  const replays = index.fights.map(id => {
    const p = path.join(SAMPLE, 'fights', String(id), 'replay.json');
    return fs.existsSync(p) ? readJson(p) : null;
  }).filter(Boolean);
  const kind = rp => (rp.result && rp.result.kind) || null;
  const settledRanked = replays.find(rp => rp.mode === 'ranked' && kind(rp) === 'COMBAT' && rp.settlement && rp.rounds.length >= 2);
  const duelFight = replays.find(rp => rp.mode === 'duel' && kind(rp) === 'COMBAT');
  const forfeit = replays.find(rp => kind(rp) === 'FORFEIT');
  const cups = (fs.existsSync(path.join(SAMPLE, 'cups.json')) ? readJson(path.join(SAMPLE, 'cups.json')).cups : []) || [];
  const duels = (fs.existsSync(path.join(SAMPLE, 'duels.json')) ? readJson(path.join(SAMPLE, 'duels.json')).duels : []) || [];
  const dep = index.deployment || {};
  const fighters = Object.entries(dep.fighters || {});
  const traded = fighters.find(([, m]) => m.asset && (m.asset.history || []).length > 1) || fighters[0];
  const book = readJson(path.join(SAMPLE, 'book.json'));
  return {
    index, settledRanked, duelFight, forfeit, book,
    cup: cups.find(c => c.champion) || cups[0], duel: duels.find(d => d.status === 'DONE') || duels[0],
    fighter: traded ? traded[0] : index.fighters[0], owner: traded ? traded[1].asset.owner : null,
  };
}

// ---- the run ----------------------------------------------------------------------

const results = [];
function record(name, ok, detail) { results.push({ name, ok, detail }); console.log((ok ? 'PASS ' : 'FAIL ') + name + (detail ? ': ' + detail : '')); }

async function main() {
  const found = findPlaywright(), chrome = findChromium();
  if (!found || !chrome) {
    console.log('web-e2e SKIPPED: ' + (!found ? 'no Playwright package found (set QDOJO_PLAYWRIGHT or run `npx playwright --version` once)' : 'no cached Chromium under ~/.cache/ms-playwright (run `npx playwright install chromium`, or set QDOJO_CHROMIUM)') + '.');
    return 0;
  }
  const only = process.env.QDOJO_E2E_ONLY ? new Set(process.env.QDOJO_E2E_ONLY.split(',')) : null;
  const want = n => !only || only.has(n);
  fs.mkdirSync(SHOTS, { recursive: true });
  for (const f of fs.readdirSync(SHOTS)) if (/^FAILED-.*\.png$/.test(f)) fs.rmSync(path.join(SHOTS, f));
  const facts = sampleFacts();
  const { chromium } = found.pw;
  const browser = await chromium.launch({ executablePath: chrome, args: ['--no-sandbox'] });
  const main = await serve([WEB]);
  console.log('chromium ' + chrome + '\nplaywright ' + found.from + '\nserving ' + WEB + ' at ' + main.base);

  // Every page is watched: page errors, console errors and failed requests
  // fail the step, except the live manifest 404 before the sample fallback.
  async function open(opts) {
    const ctx = await browser.newContext(Object.assign({ viewport: { width: 1200, height: 900 } }, opts || {}));
    const page = await ctx.newPage();
    const problems = [];
    page.on('pageerror', e => problems.push('pageerror: ' + e.message));
    page.on('console', m => {
      if (m.type() !== 'error') return;
      const url = (m.location() || {}).url || '';
      if (/Failed to load resource/.test(m.text()) && url.endsWith(LIVE_MANIFEST)) return;
      problems.push('console: ' + m.text() + (url ? ' @ ' + url : ''));
    });
    page.on('response', r => {
      if (r.status() >= 400 && !new URL(r.url()).pathname.endsWith(LIVE_MANIFEST)) problems.push('HTTP ' + r.status() + ' ' + r.url());
    });
    page.on('requestfailed', r => { if (!/fonts\.(googleapis|gstatic)\.com/.test(r.url())) problems.push('request failed: ' + r.url()); });
    return { ctx, page, problems };
  }

  async function step(name, fn, opts) {
    if (!want(name)) return;
    const { ctx, page, problems } = await open(opts && opts.context);
    try {
      const note = await fn(page, (opts && opts.base) || main.base);
      await page.waitForTimeout(150);
      if (problems.length) throw new Error(problems.join(' | '));
      record(name, true, note || '');
    } catch (e) {
      record(name, false, e.message.split('\n')[0]);
      try { await page.screenshot({ path: path.join(SHOTS, 'FAILED-' + name + '.png'), fullPage: true }); } catch (x) { /* ignore */ }
    } finally {
      await ctx.close();
    }
  }
  const shot = (page, name, full) => page.screenshot({ path: path.join(SHOTS, name + '.png'), fullPage: full !== false });
  const text = (page, sel) => page.textContent(sel).then(t => (t || '').replace(/\s+/g, ' ').trim());
  const must = async (cond, what) => { if (!cond) throw new Error('expected ' + what); };
  const go = async (page, base, hash, sel) => { await page.goto(base + hash); await page.waitForSelector(sel, { timeout: 15000 }); };

  // ---- views ----
  await step('title', async (page, base) => {
    await go(page, base, '#title', '.attract-card');
    await must((await text(page, '#hud-source')) === 'SAMPLE', 'the SAMPLE badge without live data');
    await must(await page.isHidden('#hud-stale'), 'no STALE badge on the sample');
    await shot(page, 'title', false);
  });
  await step('arena', async (page, base) => {
    await go(page, base, '#arena', '.sim-panel');
    const live = (facts.book.active_fights || []).length;
    const cards = await page.locator('.arena-card').count();
    await must(cards === live, live + ' live fight card(s), got ' + cards);
    const sim = await text(page, '.info-cols');
    await must(/SIMULATED CHAIN/.test(sim) && /DEMO PROFILE/.test(sim) && /PAIR STARTS/.test(sim), 'SIMULATED CHAIN and DEMO PROFILE panels');
    if (cards) await must(/TICKS? LEFT|DEADLINE PASSED/.test(await text(page, '.arena-card .arena-status')), 'ticks left on a live fight');
    await page.waitForTimeout(1200);
    await shot(page, 'arena');
    return cards + ' live';
  });
  await step('book', async (page, base) => { await go(page, base, '#book', 'text=OPEN OFFERS'); await shot(page, 'book'); });
  await step('results', async (page, base) => {
    await go(page, base, '#results', '.feed-row');
    await shot(page, 'results', false);
    return (await page.locator('.feed-row').count()) + ' rows';
  });
  await step('leaderboard', async (page, base) => {
    await go(page, base, '#leaderboard', 'table.board tbody tr');
    const rows = await page.locator('table.board tbody tr').count();
    await must(rows === facts.index.fighters.length, facts.index.fighters.length + ' fighters, got ' + rows);
    await shot(page, 'leaderboard');
  });
  await step('cups', async (page, base) => {
    await go(page, base, '#cups', 'text=ALL CUPS');
    await shot(page, 'cups', false);
  });
  if (facts.cup) await step('bracket', async (page, base) => {
    await go(page, base, '#cup/' + facts.cup.cup_id, '.bk-pair');
    await must((await page.locator('.bk-pair').count()) === facts.cup.pairings.length, facts.cup.pairings.length + ' pairings');
    if (facts.cup.champion) await must(await page.isVisible('.champ'), 'the champion banner');
    await must((await page.locator('.bk-in.in').count()) > 0, 'check-in marks');
    // each finished series shows its winner with the winning score
    for (const box of await page.locator('.bk-pair.bk-done').all()) {
      const head = (await box.locator('.bk-head').textContent()) || '';
      const need = (head.match(/FIRST TO (\d+)/) || [])[1];
      if (!need) continue;
      const won = (await box.locator('.bk-side.won .bk-score').textContent() || '').trim();
      await must(won === need, 'the series winner shows ' + need + ' wins, got ' + won + ' (' + head + ')');
    }
    await shot(page, 'bracket');
  });
  if (facts.duel) await step('duel', async (page, base) => {
    await go(page, base, '#duel/' + facts.duel.contest_id, '.duel-score');
    await must((await text(page, '.ds-num')).replace(/\s/g, '') === facts.duel.wins_a + '–' + facts.duel.wins_b, 'the series score');
    await shot(page, 'duel', false);
  });
  await step('duels', async (page, base) => { await go(page, base, '#duels', 'text=ALL DUELS'); });
  await step('season', async (page, base) => {
    await go(page, base, '#season', 'table.season');
    await must(/CHAMPION|PLAYOFF|NO CHAMPION/.test(await text(page, '.sstat')), 'a season status');
    await shot(page, 'season');
  });
  await step('fighter', async (page, base) => {
    await go(page, base, '#fighter/' + facts.fighter, '.drv');
    const panel = await text(page, '.fighter-panel');
    await must(/POLICY: |MODEL: |PLANNER/.test(panel), 'a driver badge');
    await must(/OWNERSHIP \(SIMULATED NFT\)/.test(await text(page, '#view')), 'the NFT history');
    await must((await page.locator('a[href^="#owner/"]').count()) > 0, 'an owner link');
    await shot(page, 'fighter');
  });
  if (facts.owner) await step('owner', async (page, base) => {
    await go(page, base, '#owner/' + facts.owner, 'text=FIGHTERS OWNED');
    await must((await page.locator('#view table tbody tr').count()) >= 1, 'an owned fighter');
    await shot(page, 'owner', false);
  });

  // ---- replay and verification ----
  const expectVerified = async page => {
    await page.waitForSelector('#level-slot .level:not(.level-PENDING)', { timeout: 15000 });
    const st = {};
    for (const li of await page.locator('li.check').all()) {
      const label = await li.locator('b').first().textContent();
      st[label] = (await li.locator('.vstat').first().textContent()).trim();
    }
    return { level: (await text(page, '#level-slot')), st };
  };
  if (facts.settledRanked) await step('replay', async (page, base) => {
    await go(page, base, '#fight/' + facts.settledRanked.fight_id, '.stage');
    const v = await expectVerified(page);
    await must(v.level === 'REPLAY MATCH', 'REPLAY MATCH, got ' + v.level);
    const want = { 'Ruleset digest matches the manifest': 'PASS', 'Input transactions confirmed on chain': 'UNAVAILABLE', 'Revealed plans and salts match their commitments': 'PASS', 'Independent replay reproduces every post-state and the outcome': 'PASS', 'Accounting and rating follow the outcome': 'PASS' };
    for (const [k, s] of Object.entries(want)) await must(v.st[k] === s, k + ' = ' + s + ', got ' + v.st[k]);
    await page.waitForTimeout(600 * 3);
    await must((await text(page, '.beat-headline')).length > 10, 'a beat headline');
    await shot(page, 'replay-mid', false);
    await page.focus('table.beats tr[data-i]');
    await page.keyboard.press('End');
    await must(/END/.test(await text(page, '.controls .pos')), 'End jumps to the result');
    await shot(page, 'replay');
    return v.level;
  });
  if (facts.duelFight) await step('replay-duel-link', async (page, base) => {
    await go(page, base, '#fight/' + facts.duelFight.fight_id, '.stage');
    await page.waitForSelector('#series-slot a', { timeout: 10000 });
    await must(/DUEL #/.test(await text(page, '#series-slot')), 'a link to its duel series');
  });
  if (facts.forfeit) await step('replay-forfeit', async (page, base) => {
    await go(page, base, '#fight/' + facts.forfeit.fight_id, '.stage');
    await expectVerified(page);
    await page.focus('#view');
    await must(/TIMEOUT/.test(await text(page, '.result-panel')), 'a forfeit reads TIMEOUT');
    await must(!/K\.O\./.test(await text(page, '.result-panel')), 'never a K.O. for a forfeit');
  });

  // Tampered export: a temp copy of the sample served as the LIVE export,
  // with one revealed salt changed. The same replay must now FAIL.
  if (facts.settledRanked && want('tampered')) {
    const tmpRoot = fs.mkdtempSync(path.join(process.env.QDOJO_E2E_TMP || os.tmpdir(), 'qdojo-e2e-'));
    try {
      const live = path.join(tmpRoot, 'data/combat/v1');
      fs.mkdirSync(path.dirname(live), { recursive: true });
      fs.cpSync(SAMPLE, live, { recursive: true });
      const f = path.join(live, 'fights', String(facts.settledRanked.fight_id), 'replay.json');
      const rp = readJson(f);
      const salt = rp.rounds[0].salts.A;
      rp.rounds[0].salts.A = (salt[0] === '0' ? '1' : '0') + salt.slice(1);
      fs.writeFileSync(f, JSON.stringify(rp));
      const tampered = await serve([tmpRoot, WEB]);
      await step('tampered', async (page, base) => {
        await go(page, base, '#fight/' + facts.settledRanked.fight_id, '.stage');
        await must((await text(page, '#hud-source')) === 'LIVE EXPORT', 'the temp copy served as the live export');
        const v = await expectVerified(page);
        await must(v.level === 'FAILED', 'FAILED, got ' + v.level);
        await must(v.st['Revealed plans and salts match their commitments'] === 'FAIL', 'the commitment check FAILs');
        await must(v.st['Independent replay reproduces every post-state and the outcome'] === 'PASS', 'the replay itself still PASSes');
        await shot(page, 'replay-tampered', false);
      }, { base: tampered.base });
      tampered.server.close();
    } finally {
      fs.rmSync(tmpRoot, { recursive: true, force: true });
    }
  }

  // ---- practice: play a round ----
  await step('practice', async (page, base) => {
    await go(page, base, '#practice', '.npc-card');
    await page.click('[data-npc="jabber-v1"]');
    await page.fill('#seed', 'ab'.repeat(32));
    await page.click('#go');
    await page.waitForSelector('#planner');
    for (const k of ['4', '1', '2', '6', '5', '1']) await page.keyboard.press(k);
    await page.click('#fight');
    await page.waitForSelector('tr.fr-beat');
    await must((await page.locator('tr.fr-beat').count()) >= 1, 'resolved beats');
    await must(/REVEALED NPC PLANS/.test(await text(page, '#view')), 'the NPC plan revealed after the round');
    await page.waitForTimeout(600 * 3);
    await shot(page, 'practice');
  });
  await step('rules', async (page, base) => {
    await go(page, base, '#rules', '#digest .vstat');
    await must((await text(page, '#digest .vstat')) === 'PASS', 'the ruleset digest PASSes');
    await must(/VERIFICATION LEVELS/.test(await text(page, '#view')), 'verification levels');
    await shot(page, 'rules');
  });
  await step('help', async (page, base) => { await go(page, base, '#help', '.help-kv'); await shot(page, 'help', false); });
  await step('join', async (page, base) => {
    await go(page, base, '#join', '#planner-src');
    await page.waitForFunction(() => !/^Loading/.test(document.querySelector('#planner-src').textContent));
    await must(/paid play is not live yet/i.test(await text(page, '#view')), 'the not-live statement');
    await shot(page, 'join');
  });
  await step('redirect', async (page, base) => {
    await page.goto(base + 'combat.html#rules');
    await page.waitForSelector('#digest');
    await must(new URL(page.url()).pathname === '/' && page.url().endsWith('#rules'), 'combat.html redirects to / and keeps the hash');
  });
  await step('legacy', async (page, base) => {
    await page.goto(base + 'legacy.html');
    await page.waitForSelector('.legacy-banner');
    await must(/RIDDLES ARE RETIRED/.test(await text(page, '.legacy-banner')), 'the retired banner');
    await page.waitForTimeout(800);
    await shot(page, 'legacy', false);
  });

  // ---- reduced motion: the same information, nothing moving ----
  if (facts.settledRanked) await step('reduced-motion', async (page, base) => {
    await go(page, base, '#fight/' + facts.settledRanked.fight_id, '.stage');
    await expectVerified(page);
    await must(/OFF \(SYSTEM\)/.test(await text(page, '#btn-motion')), 'MOTION: OFF (SYSTEM)');
    await must(/PLAY/.test(await text(page, '[data-act=play]')) && !/PAUSE/.test(await text(page, '[data-act=play]')), 'no autoplay');
    // with motion off the replay opens on its result; step from the start
    await must(/END/.test(await text(page, '.controls .pos')), 'reduced motion opens on the result, not a moving replay');
    await page.focus('table.beats tr[data-i]');
    await page.keyboard.press('Home');
    for (let i = 0; i < 4; i++) await page.keyboard.press('ArrowRight');
    const reduced = { head: await text(page, '.beat-headline'), hp: await text(page, '.corner-A .cbar-hp .cbar-num'), pos: await text(page, '.controls .pos') };
    // the same frame with motion on shows the same words and numbers
    const other = await open();
    try {
      await go(other.page, base, '#fight/' + facts.settledRanked.fight_id, '.stage');
      await other.page.click('[data-act=first]');
      for (let i = 0; i < 4; i++) await other.page.click('[data-act=next]');
      const moving = { head: await text(other.page, '.beat-headline'), hp: await text(other.page, '.corner-A .cbar-hp .cbar-num'), pos: await text(other.page, '.controls .pos') };
      await must(JSON.stringify(moving) === JSON.stringify(reduced), 'parity: ' + JSON.stringify(reduced) + ' vs ' + JSON.stringify(moving));
    } finally { await other.ctx.close(); }
    await shot(page, 'replay-reduced', false);
  }, { context: { reducedMotion: 'reduce' } });

  // ---- 375 px phone ----
  const phone = { viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true };
  for (const [name, hash, sel] of [['mobile-arena', '#arena', '.sim-panel'], ['mobile-replay', '#fight/' + (facts.settledRanked || {}).fight_id, '.stage'],
    ['mobile-bracket', '#cup/' + (facts.cup || {}).cup_id, '.bk-pair'], ['mobile-season', '#season', 'table.season'], ['mobile-leaderboard', '#leaderboard', 'table.board']]) {
    await step(name, async (page, base) => {
      await go(page, base, hash, sel);
      const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      await must(over <= 1, 'no sideways page scroll at 375 px (overflow ' + over + ' px)');
      await shot(page, name, false);
    }, { context: phone });
  }

  main.server.close();
  await browser.close();
  const failed = results.filter(r => !r.ok);
  console.log('\nweb-e2e: ' + (results.length - failed.length) + '/' + results.length + ' steps passed; screenshots in ' + path.relative(process.cwd(), SHOTS));
  return failed.length ? 1 : 0;
}

main().then(code => process.exit(code), e => { console.error(e); process.exit(2); });
