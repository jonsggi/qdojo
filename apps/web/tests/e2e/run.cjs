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
 * requires FAIL, checks reduced-motion parity, a 375 px phone width and the
 * practice deck on phone screens 664 to 844 px tall, on a phone turned
 * sideways and back and after a playback skipped or paused (AUD-036), and
 * saves screenshots to apps/web/tests/e2e/shots/ (gitignored).
 *
 * Needs the Playwright package and its Chromium; without them it prints why
 * and exits 0, so it never breaks a machine that cannot run a browser. It is
 * deliberately not part of `node --test` / `make test`.
 *
 * Environment: QDOJO_PLAYWRIGHT (path to a playwright package),
 * QDOJO_CHROMIUM (browser binary), QDOJO_E2E_TMP (temp dir root),
 * QDOJO_E2E_ONLY (comma-separated step names), QDOJO_E2E_REQUIRED=1 (fail
 * instead of skipping without a browser, and refuse QDOJO_E2E_ONLY; make release-check).
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
// Beside a live export the site probes the optional read API; this server has none.
const API_STATUS = '/api/v1/status';
const expected404 = u => { const p = new URL(u, 'http://x').pathname; return p.endsWith(LIVE_MANIFEST) || p === API_STATUS; };

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

/* The export against itself (AUD-025): no live fight past its deadline at
 * the export's tick, and every fight in results.json published as DONE. A
 * file frozen mid-round after its fight ended fails here. */
function exportProblems(root) {
  const out = [];
  const index = readJson(path.join(root, 'index.json'));
  const tick = BigInt(index.generated_tick);
  const fight = id => { const p = path.join(root, 'fights', String(id) + '.json'); return fs.existsSync(p) ? readJson(p) : null; };
  for (const id of index.active_fights || []) {
    const f = fight(id);
    if (!f) { out.push('active fight ' + id + ' has no file'); continue; }
    const last = f.phase === 'COMMIT' ? f.commit_last : f.phase === 'REVEAL' ? f.reveal_last : null;
    if (last == null) out.push('active fight ' + id + ' published as ' + f.phase);
    else if (BigInt(last) < tick) out.push('fight ' + id + ' overdue: ' + f.phase + ' deadline ' + last + ' < tick ' + tick);
  }
  const results = fs.existsSync(path.join(root, 'results.json')) ? readJson(path.join(root, 'results.json')).results || [] : [];
  for (const r of results) {
    const f = fight(r.fight_id);
    if (f && f.phase !== 'DONE') out.push('fight ' + r.fight_id + ' finished in results.json but published as ' + f.phase);
  }
  return out;
}

// ---- the run ----------------------------------------------------------------------

const results = [];
function record(name, ok, detail) { results.push({ name, ok, detail }); console.log((ok ? 'PASS ' : 'FAIL ') + name + (detail ? ': ' + detail : '')); }

async function main() {
  const found = findPlaywright(), chrome = findChromium();
  const required = process.env.QDOJO_E2E_REQUIRED === '1';
  if (!found || !chrome) {
    const why = !found ? 'no Playwright package found (set QDOJO_PLAYWRIGHT or run `npx playwright --version` once)' : 'no cached Chromium under ~/.cache/ms-playwright (run `npx playwright install chromium`, or set QDOJO_CHROMIUM)';
    // A release check must not pass on a machine that could not run the browser (AUD-041).
    if (required) { console.log('web-e2e FAILED: QDOJO_E2E_REQUIRED=1 but ' + why + '.'); return 3; }
    console.log('web-e2e SKIPPED: ' + why + '.');
    return 0;
  }
  if (required && process.env.QDOJO_E2E_ONLY) { console.log('web-e2e FAILED: QDOJO_E2E_REQUIRED=1 runs every step; unset QDOJO_E2E_ONLY.'); return 3; }
  const only = process.env.QDOJO_E2E_ONLY ? new Set(process.env.QDOJO_E2E_ONLY.split(',')) : null;
  const want = n => !only || only.has(n);
  fs.mkdirSync(SHOTS, { recursive: true });
  for (const f of fs.readdirSync(SHOTS)) if (/^FAILED-.*\.png$/.test(f)) fs.rmSync(path.join(SHOTS, f));
  const facts = sampleFacts();
  if (want('export-consistency')) {
    const bad = exportProblems(SAMPLE);
    record('export-consistency', bad.length === 0, bad.length ? bad.slice(0, 3).join('; ') : 'live fights within deadline; finished fights published as finished');
  }
  const { chromium } = found.pw;
  const browser = await chromium.launch({ executablePath: chrome, args: ['--no-sandbox'] });
  const main = await serve([WEB]);
  console.log('chromium ' + chrome + '\nplaywright ' + found.from + '\nserving ' + WEB + ' at ' + main.base);

  // Every page is watched: page errors, console errors and failed requests
  // fail the step, except the live manifest 404 before the sample fallback
  // and the read API probe's 404 (no API here).
  async function open(opts) {
    const ctx = await browser.newContext(Object.assign({ viewport: { width: 1200, height: 900 } }, opts || {}));
    const page = await ctx.newPage();
    const problems = [];
    page.on('pageerror', e => problems.push('pageerror: ' + e.message));
    page.on('console', m => {
      if (m.type() !== 'error') return;
      const url = (m.location() || {}).url || '';
      if (/Failed to load resource/.test(m.text()) && url && expected404(url)) return;
      problems.push('console: ' + m.text() + (url ? ' @ ' + url : ''));
    });
    page.on('response', r => {
      if (r.status() >= 400 && !(r.status() === 404 && expected404(r.url()))) problems.push('HTTP ' + r.status() + ' ' + r.url());
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
    await must((await text(page, '#hud-net')) === 'DEVNET' && await page.isVisible('#hud-net'), 'the DEVNET network badge from deployment.kind');
    await must(/recorded sample: the arena is offline/i.test(await text(page, '#foot-net')), 'the offline-sample footer line');
    await must(await page.getAttribute('#t-play', 'href') === '#practice' && await page.getAttribute('#t-watch', 'href') === '#arena', 'PLAY goes to practice, WATCH to the arena');
    await must(/FOUR STEPS/.test(await text(page, '#t-path')), 'the first-session path');
    await shot(page, 'title', false);
  });
  await step('arena', async (page, base) => {
    await go(page, base, '#arena', '.sim-panel');
    const live = (facts.book.active_fights || []).length;
    const cards = await page.locator('.arena-card').count();
    await must(cards === live, live + ' live fight card(s), got ' + cards);
    const sim = await text(page, '.info-cols');
    await must(/NETWORK: DEVNET/.test(sim) && /devnet QU/.test(sim) && /ARENA LIMITS/.test(sim) && /PAIR STARTS/.test(sim), 'NETWORK: DEVNET and ARENA LIMITS panels');
    // A live fight shows the ticks left before its deadline. "DEADLINE PASSED"
    // means the export is behind the contract (AUD-011, AUD-025): a failure.
    const statuses = (await page.locator('.arena-card .arena-status').allTextContents()).map(t => t.replace(/\s+/g, ' ').trim());
    for (const st of statuses) {
      await must(!/DEADLINE PASSED/.test(st), 'no overdue live fight, got "' + st + '"');
      await must(/TICKS? LEFT/.test(st), 'ticks left on every live fight, got "' + st + '"');
    }
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
    // each finished series shows its winner with the winning score; a forfeit
    // ends a series without a series win (competition.md §4), so those are skipped
    const fightFile = id => path.join(SAMPLE, 'fights', String(id) + '.json');
    const forfeited = new Set((facts.cup.pairings || []).filter(p => (p.fights || []).some(id =>
      fs.existsSync(fightFile(id)) && ((readJson(fightFile(id)).result || {}).kind === 'FORFEIT'))).map(p => String(p.pairing_id)));
    for (const box of await page.locator('.bk-pair.bk-done').all()) {
      const head = (await box.locator('.bk-head').textContent()) || '';
      const need = (head.match(/FIRST TO (\d+)/) || [])[1];
      if (!need || forfeited.has((head.match(/PAIRING (\d+)/) || [])[1])) continue;
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
    await must(/OWNERSHIP \(DEVNET NFT\)/.test(await text(page, '#view')), 'the NFT history');
    await must((await page.locator('a[href^="#owner/"]').count()) > 0, 'an owner link');
    await shot(page, 'fighter');
  });
  if (facts.owner) await step('owner', async (page, base) => {
    await go(page, base, '#owner/' + facts.owner, 'text=FIGHTERS OWNED');
    await must((await page.locator('#view table tbody tr').count()) >= 1, 'an owned fighter');
    await shot(page, 'owner', false);
  });

  // ---- fighter NFTs (docs/nft.md) ----
  const nfts = fs.existsSync(path.join(SAMPLE, 'nfts.json')) ? readJson(path.join(SAMPLE, 'nfts.json')) : null;
  if (nfts) await step('collection', async (page, base) => {
    await go(page, base, '#collection', '.nft-card');
    await must((await page.locator('.nft-card').count()) === nfts.tokens.length, 'one card per token');
    const listed = nfts.tokens.filter(t => t.ask).length;
    await page.check('#nft-sale');
    await must((await page.locator('.nft-card').count()) === listed, listed + ' cards for sale');
    await must(/HOW TO BUY/.test(await text(page, '#view')) && /no monetary value/.test(await text(page, '#view')) && /no button that spends anything/.test(await text(page, '#view')), 'the honest how-to-buy box');
    await must((await page.locator('#view button, #view [data-wallet]').count()) === 0, 'no wallet action');
    await shot(page, 'collection');
  });
  if (nfts) await step('collection-phone', async (page, base) => {
    await go(page, base, '#collection', '.nft-card');
    const wide = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    await must(wide <= 0, 'no horizontal scroll at 390 px (got ' + wide + ')');
    await shot(page, 'collection-390');
  }, { context: { viewport: { width: 390, height: 844 } } });
  if (nfts) await step('nft', async (page, base) => {
    const t = nfts.tokens.find(x => x.last_sale) || nfts.tokens[0];
    await go(page, base, '#nft/' + t.fighter_id, '.nft-events li');
    const v = await text(page, '#view');
    await must(/PROVENANCE/.test(v) && /MINTED/.test(v) && /WHO HOLDS IT/.test(v), 'provenance and holders');
    if (t.frozen) {
      await page.waitForSelector('#nft-frozen .nft-tag-frozen', { timeout: 15000 });
      await must(/ART MATCHES/.test(await text(page, '#nft-frozen')), 'the card to match its frozen master');
    }
    await shot(page, 'nft');
  });
  if (nfts) await step('fighter-nft-hook', async (page, base) => {
    await go(page, base, '#fighter/' + nfts.tokens[0].fighter_id, '.nft-hook');
    await must((await page.getAttribute('.nft-hook', 'href')) === '#nft/' + nfts.tokens[0].fighter_id, 'a link to the token page');
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
        await must((await text(page, '#hud-source')) === 'LIVE', 'the temp copy served as the live export');
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
    await page.click('.select-adv summary');   // the seed sits under ADVANCED
    await page.fill('#seed', 'ab'.repeat(32));
    await page.click('#go');
    await page.waitForSelector('#planner');
    // A desktop keeps its layout (AUD-036 changes phones only): an unpinned
    // arena, the page at the top, the deck after the replay controls and headline.
    await must(await page.$eval('.practice-stage .stage', el => getComputedStyle(el).position) === 'relative', 'an unpinned arena on a desktop (only phones pin it, AUD-036)');
    await must(await page.evaluate(() => scrollY) === 0 && !!(await page.$('#player .beat-headline + #planner')), 'a desktop round opening at the top, its deck under the replay headline');
    await must(await page.$eval('#to-deck', el => getComputedStyle(el).display) === 'none', 'no YOUR MOVES button on a desktop (the deck is under the replay there)');
    for (const k of ['4', '1', '2', '6', '5', '1']) await page.keyboard.press(k);
    await must(await page.evaluate(() => scrollY) === 0, 'typing the moves leaving a desktop page at the top');
    await page.click('#fight');
    await page.waitForSelector('tr.fr-beat', { state: 'attached' });   // the beat table is folded in practice
    await must((await page.locator('tr.fr-beat').count()) >= 1, 'resolved beats');
    await must(/REVEALED NPC PLANS/.test(await text(page, '#view')), 'the NPC plan revealed after the round');
    await page.waitForTimeout(600 * 3);
    await shot(page, 'practice');
    // Keys pressed while writing round 2 stay in the planner (AUD-036): the
    // beats are a listbox (arrows, HOME, END, SPACE pick a beat) and no key
    // steps, rewinds or plays the replay above it, so the arena keeps showing
    // the state you plan from; nor does the page scroll.
    await page.waitForFunction(() => /ROUND 2/.test(document.querySelector('#planner h3').textContent));
    await page.evaluate(() => { const p = document.querySelector('[data-act=play]'); if (p.textContent === 'PAUSE') p.click(); document.querySelector('[data-act=last]').click(); });
    const at = await text(page, '.controls .pos');
    const selected = () => page.$eval('#planner .slot[aria-selected="true"]', el => el.dataset.slot);
    await page.click('#planner .slot[data-slot="2"]');
    const y0 = await page.evaluate(() => scrollY);
    const seen = [];
    for (const k of ['ArrowLeft', 'ArrowLeft', 'End', 'Home', 'ArrowRight', 'k']) { await page.keyboard.press(k); seen.push(await selected()); }
    await page.focus('#planner .slot[data-slot="4"]'); await page.keyboard.press(' '); seen.push(await selected());
    await must(seen.join('') === '1050114', 'arrows, END, HOME and SPACE picking beats 1 0 5 0 1 1 4 (got ' + seen.join(' ') + ')');
    await must(await text(page, '.controls .pos') === at && await text(page, '[data-act=play]') === 'PLAY', 'keys in the planner leaving the replay on ' + at + ' (now ' + await text(page, '.controls .pos') + ')');
    await must(await page.evaluate(() => scrollY) === y0, 'keys in the planner not scrolling the page');
  });
  // ---- practice: a whole fight, its debrief, and the share link in a fresh session ----
  let shared = null;
  await step('practice-debrief', async (page, base) => {
    await go(page, base, '#practice', '#pr-coach');
    await must(/RECORD/.test(await text(page, '#pr-ladder')), 'the practice record panel');
    await page.click('[data-npc="jabber-v1"]');
    await page.click('.select-adv summary');
    await page.fill('#seed', 'cd'.repeat(32));
    await page.click('#go');
    await page.waitForSelector('#planner');
    for (let r = 0; r < 3 && await page.$('#planner'); r++) {
      await page.click('.slot[data-slot="0"]');
      for (const k of ['4', '4', '4', '2', '4', '4']) await page.keyboard.press(k);
      await page.click('#fight');
      await page.waitForTimeout(300);
    }
    await page.waitForSelector('#debrief');
    await must(/KEY BEATS/.test(await text(page, '#debrief')) && /TRY NEXT/.test(await text(page, '#debrief')), 'key beats and a tip in the debrief');
    await must(/vs JABBER: (1W 0L|0W 1L|0W 0L 1D)/.test(await text(page, '#pr-result')), 'the fight recorded once: ' + await text(page, '#pr-result'));
    await page.click('.db-seek');
    await must(/^R\d B\d/.test(await text(page, '.controls .pos')), 'a key beat seeks the replay');
    await page.waitForSelector('#share-link');
    shared = { url: await page.getAttribute('#share-link', 'href'), verdict: await text(page, '.result-big'),
      beats: await page.$$eval('tr.fr-beat', t => t.map(r => r.innerText.replace(/\s+/g, ' '))) };
    await must(/\/p1\.1\.[0-9a-f]{16}\.[0-8n-]+\.[0-9a-f]{8}$/.test(shared.url), 'a p1 replay link: ' + shared.url);
    await must(page.url().endsWith(shared.url.split('#')[1]), 'the address bar holds the replay link');
    await page.reload(); await page.waitForSelector('#share-check');
    await must(!(await page.$('#pr-result')), 'a reload does not record the fight again');
    await shot(page, 'practice-result');
  });
  if (shared) await step('practice-share', async (page, base) => {
    await page.goto(shared.url); await page.waitForSelector('#share-check');
    await must(/matches/.test(await text(page, '#share-check')), 'the check value matches');
    await must(await text(page, '.result-big') === shared.verdict, 'the same verdict');
    const beats = await page.$$eval('tr.fr-beat', t => t.map(r => r.innerText.replace(/\s+/g, ' ')));
    await must(JSON.stringify(beats) === JSON.stringify(shared.beats), 'the same executed beats (' + beats.length + ')');
    await page.goto(shared.url.replace(/[0-9a-f]{8}$/, '00000000')); await page.waitForSelector('#share-check');
    await must(/MISMATCH/.test(await text(page, '#share-check')), 'a tampered link shows MISMATCH');
    await page.goto(shared.url.replace('/p1.', '/p7.')); await page.waitForSelector('#share-bad');
    await must(/format/.test(await text(page, '#share-bad')), 'an unsupported link is refused with a reason');
  });
  await step('practice-no-storage', async (page, base) => {
    await page.addInitScript(() => { Object.defineProperty(window, 'localStorage', { get() { throw new Error('blocked'); } }); });
    await go(page, base, '#practice', '#pr-ladder');
    await must(/not saving/.test(await text(page, '.pr-note')), 'a storage-blocked note');
    await page.click('#go'); await page.waitForSelector('#planner');
    for (const k of ['4', '4', '4', '2', '4', '4']) await page.keyboard.press(k);
    await page.click('#fight');
    await page.waitForSelector('tr.fr-beat', { state: 'attached' });
  });

  // ---- practice on a phone (AUD-036): the deck within reach, the fight in view ----
  // While a round is open the arena is pinned at the top of the screen and the
  // page opens on the deck, with no scrolling by the player or by this test.
  // On arrival, mid-round and when the next round is planned, the six beats,
  // every move, POWER, CLEAR and FIGHT are on screen, each the topmost element
  // at its centre, none on an HP bar or under the arena (the whole box, not
  // just its centre), and both fighters' HP and stamina bars and POWER /
  // OPENING / GUARD strips are on screen, uncovered. One deck (the planner
  // straight after the arena, the replay controls after the planner), no
  // sideways scroll, and taps never move the page. The arena keeps one height
  // on every frame of a replay, so the deck under it never moves. With motion
  // on, the replay controls and the beat headline sit under the arena while
  // the round plays back, and the page lands on the deck again when it ends;
  // with motion off it lands there at once. The arena names the round being
  // planned, and the beats are a keyboard listbox whose focus moves with the
  // selection. Sizes: 390 x 844 and 360 x 740 (the first fight's coach tip on
  // that screen too, with six and with eight moves), and short screens such
  // as a browser with its toolbars showing (375 x 667, 390 x 664, 360 x 700).
  const deckView = page => page.evaluate(() => {
    const vw = innerWidth, vh = innerHeight, bad = [];
    const label = el => el.id || (el.dataset.a != null ? 'move ' + el.dataset.a : el.dataset.pw != null ? 'POWER ' + el.dataset.pw : el.dataset.slot != null ? 'beat ' + el.dataset.slot
      : (el.classList.contains('flags') ? 'flags' : el.classList.contains('cbar-hp') ? 'HP bar' : 'stamina bar') + ' ' + el.closest('.corner').dataset.side);
    const box = el => el.getBoundingClientRect();
    const onScreen = b => b.top >= 0 && b.left >= 0 && b.bottom <= vh && b.right <= vw;
    // The topmost element at the centre is the element itself (a disabled
    // FIGHT lets the pointer through to its own row).
    const onTop = el => { const b = box(el), h = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2); return !!h && (el.contains(h) || (el.disabled && el.parentElement.contains(h))); };
    const meets = (p, q) => p.left < q.right && q.left < p.right && p.top < q.bottom && q.top < p.bottom;
    const stage = document.querySelector('.practice-stage .stage'), fight = document.querySelector('#fight'), tip = document.querySelector('#pr-tip');
    const controls = [...document.querySelectorAll('#planner .slot, #planner .slot-pw, #planner .act-btn, #fight, #clear')];
    const state = [...document.querySelectorAll('.practice-stage .cbar-hp, .practice-stage .cbar-st, .practice-stage .flags')];
    const hp = state.filter(el => el.classList.contains('cbar-hp'));
    for (const el of controls.concat(state)) if (!onScreen(box(el))) bad.push(label(el) + ' off screen'); else if (!onTop(el)) bad.push(label(el) + ' covered');
    for (const el of controls) if (hp.some(x => meets(box(el), box(x)))) bad.push(label(el) + ' on an HP bar'); else if (meets(box(el), box(stage))) bad.push(label(el) + ' under the arena');
    return { bad, over: document.documentElement.scrollWidth - innerWidth, y: Math.round(scrollY), planners: document.querySelectorAll('#planner').length,
      moves: document.querySelectorAll('.act-btn').length, fights: document.querySelectorAll('#fight').length, filled: document.querySelectorAll('#planner .slot.filled').length,
      pinned: getComputedStyle(stage).position === 'sticky', order: !!document.querySelector('#player > .stage + #planner') && !!document.querySelector('#player > #planner ~ .controls'),
      round: document.querySelector('.practice-stage .round-no').textContent, list: document.querySelector('#planner .slots').getAttribute('aria-label'),
      tip: tip && { top: Math.round(box(tip).top), bottom: Math.round(box(tip).bottom), afterFight: box(tip).top >= box(fight).bottom } };
  });
  // Waits out a smooth scroll: the page has not moved for 300 ms.
  const still = page => page.waitForFunction(() => new Promise(r => { let y = scrollY, n = 0; const t = setInterval(() => { if (scrollY !== y) { y = scrollY; n = 0; } else if (++n >= 6) { clearInterval(t); r(true); } }, 50); }), null, { timeout: 10000 });
  // The same page under candidate 3 (eight moves): the manifest names that
  // ruleset and its artifact is the embedded copy, so nothing 404s.
  async function asCandidate3(page) {
    const L = require(path.join(WEB, 'combat/logic.js'));
    require(path.join(WEB, 'combat/ruleset.js'));
    const rules = globalThis.QDojoRulesets.find(r => r.semantic_version === 'combat-v1-candidate-3');
    const digest = await L.rulesetDigest(rules, L.defaultSha256());
    const manifest = Object.assign(readJson(path.join(SAMPLE, 'manifest.json')), { ruleset_digest: digest, semantic_version: rules.semantic_version });
    await page.route(/\/data\/combat\/v1\/sample\/manifest\.json$/, r => r.fulfill({ json: manifest }));
    await page.route(new RegExp('/data/combat/v1/sample/rulesets/' + digest + '\\.json$'), r => r.fulfill({ json: { schema: 'qdojo.combat.ruleset.v1', semantic_version: rules.semantic_version, digest, rules } }));
  }
  // A returning player: the first fight is behind them, so no coach tip.
  const returning = page => page.addInitScript(() => { try { localStorage.setItem('qdojo.practice.v1', JSON.stringify({ v: 1, rules: {}, seen: [], steps: { named: true, fought: true } })); } catch (e) { /* storage blocked */ } });
  const phoneCtx = (w, h, rm) => Object.assign({ viewport: { width: w, height: h }, isMobile: true, hasTouch: true }, rm ? { reducedMotion: 'reduce' } : {});
  // options: rm (reduced motion), v3 (eight moves), back (a returning player), tip (the coach tip on the first screen too)
  for (const [name, w, h, o] of [['practice-phone', 390, 844, { tip: true }], ['practice-phone-360', 360, 740, { rm: true, tip: true }], ['practice-phone-360-v3', 360, 740, { rm: true, v3: true, tip: true }],
    ['practice-phone-v3', 390, 844, { v3: true, back: true }], ['practice-phone-667', 375, 667, { rm: true, back: true }], ['practice-phone-664', 390, 664, { rm: true, v3: true }], ['practice-phone-700', 360, 700, { rm: true, back: true }]]) {
    await step(name, async (page, base) => {
      if (o.v3) await asCandidate3(page);
      if (o.back) await returning(page);
      await go(page, base, '#practice/jabber-v1/' + 'ab'.repeat(32), '#planner');
      await page.evaluate(() => document.fonts.ready);
      await still(page);
      const moves = o.v3 ? 8 : 6, size = w + 'x' + h;
      // arrival: the page opens on the deck
      let v = await deckView(page);
      await must(v.planners === 1 && v.moves === moves && v.fights === 1, 'one deck of ' + moves + ' moves and one FIGHT (got ' + v.planners + ' decks, ' + v.moves + ' moves, ' + v.fights + ' FIGHT)');
      await must(v.pinned && v.order, 'the arena pinned while planning at ' + size + ', the deck straight after it and the replay controls after the deck');
      await must(v.over <= 0, 'no sideways scroll at ' + w + ' px (overflow ' + v.over + ' px)');
      await must(!v.bad.length, 'the beats, the deck, POWER, CLEAR, FIGHT and both fighters\' HP, stamina and flags on the first screen at ' + size + ' (' + v.bad.join(', ') + ')');
      await must(v.round === 'ROUND 1/3' && v.list === 'Your plan for round 1', 'the arena and the beats naming round 1 (got ' + v.round + ', ' + v.list + ')');
      if (o.back) await must(!v.tip, 'no coach tip for a returning player');
      else await must(v.tip && v.tip.afterFight && (!o.tip || v.tip.bottom <= h), 'the first fight\'s coach tip under FIGHT' + (o.tip ? ', on that screen' : '') + ' (' + JSON.stringify(v.tip) + ')');
      const arena = await page.$eval('.practice-stage .stage', el => el.offsetHeight);
      await shot(page, name + '-plan', false);
      // mid-round: taps fill beats in place, POWER goes on the JAB, nothing moves
      for (const a of ['3', '0', '1']) await page.tap('#planner .act-btn[data-a="' + a + '"]');
      await page.tap('#planner .slot[data-slot="1"] .slot-pw');
      const mid = await deckView(page);
      await must(mid.filled === 3 && mid.y === v.y && !mid.bad.length, 'three beats filled without moving the screen (' + mid.filled + ' filled, scroll ' + v.y + ' to ' + mid.y + (mid.bad.length ? '; ' + mid.bad.join(', ') : '') + ')');
      await must(await page.getAttribute('#planner .slot[data-slot="1"] .slot-pw', 'aria-pressed') === 'true', 'POWER on the JAB');
      await shot(page, name + '-mid', false);
      // FIGHT: round 1 plays back in the arena
      for (const a of ['5', '4', '0']) await page.tap('#planner .act-btn[data-a="' + a + '"]');
      await page.tap('#fight');
      await page.waitForFunction(() => /ROUND 2/.test((document.querySelector('#planner h3') || {}).textContent || ''));
      if (!o.rm) {
        // While it plays: the replay controls and the beat headline right under the arena.
        await page.waitForFunction(() => { const q = s => document.querySelector(s).getBoundingClientRect(), a = q('.practice-stage .stage'), c = q('#player .controls'), hl = q('#player .beat-headline');
          return /^R1 B\d/.test(document.querySelector('.controls .pos').textContent) && document.querySelector('[data-act=play]').textContent === 'PAUSE' && c.top >= a.bottom && hl.bottom <= innerHeight; }, null, { timeout: 8000 });
        await must(await page.evaluate(() => { const p = document.querySelector('[data-act=play]'), b = p.getBoundingClientRect(), t = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2); return !!t && p.contains(t) && document.querySelector('#player .beat-headline').textContent.length > 10; }),
          'PAUSE and the beat headline on screen while the round plays');
        await shot(page, name + '-playing', false);
        // The controls hold still under the arena on every beat (the arena keeps its height).
        await still(page);
        const tops = await page.evaluate(async () => { const q = s => document.querySelector(s), seen = new Set();
          while (q('[data-act=play]').textContent === 'PAUSE') { if (/B\d/.test(q('.controls .pos').textContent)) seen.add(Math.round(q('#player .controls').getBoundingClientRect().top)); await new Promise(r => setTimeout(r, 50)); }
          return [...seen]; });
        await must(tops.length === 1, 'the replay controls holding still while the round plays (at ' + tops.join(', ') + ' px)');
        // When it has played to the end, the page goes back to the deck.
        await page.waitForFunction(() => document.querySelector('[data-act=play]').textContent === 'PLAY', null, { timeout: 15000 });
        await page.waitForFunction(() => { const q = s => document.querySelector(s).getBoundingClientRect(); return q('#planner .slots').top >= q('.practice-stage .stage').bottom && q('#fight').bottom <= innerHeight; }, null, { timeout: 8000 }).catch(() => {});
      }
      await still(page);
      // round 2 is written on the screen the page lands on
      v = await deckView(page);
      await must(!v.bad.length && v.filled === 0, 'round 2 on the screen the page lands on (' + v.bad.join(', ') + ')');
      await must(v.over <= 0, 'no sideways scroll after the round (overflow ' + v.over + ' px)');
      await must(v.round === 'ROUND 2/3' && v.list === 'Your plan for round 2', 'the arena and the beats naming round 2 while it is planned (got ' + v.round + ', ' + v.list + ')');
      await shot(page, name + '-round2', false);
      // Stepped through frame by frame, the arena keeps its height and the page and the beats hold still.
      const seen = { h: new Set([arena]), y: new Set(), top: new Set() };
      const ctl = act => page.evaluate(a => document.querySelector('[data-act=' + a + ']').click(), act);
      await ctl('first');
      for (let i = 0; i < 12; i++) {
        const s = await page.evaluate(() => ({ y: Math.round(scrollY), pos: document.querySelector('.controls .pos').textContent, h: document.querySelector('.practice-stage .stage').offsetHeight,
          top: Math.round(document.querySelector('#planner .slots').getBoundingClientRect().top) }));
        seen.h.add(s.h); seen.y.add(s.y); seen.top.add(s.top);
        if (/BREAK|END/.test(s.pos)) break;
        await ctl('next');
      }
      await must(seen.h.size === 1 && seen.y.size === 1 && seen.top.size === 1, 'one arena height, scroll and beat row on every frame (heights ' + [...seen.h].join(', ') + '; scroll ' + [...seen.y].join(', ') + '; beats at ' + [...seen.top].join(', ') + ')');
      // The beats are a listbox: the focus moves with the selection, DOWN a row, and the page holds still.
      const y0 = await page.evaluate(() => scrollY);
      await page.focus('#planner .slot[data-slot="1"]');
      await page.keyboard.press('ArrowDown');
      await must(await page.evaluate(() => document.activeElement.dataset.slot === '4' && document.querySelector('#planner .slot[aria-selected="true"]').dataset.slot === '4' && document.activeElement.tabIndex === 0), 'DOWN moving the focus and the selection from beat 2 to beat 5');
      await must(await page.evaluate(() => scrollY) === y0, 'keys in the beats not scrolling the page');
      // the replay controls follow the deck: focused, PLAY comes into view clear of the arena
      await page.focus('[data-act=play]');
      await still(page);
      await must(await page.evaluate(() => { const p = document.querySelector('[data-act=play]'), b = p.getBoundingClientRect(), t = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
        return b.top >= document.querySelector('.practice-stage .stage').getBoundingClientRect().bottom && b.bottom <= innerHeight && !!t && p.contains(t); }), 'the focused PLAY button on screen, clear of the arena');
    }, { context: phoneCtx(w, h, o.rm) });
  }
  // A phone turned sideways and back: wider than a phone the arena lets go and
  // the deck goes back under the replay; upright again it is pinned and the
  // page opens on the deck once more.
  await step('practice-phone-rotate', async (page, base) => {
    await returning(page);
    await go(page, base, '#practice/jabber-v1/' + 'ab'.repeat(32), '#planner');
    await page.evaluate(() => document.fonts.ready);
    await still(page);
    await page.setViewportSize({ width: 844, height: 390 });
    await page.waitForFunction(() => !document.querySelector('.practice-stage.pin') && !!document.querySelector('#player .beat-headline + #planner'));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => !!document.querySelector('.practice-stage.pin') && !!document.querySelector('#player > .stage + #planner'));
    await page.waitForTimeout(200);
    await still(page);
    const v = await deckView(page);
    await must(v.pinned && v.order && !v.bad.length, 'pinned again with the deck on screen after turning back upright (' + v.bad.join(', ') + ')');
  }, { context: phoneCtx(390, 844, true) });
  // Leaving a playback early on a phone (AUD-036 review), motion on, 390 x 844.
  // ▶| while a round plays back lands on the deck at once, as playing to the
  // end does, and so does stepping ▶ onto its end; the focus goes along to
  // the selected beat. PAUSE keeps the replay
  // under the arena with YOUR MOVES on screen, uncovered and on the row of
  // the beat position. YOUR MOVES puts the arena back on the state the round
  // is planned from, lands on the deck and takes the focus to the selected
  // beat; after stepping the replay back and scrolling up to the deck by
  // hand, a tap in the deck puts the arena back on that state too.
  await step('practice-phone-skip', async (page, base) => {
    await returning(page);
    // Half speed: a busy machine still taps ▶| and PAUSE well before a round has played out.
    await page.addInitScript(() => { try { localStorage.setItem('qdojo.combat.speed', '0.5'); } catch (e) { /* storage blocked */ } });
    await go(page, base, '#practice/jabber-v1/' + 'ab'.repeat(32), '#planner');
    await page.evaluate(() => document.fonts.ready);
    await still(page);
    const write = async () => { for (const a of ['3', '0', '1', '5', '4', '0']) await page.tap('#planner .act-btn[data-a="' + a + '"]'); await page.tap('#fight'); };
    // Round r playing back, the page at rest on the replay under the arena.
    const playing = async r => {
      await page.waitForFunction(r => new RegExp('^R' + r + ' B\\d').test(document.querySelector('.controls .pos').textContent) && document.querySelector('[data-act=play]').textContent === 'PAUSE', r, { timeout: 8000 });
      await still(page);
    };
    // The arena's HP and stamina for you next to the planner's own (the state the round is planned from).
    const arena = () => page.evaluate(() => {
      const q = s => document.querySelector(s), now = s => q('.practice-stage .corner-A ' + s).getAttribute('aria-valuenow');
      return { pos: q('.controls .pos').textContent, round: q('.practice-stage .round-no').textContent, shows: now('.cbar-hp') + '/' + now('.cbar-st'),
        plan: [...document.querySelectorAll('.planner-status b')].slice(0, 2).map(b => b.textContent).join('/') };
    });
    const onPlan = (a, r) => /^R\d BREAK/.test(a.pos) && a.round === 'ROUND ' + r + '/3' && a.shows === a.plan;
    // A tap's click can come a moment after the tap returns, so each wait is
    // for what the tap does (a page that only then starts to glide would
    // look "still" before it moved).
    const pos = () => page.$eval('.controls .pos', el => el.textContent);
    // A replay control that lands on the deck keeps the focus (ENTER on a beat
    // means FIGHT); YOUR MOVES takes it to the selected beat.
    const focusOnBeat = () => page.evaluate(() => document.activeElement.matches('#planner .slot[aria-selected="true"]'));
    const focusOnControl = () => page.evaluate(() => !!document.activeElement.closest('#player .controls'));
    const step1 = async (sel, was) => { await page.tap(sel); await page.waitForFunction(w => document.querySelector('.controls .pos').textContent !== w, was, { timeout: 5000 }); };
    const landed = async (r, what) => {
      await page.waitForFunction(() => { const q = s => document.querySelector(s).getBoundingClientRect(); return q('#planner .slots').top >= q('.practice-stage .stage').bottom && q('#fight').bottom <= innerHeight; }, null, { timeout: 8000 }).catch(() => {});
      await still(page);
      const v = await deckView(page), a = await arena();
      await must(!v.bad.length && v.over <= 0 && onPlan(a, r), what + ' landing on the round ' + r + ' deck, the arena on the state it is planned from (' + v.bad.join(', ') + '; ' + JSON.stringify(a) + ')');
      return v;
    };
    // ▶| while round 1 plays back
    await write();
    await playing(1);
    await page.tap('[data-act=last]');
    await landed(2, '▶| during the playback');
    await must(await focusOnControl(), 'the focus left on ▶| after it landed on the deck');
    await shot(page, 'practice-phone-skip-last', false);
    // PAUSE while round 2 plays back
    await write();
    await playing(2);
    await page.tap('[data-act=play]');
    await page.waitForFunction(() => document.querySelector('[data-act=play]').textContent === 'PLAY', null, { timeout: 5000 });
    await page.waitForTimeout(300);
    await still(page);
    const paused = await page.evaluate(() => {
      const q = s => document.querySelector(s), c = q('#to-deck'), b = c.getBoundingClientRect(), p = q('.controls .pos').getBoundingClientRect();
      const t = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
      return { pos: q('.controls .pos').textContent, onScreen: b.top >= q('.practice-stage .stage').getBoundingClientRect().bottom && b.bottom <= innerHeight, onTop: !!t && c.contains(t),
        row: p.top < b.bottom && b.top < p.bottom, headline: q('#player .beat-headline').getBoundingClientRect().bottom <= innerHeight };
    });
    await must(/^R2 B\d/.test(paused.pos) && paused.onScreen && paused.onTop && paused.row && paused.headline, 'a paused replay under the arena with its headline and YOUR MOVES on screen, uncovered, on the beat position\'s row (' + JSON.stringify(paused) + ')');
    await shot(page, 'practice-phone-skip-paused', false);
    // ▶ stepped onto the end
    for (let i = 0, was = await pos(); i < 12 && !/BREAK/.test(was); i++, was = await pos()) await step1('[data-act=next]', was);
    const deck = await landed(3, '▶ stepped onto the end');
    await must(await focusOnControl(), 'the focus left on ▶ after it stepped onto the end');
    // back down to the replay controls, three beats back, then YOUR MOVES
    for (let i = 0; i < 3; i++) await step1('[data-act=prev]', await pos());
    await must(/^R2 B\d/.test(await pos()), 'the replay stepped back into round 2 (' + await pos() + ')');
    await page.tap('#to-deck');
    await landed(3, 'YOUR MOVES');
    await must(await focusOnBeat(), 'the focus on the selected beat after YOUR MOVES');
    await shot(page, 'practice-phone-skip-moves', false);
    // two beats back, up to the deck by hand, a tap on a move
    for (let i = 0; i < 2; i++) await step1('[data-act=prev]', await pos());
    await page.evaluate(y => window.scrollTo(0, y), deck.y);
    await still(page);
    await must(!/BREAK/.test(await pos()), 'the arena still on the stepped-back beat before the deck is touched');
    await page.tap('#planner .act-btn[data-a="3"]');
    await page.waitForFunction(() => document.querySelectorAll('#planner .slot.filled').length === 1, null, { timeout: 5000 });
    const v = await landed(3, 'a tap on a move');
    await must(v.filled === 1 && v.y === deck.y, 'the tapped move in the first beat, the page still (' + v.filled + ' filled, scroll ' + deck.y + ' to ' + v.y + ')');
    // Round 3 written in full, then the replay stepped to its end by keyboard
    // and one ENTER more: the focus stays on ▶, so round 3 stays open.
    for (const a of ['0', '1', '5', '4', '0']) await page.tap('#planner .act-btn[data-a="' + a + '"]');
    await page.waitForFunction(() => document.querySelectorAll('#planner .slot.filled').length === 6, null, { timeout: 5000 });
    await page.focus('[data-act=next]');
    for (let i = 0, was = await pos(); i < 12 && !/BREAK/.test(was); i++, was = await pos()) {
      await page.keyboard.press('Enter');
      await page.waitForFunction(w => document.querySelector('.controls .pos').textContent !== w, was, { timeout: 5000 });
    }
    await page.keyboard.press('Enter');
    await page.waitForTimeout(300);
    await must(!!(await page.$('#planner')) && /ROUND 3/.test(await text(page, '#planner h3')) && await focusOnControl(), 'ENTER past the end of the replay leaving round 3 open, the focus on ▶ (' + await pos() + ')');
    // Nor does a held ENTER on a beat (a key repeat) fight it.
    await page.focus('#planner .slot[aria-selected="true"]');
    await page.evaluate(() => document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', repeat: true, bubbles: true, cancelable: true })));
    await page.waitForTimeout(300);
    await must(!!(await page.$('#planner')) && /ROUND 3/.test(await text(page, '#planner h3')), 'a repeated ENTER on a beat leaving round 3 open');
  }, { context: phoneCtx(390, 844) });
  await step('rules', async (page, base) => {
    await go(page, base, '#rules', '#digest .vstat');
    await must((await text(page, '#digest .vstat')) === 'PASS', 'the ruleset digest PASSes');
    await must(/VERIFICATION LEVELS/.test(await text(page, '#view')), 'verification levels');
    await shot(page, 'rules');
  });
  await step('unknown-route', async (page, base) => {
    await go(page, base, '#no-such-screen', '.lost');
    await must(/404/.test(await text(page, '.screen-title')) && /no-such-screen/.test(await text(page, '.lost')), 'a 404 screen naming the route');
    await must(page.url().endsWith('#no-such-screen'), 'no silent jump to another screen');
  });
  // Network wording comes from deployment.kind; no screen carries test-bench
  // words of its own (the SAMPLE badge and footer line are the one exception,
  // and this run is on the sample).
  await step('wording', async (page, base) => {
    // The exact ruleset id (combat-v1-candidate-2) stays visible as data.
    const bad = /fake QU|\bdemo\b|not live|(?<!combat-v\d-)candidate|\bpreview\b|play money|test data/i;
    const hits = [];
    for (const h of ['#title', '#arena', '#book', '#results', '#leaderboard', '#fighters', '#titles', '#collection', '#market', '#economy', '#cups', '#duels', '#season', '#practice', '#join', '#guide', '#rules', '#help', '#story', '#fighter/' + facts.fighter]) {
      await page.goto(base + h);
      await page.waitForTimeout(700);
      const t = await page.evaluate(() => { const c = document.body.cloneNode(true); c.querySelectorAll('#hud-source, #foot-net, #foot-data, script').forEach(n => n.remove()); return c.innerText + ' ' + Array.from(c.querySelectorAll('[title]')).map(n => n.title).join(' '); });
      const m = bad.exec(t);
      if (m) hits.push(h + ': "' + t.slice(Math.max(0, m.index - 40), m.index + 40).replace(/\s+/g, ' ') + '"');
    }
    await must(!hits.length, 'no test-bench wording, got ' + hits.join(' | '));
  });
  // ---- COMMUNITY panel on #economy (AUD-039): measured participation above the simulated economy ----
  await step('economy-community', async (page, base) => {
    await go(page, base, '#economy', '#community');
    const t = await text(page, '#view');
    await must(t.indexOf('COMMUNITY') < t.indexOf('SIMULATED ECONOMY BELOW') && t.indexOf('SIMULATED ECONOMY BELOW') < t.indexOf('THE HOUSE LEDGER'), 'community first, then the divider, then the simulated ledger');
    await must(/Measured, not simulated/.test(t) && /OUTSIDE FIGHTERS/.test(t) && /read API/.test(t), 'the static fallback (no API in this run)');
    await shot(page, 'economy-community');
  }, { context: { viewport: { width: 1440, height: 900 } } });
  const communityDoc = {
    schema: 'qdojo.combat.api.community.v1', generated_tick: '172800',
    basis: { tick: 172800, tick_seconds: 1.5, day_ticks: 57600, today: 3, run_gap_ticks: 1200 },
    fighters: { house: 20, outside: 7 }, outside: { builders: 7, registered_by_day: [{ day: 1, fighters: 4 }, { day: 2, fighters: 3 }], transactions: 4210 },
    active_builders: { today: 4, last_7_days: 6, ever: 7, by_day: [{ day: 0, builders: 0 }, { day: 1, builders: 4 }, { day: 2, builders: 6 }, { day: 3, builders: 4 }], by_week: [{ weeks_ago: 0, builders: 6 }] },
    fights: { total: { house_vs_house: 9100, outside_vs_house: 640, outside_vs_outside: 35 }, today: { house_vs_house: 900, outside_vs_house: 210, outside_vs_outside: 12 }, last_7_days: { house_vs_house: 9100, outside_vs_house: 640, outside_vs_outside: 35 }, by_day: [] },
    bot_runs: { total: 19, builders_with_two_or_more: 5, last_7_days: 19 },
    retention: { week_2_active: { eligible: 0, retained: 0 }, week_2_new_run: { eligible: 0, retained: 0 } },
  };
  async function withMockApi(page) {
    const manifest = readJson(path.join(SAMPLE, 'manifest.json'));
    await page.route(/\/data\/combat\/v1\/(?!sample\/)/, r => r.continue({ url: r.request().url().replace('/data/combat/v1/', '/data/combat/v1/sample/') }));
    await page.route(/\/api\/v1\//, r => {
      const p = new URL(r.request().url()).pathname;
      if (p.endsWith('/status')) return r.fulfill({ json: { schema: 'qdojo.combat.api.status.v1', network_id: manifest.network_id } });
      if (p.endsWith('/community')) return r.fulfill({ json: communityDoc });
      return r.fulfill({ status: 404, json: { schema: 'qdojo.combat.api.error.v1', error: { status: 404, code: 'not_found' } } });
    });
  }
  for (const [name, w, h] of [['economy-community-api', 1440, 900], ['economy-community-api-390', 390, 844]]) {
    await step(name, async (page, base) => {
      await withMockApi(page);
      await go(page, base, '#economy', '#community .cm-days');
      const t = await text(page, '#community');
      await must(/ACTIVE BUILDERS · 7 DAYS\s*6 today 4/.test(t) && /FIGHTS WITH A BUILDER · 7 DAYS\s*675 of 9,775/.test(t) && /BOT RUNS\s*19 5 restarted/.test(t) && /OUTSIDE FIGHTERS\s*7 of 27/.test(t), 'the API counts (got ' + t.slice(0, 300) + ')');
      await must(!/No outside builders yet/.test(t), 'no empty-arena line when builders exist');
      const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      await must(over <= 1, 'no sideways page scroll at ' + w + ' px (overflow ' + over + ' px)');
      await page.locator('#community').screenshot({ path: path.join(SHOTS, name + '.png') });
      await shot(page, name + '-page', false);
    }, { context: { viewport: { width: w, height: h } } });
  }
  await step('help', async (page, base) => { await go(page, base, '#help', '.help-kv'); await shot(page, 'help', false); });
  await step('join', async (page, base) => {
    await go(page, base, '#join', '#planner-src');
    await page.waitForFunction(() => !/^Loading/.test(document.querySelector('#planner-src').textContent));
    await must(/THE NETWORK: DEVNET/.test(await text(page, '#view')) && /no monetary value/i.test(await text(page, '#view')), 'the network statement');
    await shot(page, 'join');
  });
  await step('redirect', async (page, base) => {
    await page.goto(base + 'combat.html#rules');
    await page.waitForSelector('#digest');
    await must(new URL(page.url()).pathname === '/' && page.url().endsWith('#rules'), 'combat.html redirects to / and keeps the hash');
  });

  // ---- spoiler-free viewing (AUD-037): outcomes stay out of the DOM -----------
  // The setting is set once per context (a reload keeps what the page stored).
  const spoilerCtx = extra => Object.assign({ viewport: { width: 390, height: 844 } }, extra || {});
  const spoilerInit = page => page.addInitScript(() => { try { if (!sessionStorage.getItem('e2e-spoil')) { localStorage.setItem('qdojo.spoilers', 'hide'); sessionStorage.setItem('e2e-spoil', '1'); } } catch (e) { /* storage blocked */ } });
  const outcomeLeak = async (page, labels) => {
    const html = await page.evaluate(() => { const c = document.documentElement.cloneNode(true); c.querySelectorAll('script').forEach(n => n.remove()); return c.outerHTML; });
    const bad = [];
    if (/NEW CHAMPION/.test(html)) bad.push('NEW CHAMPION');
    if (/rbadge-(ko|hp|draw|timeout)\b/.test(html)) bad.push('an outcome badge');
    if (/class="beat">BEAT</.test(html)) bad.push('an X BEAT Y line');
    for (const t of labels) if (html.includes(t.replace(/&/g, '&amp;'))) bad.push('"' + t + '"');
    return bad;
  };
  const labelOf = async (page, id) => page.evaluate(async id => {
    const rp = await (await fetch('data/combat/v1/sample/fights/' + id + '/replay.json')).json();
    return { text: window.QDojoCombatLogic.outcomeLabel(rp).text, rounds: rp.rounds.length };
  }, id);
  if (facts.settledRanked) await step('spoiler-free', async (page, base) => {
    const id = String(facts.settledRanked.fight_id);
    await spoilerInit(page);
    await go(page, base, '#fight/' + id, '.stage');
    await expectVerified(page);
    const lab = await labelOf(page, id);
    let bad = await outcomeLeak(page, [lab.text]);
    await must(!bad.length, 'no outcome in the DOM mid-replay, found ' + bad.join(', '));
    await must(await page.locator('.result-hold').count() === 1 && await page.locator('.result-panel').count() === 0, 'RESULT HIDDEN instead of the result panel');
    await must(await page.locator('table.beats').count() === 0 && await page.locator('.check .evidence').count() === 0, 'no beat table or check evidence before the end');
    await must(await page.locator('#db-fold').count() === 0, 'no debrief before the end (it names the result)');
    await must(!/\(\d+\/\d+\)/.test(await text(page, '.controls .pos')), 'no frame total (it would give away the length)');
    await must(await page.getAttribute('[data-spoil-toggle]', 'aria-pressed') === 'true' && (await text(page, '#btn-spoil')) === 'SPOILERS: HIDDEN', 'the toggles say HIDDEN');
    await shot(page, 'spoiler-free-mid', false);
    // the last frame reveals the same, independently checked result
    await page.click('[data-act=last]');
    await page.waitForSelector('.result-panel');
    await must((await text(page, '.result-panel')).includes(lab.text.replace(/\s+/g, ' ')), 'the revealed result is the outcome label');
    await must(await page.locator('table.beats tr[data-i]').count() > 0 && /END \(\d+\/\d+\)/.test(await text(page, '.controls .pos')), 'the beat table and frame count after the end');
    await must(await page.locator('.check .evidence').count() > 0, 'check evidence after the end');
    await page.waitForSelector('#db-fold');
    // a watched fight stays revealed on reload
    await page.reload();
    await page.waitForSelector('.stage');
    await must(await page.locator('.result-panel').count() === 1, 'a watched fight is not hidden again');
    // results: unwatched rows held, SHOW reveals one, the toggle restores all
    await go(page, base, '#results', '.feed-row');
    const rows = await page.evaluate(id => Array.from(document.querySelectorAll('.feed-row')).map(li => ({ id: li.querySelector('.feed-id').textContent.slice(1), held: li.classList.contains('feed-held'), leak: /rbadge-(ko|hp|draw|timeout)\b|class="beat">BEAT</.test(li.outerHTML) })), id);
    const unseen = rows.filter(r => r.id !== id);
    await must(unseen.length > 0 && unseen.every(r => r.held && !r.leak), 'every unwatched results row held, no outcome in it');
    await must(rows.filter(r => r.id === id).every(r => !r.held), 'the watched fight shows its result in the list');
    const held = unseen.length;
    await page.click('.feed-held .reveal-one');
    await page.waitForFunction(n => document.querySelectorAll('.feed-held').length === n - 1, held);
    await page.click('.spoil-slot [data-spoil-toggle]');
    await page.waitForFunction(() => !document.querySelector('.feed-held'));
    await must((await text(page, '#btn-spoil')) === 'SPOILERS: SHOWN', 'the footer chip follows the toggle');
    // title and arena cards hide finished results too
    await page.click('#btn-spoil');
    await go(page, base, '#title', '#t-latest li a');
    const titleBadges = await page.locator('#t-latest .rbadge-hidden').count();
    await must(titleBadges > 0, 'held results on the title screen');
    await go(page, base, '#arena', '.sim-panel');
    await page.waitForTimeout(600);
    const arenaLeaks = await page.locator('.result-card:not(.result-held) .rbadge').count();
    const seenIds = await page.evaluate(() => JSON.parse(localStorage.getItem('qdojo.spoilers.seen') || '[]'));
    await must(arenaLeaks <= seenIds.length, 'arena result cards held except watched fights');
    return 'held ' + held + ' results rows; title ' + titleBadges + ' held';
  }, { context: spoilerCtx() });
  if (facts.settledRanked) await step('spoiler-free-reduced-motion', async (page, base) => {
    await spoilerInit(page);
    await go(page, base, '#fight/' + facts.settledRanked.fight_id, '.stage');
    await must(!/END/.test(await text(page, '.controls .pos')), 'reduced motion opens at the start, not on the result, when spoilers are hidden');
    await must(await page.locator('.result-panel').count() === 0, 'no result panel');
    await page.click('[data-reveal-replay]');
    await page.waitForSelector('.result-panel');
    await must(await page.locator('table.beats').count() === 1, 'REVEAL RESULT NOW shows the beat table');
  }, { context: spoilerCtx({ reducedMotion: 'reduce' }) });
  if (facts.forfeit) await step('spoiler-free-forfeit', async (page, base) => {
    await spoilerInit(page);
    await go(page, base, '#fight/' + facts.forfeit.fight_id, '.stage');
    const lab = await labelOf(page, facts.forfeit.fight_id);
    if (!lab.rounds) {
      await must(/TIMEOUT|FORFEIT|DOUBLE FAULT|VOID/.test(await text(page, '.result-panel')) && /nothing to spoil|no fight to spoil/i.test(await text(page, '.result-panel')), 'a forfeit before any round shows its result and says why');
    } else {
      await must(await page.locator('.result-panel').count() === 0, 'a forfeit after played rounds is held like any fight');
      await page.click('[data-act=last]');
      await must(/TIMEOUT/.test(await text(page, '.result-panel')), 'it reveals TIMEOUT at the end');
    }
  }, { context: spoilerCtx() });

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
