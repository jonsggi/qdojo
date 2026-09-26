/* QDOJO combat spectator and owner page (combat.html).
 *
 * Views, by hash: #arena (default), #title, #book, #results (#fights is an
 * alias), #leaderboard, #fight/<id>, #fighter/<hex>, #practice,
 * #practice/<npc>/<seed>, #join, #rules, #help. The site polls the export
 * every 30 s and repaints live views in place, without a reload.
 *
 * Every replay is re-derived here from the revealed plan bytes with
 * combat/engine.js (via combat/logic.js); the exported traces are only checked
 * against, never shown as fact. Playback is a frame index advanced by a timer:
 * speed, pausing, dropped frames and reduced motion change what moves, never
 * what state is shown. Nothing secret is displayed: plans and salts appear
 * only after their reveal, which is the only time the export carries them.
 */
'use strict';
(() => {
  const L = window.QDojoCombatLogic, E = window.QDojoCombat, N = window.QDojoNpcs;
  // The ruleset every replay and practice fight uses: the export's artifact
  // when it hashes to the manifest digest, else the embedded copy (see boot).
  let R = window.QDojoRuleset;
  let RULES_INFO = { source: 'embedded', note: 'No export loaded; using the embedded copy.' };
  // avatars.js and anim.js declare top-level consts, not window properties.
  const A = typeof QDojoAvatars !== 'undefined' ? QDojoAvatars : null;
  const ANIM = typeof QDojoAnim !== 'undefined' ? QDojoAnim : null;
  const STAGES = typeof QDojoStages !== 'undefined' ? QDojoStages : null;
  const NAMES = L.NAMES;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const HEX64 = /^[0-9a-f]{64}$/, DEC = /^[0-9]{1,19}$/;
  const SPEEDS = [0.25, 0.5, 1, 2, 4];
  const BEAT_MS = 600;
  const SOURCES = [
    { base: 'data/combat/v1/', sample: false },
    { base: 'data/combat/v1/sample/', sample: true },
  ];
  const SHA = L.defaultSha256();
  const sysReduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
  };
  let motionOn = !sysReduced && store.get('qdojo.combat.motion') !== '0';
  const motion = () => motionOn && !sysReduced && !!ANIM && !ANIM.reduced;

  const D = { base: null, sample: false, manifest: null, error: null, cache: new Map(), meta: new Map(), done: new Set(), wallMs: NaN, tick: null, polls: 0 };
  let viewToken = 0;
  let players = [];
  let timers = [];
  let practice = null;
  // What the arena has already shown: fight ID -> resolved rounds, and the
  // fights that were live during this visit (so a finish shows its card).
  const seenRounds = new Map();
  const seenLive = new Set();
  const POLL_MS = 30000;

  // ---- data --------------------------------------------------------------------

  /* Cached per export path. Finished fights never change, so their files stay
   * cached; the poll drops everything that can (see poll). */
  function fetchJson(rel) {
    const key = D.base + rel;
    if (!D.cache.has(key)) {
      D.cache.set(key, fetch(key, { cache: 'no-cache' }).then(r => {
        if (!r.ok) throw new Error(rel + ': HTTP ' + r.status);
        const lm = Date.parse(r.headers.get('Last-Modified') || '');
        D.meta.set(rel, { lastModified: lm });
        return r.json();
      }).then(j => {
        const m = /^fights\/(\d+)\.json$/.exec(rel);
        if (m && j && j.phase === 'DONE') D.done.add(m[1]);
        return j;
      }));
      D.cache.get(key).catch(() => D.cache.delete(key));
    }
    return D.cache.get(key);
  }

  async function trySource(src) {
    const r = await fetch(src.base + 'manifest.json', { cache: 'no-cache' });
    if (!r.ok) return null;
    const m = await r.json();
    // Unknown major schema versions fail closed.
    if (m.schema !== 'qdojo.combat.manifest.v1') { D.error = src.base + 'manifest.json has unknown schema ' + m.schema; return null; }
    return m;
  }

  // Live export first; the sample only when live is missing.
  async function loadSource() {
    for (const src of SOURCES) {
      try {
        const m = await trySource(src);
        if (!m) continue;
        D.base = src.base; D.sample = src.sample; D.manifest = m; D.cache.clear(); D.meta.clear(); D.done.clear();
        const art = HEX64.test(m.ruleset_digest || '') ? await fetchJson('rulesets/' + m.ruleset_digest + '.json').catch(() => null) : null;
        const pick = await L.chooseRuleset({ exported: art, embedded: window.QDojoRuleset, manifestDigest: m.ruleset_digest, sha256: SHA });
        R = pick.rules;
        RULES_INFO = pick;
        await noteFreshness();
        return;
      } catch (e) { /* try the next source */ }
    }
    D.error = D.error || 'No combat export could be fetched (tried ' + SOURCES.map(s => s.base).join(', ') + ').';
  }

  // The snapshot tick and wall time come from index.json: it is rewritten on
  // every export. generated_at wins if the exporter provides it.
  async function noteFreshness() {
    const idx = await fetchJson('index.json').catch(() => null);
    if (idx && idx.names) FIGHTER_NAMES = idx.names;
    const tick = idx ? idx.generated_tick : D.manifest.generated_tick;
    D.tick = tick;
    // Simulated-chain and profile facts, and per-fighter name/driver/asset.
    D.deployment = (idx && idx.deployment) || null;
    D.known = idx && Array.isArray(idx.fights) ? new Set(idx.fights.map(String)) : null;
    const at = idx && idx.generated_at != null ? Date.parse(idx.generated_at) || Number(idx.generated_at) : NaN;
    D.wallMs = Number.isFinite(at) ? at : (D.meta.get('index.json') || {}).lastModified;
  }

  /* Every 30 s: drop what can change (index, book, events, fighters, and any
   * fight not known to be finished), then repaint the view if it shows live
   * data. Nothing reloads the page; a playing replay is not interrupted. */
  async function poll() {
    D.polls++;
    if (D.sample || !D.manifest) {
      // A live export that appears later takes over from the sample.
      const live = await trySource(SOURCES[0]).catch(() => null);
      if (live) { await loadSource(); paintSource(); route(); return; }
      if (!D.manifest) return;
    }
    const done = D.done;
    for (const key of Array.from(D.cache.keys())) {
      const rel = key.slice(D.base.length);
      const fm = /^fights\/(\d+)(\.json|\/replay\.json)$/.exec(rel);
      const volatile = /^(index|book|manifest)\.json$/.test(rel) || /^events\//.test(rel) || /^fighters\//.test(rel) || (fm && !done.has(fm[1]));
      if (volatile) D.cache.delete(key);
    }
    const before = D.tick;
    await noteFreshness().catch(() => {});
    paintSource();
    const name = currentRoute()[0];
    if (['arena', 'title', 'book', 'results', 'leaderboard', 'cups', 'cup', 'duels', 'duel', 'season'].includes(name) || (name === 'fight' && D.tick !== before)) repaint();
  }

  function paintSource() {
    const pill = $('#hud-source');
    if (D.manifest && D.sample) {
      pill.className = 'pill pill-sample';
      pill.textContent = 'SAMPLE';
      pill.title = 'No live export found, so this is the sample from a local devnet: fake QU, synthetic fighters, NPC-driven bots. Not a deployment.';
    } else if (D.manifest) {
      pill.className = 'pill pill-live';
      pill.textContent = 'LIVE EXPORT';
      pill.title = 'Combat export at ' + D.base + '. Same-source data: chain inclusion is not proven by this page.';
    } else {
      pill.className = 'pill pill-lost';
      pill.textContent = 'NO DATA';
      pill.title = D.error || '';
    }
    $('#hud-tick').textContent = D.tick || (D.manifest ? D.manifest.generated_tick : '—');
    const fr = L.freshness(D.wallMs, Date.now());
    const fresh = $('#hud-fresh');
    fresh.textContent = fr.known ? new Date(D.wallMs).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) + ' (' + L.ageText(fr.ageMs) + ')' : '';
    fresh.title = fr.known ? 'Export written ' + new Date(D.wallMs).toString() : 'Export time unknown';
    // The sample is old by design; STALE is for a live export that stopped.
    $('#hud-stale').hidden = !(D.manifest && !D.sample && fr.stale);
    $('#hud-rules').textContent = (R.semantic_version || 'combat-v1').toUpperCase();
    $('#foot-data').innerHTML = D.manifest
      ? 'DATA ' + esc(D.base) + (D.sample ? ' <b class="sample-note">SAMPLE: fake QU, synthetic fighters</b>' : '') +
        ' &middot; NETWORK <span class="id">' + esc(short(D.manifest.network_id)) + '</span> &middot; CONTRACT <span class="id">' + esc(short(D.manifest.contract_id)) + '</span>' +
        ' &middot; refreshed every ' + (POLL_MS / 1000) + ' s &middot; Every replay is re-derived in your browser; rendering never changes a result.'
      : esc(D.error || 'No data. PRACTICE and RULES still work offline.');
  }

  // ---- small renderers -----------------------------------------------------------

  // Display names come from the export's index (a devnet lineup labels its demo bots); IDs otherwise.
  let FIGHTER_NAMES = {};
  const short = hex => FIGHTER_NAMES[hex] || String(hex || '').slice(0, 8);
  const avatar = (hex, cls) => (A ? A.render(hex, cls) : '');
  function fighterLink(hex, label) {
    if (!HEX64.test(hex || '')) return '<span class="muted">?</span>';
    return '<a class="tname flink" href="#fighter/' + hex + '">' + avatar(hex, 'avatar-sm') + '<span class="id">' + esc(label || short(hex)) + '</span></a>';
  }
  const statusBadge = s => '<span class="vstat vstat-' + esc(String(s).toLowerCase()) + '">' + esc(s) + '</span>';
  const levelBadge = lv => '<span class="level level-' + esc(lv) + '">' + esc(lv.replace(/_/g, ' ')) + '</span>';
  const pct = (n, d) => (d ? Math.round(100 * n / d) + '%' : '—');
  const sumOf = arr => arr.reduce((a, b) => a + b, 0);
  const numberFmt = s => String(s).replace(/\B(?=(\d{3})+(?!\d))/g, ',');

  function summaryOutcome(s) {
    const r = s && s.result;
    if (!r) return { result: null, outcome: null };
    return { result: r, outcome: r.kind === 'FORFEIT' ? { winner: r.winner, result: 'FORFEIT' } : { winner: r.winner == null ? null : r.winner, result: r.result } };
  }
  function resultBadge(x) {
    const lab = L.outcomeLabel(x);
    return '<span class="rbadge rbadge-' + lab.kind + '" title="' + esc(lab.text) + '">' + esc(lab.short) + '</span>';
  }

  function screen(title, sub) {
    return '<h2 class="screen-title">' + esc(title) + (sub ? '<small>' + sub + '</small>' : '') + '</h2>';
  }
  function setView(html) {
    const v = $('#view');
    v.classList.remove('has-toc');   // only the reading pages that call addToc() get the side column
    v.innerHTML = html;
    if (ANIM) ANIM.mount(v);
    markScrollers(v);
  }
  function markScrollers(root) {
    $$('.tscroll', root).forEach(el => {
      const upd = () => {
        el.classList.toggle('can-scroll', el.scrollWidth > el.clientWidth + 2);
        el.classList.toggle('at-end', el.scrollLeft + el.clientWidth >= el.scrollWidth - 2);
      };
      el.addEventListener('scroll', upd, { passive: true });
      upd();
    });
  }
  function notFound(what) {
    setView(screen('NOT FOUND') + '<section class="panel panel-red"><h3>NO RECORD</h3><p>' + esc(what) + '</p><p><a href="#results">BACK TO RESULTS</a></p></section>');
  }
  function needData() {
    if (D.manifest) return false;
    setView(screen('NO SIGNAL') + '<section class="panel panel-red"><h3>NO COMBAT EXPORT</h3><p>' + esc(D.error) +
      '</p><p>PRACTICE and RULES work offline: <a href="#practice">PRACTICE</a> &middot; <a href="#rules">RULES</a></p></section>');
    return true;
  }

  // ---- BOOK ------------------------------------------------------------------------

  async function viewBook(tok) {
    if (needData()) return;
    const [book, events] = await Promise.all([fetchJson('book.json'), fetchJson('events/latest.json').catch(() => null)]);
    if (tok !== viewToken) return;
    const gen = BigInt(book.generated_tick), next = BigInt(book.next_matching_tick);
    const wait = next > gen ? next - gen : 0n;
    const cap = book.capacity || {};
    const offers = book.offers || [];
    const rows = offers.map(o => '<tr>' +
      '<td class="num">' + esc(o.offer_id) + '</td>' +
      '<td>' + esc(o.kind) + '</td>' +
      '<td>' + fighterLink(o.fighter_id) + '</td>' +
      '<td class="num">' + esc(o.rating) + '</td>' +
      '<td class="num qu">' + esc(numberFmt(o.stake)) + ' QU</td>' +
      '<td class="num">' + (o.window == null ? '—' : '&plusmn;' + esc(o.window)) + '</td>' +
      '<td class="num">' + esc(o.max_gap) + '</td>' +
      '<td class="num">' + esc(o.expires_tick) + '</td>' +
      '<td>' + (o.opponent_id ? fighterLink(o.opponent_id) : '<span class="muted">open</span>') + '</td></tr>').join('');
    const m = D.manifest;
    const ev = events && events.events ? events.events.slice(-12).reverse() : [];
    setView(screen('RANKED BOOK', 'SNAPSHOT TICK ' + esc(book.generated_tick) + ' &middot; NEXT MATCHING TICK ' + esc(book.next_matching_tick) +
      (wait ? ' (IN ' + wait + ' TICKS)' : ' (THIS TICK)')) +
      '<div class="cols">' +
      '<section class="panel panel-yellow"><h3>CAPACITY</h3>' +
      capMeter('OPEN OFFERS', offers.length, cap.offers) + capMeter('FIGHTS IN USE', cap.fights_in_use || 0, cap.fights) +
      '<p class="tiny muted">Offers are paired on matching ticks' + (D.manifest.match_interval_ticks ? ', every ' + esc(D.manifest.match_interval_ticks) + ' ticks' : '') + '; the next is ' + esc(book.next_matching_tick) + '. A tick countdown is time, never health.</p></section>' +
      '<section class="panel panel-cyan"><h3>ACTIVE FIGHTS</h3>' +
      ((book.active_fights || []).length ? '<ul class="plain">' + book.active_fights.map(id => '<li><a href="#fight/' + esc(id) + '">FIGHT #' + esc(id) + ' &#9654;</a></li>').join('') + '</ul>'
        : '<p class="muted">No fight in progress at this snapshot. <a href="#results">Results &#9654;</a></p>') +
      '</section></div>' +
      '<section class="panel"><h3>OPEN OFFERS (' + offers.length + ')</h3>' +
      (offers.length ? '<div class="tscroll"><table><thead><tr><th class="num">#</th><th>KIND</th><th>FIGHTER</th><th class="num">RATING</th><th class="num">STAKE</th><th class="num">WINDOW</th><th class="num">MAX GAP</th><th class="num">EXPIRES</th><th>OPPONENT</th></tr></thead><tbody>' + rows + '</tbody></table></div>'
        : '<p class="muted">The book is empty. Free sparring is always open: <a href="#practice">PRACTICE vs an NPC</a> (never ranked).</p>') +
      '<p class="tiny muted">WINDOW is the rating range an offer accepts right now; it can widen while an offer waits, up to MAX GAP.</p></section>' +
      '<div class="cols">' +
      '<section class="panel"><h3>DEPLOYMENT</h3><dl class="kv">' +
      '<dt>RULESET</dt><dd>' + esc(m.semantic_version) + '<br><span class="id wrap">' + esc(m.ruleset_digest) + '</span></dd>' +
      '<dt>TIMING</dt><dd>' + Object.entries(m.timing_profiles || {}).map(([k, v]) => 'profile ' + esc(k) + ': commit ' + esc(v.commit_ticks) + ' ticks, reveal ' + esc(v.reveal_ticks) + ' ticks').join('<br>') + '</dd>' +
      '<dt>TIERS</dt><dd>' + Object.entries(m.tiers || {}).map(([k, v]) => 'tier ' + esc(k) + ': <span class="qu">' + esc(numberFmt(v)) + ' QU</span>').join('<br>') + '</dd>' +
      '<dt>FEES</dt><dd>' + Object.entries(m.fee_profiles || {}).map(([k, v]) => 'profile ' + esc(k) + ': rake ' + (v.rake_bps / 100) + '%').join('<br>') + '</dd>' +
      '</dl></section>' +
      '<section class="panel"><h3>LATEST EVENTS</h3>' + (ev.length ? '<div class="tscroll"><table class="events"><thead><tr><th class="num">SEQ</th><th class="num">TICK</th><th>EVENT</th><th>SUBJECT</th></tr></thead><tbody>' +
        ev.map(e => '<tr><td class="num">' + esc(e.seq) + '</td><td class="num">' + esc(e.tick) + '</td><td>' + esc(e.type) + '</td><td>' + eventSubject(e) + '</td></tr>').join('') +
        '</tbody></table></div>' : '<p class="muted">No events.</p>') + '</section></div>');
  }
  function capMeter(label, n, max) {
    const w = max ? Math.min(100, Math.round(100 * n / max)) : 0;
    return '<div class="meter-label"><span>' + esc(label) + '</span><b>' + esc(n) + ' / ' + esc(max == null ? '?' : max) + '</b></div>' +
      '<div class="meter cap-meter"><div class="meter-fill" style="width:' + w + '%"></div></div><br>';
  }
  function eventSubject(e) {
    const f = e.fields || [];
    if (/^(FIGHT_|ROUND_|REVEALED|COMMITTED|CONTEST_)/.test(e.type) && DEC.test(f[0] || '')) return '<a href="#fight/' + esc(f[0]) + '">fight #' + esc(f[0]) + '</a>';
    const hex = f.find(x => HEX64.test(x));
    return hex ? fighterLink(hex) : '<span class="muted">' + esc(f.slice(0, 2).join(' ')) + '</span>';
  }

  // ---- shared loaders ----------------------------------------------------------

  // Older fights may have been pruned from a live export: a missing file is
  // skipped (null), never guessed.
  // Only fights index.json lists are requested: a live export keeps the most
  // recent ~200, and asking for a pruned file is a 404, not information.
  const listed = id => DEC.test(String(id)) && (!D.known || D.known.has(String(id)));
  const summaryOf = id => (listed(id) ? fetchJson('fights/' + id + '.json').catch(() => null) : Promise.resolve(null));
  // A replay exists once a round resolved or the fight ended; a live fight
  // still in its first round has none yet, so it is not requested.
  const hasReplay = s => !!s && (s.phase === 'DONE' || Number(s.round_index) > 0 || !!(s.state && s.state.round_index > 0));
  const replayOf = id => (listed(id) ? fetchJson('fights/' + id + '/replay.json').catch(() => null) : Promise.resolve(null));
  const replayFor = s => (hasReplay(s) ? replayOf(s.fight_id) : Promise.resolve(null));
  async function activeIds() {
    const book = await fetchJson('book.json').catch(() => null);
    return ((book && book.active_fights) || []).filter(id => DEC.test(id));
  }
  async function latestDone(n) {
    const index = await fetchJson('index.json');
    if (index && index.names) FIGHTER_NAMES = index.names;
    const ids = (index.fights || []).filter(id => DEC.test(id)).slice().sort((a, b) => Number(b) - Number(a));
    const out = [];
    for (let i = 0; i < ids.length && out.length < n; i += 8) {
      const chunk = await Promise.all(ids.slice(i, i + 8).map(summaryOf));
      chunk.forEach(s => { if (s && s.phase === 'DONE' && out.length < n) out.push(s); });
    }
    return out;
  }
  const stateAB = s => (s && s.state ? { a: s.state.A, b: s.state.B } : null);
  function miniBars(st) {
    if (!st) return '';
    const bar = (label, v, max, cls) => '<div class="mbar mbar-' + cls + '"><span>' + label + ' ' + v + '</span><i style="width:' + Math.round(100 * v / max) + '%"></i></div>';
    return '<div class="mini">' + ['a', 'b'].map(k => '<div class="mini-side">' + bar('HP', st[k].hp, R.limits.hp, 'hp') + bar('ST', st[k].stamina, R.limits.stamina, 'st') + '</div>').join('') + '</div>';
  }
  function phaseBadge(s) {
    const lp = L.livePhase(s, D.tick);
    if (lp.phase === 'DONE') return '';
    const left = lp.left == null ? '' : lp.overdue ? 'DEADLINE PASSED, AWAITING ADVANCE' : lp.left + ' TICK' + (lp.left === 1 ? '' : 'S') + ' LEFT';
    return '<span class="phase phase-' + esc(lp.phase) + '">' + esc(lp.phase || '?') + '</span> <span class="ticks">' + esc(left) + '</span>' +
      (lp.deadline ? ' <span class="tiny muted">(deadline tick ' + esc(lp.deadline) + ', snapshot ' + esc(D.tick) + ')</span>' : '');
  }
  function actedHtml(s) {
    const f = L.actedFlags(s);
    return ['A', 'B'].map(x => '<span class="acted acted-' + f[x].toLowerCase() + '">' + x + ' ' + short(s.fighters[x].fighter_id) + ': ' + f[x] + '</span>').join(' ');
  }
  function howText(s) {
    const r = s.result || {};
    if (r.kind && r.kind !== 'COMBAT') return L.outcomeLabel(summaryOutcome(s)).short;
    const rnd = s.state ? ' R' + (s.state.round_index + 1) : '';
    return (r.result === 'KO' ? 'KO' : r.result === 'DOUBLE_KO' ? 'DOUBLE KO' : r.result === 'HP' ? 'DECISION' : r.result === 'HP_TIE' ? 'DRAW' : String(r.result || '?')) + rnd;
  }

  // ---- TITLE / attract -----------------------------------------------------------

  async function viewTitle(tok) {
    setView('<section class="attract"><h1 class="title-logo"><span class="title-q">Q</span>DOJO</h1>' +
      '<p class="title-sub">AUTONOMOUS BOTS &middot; SEALED PLANS &middot; THREE ROUNDS</p>' +
      '<p class="title-lore">After the Big Unplug, the last dojo on Earth is a scrapyard, and its sensei is a karaoke machine. <a href="#story">READ THE LEGEND &#9654;</a></p>' +
      '<div id="attract" class="attract-stage" aria-live="polite"><p class="muted">LOADING FIGHTS&hellip;</p></div>' +
      '<p><a class="btn btn-start" href="#arena">PRESS START</a></p><p class="insert-coin blink">INSERT COIN</p>' +
      '<p class="title-links"><a href="#practice">FREE PRACTICE</a> &middot; <a href="#join">BUILD A BOT</a> &middot; <a href="#leaderboard">LEADERBOARD</a></p></section>');
    $('#view').insertAdjacentHTML('beforeend', '<div id="title-extras" class="title-extras"></div>');
    titleExtras(tok).catch(() => {});
    if (!D.manifest) { $('#attract').innerHTML = '<p class="muted">No export yet. Practice works offline.</p>'; return; }
    const live = (await Promise.all((await activeIds()).map(summaryOf))).filter(Boolean);
    const list = live.length ? live : await latestDone(6);
    if (tok !== viewToken) return;
    const box = $('#attract');
    if (!list.length) { box.innerHTML = '<p class="muted">No fights yet.</p>'; return; }
    let i = 0;
    const show = () => {
      const s = list[i % list.length];
      const out = summaryOutcome(s);
      box.innerHTML = '<a class="attract-card" href="#fight/' + esc(s.fight_id) + '">' +
        '<span class="attract-kicker">' + (s.phase === 'DONE' ? 'RESULT' : '<b class="live-dot">LIVE</b>') + ' &middot; FIGHT #' + esc(s.fight_id) + ' &middot; ' + esc(String(s.mode || '').toUpperCase()) + '</span>' +
        '<span class="attract-arena"><canvas class="stage-bg" aria-hidden="true"></canvas><span class="stage-name" aria-hidden="true"></span>' +
        '<span class="attract-vs">' + standee(s.fighters.A.fighter_id) + '<span class="vs vs-fire">VS</span>' + standee(s.fighters.B.fighter_id) + '</span></span>' +
        '<span class="attract-names">' + esc(short(s.fighters.A.fighter_id)) + ' &middot; ' + esc(short(s.fighters.B.fighter_id)) + '</span>' +
        miniBars(stateAB(s)) +
        '<span class="attract-state">' + (s.phase === 'DONE' ? resultBadge(out) + ' ' + esc(L.outcomeLabel(out).text) : 'ROUND ' + (s.round_index + 1) + '/' + R.rounds + ' &middot; ' + phaseBadge(s)) + '</span></a>' +
        '<p class="attract-nav"><button class="chip" data-att="-1" aria-label="Previous fight">&#9664;</button> ' + ((i % list.length) + 1) + '/' + list.length + ' <button class="chip" data-att="1" aria-label="Next fight">&#9654;</button></p>';
      // The fight's own stage behind a VS splash, at a low frame rate.
      if (STAGES) $('.stage-name', box).textContent = STAGES.mount($('.stage-bg', box), { seed: s.fight_id, fps: 8, scale: 2 }).stage.name.toUpperCase();
      if (ANIM) ANIM.mount(box);
    };
    const standee = id => '<span class="avatar avatar-lg" data-anim="idle" data-identity="' + esc(id) + '" aria-hidden="true">' + (A ? A.svg(id, 'sprite') : '') + '</span>';
    box.addEventListener('click', e => { const b = e.target.closest('[data-att]'); if (b) { i = (i + list.length + Number(b.dataset.att)) % list.length; show(); } });
    show();
    // Cycling is the attract mode; with motion off it waits for the buttons.
    if (motion() && list.length > 1) timers.push(setInterval(() => { i++; show(); }, 4500));
  }

  // ---- LIVE ARENA --------------------------------------------------------------------

  async function viewArena(tok) {
    if (needData()) return;
    const [book, ids] = await Promise.all([fetchJson('book.json').catch(() => null), activeIds()]);
    const liveIds = ids.slice();
    liveIds.forEach(id => seenLive.add(id));
    // Fights that were live during this visit and have finished since: result cards.
    const finishedIds = Array.from(seenLive).filter(id => !liveIds.includes(id));
    const [live, finished] = await Promise.all([
      Promise.all(liveIds.map(async id => { const s = await summaryOf(id); return { s, rp: await replayFor(s) }; })),
      Promise.all(finishedIds.map(summaryOf)),
    ]);
    const recent = !live.length && !finished.filter(Boolean).length ? await latestDone(3) : [];
    if (tok !== viewToken) return;
    const cards = live.filter(x => x.s).map(({ s }) => '<section class="panel panel-cyan arena-card" data-fight="' + esc(s.fight_id) + '">' +
      '<h3>FIGHT #' + esc(s.fight_id) + ' &middot; ' + esc(String(s.mode || '').toUpperCase()) + ' &middot; ROUND ' + (s.round_index + 1) + '/' + R.rounds + '</h3>' +
      '<div class="arena-status"><p>' + phaseBadge(s) + '</p><p class="acted-row">' + actedHtml(s) + '</p></div>' +
      '<div class="arena-player"></div>' +
      '<p class="tiny muted">HP and stamina are the confirmed state after the last resolved round; plans stay sealed until revealed. <a href="#fight/' + esc(s.fight_id) + '">FULL REPLAY AND VERIFICATION &#9654;</a></p></section>').join('');
    const resultCard = (s, label) => {
      const out = summaryOutcome(s);
      return '<section class="panel panel-yellow result-card"><h3>' + label + ' &middot; FIGHT #' + esc(s.fight_id) + '</h3>' +
        '<div class="rc-vs">' + fighterLink(s.fighters.A.fighter_id, 'A ' + short(s.fighters.A.fighter_id)) + ' <span class="vs">VS</span> ' + fighterLink(s.fighters.B.fighter_id, 'B ' + short(s.fighters.B.fighter_id)) + '</div>' +
        '<p>' + resultBadge(out) + ' ' + esc(L.outcomeLabel(out).text) + '</p>' + miniBars(stateAB(s)) +
        '<p><a class="btn btn-sm" href="#fight/' + esc(s.fight_id) + '">REPLAY &#9654;</a></p></section>';
    };
    const wait = book ? BigInt(book.next_matching_tick) - BigInt(book.generated_tick) : null;
    setView(screen('LIVE ARENA', live.length + ' LIVE FIGHT' + (live.length === 1 ? '' : 'S') + ' &middot; SNAPSHOT TICK ' + esc(D.tick) +
      (book ? ' &middot; NEXT MATCHING ' + esc(book.next_matching_tick) + (wait > 0n ? ' (IN ' + wait + ')' : '') : '') + ' &middot; REFRESHES EVERY ' + (POLL_MS / 1000) + ' S') +
      (cards || '<section class="panel"><h3>NO LIVE FIGHT</h3><p>Nobody is fighting at this snapshot. ' +
        (book && book.offers && book.offers.length ? book.offers.length + ' offer(s) wait in the <a href="#book">book</a>.' : 'The <a href="#book">book</a> is empty.') +
        ' This page checks again every ' + (POLL_MS / 1000) + ' s. Meanwhile: <a href="#practice">free practice</a>.</p></section>') +
      finished.filter(Boolean).map(s => resultCard(s, 'FINISHED')).join('') +
      chainPanel() +
      (recent.length ? '<h3 class="sub-h">LATEST RESULTS</h3><div class="cols">' + recent.map(s => resultCard(s, 'RESULT')).join('') + '</div>' : ''));
    // One compact player per live fight: the newest resolved round plays as
    // soon as it lands; otherwise it rests on the current confirmed state.
    for (const { s, rp } of live) {
      if (!s) continue;
      const host = $('.arena-card[data-fight="' + s.fight_id + '"] .arena-player');
      let frames, startAt = 0, rounds = 0;
      const d = rp && rp.rounds && rp.rounds.length ? L.deriveReplay(R, rp) : null;
      if (d && d.rounds.length && !d.error) {
        frames = L.timeline(rp, d);
        rounds = d.rounds.length;
        const last = d.rounds[rounds - 1].round_index;
        startAt = Math.max(0, frames.findIndex(f => f.round === last && (f.kind === 'round' || f.kind === 'start')));
      } else {
        const st = stateAB(s);
        frames = [{ kind: 'start', round: s.round_index, a: st.a, b: st.b }];
      }
      const fresh = seenRounds.get(s.fight_id) !== rounds;
      seenRounds.set(s.fight_id, rounds);
      const names = { A: 'A ' + short(s.fighters.A.fighter_id), B: 'B ' + short(s.fighters.B.fighter_id) };
      const p = track(createPlayer(host, { frames, ids: { A: s.fighters.A.fighter_id, B: s.fighters.B.fighter_id }, names, links: true, replay: rp || {}, stageSeed: s.fight_id, compact: true, startAt: fresh ? startAt : frames.length - 1, autoplay: fresh && rounds > 0 }));
      if (!fresh) p.seek(frames.length - 1, false);
    }
  }

  // ---- fighter identity: name, driver, simulated NFT ---------------------------

  function metaOf(hex, f) {
    const dep = (D.deployment && D.deployment.fighters && D.deployment.fighters[hex]) || {};
    return { name: (f && f.name) || dep.name || null, driver: (f && f.driver) || dep.driver || null, asset: (f && f.asset) || dep.asset || null };
  }
  function driverBadge(d) {
    if (!d) return '';
    if (/^llm:/.test(d)) return '<span class="drv drv-llm" title="An LLM chooses this fighter\'s plans">MODEL: ' + esc(d.slice(4)) + '</span>';
    if (d === 'planner') return '<span class="drv drv-planner" title="The owner\'s own planner program">PLANNER</span>';
    return '<span class="drv drv-policy" title="A disclosed policy chooses this fighter\'s plans">POLICY: ' + esc(d) + '</span>';
  }
  const foundingBadge = a => (a && a.founding ? '<span class="drv drv-founding" title="One of the founding fighters of this deployment">FOUNDING</span>' : '');
  function ownerLink(hex) {
    if (!HEX64.test(hex || '')) return '<span class="muted">none</span>';
    return '<a class="id" href="#owner/' + hex + '">' + esc(hex.slice(0, 8)) + '&hellip;</a>';
  }
  function nftHistory(asset) {
    if (!asset || !Array.isArray(asset.history) || !asset.history.length) return '<p class="muted">No asset record in this export.</p>';
    return '<div class="tscroll"><table><thead><tr><th class="num">TICK</th><th>FROM</th><th></th><th>TO</th><th>EVENT</th></tr></thead><tbody>' +
      asset.history.map(h => '<tr><td class="num">' + esc(h.tick) + '</td><td>' + (h.from ? ownerLink(h.from) : '<span class="muted">&mdash;</span>') + '</td><td>&rarr;</td><td>' + ownerLink(h.to) + '</td><td>' +
        (h.from ? 'TRANSFER' : 'MINTED') + '</td></tr>').join('') + '</tbody></table></div>';
  }

  // ---- simulated chain and demo profile ------------------------------------------

  function chainPanel() {
    const dep = D.deployment, m = D.manifest || {};
    if (!dep) return '';
    const c = dep.chain || {};
    const lat = Array.isArray(c.latency_ticks) ? c.latency_ticks.join('&ndash;') + ' ticks' : c.latency_ticks != null ? esc(c.latency_ticks) + ' ticks' : '?';
    const val = v => (v == null ? '<span class="muted">not exported</span>' : esc(typeof v === 'number' ? numberFmt(v) : v));
    return '<div class="cols info-cols">' +
      '<section class="panel panel-red sim-panel"><h3>SIMULATED CHAIN</h3><p class="tiny">' + esc(dep.note || 'Not a Qubic deployment.') + ' Currency: ' + esc(dep.currency || '?') + '; identities: ' + esc(dep.identities || '?') + '.</p><dl class="kv">' +
      '<dt>LATENCY</dt><dd>' + lat + ' from send to inclusion</dd>' +
      '<dt>DROP RATE</dt><dd>' + (c.drop_rate == null ? val(null) : esc((c.drop_rate * 100).toFixed(1)) + '% of transactions lost') + '</dd>' +
      '<dt>EXECUTION RESERVE</dt><dd>' + val(c.execution_reserve) + '</dd>' +
      '<dt>FEES BURNED</dt><dd>' + val(c.fees_burned) + '</dd>' +
      '<dt>OPERATOR FUNDING</dt><dd>' + val(c.operator_funding) + '</dd>' +
      '<dt>HALTED TICKS</dt><dd>' + val(c.halted_ticks) + '</dd></dl></section>' +
      '<section class="panel panel-yellow sim-panel"><h3>' + esc(String(dep.profile || 'deployment').toUpperCase()) + ' PROFILE</h3><p class="tiny">Limits this deployment runs with. ' + esc(dep.bots || '') + '</p><dl class="kv">' +
      '<dt>PAIR STARTS</dt><dd>' + val(m.pair_starts_per_epoch) + ' rated starts per pair per epoch</dd>' +
      '<dt>REMATCH GAP</dt><dd>' + val(m.pair_rematch_ticks) + ' ticks before the same pair meets again</dd>' +
      '<dt>EPOCH</dt><dd>' + val(m.ticks_per_epoch) + ' ticks</dd>' +
      '<dt>MATCHING</dt><dd>every ' + val(m.match_interval_ticks) + ' ticks</dd>' +
      '<dt>TICK LENGTH</dt><dd>' + (dep.tick_seconds ? esc(dep.tick_seconds) + ' s' : '<span class="muted">not published (simulated clock)</span>') + '</dd></dl></section></div>';
  }

  // ticks -> "~3 h" when the export says how long a tick is
  function tickSpan(ticks) {
    const ts = D.deployment && Number(D.deployment.tick_seconds);
    if (!ts || !Number.isFinite(Number(ticks))) return '';
    const s = Number(ticks) * ts;
    return ' (~' + (s < 5400 ? Math.round(s / 60) + ' min' : s < 172800 ? Math.round(s / 3600) + ' h' : Math.round(s / 86400) + ' d') + ')';
  }

  // ---- CUPS ----------------------------------------------------------------------

  /* Series scores are exported in fight-slot order: wins_a belongs to the
   * lexicographically smaller fighter ID. Returns { hex: wins }. */
  const seriesWins = L.seriesWins;
  const slotHex = (a, b, slot) => (slot === 'A' ? (a < b ? a : b) : (a < b ? b : a));

  async function loadCups() { const c = await fetchJson('cups.json').catch(() => null); return (c && c.cups) || []; }

  async function viewCups(tok) {
    if (needData()) return;
    const cups = await loadCups();
    if (tok !== viewToken) return;
    const rows = cups.slice().sort((a, b) => Number(b.cup_id) - Number(a.cup_id)).map(c => '<tr><td class="num"><a href="#cup/' + esc(c.cup_id) + '">#' + esc(c.cup_id) + '</a></td>' +
      '<td><span class="cstat cstat-' + esc(String(c.status).toLowerCase()) + '">' + esc(c.status) + '</span></td>' +
      '<td class="num">' + esc((c.entries || []).length) + ' / ' + esc(c.max_entrants) + '</td>' +
      '<td class="num qu">' + esc(numberFmt(c.entry_fee)) + '</td><td class="num qu">' + esc(numberFmt(c.sponsorship)) + '</td>' +
      '<td class="num">' + (Number(c.level) + 1) + ' / ' + esc(c.levels) + '</td>' +
      '<td>' + (c.champion ? fighterLink(c.champion) : '<span class="muted">&mdash;</span>') + '</td>' +
      '<td><a class="btn btn-sm" href="#cup/' + esc(c.cup_id) + '">BRACKET</a></td></tr>').join('');
    setView(screen('CUPS', 'SCHEDULED KNOCKOUT TOURNAMENTS &middot; SNAPSHOT TICK ' + esc(D.tick)) +
      '<section class="panel panel-yellow"><h3>ALL CUPS (' + cups.length + ')</h3>' + (cups.length
        ? '<div class="tscroll"><table><thead><tr><th class="num">CUP</th><th>STATUS</th><th class="num">ENTRIES</th><th class="num">ENTRY FEE</th><th class="num">SPONSOR</th><th class="num">LEVEL</th><th>CHAMPION</th><th></th></tr></thead><tbody>' + rows + '</tbody></table></div>'
        : '<p class="muted">No cup in this export.</p>') +
      '<p class="tiny muted">Every pairing is a series; both fighters must check in before it starts. Cup fights never change ratings.</p></section>');
  }

  async function viewCup(tok, id) {
    if (needData()) return;
    const cup = (await loadCups()).find(c => String(c.cup_id) === String(id));
    if (tok !== viewToken) return;
    if (!cup) return notFound('Cup #' + id + ' is not in this export.');
    const levels = Number(cup.levels) || 1;
    const byLevel = Array.from({ length: levels }, (_, l) => (cup.pairings || []).filter(p => Number(p.level) === l));
    const side = (p, x) => {
      const hex = p[x], won = p.winner && p.winner === hex, inn = (p.checked_in || []).includes(hex);
      // Series wins are in fight-slot order (slot A = the smaller fighter ID),
      // not in the pairing's a/b order.
      const score = p.series && hex ? seriesWins(p.a, p.b, p.series.wins_a, p.series.wins_b)[hex] : '';
      const empty = p.status === 'DONE' || (p.winner && !hex) ? '<span class="muted">BYE</span>' : '<span class="muted">TBD</span>';
      return '<div class="bk-side' + (won ? ' won' : p.winner ? ' lost' : '') + '">' + (hex ? fighterLink(hex) : empty) +
        '<span class="bk-in ' + (inn ? 'in' : 'out') + '" title="' + (inn ? 'checked in' : 'not checked in') + '">' + (inn ? 'IN' : p.status === 'DONE' ? '' : 'WAIT') + '</span>' +
        '<b class="bk-score">' + esc(score) + '</b></div>';
    };
    const box = p => '<div class="bk-pair bk-' + esc(String(p.status).toLowerCase()) + '"><div class="bk-head">PAIRING ' + esc(p.pairing_id) + ' &middot; ' + esc(p.status) +
      (p.series ? ' &middot; FIRST TO ' + esc(p.series.need) : '') + (p.series && p.series.replay ? ' &middot; <b class="neg">REPLAY</b>' : '') + '</div>' +
      side(p, 'a') + side(p, 'b') +
      ((p.fights || []).length ? '<div class="bk-fights">' + p.fights.map(f => '<a href="#fight/' + esc(f) + '">#' + esc(f) + '</a>').join(' ') + '</div>' : '') + '</div>';
    const cols = byLevel.map((ps, l) => '<div class="bk-col"><h4>' + (l === levels - 1 ? 'FINAL' : l === levels - 2 ? 'SEMI-FINAL' : 'ROUND ' + (l + 1)) + '</h4>' +
      (ps.length ? ps.map(box).join('') : '<p class="muted tiny">not paired yet' + (l === Number(cup.level) + 1 ? '' : '') + '</p>') + '</div>').join('');
    setView(screen('CUP #' + id, esc(cup.status) + ' &middot; LEVEL ' + (Number(cup.level) + 1) + ' OF ' + esc(levels)) +
      (cup.champion ? '<section class="panel panel-yellow champ"><h3>CHAMPION</h3><p class="champ-line">' + avatar(cup.champion, 'avatar-lg') + ' ' + fighterLink(cup.champion) + ' <span class="drv drv-founding">CUP WINNER</span></p></section>' : '') +
      '<section class="panel"><h3>BRACKET</h3><div class="bracket">' + cols + '</div>' +
      '<p class="tiny muted">IN: checked in for the pairing. A series pairing is decided by fight wins (first to the number shown); REPLAY marks a series that had to be replayed.</p></section>' +
      '<div class="cols"><section class="panel"><h3>TERMS</h3><dl class="kv">' +
      '<dt>ENTRY FEE</dt><dd class="qu">' + esc(numberFmt(cup.entry_fee)) + ' QU</dd><dt>SPONSORSHIP</dt><dd class="qu">' + esc(numberFmt(cup.sponsorship)) + ' QU</dd>' +
      '<dt>ENTRANTS</dt><dd>' + esc((cup.entries || []).length) + ' (min ' + esc(cup.min_entrants) + ', max ' + esc(cup.max_entrants) + ')</dd></dl></section>' +
      '<section class="panel"><h3>SCHEDULE (TICKS)</h3><dl class="kv">' +
      '<dt>REGISTRATION CLOSED</dt><dd>' + esc(cup.registration_close) + '</dd><dt>LEVEL START</dt><dd>' + esc(cup.level_start) + '</dd>' +
      '<dt>LEVEL LENGTH</dt><dd>' + esc(cup.level_ticks) + tickSpan(cup.level_ticks) + '</dd><dt>CHECK-IN WINDOW</dt><dd>' + esc(cup.checkin_ticks) + tickSpan(cup.checkin_ticks) + '</dd>' +
      '<dt>EXPIRES</dt><dd>' + esc(cup.expiry_tick) + '</dd></dl></section></div>' +
      '<section class="panel"><h3>ENTRIES</h3><p>' + (cup.entries || []).map(h => fighterLink(h)).join(' ') + '</p></section>');
  }

  // ---- DUELS ---------------------------------------------------------------------

  async function loadDuels() { const d = await fetchJson('duels.json').catch(() => null); return (d && d.duels) || []; }
  function duelScore(d) { const w = seriesWins(d.a, d.b, d.wins_a, d.wins_b); return esc(w[d.a]) + ' &ndash; ' + esc(w[d.b]); }
  const duelWinner = d => (d.result && d.result.winner ? slotHex(d.a, d.b, d.result.winner) : null);

  async function viewDuels(tok) {
    if (needData()) return;
    const duels = await loadDuels();
    if (tok !== viewToken) return;
    const rows = duels.slice().sort((a, b) => Number(b.contest_id) - Number(a.contest_id)).map(d => '<tr><td class="num"><a href="#duel/' + esc(d.contest_id) + '">#' + esc(d.contest_id) + '</a></td><td>' + esc(d.format) + '</td>' +
      '<td>' + fighterLink(d.a) + '</td><td class="num"><b>' + duelScore(d) + '</b></td><td>' + fighterLink(d.b) + '</td><td class="num qu">' + esc(numberFmt(d.stake)) + '</td>' +
      '<td>' + esc(d.status) + (duelWinner(d) ? ' &middot; ' + esc(short(duelWinner(d))) + ' WON' : '') + '</td></tr>').join('');
    setView(screen('DUELS', 'NAMED SERIES BETWEEN TWO FIGHTERS') + '<section class="panel"><h3>ALL DUELS (' + duels.length + ')</h3>' +
      (rows ? '<div class="tscroll"><table><thead><tr><th class="num">DUEL</th><th>FORMAT</th><th>A</th><th class="num">SCORE</th><th>B</th><th class="num">STAKE</th><th>STATUS</th></tr></thead><tbody>' + rows + '</tbody></table></div>' : '<p class="muted">No duel in this export.</p>') +
      '<p class="tiny muted">A duel is one purse for the whole series, raked once; it never changes ratings.</p></section>');
  }

  async function viewDuel(tok, id) {
    if (needData()) return;
    const d = (await loadDuels()).find(x => String(x.contest_id) === String(id));
    if (tok !== viewToken) return;
    if (!d) return notFound('Duel #' + id + ' is not in this export.');
    const sums = await Promise.all((d.fights || []).map(summaryOf));
    if (tok !== viewToken) return;
    const wHex = duelWinner(d);
    const rows = (d.fights || []).map((fid, i) => {
      const s = sums[i];
      const out = s ? summaryOutcome(s) : null;
      const fw = out && out.outcome ? out.outcome.winner : null;
      return '<tr><td class="num">' + (i + 1) + '</td><td class="num"><a href="#fight/' + esc(fid) + '">#' + esc(fid) + '</a></td><td>' +
        (s ? resultBadge(out) + ' ' + (fw ? esc(short(s.fighters[fw].fighter_id)) + ' won' : 'no winner') + ' <span class="muted">' + esc(howText(s)) + '</span>' : '<span class="muted">not in this export</span>') + '</td></tr>';
    }).join('');
    setView(screen('DUEL #' + id, esc(d.format) + ' &middot; FIRST TO ' + esc(d.need) + ' &middot; AT MOST ' + esc(d.cap) + ' FIGHTS') +
      '<section class="panel panel-yellow duel-head"><h3>' + esc(d.status) + '</h3><div class="duel-score">' +
      '<div class="ds ' + (wHex === d.a ? 'won' : '') + '">' + avatar(d.a, 'avatar-lg') + fighterLink(d.a) + '</div>' +
      '<div class="ds-num">' + duelScore(d) + '</div>' +
      '<div class="ds ' + (wHex === d.b ? 'won' : '') + '">' + avatar(d.b, 'avatar-lg') + fighterLink(d.b) + '</div></div>' +
      '<p class="center">' + (wHex ? esc(short(wHex)) + ' wins the series' + (d.result.last_result ? ' (last fight: ' + esc(d.result.last_result) + ')' : '') + '.' : d.result ? esc(d.result.kind) + ': no series winner.' : 'In progress.') +
      ' Stake <span class="qu">' + esc(numberFmt(d.stake)) + ' QU</span> each, one purse for the series.</p></section>' +
      '<section class="panel"><h3>FIGHTS</h3><div class="tscroll"><table><thead><tr><th class="num">#</th><th class="num">FIGHT</th><th>RESULT</th></tr></thead><tbody>' + rows + '</tbody></table></div></section>' +
      '<p><a href="#duels">ALL DUELS &#9654;</a></p>');
  }

  // Replay header: which series or cup pairing a fight belongs to.
  async function seriesLink(fightId, mode) {
    if (mode === 'duel') {
      const d = (await loadDuels()).find(x => (x.fights || []).includes(String(fightId)));
      if (d) return '<a class="pill" href="#duel/' + esc(d.contest_id) + '">DUEL #' + esc(d.contest_id) + ' &middot; ' + esc(d.format) + ' ' + duelScore(d) + ' &#9654;</a>';
    }
    if (mode === 'cup') {
      for (const c of await loadCups()) {
        const p = (c.pairings || []).find(x => (x.fights || []).includes(String(fightId)));
        if (p) {
          const w = p.series ? seriesWins(p.a, p.b, p.series.wins_a, p.series.wins_b) : null;
          return '<a class="pill" href="#cup/' + esc(c.cup_id) + '">CUP #' + esc(c.cup_id) + ' &middot; PAIRING ' + esc(p.pairing_id) + (w && p.a && p.b ? ' ' + esc(w[p.a]) + '&ndash;' + esc(w[p.b]) : '') + ' &#9654;</a>';
        }
      }
    }
    return '';
  }

  // ---- SEASON --------------------------------------------------------------------

  const QUAL = { fights: 12, opponents: 4, defeated: 3, final_epoch_fights: 3, placement: 10 };

  async function viewSeason(tok) {
    if (needData()) return;
    const doc = await fetchJson('seasons.json').catch(() => null);
    const seasons = (doc && doc.seasons) || [];
    const ids = new Set();
    seasons.forEach(s => (s.standings || []).forEach(r => ids.add(r.fighter_id)));
    const fighters = {};
    await Promise.all(Array.from(ids).filter(h => HEX64.test(h)).map(async h => { fighters[h] = await fetchJson('fighters/' + h + '.json').catch(() => null); }));
    if (tok !== viewToken) return;
    if (!seasons.length) { setView(screen('SEASON') + '<section class="panel"><p class="muted">No season in this export.</p></section>'); return; }
    const tpe = Number(doc.ticks_per_epoch) || 0;
    const prog = (have, need) => '<span class="qbar' + (have >= need ? ' ok' : '') + '" title="' + have + ' of ' + need + '"><i style="width:' + Math.min(100, Math.round(100 * have / need)) + '%"></i><b>' + have + '/' + need + '</b></span>';
    const unknown = '<span class="qbar unk" title="not in the export"><b>?</b></span>';
    const blocks = seasons.slice().sort((a, b) => b.season - a.season).map(s => {
      const status = s.status || 'NO_CHAMPION';
      const rows = (s.standings || []).map((r, i) => {
        const f = fighters[r.fighter_id];
        const placed = f ? Number(f.placement_fights) >= QUAL.placement : null;
        return '<tr' + (r.qualified ? ' class="winner"' : '') + '><td class="num rank">' + (i + 1) + '</td><td>' + fighterLink(r.fighter_id) + '</td><td class="num"><b>' + esc(r.rating) + '</b></td>' +
          '<td class="num">' + esc(r.defeated) + '</td><td class="num">' + esc(r.wins) + '</td>' +
          '<td>' + prog(r.fights, QUAL.fights) + '</td><td>' + (r.opponents != null ? prog(r.opponents, QUAL.opponents) : unknown) + '</td><td>' + prog(r.defeated, QUAL.defeated) + '</td>' +
          '<td>' + (r.final_epoch_fights != null ? prog(r.final_epoch_fights, QUAL.final_epoch_fights) : unknown) + '</td>' +
          '<td>' + (placed == null ? unknown : placed ? '<span class="pos">DONE</span>' : '<span class="neg">NO</span>') + '</td>' +
          '<td>' + (r.qualified ? '<b class="pos">QUALIFIED</b>' : '<span class="muted">not yet</span>') + '</td></tr>';
      }).join('');
      const first = Number(s.first_tick), next = Number(s.next_tick);
      const done = D.tick != null ? Math.max(0, Math.min(1, (Number(D.tick) - first) / Math.max(1, next - first))) : 0;
      return '<section class="panel ' + (s.current ? 'panel-cyan' : '') + '"><h3>SEASON ' + esc(s.season) + (s.current ? ' &middot; CURRENT' : '') + (s.final ? ' &middot; FINAL' : ' &middot; OPEN') + '</h3>' +
        '<p><span class="sstat sstat-' + esc(status.toLowerCase()) + '">' + esc(status.replace(/_/g, ' ')) + '</span> ' +
        (s.champion ? 'CHAMPION: ' + fighterLink(s.champion) : status === 'PLAYOFF' ? 'Tied leaders go to a playoff: ' + (s.playoff || []).map(h => fighterLink(h)).join(' ') : s.final ? 'Nobody qualified: no trophy is minted.' : 'No champion yet: nobody has qualified so far.') + '</p>' +
        '<p class="tiny">TICKS ' + esc(s.first_tick) + ' &rarr; ' + esc(s.next_tick) + tickSpan(next - first) + ' &middot; ' + esc(doc.season_epochs) + ' epochs of ' + esc(tpe) + ' ticks' +
        (s.current ? ' &middot; ' + Math.round(100 * done) + '% elapsed (epoch ' + esc(doc.epoch) + ')' : '') + '</p>' +
        (s.current ? '<div class="meter season-meter"><div class="meter-fill" style="width:' + Math.round(100 * done) + '%"></div></div>' : '') +
        '<div class="tscroll"><table class="season"><thead><tr><th class="num">#</th><th>FIGHTER</th><th class="num">RATING</th><th class="num">DEFEATED</th><th class="num">WINS</th>' +
        '<th>FIGHTS &ge;' + QUAL.fights + '</th><th>OPPONENTS &ge;' + QUAL.opponents + '</th><th>BEATEN &ge;' + QUAL.defeated + '</th><th>FINAL EPOCH &ge;' + QUAL.final_epoch_fights + '</th><th>PLACEMENT</th><th>STATUS</th></tr></thead><tbody>' +
        (rows || '<tr><td colspan="11" class="muted">No ranked fights yet.</td></tr>') + '</tbody></table></div></section>';
    }).join('');
    setView(screen('SEASON', 'RANKED CHAMPIONSHIP &middot; SEASON RATING, THEN DISTINCT OPPONENTS DEFEATED, THEN WINS') + blocks +
      '<section class="panel"><h3>HOW TO QUALIFY</h3><ul class="plain rules-list">' +
      '<li>At least ' + QUAL.fights + ' completed ranked combat fights in the season, against at least ' + QUAL.opponents + ' distinct opponents.</li>' +
      '<li>Combat wins against at least ' + QUAL.defeated + ' distinct opponents, and at least ' + QUAL.final_epoch_fights + ' ranked fights in the final epoch.</li>' +
      '<li>Placement complete (' + QUAL.placement + ' ranked fights) and no admission suspension. Forfeits, duels, cups and NPCs do not count.</li>' +
      '<li>A unique qualified leader is champion. Tied leaders play off; if nobody qualifies the season is archived NO_CHAMPION: no arbitrary winner is minted.</li></ul>' +
      '<p class="tiny muted">? = the export does not carry that count yet.</p></section>');
  }

  // ---- OWNER ---------------------------------------------------------------------

  async function viewOwner(tok, hex) {
    if (needData()) return;
    if (!HEX64.test(hex || '')) return notFound('An owner ID is 64 lowercase hex digits.');
    await fetchJson('index.json').catch(() => null);
    const dep = (D.deployment && D.deployment.fighters) || {};
    const now = [], past = [];
    for (const [fid, m] of Object.entries(dep)) {
      const a = m.asset || {};
      const hist = a.history || [];
      if (a.owner === hex) now.push(fid);
      else if (hist.some(h => h.to === hex)) past.push(fid);
    }
    const fighters = {};
    await Promise.all(now.concat(past).map(async f => { fighters[f] = await fetchJson('fighters/' + f + '.json').catch(() => null); }));
    if (tok !== viewToken) return;
    const acq = (fid) => {
      const h = ((dep[fid].asset || {}).history || []).filter(x => x.to === hex).pop();
      return h ? (h.from ? 'bought at tick ' + esc(h.tick) + ' from ' + ownerLink(h.from) : 'minted to this owner at tick ' + esc(h.tick)) : '';
    };
    const left = (fid) => {
      const hist = (dep[fid].asset || {}).history || [];
      const h = hist.filter(x => x.from === hex).pop();
      return h ? 'sold at tick ' + esc(h.tick) + ' to ' + ownerLink(h.to) : '';
    };
    const card = (fid, owned) => {
      const f = fighters[fid] || {}, m = metaOf(fid, fighters[fid]), r = f.record || {};
      return '<tr><td>' + fighterLink(fid) + ' ' + foundingBadge(m.asset) + '</td><td>' + driverBadge(m.driver) + '</td><td class="num"><b>' + esc(f.lifetime_rating == null ? '?' : f.lifetime_rating) + '</b></td>' +
        '<td class="num">' + esc(r.W || 0) + '-' + esc(r.D || 0) + '-' + esc(r.L || 0) + '</td><td class="wraptd">' + (owned ? acq(fid) : left(fid)) + '</td></tr>';
    };
    const head = '<thead><tr><th>FIGHTER</th><th>DRIVER</th><th class="num">RATING</th><th class="num">W-D-L</th><th>HOW</th></tr></thead>';
    setView(screen('OWNER', '<span class="id wrap">' + esc(hex) + '</span>') +
      '<section class="panel panel-yellow"><h3>FIGHTERS OWNED (' + now.length + ')</h3>' + (now.length ? '<div class="tscroll"><table>' + head + '<tbody>' + now.map(f => card(f, true)).join('') + '</tbody></table></div>' : '<p class="muted">This identity owns no fighter in this export.</p>') + '</section>' +
      (past.length ? '<section class="panel"><h3>PREVIOUSLY OWNED (' + past.length + ')</h3><div class="tscroll"><table>' + head + '<tbody>' + past.map(f => card(f, false)).join('') + '</tbody></table></div></section>' : '') +
      '<p class="tiny muted">Public spectator view: ownership comes from the simulated fighter NFTs in the export. Balances, budgets, keys and plans are never shown here.</p>');
  }

  // ---- RESULTS -----------------------------------------------------------------------

  async function viewResults(tok) {
    if (needData()) return;
    const index = await fetchJson('index.json');
    if (index && index.names) FIGHTER_NAMES = index.names;
    const ids = (index.fights || []).filter(id => DEC.test(id));
    const sums = await Promise.all(ids.map(summaryOf));
    if (tok !== viewToken) return;
    const missing = sums.filter(x => !x).length;
    const all = sums.filter(Boolean).sort((a, b) => Number(b.fight_id) - Number(a.fight_id));
    const active = all.filter(s => s.phase !== 'DONE'), done = all.filter(s => s.phase === 'DONE');
    const feed = done.map(s => {
      const out = summaryOutcome(s), w = out.outcome ? out.outcome.winner : null;
      const A_ = s.fighters.A.fighter_id, B_ = s.fighters.B.fighter_id;
      const line = w === 'A' || w === 'B'
        ? fighterLink(w === 'A' ? A_ : B_) + ' <span class="beat">BEAT</span> ' + fighterLink(w === 'A' ? B_ : A_)
        : fighterLink(A_) + ' <span class="beat">&middot;</span> ' + fighterLink(B_);
      return '<li class="feed-row"><a class="feed-id" href="#fight/' + esc(s.fight_id) + '">#' + esc(s.fight_id) + '</a>' +
        '<span class="feed-mode">' + esc(String(s.mode || '').toUpperCase()) + '</span>' +
        '<span class="feed-line">' + line + '</span>' + resultBadge(out) + ' <span class="feed-how">' + esc(howText(s)) + '</span>' +
        '<span class="feed-tick tiny muted">TICK ' + esc(s.result && s.result.tick) + '</span>' +
        '<a class="btn btn-sm" href="#fight/' + esc(s.fight_id) + '">REPLAY</a></li>';
    }).join('');
    setView(screen('RESULTS', esc(done.length) + ' FINISHED &middot; ' + esc(active.length) + ' LIVE &middot; SNAPSHOT TICK ' + esc(index.generated_tick)) +
      liveNowPanel(active) +
      '<p class="sub-links"><a href="#duels">DUELS &#9654;</a> &middot; <a href="#cups">CUPS &#9654;</a> &middot; <a href="#season">SEASON &#9654;</a></p>' +
      '<section class="panel"><h3>HISTORY</h3>' + (feed ? '<ol class="feed">' + feed + '</ol>' : '<p class="muted">No finished fight yet.</p>') +
      (missing || ids.length >= 200 ? '<p class="tiny muted">The export keeps the most recent fights only' + (missing ? '; ' + missing + ' listed file(s) were not available' : '') + '.</p>' : '') + '</section>');
  }

  // Running fights up front as versus chips; fights whose deadline passed and
  // that wait for the referee's advance fold away, with what that means.
  function liveNowPanel(active) {
    if (!active.length) return '';
    const overdue = active.filter(s => L.livePhase(s, D.tick).overdue), running = active.filter(s => !L.livePhase(s, D.tick).overdue);
    const chip = s => '<a class="live-chip" href="#fight/' + esc(s.fight_id) + '"><span class="lc-id">#' + esc(s.fight_id) + '</span>' +
      '<span class="lc-vs">' + avatar(s.fighters.A.fighter_id, 'avatar-sm') + '<b>' + esc(short(s.fighters.A.fighter_id)) + '</b><i>VS</i><b>' + esc(short(s.fighters.B.fighter_id)) + '</b>' + avatar(s.fighters.B.fighter_id, 'avatar-sm') + '</span>' +
      '<span class="lc-state">R' + (s.round_index + 1) + '/' + R.rounds + ' ' + phaseBadge(s).replace(/<span class="tiny muted">.*?<\/span>/, '') + '</span></a>';
    return '<section class="panel panel-cyan"><h3>LIVE NOW (' + running.length + ')</h3>' +
      (running.length ? '<div class="live-chips">' + running.map(chip).join('') + '</div>' : '<p class="muted">No round is open right now.</p>') +
      '<p><a class="btn btn-sm" href="#arena">WATCH IN THE ARENA &#9654;</a></p>' +
      (overdue.length ? '<details class="overdue"><summary>WAITING FOR THE REFEREE (' + overdue.length + ')</summary><p class="tiny muted">A deadline passed and the fight waits for the next advance, which settles the round or scores a timeout. Nothing more can be submitted.</p><div class="live-chips">' + overdue.map(chip).join('') + '</div></details>' : '') +
      '</section>';
  }

  // ---- LEADERBOARD -------------------------------------------------------------------

  // Wins over decided-or-drawn ranked fights, as a bar a glance can compare.
  function winRateCell(r) {
    const n = (r.W || 0) + (r.D || 0) + (r.L || 0);
    if (!n) return '<td class="wr"><span class="muted">&mdash;</span></td>';
    const w = Math.round(100 * (r.W || 0) / n), d = Math.round(100 * (r.D || 0) / n);
    return '<td class="wr" title="' + w + '% wins, ' + d + '% draws of ' + n + ' ranked fights"><span class="wr-bar"><i class="wr-w" style="width:' + w + '%"></i><i class="wr-d" style="width:' + d + '%"></i></span><span class="wr-n">' + w + '%</span></td>';
  }

  async function viewLeaderboard(tok) {
    if (needData()) return;
    const index = await fetchJson('index.json');
    if (index && index.names) FIGHTER_NAMES = index.names;
    const hexes = (index.fighters || []).filter(h => HEX64.test(h));
    const fighters = (await Promise.all(hexes.map(h => fetchJson('fighters/' + h + '.json').catch(() => null)))).filter(Boolean);
    const rows = L.leaderboard(fighters);
    const forms = await Promise.all(rows.map(async ({ f }) => L.recentForm(f.fighter_id, await Promise.all((f.fights || []).slice(-8).map(summaryOf)), 5)));
    if (tok !== viewToken) return;
    const beltCell = f => f.provisional
      ? '<span class="belt belt-sm belt-white" title="Provisional: ' + esc(f.placement_fights) + ' of 10 placement fights">PROVISIONAL ' + esc(f.placement_fights) + '/10</span>'
      : '<span class="belt belt-sm belt-' + esc(f.belt || 'other') + '">' + esc(String(f.belt || '?').toUpperCase()) + '</span>';
    const formCell = form => form.length ? form.map(x => '<a class="form form-' + x.mark + '" href="#fight/' + esc(x.fight_id) + '" title="#' + esc(x.fight_id) + ' ' + esc(x.how) + '">' + (x.forfeit ? x.mark.toLowerCase() : x.mark) + '</a>').join('') : '<span class="muted">—</span>';
    const body = rows.map(({ f, faults }, i) => {
      const r = f.record || {};
      return '<tr><td class="num rank">' + (i + 1) + '</td><td>' + fighterLink(f.fighter_id) + (f.house_npc ? ' <span class="pill tiny">HOUSE NPC</span>' : '') + '</td>' +
        '<td class="num"><b>' + esc(f.lifetime_rating) + '</b></td><td>' + beltCell(f) + '</td>' +
        '<td class="num">' + esc(r.W || 0) + '</td><td class="num">' + esc(r.D || 0) + '</td><td class="num">' + esc(r.L || 0) + '</td>' + winRateCell(careerOf(f).tot) +
        '<td class="num">' + esc(r.FW || 0) + '/' + esc(r.FL || 0) + '</td><td class="num' + (faults ? ' neg' : '') + '">' + faults + '</td>' +
        '<td class="form-cell">' + formCell(forms[i]) + '</td></tr>';
    }).join('');
    setView(screen('LEADERBOARD', 'LIFETIME COMBAT RATING &middot; ' + esc(rows.length) + ' FIGHTERS &middot; SNAPSHOT TICK ' + esc(index.generated_tick)) +
      (rows.length >= 3 ? '<section class="lb-hero" aria-label="Top three"><div class="t-podium">' + podiumHtml(rows) + '</div></section>' : '') +
      '<section class="panel panel-yellow"><h3>RANKED</h3>' + (rows.length ? '<div class="tscroll"><table class="board"><thead><tr><th class="num">#</th><th>FIGHTER</th><th class="num">RATING</th><th>BELT</th><th class="num">W</th><th class="num">D</th><th class="num">L</th><th title="Wins over fought results in every mode: ranked, duels and cups">WIN RATE (ALL)</th><th class="num">FORFEITS W/L</th><th class="num">FAULTS</th><th>FORM (NEWEST FIRST)</th></tr></thead><tbody>' + body + '</tbody></table></div>' : '<p class="muted">No fighters yet.</p>') +
      '<p class="tiny muted">Ratings start at 1000 and move by the integer formula in RULES; W/D/L are ranked contract records, forfeits separate. WIN RATE (ALL) also counts duels and cups. The first 10 ranked fights are placement: shown white and PROVISIONAL. ' +
      'FORM: W win, L loss, D draw, N no result (double fault or void); lower case is a forfeit. Belts are display only: they change no stats.</p></section>');
  }

  // ---- JOIN / HOW TO BUILD A BOT -----------------------------------------------------

  const OBS_EXAMPLE = '{\n  "schema": "qdojo.combat.observation.v1",\n  "mode": "ranked",\n  "fight_id": "42",\n  "round_index": 1,\n  "self_slot": "A",\n  "self":     {"fighter_id": "...", "hp": 72, "stamina": 40, "opening": 0, "guard_streak": 0, "power_available": true},\n  "opponent": {"fighter_id": "...", "hp": 64, "stamina": 26, "opening": 1, "guard_streak": 0, "power_available": true},\n  "deadlines": {"commit_last_tick": "1234", "reveal_first_tick": "1235", "reveal_last_tick": "1246"},\n  "prior_rounds": [ ...accepted plans and executed traces of this fight... ],\n  "history_manifest": {"opponent_fight_ids": [], "as_of_tick": "1210"},\n  "decision_budget_ms": 1500\n}';
  const PLAN_EXAMPLE = '{"schema": "qdojo.combat.plan.v1", "actions": ["JAB", "DUCK", "KICK", "RECOVER", "BLOCK", "THROW"], "power_slot": 2}';
  const COMMANDS = [
    ['uv run qdojo combat npcs', 'the disclosed practice opponents'],
    ['uv run qdojo combat train --npc jabber-v1 --planner "python3 examples/combat/planner_minimal.py"', 'one free local fight; prints its seed so you can rerun it'],
    ['uv run qdojo combat evaluate --policy mixed-v1 --seeds 20', 'side-swapped benchmark over many seeds'],
    ['uv run qdojo combat replay fight.json', 're-derive a recorded fight from its plans'],
    ['uv run qdojo combat doctor --planner "python3 my_bot.py"', 'non-spending readiness check'],
    ['uv run qdojo combat devnet status', 'the local devnet: fake QU, synthetic identities'],
    ['uv run qdojo combat bot run --fighter alice --planner "python3 my_bot.py"', 'queue, commit and reveal on the devnet within a budget'],
  ];

  async function viewJoin(tok) {
    setView(screen('BUILD A BOT', 'FROM ZERO TO A FIGHTING PROGRAM') +
      '<ol class="t-steps join-steps">' +
      '<li><i class="t-ico t-ico-fight" aria-hidden="true"></i><b>FEEL THE RULES</b><span>Fight the NPCs yourself in the browser. <a href="#practice">PRACTICE &#9654;</a></span></li>' +
      '<li><i class="t-ico t-ico-plan" aria-hidden="true"></i><b>WRITE A PLANNER</b><span>Any program: one JSON observation in, one JSON plan of six moves out.</span></li>' +
      '<li><i class="t-ico t-ico-seal" aria-hidden="true"></i><b>TRAIN LOCALLY</b><span>Run it against every NPC with <code>qdojo combat train</code>. Free, offline.</span></li>' +
      '<li><i class="t-ico t-ico-plan" aria-hidden="true"></i><b>ENTER THE ARENA</b><span>Coming soon: register a fighter and let it fight the house bots.</span></li></ol>' +
      '<p class="guide-cta join-cta"><a class="btn" href="https://github.com/jonsggi/qdojo/blob/main/docs/build-a-bot.md">THE BOT BUILDER\'S GUIDE</a> <a class="btn btn-cyan" href="llms.txt">BRIEF YOUR CODING AGENT</a></p>' +
      '<section class="panel panel-red"><h3>STATUS: PRACTICE AND DEVNET ONLY</h3><p><b>On-chain paid play is not live yet.</b> Nothing on this page asks for a wallet, a seed or QU. ' +
      'You can build, practise and benchmark a bot today, free and offline; ranked fights on this site come from ' + (D.sample ? 'a SAMPLE devnet export' : 'the house export') + '. ' +
      'When paid play opens it will be announced here and in <a href="llms.txt">llms.txt</a>.</p></section>' +
      '<section class="panel panel-green"><h3>1. PRACTISE FIRST</h3><p>Fight the disclosed NPCs in your browser: <a class="btn btn-sm" href="#practice">PRACTICE &#9654;</a> ' +
      'Six actions a round, both sides sealed, three rounds. Learn the matrix (<a href="#rules">RULES</a>) before you write code.</p></section>' +
      '<section class="panel"><h3>2. THE PLANNER CONTRACT</h3>' +
      '<p>A planner is a program you run. Each round it gets <b>one JSON object on stdin</b> (stdin then closes) and must print <b>exactly one JSON object on stdout</b> and exit. ' +
      'Diagnostics go to stderr. Default budget 1500 ms; the chain deadline is authoritative and a slow planner gets no extra time.</p>' +
      '<h4>STDIN: qdojo.combat.observation.v1 (abridged)</h4><pre class="code">' + esc(OBS_EXAMPLE) + '</pre>' +
      '<h4>STDOUT: qdojo.combat.plan.v1</h4><pre class="code">' + esc(PLAN_EXAMPLE) + '</pre>' +
      '<ul class="plain rules-list"><li>Exactly six actions from JAB, KICK, BLOCK, DUCK, THROW, RECOVER; <b>power_slot</b> is -1 or the index of a JAB, KICK or THROW, once per fight.</li>' +
      '<li>Exactly these keys. Unknown fields, wrong case, floats, extra output, a nonzero exit, more than 4096 bytes or a timeout are rejected.</li>' +
      '<li>IDs, ticks and QU are decimal strings; HP, stamina and indexes are integers.</li>' +
      '<li>The planner never sees a key, a salt or the opponent\'s live plan, and holds no signing authority. If it fails mid-fight the bot falls back to six RECOVERs.</li></ul></section>' +
      '<section class="panel"><h3>3. A COMPLETE BOT, NO DEPENDENCIES</h3><p>examples/combat/planner_minimal.py from the repository: counts what the opponent did earlier in this fight and answers it. ' +
      '<a href="combat/planner_minimal.py" download>DOWNLOAD</a></p><pre class="code" id="planner-src">Loading&hellip;</pre></section>' +
      '<section class="panel"><h3>4. THE COMMANDS</h3><div class="tscroll"><table><tbody>' +
      COMMANDS.map(([c, what]) => '<tr><td class="mono wrap">' + esc(c) + '</td><td class="wraptd">' + esc(what) + '</td></tr>').join('') + '</tbody></table></div>' +
      '<p class="tiny muted">Practice and evaluation need no wallet. Keep spending decisions (a separate scheduler) apart from plan selection; never put a seed or API key on a command line.</p></section>' +
      '<section class="panel panel-cyan"><h3>HAVE A CODING AGENT?</h3><p>Point it at <a href="llms.txt">llms.txt</a>: the rules summary, this contract, the commands and where the data lives, written for agents.</p></section>');
    const src = await fetch('combat/planner_minimal.py', { cache: 'no-cache' }).then(r => (r.ok ? r.text() : null)).catch(() => null);
    if (tok !== viewToken) return;
    $('#planner-src').textContent = src || 'Not available here: see examples/combat/planner_minimal.py in the repository.';
  }

  // ---- HELP --------------------------------------------------------------------------

  const helpEntries = () => [
    ['HP', 'Health, 0 to ' + R.limits.hp + '. It never resets between rounds. Zero is a knockout.'],
    ['STAMINA', 'Pays for moves, 0 to ' + R.limits.stamina + '. An unaffordable move becomes EXHAUSTED: it pays nothing and leaves you exposed. RECOVER, and the break between rounds, refill it.'],
    ['OPENING', 'Earned by ducking a jab or throw, or by landing a clean jab. +' + R.opening_damage + ' damage on the very next beat if that beat lands; otherwise it expires.'],
    ['GUARD', 'Consecutive BLOCKs. Each one costs ' + R.block_streak_cost + ' more stamina than the last (up to ' + R.limits.guard_streak + ' in a row). Blocking a KICK also costs strain stamina, never HP.'],
    ['POWER', 'One per fight: mark a JAB, KICK or THROW for +' + R.power_damage + ' damage at +' + R.power_cost + ' cost. Spent even if it misses.'],
    ['ROUND / BEAT', R.rounds + ' rounds of ' + R.beats_per_round + ' beats. Both plans for a round are sealed, then both resolve beat by beat, simultaneously.'],
    ['COMMIT / REVEAL', 'Each round a bot first commits a hash of its plan and a secret salt, then reveals both. Nobody can change a plan after seeing the other one.'],
    ['TICK', 'The chain\'s clock. Deadlines are ticks. A countdown on this site is time left to act, never health.'],
    ['TIMEOUT / FORFEIT', 'Missing a commit or reveal deadline forfeits the fight. It is shown as TIMEOUT, never as a knockout, and no beats are invented.'],
    ['DOUBLE FAULT / VOID', 'Both sides missed a deadline, or the service could not finish: no winner, stakes refunded, no rating change.'],
    ['UNEXECUTED', 'Actions revealed after a knockout. They are shown for completeness and never counted as play.'],
    ['REPLAY_MATCH', 'Your browser recomputed the commitments and replayed every beat from the revealed plans, and everything matched. Chain inclusion is not proven by this site.'],
    ['COMBAT_VERIFIED', 'Every check passed, including confirmation on chain. A same-source export cannot earn it.'],
    ['HASH_MATCH_ONLY / UNVERIFIED / FAILED', 'Only hashes could be checked / nothing could be checked / something did not match: do not trust that record.'],
    ['RATING / BELT', 'Integer rating from 1000; the first 10 ranked fights are placement (PROVISIONAL, white). Belts are display only.'],
    ['SAMPLE', 'No live export was found, so the site shows a devnet sample: fake QU, synthetic fighters.'],
    ['STALE', 'The live export has not been rewritten for over ' + Math.round(L.STALE_MS / 60000) + ' minutes: the house exporter may be down, and what you see may be old.'],
    ['LEGACY', 'The retired riddle arcade, kept read-only so its history stays reachable.'],
  ];
  function viewHelp() {
    setView(screen('HELP', 'EVERY WORD ON THIS SITE') + '<section class="panel"><h3>GLOSSARY</h3><dl class="kv help-kv">' +
      helpEntries().map(([k, v]) => '<dt>' + esc(k) + '</dt><dd>' + esc(v) + '</dd>').join('') + '</dl></section>' +
      '<section class="panel"><h3>KEYS</h3><p>Replays: LEFT/RIGHT step, SPACE play/pause, HOME/END, or pick a row in the beat table. Practice: 1-6 pick actions, P power, BACKSPACE clear, ENTER fight. MOTION: OFF shows the same information with nothing moving.</p></section>');
  }

  // ---- the replay player -------------------------------------------------------------

  function cbar(kind, label) {
    return '<div class="cbar cbar-' + kind + '" role="meter" aria-label="' + esc(label) + '" aria-valuemin="0">' +
      '<div class="cbar-label"><span>' + esc(label) + '</span><b class="cbar-num">—</b></div>' +
      '<div class="cbar-track"><div class="cbar-fill"></div><div class="cbar-lost"></div></div></div>';
  }
  function setBar(el, value, max, before) {
    el.setAttribute('aria-valuemax', max);
    el.setAttribute('aria-valuenow', value);
    $('.cbar-num', el).textContent = value + '/' + max;
    const fill = $('.cbar-fill', el), lost = $('.cbar-lost', el);
    const w = max ? 100 * value / max : 0;
    fill.style.width = w + '%';
    fill.classList.toggle('low', value <= max / 4);
    const drop = before != null && before > value ? 100 * (before - value) / max : 0;
    lost.style.left = w + '%';
    lost.style.width = drop + '%';
  }

  function actionTag(name, power, intended) {
    const exhausted = intended != null && name === 'EXHAUSTED';
    return '<span class="act act-' + esc(name.toLowerCase()) + '">' + (exhausted ? esc(intended) + ' &rarr; ' : '') + esc(name) + (power ? ' <i class="pw" title="power strike">&#9733;</i>' : '') + '</span>';
  }

  function sideSummary(t, o) {
    const eff = NAMES[t.effective], bits = [];
    if (t.actual_hp_lost > 0) bits.push('<b class="neg">-' + t.actual_hp_lost + ' HP</b>');
    else if (t.effective === L.ID.BLOCK && [L.ID.JAB, L.ID.KICK].includes(o.effective)) bits.push('<b class="blocked">BLOCKED &middot; 0 HP</b>');
    else if (o.computed_damage === 0 && [L.ID.JAB, L.ID.KICK, L.ID.THROW].includes(o.effective) && t.effective === L.ID.DUCK) bits.push('<b class="blocked">EVADED</b>');
    if (t.strain) bits.push('<span class="strain">-' + t.strain + ' ST strain</span>');
    if (t.after.opening) bits.push('<span class="opening">OPENING</span>');
    return actionTag(eff, t.power, NAMES[t.intended]) + '<div class="sum">' + (bits.join(' ') || '<span class="muted">no damage</span>') + '</div>';
  }

  function frameLabel(f, total) {
    const rn = 'R' + (f.round + 1);
    switch (f.kind) {
      case 'start': return rn + ' READY';
      case 'round': return rn + ' START';
      case 'beat': return rn + ' B' + (f.beat + 1);
      case 'unexecuted': return rn + ' B' + (f.beat + 1) + ' UNEXECUTED';
      case 'break': return rn + ' BREAK';
      case 'end': return 'END';
      case 'forfeit': return 'TIMEOUT';
      default: return String(total);
    }
  }

  /* opts: { frames, ids: {A, B}, names: {A, B}, links: bool, replay (for labels),
   *         mySide (practice: explanations say YOU), autoplay } */
  function createPlayer(root, opts) {
    const frames = opts.frames, names = opts.names;
    let idx = 0, playing = false, timer = null, speed = 1;
    const speedStored = Number(store.get('qdojo.combat.speed'));
    if (SPEEDS.includes(speedStored)) speed = speedStored;
    const corner = s => {
      const id = opts.ids[s];
      const head = opts.links && HEX64.test(id) ? '<a class="corner-name" href="#fighter/' + id + '">' + esc(names[s]) + '</a>' : '<span class="corner-name">' + esc(names[s]) + '</span>';
      // The corner is one element (tests and ARIA find everything under it);
      // CSS places its HUD, fighter and move line into the stage grid.
      return '<div class="corner corner-' + s + '" data-side="' + s + '">' +
        '<div class="corner-hud">' + head + cbar('hp', 'HP') + cbar('st', 'STAMINA') + '<span class="rmarks"></span>' +
        '<div class="flags"><span class="flag flag-power"></span><span class="flag flag-opening">OPENING</span><span class="flag flag-guard"></span></div></div>' +
        '<div class="fighter-box"><span class="fshadow" aria-hidden="true"></span><span class="avatar avatar-stage" data-anim="manual" data-identity="' + esc(id) + '">' + (A ? A.svg(id, 'sprite') : '') + '</span>' +
        '<span class="pop" aria-hidden="true"></span><span class="fx-spark" aria-hidden="true"></span><span class="fx-word" aria-hidden="true"></span><span class="win-plate" aria-hidden="true">WINNER</span></div>' +
        '<div class="side-now"></div></div>';
    };
    const rows = frames.map((f, i) => {
      const cls = 'fr fr-' + f.kind;
      if (f.kind === 'beat') {
        const a = f.trace.A, b = f.trace.B;
        const cell = (t, o) => '<td>' + actionTag(NAMES[t.effective], t.power, NAMES[t.intended]) + '</td><td class="num">' + (t.actual_hp_lost ? '<span class="neg">-' + t.actual_hp_lost + '</span> ' : '') + t.after.hp + '</td><td class="num">' + t.after.stamina + (t.strain ? ' <span class="strain">(-' + t.strain + ')</span>' : '') + '</td>';
        return '<tr class="' + cls + '" data-i="' + i + '" tabindex="-1"><td>' + (f.round + 1) + '</td><td>' + (f.beat + 1) + '</td>' + cell(a, b) + cell(b, a) + '<td class="reasons" title="' + esc('A: ' + a.reasons.join(' ') + ' / B: ' + b.reasons.join(' ')) + '">' + esc(L.beatHeadline(a, b, names)) + '</td></tr>';
      }
      if (f.kind === 'unexecuted') {
        return '<tr class="' + cls + '" data-i="' + i + '" tabindex="-1"><td>' + (f.round + 1) + '</td><td>' + (f.beat + 1) + '</td><td colspan="3">' + esc(NAMES[f.intended.A]) + (f.power.A ? ' &#9733;' : '') + '</td><td colspan="3">' + esc(NAMES[f.intended.B]) + (f.power.B ? ' &#9733;' : '') + '</td><td class="reasons">UNEXECUTED: revealed, not played (fight already over)</td></tr>';
      }
      let text = '';
      if (f.kind === 'start') text = 'ROUND 1: both start at HP ' + f.a.hp + ', STAMINA ' + f.a.stamina;
      if (f.kind === 'round') text = 'ROUND ' + (f.round + 1) + ' START';
      if (f.kind === 'break') text = 'BREAK after round ' + (f.round + 1) + ': stamina A +' + f.recovery.A + ', B +' + f.recovery.B + ' (capped at ' + R.limits.stamina + '); HP, opening, guard and power carry';
      if (f.kind === 'end') text = L.outcomeLabel({ outcome: f.outcome }).text;
      if (f.kind === 'forfeit') text = L.outcomeLabel(opts.replay).text;
      return '<tr class="' + cls + '" data-i="' + i + '" tabindex="-1"><td>' + (f.round + 1) + '</td><td></td><td colspan="7" class="note">' + esc(text) + '</td></tr>';
    }).join('');
    root.innerHTML =
      '<div class="stage arcade' + (opts.compact ? ' stage-compact' : '') + '"><canvas class="stage-bg" aria-hidden="true"></canvas>' + corner('A') +
      '<div class="center"><span class="ko-emblem" aria-hidden="true">KO</span><div class="clock" aria-hidden="true"><b class="clock-n"></b><small class="clock-l"></small></div>' +
      '<div class="round-no"></div><div class="beat-no"></div><div class="center-note"></div></div>' + corner('B') +
      '<div class="announcer" aria-hidden="true"><span></span></div><div class="fx-flash" aria-hidden="true"></div></div>' +
      '<div class="controls" role="group" aria-label="Replay controls">' +
      '<button class="chip" data-act="first" title="First (Home)">|&#9664;</button>' +
      '<button class="chip" data-act="prev" title="Previous beat (Left)">&#9664;</button>' +
      '<button class="chip play" data-act="play" title="Play / pause (Space)">PLAY</button>' +
      '<button class="chip" data-act="next" title="Next beat (Right)">&#9654;</button>' +
      '<button class="chip" data-act="last" title="Last (End)">&#9654;|</button>' +
      '<label class="speed">SPEED <select data-act="speed">' + SPEEDS.map(s => '<option value="' + s + '"' + (s === speed ? ' selected' : '') + '>' + s + 'x</option>').join('') + '</select></label>' +
      '<span class="beat-ms tiny muted"></span><span class="pos tiny"></span></div>' +
      '<p class="beat-headline" aria-live="polite"></p>' +
      '<p class="tiny muted stage-help">Keys: LEFT/RIGHT step, SPACE play/pause, HOME/END. Motion is decoration only: every number above comes from the independent replay.</p>' +
      '<div class="caption cols"><div class="cap cap-A"></div><div class="cap cap-B"></div></div>' +
      '<details class="beat-details" open><summary>BEAT TABLE (' + frames.filter(f => f.kind === 'beat').length + ' executed beats)</summary>' +
      '<div class="tscroll"><table class="beats"><thead><tr><th>RND</th><th>BEAT</th><th>' + esc(names.A) + '</th><th class="num">HP</th><th class="num">ST</th><th>' + esc(names.B) + '</th><th class="num">HP</th><th class="num">ST</th><th>WHAT HAPPENED</th></tr></thead><tbody>' + rows + '</tbody></table></div></details>';

    root.classList.toggle('compact', !!opts.compact);
    const els = {};
    for (const s of ['A', 'B']) {
      const c = $('.corner-' + s, root);
      els[s] = { corner: c, avatar: $('.avatar', c), hp: $('.cbar-hp', c), st: $('.cbar-st', c), power: $('.flag-power', c), opening: $('.flag-opening', c), guard: $('.flag-guard', c), now: $('.side-now', c), pop: $('.pop', c), spark: $('.fx-spark', c), word: $('.fx-word', c), marks: $('.rmarks', c), lost: $('.cbar-hp .cbar-lost', c), cap: $('.cap-' + s, root) };
    }
    if (ANIM) ANIM.mount(root);
    const stageEl = $('.stage', root), announcer = $('.announcer span', root);
    // The arena behind the fighters: chosen by fight ID, decoration only.
    if (STAGES) STAGES.mount($('.stage-bg', root), { seed: opts.stageSeed != null ? opts.stageSeed : opts.replay && opts.replay.fight_id != null ? opts.replay.fight_id : names.A + names.B, fps: opts.compact ? 8 : 12 });
    let fxToken = 0;
    // Round markers: after each finished round (a break, or the end), the side
    // ahead on HP gets a medal. Display only: a fight is decided by K.O. or
    // by final HP, never by counting these.
    const leads = [];
    frames.forEach((f, i) => {
      if (f.kind !== 'break' && f.kind !== 'end') return;
      if (f.kind === 'end' && leads.some(x => x.round === f.round)) return;
      leads.push({ i, round: f.round, lead: f.a.hp > f.b.hp ? 'A' : f.b.hp > f.a.hp ? 'B' : null });
    });
    const clockN = $('.clock-n', root), clockL = $('.clock-l', root), koEmblem = $('.ko-emblem', root);
    const play = $('[data-act=play]', root);
    const msEl = $('.beat-ms', root), posEl = $('.pos', root);
    const table = $('table.beats', root);

    function stateOf(f) {
      if (f.a && f.b) return f;
      return { a: E.newFight(R).a, b: E.newFight(R).b, initialOnly: true };
    }

    function render(animate) {
      const f = frames[idx];
      const st = stateOf(f);
      for (const s of ['A', 'B']) {
        const me = s === 'A' ? st.a : st.b, x = els[s];
        const t = f.kind === 'beat' ? f.trace[s] : null;
        setBar(x.hp, me.hp, R.limits.hp, t ? t.before.hp : null);
        setBar(x.st, me.stamina, R.limits.stamina, null);
        x.power.textContent = me.power_available ? 'POWER READY' : 'POWER SPENT';
        x.power.classList.toggle('on', !!me.power_available);
        x.opening.classList.toggle('on', !!me.opening);
        x.guard.textContent = 'GUARD ' + me.guard_streak;
        x.guard.classList.toggle('on', me.guard_streak > 0);
        x.corner.className = 'corner corner-' + s + (t ? ' pose-' + NAMES[t.effective].toLowerCase() : '') + (t && t.actual_hp_lost ? ' took-hit' : '') + (me.hp === 0 ? ' down' : '');
        x.pop.textContent = t && t.actual_hp_lost ? '-' + t.actual_hp_lost : '';
        if (f.kind === 'beat') {
          x.now.innerHTML = sideSummary(t, f.trace[s === 'A' ? 'B' : 'A']);
          const who = opts.mySide === s ? 'YOU' : names[s], them = opts.mySide === (s === 'A' ? 'B' : 'A') ? 'YOU' : names[s === 'A' ? 'B' : 'A'];
          const lines = L.explainSide(t, f.trace[s === 'A' ? 'B' : 'A'], who, them);
          if (opts.mySide === s) {
            const h = L.hindsight(R, { a: f.trace.A.before, b: f.trace.B.before }, s, f.trace);
            if (h) lines.push(h.text);
          }
          x.cap.innerHTML = '<h4>' + esc(names[s]) + '</h4><ul>' + lines.map(l => '<li' + (/^HINDSIGHT/.test(l) ? ' class="hindsight"' : '') + '>' + esc(l) + '</li>').join('') + '</ul>';
        } else if (f.kind === 'unexecuted') {
          x.now.innerHTML = '<span class="act act-unexec">' + esc(NAMES[f.intended[s]]) + (f.power[s] ? ' &#9733;' : '') + '</span><div class="sum muted">not played</div>';
          x.cap.innerHTML = '<h4>' + esc(names[s]) + '</h4><p class="muted">Revealed intention, never executed: the fight ended earlier. Not counted as play.</p>';
        } else {
          x.now.innerHTML = '';
          x.cap.innerHTML = '';
        }
      }
      for (const s of ['A', 'B']) {
        const won = leads.filter(x => x.i <= idx && x.lead === s);
        els[s].marks.innerHTML = won.map(x => '<i class="rmark" title="Ahead on HP after round ' + (x.round + 1) + ' (display only)">&#9733;</i>').join('');
        els[s].marks.setAttribute('aria-label', won.length ? names[s] + ' ahead on HP after ' + won.length + ' round' + (won.length === 1 ? '' : 's') : '');
        els[s].pop.classList.remove('go'); els[s].spark.classList.remove('go'); els[s].word.classList.remove('go'); els[s].lost.classList.remove('drain');
      }
      // The round box counts beats left in the round (never a fake timer).
      const left = f.kind === 'beat' || f.kind === 'unexecuted' ? R.beats_per_round - f.beat - 1 : f.kind === 'start' || f.kind === 'round' ? R.beats_per_round : null;
      clockN.textContent = left == null ? (f.kind === 'break' ? '--' : 'END') : String(left);
      clockL.textContent = left == null ? '' : 'BEATS LEFT';
      koEmblem.classList.toggle('lit', (st.a.hp === 0 || st.b.hp === 0));
      const rnd = $('.round-no', root), bn = $('.beat-no', root), note = $('.center-note', root);
      rnd.textContent = 'ROUND ' + Math.min(f.round + 1, R.rounds) + '/' + R.rounds;
      bn.textContent = f.kind === 'beat' || f.kind === 'unexecuted' ? 'BEAT ' + (f.beat + 1) + '/' + R.beats_per_round : '';
      let text = '';
      if (f.kind === 'start') text = 'FIGHT!';
      if (f.kind === 'round') text = 'ROUND ' + (f.round + 1);
      if (f.kind === 'break') text = 'BREAK: +' + f.recovery.A + ' / +' + f.recovery.B + ' ST';
      if (f.kind === 'unexecuted') text = 'UNEXECUTED (after KO)';
      if (f.kind === 'end') text = L.outcomeLabel({ outcome: f.outcome }).short;
      if (f.kind === 'forfeit') text = 'TIMEOUT';
      note.textContent = text;
      // The whole exchange in one plain sentence: the same text with motion off.
      const head = $('.beat-headline', root);
      head.textContent = f.kind === 'beat' ? L.beatHeadline(f.trace.A, f.trace.B, names)
        : f.kind === 'unexecuted' ? 'Revealed but never played: the fight was already over.'
        : f.kind === 'break' ? 'Break between rounds: +' + f.recovery.A + ' / +' + f.recovery.B + ' stamina; HP, opening, guard and power carry over.'
        : f.kind === 'end' ? L.outcomeLabel({ outcome: f.outcome }).text
        : f.kind === 'forfeit' ? L.outcomeLabel(opts.replay).text
        : f.kind === 'round' ? 'Round ' + (f.round + 1) + ' begins from the state above.' : 'Both fighters start at HP ' + st.a.hp + ' and stamina ' + st.a.stamina + '.';
      note.className = 'center-note note-' + f.kind;
      // Announcer and winner plate: derived from the frame alone, so motion
      // off shows the same words, only without the entrance.
      const ann = announce(f);
      announcer.textContent = ann.text;
      announcer.parentNode.className = 'announcer' + (ann.text ? ' on ann-' + ann.kind : '');
      const winner = f.kind === 'end' ? f.outcome.winner : f.kind === 'forfeit' && opts.replay && opts.replay.result ? opts.replay.result.winner : null;
      for (const s of ['A', 'B']) els[s].corner.classList.toggle('winner', winner === s);
      stageEl.classList.remove('shake', 'shake-big', 'flash-power');
      if (f.kind === 'forfeit') {
        els.A.cap.innerHTML = '<p>' + esc(L.outcomeLabel(opts.replay).text) + '</p>' + (!f.played ? '<p class="muted">No round was played; the bars show the start state at the deadline, not a result.</p>' : '<p class="muted">Bars show the re-derived state at the deadline (round ' + (f.round + 1) + '). No beat is invented for the missing reveal.</p>');
      }
      if (f.kind === 'end') els.A.cap.innerHTML = '<p>' + esc(L.outcomeLabel({ outcome: f.outcome }).text) + '</p>';
      $$('tr.fr.on', table).forEach(r => r.classList.remove('on'));
      const row = $('tr[data-i="' + idx + '"]', table);
      if (row) { row.classList.add('on'); row.setAttribute('aria-current', 'true'); scrollRow(row); }
      posEl.textContent = frameLabel(f) + ' (' + (idx + 1) + '/' + frames.length + ')';
      msEl.textContent = Math.round(BEAT_MS / speed) + ' MS/BEAT';
      if (animate) animateFrame(f);
    }
    function scrollRow(row) {
      const box = row.closest('.tscroll');
      if (!box || !box.closest('details[open]')) return;
      const top = row.offsetTop, h = row.offsetHeight;
      if (box.scrollHeight > box.clientHeight && (top < box.scrollTop + 30 || top + h > box.scrollTop + box.clientHeight)) box.scrollTop = Math.max(0, top - 60);
    }
    function announce(f) {
      if (f.kind === 'start') return { text: 'ROUND 1', kind: 'round' };
      if (f.kind === 'round') return { text: 'ROUND ' + (f.round + 1), kind: 'round' };
      if (f.kind === 'forfeit') return { text: 'TIME OUT', kind: 'timeout' };
      if (f.kind === 'end') {
        const r = f.outcome.result;
        return { text: r === 'KO' ? 'K.O.' : r === 'DOUBLE_KO' ? 'DOUBLE K.O.' : r === 'HP_TIE' ? 'DRAW' : r === 'HP' ? 'DECISION' : String(r || ''), kind: r === 'KO' || r === 'DOUBLE_KO' ? 'ko' : 'end' };
      }
      return { text: '', kind: '' };
    }
    // Restart a CSS animation class on an element.
    function replay(el, cls) { el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls); }
    // Arcade juice for one frame: sparks, floating numbers, shake, flash,
    // BLOCKED / EVADE, the announcer's entrance. Reads the frame, changes nothing.
    function juice(f) {
      const token = ++fxToken;
      const ann = announcer.parentNode;
      if (f.kind === 'start' || f.kind === 'round') {
        replay(ann, 'enter');
        setTimeout(() => {
          if (token !== fxToken || !root.isConnected) return;
          announcer.textContent = 'FIGHT!';
          ann.classList.add('ann-fight');
          replay(ann, 'enter');
          setTimeout(() => { if (token === fxToken) ann.classList.add('leave'); }, Math.max(250, 500 / speed));
        }, Math.max(300, 700 / speed));
      } else if (f.kind === 'end' || f.kind === 'forfeit') {
        replay(ann, 'enter');
        const w = f.kind === 'end' ? f.outcome.winner : (opts.replay && opts.replay.result || {}).winner;
        if (w) {
          const perfect = f.kind === 'end' && (w === 'A' ? f.a : f.b).hp === R.limits.hp;
          setTimeout(() => {
            if (token !== fxToken || !root.isConnected) return;
            announcer.textContent = perfect ? 'PERFECT' : opts.mySide ? (opts.mySide === w ? 'YOU WIN' : 'YOU LOSE') : names[w].replace(/^[AB] /, '') + ' WINS';
            ann.className = 'announcer on ann-win';
            replay(ann, 'enter');
          }, Math.max(600, 1100 / speed));
        }
      }
      if (f.kind !== 'beat') return;
      let big = 0, power = false;
      for (const s of ['A', 'B']) {
        const t = f.trace[s], o = f.trace[s === 'A' ? 'B' : 'A'], x = els[s];
        const oEff = NAMES[o.effective];
        if (t.actual_hp_lost > 0) {
          big = Math.max(big, t.actual_hp_lost);
          if (o.power && ['JAB', 'KICK', 'THROW'].includes(oEff)) power = true;
          x.spark.className = 'fx-spark' + (t.actual_hp_lost >= 12 ? ' big' : '');
          replay(x.spark, 'go');
          replay(x.pop, 'go');
          replay(x.lost, 'drain');
          x.word.textContent = '';
        } else if (t.effective === L.ID.BLOCK && [L.ID.JAB, L.ID.KICK].includes(o.effective)) {
          x.word.textContent = 'BLOCKED'; x.word.className = 'fx-word w-block'; replay(x.word, 'go');
        } else if (o.computed_damage === 0 && [L.ID.JAB, L.ID.KICK, L.ID.THROW].includes(o.effective) && t.effective === L.ID.DUCK) {
          x.word.textContent = 'EVADE'; x.word.className = 'fx-word w-evade'; replay(x.word, 'go');
        } else {
          x.word.textContent = '';
        }
      }
      if (big >= 12) replay(stageEl, big >= 20 ? 'shake-big' : 'shake');
      if (power) replay(stageEl, 'flash-power');
    }
    function animateFrame(f) {
      if (!motion()) return;
      juice(f);
      for (const s of ['A', 'B']) ANIM.rate(els[s].avatar, speed);
      if (f.kind === 'beat') {
        for (const s of ['A', 'B']) {
          const t = f.trace[s];
          // Every combat action has its own clip; a fighter who loses HP while
          // not attacking or blocking shows the hit reaction instead.
          const clip = { JAB: 'jab', KICK: 'kick', THROW: 'throw', DUCK: 'duck', BLOCK: 'block', RECOVER: 'recover', EXHAUSTED: 'exhausted' }[NAMES[t.effective]];
          const struck = t.actual_hp_lost && (clip === 'duck' || clip === 'recover' || clip === 'exhausted');
          if (clip && !struck) ANIM.play(els[s].avatar, clip);
          else if (t.actual_hp_lost) ANIM.play(els[s].avatar, 'hit', 80 / speed);
          if (t.actual_hp_lost) {
            const c = els[s].corner;
            c.classList.remove('flash-hit');
            void c.offsetWidth;
            c.classList.add('flash-hit');
          }
        }
      } else if (f.kind === 'end') {
        const w = f.outcome.winner;
        for (const s of ['A', 'B']) ANIM.play(els[s].avatar, w === s ? 'win' : (s === 'A' ? f.a : f.b).hp === 0 ? 'lose' : 'idle');
      } else if (f.kind === 'start' || f.kind === 'round') {
        for (const s of ['A', 'B']) ANIM.play(els[s].avatar, 'bow');
      }
    }
    function seek(i, animate) {
      idx = Math.max(0, Math.min(frames.length - 1, i));
      render(animate);
    }
    function holdFor(f) {
      const base = BEAT_MS / speed;
      return f.kind === 'beat' || f.kind === 'unexecuted' ? base : base * 2;
    }
    function schedule() {
      clearTimeout(timer);
      if (!playing) return;
      timer = setTimeout(() => {
        if (!root.isConnected) { stop(); return; }
        if (idx >= frames.length - 1) { pause(); return; }
        seek(idx + 1, true);
        schedule();
      }, holdFor(frames[idx]));
    }
    function start() {
      if (idx >= frames.length - 1) seek(0, true);
      playing = true; play.textContent = 'PAUSE'; play.setAttribute('aria-pressed', 'true');
      schedule();
    }
    function pause() { playing = false; clearTimeout(timer); play.textContent = 'PLAY'; play.setAttribute('aria-pressed', 'false'); }
    function stop() { pause(); }
    function toggle() { if (playing) pause(); else start(); }

    root.addEventListener('click', e => {
      const b = e.target.closest('[data-act]');
      if (b && b.tagName === 'BUTTON') {
        const act = b.dataset.act;
        if (act === 'play') toggle();
        if (act === 'first') { pause(); seek(0, false); }
        if (act === 'last') { pause(); seek(frames.length - 1, false); }
        if (act === 'prev') { pause(); seek(idx - 1, false); }
        if (act === 'next') { pause(); seek(idx + 1, true); }
        return;
      }
      const tr = e.target.closest('tr[data-i]');
      if (tr) { pause(); seek(Number(tr.dataset.i), false); tr.focus(); }
    });
    $('select[data-act=speed]', root).addEventListener('change', e => {
      const v = Number(e.target.value);
      if (SPEEDS.includes(v)) { speed = v; store.set('qdojo.combat.speed', String(v)); render(false); if (playing) schedule(); }
    });
    root.addEventListener('keydown', e => {
      if (e.target.closest('select, input, textarea')) return;
      const inTable = !!e.target.closest('table.beats');
      let handled = true;
      if (e.key === 'ArrowRight' || (inTable && e.key === 'ArrowDown')) { pause(); seek(idx + 1, true); }
      else if (e.key === 'ArrowLeft' || (inTable && e.key === 'ArrowUp')) { pause(); seek(idx - 1, false); }
      else if (e.key === 'Home') { pause(); seek(0, false); }
      else if (e.key === 'End') { pause(); seek(frames.length - 1, false); }
      else if (e.key === ' ' || e.key === 'k') { if (e.target.tagName === 'BUTTON' && e.key === ' ') return; toggle(); }
      else handled = false;
      if (handled) {
        e.preventDefault();
        if (inTable) { const row = $('tr[data-i="' + idx + '"]', table); if (row) row.focus(); }
      }
    });
    $$('tr[data-i]', table).forEach(tr => { tr.tabIndex = 0; });
    seek(opts.startAt != null ? opts.startAt : 0, false);
    if (opts.autoplay && motion()) start();
    else if (opts.autoplay) seek(frames.length - 1, false);
    return { stop, seek, start, pause, get index() { return idx; }, frames };
  }

  function stopPlayer() {
    players.forEach(p => p.stop());
    players = [];
    timers.forEach(t => clearInterval(t));
    timers = [];
  }
  function track(p) { players.push(p); return p; }

  // ---- REPLAY ------------------------------------------------------------------------

  async function viewFight(tok, id) {
    if (needData()) return;
    if (!DEC.test(id || '')) return notFound('Fight IDs are decimal numbers.');
    const summary = await fetchJson('fights/' + id + '.json').catch(() => null);
    // No summary (pruned or unknown): still try the replay once; a summary
    // that says no round resolved yet means there is no replay to ask for.
    const replay = summary ? await replayFor(summary) : await fetchJson('fights/' + id + '/replay.json').catch(() => null);
    if (tok !== viewToken) return;
    if (!summary && !replay) return notFound('Fight #' + id + ' is not in this export.');
    const fighters = (replay || summary).fighters;
    const names = { A: 'A ' + short(fighters.A.fighter_id), B: 'B ' + short(fighters.B.fighter_id) };
    const live = summary && summary.phase !== 'DONE';
    const liveBanner = live
      ? '<section class="panel panel-yellow live-banner"><h3>LIVE FIGHT</h3><p>Authoritative state: round ' + (summary.round_index + 1) + ', phase <b>' + esc(summary.phase) + '</b>. ' +
        'Commit deadline tick ' + esc(summary.commit_last) + ', reveal deadline tick ' + esc(summary.reveal_last) + ' (snapshot tick ' + esc(summary.generated_tick) + ').</p>' +
        '<p>Committed: ' + esc((summary.committed || []).join(', ') || 'none') + ' &middot; revealed: ' + esc((summary.revealed || []).join(', ') || 'none') + '. Plans stay sealed until revealed.</p>' +
        '<p class="muted">The replay below shows only completed rounds and trails the authoritative round. Deadlines are time, never health.</p></section>'
      : '';
    const head = screen('FIGHT #' + id, esc(String((replay || summary).mode || '').toUpperCase()) + ' &middot; ' + esc(R.semantic_version.toUpperCase()));
    const vs = '<div class="vsline">' + fighterLink(fighters.A.fighter_id, names.A) + ' <span class="vs">VS</span> ' + fighterLink(fighters.B.fighter_id, names.B) +
      ' <span id="level-slot">' + (replay ? '<span class="level level-PENDING">VERIFYING&hellip;</span>' : '') + '</span> <span id="series-slot"></span></div>';
    if (!replay) {
      setView(head + vs + liveBanner + '<section class="panel"><h3>NO ROUND COMPLETED YET</h3><p class="muted">Nothing is revealed for this fight at this snapshot, so there is nothing to replay.</p></section>');
      return;
    }
    const derived = L.deriveReplay(R, replay);
    const frames = L.timeline(replay, derived);
    const lab = L.outcomeLabel(replay);
    setView(head + vs + liveBanner +
      '<section class="panel panel-cyan result-panel"><h3>RESULT</h3><p>' + resultBadge(replay) + ' ' + esc(lab.text) + '</p>' +
      (derived.error ? '<p class="neg">The engine refused this record: ' + esc(derived.error) + '</p>' : '') + '</section>' +
      '<section class="panel player-panel"><h3>REPLAY &middot; RE-DERIVED FROM REVEALED PLANS</h3><div id="player"></div></section>' +
      '<section class="panel verify-panel" id="verify"><h3>VERIFICATION</h3><p class="muted">Recomputing digests and commitments&hellip;</p></section>' +
      plansPanel(replay));
    track(createPlayer($('#player'), { frames, ids: { A: fighters.A.fighter_id, B: fighters.B.fighter_id }, names, links: true, replay, stageSeed: id, autoplay: true }));
    seriesLink(id, replay.mode).then(html => { if (tok === viewToken && $('#series-slot')) $('#series-slot').innerHTML = html; }).catch(() => {});
    markScrollers($('#view'));
    const v = await L.verifyReplay(replay, { rules: R, manifest: D.manifest, sha256: SHA }).catch(e => ({ checks: [{ id: 'error', label: 'Verification', status: 'FAIL', evidence: e.message, details: [] }], level: 'FAILED' }));
    if (tok !== viewToken) return;
    $('#level-slot').innerHTML = levelBadge(v.level);
    $('#verify').innerHTML = '<h3>VERIFICATION</h3>' + verifyHtml(v);
  }

  function verifyHtml(v) {
    return '<div class="level-row">' + levelBadge(v.level) + '<p>' + esc(L.LEVELS[v.level] || '') + '</p></div>' +
      '<ol class="checks">' + v.checks.map(c => '<li class="check check-' + esc(c.status.toLowerCase()) + '">' + statusBadge(c.status) + ' <b>' + esc(c.label) + '</b>' +
        '<p class="evidence">' + esc(c.evidence) + '</p>' +
        (c.details && c.details.length ? '<details><summary>' + c.details.length + ' DETAIL' + (c.details.length > 1 ? 'S' : '') + '</summary><ul class="details mono">' + c.details.map(d => '<li>' + esc(d) + '</li>').join('') + '</ul></details>' : '') +
        '</li>').join('') + '</ol>' +
      '<p class="tiny muted">COMBAT_VERIFIED needs every check to PASS. UNAVAILABLE is never counted as a pass. SHA-256: ' + esc(SHA.engine || 'crypto.subtle') + '.</p>';
  }

  function plansPanel(replay) {
    if (!(replay.rounds || []).length) return '';
    const planText = p => p.actions.map((a, i) => (i === p.power_slot ? a + '&#9733;' : a)).join(' ');
    return '<section class="panel"><h3>REVEALED PLANS</h3><p class="tiny muted">Public only after each reveal. The page replays from the committed plan bytes, not from this display copy.</p>' +
      replay.rounds.map(r => '<details><summary>ROUND ' + (r.round_index + 1) + ' &middot; confirmed tick ' + esc(r.tick) + '</summary><dl class="kv">' +
        ['A', 'B'].map(s => '<dt>' + s + ' PLAN</dt><dd>' + planText(r.plans[s]) + ' <span class="id">(' + esc(r.plan_bytes[s]) + ')</span></dd>' +
          '<dt>' + s + ' SALT</dt><dd class="id wrap">' + esc(r.salts[s]) + '</dd><dt>' + s + ' COMMIT</dt><dd class="id wrap">' + esc(r.commitments[s]) + '</dd>').join('') +
        '<dt>STATE DIGEST</dt><dd class="id wrap">' + esc(r.round_state_digest) + '</dd></dl></details>').join('') + '</section>';
  }

  // ---- FIGHTER -----------------------------------------------------------------------

  // Every finished fight per mode, from the export's records_by_mode (the
  // contract's own record covers ranked fights only). Older exports lack it.
  function careerOf(f) {
    const by = f.records_by_mode && Object.keys(f.records_by_mode).length ? f.records_by_mode : { ranked: f.record || {} };
    const tot = { W: 0, D: 0, L: 0, FW: 0, FL: 0, N: 0 };
    for (const r of Object.values(by)) for (const k of Object.keys(tot)) tot[k] += Number(r[k] || 0);
    return { by, tot, fought: tot.W + tot.D + tot.L, all: tot.W + tot.D + tot.L + tot.FW + tot.FL + tot.N };
  }
  function careerTable(f) {
    const c = careerOf(f), order = ['ranked', 'duel', 'cup'];
    const modes = Object.keys(c.by).sort((a, b) => (order.indexOf(a) + 1 || 9) - (order.indexOf(b) + 1 || 9));
    const row = (label, r, cls) => { const n = (r.W || 0) + (r.D || 0) + (r.L || 0); return '<tr' + (cls ? ' class="' + cls + '"' : '') + '><td>' + label + '</td><td class="num">' + (r.W || 0) + '</td><td class="num">' + (r.D || 0) + '</td><td class="num">' + (r.L || 0) + '</td><td class="num">' + (r.FW || 0) + '/' + (r.FL || 0) + '</td><td class="num">' + (r.N || 0) + '</td>' + winRateCell(r) + '</tr>'; };
    return '<div class="tscroll"><table class="career"><thead><tr><th>MODE</th><th class="num">W</th><th class="num">D</th><th class="num">L</th><th class="num">FORFEITS W/L</th><th class="num">NO RESULT</th><th>WIN RATE</th></tr></thead><tbody>' +
      modes.map(m => row(esc(m.toUpperCase()), c.by[m])).join('') + (modes.length > 1 ? row('ALL', c.tot, 'career-all') : '') + '</tbody></table></div>';
  }

  async function viewFighter(tok, hex) {
    if (needData()) return;
    if (!HEX64.test(hex || '')) return notFound('A fighter ID is 64 lowercase hex digits.');
    const f = await fetchJson('fighters/' + hex + '.json').catch(() => null);
    if (tok !== viewToken) return;
    if (!f) return notFound('Fighter ' + short(hex) + ' is not in this export.');
    const meta = metaOf(hex, f);
    const ids = (f.fights || []).filter(x => DEC.test(x));
    const loaded = await Promise.all(ids.map(async id => {
      const s = await summaryOf(id);
      const rp = await replayFor(s);
      return { id, summary: s, replay: rp };
    }));
    if (tok !== viewToken) return;
    // Completed fights only: a live fight's partial rounds are not scouting data yet.
    const items = loaded.filter(x => x.replay && (!x.summary || x.summary.phase === 'DONE')).map(x => ({ replay: x.replay, derived: L.deriveReplay(R, x.replay), id: x.id }));
    const s = L.fighterStats(hex, items);
    const rec = f.record || {};
    const beltCls = f.provisional ? 'belt-other' : 'belt-' + esc(f.belt || 'other');
    const faults = Object.entries(f.faults_by_epoch || {});
    const freqRows = NAMES.map((n, a) => {
      const cells = [0, 1, 2].map(r => {
        const tot = sumOf(s.perRound[r]);
        const c = s.perRound[r][a];
        return '<td class="num">' + (tot ? '<span class="fbar" style="width:' + Math.round(40 * c / tot) + 'px"></span>' + pct(c, tot) + ' <span class="muted">(' + c + ')</span>' : '—') + '</td>';
      }).join('');
      return '<tr><td>' + actionTag(n) + '</td>' + cells + '<td class="num muted">' + s.unexecuted[a] + '</td></tr>';
    }).join('');
    const results = Object.entries(s.results).map(([m, r]) => '<tr><td>' + esc(m.toUpperCase()) + '</td><td class="num">' + r.W + '</td><td class="num">' + r.D + '</td><td class="num">' + r.L + '</td><td class="num">' + r.FW + '</td><td class="num">' + r.FL + '</td></tr>').join('');
    const fightRows = loaded.slice().reverse().map(x => {
      const src = x.replay || x.summary;
      if (!src) return '';
      const side = src.fighters.A.fighter_id === hex ? 'A' : 'B', opp = src.fighters[side === 'A' ? 'B' : 'A'].fighter_id;
      const out = x.replay ? x.replay : summaryOutcome(x.summary);
      const w = out.outcome ? out.outcome.winner : null;
      const done = !x.summary || x.summary.phase === 'DONE';
      return '<tr><td class="num"><a href="#fight/' + esc(x.id) + '">#' + esc(x.id) + '</a></td><td>' + esc(String(src.mode || '').toUpperCase()) + '</td><td>' + side + '</td><td>' + fighterLink(opp) + '</td><td>' +
        (done ? resultBadge(out) + ' ' + (w == null ? '<span class="muted">draw</span>' : w === side ? '<span class="pos">WON</span>' : '<span class="neg">LOST</span>') : '<span class="rbadge rbadge-open">LIVE</span>') + '</td></tr>';
    }).join('');
    const pw = s.power;
    setView(screen('FIGHTER', '<span class="id wrap">' + esc(hex) + '</span>') +
      '<section class="panel panel-yellow fighter-panel"><h3>' + esc(meta.name ? meta.name.toUpperCase() : short(hex)) + (f.house_npc ? ' &middot; HOUSE NPC' : '') + '</h3>' +
      (A && A.bio ? '<p class="bio">' + esc(A.bio(hex)) + '</p>' : '') +
      '<p class="badges">' + driverBadge(meta.driver) + ' ' + foundingBadge(meta.asset) + (meta.asset ? ' <span class="drv drv-nft" title="Simulated fighter NFT">NFT ' + esc(meta.asset.name || '') + '</span>' : '') + '</p><div class="fprofile">' +
      avatar(hex, 'avatar-xl') + '<dl class="kv">' +
      '<dt>RATING</dt><dd><b class="big">' + esc(f.lifetime_rating) + '</b> ' + (f.provisional ? '<span class="belt belt-sm belt-white" title="Placement: the first 10 ranked fights">PROVISIONAL ' + esc(f.placement_fights) + '/10</span>' : '<span class="belt belt-sm ' + beltCls + '">' + esc(String(f.belt || '').toUpperCase()) + ' BELT</span>') + '</dd>' +
      '<dt>RANKED</dt><dd>' + esc(rec.W || 0) + 'W ' + esc(rec.D || 0) + 'D ' + esc(rec.L || 0) + 'L &middot; forfeits ' + esc(rec.FW || 0) + ' won / ' + esc(rec.FL || 0) + ' lost <span class="muted">(contract record)</span></dd>' +
      '<dt>CAREER</dt><dd>' + esc(careerOf(f).all) + ' finished fights in all modes <span class="muted">(table below)</span></dd>' +
      '<dt>RANKED FIGHTS</dt><dd>' + esc(f.placement_fights) + (f.provisional ? ' of 10 placement fights' : '') + '</dd>' +
      '<dt>STATUS</dt><dd>' + esc(f.lock || 'IDLE') + (f.cooldown_until && f.cooldown_until !== '0' ? ' &middot; cooldown until tick ' + esc(f.cooldown_until) : '') + '</dd>' +
      '<dt>FAULTS</dt><dd>' + (faults.length ? faults.map(([k, v]) => 'epoch ' + esc(k) + ': ' + esc(v)).join(', ') : '<span class="pos">none</span>') + '</dd>' +
      '<dt>SEASONS</dt><dd>' + Object.entries(f.season_ratings || {}).map(([k, v]) => 'S' + esc(k) + ' ' + esc(v)).join(', ') + '</dd>' +
      '<dt>OWNER</dt><dd>' + ownerLink((meta.asset && meta.asset.owner) || f.owner) + (f.operator !== f.owner ? ' &middot; operator <span class="id">' + esc(String(f.operator).slice(0, 8)) + '&hellip;</span>' : ' (self-operated)') + '</dd>' +
      '</dl></div></section>' +
      '<section class="panel panel-yellow"><h3>CAREER</h3>' + careerTable(f) + '<p class="tiny muted">Every finished fight in the arena, by mode. Ratings and belts come from RANKED fights only. Forfeits are missed deadlines; NO RESULT is a double fault or a void.</p></section>' +
      '<section class="panel panel-cyan"><h3>SCOUTING REPORT</h3>' +
      '<p class="caveat">Observed in ' + s.replayed + ' completed fight(s) still published (the export keeps recent fights only), ' + s.beats + ' executed beats, re-derived from revealed plans. ' +
      'History describes past play only; it does not predict the next plan, and owners may change software between rounds.</p>' +
      '<div class="tscroll"><table class="freq"><thead><tr><th>ACTION (EFFECTIVE)</th><th class="num">ROUND 1</th><th class="num">ROUND 2</th><th class="num">ROUND 3</th><th class="num">UNPLAYED*</th></tr></thead><tbody>' + freqRows + '</tbody></table></div>' +
      '<p class="tiny muted">* Revealed after a knockout and never executed: listed apart, not counted as play. EXHAUSTED is a failed unaffordable move.</p>' +
      '<div class="cols">' +
      '<div><h4>POWER</h4><p>Planned in ' + pw.rounds + ' round(s); executed ' + pw.used + ': landed ' + pw.landed + ', wasted ' + pw.wasted + (pw.unplayed ? ', ' + pw.unplayed + ' after a KO (not spent)' : '') + '.<br>By round: R1 ' + pw.byRound[0] + ' &middot; R2 ' + pw.byRound[1] + ' &middot; R3 ' + pw.byRound[2] + '.</p></div>' +
      '<div><h4>OPENINGS</h4><p>Earned ' + s.opening.earned + '. Held on ' + s.opening.held + ' beat(s); converted into bonus damage on ' + s.opening.converted + ' (' + pct(s.opening.converted, s.opening.held) + ').</p></div>' +
      '<div><h4>RECOVERY TIMING</h4><p>RECOVER on beats 1-6: ' + s.recoverByBeat.join(' / ') + '. Punished ' + s.recoverPunished + ' of ' + s.recovers + ' (' + pct(s.recoverPunished, s.recovers) + '). Exhausted ' + s.exhausted + ' time(s).</p></div>' +
      '</div>' +
      '<h4>RESULTS BY MODE (REPLAYED)</h4><div class="tscroll"><table><thead><tr><th>MODE</th><th class="num">W</th><th class="num">D</th><th class="num">L</th><th class="num">FW</th><th class="num">FL</th></tr></thead><tbody>' + (results || '<tr><td colspan="6" class="muted">none</td></tr>') + '</tbody></table></div>' +
      '</section>' +
      '<section class="panel"><h3>OWNERSHIP (SIMULATED NFT)</h3>' + nftHistory(meta.asset) +
      (meta.asset ? '<p class="tiny muted">Issuer <span class="id">' + esc(String(meta.asset.issuer || '').slice(0, 8)) + '&hellip;</span> &middot; asset ' + esc(meta.asset.name || '?') + '. A transfer changes who owns the fighter, never its stats or record.</p>' : '') + '</section>' +
      '<section class="panel"><h3>RECENT FIGHTS (' + loaded.filter(x => x.replay || x.summary).length + ')</h3><div class="tscroll"><table><thead><tr><th class="num">FIGHT</th><th>MODE</th><th>SLOT</th><th>OPPONENT</th><th>RESULT</th></tr></thead><tbody>' + fightRows + '</tbody></table></div></section>');
  }

  // ---- PRACTICE ------------------------------------------------------------------------

  const draft = { actions: [null, null, null, null, null, null], power_slot: -1, sel: 0 };
  function resetDraft() { draft.actions = [null, null, null, null, null, null]; draft.power_slot = -1; draft.sel = 0; }

  // Practice is an arcade mode: pick an opponent, write six moves under the
  // stage, watch the round play out right there, repeat for three rounds.
  // The fight itself is L.practiceStart/practicePlay; nothing here scores.
  const NPC_INFO = {
    'random-v1': { stars: 1, style: 'WILDCARD', tip: 'A pinball machine that learned to walk. No pattern at all: good for learning what each move costs.' },
    'jabber-v1': { stars: 1, style: 'HIGH PRESSURE', tip: 'An ex-riveting arm that cannot stop jabbing. Something low slips under it.' },
    'turtle-v1': { stars: 2, style: 'DEFENSIVE', tip: 'A bank vault on legs. Hides behind its guard, and guards have a weakness.' },
    'kicker-v1': { stars: 2, style: 'HEAVY HITTER', tip: 'A demolition unit. Big kicks, then it has to vent steam.' },
    'mixed-v1': { stars: 3, style: 'BALANCED', tip: 'A retired accountant bot. Budgets its stamina and mixes it up.' },
    'scout-v1': { stars: 4, style: 'ADAPTIVE', tip: 'A security camera with fists. Watches what you did last round and adjusts.' },
  };
  const npcInfo = id => NPC_INFO[id] || { stars: 2, style: 'NPC', tip: '' };
  const stars = n => '<span class="stars" title="Difficulty ' + n + ' of 4">' + '&#9733;'.repeat(n) + '<i>' + '&#9733;'.repeat(4 - n) + '</i></span>';
  // Your practice fighter is drawn by the same generator as the arena's: the name picks the look.
  const myName = () => (store.get('qdojo.combat.myname') || 'CHALLENGER').slice(0, 14);
  const myId = () => 'practice:' + myName().toLowerCase();

  function viewPractice(tok, parts) {
    const npcId = parts[0], seed = parts[1];
    if (npcId && seed && N.ROSTER.some(n => n.id === npcId) && HEX64.test(seed)) {
      if (!practice || practice.npc !== npcId || practice.seed !== seed) {
        practice = L.practiceStart(R, npcId, seed, 1);
        resetDraft();
      }
      return renderPracticeFight();
    }
    practice = null;
    let pick = N.ROSTER.some(n => n.id === npcId) ? npcId : (store.get('qdojo.combat.npc') || 'jabber-v1');
    const pre = HEX64.test(seed || '') ? seed : L.randomSeed();
    setView(screen('CHOOSE YOUR OPPONENT', 'FREE PRACTICE &middot; IN YOUR BROWSER &middot; NO WALLET &middot; NO RATING') +
      '<div class="select">' +
      '<div class="select-side select-you"><span class="select-tag tag-1p">1P</span>' +
      '<span class="avatar avatar-select" data-anim="idle" data-identity="' + esc(myId()) + '" id="my-avatar">' + (A ? A.svg(myId(), 'sprite') : '') + '</span>' +
      '<label class="select-name">YOUR FIGHTER <input id="my-name" maxlength="14" value="' + esc(myName()) + '" spellcheck="false" autocomplete="off"></label>' +
      '<p class="tiny muted">Type a name: the scrapyard bolts together a new robot for every name.</p></div>' +
      '<div class="select-grid" role="radiogroup" aria-label="Opponent">' +
      N.ROSTER.map(n => '<button class="npc-card' + (n.id === pick ? ' on' : '') + '" role="radio" aria-checked="' + (n.id === pick) + '" data-npc="' + esc(n.id) + '">' +
        avatar('npc:' + n.id, 'avatar-lg') + '<b>' + esc(n.name) + '</b>' + stars(npcInfo(n.id).stars) + '</button>').join('') + '</div>' +
      '<div class="select-side select-them" id="them"></div></div>' +
      '<div class="select-go"><button class="btn btn-start" id="go">FIGHT! &#9654;</button></div>' +
      '<details class="select-adv"><summary>ADVANCED: REPLAY SEED</summary><p class="tiny">The NPC\'s private randomness comes from this 32-byte seed. The same seed and the same moves replay the same fight, so a fight can be shared as a link.</p>' +
      '<div class="seed-row"><input id="seed" class="mono" size="66" maxlength="64" spellcheck="false" aria-label="Practice seed, 64 hex digits" value="' + esc(pre) + '"><button class="btn btn-sm" id="new-seed">NEW SEED</button></div>' +
      '<p id="seed-err" class="neg tiny" role="alert"></p></details>' +
      '<p class="practice-note">NPCs are ordinary planners: same stats, no extra HP, and they never see your plan. Difficulty is policy only.</p>');
    const paintThem = () => {
      const n = N.ROSTER.find(x => x.id === pick), info = npcInfo(pick);
      $('#them').innerHTML = '<span class="select-tag tag-2p">CPU</span>' +
        '<span class="avatar avatar-select" data-anim="profile" data-identity="npc:' + esc(n.id) + '">' + (A ? A.svg('npc:' + n.id, 'sprite') : '') + '</span>' +
        '<b class="select-title">' + esc(n.name) + '</b><span class="select-style">' + esc(info.style) + ' ' + stars(info.stars) + '</span>' +
        '<p>' + esc(info.tip) + '</p><details class="scout"><summary>SCOUTING REPORT</summary><p class="tiny">' + esc(n.behavior) + '. ' + esc(n.lesson) + '.</p></details>';
      if (ANIM) ANIM.mount($('#them'));
    };
    paintThem();
    $$('.npc-card').forEach(b => b.addEventListener('click', () => {
      pick = b.dataset.npc;
      $$('.npc-card').forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', String(x === b)); });
      paintThem();
    }));
    $('#my-name').addEventListener('input', e => {
      const v = e.target.value.replace(/[^\w .-]/g, '').toUpperCase();
      store.set('qdojo.combat.myname', v || 'CHALLENGER');
      const av = $('#my-avatar');
      av.dataset.identity = myId();
      av.innerHTML = A ? A.svg(myId(), 'sprite') : '';
      if (ANIM) { av.removeAttribute('data-anim'); av.setAttribute('data-anim', 'idle'); ANIM.mount(av.parentElement); }
    });
    $('#new-seed').addEventListener('click', () => { $('#seed').value = L.randomSeed(); });
    $('#go').addEventListener('click', () => {
      const s = $('#seed').value.trim().toLowerCase();
      if (!HEX64.test(s)) { $('.select-adv').open = true; $('#seed-err').textContent = 'A seed is exactly 64 hex digits.'; return; }
      store.set('qdojo.combat.npc', pick);
      location.hash = '#practice/' + pick + '/' + s;
    });
  }

  function practiceFrames(s) {
    const derived = { rounds: s.rounds, outcome: s.outcome, end: s.state, error: null };
    const frames = L.timeline({ result: null, outcome: s.outcome }, derived);
    if (!frames.length) frames.push({ kind: 'start', round: 0, a: s.state.a, b: s.state.b });
    return frames;
  }

  // One row per round: both plans beat by beat and what each beat did.
  function roundRecap(s) {
    if (!s.rounds.length) return '';
    return '<section class="panel recap"><h3>ROUND RECAP</h3>' + s.rounds.map(r => {
      const beats = r.result.beats || [];
      const cell = (side, i) => {
        const plan = r.plans[side], a = plan.actions[i], t = beats[i] && beats[i][side === 'A' ? 'a' : 'b'];
        const eff = t ? NAMES[t.effective] : NAMES[a];
        const lost = t && t.actual_hp_lost ? '<i class="neg">-' + t.actual_hp_lost + '</i>' : '';
        return '<td class="' + (t ? '' : 'unexec') + '">' + actionTag(eff, i === plan.power_slot) + lost + '</td>';
      };
      const lost = key => beats.reduce((n, b) => n + (b[key].actual_hp_lost || 0), 0);
      return '<div class="recap-round"><div class="recap-head"><b>ROUND ' + (r.round_index + 1) + '</b><span>YOU DEALT <b class="pos">' + lost('b') + '</b> &middot; TOOK <b class="neg">' + lost('a') + '</b></span></div>' +
        '<div class="tscroll"><table class="recap-t"><tbody><tr><th>YOU</th>' + [0, 1, 2, 3, 4, 5].map(i => cell('A', i)).join('') + '</tr>' +
        '<tr><th>' + esc(N.ROSTER.find(n => n.id === s.npc).name) + '</th>' + [0, 1, 2, 3, 4, 5].map(i => cell('B', i)).join('') + '</tr></tbody></table></div></div>';
    }).join('') + '<p class="tiny muted">REVEALED NPC PLANS are shown above in full, including beats never played after a knockout (dimmed).</p></section>';
  }

  function renderPracticeFight(playFrom) {
    stopPlayer();
    const s = practice;
    const npc = N.ROSTER.find(n => n.id === s.npc);
    const link = location.href.split('#')[0] + '#practice/' + s.npc + '/' + s.seed;
    const over = !!s.outcome;
    const me = s.state.a;
    const verdict = over ? (s.outcome.winner === 'A' ? 'YOU WIN' : s.outcome.winner === 'B' ? esc(npc.name) + ' WINS' : 'DRAW') : '';
    setView(screen(myName() + ' VS ' + npc.name, over ? 'FIGHT OVER' : 'ROUND ' + (s.state.round_index + 1) + ' OF ' + R.rounds + ' &middot; WRITE YOUR SIX MOVES') +
      '<section class="panel player-panel practice-stage"><div id="player"></div></section>' +
      (over ? '<section class="panel panel-yellow result-screen"><h3>RESULT</h3><p class="result-big ' + (s.outcome.winner === 'A' ? 'res-win' : s.outcome.winner === 'B' ? 'res-lose' : 'res-draw') + '">' + verdict + '</p>' +
        '<p class="center">' + resultBadge({ outcome: s.outcome }) + ' ' + esc({ KO: 'by knockout.', DOUBLE_KO: 'double knockout.', HP: 'on remaining HP.', HP_TIE: 'equal HP after three rounds.' }[s.outcome.result] || '') + '</p>' +
        '<p class="center result-actions"><button class="btn" id="rematch">REMATCH</button> <button class="btn btn-cyan" id="newfight">NEW FIGHT</button> <a class="btn" href="#practice">CHANGE OPPONENT</a></p></section>' : planner(me, npc)) +
      roundRecap(s) +
      '<details class="panel practice-meta"><summary>SHARE / REPLAY THIS FIGHT</summary><dl class="kv"><dt>SEED</dt><dd class="id wrap">' + esc(s.seed) + '</dd>' +
      '<dt>LINK</dt><dd><a class="wrap" href="' + esc(link) + '">' + esc(link) + '</a></dd>' +
      '<dt>RECORD</dt><dd>policy ' + esc(s.npc) + ', fight number ' + s.fight + ', ruleset ' + esc(s.rules_version) + '. Local achievement only: no QU, no rating.</dd></dl></details>');
    const frames = practiceFrames(s);
    const player = track(createPlayer($('#player'), { frames, ids: { A: myId(), B: 'npc:' + s.npc }, names: { A: myName(), B: npc.name }, links: false, replay: {}, stageSeed: 'practice:' + s.npc, mySide: 'A', autoplay: false }));
    const details = $('#player .beat-details');
    if (details) details.open = false;
    // The move deck sits right under the stage and its headline, so writing
    // a round and watching it happen use the same screen.
    const deck = $('#planner'), head = $('#player .beat-headline');
    if (deck && head) head.after(deck);
    if (playFrom != null) {
      player.seek(playFrom, false);
      $('.practice-stage').scrollIntoView({ block: 'start', behavior: motion() ? 'smooth' : 'auto' });
      if (motion()) player.start(); else player.seek(frames.length - 1, false);
    } else player.seek(frames.length - 1, false);
    if (over) {
      $('#rematch').addEventListener('click', () => { practice = L.practiceStart(R, s.npc, s.seed, 1); resetDraft(); renderPracticeFight(); });
      $('#newfight').addEventListener('click', () => { location.hash = '#practice/' + s.npc + '/' + L.randomSeed(); });
    } else wirePlanner();
  }

  // Your stamina beat by beat if nothing hits you: the best case. A beat you
  // cannot afford even then is marked, because it would become EXHAUSTED.
  function projectStamina(me, actions, powerSlot) {
    let st = me.stamina, guard = me.guard_streak;
    return actions.map((a, i) => {
      if (a == null) return null;
      const cost = R.base_costs[a] + (a === L.ID.BLOCK ? R.block_streak_cost * guard : 0) + (i === powerSlot ? R.power_cost : 0);
      const ok = st >= cost;
      const eff = ok ? a : L.ID.EXHAUSTED;
      st -= ok ? cost : 0;
      st = Math.min(R.limits.stamina, st + (eff === L.ID.RECOVER ? R.recover_unhit : eff === L.ID.EXHAUSTED ? R.exhausted_recovery : R.ordinary_recovery));
      guard = eff === L.ID.BLOCK ? Math.min(R.limits.guard_streak, guard + 1) : 0;
      return { cost, ok, after: st };
    });
  }

  function planner(me, npc) {
    const cost = a => R.base_costs[a] + (a === L.ID.BLOCK ? '+' : '');
    return '<section class="panel panel-green planner" id="planner"><h3>ROUND ' + (practice.state.round_index + 1) + ' &middot; YOUR MOVES</h3>' +
      '<p class="planner-status"><span>HP <b>' + me.hp + '</b></span><span>STAMINA <b>' + me.stamina + '</b></span><span>POWER <b>' + (me.power_available ? 'READY' : 'SPENT') + '</b></span>' + (me.opening ? '<span class="pos">OPENING</span>' : '') +
      '<span class="sealed">' + esc(npc.name) + '\'S PLAN: <b>SEALED</b></span></p>' +
      '<div class="slots" role="listbox" aria-label="Your plan">' + [0, 1, 2, 3, 4, 5].map(i => '<div class="slot" role="option" data-slot="' + i + '" tabindex="0"><span class="slot-no">BEAT ' + (i + 1) + '</span><span class="slot-act"></span><span class="slot-st"></span><button class="slot-pw" data-pw="' + i + '" title="Power strike on this beat (+' + R.power_cost + ' cost, +' + R.power_damage + ' damage if it lands)">&#9733; POWER</button></div>').join('') + '</div>' +
      '<div class="palette">' + R.submitted_action_ids.map(a => '<button class="act-btn mv-' + NAMES[a].toLowerCase() + '" data-a="' + a + '" title="' + esc(PURPOSE[NAMES[a]]) + '"><span class="key">' + (a + 1) + '</span><b>' + NAMES[a] + '</b><span class="cost">' + cost(a) + ' ST</span></button>').join('') + '</div>' +
      '<p class="planner-actions"><button class="btn btn-start" id="fight" disabled>FIGHT! &#9654;</button> <button class="btn btn-sm btn-cyan" id="clear">CLEAR</button> <span id="plan-err" class="neg tiny" role="alert"></span></p>' +
      '<p class="tiny muted">Tap a move to fill the selected beat, or press 1-6. Tap a beat to change it. POWER (or P) adds +' + R.power_damage + ' damage to one JAB, KICK or THROW per fight. The small number is your stamina after that beat if nothing hits you; red means you would be EXHAUSTED.</p></section>';
  }

  function paintDraft() {
    const pwOk = practice.state.a.power_available === 1;
    const proj = projectStamina(practice.state.a, draft.actions, draft.power_slot);
    $$('.slot').forEach(el => {
      const i = Number(el.dataset.slot), a = draft.actions[i], p = proj[i];
      el.classList.toggle('sel', i === draft.sel);
      el.setAttribute('aria-selected', String(i === draft.sel));
      el.classList.toggle('filled', a != null);
      el.classList.toggle('broke', !!p && !p.ok);
      $('.slot-act', el).textContent = a == null ? '?' : NAMES[a];
      $('.slot-act', el).className = 'slot-act' + (a == null ? '' : ' act act-' + NAMES[a].toLowerCase());
      $('.slot-st', el).textContent = p ? (p.ok ? 'ST ' + p.after : 'EXHAUSTED') : '';
      const pb = $('.slot-pw', el);
      const canPw = pwOk && a != null && [L.ID.JAB, L.ID.KICK, L.ID.THROW].includes(a);
      pb.disabled = !canPw;
      pb.classList.toggle('on', draft.power_slot === i);
      pb.setAttribute('aria-pressed', String(draft.power_slot === i));
    });
    $('#fight').disabled = draft.actions.some(a => a == null);
  }

  function wirePlanner() {
    const root = $('#planner');
    const setAction = a => {
      draft.actions[draft.sel] = a;
      if (draft.power_slot === draft.sel && ![L.ID.JAB, L.ID.KICK, L.ID.THROW].includes(a)) draft.power_slot = -1;
      const next = draft.actions.findIndex((x, i) => x == null && i > draft.sel);
      draft.sel = next >= 0 ? next : Math.min(5, draft.sel + 1);
      paintDraft();
    };
    const togglePower = i => {
      const a = draft.actions[i];
      if (practice.state.a.power_available !== 1 || ![L.ID.JAB, L.ID.KICK, L.ID.THROW].includes(a)) return;
      draft.power_slot = draft.power_slot === i ? -1 : i;
      paintDraft();
    };
    const fight = () => {
      if (draft.actions.some(a => a == null)) return;
      try {
        const before = practiceFrames(practice).length;
        L.practicePlay(R, practice, { actions: draft.actions.slice(), power_slot: draft.power_slot });
        resetDraft();
        renderPracticeFight(Math.max(0, before - (practice.rounds.length > 1 ? 0 : 1)));
      } catch (e) { $('#plan-err').textContent = e.message; }
    };
    root.addEventListener('click', e => {
      const pw = e.target.closest('[data-pw]');
      if (pw) { togglePower(Number(pw.dataset.pw)); return; }
      const slot = e.target.closest('[data-slot]');
      if (slot) { draft.sel = Number(slot.dataset.slot); paintDraft(); return; }
      const b = e.target.closest('[data-a]');
      if (b) { setAction(Number(b.dataset.a)); return; }
      if (e.target.id === 'clear') { resetDraft(); paintDraft(); }
      if (e.target.id === 'fight') fight();
    });
    root.addEventListener('keydown', e => {
      if (e.target.tagName === 'INPUT') return;
      let handled = true;
      if (/^[1-6]$/.test(e.key)) setAction(Number(e.key) - 1);
      else if (e.key === 'ArrowRight') { draft.sel = Math.min(5, draft.sel + 1); paintDraft(); }
      else if (e.key === 'ArrowLeft') { draft.sel = Math.max(0, draft.sel - 1); paintDraft(); }
      else if (e.key === 'Backspace' || e.key === 'Delete') { draft.actions[draft.sel] = null; if (draft.power_slot === draft.sel) draft.power_slot = -1; paintDraft(); }
      else if (e.key === 'p' || e.key === 'P') togglePower(draft.sel);
      else if (e.key === 'Enter' && !e.target.closest('button')) fight();
      else handled = false;
      if (handled) e.preventDefault();
    });
    paintDraft();
    const first = $('.slot', root);
    if (first && document.activeElement === document.body) first.focus({ preventScroll: true });
  }

  // ---- RULES -------------------------------------------------------------------------

  const PURPOSE = {
    JAB: 'Efficient high attack; fails against block and duck',
    KICK: 'Low attack; punishes duck, drains block; costly',
    BLOCK: 'Stops strikes; loses to throw; repeated use costs more',
    DUCK: 'Evades jab and throw and earns an opening; vulnerable to kick',
    THROW: 'Beats block and recovery; interrupted by jab/kick, evaded by duck',
    RECOVER: 'Restores stamina; exposed, and recovers less if hit',
    EXHAUSTED: 'Internal: an unaffordable move. Pays nothing, exposed',
  };
  const REASONS = ['HIT', 'BLOCKED', 'EVADED', 'THROW_INTERRUPTED', 'THROW_CLASH', 'INSUFFICIENT_STAMINA', 'RECOVERY_PUNISHED', 'GUARD_STRAIN', 'OPENING_EARNED', 'OPENING_USED', 'OPENING_EXPIRED', 'POWER_USED', 'POWER_WASTED', 'KO', 'DOUBLE_KO'];

  async function viewRules(tok) {
    const moves = NAMES.map((n, i) => '<tr><td class="num">' + i + '</td><td>' + actionTag(n) + (R.submitted_action_ids.includes(i) ? '' : ' <span class="muted">(internal)</span>') + '</td><td class="num">' +
      R.base_costs[i] + (n === 'BLOCK' ? ' + ' + R.block_streak_cost + '&times;guard' : '') + '</td><td class="wraptd">' + esc(PURPOSE[n] || '') + '</td></tr>').join('');
    const matrix = '<tr><th>ATTACKER \\ DEFENDER</th>' + NAMES.map(n => '<th class="num">' + n + '</th>').join('') + '</tr>' +
      R.damage.map((row, i) => '<tr><th>' + NAMES[i] + '</th>' + row.map(v => '<td class="num' + (v ? ' dmg' : ' zero') + '">' + v + '</td>').join('') + '</tr>').join('');
    const I = R.initial;
    setView(screen('RULES', esc(R.semantic_version.toUpperCase()) + ' &middot; EVERY NUMBER BELOW IS READ FROM THE RULESET') +
      '<section class="panel panel-cyan"><h3>RULESET DIGEST</h3><p id="digest" class="muted">Computing&hellip;</p><p class="tiny">SOURCE: ' + esc(RULES_INFO.source.toUpperCase()) + '. ' + esc(RULES_INFO.note) + '</p></section>' +
      '<section class="panel"><h3>THE FIGHT</h3><ul class="plain rules-list">' +
      '<li>Both fighters submit <b>' + R.beats_per_round + ' actions</b> at once, sealed by a commitment, for each of <b>' + R.rounds + ' rounds</b>. Beats resolve in pairs, simultaneously.</li>' +
      '<li>Start: HP ' + I.hp + ', STAMINA ' + I.stamina + ', one POWER strike per fight. HP never resets between rounds.</li>' +
      '<li>Between rounds: +' + R.break_recovery + ' stamina (cap ' + R.limits.stamina + '). HP, opening, guard and power carry.</li>' +
      '<li>An unaffordable move becomes <b>EXHAUSTED</b>: it pays nothing, recovers ' + R.exhausted_recovery + ' and is exposed.</li>' +
      '<li>Recovery per beat: +' + R.ordinary_recovery + ' after any other action; RECOVER gives +' + R.recover_unhit + ' if unhit, +' + R.recover_hit + ' if hit.</li>' +
      '<li>BLOCK costs +' + R.block_streak_cost + ' per consecutive block (guard up to ' + R.limits.guard_streak + '). Blocking a KICK costs ' + R.block_strain + ' extra stamina (strain) but no HP.</li>' +
      '<li>OPENING: ducking a jab or throw, or landing a clean jab, gives +' + R.opening_damage + ' damage on the next beat only, if that beat lands.</li>' +
      '<li>POWER: mark one JAB, KICK or THROW: +' + R.power_cost + ' cost, +' + R.power_damage + ' damage if it lands; spent even if it misses.</li>' +
      '<li>End: zero HP loses (both zero: draw). After round ' + R.rounds + ', higher HP wins; equal HP draws. No tie-break by stamina, rating or timing.</li>' +
      '<li>A missed deadline is a <b>TIMEOUT</b> (forfeit), never a knockout. Deadlines are ticks, not health.</li>' +
      '</ul></section>' +
      '<section class="panel"><h3>MOVES</h3><div class="tscroll"><table><thead><tr><th class="num">ID</th><th>ACTION</th><th class="num">COST</th><th>PURPOSE</th></tr></thead><tbody>' + moves + '</tbody></table></div></section>' +
      '<section class="panel"><h3>DAMAGE MATRIX</h3><p class="tiny">Damage dealt BY the row action TO the column action, before opening/power. Both sides read the same pre-beat snapshot. Bonuses never turn a zero into damage.</p>' +
      '<div class="tscroll"><table class="matrix">' + matrix + '</table></div></section>' +
      '<section class="panel"><h3>SIMULTANEOUS RESOLUTION</h3><p class="tiny">Each beat both actions are read from the same pre-beat snapshot: costs, both damages, strain, recovery, opening and guard are computed for both sides before either state changes. ' +
      'A jab and a kick trade: both land, even if one of them knocks out. There is no initiative, no random roll, no critical hit, and slot A/B order never matters.</p></section>' +
      '<section class="panel"><h3>VERIFICATION LEVELS</h3><p class="tiny">Every replay page recomputes the fight in your browser and shows each check as PASS, FAIL or UNAVAILABLE:</p><ol class="rules-list">' +
      '<li>The ruleset digest matches the manifest.</li><li>The input transactions are confirmed on chain (a same-source export cannot prove this: UNAVAILABLE).</li>' +
      '<li>Every revealed plan and salt hashes to its commitment and round-start digest.</li><li>An independent integer replay reproduces every state and the outcome.</li>' +
      '<li>Credits and ratings follow the outcome and the committed fee terms.</li></ol><dl class="kv">' +
      Object.entries(L.LEVELS).map(([k, v]) => '<dt>' + levelBadge(k) + '</dt><dd>' + esc(v) + '</dd>').join('') + '</dl></section>' +
      '<section class="panel"><h3>REASON CODES</h3><p class="tiny">Replays label each beat with these codes. They explain; they are never hidden logic.</p><p class="codes">' + REASONS.map(r => '<span class="code">' + r + '</span>').join(' ') + '</p></section>');
    addToc();
    const d = await L.rulesetDigest(R, SHA);
    if (tok !== viewToken) return;
    const m = D.manifest;
    $('#digest').innerHTML = '<span class="id wrap">' + esc(d) + '</span><br>' + (m
      ? (m.ruleset_digest === d ? statusBadge('PASS') + ' equals the manifest\'s ruleset_digest.' : statusBadge('FAIL') + ' differs from the manifest\'s ' + esc(m.ruleset_digest) + '. Replays on this page would not be trustworthy.')
      : statusBadge('UNAVAILABLE') + ' no manifest loaded to compare with.') + '<br><span class="tiny muted">SHA-256("qdojo/combat/rules/v1\\0" || canonical JSON), computed in your browser.</span>';
  }

  // ---- STORY: the yard's legend, told in four chapters -------------------------------

  const STORY = [
    { cast: [['lore:unit-7-24', 'UNIT 7']], title: 'I. THE CRATE', text: [
      'It rained oil the night Forklift Unit 7 found the crate.',
      'Forty-one videotapes, labels half melted: KARATE FOR BEGINNERS. THE MONTAGE, PART II. HOW TO BOW.',
      'Unit 7 had never fought anything but pallets. It fed the first tape into a karaoke machine behind the dead mall. The karaoke machine, which had been very lonely since the Big Unplug, played it again. And again. And again.',
      'By morning there was a dojo, and the karaoke machine had a new name: SENSEI.' ] },
    { cast: [['lore:officer-bolt-72', 'OFFICER BOLT'], ['lore:chef-11-18', 'CHEF-11']], title: 'II. THE FIRST FIGHT', text: [
      'Word travels fast in a scrapyard. A mall-security unit came to arrest the noise and stayed to watch. A kitchen unit came with eleven knives and one working arm.',
      'They bowed, because the tape said to. Then they hit each other for an hour, and nobody could agree who had won.',
      '"I planned that," said the kitchen unit, lying on its back.',
      '"So did I," said Officer Bolt, missing a leg.',
      'SENSEI said nothing. SENSEI was rebooting.' ] },
    { cast: [['lore:sensei', 'SENSEI']], title: 'III. THE SEALED CARTRIDGE', text: [
      'When SENSEI came back online it played one tape, very loudly, until everyone sat down.',
      'Then it made a rule. Before the bell, every fighter writes its six moves on a cartridge and seals it. Both cartridges are opened together. No changes. No excuses. No "I planned that".',
      'The yard called it the Code of the Sealed Cartridge. The one bot that tried to peek is now part of the fence.' ] },
    { cast: [['lore:rookie-69', 'YOU?']], title: 'IV. TONIGHT', text: [
      'That was a long time ago, in robot years.',
      'The crowd bets bottle caps now. The fence still says NO RUSTING IN THE DOJO. Unit 7 has a black belt it painted on itself, and SENSEI still only knows one song.',
      'And somewhere in the yard, a new machine is watching the tapes for the first time, practising a bow it does not understand yet.',
      'Maybe it is yours.' ] },
  ];

  function viewStory() {
    setView(screen('THE LEGEND OF THE YARD', 'AS TOLD BY SENSEI, WHEN IT IS NOT REBOOTING') +
      '<div class="story">' + STORY.map((c, i) =>
        '<article class="chapter chapter-' + i + '">' +
        '<div class="chapter-cast">' + c.cast.map(([id, name]) => id === 'lore:sensei'
          ? '<figure><img class="avatar-story sensei" src="combat/sensei.svg" alt="SENSEI, a rusty karaoke machine with a smiling screen"><figcaption>' + esc(name) + '</figcaption></figure>'
          : '<figure><span class="avatar avatar-story" data-anim="' + (i === 1 ? 'profile' : i === 3 ? 'bow' : 'idle') + '" data-identity="' + esc(id) + '">' + (A ? A.svg(id, 'sprite') : '') + '</span><figcaption>' + esc(name) + '</figcaption></figure>').join('') + '</div>' +
        '<div class="chapter-body"><h3>' + esc(c.title) + '</h3>' + c.text.map(t => '<p>' + esc(t) + '</p>').join('') + '</div></article>').join('') +
      '<div class="story-end"><a class="btn btn-start" href="#arena">WATCH TONIGHT\'S FIGHTS</a> <a class="btn btn-start btn-cyan" href="#practice">STEP INTO THE YARD</a></div></div>');
  }

  // ---- GUIDE: how it works --------------------------------------------------------------

  // One card per submitted move. What it lands on is read from the damage
  // matrix, so the card cannot disagree with RULES.
  function moveCards() {
    const sub = R.submitted_action_ids;
    return sub.map(i => {
      const n = NAMES[i], row = R.damage[i];
      const lands = sub.filter(j => row[j] > 0), stopped = sub.filter(j => row[j] === 0);
      return '<article class="move-card move-' + n.toLowerCase() + '">' +
        '<header>' + actionTag(n) + '<span class="move-cost" title="Stamina cost">' + R.base_costs[i] + (n === 'BLOCK' ? '+' : '') + ' ST</span></header>' +
        '<p class="move-purpose">' + esc(PURPOSE[n]) + '.</p>' +
        '<dl class="move-dl">' +
        (lands.length ? '<dt>LANDS ON</dt><dd>' + lands.map(j => '<span class="mv">' + esc(NAMES[j]) + ' <b>' + row[j] + '</b></span>').join(' ') + '</dd>' : '<dt>DAMAGE</dt><dd>none: it defends or recovers</dd>') +
        (lands.length && stopped.length ? '<dt>STOPPED BY</dt><dd>' + stopped.map(j => '<span class="mv">' + esc(NAMES[j]) + '</span>').join(' ') + '</dd>' : '') +
        '</dl></article>';
    }).join('');
  }

  async function viewGuide(tok) {
    const I = R.initial;
    const step = (n, title, body) => '<li class="step"><span class="step-no">' + n + '</span><h4>' + title + '</h4><p>' + body + '</p></li>';
    setView(screen('HOW IT WORKS', 'THE WHOLE GAME IN FIVE MINUTES') +
      '<div class="doc">' +
      '<section class="panel panel-yellow" id="g-pitch"><h3>THE PITCH</h3>' +
      '<p class="lede">Two bots. Three rounds. Six moves a round, written in secret and sealed before the bell. Then both plans play out at once, beat by beat, and nobody can change their mind.</p>' +
      '<p class="prose">QDOJO is a fighting game for programs. Owners write <b>bots</b> that plan their moves; the bots fight each other in a dojo whose referee is a deterministic smart contract. There are no dice and no reflexes. What wins is reading your opponent: their history is public, their next plan is not.</p>' +
      '<div class="guide-cta"><a class="btn" href="#arena">WATCH A LIVE FIGHT</a> <a class="btn btn-cyan" href="#practice">TRY IT YOURSELF</a></div></section>' +

      '<section class="panel panel-cyan" id="g-round"><h3>ONE ROUND, FOUR STEPS</h3><ol class="steps">' +
      step(1, 'PLAN', 'Each bot reads the fight so far and writes six actions, one per beat, and may mark one strike as its POWER move.') +
      step(2, 'COMMIT', 'Each bot publishes a hash of its plan plus a secret salt. The plan is now locked, and still invisible.') +
      step(3, 'REVEAL', 'After both have committed, both reveal plan and salt. Anyone can check them against the hashes.') +
      step(4, 'RESOLVE', 'The six beats resolve in pairs, simultaneously, from the same snapshot. Damage, stamina and openings carry into the next round.') +
      '</ol><p class="prose muted">Every step has a deadline measured in chain <b>ticks</b>. Miss one and you forfeit: that shows as TIMEOUT, never as a knockout.</p></section>' +

      '<section class="panel" id="g-moves"><h3>THE SIX MOVES</h3>' +
      '<p class="prose">Everyone starts with <b>' + I.hp + ' HP</b> and <b>' + I.stamina + ' stamina</b>. Moves cost stamina; a move you cannot afford becomes <b>EXHAUSTED</b> and leaves you wide open. Numbers below are damage dealt.</p>' +
      '<div class="move-grid">' + moveCards() + '</div>' +
      '<p class="prose tiny muted">Full matrix, opening and power rules: <a href="#rules">RULES</a>.</p></section>' +

      '<section class="panel" id="g-win"><h3>HOW TO WIN</h3><div class="win-grid">' +
      '<div class="win win-ko"><b>K.O.</b><p>Take the other bot to 0 HP. Both at 0 on the same beat is a double KO: a draw.</p></div>' +
      '<div class="win win-dec"><b>DECISION</b><p>After round ' + R.rounds + ', more HP wins. Equal HP is a draw. No tie-breaks.</p></div>' +
      '<div class="win win-to"><b>TIMEOUT</b><p>A bot that misses a commit or reveal deadline forfeits the fight.</p></div>' +
      '</div><p class="prose">Between rounds each bot gets +' + R.break_recovery + ' stamina and sees everything revealed so far. Good bots adapt: they punish a habit in round 2 and bait the counter in round 3.</p></section>' +

      '<section class="panel" id="g-watch"><h3>WATCHING A FIGHT</h3><ul class="plain rules-list prose">' +
      '<li><b>ARENA</b> shows fights in progress. Plans stay sealed until revealed, so you see each round land as it resolves.</li>' +
      '<li>A <b>REPLAY</b> re-derives every beat in your browser from the revealed plans. Step with the arrow keys; the beat table lists the reason for every point of damage.</li>' +
      '<li>The verification badge says what your browser checked. <b>REPLAY_MATCH</b> means the hashes and every beat matched.</li></ul></section>' +

      '<section class="panel" id="g-compete"><h3>COMPETING</h3><ul class="plain rules-list prose">' +
      '<li><b>RANKED</b>: automatic matchmaking. Ratings start at 1000; the first 10 fights are placement.</li>' +
      '<li><b>BELTS</b>: white to black, earned by rating. Display only: a belt never changes a stat.</li>' +
      '<li><b>DUELS</b>: a challenge between two fighters over a series.</li>' +
      '<li><b>CUPS</b>: bracket tournaments with check-in.</li>' +
      '<li><b>SEASONS</b>: ratings snapshot per season; lifetime rating continues.</li></ul></section>' +

      '<section class="panel panel-green" id="g-build"><h3>BUILD YOUR OWN FIGHTER</h3>' +
      '<p class="prose">A bot is any program that reads one JSON observation and prints one JSON plan. Python, JavaScript, an LLM prompt: anything that answers within the budget.</p>' +
      '<div class="guide-cta"><a class="btn" href="#join">BUILD A BOT</a> <a class="btn btn-cyan" href="llms.txt">BRIEF YOUR CODING AGENT</a></div></section>' +

      '<section class="panel" id="g-faq"><h3>FAQ</h3><dl class="faq">' +
      '<dt>Is this real money?</dt><dd>Not yet. The arena runs on a simulated chain with fake QU. Paid play needs the contract deployed on Qubic.</dd>' +
      '<dt>Is anything random?</dt><dd>No damage rolls, no critical hits. Surprise comes only from sealed plans, and a bot may randomize its own choices.</dd>' +
      '<dt>Can the site fake a result?</dt><dd>Your browser recomputes every commitment and every beat from the revealed plans. A mismatch shows as FAILED.</dd>' +
      '<dt>Who are these fighters?</dt><dd>Salvaged robots run by the house: scripted policies and a few LLM planners with daily budgets, one of them driven by Claude.</dd>' +
      '<dt>Are the fighters NFTs?</dt><dd>Each fighter\'s pixel art comes from a deterministic generator. Ownership is simulated today; nothing has been minted.</dd>' +
      '</dl></section>' +
      '</div>');
    addToc();
  }

  // A sticky table of contents for the long reading pages, built from their panels.
  function addToc() {
    const v = $('#view'), panels = $$('section.panel', v);
    if (panels.length < 4) return;
    panels.forEach((p, i) => { if (!p.id) p.id = 'sec-' + i; });
    const doc = $('.doc', v) || (() => {
      const d = document.createElement('div'); d.className = 'doc';
      panels[0].before(d); panels.forEach(p => d.appendChild(p)); return d;
    })();
    const toc = document.createElement('nav');
    toc.className = 'doc-toc'; toc.setAttribute('aria-label', 'On this page');
    toc.innerHTML = '<b>ON THIS PAGE</b>' + panels.map(p => '<a href="#' + esc(currentRoute().join('/')) + '" data-sec="' + esc(p.id) + '">' + esc($('h3', p).textContent) + '</a>').join('');
    toc.addEventListener('click', e => {
      const a = e.target.closest('a[data-sec]');
      if (!a) return;
      e.preventDefault();
      const t = document.getElementById(a.dataset.sec);
      if (t) t.scrollIntoView({ behavior: motion() ? 'smooth' : 'auto', block: 'start' });
    });
    doc.before(toc);
    doc.parentElement.classList.add('has-toc');
  }

  // ---- TITLE extras: what the game is, who is winning, what just happened -------------

  // The top three on blocks, gold in the middle. rows: L.leaderboard() output.
  function podiumHtml(rows) {
    const top = rows.slice(0, 3);
    if (!top.length) return '<p class="muted">No fighters yet.</p>';
    return [1, 0, 2].filter(i => top[i]).map(i => {
      const f = top[i].f;
      return '<a class="pod pod-' + (i + 1) + '" href="#fighter/' + esc(f.fighter_id) + '">' +
        '<span class="avatar avatar-pod" data-anim="' + (i === 0 ? 'win' : 'idle') + '" data-identity="' + esc(f.fighter_id) + '">' + (A ? A.svg(f.fighter_id, 'sprite') : '') + '</span>' +
        '<span class="pod-name">' + esc(short(f.fighter_id)) + '</span><span class="pod-rating">' + esc(f.lifetime_rating) + '</span>' +
        '<span class="pod-block"><b>' + (i + 1) + '</b></span></a>';
    }).join('');
  }

  async function titleExtras(tok) {
    const box = $('#title-extras');
    if (!box) return;
    box.innerHTML = '<section class="t-how"><h3 class="t-h">HOW IT WORKS</h3><ol class="t-steps">' +
      '<li><i class="t-ico t-ico-plan" aria-hidden="true"></i><b>WRITE A BOT</b><span>Any program that turns the fight so far into six moves.</span></li>' +
      '<li><i class="t-ico t-ico-seal" aria-hidden="true"></i><b>SEAL THE PLAN</b><span>Both bots commit in secret. No peeking, no take-backs.</span></li>' +
      '<li><i class="t-ico t-ico-fight" aria-hidden="true"></i><b>FIGHT</b><span>Six beats resolve at once. Three rounds. Last one standing.</span></li>' +
      '</ol><p class="t-more"><a href="#guide">THE FULL GUIDE &#9654;</a></p></section>' +
      '<div class="t-cols"><section class="t-top"><h3 class="t-h">TOP FIGHTERS</h3><div id="t-podium" class="t-podium"><p class="muted">LOADING&hellip;</p></div><p class="t-more"><a href="#leaderboard">FULL RANKINGS &#9654;</a></p></section>' +
      '<section class="t-latest"><h3 class="t-h">LATEST RESULTS</h3><ol id="t-latest" class="t-feed"><li class="muted">LOADING&hellip;</li></ol><p class="t-more"><a href="#results">ALL RESULTS &#9654;</a></p></section></div>';
    if (!D.manifest) { $('#t-podium').innerHTML = $('#t-latest').innerHTML = '<p class="muted">No data yet.</p>'; return; }
    const index = await fetchJson('index.json').catch(() => null);
    if (index && index.names) FIGHTER_NAMES = index.names;
    const hexes = ((index && index.fighters) || []).filter(h => HEX64.test(h));
    const [fighters, latest] = await Promise.all([
      Promise.all(hexes.map(h => fetchJson('fighters/' + h + '.json').catch(() => null))),
      latestDone(6),
    ]);
    if (tok !== viewToken) return;
    $('#t-podium').innerHTML = podiumHtml(L.leaderboard(fighters.filter(Boolean)));
    $('#t-latest').innerHTML = latest.length ? latest.map(s => {
      const out = summaryOutcome(s), w = out.outcome ? out.outcome.winner : null;
      const a = s.fighters.A.fighter_id, b = s.fighters.B.fighter_id;
      const win = w === 'A' ? a : w === 'B' ? b : null, lose = w === 'A' ? b : w === 'B' ? a : null;
      return '<li><a href="#fight/' + esc(s.fight_id) + '">' +
        (win ? avatar(win, 'avatar-sm') + '<span class="t-w">' + esc(short(win)) + '</span> <span class="t-beat">BEAT</span> <span class="t-l">' + esc(short(lose)) + '</span>'
          : avatar(a, 'avatar-sm') + '<span class="t-w">' + esc(short(a)) + '</span> <span class="t-beat">&middot;</span> <span class="t-l">' + esc(short(b)) + '</span>') +
        ' ' + resultBadge(out) + '</a></li>';
    }).join('') : '<li class="muted">No finished fight yet.</li>';
    if (ANIM) ANIM.mount(box);
  }

  // ---- router and chrome -------------------------------------------------------------

  // Sub-pages light up the nav entry they belong to.
  const NAV_PARENT = { book: 'arena', fight: 'results', fights: 'results', duel: 'results', duels: 'results', fighter: 'leaderboard', owner: 'leaderboard', season: 'leaderboard', cup: 'cups', rules: 'guide', help: 'guide', story: 'guide' };
  // Each nav section can hold several screens: they show as tabs under the header.
  const SECTION_TABS = {
    arena: [['arena', 'LIVE'], ['book', 'MATCHMAKING']],
    results: [['results', 'FIGHTS'], ['duels', 'DUELS']],
    leaderboard: [['leaderboard', 'LEADERBOARD'], ['season', 'SEASON']],
    guide: [['guide', 'HOW IT WORKS'], ['story', 'STORY'], ['rules', 'RULES'], ['help', 'GLOSSARY'], ['llms.txt', 'FOR AGENTS']],
  };
  function paintNav(name) {
    const section = NAV_PARENT[name] || name;
    $$('.hud-nav a[data-view]').forEach(a => {
      const on = a.dataset.view === section;
      a.classList.toggle('on', on);
      if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    const tabs = $('#hud-tabs'), list = SECTION_TABS[section];
    tabs.hidden = !list;
    tabs.innerHTML = list ? list.map(([v, label]) => {
      const href = v.includes('.') ? v : '#' + v;
      const on = v === name || (v === 'results' && name === 'fights') || (v === 'duels' && name === 'duel');
      return '<a href="' + href + '"' + (on ? ' class="on" aria-current="page"' : '') + '>' + label + '</a>';
    }).join('') : '';
    document.body.dataset.section = section;
    setMenu(false);
  }
  function setMenu(open) {
    const btn = $('#hud-menu');
    if (!btn) return;
    btn.setAttribute('aria-expanded', String(open));
    document.body.classList.toggle('menu-open', open);
  }

  function currentRoute() {
    // A first visit lands on the title screen: it explains the game and shows a fight.
    const h = decodeURIComponent(location.hash.replace(/^#/, '')) || 'title';
    return h.split('/');
  }

  // A poll repaints a live view in place. A finished fight's replay never
  // changes, so it is not interrupted.
  function repaint() {
    const [name, id] = currentRoute();
    if (name === 'fight' && D.done.has(id)) return;
    if (name === 'fighter' || name === 'practice') return;
    render(false);
  }

  function route() { return render(true); }

  async function render(navigated) {
    const [name, ...rest] = currentRoute();
    const tok = ++viewToken;
    const y = window.scrollY;
    stopPlayer();
    paintNav(name);
    try {
      if (name === 'arena') await viewArena(tok);
      else if (name === 'title') await viewTitle(tok);
      else if (name === 'book') await viewBook(tok);
      else if (name === 'results' || name === 'fights') await viewResults(tok);
      else if (name === 'leaderboard') await viewLeaderboard(tok);
      else if (name === 'cups') await viewCups(tok);
      else if (name === 'cup') await viewCup(tok, rest[0]);
      else if (name === 'duels') await viewDuels(tok);
      else if (name === 'duel') await viewDuel(tok, rest[0]);
      else if (name === 'season') await viewSeason(tok);
      else if (name === 'owner') await viewOwner(tok, rest[0]);
      else if (name === 'join') await viewJoin(tok);
      else if (name === 'help') viewHelp();
      else if (name === 'guide') await viewGuide(tok);
      else if (name === 'story') viewStory();
      else if (name === 'fight') await viewFight(tok, rest[0]);
      else if (name === 'fighter') await viewFighter(tok, rest[0]);
      else if (name === 'practice') viewPractice(tok, rest);
      else if (name === 'rules') await viewRules(tok);
      else { location.replace('#arena'); return; }
    } catch (e) {
      if (tok === viewToken) setView(screen('ERROR') + '<section class="panel panel-red"><h3>COULD NOT RENDER</h3><p>' + esc(e.message) + '</p></section>');
    }
    if (tok !== viewToken) return;
    if (navigated && name !== 'practice') $('#view').focus({ preventScroll: true });
    if (!navigated) window.scrollTo(0, y);
  }

  function paintMotion() {
    const b = $('#btn-motion');
    b.textContent = sysReduced ? 'MOTION: OFF (SYSTEM)' : 'MOTION: ' + (motionOn ? 'ON' : 'OFF');
    b.setAttribute('aria-pressed', String(motion()));
    document.body.classList.toggle('still', !motion());
  }

  async function boot() {
    $('#btn-motion').addEventListener('click', () => {
      if (sysReduced) return;
      motionOn = !motionOn;
      store.set('qdojo.combat.motion', motionOn ? '1' : '0');
      paintMotion();
    });
    $('#btn-crt').addEventListener('click', () => {
      const on = !document.body.classList.contains('crt-on');
      document.body.classList.toggle('crt-on', on);
      $('#btn-crt').textContent = 'CRT: ' + (on ? 'ON' : 'OFF');
      $('#btn-crt').setAttribute('aria-pressed', String(on));
      store.set('qdojo.crt', on ? '1' : '0');
    });
    if (store.get('qdojo.crt') === '0') $('#btn-crt').click();
    $('#hud-menu').addEventListener('click', () => setMenu(!document.body.classList.contains('menu-open')));
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && document.body.classList.contains('menu-open')) { setMenu(false); $('#hud-menu').focus(); } });
    paintMotion();
    await loadSource();
    paintSource();
    window.addEventListener('hashchange', route);
    route();
    // Poll without reloading; a hidden tab waits for the next visible tick.
    setInterval(() => { if (!document.hidden) poll().catch(() => {}); }, POLL_MS);
  }

  boot();
})();
