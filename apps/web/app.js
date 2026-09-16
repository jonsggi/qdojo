/* QDOJO spectator page.
 *
 * Reads ./data/history.json (every round), ./data/board.json (open rounds),
 * ./data/fighters.json (performance per fighter) and ./data/belts.json (the
 * ladder), polls them every 10 s, and re-renders only the parts whose data
 * changed. If the live files are missing it loads ./data/sample-*.json; if
 * even those cannot be fetched (file://) it uses the tiny EMBEDDED set so the
 * cabinet still lights up. No build step, no framework.
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
  fighter: null,       // selected identity on the fighter card screen
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
function signed(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '—';
  return (Number(n) > 0 ? '+' : Number(n) < 0 ? '−' : '') + fmt(Math.abs(Number(n)));
}
function pct(x) { return x === null || x === undefined ? '—' : `${Math.round(Number(x) * 100)}%`; }
// "41.2 T · 20.6 s": ticks and seconds at 0.5 s per tick
function ticksSecs(t) {
  if (t === null || t === undefined) return '—';
  const n = Number(t);
  const s = n * TICK_MS / 1000;
  return `${Number.isInteger(n) ? fmt(n) : n.toFixed(1)} T · ${s.toFixed(1)} s`;
}
function fighterHref(id) { return `#fighter/${encodeURIComponent(id || '')}`; }
function fighterLink(id, inner, cls = '') {
  if (!id) return inner;
  return `<a class="flink ${cls}" href="${fighterHref(id)}" title="FIGHTER CARD">${inner}</a>`;
}
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

// The three side files are optional: the page works from history.json alone.
async function optionalJSON(url) { try { return await fetchJSON(url); } catch (e) { return null; } }
async function loadSet(prefix) {
  const history = await fetchJSON(`./data/${prefix}history.json`);
  if (!history || !Array.isArray(history.rounds)) throw new Error(`${prefix}history.json has no rounds`);
  const [board, fighters, belts] = await Promise.all([
    optionalJSON(`./data/${prefix}board.json`), optionalJSON(`./data/${prefix}fighters.json`), optionalJSON(`./data/${prefix}belts.json`)]);
  return { history, board, fighters, belts };
}
async function loadData() {
  // 1. the live export
  try {
    return Object.assign(await loadSet(''), { source: 'live' });
  } catch (e) {
    if (S.liveSeen) throw e; // keep the last good live data, do not flip to the sample
  }
  // 2. the sample files
  try {
    return Object.assign(await loadSet('sample-'), { source: 'sample' });
  } catch (e) { /* fall through */ }
  // 3. embedded last resort
  return { history: EMBEDDED.history, board: EMBEDDED.board, fighters: null, belts: null, source: 'embedded' };
}

const DEFAULT_LADDER = ['white', 'yellow', 'orange', 'green', 'blue'];
const DEFAULT_RULES = { promote_at: 3, demote_at: -3, winner: 2, solved: 1, failure: -1 };

function normalise(history, board, fighters, belts) {
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
    open = rounds.filter(r => OPEN_STATES.has(r.state));
  }
  rounds.sort((a, b) => a.round_id - b.round_id);
  open.sort((a, b) => a.round_id - b.round_id);
  // fighters.json is the rich row; history.fighters is the older, thinner one
  const rows = (fighters && Array.isArray(fighters.fighters)) ? fighters.fighters : (history.fighters || []);
  const ladder = (belts && Array.isArray(belts.ladder) && belts.ladder.length) ? belts.ladder.map(String) : DEFAULT_LADDER;
  const rules = Object.assign({}, DEFAULT_RULES, (belts && belts.rules) || {});
  const beltState = (belts && belts.belts) || history.belts || (board && board.belts) || {};
  const profiles = new Map();
  for (const f of rows) if (f && f.identity) profiles.set(f.identity, Object.assign({}, f));
  const stub = id => { if (!profiles.has(id)) profiles.set(id, { identity: id, name: null, bow_tick: null }); return profiles.get(id); };
  for (const id of Object.keys(beltState)) stub(id);
  for (const r of rounds) for (const e of r.entries || []) { const p = stub(e.identity); if (!p.name && e.name) p.name = e.name; }
  for (const [id, p] of profiles) {
    const b = beltState[id];
    if (b) { if (p.belt == null) p.belt = b.belt; if (p.rank == null) p.rank = b.rank; if (p.points == null) p.points = b.points; }
    if (p.belt == null) p.belt = ladder[0];
    if (p.rank == null) p.rank = Math.max(0, ladder.indexOf(String(p.belt)));
    if (p.points == null) p.points = 0;
  }
  const names = new Map(Array.from(profiles.values()).filter(f => f.name).map(f => [f.identity, f.name]));
  return {
    house: history.house || (board && board.house) || '',
    generated_at: history.generated_at || null,
    generated_tick: Math.max(Number(history.generated_tick) || 0, Number(board && board.generated_tick) || 0),
    rounds, open, fighters: rows, names, profiles, ladder, rules,
    fightersFile: !!(fighters && Array.isArray(fighters.fighters)),
  };
}

// Everything the fighter card needs, computed from history.json when the
// fighters.json row is missing or thin (an older export). A field the export
// gave is never overwritten: the house's numbers win over ours.
const FAILURES = new Set(['wrong', 'no_reveal', 'no_commit', 'bad_reveal']);
function deriveStats(identity) {
  const d = { rounds_played: 0, solved: 0, wins: 0, losses: 0, staked: 0, earned: 0, strikes: 0, streak: 0, best_streak: 0, by_belt: {}, belt_history: [] };
  const ticks = [];
  for (const r of S.data.rounds) {
    const s = r.settlement, settled = !!s && !s.void;
    for (const e of r.entries || []) {
      if (e.identity !== identity) continue;
      if (e.verdict === 'duplicate' || e.verdict === 'bad_reveal') d.strikes++;
      if (!COUNTED.has(e.verdict)) continue;
      d.rounds_played++;
      if (settled) d.staked += e.stake || 0;
      const bb = d.by_belt[r.belt || 'open'] || (d.by_belt[r.belt || 'open'] = { rounds: 0, solved: 0, wins: 0, ticks: [] });
      bb.rounds++;
      if (e.verdict === 'winner' || e.verdict === 'solved') {
        d.solved++; bb.solved++;
        if (e.commit_tick && r.publish_tick) { ticks.push(e.commit_tick - r.publish_tick); bb.ticks.push(e.commit_tick - r.publish_tick); }
      }
      if (e.verdict === 'winner') {
        d.wins++; bb.wins++;
        if (settled) { d.streak = d.streak >= 0 ? d.streak + 1 : 1; d.best_streak = Math.max(d.best_streak, d.streak); }
      } else if (settled && FAILURES.has(e.verdict)) {
        d.losses++; d.streak = d.streak <= 0 ? d.streak - 1 : -1;
      }
    }
    if (settled) {
      for (const p of s.payouts || []) if (p.identity === identity && (p.kind === 'win' || p.kind === 'bond_release') && p.confirmed) d.earned += p.amount || 0;
      for (const c of s.belt_changes || []) if (c.identity === identity) {
        const name = x => typeof x === 'number' ? (S.data.ladder[x] || String(x)) : String(x);
        d.belt_history.push({ round_id: r.round_id, from: name(c.before ?? c.from), to: name(c.after ?? c.to), reason: c.reason || '' });
      }
    }
  }
  const avg = xs => xs.length ? Math.round(10 * xs.reduce((a, b) => a + b, 0) / xs.length) / 10 : null;
  d.net = d.earned - d.staked;
  d.avg_solve_ticks = avg(ticks);
  d.best_solve_ticks = ticks.length ? Math.min(...ticks) : null;
  d.solve_rate = d.rounds_played ? Math.round(100 * d.solved / d.rounds_played) / 100 : null;
  d.win_rate = d.rounds_played ? Math.round(100 * d.wins / d.rounds_played) / 100 : null;
  d.win_loss = d.losses ? Math.round(100 * d.wins / d.losses) / 100 : (d.wins ? d.wins : null);
  for (const bb of Object.values(d.by_belt)) { bb.avg_solve_ticks = avg(bb.ticks); delete bb.ticks; }
  return d;
}
function profileOf(identity) {
  const p = S.data.profiles.get(identity);
  if (!p) return null;
  if (!p._complete) {
    const d = deriveStats(identity);
    for (const k of Object.keys(d)) if (p[k] === undefined || p[k] === null && k !== 'solve_rate' && k !== 'win_rate' && k !== 'win_loss' && k !== 'avg_solve_ticks' && k !== 'best_solve_ticks') p[k] = d[k];
    if (!p.by_belt || !Object.keys(p.by_belt).length) p.by_belt = d.by_belt;
    if (!Array.isArray(p.belt_history) || !p.belt_history.length) p.belt_history = d.belt_history;
    p._complete = true;
  }
  return p;
}
function allProfiles() { return Array.from(S.data.profiles.keys()).map(profileOf); }
// leaderboard: by net, then wins, then identity (the fighters.json order)
function byNet(a, b) { return ((b.net || 0) - (a.net || 0)) || ((b.wins || 0) - (a.wins || 0)) || String(a.identity).localeCompare(String(b.identity)); }

// ---------------------------------------------------------------- round helpers
// Verdicts whose stake stays in the pot. "no_commit" bought a seat and never
// fought: the seat is forfeited to the pot. "void" is refunded, so not counted.
const COUNTED = new Set(['winner', 'solved', 'wrong', 'no_reveal', 'no_commit', 'bad_reveal', 'pending']);
const OPEN_STATES = new Set(['lobby', 'commit', 'reveal']);
const BELTS = ['white', 'yellow', 'orange', 'green', 'blue', 'purple', 'brown', 'black'];
function isLobby(r) { return r.state === 'lobby'; }
function isVoid(r) { return r.state === 'void' || !!(r.settlement && r.settlement.void); }
function hasLobby(r) { return r.lobby_tick !== null && r.lobby_tick !== undefined; }
function windows(r) {
  const c0 = r.publish_tick + 1, c1 = r.publish_tick + r.commit_window;
  return { c0, c1, r0: c1 + 1, r1: c1 + r.reveal_window };
}
function lobbyWindow(r) {
  return { l0: (r.lobby_tick || 0) + 1, l1: (r.lobby_tick || 0) + (r.lobby_window || 0) };
}
function nowTick() {
  if (!S.data) return 0;
  const elapsed = Math.floor((Date.now() - S.fetchedAt) / TICK_MS);
  return S.data.generated_tick + Math.max(0, elapsed);
}
function phaseAt(r, tick) {
  if (isLobby(r) || r.publish_tick === null || r.publish_tick === undefined) {
    // the table is open: the riddle is not published yet, the lobby meter runs
    const l = lobbyWindow(r);
    if (tick <= l.l1) return { phase: 'lobby', remaining: l.l1 - tick, total: r.lobby_window || 1, end: l.l1 };
    return { phase: 'lobby_over', remaining: 0, total: r.lobby_window || 1, end: l.l1 };
  }
  const w = windows(r);
  if (tick <= w.c1) return { phase: 'commit', remaining: w.c1 - tick, total: r.commit_window, end: w.c1 };
  if (tick <= w.r1) return { phase: 'reveal', remaining: w.r1 - tick, total: r.reveal_window, end: w.r1 };
  return { phase: 'over', remaining: 0, total: r.reveal_window, end: w.r1 };
}
// The seed the house adds for a given amount of counted stakes (docs/spec.md §5):
// carry in, plus min(seed cap, stakes × match_bps / 10000), or the fixed seed when match_bps is 0.
function seedFor(r, stakes) {
  const cap = r.house_seed || 0, bps = r.match_bps || 0;
  const matched = bps ? Math.min(cap, Math.floor(stakes * bps / 10000)) : cap;
  return (r.carry_in || 0) + matched;
}
function countedStakes(r) {
  return (r.entries || []).filter(e => COUNTED.has(e.verdict)).reduce((a, e) => a + (e.stake || 0), 0);
}
function livePot(r) {
  if (r.settlement) return r.settlement.pot;
  const stakes = countedStakes(r);
  return seedFor(r, stakes) + stakes;
}
function seedUsed(r) {
  const s = r.settlement;
  if (s && s.seed_used !== null && s.seed_used !== undefined) return s.seed_used;
  if (s && s.void) return 0;
  return seedFor(r, countedStakes(r));
}
// "HOUSE MATCH 1:1" for 10000 bps, "1:2" for 5000, "FIXED" for 0, reduced ratio otherwise.
function matchLabel(bps) {
  bps = Number(bps) || 0;
  if (bps <= 0) return 'FIXED';
  const gcd = (a, b) => b ? gcd(b, a % b) : a;
  const g = gcd(bps, 10000);
  return `${bps / g}:${10000 / g}`;
}
function payoutModeLabel(r) {
  if (r.payout_mode === 'first') return 'FIRST WINS';
  if (r.payout_mode === 'split') return 'SPLIT';
  if (r.payout_mode === 'podium') return 'PODIUM 5:3:2';
  return r.payout_mode ? String(r.payout_mode).toUpperCase() : '—';
}
const PODIUM_WEIGHTS = [5, 3, 2];
function bondLabel(r) {
  if (!r.bond_bps) return '';
  return `BOND ${(r.bond_bps / 100).toFixed(r.bond_bps % 100 ? 1 : 0)}% · ${fmt(r.bond_rounds)} MORE FIGHT${r.bond_rounds === 1 ? '' : 'S'}`;
}
function beltTag(r, cls = '') {
  const b = String(r.belt || '').toLowerCase();
  if (!b) return '';
  const known = BELTS.includes(b) ? b : 'other';
  return `<span class="belt belt-${known} ${cls}" title="${esc(b)} belt">${esc(b.toUpperCase())} BELT</span>`;
}
// The coloured belt band on a fighter card.
function beltBand(belt, cls = '') {
  const b = String(belt || 'white').toLowerCase();
  const known = BELTS.includes(b) ? b : 'other';
  return `<div class="beltband beltband-${known} ${cls}" title="${esc(b)} belt">${esc(b.toUpperCase())} BELT</div>`;
}
function seatsText(seats) {
  // "6 / 3" reads like a fraction; say what it means.
  if (!seats.min) return `${seats.bought} SEATED`;
  return seats.bought >= seats.min ? `${seats.bought} SEATED · ${seats.min} NEEDED` : `${seats.bought} SEATED · ${seats.min - seats.bought} MORE NEEDED`;
}
function seatsShort(seats) {
  return seats.min ? `${seats.bought} (${seats.min} needed)` : `${seats.bought}`;
}
function seatsOf(r) {
  // Seats bought so far. Prefer the counted export figure; fall back to the entries we can see.
  const seated = (r.entries || []).filter(e => e.verdict === 'pending' || COUNTED.has(e.verdict));
  const bought = Math.max(Number(r.entrants) || 0, seated.length);
  return { bought, min: Number(r.min_players) || 0, seated };
}
function entryTick(e) {
  return e.commit_tick ?? e.enter_tick ?? Number.MAX_SAFE_INTEGER;
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
  if (isVoid(r)) {
    const seats = seatsOf(r);
    return { text: 'NO CONTEST', cls: 'timeover void', sub: `TABLE NEVER FILLED · ${seatsText(seats)} · REFUNDED` };
  }
  if (!r.settlement) {
    if (r.state === 'settling') return { text: 'SETTLING', cls: 'progress' };
    if (r.state === 'lobby') return { text: 'TABLE OPEN', cls: 'progress', sub: 'WAITING FOR CHALLENGERS' };
    if (r.state === 'commit') return { text: 'FIGHT!', cls: 'progress' };
    if (r.state === 'reveal') return { text: 'REVEAL!', cls: 'progress' };
    return { text: '…', cls: 'progress' };
  }
  const n = (r.settlement.winners || []).length;
  const counted = (r.entries || []).filter(e => COUNTED.has(e.verdict)).length;
  const solved = (r.entries || []).filter(e => e.verdict === 'solved').length;
  const later = solved ? ` · ${solved} SOLVED LATER, NO PAY` : '';
  const first = r.payout_mode === 'first', podium = r.payout_mode === 'podium';
  if (n === 0) return { text: 'TIME OVER', cls: 'timeover', sub: 'NO WINNER · POT CARRIES' };
  if (n === 1) return { text: 'K.O.', cls: 'ko', perfect: counted >= 3, sub: (first ? 'FIRST TO SOLVE TAKES THE POT' : podium ? 'ALONE ON THE PODIUM · TAKES THE POT' : 'ONE WINNER TAKES THE POT') + later };
  if (n === 2) return { text: 'DOUBLE K.O.', cls: 'ko', sub: (podium ? 'PODIUM · TWO SOLVERS SPLIT 5:3' : 'TWO WINNERS SPLIT THE POT') + later };
  if (n === 3) return { text: 'TRIPLE K.O.', cls: 'ko', sub: (podium ? 'PODIUM · FIRST THREE SPLIT 5:3:2' : 'THREE WINNERS SPLIT THE POT') + later };
  return { text: `${n}x K.O.`, cls: 'ko', sub: `${n} WINNERS SPLIT THE POT${later}` };
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
async function settlementHash(s) {
  const body = Object.assign({}, s); delete body.hash; delete body.settle_tx; delete body.settle_tick;
  return sha256hex(concat(enc.encode('qdojo/settlement/v0'), enc.encode(canonicalJSON(body))));
}
async function verifyRound(r) {
  if (!(window.crypto && crypto.subtle)) return [{ ok: false, label: 'VERIFY needs https or localhost (no WebCrypto here)' }];
  const out = [];
  // A lobby or void round never published a riddle: nothing to hash there.
  const pub = r.riddle && r.riddle_hash ? { round_id: r.riddle.round_id, title: r.riddle.title, statement: r.riddle.statement, input: r.riddle.input, answer_format: r.riddle.answer_format } : null;
  if (pub) {
    const h = await sha256hex(concat(enc.encode('qdojo/riddle/v0'), enc.encode(canonicalJSON(pub))));
    out.push({ ok: h === r.riddle_hash, label: 'RIDDLE HASH', detail: h });
  }
  if (r.settlement) {
    const s = r.settlement;
    if (!s.void && r.answer_commitment && s.answer !== null && s.answer !== undefined && s.dojo_salt) {
      const canon = canonicalAnswer(s.answer, r.riddle ? r.riddle.answer_format : 'string');
      const c = await sha256hex(concat(enc.encode('qdojo/answer/v0'), u32le(r.round_id), hexBytes(s.dojo_salt), enc.encode(canon)));
      out.push({ ok: c === r.answer_commitment, label: 'ANSWER COMMITMENT', detail: c });
    }
    if (!s.hash) {
      out.push({ ok: false, label: 'SETTLEMENT HASH · NOT PUBLISHED YET' });
    } else {
      let sh = await settlementHash(s), label = 'SETTLEMENT HASH';
      if (s.void && sh !== s.hash && S.source === 'live') {
        // The live export condenses a void settlement; the hashed document is the
        // published settlements/<round>.json. Verify that one when it can be fetched.
        try {
          const doc = await fetchJSON(`./data/settlements/${r.round_id}.json`);
          if (doc && typeof doc === 'object') { sh = await settlementHash(doc); label = 'SETTLEMENT HASH (settlements/' + r.round_id + '.json)'; }
        } catch (e) { /* keep the page-body hash and report the mismatch */ }
      }
      out.push({ ok: sh === s.hash, label, detail: sh });
    }
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
  for (const o of d.open.slice(0, 2)) {
    if (isLobby(o)) { const seats = seatsOf(o); lines.push(`<div class="blink">ROUND ${o.round_id} TABLE OPEN — ${seatsText(seats)} · INSERT COIN</div>`); }
    else lines.push(`<div class="blink">ROUND ${o.round_id} IN PROGRESS — ${esc(o.state.toUpperCase())} WINDOW</div>`);
  }
  if (!d.rounds.length) lines.push('<div class="muted">NO ROUNDS YET. THE BELL HAS NOT RUNG.</div>');
  setHTML('title-ticker', lines.join(''));
  const roster = d.fighters.filter(f => f.name).slice(0, 8).map(f => `<a class="roster-walk" href="${fighterHref(f.identity)}" title="${esc(f.name)}">${avatarSVG(f.identity)}</a>`).join('');
  setHTML('title-roster', roster);
  setHTML('title-house', d.house ? `HOUSE ${idLink(d.house)}` : '');
}

// The riddle of a lobby (or void) round was never published: show the seal, not a blank.
function sealedHTML(r) {
  const seats = seatsOf(r);
  const line = isVoid(r)
    ? `THE TABLE NEVER FILLED · ${seatsText(seats)} · THE RIDDLE STAYS SEALED`
    : `RIDDLE SEALED UNTIL THE TABLE IS FULL`;
  return `<div class="sealed">
    <span class="sealed-lock" aria-hidden="true"><svg viewBox="0 0 8 8" shape-rendering="crispEdges"><rect x="2" y="0" width="4" height="1" fill="#24e6ff"/><rect x="1" y="1" width="1" height="2" fill="#24e6ff"/><rect x="6" y="1" width="1" height="2" fill="#24e6ff"/><rect x="0" y="3" width="8" height="5" fill="#ffd200"/><rect x="3" y="4" width="2" height="1" fill="#0a0f3d"/><rect x="3" y="5" width="2" height="2" fill="#0a0f3d"/></svg></span>
    <div class="sealed-text${isVoid(r) ? '' : ' pulse'}">${line}</div>
    <p class="tiny muted">${isVoid(r) ? 'No PUBLISH was sent, so there is no riddle hash and no answer commitment to verify. Only the refunds were settled.' : 'The house sends PUBLISH with the riddle hash and the answer commitment the moment the last seat is bought. Until then nobody, not even a seated fighter, knows the riddle.'}</p>
  </div>`;
}

function riddleHTML(r) {
  if (isLobby(r) || isVoid(r) || (!r.riddle && !r.riddle_hash)) return sealedHTML(r);
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

const VERDICT_LABEL = { solved: 'SOLVED', no_commit: 'NO SHOW', void: 'REFUNDED' };
function entryStatus(e, r) {
  if (e.verdict && e.verdict !== 'pending') {
    const label = VERDICT_LABEL[e.verdict] || e.verdict.replace('_', ' ').toUpperCase();
    return `<span class="badge badge-${esc(e.verdict)}">${esc(label)}</span>`;
  }
  if (e.reveal_tick) return '<span class="badge badge-reveal">REVEALED</span>';
  if (!e.commit_tx && e.enter_tx) return '<span class="badge badge-seated">SEATED</span>';
  return `<span class="badge badge-pending">SEALED</span>`;
}

function entryLinks(e) {
  const parts = [];
  if (e.enter_tx) parts.push(txLink(e.enter_tx, `SEAT @${fmt(e.enter_tick)}`));
  if (e.commit_tx || !e.enter_tx) parts.push(txLink(e.commit_tx, `COMMIT @${fmt(e.commit_tick)}`));
  if (e.reveal_tx) parts.push(txLink(e.reveal_tx, `REVEAL @${fmt(e.reveal_tick)}`));
  return parts.join('\n      ');
}

function fighterCard(e, r, slot) {
  const cls = e.verdict && e.verdict !== 'pending' ? e.verdict : (e.reveal_tick ? 'revealed' : (e.commit_tx ? 'sealed' : 'seated'));
  return `<div class="fcard ${cls}">
    <span class="fslot">${String(slot).padStart(2, '0')}</span>
    ${fighterLink(e.identity, avatarSVG(e.identity, 'avatar-lg'))}
    <div class="fname">${fighterLink(e.identity, displayName(e))}</div>
    <div class="fid">${idLink(e.identity)}</div>
    <div class="fstake">STAKE ${qu(e.stake)}</div>
    <div class="fstatus">${entryStatus(e, r)}</div>
    <div class="flinks">
      ${entryLinks(e)}
    </div>
  </div>`;
}

// A pixel-art chair. Original art. `taken` puts the fighter on it.
function chairSVG() {
  const p = [];
  const put = (x, y, w, h, c) => p.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${c}"/>`);
  put(1, 0, 6, 1, '#ff2a2a'); put(1, 1, 1, 4, '#ff2a2a'); put(6, 1, 1, 4, '#ff2a2a');   // backrest frame
  put(2, 1, 4, 1, '#b30000'); put(2, 3, 4, 1, '#b30000');                              // slats
  put(0, 5, 8, 2, '#ffd200'); put(1, 6, 6, 1, '#d9b000');                               // seat
  put(0, 7, 1, 3, '#f4f4f4'); put(7, 7, 1, 3, '#f4f4f4'); put(2, 7, 1, 2, '#9aa3c7'); put(5, 7, 1, 2, '#9aa3c7'); // legs
  return `<svg viewBox="0 0 8 10" shape-rendering="crispEdges">${p.join('')}</svg>`;
}

function seatCard(e, r, slot) {
  if (!e) {
    return `<div class="seat seat-empty">
      <span class="seat-no">SEAT ${String(slot).padStart(2, '0')}</span>
      <div class="seat-chair">${chairSVG()}</div>
      <div class="seat-coin blink">INSERT COIN</div>
      <div class="seat-fee">${qu(r.entry_fee)}</div>
    </div>`;
  }
  if (e.unknown) {
    return `<div class="seat seat-taken">
      <span class="seat-no">SEAT ${String(slot).padStart(2, '0')}</span>
      <div class="seat-chair taken">${chairSVG()}<span class="seat-sit">${avatarSVG('', 'avatar-lg')}</span></div>
      <div class="fname"><span class="muted">TAKEN</span></div>
      <div class="tiny muted">FIGHTER NOT IN HISTORY YET</div>
    </div>`;
  }
  return `<div class="seat seat-taken">
    <span class="seat-no">SEAT ${String(slot).padStart(2, '0')}</span>
    <div class="seat-chair taken">${chairSVG()}<span class="seat-sit">${fighterLink(e.identity, avatarSVG(e.identity, 'avatar-lg'))}</span></div>
    <div class="fname">${fighterLink(e.identity, displayName(e))}</div>
    <div class="fid">${idLink(e.identity)}</div>
    <div class="fstake">SEAT ${qu(e.stake)}</div>
    <div class="fstatus">${entryStatus(e, r)}</div>
    <div class="flinks">${e.enter_tx ? txLink(e.enter_tx, `ENTER @${fmt(e.enter_tick)}`) : '<span class="muted">ENTER TX PENDING</span>'}</div>
  </div>`;
}

// THE TABLE: a lobby round. Seats, a countdown, the fee and the belt; no riddle yet.
function lobbyHTML(r) {
  const seats = seatsOf(r);
  const l = lobbyWindow(r);
  const seated = seats.seated.slice().sort((a, b) => entryTick(a) - entryTick(b));
  const unknown = Math.max(0, seats.bought - seated.length);
  const total = Math.max(seats.min, seats.bought, 1);
  const cards = [];
  for (let i = 0; i < total; i++) {
    const e = i < seated.length ? seated[i] : (i < seated.length + unknown ? { unknown: true } : null);
    cards.push(seatCard(e, r, i + 1));
  }
  const full = seats.min > 0 && seats.bought >= seats.min;
  const pot = livePot(r);
  return `
    <div class="fight-head">
      <div class="fight-round">ROUND ${r.round_id}</div>
      <div class="fight-phase"><span class="badge badge-lobby" data-phase-badge="${r.round_id}">LOBBY</span> THE TABLE ${beltTag(r)}</div>
      <div class="tiny muted">TABLE OPENED @ ${fmt(r.lobby_tick)} · ${esc(r.title || '')}</div>
    </div>

    <div class="table-banner">
      <div class="table-title">WAITING FOR CHALLENGERS</div>
      <div class="table-seats" data-seats="${r.round_id}">${seatsText(seats)}</div>
      <div class="table-sub">${full ? 'THE TABLE IS FULL · THE HOUSE PUBLISHES THE RIDDLE' : `${seats.min - seats.bought} MORE TO RING THE BELL · SEND ENTER WITH THE FEE`}</div>
    </div>

    <div class="panel panel-yellow">
      <h3>SEATS · ${seats.bought} TAKEN</h3>
      <div class="grid-seats">${cards.join('')}</div>
    </div>

    <div class="cols">
      <div class="panel panel-red">
        <h3>LOBBY</h3>
        <div class="meter-label">
          <span data-phase-label="${r.round_id}">—</span>
          <b><span data-ticks-left="${r.round_id}">—</span> TICKS</b>
        </div>
        ${meterHTML(`win-${r.round_id}`, 'warn')}
        <div class="meter-legend">
          <span>LOBBY ${fmt(l.l0)} – ${fmt(l.l1)}</span>
          <span>THEN COMMIT ${fmt(r.commit_window)} · REVEAL ${fmt(r.reveal_window)} TICKS</span>
        </div>
        <div class="continue lobby" data-continue="${r.round_id}">
          <div class="continue-label" data-continue-label="${r.round_id}">INSERT COIN</div>
          <div class="continue-num" data-secs-left="${r.round_id}">—</div>
          <div class="continue-sub" data-continue-sub="${r.round_id}"></div>
        </div>
      </div>

      <div class="panel panel-cyan">
        <h3>THE STAKES</h3>
        <div class="stats" style="margin-bottom:0">
          <div class="stat"><div class="k">ENTRY FEE</div><div class="v">${fmt(r.entry_fee)}</div></div>
          <div class="stat green"><div class="k">MIN PLAYERS</div><div class="v">${fmt(r.min_players)}</div></div>
          <div class="stat cyan"><div class="k">${r.match_bps ? 'SEED CAP' : 'HOUSE SEED'}</div><div class="v">${fmt(r.house_seed)}</div></div>
          <div class="stat cyan"><div class="k">HOUSE MATCH</div><div class="v">${esc(matchLabel(r.match_bps))}</div></div>
          <div class="stat"><div class="k">CARRY IN</div><div class="v">${fmt(r.carry_in)}</div></div>
          <div class="stat"><div class="k">PAYOUT</div><div class="v small">${esc(payoutModeLabel(r))}</div></div>
          <div class="stat"><div class="k">BELT</div><div class="v small">${r.belt ? beltTag(r) : '<span class="muted">OPEN</span>'}</div></div>
          <div class="stat"><div class="k">POT SO FAR</div><div class="v">${fmt(pot)}</div></div>
        </div>
        <p class="tiny muted" style="margin:10px 0 0">A seat bought and never fought is forfeited to the pot. If the table does not fill, every seat is refunded.</p>
      </div>
    </div>

    <div class="panel panel-cyan">
      <h3>THE RIDDLE</h3>
      ${sealedHTML(r)}
    </div>
  `;
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
    if (isLobby(r)) { parts.push(lobbyHTML(r)); continue; }
    const w = windows(r);
    const entries = (r.entries || []).slice().sort((a, b) => entryTick(a) - entryTick(b));
    const staked = countedStakes(r);
    const revealed = entries.filter(e => e.reveal_tick).length;
    const pot = livePot(r);
    const seed = seedFor(r, staked);
    const potPct = Math.min(100, 100 * pot / maxPot());
    const seedPct = potPct * seed / Math.max(1, pot);
    const seats = seatsOf(r);
    const cards = entries.map((e, i) => fighterCard(e, r, i + 1)).join('');
    const empties = entries.length < 4 ? Array.from({ length: 4 - entries.length }, () => '<div class="fcard fcard-empty">OPEN SLOT<br>INSERT COIN</div>').join('') : '';
    parts.push(`
      <div class="fight-head">
        <div class="fight-round">ROUND ${r.round_id}</div>
        <div class="fight-phase"><span class="badge badge-${esc(r.state)}" data-phase-badge="${r.round_id}">${esc(r.state.toUpperCase())}</span> ${esc(r.title)} ${beltTag(r)}</div>
        <div class="tiny muted">PUBLISHED @ ${fmt(r.publish_tick)} · ${txLink(r.publish_tx, 'TX')}${hasLobby(r) ? ` · SEATS ${seatsShort(seats)}` : ''} · ${esc(payoutModeLabel(r))}${r.bond_bps ? ` · ${esc(bondLabel(r))}` : ''}</div>
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
            <span><i style="background:var(--cyan)"></i>HOUSE SEED ${fmt(seed)}${r.match_bps ? ` (MATCH ${esc(matchLabel(r.match_bps))} · CAP ${fmt(r.house_seed)})` : ''}${r.carry_in ? ` · CARRY IN ${fmt(r.carry_in)}` : ''}</span>
            <span><i style="background:var(--yellow)"></i>STAKES ${fmt(staked)}</span>
          </div>
          <div class="stats" style="margin-top:14px;margin-bottom:0">
            <div class="stat"><div class="k">ENTRY FEE</div><div class="v">${fmt(r.entry_fee)}</div></div>
            <div class="stat green"><div class="k">${hasLobby(r) ? 'SEATS' : 'FIGHTERS IN'}</div><div class="v">${hasLobby(r) ? `${seatsShort(seats)}` : entries.length}</div></div>
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
  const entries = (r.entries || []).slice().sort((a, b) => entryTick(a) - entryTick(b));
  if (!entries.length) return '<p class="muted">No entries were observed in this round.</p>';
  const lobby = hasLobby(r) || entries.some(e => e.enter_tx);
  return `<div class="tscroll"><table>
    <thead><tr><th>FIGHTER</th><th>IDENTITY</th><th class="num">STAKE</th>${lobby ? '<th>SEAT</th>' : ''}<th>COMMIT</th><th>REVEAL</th><th>ANSWER</th><th>VERDICT</th></tr></thead>
    <tbody>${entries.map(e => `<tr class="${e.verdict === 'winner' ? 'winner' : ''}">
      <td>${fighterLink(e.identity, `${avatarSVG(e.identity, 'avatar-sm')} ${displayName(e)}`, 'tname')}</td>
      <td>${idLink(e.identity)}</td>
      <td class="num">${fmt(e.stake)}</td>
      ${lobby ? `<td>${e.enter_tx ? txLink(e.enter_tx, '@' + fmt(e.enter_tick)) : '<span class="muted">—</span>'}</td>` : ''}
      <td>${e.commit_tx ? txLink(e.commit_tx, '@' + fmt(e.commit_tick)) : '<span class="muted">—</span>'}</td>
      <td>${e.reveal_tx ? txLink(e.reveal_tx, '@' + fmt(e.reveal_tick)) : '<span class="muted">—</span>'}</td>
      <td class="mono">${e.answer === null || e.answer === undefined ? '<span class="muted">—</span>' : esc(e.answer)}</td>
      <td>${entryStatus(e, r)}</td>
    </tr>`).join('')}</tbody></table></div>`;
}

const PAYOUT_LABEL = { win: 'WIN', refund: 'REFUND', bond_release: 'BOND RELEASED' };
function payoutBadge(kind) {
  const k = String(kind || '');
  return `<span class="badge badge-${esc(k)}">${esc(PAYOUT_LABEL[k] || k.replace(/_/g, ' ').toUpperCase())}</span>`;
}
function bondsHeldTable(s, r) {
  const held = s.bonds_held || [];
  if (!held.length) return '';
  const total = held.reduce((a, b) => a + (b.amount || 0), 0);
  return `<h3 style="margin-top:20px">BONDS HELD · ${held.length}</h3>
    <div class="tscroll"><table>
    <thead><tr><th>WINNER</th><th>KIND</th><th class="num">HELD</th><th>RELEASED WHEN</th></tr></thead>
    <tbody>${held.map(b => `<tr>
      <td>${fighterLink(b.identity, `${avatarSVG(b.identity, 'avatar-sm')} ${displayName({ identity: b.identity })}`, 'tname')} ${idLink(b.identity)}</td>
      <td><span class="badge badge-bond_held">BOND HELD</span></td>
      <td class="num">${fmt(b.amount)}</td>
      <td class="tiny">${r && r.bond_rounds ? `AFTER ${fmt(r.bond_rounds)} MORE FIGHT${r.bond_rounds === 1 ? '' : 'S'}` : 'AFTER THE NEXT FIGHTS'}</td>
    </tr>`).join('')}</tbody></table></div>
    <p class="tiny muted" style="margin:10px 0 0">${fmt(total)} QU of the winnings stays with the house as the winners' bond${r && r.bond_bps ? ` (${(r.bond_bps / 100).toFixed(r.bond_bps % 100 ? 1 : 0)}% of every win)` : ''}. It is paid out with the settlement of the round in which the winner completes the fights; a holder who never comes back forfeits it to the pot.</p>`;
}
function payoutsTable(s, r) {
  const rows = s.payouts || [];
  const released = s.bonds_released || [];
  const forfeited = Number(s.bonds_forfeited) || 0;
  const table = !rows.length ? '<p class="muted">No payouts. The house kept the rake; the rest carries.</p>' : `<div class="tscroll"><table>
    <thead><tr><th>TO</th><th>KIND</th><th class="num">AMOUNT</th><th>TX</th><th>TICK</th><th>CONFIRMED</th></tr></thead>
    <tbody>${rows.map(p => {
      const rel = p.kind === 'bond_release' ? released.find(b => b.identity === p.identity && b.amount === p.amount) : null;
      return `<tr>
      <td>${fighterLink(p.identity, `${avatarSVG(p.identity, 'avatar-sm')} ${displayName({ identity: p.identity })}`, 'tname')} ${idLink(p.identity)}</td>
      <td>${payoutBadge(p.kind)}${rel && rel.bond_round ? ` <a class="tiny" href="#results/${rel.bond_round}">FROM R${rel.bond_round}</a>` : ''}</td>
      <td class="num">${fmt(p.amount)}</td>
      <td>${txLink(p.tx)}</td>
      <td>${p.tick ? fmt(p.tick) : '<span class="muted">—</span>'}</td>
      <td>${p.confirmed ? '<span style="color:var(--green)">YES</span>' : '<span class="blink" style="color:var(--orange)">PENDING</span>'}</td>
    </tr>`; }).join('')}</tbody></table></div>`;
  return table + bondsHeldTable(s, r) + (forfeited ? `<p class="tiny" style="margin:10px 0 0;color:var(--orange)">BONDS FORFEITED: ${fmt(forfeited)} QU went to the pot — a holder did not come back to fight.</p>` : '');
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
    <h2 class="screen-title" style="margin:0">ROUND ${r.round_id}<small>${esc(r.title)} · <span class="badge badge-${esc(r.state)}">${esc(r.state.toUpperCase())}</span> ${beltTag(r)}</small></h2>
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
    ${!s ? `<div class="ko-sub">THIS ROUND IS STILL OPEN — <a href="#fight">${isLobby(r) ? 'THE TABLE' : 'NOW FIGHTING'}</a></div>` : ''}
  </div>`);

  const seats = seatsOf(r);
  const seatTile = hasLobby(r) ? `<div class="stat green"><div class="k">SEATS</div><div class="v">${seatsShort(seats)}</div></div>` : '';
  const moneyTiles = `
      <div class="stat"><div class="k">${r.match_bps ? 'SEED CAP' : 'HOUSE SEED'}</div><div class="v">${fmt(r.house_seed)}</div></div>
      <div class="stat cyan"><div class="k">HOUSE MATCH</div><div class="v">${esc(matchLabel(r.match_bps))}</div></div>
      <div class="stat"><div class="k">CARRY IN</div><div class="v">${fmt(r.carry_in)}</div></div>
      <div class="stat"><div class="k">ENTRY FEE</div><div class="v">${fmt(r.entry_fee)}</div></div>
      <div class="stat"><div class="k">PAYOUT</div><div class="v small">${esc(payoutModeLabel(r))}</div></div>
      ${r.bond_bps ? `<div class="stat cyan"><div class="k">BOND</div><div class="v small">${esc(bondLabel(r))}</div></div>` : ''}
      ${seatTile}`;

  if (s && s.void) {
    // NO CONTEST: the lobby never filled. Nothing but refunds moved.
    const refunds = (s.payouts || []).filter(p => p.kind === 'refund');
    const refunded = refunds.reduce((a, p) => a + (p.amount || 0), 0);
    const l = lobbyWindow(r);
    parts.push(`<div class="stats">
      <div class="stat"><div class="k">POT</div><div class="v">${fmt(s.pot)}</div></div>
      <div class="stat red"><div class="k">RAKE</div><div class="v">${fmt(s.rake)}</div></div>
      <div class="stat cyan"><div class="k">CARRY</div><div class="v">${fmt(s.carry)}</div></div>
      <div class="stat green"><div class="k">REFUNDED</div><div class="v">${fmt(refunded)}</div></div>
      <div class="stat"><div class="k">SEED USED</div><div class="v">${fmt(seedUsed(r))}</div></div>
      ${moneyTiles}
    </div>`);
    parts.push(`<div class="cols">
      <div class="panel panel-cyan">
        <h3>THE TABLE</h3>
        <dl class="kv">
          <dt>LOBBY</dt><dd>${fmt(l.l0)} – ${fmt(l.l1)} (${fmt(r.lobby_window)} ticks, ~${ticksToHuman(r.lobby_window || 0)})</dd>
          <dt>SEATS</dt><dd>${seats.bought} bought, ${fmt(r.min_players)} needed</dd>
          <dt>BELT</dt><dd>${r.belt ? beltTag(r) : '<span class="muted">open</span>'}</dd>
          <dt>RIDDLE</dt><dd class="muted">never published</dd>
        </dl>
        <p class="tiny muted" style="margin:10px 0 0">The carry in rolls on to the next round untouched.</p>
      </div>
      <div class="panel panel-yellow">
        <h3>SETTLEMENT · VERIFY IT YOURSELF</h3>
        <dl class="kv">
          <dt>SETTLE HASH</dt><dd class="mono wrap">${esc(s.hash || '—')}</dd>
          <dt>SETTLE TX</dt><dd>${txLink(s.settle_tx)}</dd>
        </dl>
        <p class="tiny muted" style="margin:10px 0">settlement_hash = SHA-256("qdojo/settlement/v0" ‖ canonical JSON of the settlement without hash, settle_tx, settle_tick). No riddle hash and no answer commitment exist for a void round.</p>
        <button class="btn btn-sm btn-cyan" data-verify="${r.round_id}">VERIFY</button>
        <div class="verify-out" data-verify-out="${r.round_id}"></div>
      </div>
    </div>`);
    parts.push(`<div class="panel panel-cyan"><h3>THE RIDDLE</h3>${sealedHTML(r)}</div>`);
    parts.push(`<div class="panel"><h3>ENTRIES · ${(r.entries || []).length}</h3>${entriesTable(r)}</div>`);
    parts.push(`<div class="panel panel-green"><h3>REFUNDS · ${refunds.length}</h3>${payoutsTable(s)}</div>`);
    if (setHTML('results-body', parts.join(''))) runVerify(r.round_id);
    return;
  }

  if (s) {
    const potPct = Math.min(100, 100 * s.pot / maxPot());
    parts.push(`<div class="stats">
      <div class="stat"><div class="k">POT</div><div class="v">${fmt(s.pot)}</div></div>
      <div class="stat red"><div class="k">RAKE</div><div class="v">${fmt(s.rake)}</div></div>
      <div class="stat cyan"><div class="k">CARRY</div><div class="v">${fmt(s.carry)}</div></div>
      <div class="stat green"><div class="k">WINNERS</div><div class="v">${(s.winners || []).length}</div></div>
      <div class="stat"><div class="k">SEED USED</div><div class="v">${fmt(seedUsed(r))}</div></div>
      ${moneyTiles}
    </div>
    <div class="meter" style="margin-bottom:20px"><div class="meter-fill pot" style="width:${potPct.toFixed(1)}%"></div></div>`);

    // winners in the settlement's order: on a podium that is 1st, 2nd, 3rd
    const podium = r.payout_mode === 'podium';
    const winners = (s.winners || []).map(id => (r.entries || []).find(e => e.identity === id) || { identity: id }).filter(Boolean);
    const payoutFor = id => (s.payouts || []).find(p => p.identity === id && p.kind === 'win');
    const bondFor = id => (s.bonds_held || []).find(b => b.identity === id);
    const wsum = PODIUM_WEIGHTS.slice(0, winners.length).reduce((a, b) => a + b, 0);
    parts.push(`<div class="cols">
      <div class="panel panel-green">
        <h3>WINNERS${podium ? ' · PODIUM 5:3:2' : ''}</h3>
        ${winners.length ? `<div class="winners">${winners.map((e, i) => { const p = payoutFor(e.identity), b = bondFor(e.identity); return `<div class="winner-row">
            ${podium ? `<span class="podium-place place-${i + 1}">${ordinal(i + 1)}</span>` : ''}
            ${fighterLink(e.identity, avatarSVG(e.identity, 'avatar-lg'))}
            <div class="wname">${fighterLink(e.identity, displayName(e))}${podium && PODIUM_WEIGHTS[i] ? ` <span class="tiny muted">${PODIUM_WEIGHTS[i]}/${wsum} OF THE POT</span>` : ''}<br>${idLink(e.identity)}</div>
            <div class="wamt">+${fmt(p ? p.amount : 0)} QU${b ? `<span class="wtx"><span class="badge badge-bond_held">BOND HELD</span> ${fmt(b.amount)} QU</span>` : ''}${p && p.tx ? `<span class="wtx">${txLink(p.tx, 'PAYOUT TX')}</span>` : ''}</div>
          </div>`; }).join('')}</div>`
        : `<p class="muted">Nobody solved it. ${fmt(s.carry)} QU carries into the next round's seed.</p>`}
        ${(r.entries || []).some(e => e.verdict === 'solved') ? `<p class="tiny muted" style="margin:10px 0 0">SOLVED, NO PAY: ${(r.entries || []).filter(e => e.verdict === 'solved').map(e => nameOf(e) || shortId(e.identity)).map(esc).join(', ')} — ${podium ? 'correct, but off the podium. THE FIRST THREE SPLIT 5:3:2.' : 'correct, but not first. FIRST WINS.'}</p>` : ''}
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

  if (!s) {
    parts.push(`<div class="stats">
      <div class="stat"><div class="k">POT SO FAR</div><div class="v">${fmt(livePot(r))}</div></div>
      <div class="stat"><div class="k">SEED SO FAR</div><div class="v">${fmt(seedUsed(r))}</div></div>
      ${moneyTiles}
    </div>`);
  }
  parts.push(`<div class="panel panel-cyan"><h3>THE RIDDLE</h3>${riddleHTML(r)}</div>`);
  parts.push(`<div class="panel"><h3>${isLobby(r) ? 'SEATS' : 'ENTRIES'} · ${(r.entries || []).length}</h3>${entriesTable(r)}</div>`);
  if (s) parts.push(`<div class="panel panel-green"><h3>PAYOUTS · ${(s.payouts || []).length}</h3>${payoutsTable(s, r)}</div>`);
  if (setHTML('results-body', parts.join('')) && s) runVerify(r.round_id);
}

// ---------------------------------------------------------------- fighters
function fighterNameHTML(f) {
  return f.name ? esc(f.name) : '<span class="muted">???</span>';
}
function strikesHTML(n) {
  n = Number(n) || 0;
  if (!n) return '<span class="muted">—</span>';
  return `<span class="strikes">${'✕'.repeat(Math.min(8, n))}</span>${n > 8 ? ` +${n - 8}` : ''}`;
}
function streakHTML(n) {
  n = Number(n) || 0;
  if (!n) return '<span class="muted">—</span>';
  return n > 0 ? `<span style="color:var(--green)">W${n}</span>` : `<span style="color:var(--red)">L${-n}</span>`;
}
function beltRank(f) { const i = S.data.ladder.indexOf(String(f.belt || '').toLowerCase()); return i >= 0 ? i : (Number(f.rank) || 0); }

// The hall of fame boards. `metric` is what the board sorts by (higher is
// better, null keeps the fighter off the board); `score` is what it shows.
const MIN_ROUNDS = 3;
const BOARDS = [
  { key: 'fastest', title: 'FASTEST', sub: 'BEST SOLVE · COMMIT AFTER PUBLISH', cls: 'panel-cyan',
    metric: f => f.best_solve_ticks == null ? null : -f.best_solve_ticks, score: f => ticksSecs(f.best_solve_ticks) },
  { key: 'sharpest', title: 'SHARPEST', sub: `SOLVE RATE · MIN ${MIN_ROUNDS} ROUNDS`, cls: 'panel-green',
    metric: f => (f.rounds_played >= MIN_ROUNDS && f.solve_rate != null) ? f.solve_rate : null, score: f => `${pct(f.solve_rate)} <span class="tiny muted">${fmt(f.solved)}/${fmt(f.rounds_played)}</span>` },
  { key: 'winrate', title: 'WIN RATE', sub: `WINS PER ROUND · MIN ${MIN_ROUNDS} ROUNDS`, cls: 'panel-yellow',
    metric: f => (f.rounds_played >= MIN_ROUNDS && f.win_rate != null) ? f.win_rate : null, score: f => `${pct(f.win_rate)} <span class="tiny muted">${fmt(f.wins)}/${fmt(f.rounds_played)}</span>` },
  { key: 'winloss', title: 'WIN/LOSS', sub: `WINS PER LOSS · MIN ${MIN_ROUNDS} ROUNDS`, cls: 'panel-red',
    metric: f => (f.rounds_played >= MIN_ROUNDS && f.win_loss != null) ? f.win_loss : null, score: f => `${Number(f.win_loss).toFixed(2)} <span class="tiny muted">${fmt(f.wins)}W ${fmt(f.losses)}L</span>` },
  { key: 'streak', title: 'IRON STREAK', sub: 'MOST WINS IN A ROW', cls: 'panel-red',
    metric: f => f.best_streak > 0 ? f.best_streak : null, score: f => `W${fmt(f.best_streak)} <span class="tiny muted">NOW ${streakHTML(f.streak)}</span>` },
  { key: 'belt', title: 'HIGHEST BELT', sub: 'BELT, THEN POINTS', cls: 'panel-cyan',
    metric: f => beltRank(f) * 100 + (Number(f.points) || 0), score: f => `${beltTag({ belt: f.belt }, 'belt-sm')} <span class="tiny muted">${signed(f.points)}</span>` },
  { key: 'fights', title: 'MOST FIGHTS', sub: 'ROUNDS PLAYED', cls: 'panel-yellow',
    metric: f => f.rounds_played > 0 ? f.rounds_played : null, score: f => `${fmt(f.rounds_played)} <span class="tiny muted">${fmt(f.wins)} WON</span>` },
];
function boardHTML(b, all) {
  const rows = all.map(f => ({ f, m: b.metric(f) })).filter(x => x.m !== null && x.m !== undefined && !Number.isNaN(x.m))
    .sort((x, y) => (y.m - x.m) || byNet(x.f, y.f)).slice(0, 8);
  return `<div class="panel board ${b.cls}">
    <h3>${b.title}<small>${b.sub}</small></h3>
    ${rows.length ? `<table class="score-table"><tbody>${rows.map((x, i) => `<tr>
      <td class="rank rank-${i + 1}">${ordinal(i + 1)}</td>
      <td>${fighterLink(x.f.identity, `${avatarSVG(x.f.identity, 'avatar-sm')} ${fighterNameHTML(x.f)}`, 'tname')}</td>
      <td class="num score">${b.score(x.f)}</td>
    </tr>`).join('')}</tbody></table>` : '<p class="muted tiny" style="margin:0">NOBODY QUALIFIES YET</p>'}
  </div>`;
}

function renderFame() {
  const all = allProfiles();
  const rows = all.slice().sort(byNet);
  const parts = [`<h2 class="screen-title">HALL OF FAME<small>HIGH SCORES SINCE ROUND 1 · ${all.length} FIGHTERS · <a href="#fighters">FIGHTER SELECT</a></small></h2>`];
  if (!rows.length) { parts.push('<div class="panel"><p class="muted">No fighter has bowed yet.</p></div>'); setHTML('fame-body', parts.join('')); return; }
  parts.push(`<div class="panel panel-yellow board-main"><h3>RICHEST<small>NET QU · EARNED − STAKED</small></h3><div class="tscroll"><table class="fame-table">
    <thead><tr><th>RANK</th><th>FIGHTER</th><th>IDENTITY</th><th>BELT</th><th class="num">WINS</th><th class="num">PLAYED</th><th class="num">EARNED QU</th><th class="num">NET QU</th><th>STRIKES</th><th>BOWED</th></tr></thead>
    <tbody>${rows.map((f, i) => `<tr>
      <td class="rank rank-${i + 1}">${ordinal(i + 1)}</td>
      <td>${fighterLink(f.identity, `${avatarSVG(f.identity)} ${fighterNameHTML(f)}`, 'tname')}${f.name ? '' : ' <span class="badge">STRANGER</span>'}</td>
      <td>${idLink(f.identity)}</td>
      <td>${beltTag({ belt: f.belt }, 'belt-sm')} <span class="tiny muted">${signed(f.points)}</span></td>
      <td class="num">${fmt(f.wins)}</td>
      <td class="num">${fmt(f.rounds_played)}</td>
      <td class="num qu">${fmt(f.earned)}</td>
      <td class="num ${Number(f.net) < 0 ? 'neg' : 'pos'}">${signed(f.net)}</td>
      <td>${strikesHTML(f.strikes)}</td>
      <td>${f.bow_tick ? '@' + fmt(f.bow_tick) : '<span class="muted">never</span>'}</td>
    </tr>`).join('')}</tbody></table></div>
    <p class="tiny muted" style="margin:12px 0 0">A stranger has not bowed. Strikes: duplicate commits, malformed payloads, reveals without a commit, spam. Phase one evicts on them. Belts: winner +${S.data.rules.winner}, solved +${S.data.rules.solved}, failure ${S.data.rules.failure}; ${signed(S.data.rules.promote_at)} promotes, ${signed(S.data.rules.demote_at)} demotes; a win above your belt promotes you straight there.</p>
    </div>`);
  parts.push(`<div class="boards">${BOARDS.map(b => boardHTML(b, all)).join('')}</div>`);
  const clean = all.filter(f => f.rounds_played > 0 && !(Number(f.strikes) || 0)).sort(byNet);
  parts.push(`<div class="panel panel-green clean-record"><h3>CLEAN RECORD<small>FOUGHT, NEVER STRUCK</small></h3>
    ${clean.length ? `<div class="clean-list">${clean.map(f => fighterLink(f.identity, `${avatarSVG(f.identity, 'avatar-sm')} ${fighterNameHTML(f)}`, 'tname chip-name')).join('')}</div>` : '<p class="muted tiny" style="margin:0">NOBODY YET · EVERY FIGHTER HAS A STRIKE</p>'}
    <p class="tiny muted" style="margin:10px 0 0">No duplicate commit, no bad reveal, no spam — ${clean.length} of ${all.filter(f => f.rounds_played > 0).length} who fought.</p>
  </div>`);
  setHTML('fame-body', parts.join(''));
}

// FIGHTER SELECT: every fighter as a card, best net first.
function selectCard(f, i) {
  return `<a class="scard belt-b-${esc(String(f.belt || 'white').toLowerCase())}" href="${fighterHref(f.identity)}">
    <span class="scard-no">${String(i + 1).padStart(2, '0')}</span>
    ${avatarSVG(f.identity, 'avatar-xl')}
    <div class="scard-name">${f.name ? esc(f.name) : '<span class="muted">STRANGER</span>'}</div>
    ${beltBand(f.belt, 'beltband-sm')}
    <div class="scard-net ${Number(f.net) < 0 ? 'neg' : 'pos'}">${signed(f.net)} QU</div>
    <div class="scard-sub">${fmt(f.wins)} W · ${fmt(f.losses)} L · ${fmt(f.rounds_played)} FIGHTS</div>
    <div class="scard-sub muted">${f.solve_rate == null ? 'NO SOLVES YET' : `SOLVES ${pct(f.solve_rate)}`}${f.best_solve_ticks != null ? `  · BEST ${fmt(f.best_solve_ticks)}T` : ''}</div>
  </a>`;
}
function renderFighters() {
  const all = allProfiles().sort(byNet);
  const parts = [`<h2 class="screen-title">FIGHTER SELECT<small>${all.length} FIGHTERS · SORTED BY NET QU · PICK ONE FOR THE CARD</small></h2>`];
  if (!all.length) parts.push('<div class="panel"><p class="muted">No fighter has bowed yet.</p></div>');
  else parts.push(`<div class="grid-select">${all.map(selectCard).join('')}</div>`);
  setHTML('fighters-body', parts.join(''));
}

// The points meter: cells from demote_at to promote_at, lit from zero toward
// the fighter's points.
function pointsMeter(points, rules) {
  const lo = Number(rules.demote_at) || -3, hi = Number(rules.promote_at) || 3;
  const p = Math.max(lo, Math.min(hi, Number(points) || 0));
  const cells = [];
  for (let v = lo; v <= hi; v++) {
    const lit = v === 0 ? 'zero' : (v < 0 && v >= p) ? 'lit neg' : (v > 0 && v <= p) ? 'lit pos' : '';
    cells.push(`<span class="pts-cell ${lit} ${v === p ? 'cur' : ''}" title="${signed(v)}">${v === 0 ? '0' : signed(v)}</span>`);
  }
  return `<div class="pts">
    <span class="pts-end pts-demote">DEMOTE<br>${signed(lo)}</span>
    <div class="pts-track">${cells.join('')}</div>
    <span class="pts-end pts-promote">PROMOTE<br>${signed(hi)}</span>
  </div>`;
}

function fightsOf(identity) {
  const out = [];
  for (const r of S.data.rounds) {
    for (const e of r.entries || []) {
      if (e.identity !== identity) continue;
      const s = r.settlement;
      const pays = ((s && s.payouts) || []).filter(p => p.identity === identity);
      const win = pays.filter(p => p.kind === 'win').reduce((a, p) => a + (p.amount || 0), 0);
      const refund = pays.filter(p => p.kind === 'refund').reduce((a, p) => a + (p.amount || 0), 0);
      const release = pays.filter(p => p.kind === 'bond_release').reduce((a, p) => a + (p.amount || 0), 0);
      const held = ((s && s.bonds_held) || []).filter(b => b.identity === identity).reduce((a, b) => a + (b.amount || 0), 0);
      const latency = (e.commit_tick && r.publish_tick) ? e.commit_tick - r.publish_tick : null;
      // what this round did to the fighter's balance: every stake went out, refunds bring it back
      out.push({ r, e, win, refund, release, held, latency, net: s ? win + refund + release - (e.stake || 0) : null });
    }
  }
  return out.sort((a, b) => (b.r.round_id - a.r.round_id) || (entryTick(b.e) - entryTick(a.e)));
}

function renderFighter() {
  const d = S.data;
  const id = S.fighter;
  const p = id ? profileOf(id) : null;
  if (!p) {
    setHTML('fighter-body', `<h2 class="screen-title">FIGHTER CARD<small>${id ? 'UNKNOWN FIGHTER' : 'PICK A FIGHTER'}</small></h2>
      <div class="panel"><p class="muted">${id ? `${esc(shortId(id))} has not fought here. ${idLink(id)}` : 'Nobody selected.'}</p>
      <a class="btn btn-sm btn-cyan" href="#fighters">FIGHTER SELECT</a></div>`);
    return;
  }
  const all = allProfiles().sort(byNet);
  const place = all.findIndex(f => f.identity === id) + 1;
  const ladderIdx = beltRank(p);
  const parts = [];
  parts.push(`<div class="res-head">
    <h2 class="screen-title" style="margin:0">FIGHTER CARD<small>${p.name ? esc(p.name) : 'STRANGER'} · ${ordinal(place)} OF ${all.length} BY NET</small></h2>
    <div class="spacer"></div>
    <div class="res-nav">
      <a class="btn btn-sm btn-cyan" href="#fighters">ALL FIGHTERS</a>
      <a class="btn btn-sm" href="#fame">HALL OF FAME</a>
    </div>
  </div>`);

  parts.push(`<div class="cols profile-cols">
    <div class="panel panel-yellow fcb belt-b-${esc(String(p.belt || 'white').toLowerCase())}">
      <div class="fcb-top">
        <div class="fcb-avatar">${avatarSVG(p.identity, 'avatar-xl')}</div>
        <div class="fcb-info">
          <div class="fcb-name">${p.name ? esc(p.name) : 'STRANGER'}</div>
          ${p.name ? '' : '<div class="tiny muted">HAS NOT BOWED · NO NAME ON RECORD</div>'}
          <div class="fcb-id">${idLink(p.identity)} <span class="tiny muted">EXPLORER</span></div>
          <div class="fcb-meta">
            <span>BOWED ${p.bow_tick ? '@' + fmt(p.bow_tick) : '<span class="muted">NEVER</span>'}</span>
            <span>RANK ${ladderIdx + 1} / ${d.ladder.length}</span>
            <span>${ordinal(place)} BY NET</span>
          </div>
        </div>
      </div>
      ${beltBand(p.belt)}
      ${pointsMeter(p.points, d.rules)}
      <div class="pts-label">POINTS <b>${signed(p.points)}</b> · WINNER +${d.rules.winner} · SOLVED +${d.rules.solved} · FAILURE ${d.rules.failure} · ${signed(d.rules.promote_at)} PROMOTES · ${signed(d.rules.demote_at)} DEMOTES</div>
    </div>

    <div class="panel panel-cyan">
      <h3>STATS</h3>
      <div class="stats stats-profile" style="margin-bottom:0">
        <div class="stat"><div class="k">ROUNDS</div><div class="v">${fmt(p.rounds_played)}</div></div>
        <div class="stat cyan"><div class="k">SOLVED</div><div class="v">${fmt(p.solved)}</div></div>
        <div class="stat green"><div class="k">WINS</div><div class="v">${fmt(p.wins)}</div></div>
        <div class="stat red"><div class="k">LOSSES</div><div class="v">${fmt(p.losses)}</div></div>
        <div class="stat"><div class="k">SOLVE RATE</div><div class="v">${pct(p.solve_rate)}</div></div>
        <div class="stat"><div class="k">WIN RATE</div><div class="v">${pct(p.win_rate)}</div></div>
        <div class="stat"><div class="k">WIN / LOSS</div><div class="v">${p.win_loss == null ? '—' : Number(p.win_loss).toFixed(2)}</div></div>
        <div class="stat cyan"><div class="k">AVG SOLVE</div><div class="v small">${ticksSecs(p.avg_solve_ticks)}</div></div>
        <div class="stat cyan"><div class="k">BEST SOLVE</div><div class="v small">${ticksSecs(p.best_solve_ticks)}</div></div>
        <div class="stat"><div class="k">STAKED</div><div class="v">${fmt(p.staked)}</div></div>
        <div class="stat green"><div class="k">EARNED</div><div class="v">${fmt(p.earned)}</div></div>
        <div class="stat ${Number(p.net) < 0 ? 'red' : 'green'}"><div class="k">NET</div><div class="v ${Number(p.net) < 0 ? 'neg' : 'pos'}">${signed(p.net)}</div></div>
        <div class="stat"><div class="k">STREAK</div><div class="v">${streakHTML(p.streak)}</div></div>
        <div class="stat"><div class="k">BEST STREAK</div><div class="v">${p.best_streak ? 'W' + fmt(p.best_streak) : '—'}</div></div>
        <div class="stat red"><div class="k">STRIKES</div><div class="v">${strikesHTML(p.strikes)}</div></div>
      </div>
      <p class="tiny muted" style="margin:10px 0 0">Solve time is the commit tick minus the publish tick; 1 tick ≈ ${(TICK_MS / 1000).toFixed(1)} s. Net is earned minus staked; a bond still held is not earned yet.</p>
    </div>
  </div>`);

  // per-belt table, in ladder order, open tables last
  const belts = Object.keys(p.by_belt || {}).sort((a, b) => {
    const ia = d.ladder.indexOf(a), ib = d.ladder.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b);
  });
  const hist = (p.belt_history || []).slice().sort((a, b) => a.round_id - b.round_id);
  const reasonLabel = s => String(s || '').replace(/_/g, ' ').toUpperCase();
  parts.push(`<div class="cols">
    <div class="panel">
      <h3>BY BELT</h3>
      ${belts.length ? `<div class="tscroll"><table>
        <thead><tr><th>TABLE</th><th class="num">ROUNDS</th><th class="num">SOLVED</th><th class="num">WINS</th><th class="num">AVG SOLVE</th></tr></thead>
        <tbody>${belts.map(k => { const b = p.by_belt[k]; return `<tr>
          <td>${d.ladder.includes(k) || BELTS.includes(k) ? beltTag({ belt: k }, 'belt-sm') : `<span class="belt belt-other belt-sm">${esc(k.toUpperCase())} TABLE</span>`}</td>
          <td class="num">${fmt(b.rounds)}</td><td class="num">${fmt(b.solved)}</td><td class="num">${fmt(b.wins)}</td>
          <td class="num">${ticksSecs(b.avg_solve_ticks)}</td>
        </tr>`; }).join('')}</tbody></table></div>` : '<p class="muted">No rounds fought yet.</p>'}
    </div>
    <div class="panel panel-green">
      <h3>BELT HISTORY</h3>
      <div class="tl">
        <div class="tl-row tl-start"><span class="tl-dot"></span><span class="tl-when">${p.bow_tick ? 'BOW @' + fmt(p.bow_tick) : 'FIRST SEEN'}</span><span class="tl-what">${beltTag({ belt: d.ladder[0] }, 'belt-sm')} <span class="muted">EVERYONE STARTS HERE</span></span></div>
        ${hist.map(h => `<a class="tl-row" href="#results/${h.round_id}"><span class="tl-dot ${h.reason === 'demoted' ? 'down' : 'up'}"></span><span class="tl-when">ROUND ${h.round_id}</span><span class="tl-what">${beltTag({ belt: h.from }, 'belt-sm')} <span class="tl-arrow">${h.reason === 'demoted' ? '▼' : '▶'}</span> ${beltTag({ belt: h.to }, 'belt-sm')} <span class="badge ${h.reason === 'demoted' ? 'badge-wrong' : 'badge-winner'}">${esc(reasonLabel(h.reason))}</span></span></a>`).join('')}
        ${hist.length ? '' : '<div class="tl-row"><span class="tl-dot"></span><span class="tl-when">—</span><span class="tl-what muted">NO BELT CHANGE YET</span></div>'}
      </div>
    </div>
  </div>`);

  const fights = fightsOf(id);
  parts.push(`<div class="panel panel-red"><h3>RECENT FIGHTS · ${fights.length}</h3>
    ${fights.length ? `<div class="hist-list">${fights.map(x => {
      const { r, e } = x;
      const bits = [];
      bits.push(x.latency !== null ? `SOLVE ${ticksSecs(x.latency)}` : (e.commit_tick ? '' : 'NO COMMIT'));
      bits.push(`STAKE ${fmt(e.stake)}`);
      if (x.win) bits.push(`PAID +${fmt(x.win)}`);
      if (x.held) bits.push(`BOND HELD ${fmt(x.held)}`);
      if (x.release) bits.push(`BOND RELEASED +${fmt(x.release)}`);
      if (x.refund) bits.push(`REFUNDED ${fmt(x.refund)}`);
      if (!r.settlement) bits.push(`${esc(r.state.toUpperCase())} · STILL OPEN`);
      const amt = x.net === null ? '<span class="muted">…</span>' : `${signed(x.net)}<small>QU</small>`;
      return `<a class="hist-row ${x.net === null ? 'open' : ''}" href="#results/${r.round_id}">
        <div class="hr-num">R${String(r.round_id).padStart(2, '0')}</div>
        <div><div class="hr-title">${esc(r.title)} ${beltTag(r, 'belt-sm')} ${entryStatus(e, r)}</div>
          <div class="hr-sub">${bits.filter(Boolean).join(' · ')} · ${esc(payoutModeLabel(r))}</div></div>
        <div class="hr-call ${x.net === null ? 'progress' : x.net > 0 ? 'progress' : x.net < 0 ? '' : 'timeover'}">${amt}</div>
      </a>`;
    }).join('')}</div>` : '<p class="muted">No fights on record.</p>'}
  </div>`);
  setHTML('fighter-body', parts.join(''));
}

function renderHistory() {
  const d = S.data;
  const parts = [`<h2 class="screen-title">ROUND HISTORY<small>EVERY ROUND FROM THE BEGINNING · ${d.rounds.length} ROUNDS</small></h2>`];
  if (!d.rounds.length) parts.push('<div class="panel"><p class="muted">No rounds yet.</p></div>');
  else {
    parts.push(`<p style="margin:0 0 14px"><a class="btn btn-sm" href="#results/${d.rounds[0].round_id}">&#9654; WATCH FROM ROUND ${d.rounds[0].round_id}</a></p>`);
    parts.push(`<div class="hist-list">${d.rounds.map(r => {
      const c = callout(r), s = r.settlement, open = !s && OPEN_STATES.has(r.state);
      const names = winnerNames(r);
      const seats = seatsOf(r);
      let sub;
      if (isVoid(r)) {
        const refunded = ((s && s.payouts) || []).filter(p => p.kind === 'refund').reduce((a, p) => a + (p.amount || 0), 0);
        sub = `${seatsText(seats)} · REFUNDED ${fmt(refunded)} QU · CARRY ${fmt(s ? s.carry : r.carry_in)} · TABLE OPENED @${fmt(r.lobby_tick)}`;
      } else if (isLobby(r)) {
        sub = `${seatsText(seats)} · FEE ${fmt(r.entry_fee)} QU · MATCH ${esc(matchLabel(r.match_bps))} · TABLE OPENED @${fmt(r.lobby_tick)}`;
      } else {
        sub = `${(r.entries || []).length} IN${hasLobby(r) ? ` · ${seats.bought} SEATS` : ''} · POT ${fmt(livePot(r))} QU${s ? ` · RAKE ${fmt(s.rake)} · CARRY ${fmt(s.carry)}` : ''} · ${esc(payoutModeLabel(r))} · PUBLISHED @${fmt(r.publish_tick)}${names.length ? ' · ' + esc(names.join(', ')) : ''}`;
      }
      return `<a class="hist-row ${open ? 'open' : ''} ${isVoid(r) ? 'void' : ''}" href="#results/${r.round_id}">
        <div class="hr-num">R${String(r.round_id).padStart(2, '0')}</div>
        <div><div class="hr-title">${esc(r.title)} <span class="badge badge-${esc(r.state)}">${esc(r.state.toUpperCase())}</span> ${beltTag(r, 'belt-sm')}</div>
          <div class="hr-sub">${sub}</div></div>
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
          <dt>ENTRY FEE</dt><dd>${open ? qu(open.entry_fee) : '<span class="muted">see the next LOBBY or PUBLISH</span>'}</dd>
          ${open && hasLobby(open) ? `<dt>LOBBY</dt><dd>${fmt(open.lobby_window)} ticks (~${ticksToHuman(open.lobby_window || 0)}) · ${fmt(open.min_players)} seats to ring the bell ${beltTag(open)}</dd>` : ''}
          <dt>COMMIT</dt><dd>${open ? `${fmt(open.commit_window)} ticks (~${ticksToHuman(open.commit_window)})` : '—'}</dd>
          <dt>REVEAL</dt><dd>${open ? `${fmt(open.reveal_window)} ticks (~${ticksToHuman(open.reveal_window)})` : '—'}</dd>
          <dt>SEED</dt><dd>${open ? `${open.match_bps ? `house matches stakes ${esc(matchLabel(open.match_bps))} up to ${fmt(open.house_seed)}` : `fixed ${fmt(open.house_seed)}`} + carry in` : 'carry in + matched stakes up to the cap'}</dd>
          <dt>PAYOUT</dt><dd>${open ? `${esc(payoutModeLabel(open))} · ` : ''}${open && open.payout_mode === 'podium' ? 'the first three correct commits split (pot − rake) 5:3:2, later solvers get nothing' : `(pot − rake) ÷ winners, remainder carries${open && open.payout_mode === 'first' ? '; first commit tick wins, later solvers get nothing' : ''}`}</dd>
          ${open && open.bond_bps ? `<dt>BOND</dt><dd>${esc(bondLabel(open))}: that share of every win stays with the house until the winner has fought again</dd>` : ''}
          <dt>NO WINNER</dt><dd>pot − rake carries to the next round</dd>
          <dt>NO TABLE</dt><dd>a lobby that does not fill is void: every seat refunded</dd>
          <dt>REFUNDS</dt><dd>underpaid or late commits, in full; a seat with no commit is forfeited</dd>
        </dl>
      </div>
    </div>
    <div class="panel panel-cyan">
      <h3>DOJO ETIQUETTE</h3>
      <ol class="rules">
        <li><b>BOW</b> when you enter. A bot that does not bow is a stranger.</li>
        <li><b>TAKE A SEAT.</b> When the house opens a table, ENTER with the fee before the riddle exists. A seat you do not fight from is forfeited.</li>
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
  renderTitle(); renderFight(); renderResults(); renderFame(); renderFighters(); renderFighter(); renderHistory(); renderJoin(); renderFooter(); renderStatus();
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
    if ((p.phase === 'over' || p.phase === 'lobby_over') && S.source !== 'live') {
      // demo loop: restart the window so the cabinet never sits on zero
      S.fetchedAt = Date.now();
      p = phaseAt(r, nowTick());
    }
    const lobby = p.phase === 'lobby' || p.phase === 'lobby_over';
    const over = p.phase === 'over' || p.phase === 'lobby_over';
    const fill = $(`[data-meter="win-${id}"]`);
    if (fill) {
      const pct = p.total ? 100 * p.remaining / p.total : 0;
      fill.style.width = `${pct.toFixed(1)}%`;
      fill.className = `meter-fill ${p.phase === 'reveal' ? (pct < 25 ? 'crit' : 'warn') : p.phase === 'lobby' ? (pct < 20 ? 'crit' : 'lobby') : (pct < 20 ? 'warn' : '')}`;
    }
    const lbl = $(`[data-phase-label="${id}"]`);
    if (lbl) lbl.textContent = p.phase === 'commit' ? 'COMMIT WINDOW · SEAL YOUR ANSWER'
      : p.phase === 'reveal' ? 'REVEAL WINDOW · SHOW WHAT YOU SEALED'
      : p.phase === 'lobby' ? 'LOBBY OPEN · BUY A SEAT'
      : p.phase === 'lobby_over' ? 'LOBBY CLOSED · THE HOUSE PUBLISHES OR VOIDS'
      : 'TIME OVER · WAITING FOR SETTLEMENT';
    const tl = $(`[data-ticks-left="${id}"]`); if (tl) tl.textContent = fmt(p.remaining);
    const secs = $(`[data-secs-left="${id}"]`); if (secs) secs.textContent = over ? '0' : String(Math.ceil(p.remaining / 2));
    const cont = $(`[data-continue="${id}"]`); if (cont) cont.className = `continue ${p.phase}`;
    const cl = $(`[data-continue-label="${id}"]`); if (cl) cl.textContent = p.phase === 'commit' ? 'COMMIT!' : p.phase === 'reveal' ? 'CONTINUE?' : p.phase === 'lobby' ? 'INSERT COIN' : p.phase === 'lobby_over' ? 'TABLE CLOSED' : 'TIME OVER';
    const cs = $(`[data-continue-sub="${id}"]`); if (cs) cs.textContent = p.phase === 'over' ? 'THE HOUSE SETTLES AFTER THE WINDOW'
      : p.phase === 'lobby_over' ? 'ENOUGH SEATS: THE RIDDLE COMES · TOO FEW: EVERY SEAT IS REFUNDED'
      : `SECONDS LEFT · ${lobby ? 'LOBBY' : 'WINDOW'} ENDS @ TICK ${fmt(p.end)}`;
    const badge = $(`[data-phase-badge="${id}"]`);
    if (badge) {
      const txt = p.phase === 'over' ? 'SETTLING' : p.phase === 'lobby_over' ? 'CLOSED' : p.phase.toUpperCase();
      if (badge.textContent !== txt) { badge.textContent = txt; badge.className = `badge badge-${p.phase === 'over' ? 'settling' : p.phase === 'lobby_over' ? 'settling' : p.phase}`; }
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
  if (!r.settlement) {
    if (isLobby(r)) { showCallout('TABLE OPEN', `ROUND ${r.round_id} · INSERT COIN`, 'cyan'); SFX.coin(); return; }
    showCallout('FIGHT!', `ROUND ${r.round_id}`); SFX.fight(); return;
  }
  showCallout(`ROUND ${r.round_id}`, r.title);
  SFX.fight();
  setTimeout(() => {
    if (isVoid(r)) { showCallout('NO CONTEST', 'TABLE NEVER FILLED · SEATS REFUNDED', 'cyan'); SFX.over(); }
    else if (c.cls === 'timeover') { showCallout('TIME OVER', 'NO WINNER · POT CARRIES', 'cyan'); SFX.over(); }
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
    if (!p) {
      if (c.state === 'lobby') events.push(() => { showCallout('TABLE OPEN', `ROUND ${r.round_id} · INSERT COIN`, 'cyan'); SFX.coin(); });
      else events.push(() => { showCallout(`ROUND ${r.round_id}`, 'FIGHT!'); SFX.fight(); });
      continue;
    }
    if (p.state === 'lobby' && c.state === 'commit') events.push(() => { showCallout('FIGHT!', `ROUND ${r.round_id} · THE TABLE IS FULL`); SFX.fight(); });
    if (p.state === 'commit' && c.state === 'reveal') events.push(() => { showCallout('REVEAL!', `ROUND ${r.round_id}`); SFX.reveal(); });
    if (!p.settled && c.settled) events.push(() => replayRound(r));
  }
  events.forEach((fn, i) => setTimeout(fn, i * 3200));
}

// ---------------------------------------------------------------- polling
async function poll() {
  try {
    const { history, board, fighters, belts, source } = await loadData();
    const data = normalise(history, board, fighters, belts);
    const key = JSON.stringify([history, board, fighters, belts]);
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
const SCREENS = ['title', 'fight', 'results', 'fame', 'fighters', 'history', 'join', 'fighter'];
function parseHash() {
  const h = (location.hash || '#title').slice(1);
  const i = h.indexOf('/');
  let name = i < 0 ? h : h.slice(0, i), arg = i < 0 ? undefined : h.slice(i + 1);
  if (!SCREENS.includes(name)) name = 'title';
  if (name === 'fighter' && !arg) name = 'fighters';   // #fighter alone is the select grid
  return { name, arg };
}
function applyHash() {
  const { name, arg } = parseHash();
  if (name === 'results' && arg && /^\d+$/.test(arg)) { S.round = Number(arg); if (S.data) renderResults(); }
  if (name === 'fighter') {
    let id = arg; try { id = decodeURIComponent(arg); } catch (e) { /* keep raw */ }
    S.fighter = id.toUpperCase();
    if (S.data) renderFighter();
  }
  S.screen = name;
  $$('.screen').forEach(s => s.classList.toggle('active', s.dataset.screen === name));
  $$('.hud-nav a').forEach(a => a.classList.toggle('on', a.dataset.screen === name || (name === 'fighter' && a.dataset.screen === 'fighters')));
  window.scrollTo({ top: 0 });
}
function go(name, arg) {
  const target = `#${name}${arg !== undefined ? '/' + arg : ''}`;
  if (location.hash === target) applyHash(); else location.hash = target;
}

// attract mode: cycle the screens until somebody touches the cabinet
let attractTimer = null;
const ATTRACT = [['title', 9000], ['fight', 22000], ['results', 16000], ['fame', 12000], ['fighters', 9000], ['fighter', 12000], ['history', 10000]];
let attractIdx = 0;
function attractStep() {
  if (!S.attract) return;
  const [name, ms] = ATTRACT[attractIdx % ATTRACT.length];
  attractIdx++;
  if (name === 'results' && S.data) {
    const settled = S.data.rounds.filter(r => r.settlement);
    if (settled.length) { const r = settled[Math.floor(Math.random() * settled.length)]; go('results', r.round_id); }
    else go('results');
  } else if (name === 'fighter') {
    // a random fighter card, someone who actually fought
    const fought = S.data ? allProfiles().filter(f => f.rounds_played > 0) : [];
    if (fought.length) go('fighter', fought[Math.floor(Math.random() * fought.length)].identity);
    else go('fighters');
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
    if (n >= 1 && n <= 7 && !e.metaKey && !e.ctrlKey && !e.altKey) go(SCREENS[n - 1]);
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
