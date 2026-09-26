#!/usr/bin/env node
/* Browser check of the site against a running read API (AUD-026).
 *
 *   uv run qdojo combat api --db rm.sqlite --export DIR --port 8795 &
 *   python3 scripts/dev-site.py --api http://127.0.0.1:8795 --port 8080 &
 *   QDOJO_E2E_SITE=http://127.0.0.1:8080/ node apps/web/tests/e2e/api-run.cjs
 *
 * Checks that the site finds the API, that the busiest fighter's page shows
 * its whole career (more fights than the static export keeps) paginated,
 * that a pruned fight still opens, that scouting can cover the full career,
 * and that the results and leaderboard views use the API. Screenshots go to
 * apps/web/tests/e2e/shots/api-*.png. Skips (exit 0) without QDOJO_E2E_SITE
 * or without Playwright, like run.cjs.
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

const SITE = process.env.QDOJO_E2E_SITE;
const SHOTS = path.join(__dirname, 'shots');

function findPlaywright() {
  const tries = [process.env.QDOJO_PLAYWRIGHT, 'playwright', 'playwright-core'].filter(Boolean);
  const npx = path.join(os.homedir(), '.npm/_npx');
  if (fs.existsSync(npx)) for (const d of fs.readdirSync(npx)) for (const n of ['playwright', 'playwright-core']) tries.push(path.join(npx, d, 'node_modules', n));
  for (const t of tries) { try { return require(t); } catch (e) { /* next */ } }
  return null;
}
function findChromium() {
  if (process.env.QDOJO_CHROMIUM) return process.env.QDOJO_CHROMIUM;
  const root = path.join(os.homedir(), '.cache/ms-playwright');
  if (!fs.existsSync(root)) return null;
  for (const d of fs.readdirSync(root).filter(x => /^chromium-\d+$/.test(x)).sort().reverse()) {
    const p = path.join(root, d, 'chrome-linux64/chrome');
    if (fs.existsSync(p)) return p;
  }
  return null;
}

async function main() {
  const pw = findPlaywright(), chrome = findChromium();
  if (!SITE || !pw || !chrome) { console.log('api e2e SKIPPED: ' + (!SITE ? 'set QDOJO_E2E_SITE' : 'no Playwright/Chromium')); return 0; }
  fs.mkdirSync(SHOTS, { recursive: true });
  const api = u => fetch(new URL('api/v1/' + u, SITE)).then(r => r.json());
  const board = await api('leaderboard');
  const busiest = board.fighters.slice().sort((a, b) => b.fights_total - a.fights_total)[0];
  const index = await fetch(new URL('data/combat/v1/index.json', SITE)).then(r => r.json());
  const oldest = Math.min(...index.fights.map(Number));
  console.log('busiest fighter ' + busiest.name + ': ' + busiest.fights_total + ' fights; export keeps ' + index.fights.length + ' (oldest #' + oldest + ')');

  const browser = await pw.chromium.launch({ executablePath: chrome, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const problems = [];
  page.on('pageerror', e => problems.push('pageerror: ' + e.message));
  let failed = 0;
  const step = async (name, fn) => {
    try { await fn(); console.log('PASS ' + name); } catch (e) { failed++; console.log('FAIL ' + name + ': ' + e.message); }
  };
  const must = (c, what) => { if (!c) throw new Error('expected ' + what); };
  const go = async (hash, sel) => { await page.goto(new URL('#' + hash, SITE).href); await page.waitForSelector(sel, { timeout: 20000 }); };

  await step('fighter page shows the full career, paginated', async () => {
    await go('fighter/' + busiest.fighter_id, '#fighter-fights table');
    const head = await page.textContent('#fighter-fights h3');
    const n = Number((/ALL FIGHTS \((\d+)\)/.exec(head) || [])[1]);
    must(n === busiest.fights_total && n > 200, 'ALL FIGHTS (' + busiest.fights_total + '), got ' + head);
    must(await page.locator('#fighter-fights tbody tr').count() === 50, '50 rows on page 1');
    const foot = await page.textContent('#foot-data');
    must(/FULL HISTORY/.test(foot), 'the footer to say FULL HISTORY');
    await page.screenshot({ path: path.join(SHOTS, 'api-fighter.png'), fullPage: true });
    await page.locator('#fighter-fights').screenshot({ path: path.join(SHOTS, 'api-fighter-fights.png') });
  });
  await step('the last page reaches the first fight', async () => {
    const pages = Math.ceil(busiest.fights_total / 50);
    await go('fighter/' + busiest.fighter_id + '/' + pages, '#fighter-fights table');
    const ids = await page.$$eval('#fighter-fights tbody tr td:first-child a', as => as.map(a => Number(a.textContent.slice(1))));
    must(ids.length && Math.min(...ids) < oldest, 'fights older than the export keeps (#' + oldest + ')');
    await page.locator('#fighter-fights').screenshot({ path: path.join(SHOTS, 'api-fighter-last-page.png') });
    await page.click('#fighter-fights tbody tr:last-child td:first-child a');
    await page.waitForSelector('#verify .level-row', { timeout: 30000 });
    const level = await page.textContent('#level-slot');
    must(/REPLAY MATCH/.test(level), 'a pruned fight to open and verify, got ' + level);
    await page.screenshot({ path: path.join(SHOTS, 'api-old-fight.png') });
  });
  await step('scouting covers the full career on request', async () => {
    await go('fighter/' + busiest.fighter_id, '#scout-all');
    await page.click('#scout-all');
    await page.waitForFunction(() => /most recent \d+ of \d+/.test(document.querySelector('#scout .caveat').textContent) && !document.querySelector('#scout-all'), null, { timeout: 120000 });
    const cav = await page.textContent('#scout .caveat');
    const m = /most recent (\d+) of (\d+)/.exec(cav);
    must(m && Number(m[1]) > 200, 'a report over more than 200 fights, got: ' + cav);
    await page.locator('#scout').screenshot({ path: path.join(SHOTS, 'api-scouting.png') });
  });
  await step('results are paginated over the whole history', async () => {
    await go('results/2', '.feed');
    const h = await page.textContent('.screen-title');
    must(/(\d+) FINISHED/.test(h) && Number(/(\d+) FINISHED/.exec(h)[1]) > 1000, 'the full count, got ' + h);
    await page.screenshot({ path: path.join(SHOTS, 'api-results.png') });
  });
  await step('leaderboard ranks on whole careers and shows origin', async () => {
    await go('leaderboard', 'table.board');
    must(/every fight in the arena/.test(await page.textContent('.panel-yellow .tiny')), 'the full-history note');
    must(await page.locator('table.board .drv-house').count() > 0, 'HOUSE badges');
    await page.screenshot({ path: path.join(SHOTS, 'api-leaderboard.png') });
  });
  await browser.close();
  if (problems.length) { failed++; console.log('FAIL page errors: ' + problems.join('; ')); }
  console.log(failed ? 'api e2e: ' + failed + ' failure(s)' : 'api e2e: all passed');
  return failed ? 1 : 0;
}

main().then(c => process.exit(c), e => { console.error(e); process.exit(2); });
