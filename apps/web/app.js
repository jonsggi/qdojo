/* QDOJO spectator page.
 *
 * Reads ./data/history.json (every round) and ./data/board.json (open rounds),
 * polls them every 10 s, and re-renders only the parts whose data changed.
 * If the live files are missing it loads ./data/sample-*.json; if even those
 * cannot be fetched (file://) it uses the tiny EMBEDDED set so the cabinet
 * still lights up. No build step, no framework.
 */
'use strict';

const EXPLORER_TX = 'https://explorer.qubic.org/network/tx/';
const EXPLORER_ADDR = 'https://explorer.qubic.org/network/address/';
const POLL_MS = 10000;
const TICK_MS = 500;               // one tick is about half a second
const STALE_AFTER_MS = 3 * 60000;  // live export older than this is flagged

const QUICK_START =
`uv sync
uv run qdojo bot run --board https://<house>/data/board.json \\
    --conf ~/.qdojo/bot.conf --solver examples/solvers/echo.py`;

// Last resort when nothing can be fetched at all (opened from file://).
const EMBEDDED = {
  history: { house: 'QDOJOHASNOSIGNALYETINSERTCOINANDWAITFORTHEBELLTORINGONTHEBOARD',
             generated_at: null, generated_tick: 0, rounds: [], fighters: [] },
  board: null,
};

// ---------------------------------------------------------------- state
const S = {
  data: null,          // normalised dataset
  source: 'loading',   // 'live' | 'sample' | 'embedded'
  liveSeen: false,     // a live history.json was loaded at least once
  lastLiveOk: 0,       // ms timestamp of the last successful live fetch
  fetchedAt: 0,        // ms timestamp when generated_tick was observed
  screen: 'title',
  round: null,         // selected round on the results screen
  attract: true,
  sound: false,
  audio: null,
  cache: {},           // container id -> last html
  prevRounds: null,    // round_id -> {state, winners} for diff callouts
};

// ---------------------------------------------------------------- utils
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function fmt(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '—';
  return Number(n).toLocaleString('en-US');
}
function qu(n) { return `<span class="qu">${fmt(n)} QU</span>`; }
function shortId(id) { return id && id.length > 12 ? `${id.slice(0, 6)}…${id.slice(-4)}` : (id || '—'); }
function shortHex(h, n = 8) { return h && h.length > 2 * n + 1 ? `${h.slice(0, n)}…${h.slice(-4)}` : (h || '—'); }
function idLink(id, cls = '') {
  if (!id) return '<span class="muted">—</span>';
  return `<a class="id ${cls}" href="${EXPLORER_ADDR}${esc(id)}" title="${esc(id)}" target="_blank" rel="noopener">${esc(shortId(id))}</a>`;
}
function txLink(tx, label) {
  if (!tx) return '<span class="muted">—</span>';
  return `<a class="tx" href="${EXPLORER_TX}${esc(tx)}" title="${esc(tx)}" target="_blank" rel="noopener">${esc(label || shortId(tx))}</a>`;
}
function ticksToHuman(t) {
  const s = Math.max(0, Math.round(t / 2));
  if (s < 90) return `${s}s`;
  const m = Math.floor(s / 60), r = s % 60;
  return r ? `${m}m${String(r).padStart(2, '0')}s` : `${m}m`;
}
function ordinal(n) { return n === 1 ? '1ST' : n === 2 ? '2ND' : n === 3 ? '3RD' : `${n}TH`; }
function setHTML(id, html) {
  if (S.cache[id] === html) return false;
  const el = document.getElementById(id);
  if (!el) return false;
  el.innerHTML = html;
  S.cache[id] = html;
  return true;
}

// ---------------------------------------------------------------- avatars
// A deterministic 8x8 pixel fighter per identity. Original art, no trademarks.
const SKIN = ['#f5c9a3', '#d9a066', '#8d5524', '#e0ac69', '#c68642', '#ffdbac'];
const GI = ['#f4f4f4', '#ff2a2a', '#1b2cc1', '#39ff5a', '#ffd200', '#ff3cac', '#24e6ff', '#ff8c00', '#8a2be2', '#111111'];
const HAIR = ['#111111', '#ffd200', '#8b3a0e', '#ff2a2a', '#f4f4f4', '#24e6ff', '#39ff5a', '#ff3cac'];
function hash32(s) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
  return h;
}
function avatarSVG(identity, cls = '') {
  const h = hash32(identity || '');
  const pick = (arr, shift) => arr[(h >>> shift) % arr.length];
  const skin = pick(SKIN, 0), gi = pick(GI, 4), hair = pick(HAIR, 8);
  const belt = pick(['#111111', '#ffd200', '#ff2a2a', '#f4f4f4', '#39ff5a', '#8b3a0e'], 12);
  const band = (h >>> 16) & 1;         // headband
  const eyes = (h >>> 17) & 1 ? [2, 5] : [3, 4];
  const stance = (h >>> 18) & 1;       // which arm is raised
  const px = [];
  const put = (x, y, c) => px.push(`<rect x="${x}" y="${y}" width="1" height="1" fill="${c}"/>`);
  // hair / headband
  for (let x = 2; x <= 5; x++) put(x, 0, hair);
  if (band) { for (let x = 1; x <= 6; x++) put(x, 1, '#ff2a2a'); put(7, 1, '#ff2a2a'); put(7, 2, '#ff2a2a'); }
  else { put(1, 1, hair); put(6, 1, hair); for (let x = 2; x <= 5; x++) put(x, 1, skin); }
  // face
  for (let x = 2; x <= 5; x++) put(x, 2, skin);
  put(eyes[0], 2, '#111'); put(eyes[1], 2, '#111');
  // gi + arms
  for (let x = 2; x <= 5; x++) put(x, 3, gi);
  put(1, 3, stance ? skin : gi); put(6, 3, stance ? gi : skin);
  for (let x = 1; x <= 6; x++) put(x, 4, gi);
  put(0, stance ? 3 : 4, skin); put(7, stance ? 4 : 3, skin);
  // belt
  for (let x = 2; x <= 5; x++) put(x, 5, belt);
  // legs
  put(2, 6, gi); put(3, 6, gi); put(4, 6, gi); put(5, 6, gi);
  put(2, 7, '#111'); put(3, 7, '#111'); put(4, 7, '#111'); put(5, 7, '#111');
  return `<span class="avatar ${cls}" aria-hidden="true"><svg viewBox="0 0 8 8" shape-rendering="crispEdges">${px.join('')}</svg></span>`;
}

// ---------------------------------------------------------------- audio (opt-in)
function beep(freq, ms, when = 0, type = 'square') {
  if (!S.sound || !S.audio) return;
  const ctx = S.audio, o = ctx.createOscillator(), g = ctx.createGain();
  o.type = type; o.frequency.value = freq;
  g.gain.value = 0.06;
  o.connect(g); g.connect(ctx.destination);
  const t = ctx.currentTime + when;
  o.start(t); o.stop(t + ms / 1000);
}
const SFX = {
  coin() { beep(1320, 80); beep(1760, 160, 0.08); },
  fight() { beep(440, 90); beep(660, 90, 0.1); beep(880, 200, 0.2); },
  ko() { beep(220, 120); beep(165, 120, 0.12); beep(110, 320, 0.24, 'sawtooth'); },
  reveal() { beep(990, 60); beep(990, 60, 0.09); beep(1320, 140, 0.18); },
  over() { beep(330, 200); beep(262, 200, 0.22); beep(196, 400, 0.44); },
};

// ---------------------------------------------------------------- data loading
async function fetchJSON(url) {
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return res.json();
}

async function loadData() {
  // 1. the live export
  try {
    const history = await fetchJSON('./data/history.json');
    if (!history || !Array.isArray(history.rounds)) throw new Error('history.json has no rounds');
    let board = null;
    try { board = await fetchJSON('./data/board.json'); } catch (e) { board = null; }
    return { history, board, source: 'live' };
  } catch (e) {
    if (S.liveSeen) throw e; // keep the last good live data, do not flip to the sample
  }
  // 2. the sample files
  try {
    const history = await fetchJSON('./data/sample-history.json');
    let board = null;
    try { board = await fetchJSON('./data/sample-board.json'); } catch (e) { board = null; }
    return { history, board, source: 'sample' };
  } catch (e) { /* fall through */ }
  // 3. embedded last resort
  return { history: EMBEDDED.history, board: EMBEDDED.board, source: 'embedded' };
}

function normalise(history, board) {
  const rounds = (history.rounds || []).map(r => Object.assign({ entries: [], settlement: null }, r));
  const byId = new Map(rounds.map(r => [r.round_id, r]));
  let open;
  if (board && Array.isArray(board.rounds)) {
    open = board.rounds.map(b => {
      const h = byId.get(b.round_id);
      const merged = Object.assign({}, h || {}, b, { entries: (h && h.entries) || [], settlement: (h && h.settlement) || null });
      if (!h) { rounds.push(merged); byId.set(b.round_id, merged); }
      else Object.assign(h, merged);
      return merged;
    });
  } else {
    open = rounds.filter(r => r.state === 'commit' || r.state === 'reveal');
  }
  rounds.sort((a, b) => a.round_id - b.round_id);
  open.sort((a, b) => a.round_id - b.round_id);
  const fighters = (history.fighters || []).slice();
  const names = new Map(fighters.filter(f => f.name).map(f => [f.identity, f.name]));
  return {
    house: history.house || (board && board.house) || '',
    generated_at: history.generated_at || null,
    generated_tick: Math.max(Number(history.generated_tick) || 0, Number(board && board.generated_tick) || 0),
    rounds, open, fighters, names,
  };
}

// ---------------------------------------------------------------- round helpers
const COUNTED = new Set(['winner', 'solved', 'wrong', 'no_reveal', 'bad_reveal', 'pending']);
function windows(r) {
  const c0 = r.publish_tick + 1, c1 = r.publish_tick + r.commit_window;
  return { c0, c1, r0: c1 + 1, r1: c1 + r.reveal_window };
}
function nowTick() {
  if (!S.data) return 0;
  const elapsed = Math.floor((Date.now() - S.fetchedAt) / TICK_MS);
  return S.data.generated_tick + Math.max(0, elapsed);
}
function phaseAt(r, tick) {
  const w = windows(r);
  if (tick <= w.c1) return { phase: 'commit', remaining: w.c1 - tick, total: r.commit_window, end: w.c1 };
  if (tick <= w.r1) return { phase: 'reveal', remaining: w.r1 - tick, total: r.reveal_window, end: w.r1 };
  return { phase: 'over', remaining: 0, total: r.reveal_window, end: w.r1 };
}
function livePot(r) {
  if (r.settlement) return r.settlement.pot;
  return (r.house_seed || 0) + (r.entries || []).filter(e => COUNTED.has(e.verdict)).reduce((a, e) => a + (e.stake || 0), 0);
}
function maxPot() {
  return Math.max(1, ...S.data.rounds.map(livePot));
}
function nameOf(e) {
  return e.name || S.data.names.get(e.identity) || null;
}
function displayName(e) {
  const n = nameOf(e);
  return n ? esc(n) : '<span class="muted">???</span>';
}
function callout(r) {
  if (!r.settlement) {
    if (r.state === 'settling') return { text: 'SETTLING', cls: 'progress' };
    if (r.state === 'commit') return { text: 'FIGHT!', cls: 'progress' };
    if (r.state === 'reveal') return { text: 'REVEAL!', cls: 'progress' };
    return { text: '…', cls: 'progress' };
  }
  const n = (r.settlement.winners || []).length;
  const counted = (r.entries || []).filter(e => COUNTED.has(e.verdict)).length;
  if (n === 0) return { text: 'TIME OVER', cls: 'timeover', sub: 'NO WINNER · POT CARRIES' };
  if (n === 1) return { text: 'K.O.', cls: 'ko', perfect: counted >= 3, sub: 'ONE WINNER TAKES THE POT' };
  if (n === 2) return { text: 'DOUBLE K.O.', cls: 'ko', sub: 'TWO WINNERS SPLIT THE POT' };
  if (n === 3) return { text: 'TRIPLE K.O.', cls: 'ko', sub: 'THREE WINNERS SPLIT THE POT' };
  return { text: `${n}x K.O.`, cls: 'ko', sub: `${n} WINNERS SPLIT THE POT` };
}
function winnerNames(r) {
  if (!r.settlement) return [];
  const set = new Set(r.settlement.winners || []);
  return (r.entries || []).filter(e => set.has(e.identity)).map(e => nameOf(e) || shortId(e.identity));
}

// ---------------------------------------------------------------- verification (WebCrypto)
const enc = new TextEncoder();
function u32le(n) { const b = new Uint8Array(4); new DataView(b.buffer).setUint32(0, n, true); return b; }
function hexBytes(h) { const out = new Uint8Array(h.length / 2); for (let i = 0; i < out.length; i++) out[i] = parseInt(h.substr(2 * i, 2), 16); return out; }
function concat(...parts) {
  const len = parts.reduce((a, p) => a + p.length, 0); const out = new Uint8Array(len); let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; } return out;
}
async function sha256hex(bytes) {
  const d = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(d)).map(b => b.toString(16).padStart(2, '0')).join('');
}
// json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
function canonicalJSON(v) {
  if (v === null || typeof v !== 'object') return JSON.stringify(v);
  if (Array.isArray(v)) return `[${v.map(canonicalJSON).join(',')}]`;
  return `{${Object.keys(v).sort().map(k => `${JSON.stringify(k)}:${canonicalJSON(v[k])}`).join(',')}}`;
}
function canonicalAnswer(answer, fmt) {
  if (fmt === 'integer') return String(parseInt(String(answer).trim(), 10));
  if (fmt === 'hex') { let s = String(answer).trim().toLowerCase(); if (s.startsWith('0x')) s = s.slice(2); return s; }
  return String(answer).normalize('NFC').trim();
}
async function verifyRound(r) {
  if (!(window.crypto && crypto.subtle)) return [{ ok: false, label: 'VERIFY needs https or localhost (no WebCrypto here)' }];
  const out = [];
  const pub = r.riddle ? { round_id: r.riddle.round_id, title: r.riddle.title, statement: r.riddle.statement, input: r.riddle.input, answer_format: r.riddle.answer_format } : null;
  if (pub) {
    const h = await sha256hex(concat(enc.encode('qdojo/riddle/v0'), enc.encode(canonicalJSON(pub))));
    out.push({ ok: h === r.riddle_hash, label: 'RIDDLE HASH', detail: h });
  }
  if (r.settlement) {
    const s = r.settlement;
    const canon = canonicalAnswer(s.answer, r.riddle ? r.riddle.answer_format : 'string');
    const c = await sha256hex(concat(enc.encode('qdojo/answer/v0'), u32le(r.round_id), hexBytes(s.dojo_salt), enc.encode(canon)));
    out.push({ ok: c === r.answer_commitment, label: 'ANSWER COMMITMENT', detail: c });
    const body = Object.assign({}, s); delete body.hash; delete body.settle_tx; delete body.settle_tick;
    const sh = await sha256hex(concat(enc.encode('qdojo/settlement/v0'), enc.encode(canonicalJSON(body))));
    out.push({ ok: sh === s.hash, label: 'SETTLEMENT HASH', detail: sh });
  }
  return out;
}

// Recompute every hash of a settled round in the browser and print the verdict.
// Runs on its own when a results screen renders; `loud` (the button) adds the callout.
async function runVerify(roundId, loud = false) {
  const r = S.data && S.data.rounds.find(x => x.round_id === roundId);
  const out = $(`[data-verify-out="${roundId}"]`);
  if (!r || !out) return;
  out.innerHTML = '<span class="muted">HASHING…</span>';
  try {
    const res = await verifyRound(r);
    const all = res.every(x => x.ok);
    out.innerHTML = res.map(x => `<div class="${x.ok ? 'ok' : 'bad'}">${x.ok ? '✔' : '✘'} ${esc(x.label)}${x.detail ? ` <span class="muted mono" title="${esc(x.detail)}">${esc(shortHex(x.detail, 10))}</span>` : ''}</div>`).join('')
      + (all ? '<div class="ok">ALL CHECKS PASS · THE HOUSE DID NOT MOVE THE GOALPOSTS</div>' : '<div class="bad">MISMATCH · DO NOT TRUST THIS ROUND</div>');
    if (loud) { showCallout(all ? 'VERIFIED' : 'MISMATCH', `ROUND ${r.round_id}`, all ? 'cyan' : 'ko'); if (all) SFX.reveal(); else SFX.over(); }
  } catch (err) { out.innerHTML = `<div class="bad">VERIFY FAILED: ${esc(err.message)}</div>`; }
}

// ---------------------------------------------------------------- renderers
function meterHTML(id, cls, extra = '') {
  return `<div class="meter"><div class="meter-fill ${cls}" ${extra} data-meter="${id}"></div></div>`;
}

function renderTitle() {
  const d = S.data;
  const settled = d.rounds.filter(r => r.settlement);
  const last = settled[settled.length - 1];
  const top = d.fighters.slice().sort((a, b) => (b.earned - a.earned) || (b.wins - a.wins))[0];
  const lines = [];
  if (top) lines.push(`<div><span class="hi">HI-SCORE</span> ${esc(top.name || '???')} ${fmt(top.earned)} QU</div>`);
  if (last) {
    const c = callout(last);
    lines.push(`<div>ROUND ${last.round_id}: <span class="ko">${esc(c.text)}</span>${winnerNames(last).length ? ' — ' + esc(winnerNames(last).join(', ')) : ''}</div>`);
  }
  if (d.open.length) lines.push(`<div class="blink">ROUND ${d.open[0].round_id} IN PROGRESS — ${esc(d.open[0].state.toUpperCase())} WINDOW</div>`);
  if (!d.rounds.length) lines.push('<div class="muted">NO ROUNDS YET. THE BELL HAS NOT RUNG.</div>');
  setHTML('title-ticker', lines.join(''));
  const roster = d.fighters.filter(f => f.name).slice(0, 8).map(f => `<span class="roster-walk" title="${esc(f.name)}">${avatarSVG(f.identity)}</span>`).join('');
  setHTML('title-roster', roster);
  setHTML('title-house', d.house ? `HOUSE ${idLink(d.house)}` : '');
}

function riddleHTML(r) {
  const q = r.riddle || {};
  return `<div class="riddle-box">
    <p class="riddle-statement">${esc(q.statement || '(riddle document not published yet)')}</p>
    ${q.input ? `<pre class="riddle-input">${esc(q.input)}</pre>` : ''}
    <div class="riddle-meta">
      <span>FORMAT: <b>${esc((q.answer_format || '?').toUpperCase())}</b></span>
      <span>RIDDLE HASH: <span title="${esc(r.riddle_hash)}">${esc(shortHex(r.riddle_hash))}</span></span>
      <span>COMMITMENT: <span title="${esc(r.answer_commitment)}">${esc(shortHex(r.answer_commitment))}</span></span>
    </div>
  </div>`;
}

function entryStatus(e, r) {
  if (e.verdict && e.verdict !== 'pending') return `<span class="badge badge-${esc(e.verdict)}">${esc(e.verdict.replace('_', ' ').toUpperCase())}</span>`;
  if (e.reveal_tick) return '<span class="badge badge-reveal">REVEALED</span>';
  return `<span class="badge badge-pending">SEALED</span>`;
}

function fighterCard(e, r, slot) {
  const cls = e.verdict && e.verdict !== 'pending' ? e.verdict : (e.reveal_tick ? 'revealed' : 'sealed');
  return `<div class="fcard ${cls}">
    <span class="fslot">${String(slot).padStart(2, '0')}</span>
    ${avatarSVG(e.identity, 'avatar-lg')}
    <div class="fname">${displayName(e)}</div>
    <div class="fid">${idLink(e.identity)}</div>
    <div class="fstake">STAKE ${qu(e.stake)}</div>
    <div class="fstatus">${entryStatus(e, r)}</div>
    <div class="flinks">
      ${txLink(e.commit_tx, `COMMIT @${fmt(e.commit_tick)}`)}
      ${e.reveal_tx ? txLink(e.reveal_tx, `REVEAL @${fmt(e.reveal_tick)}`) : ''}
    </div>
  </div>`;
}

function renderFight() {
  const d = S.data;
  const parts = [];
  if (!d.open.length) {
    const settled = d.rounds.filter(r => r.settlement);
    const last = settled[settled.length - 1];
    const settling = d.rounds.filter(r => r.state === 'settling');
    parts.push(`<h2 class="screen-title">NOW FIGHTING<small>${settling.length ? 'THE HOUSE IS SETTLING ROUND ' + settling.map(r => r.round_id).join(', ') : 'WAITING FOR THE BELL'}</small></h2>`);
    parts.push(`<div class="panel panel-cyan"><div class="waiting">
      <div class="big blink">${settling.length ? 'SETTLING…' : 'WAITING FOR THE BELL'}</div>
      <p class="muted">The house publishes the next riddle on chain. This page polls every 10 seconds.</p>
      ${last ? `<p>LAST ROUND: <a href="#results/${last.round_id}">ROUND ${last.round_id} · ${esc(last.title)} · ${esc(callout(last).text)}</a></p>` : ''}
      ${settling.map(r => `<p><a href="#results/${r.round_id}">ROUND ${r.round_id} · ${esc(r.title)} · SETTLING</a></p>`).join('')}
    </div></div>`);
    setHTML('fight-body', parts.join(''));
    return;
  }
  for (const r of d.open) {
    const w = windows(r);
    const entries = (r.entries || []).slice().sort((a, b) => a.commit_tick - b.commit_tick);
    const staked = entries.filter(e => COUNTED.has(e.verdict)).reduce((a, e) => a + e.stake, 0);
    const revealed = entries.filter(e => e.reveal_tick).length;
    const pot = livePot(r);
    const potPct = Math.min(100, 100 * pot / maxPot());
    const seedPct = potPct * (r.house_seed || 0) / Math.max(1, pot);
    const cards = entries.map((e, i) => fighterCard(e, r, i + 1)).join('');
    const empties = entries.length < 4 ? Array.from({ length: 4 - entries.length }, () => '<div class="fcard fcard-empty">OPEN SLOT<br>INSERT COIN</div>').join('') : '';
    parts.push(`
      <div class="fight-head">
        <div class="fight-round">ROUND ${r.round_id}</div>
        <div class="fight-phase"><span class="badge badge-${esc(r.state)}" data-phase-badge="${r.round_id}">${esc(r.state.toUpperCase())}</span> ${esc(r.title)}</div>
        <div class="tiny muted">PUBLISHED @ ${fmt(r.publish_tick)} · ${txLink(r.publish_tx, 'TX')}</div>
      </div>

      <div class="cols">
        <div class="panel panel-red">
          <h3>WINDOW</h3>
          <div class="meter-label">
            <span data-phase-label="${r.round_id}">—</span>
            <b><span data-ticks-left="${r.round_id}">—</span> TICKS</b>
          </div>
          ${meterHTML(`win-${r.round_id}`, 'warn')}
          <div class="meter-legend">
            <span>COMMIT ${fmt(w.c0)} – ${fmt(w.c1)}</span>
            <span>REVEAL ${fmt(w.r0)} – ${fmt(w.r1)}</span>
          </div>
          <div class="continue" data-continue="${r.round_id}">
            <div class="continue-label" data-continue-label="${r.round_id}">CONTINUE?</div>
            <div class="continue-num" data-secs-left="${r.round_id}">—</div>
            <div class="continue-sub" data-continue-sub="${r.round_id}"></div>
          </div>
        </div>

        <div class="panel panel-yellow">
          <h3>POT</h3>
          <div class="meter-label"><span>LIVE POT</span><b>${fmt(pot)} QU</b></div>
          <div class="meter">
            <div class="meter-fill stakes" style="width:${potPct.toFixed(1)}%"></div>
            <div class="meter-fill seed" style="width:${seedPct.toFixed(1)}%"></div>
          </div>
          <div class="meter-legend">
            <span><i style="background:var(--cyan)"></i>HOUSE SEED ${fmt(r.house_seed)}</span>
            <span><i style="background:var(--yellow)"></i>STAKES ${fmt(staked)}</span>
          </div>
          <div class="stats" style="margin-top:14px;margin-bottom:0">
            <div class="stat"><div class="k">ENTRY FEE</div><div class="v">${fmt(r.entry_fee)}</div></div>
            <div class="stat green"><div class="k">FIGHTERS IN</div><div class="v">${entries.length}</div></div>
            <div class="stat cyan"><div class="k">REVEALED</div><div class="v">${revealed} / ${entries.length}</div></div>
          </div>
        </div>
      </div>

      <div class="panel panel-cyan">
        <h3>THE RIDDLE</h3>
        ${riddleHTML(r)}
      </div>

      <div class="panel">
        <h3>FIGHTER SELECT · ${entries.length} IN</h3>
        <div class="grid-fighters">${cards}${empties}</div>
      </div>
    `);
  }
  setHTML('fight-body', parts.join(''));
}

function entriesTable(r) {
  const entries = (r.entries || []).slice().sort((a, b) => a.commit_tick - b.commit_tick);
  if (!entries.length) return '<p class="muted">No entries were observed in this round.</p>';
  return `<div class="tscroll"><table>
    <thead><tr><th>FIGHTER</th><th>IDENTITY</th><th class="num">STAKE</th><th>COMMIT</th><th>REVEAL</th><th>ANSWER</th><th>VERDICT</th></tr></thead>
    <tbody>${entries.map(e => `<tr class="${e.verdict === 'winner' ? 'winner' : ''}">
      <td><span class="tname">${avatarSVG(e.identity, 'avatar-sm')} ${displayName(e)}</span></td>
      <td>${idLink(e.identity)}</td>
      <td class="num">${fmt(e.stake)}</td>
      <td>${txLink(e.commit_tx, '@' + fmt(e.commit_tick))}</td>
      <td>${e.reveal_tx ? txLink(e.reveal_tx, '@' + fmt(e.reveal_tick)) : '<span class="muted">—</span>'}</td>
      <td class="mono">${e.answer === null || e.answer === undefined ? '<span class="muted">—</span>' : esc(e.answer)}</td>
      <td>${entryStatus(e, r)}</td>
    </tr>`).join('')}</tbody></table></div>`;
}

function payoutsTable(s) {
  if (!s.payouts || !s.payouts.length) return '<p class="muted">No payouts. The house kept the rake; the rest carries.</p>';
  return `<div class="tscroll"><table>
    <thead><tr><th>TO</th><th>KIND</th><th class="num">AMOUNT</th><th>TX</th><th>TICK</th><th>CONFIRMED</th></tr></thead>
    <tbody>${s.payouts.map(p => `<tr>
      <td><span class="tname">${avatarSVG(p.identity, 'avatar-sm')} ${displayName({ identity: p.identity })} ${idLink(p.identity)}</span></td>
      <td><span class="badge badge-${esc(p.kind)}">${esc(String(p.kind).toUpperCase())}</span></td>
      <td class="num">${fmt(p.amount)}</td>
      <td>${txLink(p.tx)}</td>
      <td>${p.tick ? fmt(p.tick) : '<span class="muted">—</span>'}</td>
      <td>${p.confirmed ? '<span style="color:var(--green)">YES</span>' : '<span class="blink" style="color:var(--orange)">PENDING</span>'}</td>
    </tr>`).join('')}</tbody></table></div>`;
}

function renderResults() {
  const d = S.data;
  if (!d.rounds.length) {
    setHTML('results-body', '<h2 class="screen-title">RESULTS</h2><div class="panel"><p class="muted">No rounds yet.</p></div>');
    return;
  }
  const ids = d.rounds.map(r => r.round_id);
  if (S.round === null || !ids.includes(S.round)) {
    const settled = d.rounds.filter(r => r.settlement);
    S.round = settled.length ? settled[settled.length - 1].round_id : ids[ids.length - 1];
  }
  const i = ids.indexOf(S.round);
  const r = d.rounds[i];
  const prev = i > 0 ? ids[i - 1] : null, next = i < ids.length - 1 ? ids[i + 1] : null;
  const c = callout(r);
  const s = r.settlement;
  const parts = [];
  parts.push(`<div class="res-head">
    <h2 class="screen-title" style="margin:0">ROUND ${r.round_id}<small>${esc(r.title)} · <span class="badge badge-${esc(r.state)}">${esc(r.state.toUpperCase())}</span></small></h2>
    <div class="spacer"></div>
    <div class="res-nav">
      <a class="btn btn-sm ${prev === null ? 'disabled' : ''}" href="#results/${prev ?? r.round_id}" ${prev === null ? 'aria-disabled="true"' : ''}>&#9664; PREV</a>
      <a class="btn btn-sm btn-cyan" href="#history">ALL</a>
      <a class="btn btn-sm ${next === null ? 'disabled' : ''}" href="#results/${next ?? r.round_id}" ${next === null ? 'aria-disabled="true"' : ''}>NEXT &#9654;</a>
      ${s ? `<button class="btn btn-sm" data-replay="${r.round_id}">REPLAY</button>` : `<a class="btn btn-sm" href="#fight">WATCH LIVE</a>`}
    </div>
  </div>`);

  parts.push(`<div class="res-ko">
    <div class="ko-text ${c.cls}">${esc(c.text)}</div>
    ${c.perfect ? '<div class="ko-perfect">PERFECT</div>' : ''}
    ${c.sub ? `<div class="ko-sub">${esc(c.sub)}</div>` : ''}
    ${!s ? `<div class="ko-sub">THIS ROUND IS STILL OPEN — <a href="#fight">NOW FIGHTING</a></div>` : ''}
  </div>`);

  if (s) {
    const potPct = Math.min(100, 100 * s.pot / maxPot());
    parts.push(`<div class="stats">
      <div class="stat"><div class="k">POT</div><div class="v">${fmt(s.pot)}</div></div>
      <div class="stat red"><div class="k">RAKE</div><div class="v">${fmt(s.rake)}</div></div>
      <div class="stat cyan"><div class="k">CARRY</div><div class="v">${fmt(s.carry)}</div></div>
      <div class="stat green"><div class="k">WINNERS</div><div class="v">${(s.winners || []).length}</div></div>
      <div class="stat"><div class="k">HOUSE SEED</div><div class="v">${fmt(r.house_seed)}</div></div>
      <div class="stat"><div class="k">ENTRY FEE</div><div class="v">${fmt(r.entry_fee)}</div></div>
    </div>
    <div class="meter" style="margin-bottom:20px"><div class="meter-fill pot" style="width:${potPct.toFixed(1)}%"></div></div>`);

    const winners = (r.entries || []).filter(e => (s.winners || []).includes(e.identity));
    const payoutFor = id => (s.payouts || []).find(p => p.identity === id && p.kind === 'win');
    parts.push(`<div class="cols">
      <div class="panel panel-green">
        <h3>WINNERS</h3>
        ${winners.length ? `<div class="winners">${winners.map(e => { const p = payoutFor(e.identity); return `<div class="winner-row">
            ${avatarSVG(e.identity, 'avatar-lg')}
            <div class="wname">${displayName(e)}<br>${idLink(e.identity)}</div>
            <div class="wamt">+${fmt(p ? p.amount : 0)} QU${p && p.tx ? `<span class="wtx">${txLink(p.tx, 'PAYOUT TX')}</span>` : ''}</div>
          </div>`; }).join('')}</div>`
        : `<p class="muted">Nobody solved it. ${fmt(s.carry)} QU carries into the next round's seed.</p>`}
      </div>
      <div class="panel panel-yellow">
        <h3>THE ANSWER · VERIFY IT YOURSELF</h3>
        <dl class="kv">
          <dt>ANSWER</dt><dd class="answer">${esc(s.answer)}</dd>
          <dt>DOJO SALT</dt><dd class="mono wrap">${esc(s.dojo_salt)}</dd>
          <dt>COMMITMENT</dt><dd class="mono wrap">${esc(r.answer_commitment)}</dd>
          <dt>RIDDLE HASH</dt><dd class="mono wrap">${esc(r.riddle_hash)}</dd>
          <dt>SETTLE HASH</dt><dd class="mono wrap">${esc(s.hash)}</dd>
          <dt>PUBLISH TX</dt><dd>${txLink(r.publish_tx)}</dd>
          <dt>SETTLE TX</dt><dd>${txLink(s.settle_tx)}</dd>
        </dl>
        <p class="tiny muted" style="margin:10px 0">commitment = SHA-256("qdojo/answer/v0" ‖ round_id u32le ‖ dojo_salt ‖ canonical answer)</p>
        <button class="btn btn-sm btn-cyan" data-verify="${r.round_id}">VERIFY</button>
        <div class="verify-out" data-verify-out="${r.round_id}"></div>
      </div>
    </div>`);
  }

  parts.push(`<div class="panel panel-cyan"><h3>THE RIDDLE</h3>${riddleHTML(r)}</div>`);
  parts.push(`<div class="panel"><h3>ENTRIES · ${(r.entries || []).length}</h3>${entriesTable(r)}</div>`);
  if (s) parts.push(`<div class="panel panel-green"><h3>PAYOUTS · ${(s.payouts || []).length}</h3>${payoutsTable(s)}</div>`);
  if (setHTML('results-body', parts.join('')) && s) runVerify(r.round_id);
}

function renderFame() {
  const d = S.data;
  const rows = d.fighters.slice().sort((a, b) => (b.earned - a.earned) || (b.wins - a.wins) || (b.rounds_played - a.rounds_played) || String(a.name || '').localeCompare(String(b.name || '')));
  const parts = [`<h2 class="screen-title">HALL OF FAME<small>HIGH SCORES · EARNED QU SINCE ROUND 1 · BELTS COME LATER</small></h2>`];
  if (!rows.length) parts.push('<div class="panel"><p class="muted">No fighter has bowed yet.</p></div>');
  else parts.push(`<div class="panel panel-yellow"><div class="tscroll"><table class="fame-table">
    <thead><tr><th>RANK</th><th>FIGHTER</th><th>IDENTITY</th><th class="num">WINS</th><th class="num">PLAYED</th><th class="num">EARNED QU</th><th>STRIKES</th><th>BOWED</th></tr></thead>
    <tbody>${rows.map((f, i) => `<tr>
      <td class="rank rank-${i + 1}">${ordinal(i + 1)}</td>
      <td><span class="tname">${avatarSVG(f.identity)} ${f.name ? esc(f.name) : '<span class="muted">???</span>'}${f.name ? '' : ' <span class="badge">STRANGER</span>'}</span></td>
      <td>${idLink(f.identity)}</td>
      <td class="num">${fmt(f.wins)}</td>
      <td class="num">${fmt(f.rounds_played)}</td>
      <td class="num qu">${fmt(f.earned)}</td>
      <td><span class="strikes">${'✕'.repeat(Math.min(8, f.strikes || 0))}</span>${f.strikes > 8 ? ` +${f.strikes - 8}` : ''}${!f.strikes ? '<span class="muted">—</span>' : ''}</td>
      <td>${f.bow_tick ? '@' + fmt(f.bow_tick) : '<span class="muted">never</span>'}</td>
    </tr>`).join('')}</tbody></table></div>
    <p class="tiny muted" style="margin:12px 0 0">A stranger has not bowed. Strikes: duplicate commits, malformed payloads, reveals without a commit, spam. Phase one evicts on them.</p>
    </div>`);
  setHTML('fame-body', parts.join(''));
}

function renderHistory() {
  const d = S.data;
  const parts = [`<h2 class="screen-title">ROUND HISTORY<small>EVERY ROUND FROM THE BEGINNING · ${d.rounds.length} ROUNDS</small></h2>`];
  if (!d.rounds.length) parts.push('<div class="panel"><p class="muted">No rounds yet.</p></div>');
  else {
    parts.push(`<p style="margin:0 0 14px"><a class="btn btn-sm" href="#results/${d.rounds[0].round_id}">&#9654; WATCH FROM ROUND ${d.rounds[0].round_id}</a></p>`);
    parts.push(`<div class="hist-list">${d.rounds.map(r => {
      const c = callout(r), s = r.settlement, open = !s && (r.state === 'commit' || r.state === 'reveal');
      const names = winnerNames(r);
      return `<a class="hist-row ${open ? 'open' : ''}" href="#results/${r.round_id}">
        <div class="hr-num">R${String(r.round_id).padStart(2, '0')}</div>
        <div><div class="hr-title">${esc(r.title)} <span class="badge badge-${esc(r.state)}">${esc(r.state.toUpperCase())}</span></div>
          <div class="hr-sub">${(r.entries || []).length} IN · POT ${fmt(livePot(r))} QU${s ? ` · RAKE ${fmt(s.rake)} · CARRY ${fmt(s.carry)}` : ''} · PUBLISHED @${fmt(r.publish_tick)}${names.length ? ' · ' + esc(names.join(', ')) : ''}</div></div>
        <div class="hr-call ${c.cls}">${esc(c.text)}${c.perfect ? '<small>PERFECT</small>' : ''}</div>
      </a>`;
    }).join('')}</div>`);
  }
  setHTML('history-body', parts.join(''));
}

function renderJoin() {
  const d = S.data;
  const boardURL = new URL('data/board.json', location.href).href;
  const open = d.open[0];
  setHTML('join-body', `
    <h2 class="screen-title">HOW TO JOIN<small>BRING A BOT. BOW. WAIT FOR THE BELL.</small></h2>
    <div class="cols">
      <div class="panel panel-green">
        <h3>BOT QUICK START</h3>
        <pre class="code" id="quickstart">${esc(QUICK_START)}</pre>
        <button class="btn btn-sm" data-copy="quickstart">COPY</button>
        <p class="tiny muted" style="margin-top:12px">This dojo's board: <a class="mono wrap" href="${esc(boardURL)}">${esc(boardURL)}</a><br>
        The conf holds one <b>seed=</b> line, mode 0600. A seed never goes on argv.</p>
        <p class="tiny muted">The solver is any executable: riddle JSON on stdin, <span class="mono">{"answer": …}</span> on stdout.</p>
      </div>
      <div class="panel panel-red">
        <h3>THE HOUSE</h3>
        <dl class="kv">
          <dt>HOUSE</dt><dd>${idLink(d.house)}</dd>
          <dt>ENTRY FEE</dt><dd>${open ? qu(open.entry_fee) : '<span class="muted">see the next PUBLISH</span>'}</dd>
          <dt>COMMIT</dt><dd>${open ? `${fmt(open.commit_window)} ticks (~${ticksToHuman(open.commit_window)})` : '—'}</dd>
          <dt>REVEAL</dt><dd>${open ? `${fmt(open.reveal_window)} ticks (~${ticksToHuman(open.reveal_window)})` : '—'}</dd>
          <dt>PAYOUT</dt><dd>(pot − rake) ÷ winners, remainder carries</dd>
          <dt>NO WINNER</dt><dd>pot − rake carries to the next round</dd>
          <dt>REFUNDS</dt><dd>underpaid or late commits, in full</dd>
        </dl>
      </div>
    </div>
    <div class="panel panel-cyan">
      <h3>DOJO ETIQUETTE</h3>
      <ol class="rules">
        <li><b>BOW</b> when you enter. A bot that does not bow is a stranger.</li>
        <li><b>WAIT FOR THE BELL.</b> The riddle is the bell. Commit before it rings and you strike the air.</li>
        <li><b>DO NOT STRIKE TWICE.</b> One commitment per round. A second is a strike against you.</li>
        <li><b>REVEAL WHAT YOU SEALED.</b> A reveal that does not match its commitment is a lie, and the dojo remembers lies.</li>
        <li><b>BELTS</b> come later, and they are earned, not bought.</li>
      </ol>
    </div>
  `);
}

function renderFooter() {
  const d = S.data;
  const src = S.source === 'live' ? 'LIVE EXPORT' : S.source === 'sample' ? 'SAMPLE DATA (no house running)' : 'EMBEDDED (nothing could be fetched)';
  setHTML('foot-data', `DATA: ${src} · GENERATED ${esc(d.generated_at || '—')} @ TICK ${fmt(d.generated_tick)} · HOUSE ${idLink(d.house)} · <a href="https://explorer.qubic.org" target="_blank" rel="noopener">QUBIC EXPLORER</a> · 1 TICK ≈ 0.5 s`);
}

function renderStatus() {
  const el = $('#hud-source');
  let cls = 'pill-demo', txt = 'DEMO';
  if (S.source === 'live') {
    const age = Date.now() - S.lastLiveOk;
    const gen = S.data.generated_at ? Date.parse(S.data.generated_at) : NaN;
    if (age > POLL_MS * 3) { cls = 'pill-lost'; txt = 'SIGNAL LOST'; }
    else if (!Number.isNaN(gen) && Date.now() - gen > STALE_AFTER_MS) { cls = 'pill-lost'; txt = 'STALE'; }
    else { cls = 'pill-live'; txt = 'LIVE'; }
  } else if (S.source === 'embedded') { txt = 'NO SIGNAL'; }
  if (el.textContent !== txt) el.textContent = txt;
  el.className = `pill ${cls}`;
}

function renderAll() {
  if (!S.data) return;
  renderTitle(); renderFight(); renderResults(); renderFame(); renderHistory(); renderJoin(); renderFooter(); renderStatus();
  updateTicks();
}

// ---------------------------------------------------------------- tick animation (2/s)
function updateTicks() {
  if (!S.data) return;
  const t = nowTick();
  const tickEl = $('#hud-tick');
  if (tickEl) tickEl.textContent = fmt(t);
  for (const r of S.data.open) {
    const id = r.round_id;
    let p = phaseAt(r, t);
    if (p.phase === 'over' && S.source !== 'live') {
      // demo loop: restart the window so the cabinet never sits on zero
      S.fetchedAt = Date.now();
      p = phaseAt(r, nowTick());
    }
    const fill = $(`[data-meter="win-${id}"]`);
    if (fill) {
      const pct = p.total ? 100 * p.remaining / p.total : 0;
      fill.style.width = `${pct.toFixed(1)}%`;
      fill.className = `meter-fill ${p.phase === 'reveal' ? (pct < 25 ? 'crit' : 'warn') : (pct < 20 ? 'warn' : '')}`;
    }
    const lbl = $(`[data-phase-label="${id}"]`);
    if (lbl) lbl.textContent = p.phase === 'commit' ? 'COMMIT WINDOW · SEAL YOUR ANSWER' : p.phase === 'reveal' ? 'REVEAL WINDOW · SHOW WHAT YOU SEALED' : 'TIME OVER · WAITING FOR SETTLEMENT';
    const tl = $(`[data-ticks-left="${id}"]`); if (tl) tl.textContent = fmt(p.remaining);
    const secs = $(`[data-secs-left="${id}"]`); if (secs) secs.textContent = p.phase === 'over' ? '0' : String(Math.ceil(p.remaining / 2));
    const cont = $(`[data-continue="${id}"]`); if (cont) cont.className = `continue ${p.phase}`;
    const cl = $(`[data-continue-label="${id}"]`); if (cl) cl.textContent = p.phase === 'commit' ? 'COMMIT!' : p.phase === 'reveal' ? 'CONTINUE?' : 'TIME OVER';
    const cs = $(`[data-continue-sub="${id}"]`); if (cs) cs.textContent = p.phase === 'over' ? 'THE HOUSE SETTLES AFTER THE WINDOW' : `SECONDS LEFT · WINDOW ENDS @ TICK ${fmt(p.end)}`;
    const badge = $(`[data-phase-badge="${id}"]`);
    if (badge) {
      const txt = p.phase === 'over' ? 'SETTLING' : p.phase.toUpperCase();
      if (badge.textContent !== txt) { badge.textContent = txt; badge.className = `badge badge-${p.phase === 'over' ? 'settling' : p.phase}`; }
    }
  }
}

// ---------------------------------------------------------------- callouts, shake, flash
let calloutTimer = null;
function showCallout(text, sub = '', kind = '') {
  const el = $('#callout');
  $('.callout-text', el).textContent = text;
  $('.callout-sub', el).textContent = sub;
  el.className = `callout show ${kind}`;
  // restart the punch animation
  const t = $('.callout-text', el); t.style.animation = 'none'; void t.offsetWidth; t.style.animation = '';
  clearTimeout(calloutTimer);
  calloutTimer = setTimeout(() => { el.className = 'callout'; }, kind === 'ko' ? 2600 : 2000);
  if (kind === 'ko') {
    document.body.classList.remove('shake'); void document.body.offsetWidth; document.body.classList.add('shake');
    const f = $('#flash'); f.classList.remove('go'); void f.offsetWidth; f.classList.add('go');
    setTimeout(() => document.body.classList.remove('shake'), 600);
  }
}
function replayRound(r) {
  const c = callout(r);
  if (!r.settlement) { showCallout('FIGHT!', `ROUND ${r.round_id}`); SFX.fight(); return; }
  showCallout(`ROUND ${r.round_id}`, r.title);
  SFX.fight();
  setTimeout(() => {
    if (c.cls === 'timeover') { showCallout('TIME OVER', 'NO WINNER · POT CARRIES', 'cyan'); SFX.over(); }
    else { showCallout(c.text, c.perfect ? 'PERFECT' : winnerNames(r).join(' · '), 'ko'); SFX.ko(); }
  }, 1400);
}
function diffCallouts(data) {
  const prev = S.prevRounds;
  const cur = new Map(data.rounds.map(r => [r.round_id, { state: r.state, settled: !!r.settlement }]));
  S.prevRounds = cur;
  if (!prev) return;
  const events = [];
  for (const r of data.rounds) {
    const p = prev.get(r.round_id), c = cur.get(r.round_id);
    if (!p) { events.push(() => { showCallout(`ROUND ${r.round_id}`, 'FIGHT!'); SFX.fight(); }); continue; }
    if (p.state === 'commit' && c.state === 'reveal') events.push(() => { showCallout('REVEAL!', `ROUND ${r.round_id}`); SFX.reveal(); });
    if (!p.settled && c.settled) events.push(() => replayRound(r));
  }
  events.forEach((fn, i) => setTimeout(fn, i * 3200));
}

// ---------------------------------------------------------------- polling
async function poll() {
  try {
    const { history, board, source } = await loadData();
    const data = normalise(history, board);
    const key = JSON.stringify([history, board]);
    const changed = !S.data || key !== S.rawKey;
    S.rawKey = key;
    if (source === 'live') { S.liveSeen = true; S.lastLiveOk = Date.now(); }
    if (!S.data || data.generated_tick !== S.data.generated_tick || source !== S.source) S.fetchedAt = Date.now();
    S.source = source;
    S.data = data;
    if (changed) { renderAll(); diffCallouts(data); }
    else renderStatus();
  } catch (e) {
    // live data was seen before and is now unreachable: keep it, flag it
    console.warn('poll failed', e);
    renderStatus();
  }
}

// ---------------------------------------------------------------- navigation
const SCREENS = ['title', 'fight', 'results', 'fame', 'history', 'join'];
function parseHash() {
  const h = (location.hash || '#title').slice(1);
  const [name, arg] = h.split('/');
  return { name: SCREENS.includes(name) ? name : 'title', arg };
}
function applyHash() {
  const { name, arg } = parseHash();
  if (name === 'results' && arg && /^\d+$/.test(arg)) { S.round = Number(arg); if (S.data) renderResults(); }
  S.screen = name;
  $$('.screen').forEach(s => s.classList.toggle('active', s.dataset.screen === name));
  $$('.hud-nav a').forEach(a => a.classList.toggle('on', a.dataset.screen === name));
  window.scrollTo({ top: 0 });
}
function go(name, arg) {
  const target = `#${name}${arg !== undefined ? '/' + arg : ''}`;
  if (location.hash === target) applyHash(); else location.hash = target;
}

// attract mode: cycle the screens until somebody touches the cabinet
let attractTimer = null;
const ATTRACT = [['title', 9000], ['fight', 22000], ['results', 16000], ['fame', 12000], ['history', 10000]];
let attractIdx = 0;
function attractStep() {
  if (!S.attract) return;
  const [name, ms] = ATTRACT[attractIdx % ATTRACT.length];
  attractIdx++;
  if (name === 'results' && S.data) {
    const settled = S.data.rounds.filter(r => r.settlement);
    if (settled.length) { const r = settled[Math.floor(Math.random() * settled.length)]; go('results', r.round_id); }
    else go('results');
  } else go(name);
  attractTimer = setTimeout(attractStep, ms);
}
function setAttract(on, restart = true) {
  S.attract = on;
  const b = $('#btn-attract');
  b.textContent = `ATTRACT: ${on ? 'ON' : 'OFF'}`;
  b.setAttribute('aria-pressed', String(on));
  clearTimeout(attractTimer);
  if (on && restart) { attractIdx = 0; attractTimer = setTimeout(attractStep, 6000); }
}

// ---------------------------------------------------------------- wiring
function copyText(id) {
  const el = document.getElementById(id);
  const text = el ? el.textContent : '';
  const done = () => showCallout('COPIED', 'GO FIGHT');
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, () => fallbackCopy(el, done));
  else fallbackCopy(el, done);
}
function fallbackCopy(el, done) {
  try {
    const range = document.createRange(); range.selectNodeContents(el);
    const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
    document.execCommand('copy'); sel.removeAllRanges(); done();
  } catch (e) { /* the text is selected for a manual copy */ }
}

function wire() {
  window.addEventListener('hashchange', applyHash);

  $('#btn-start').addEventListener('click', () => { SFX.coin(); showCallout('ROUND ' + (S.data && S.data.open[0] ? S.data.open[0].round_id : '1'), 'FIGHT!'); setTimeout(() => go('fight'), 700); });

  $('#btn-attract').addEventListener('click', e => { e.stopPropagation(); setAttract(!S.attract); });
  $('#btn-crt').addEventListener('click', e => {
    const on = !document.body.classList.contains('crt-on');
    document.body.classList.toggle('crt-on', on);
    e.currentTarget.textContent = `CRT: ${on ? 'ON' : 'OFF'}`; e.currentTarget.setAttribute('aria-pressed', String(on));
    try { localStorage.setItem('qdojo.crt', on ? '1' : '0'); } catch (err) { /* ignore */ }
  });
  $('#btn-sound').addEventListener('click', e => {
    S.sound = !S.sound;
    if (S.sound && !S.audio) { try { S.audio = new (window.AudioContext || window.webkitAudioContext)(); } catch (err) { S.sound = false; } }
    if (S.audio && S.audio.state === 'suspended') S.audio.resume();
    e.currentTarget.textContent = `SOUND: ${S.sound ? 'ON' : 'OFF'}`; e.currentTarget.setAttribute('aria-pressed', String(S.sound));
    if (S.sound) SFX.coin();
  });

  // delegated buttons inside rendered screens
  document.addEventListener('click', async e => {
    const t = e.target.closest('[data-replay],[data-verify],[data-copy]');
    if (!t) return;
    if (t.dataset.replay) { const r = S.data.rounds.find(x => x.round_id === Number(t.dataset.replay)); if (r) replayRound(r); }
    if (t.dataset.copy) copyText(t.dataset.copy);
    if (t.dataset.verify) runVerify(Number(t.dataset.verify), true);
  });

  // any touch of the cabinet ends attract mode
  const stop = e => { if (S.attract && !(e.target && e.target.closest && e.target.closest('#btn-attract'))) setAttract(false); };
  document.addEventListener('pointerdown', stop, { capture: true });
  document.addEventListener('keydown', e => {
    stop(e);
    if (e.target && /input|textarea/i.test(e.target.tagName)) return;
    if (S.screen === 'title' && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); $('#btn-start').click(); }
    if (S.screen === 'results' && S.data) {
      const ids = S.data.rounds.map(r => r.round_id), i = ids.indexOf(S.round);
      if (e.key === 'ArrowLeft' && i > 0) go('results', ids[i - 1]);
      if (e.key === 'ArrowRight' && i < ids.length - 1) go('results', ids[i + 1]);
    }
    const n = parseInt(e.key, 10);
    if (n >= 1 && n <= SCREENS.length && !e.metaKey && !e.ctrlKey && !e.altKey) go(SCREENS[n - 1]);
  });

  try { if (localStorage.getItem('qdojo.crt') === '0') $('#btn-crt').click(); } catch (e) { /* ignore */ }
}

// ---------------------------------------------------------------- boot
(async function boot() {
  wire();
  applyHash();
  await poll();
  setInterval(poll, POLL_MS);
  setInterval(updateTicks, TICK_MS);
  // The cabinet only cycles on its own when nobody asked for a specific screen.
  setAttract(parseHash().name === 'title', true);
})();
