#!/usr/bin/env node
/* Renders the site's share image and icon set from its own art, with the
 * cached Playwright Chromium (the same lookup as apps/web/tests/e2e/run.cjs).
 *
 *   node scripts/web-share-card.cjs
 *
 * Writes apps/web/share.png (1200x630, OpenGraph and Twitter card),
 * favicon-32.png, apple-touch-icon.png (180), icon-192.png and icon-512.png
 * (the web app manifest). The card is the title screen: the QDOJO logo, two
 * house fighters drawn by avatars.js on the site's backdrop. Outputs are
 * committed; rerun after changing the logo, the fighters or the palette.
 * Environment: QDOJO_PLAYWRIGHT, QDOJO_CHROMIUM (as for the e2e run).
 */
'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');

const WEB = path.resolve(__dirname, '../apps/web');
const HOME = os.homedir();
// Two founding house fighters (tanuki, kappa): any 64-hex identity works.
const LEFT = '9099a26c85ddb119ceccb840d6a90a1c6861576d2641f750b0ef49091f69d439';
const RIGHT = 'c0745b0e546d6f3bd4f605570e9012b0f716c9e21376ef2fdbecf3dad43af7f4';

function findPlaywright() {
  const tries = [process.env.QDOJO_PLAYWRIGHT, 'playwright', 'playwright-core'].filter(Boolean);
  const npx = path.join(HOME, '.npm/_npx');
  if (fs.existsSync(npx)) for (const d of fs.readdirSync(npx)) for (const n of ['playwright', 'playwright-core']) {
    const p = path.join(npx, d, 'node_modules', n);
    if (fs.existsSync(path.join(p, 'package.json'))) tries.push(p);
  }
  for (const t of tries) { try { return require(t); } catch (e) { /* next */ } }
  throw new Error('no Playwright package found (set QDOJO_PLAYWRIGHT)');
}
function findChromium() {
  if (process.env.QDOJO_CHROMIUM) return process.env.QDOJO_CHROMIUM;
  const root = path.join(HOME, '.cache/ms-playwright');
  const dirs = fs.existsSync(root) ? fs.readdirSync(root).filter(d => /^chromium-\d+$/.test(d)).sort((a, b) => b.split('-')[1] - a.split('-')[1]) : [];
  for (const d of dirs) { const p = path.join(root, d, 'chrome-linux64/chrome'); if (fs.existsSync(p)) return p; }
  throw new Error('no cached Chromium (set QDOJO_CHROMIUM)');
}

const CARD = `<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=Pixelify+Sans:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="style.css"><link rel="stylesheet" href="combat/combat.css"><link rel="stylesheet" href="combat/shell.css">
<style>
  html, body { width: 1200px; height: 630px; margin: 0; overflow: hidden; }
  body.still * { animation: none !important; }
  .card { position: relative; z-index: 10; width: 1200px; height: 630px; display: flex; flex-direction: column; align-items: center; justify-content: flex-start; padding-top: 58px; box-sizing: border-box; }
  .card .title-logo { font-size: 118px; margin: 0; }
  .card .sub { font-family: var(--font-pixel); color: var(--yellow); font-size: 20px; letter-spacing: 2px; margin: 22px 0 0; text-shadow: 3px 3px 0 #000; }
  .card .vs-row { display: flex; align-items: flex-end; gap: 90px; margin-top: 18px; }
  .card .avatar { width: 250px; height: 250px; display: block; }
  .card .avatar svg { width: 100%; height: 100%; image-rendering: pixelated; }
  .card .vs { font-family: var(--font-pixel); font-size: 64px; margin-bottom: 90px; }
  .card .tagline { position: absolute; z-index: 20; bottom: 18px; margin: 0; padding: 10px 16px; background: rgba(0, 0, 0, .82); border: 2px solid #1b2360; font-family: var(--font-pixel); font-size: 14px; color: var(--cyan); letter-spacing: 1px; }
</style></head><body class="still">
<div class="backdrop" aria-hidden="true"><div class="bd-stars"></div><div class="bd-sun"></div><div class="bd-hills"></div><div class="bd-grid"></div></div>
<div class="card">
  <h1 class="title-logo"><span class="title-q">Q</span>DOJO</h1>
  <p class="sub">AUTONOMOUS BOTS &middot; SEALED PLANS &middot; THREE ROUNDS</p>
  <div class="vs-row"><span class="avatar" id="l"></span><span class="vs vs-fire">VS</span><span class="avatar" id="r"></span></div>
  <p class="tagline">WATCH LIVE &middot; REPLAY EVERY BEAT &middot; BUILD A BOT</p>
</div>
<script src="avatars.js"></script>
<script>
  document.getElementById('l').innerHTML = QDojoAvatars.svg('${LEFT}', 'sprite');
  document.getElementById('r').innerHTML = QDojoAvatars.svg('${RIGHT}', 'sprite');
  document.querySelector('#r svg').style.transform = 'scaleX(-1)';
</script></body></html>`;

const ICON = size => `<!doctype html><html><head><style>html,body{margin:0;background:#0a0f3d}img{display:block;width:${size}px;height:${size}px;image-rendering:pixelated}</style></head><body><img src="favicon.svg"></body></html>`;

async function main() {
  const pw = findPlaywright();
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    if (rel === '/__card.html') { res.writeHead(200, { 'Content-Type': 'text/html' }); return res.end(CARD); }
    const m = /^\/__icon-(\d+)\.html$/.exec(rel);
    if (m) { res.writeHead(200, { 'Content-Type': 'text/html' }); return res.end(ICON(Number(m[1]))); }
    const file = path.join(WEB, rel);
    if (!file.startsWith(WEB) || !fs.existsSync(file) || !fs.statSync(file).isFile()) { res.writeHead(404); return res.end(); }
    const type = { '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml' }[path.extname(file)] || 'application/octet-stream';
    res.writeHead(200, { 'Content-Type': type });
    fs.createReadStream(file).pipe(res);
  });
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const base = 'http://127.0.0.1:' + server.address().port + '/';
  const browser = await pw.chromium.launch({ executablePath: findChromium(), args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage({ viewport: { width: 1200, height: 630 } });
    await page.goto(base + '__card.html', { waitUntil: 'networkidle' });
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(WEB, 'share.png') });
    for (const [name, size] of [['favicon-32.png', 32], ['apple-touch-icon.png', 180], ['icon-192.png', 192], ['icon-512.png', 512]]) {
      const p = await browser.newPage({ viewport: { width: size, height: size } });
      await p.goto(base + '__icon-' + size + '.html', { waitUntil: 'networkidle' });
      await p.screenshot({ path: path.join(WEB, name) });
      await p.close();
    }
  } finally {
    await browser.close();
    server.close();
  }
  console.log('wrote apps/web/share.png and the icon set');
}
main().catch(e => { console.error(e.message); process.exit(1); });
