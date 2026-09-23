/* QDOJO combat spectator and owner page (combat.html).
 *
 * Views, by hash: #book, #fights, #fight/<id>, #fighter/<hex>, #practice,
 * #practice/<npc>/<seed>, #rules.
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

  const D = { base: null, sample: false, manifest: null, error: null, cache: new Map() };
  let viewToken = 0;
  let player = null;
  let practice = null;

  // ---- data --------------------------------------------------------------------

  function fetchJson(rel) {
    const key = D.base + rel;
    if (!D.cache.has(key)) {
      D.cache.set(key, fetch(key, { cache: 'no-cache' }).then(r => {
        if (!r.ok) throw new Error(rel + ': HTTP ' + r.status);
        return r.json();
      }));
      D.cache.get(key).catch(() => D.cache.delete(key));
    }
    return D.cache.get(key);
  }

  async function loadSource() {
    for (const src of SOURCES) {
      try {
        const r = await fetch(src.base + 'manifest.json', { cache: 'no-cache' });
        if (!r.ok) continue;
        const m = await r.json();
        // Unknown major schema versions fail closed.
        if (m.schema !== 'qdojo.combat.manifest.v1') { D.error = src.base + 'manifest.json has unknown schema ' + m.schema; continue; }
        D.base = src.base; D.sample = src.sample; D.manifest = m;
        const art = HEX64.test(m.ruleset_digest || '') ? await fetchJson('rulesets/' + m.ruleset_digest + '.json').catch(() => null) : null;
        const pick = await L.chooseRuleset({ exported: art, embedded: window.QDojoRuleset, manifestDigest: m.ruleset_digest, sha256: SHA });
        R = pick.rules;
        RULES_INFO = pick;
        return;
      } catch (e) { /* try the next source */ }
    }
    D.error = D.error || 'No combat export could be fetched (tried ' + SOURCES.map(s => s.base).join(', ') + ').';
  }

  function paintSource() {
    const pill = $('#hud-source');
    if (D.manifest && D.sample) {
      pill.className = 'pill pill-sample';
      pill.textContent = 'SAMPLE';
      pill.title = 'Sample export from a local devnet: fake QU, synthetic fighters, NPC-driven bots. Not a deployment.';
    } else if (D.manifest) {
      pill.className = 'pill pill-live';
      pill.textContent = 'EXPORT';
      pill.title = 'Combat export at ' + D.base + '. Same-source data: chain inclusion is not proven by this page.';
    } else {
      pill.className = 'pill pill-lost';
      pill.textContent = 'NO DATA';
      pill.title = D.error || '';
    }
    $('#hud-tick').textContent = D.manifest ? D.manifest.generated_tick : '—';
    $('#hud-rules').textContent = (R.semantic_version || 'combat-v1').toUpperCase();
    $('#foot-data').innerHTML = D.manifest
      ? 'DATA ' + esc(D.base) + (D.sample ? ' <b class="sample-note">SAMPLE: fake QU, synthetic fighters</b>' : '') +
        ' &middot; NETWORK <span class="id">' + esc(short(D.manifest.network_id)) + '</span> &middot; CONTRACT <span class="id">' + esc(short(D.manifest.contract_id)) + '</span>' +
        ' &middot; Every replay is re-derived in your browser; rendering never changes a result.'
      : esc(D.error || 'No data. PRACTICE and RULES still work offline.');
  }

  // ---- small renderers -----------------------------------------------------------

  const short = hex => String(hex || '').slice(0, 8);
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
    setView(screen('NOT FOUND') + '<section class="panel panel-red"><h3>NO RECORD</h3><p>' + esc(what) + '</p><p><a href="#fights">BACK TO FIGHTS</a></p></section>');
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
        : '<p class="muted">No fight in progress at this snapshot. <a href="#fights">Completed fights &#9654;</a></p>') +
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

  // ---- FIGHTS ----------------------------------------------------------------------

  async function viewFights(tok) {
    if (needData()) return;
    const index = await fetchJson('index.json');
    const ids = (index.fights || []).filter(id => DEC.test(id));
    const sums = await Promise.all(ids.map(id => fetchJson('fights/' + id + '.json').catch(() => null)));
    if (tok !== viewToken) return;
    const all = sums.filter(Boolean).sort((a, b) => Number(b.fight_id) - Number(a.fight_id));
    const active = all.filter(s => s.phase !== 'DONE'), done = all.filter(s => s.phase === 'DONE');
    const row = s => {
      const out = summaryOutcome(s);
      return '<tr>' +
        '<td class="num"><a href="#fight/' + esc(s.fight_id) + '">#' + esc(s.fight_id) + '</a></td>' +
        '<td>' + esc(String(s.mode || '').toUpperCase()) + '</td>' +
        '<td>' + fighterLink(s.fighters.A.fighter_id) + '</td><td class="vs">VS</td><td>' + fighterLink(s.fighters.B.fighter_id) + '</td>' +
        (s.phase === 'DONE'
          ? '<td>' + resultBadge(out) + '</td><td>' + (out.outcome && out.outcome.winner ? esc(out.outcome.winner) : '<span class="muted">none</span>') + '</td><td class="num">' + esc(s.result && s.result.tick) + '</td>'
          : '<td><span class="rbadge rbadge-open">' + esc(s.phase) + '</span></td><td>R' + (s.round_index + 1) + '</td><td class="num">commit &le; ' + esc(s.commit_last) + '<br>reveal &le; ' + esc(s.reveal_last) + '</td>') +
        '<td><a class="btn btn-sm" href="#fight/' + esc(s.fight_id) + '">' + (s.phase === 'DONE' ? 'REPLAY' : 'WATCH') + '</a></td></tr>';
    };
    const table = (list, head) => '<div class="tscroll"><table class="fights-table"><thead><tr><th class="num">FIGHT</th><th>MODE</th><th>A</th><th></th><th>B</th>' + head + '<th></th></tr></thead><tbody>' + list.map(row).join('') + '</tbody></table></div>';
    setView(screen('FIGHTS', esc(all.length) + ' FIGHTS IN THIS EXPORT &middot; SNAPSHOT TICK ' + esc(index.generated_tick)) +
      '<section class="panel panel-cyan"><h3>ACTIVE (' + active.length + ')</h3>' +
      (active.length ? table(active, '<th>PHASE</th><th>ROUND</th><th class="num">DEADLINE TICKS</th>') + '<p class="tiny muted">Deadlines are ticks, not health. Live plans stay sealed until their reveal.</p>'
        : '<p class="muted">No fight in progress at this snapshot.</p>') + '</section>' +
      '<section class="panel"><h3>COMPLETED (' + done.length + ')</h3>' + (done.length ? table(done, '<th>RESULT</th><th>WINNER</th><th class="num">END TICK</th>') : '<p class="muted">None yet.</p>') + '</section>');
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
      return '<div class="corner corner-' + s + '" data-side="' + s + '">' + head +
        '<div class="fighter-box"><span class="avatar avatar-stage" data-anim="manual" data-identity="' + esc(id) + '">' + (A ? A.svg(id, 'sprite') : '') + '</span><span class="pop" aria-hidden="true"></span></div>' +
        cbar('hp', 'HP') + cbar('st', 'STAMINA') +
        '<div class="flags"><span class="flag flag-power"></span><span class="flag flag-opening">OPENING</span><span class="flag flag-guard"></span></div>' +
        '<div class="side-now"></div></div>';
    };
    const rows = frames.map((f, i) => {
      const cls = 'fr fr-' + f.kind;
      if (f.kind === 'beat') {
        const a = f.trace.A, b = f.trace.B;
        const cell = (t, o) => '<td>' + actionTag(NAMES[t.effective], t.power, NAMES[t.intended]) + '</td><td class="num">' + (t.actual_hp_lost ? '<span class="neg">-' + t.actual_hp_lost + '</span> ' : '') + t.after.hp + '</td><td class="num">' + t.after.stamina + (t.strain ? ' <span class="strain">(-' + t.strain + ')</span>' : '') + '</td>';
        return '<tr class="' + cls + '" data-i="' + i + '" tabindex="-1"><td>' + (f.round + 1) + '</td><td>' + (f.beat + 1) + '</td>' + cell(a, b) + cell(b, a) + '<td class="reasons">' + esc(a.reasons.join(' ')) + ' / ' + esc(b.reasons.join(' ')) + '</td></tr>';
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
      '<div class="stage" aria-describedby="stage-help">' + corner('A') +
      '<div class="center"><div class="round-no"></div><div class="beat-no"></div><div class="center-note"></div></div>' + corner('B') + '</div>' +
      '<div class="controls" role="group" aria-label="Replay controls">' +
      '<button class="chip" data-act="first" title="First (Home)">|&#9664;</button>' +
      '<button class="chip" data-act="prev" title="Previous beat (Left)">&#9664;</button>' +
      '<button class="chip play" data-act="play" title="Play / pause (Space)">PLAY</button>' +
      '<button class="chip" data-act="next" title="Next beat (Right)">&#9654;</button>' +
      '<button class="chip" data-act="last" title="Last (End)">&#9654;|</button>' +
      '<label class="speed">SPEED <select data-act="speed">' + SPEEDS.map(s => '<option value="' + s + '"' + (s === speed ? ' selected' : '') + '>' + s + 'x</option>').join('') + '</select></label>' +
      '<span class="beat-ms tiny muted"></span><span class="pos tiny"></span></div>' +
      '<p id="stage-help" class="tiny muted">Keys: LEFT/RIGHT step, SPACE play/pause, HOME/END. Motion is decoration only: every number above comes from the independent replay.</p>' +
      '<div class="caption cols"><div class="cap cap-A"></div><div class="cap cap-B"></div></div>' +
      '<details class="beat-details" open><summary>BEAT TABLE (' + frames.filter(f => f.kind === 'beat').length + ' executed beats)</summary>' +
      '<div class="tscroll"><table class="beats"><thead><tr><th>RND</th><th>BEAT</th><th>' + esc(names.A) + '</th><th class="num">HP</th><th class="num">ST</th><th>' + esc(names.B) + '</th><th class="num">HP</th><th class="num">ST</th><th>REASONS A / B</th></tr></thead><tbody>' + rows + '</tbody></table></div></details>';

    const els = {};
    for (const s of ['A', 'B']) {
      const c = $('.corner-' + s, root);
      els[s] = { corner: c, avatar: $('.avatar', c), hp: $('.cbar-hp', c), st: $('.cbar-st', c), power: $('.flag-power', c), opening: $('.flag-opening', c), guard: $('.flag-guard', c), now: $('.side-now', c), pop: $('.pop', c), cap: $('.cap-' + s, root) };
    }
    if (ANIM) ANIM.mount(root);
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
      note.className = 'center-note note-' + f.kind;
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
    function animateFrame(f) {
      if (!motion()) return;
      for (const s of ['A', 'B']) ANIM.rate(els[s].avatar, speed);
      if (f.kind === 'beat') {
        for (const s of ['A', 'B']) {
          const t = f.trace[s];
          const clip = { JAB: 'jab', KICK: 'kick', THROW: 'jab', DUCK: 'bow', EXHAUSTED: 'hit' }[NAMES[t.effective]];
          if (clip) ANIM.play(els[s].avatar, clip);
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
    seek(0, false);
    if (opts.autoplay && motion()) start();
    return { stop, seek, start, pause, get index() { return idx; }, frames };
  }

  function stopPlayer() { if (player) { player.stop(); player = null; } }

  // ---- REPLAY ------------------------------------------------------------------------

  async function viewFight(tok, id) {
    if (needData()) return;
    if (!DEC.test(id || '')) return notFound('Fight IDs are decimal numbers.');
    const [summary, replay] = await Promise.all([
      fetchJson('fights/' + id + '.json').catch(() => null),
      fetchJson('fights/' + id + '/replay.json').catch(() => null),
    ]);
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
      ' <span id="level-slot">' + (replay ? '<span class="level level-PENDING">VERIFYING&hellip;</span>' : '') + '</span></div>';
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
    player = createPlayer($('#player'), { frames, ids: { A: fighters.A.fighter_id, B: fighters.B.fighter_id }, names, links: true, replay, autoplay: true });
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

  async function viewFighter(tok, hex) {
    if (needData()) return;
    if (!HEX64.test(hex || '')) return notFound('A fighter ID is 64 lowercase hex digits.');
    const f = await fetchJson('fighters/' + hex + '.json').catch(() => null);
    if (tok !== viewToken) return;
    if (!f) return notFound('Fighter ' + short(hex) + ' is not in this export.');
    const ids = (f.fights || []).filter(x => DEC.test(x));
    const loaded = await Promise.all(ids.map(async id => {
      const [s, rp] = await Promise.all([fetchJson('fights/' + id + '.json').catch(() => null), fetchJson('fights/' + id + '/replay.json').catch(() => null)]);
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
      '<section class="panel panel-yellow fighter-panel"><h3>' + esc(short(hex)) + (f.house_npc ? ' &middot; HOUSE NPC' : '') + '</h3><div class="fprofile">' +
      avatar(hex, 'avatar-xl') + '<dl class="kv">' +
      '<dt>RATING</dt><dd><b class="big">' + esc(f.lifetime_rating) + '</b> ' + (f.provisional ? '<span class="belt belt-sm belt-other">PROVISIONAL ' + esc(f.placement_fights) + '/?</span>' : '<span class="belt belt-sm ' + beltCls + '">' + esc(String(f.belt || '').toUpperCase()) + ' BELT</span>') + '</dd>' +
      '<dt>RECORD</dt><dd>' + esc(rec.W || 0) + 'W ' + esc(rec.D || 0) + 'D ' + esc(rec.L || 0) + 'L &middot; forfeits ' + esc(rec.FW || 0) + ' won / ' + esc(rec.FL || 0) + ' lost <span class="muted">(contract record)</span></dd>' +
      '<dt>PLACEMENT</dt><dd>' + esc(f.placement_fights) + ' fights</dd>' +
      '<dt>STATUS</dt><dd>' + esc(f.lock || 'IDLE') + (f.cooldown_until && f.cooldown_until !== '0' ? ' &middot; cooldown until tick ' + esc(f.cooldown_until) : '') + '</dd>' +
      '<dt>FAULTS</dt><dd>' + (faults.length ? faults.map(([k, v]) => 'epoch ' + esc(k) + ': ' + esc(v)).join(', ') : '<span class="pos">none</span>') + '</dd>' +
      '<dt>SEASONS</dt><dd>' + Object.entries(f.season_ratings || {}).map(([k, v]) => 'S' + esc(k) + ' ' + esc(v)).join(', ') + '</dd>' +
      '<dt>OWNER</dt><dd class="id">' + esc(short(f.owner)) + '&hellip;' + (f.operator !== f.owner ? ' &middot; operator ' + esc(short(f.operator)) + '&hellip;' : ' (self-operated)') + '</dd>' +
      '</dl></div></section>' +
      '<section class="panel panel-cyan"><h3>SCOUTING REPORT</h3>' +
      '<p class="caveat">Observed in ' + s.replayed + ' completed fight(s), ' + s.beats + ' executed beats, re-derived from revealed plans. ' +
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
      '<section class="panel"><h3>FIGHTS (' + loaded.length + ')</h3><div class="tscroll"><table><thead><tr><th class="num">FIGHT</th><th>MODE</th><th>SLOT</th><th>OPPONENT</th><th>RESULT</th></tr></thead><tbody>' + fightRows + '</tbody></table></div></section>');
  }

  // ---- PRACTICE ------------------------------------------------------------------------

  const draft = { actions: [null, null, null, null, null, null], power_slot: -1, sel: 0 };
  function resetDraft() { draft.actions = [null, null, null, null, null, null]; draft.power_slot = -1; draft.sel = 0; }

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
    const chosen = N.ROSTER.some(n => n.id === npcId) ? npcId : (store.get('qdojo.combat.npc') || 'jabber-v1');
    const pre = HEX64.test(seed || '') ? seed : L.randomSeed();
    setView(screen('PRACTICE', 'FREE &middot; OFFLINE &middot; NO WALLET &middot; NO RATING') +
      '<section class="panel panel-green"><h3>1. PICK A DISCLOSED NPC</h3><div class="npc-grid" role="radiogroup" aria-label="NPC">' +
      N.ROSTER.map(n => '<button class="npc-card' + (n.id === chosen ? ' on' : '') + '" role="radio" aria-checked="' + (n.id === chosen) + '" data-npc="' + esc(n.id) + '">' +
        avatar('npc:' + n.id, 'avatar-lg') + '<b>' + esc(n.name) + '</b><span class="id">' + esc(n.id) + '</span><span class="tiny">' + esc(n.behavior) + '</span><span class="tiny lesson">LESSON: ' + esc(n.lesson) + '</span></button>').join('') +
      '</div><p class="tiny muted">NPCs are ordinary planners: same stats, no extra HP, no view of your plan. Difficulty is policy only.</p></section>' +
      '<section class="panel"><h3>2. SEED</h3><p>The NPC\'s private randomness comes from this 32-byte seed. The same seed and the same moves replay the same fight.</p>' +
      '<div class="seed-row"><input id="seed" class="mono" size="66" maxlength="64" spellcheck="false" aria-label="Practice seed, 64 hex digits" value="' + esc(pre) + '"><button class="btn btn-sm" id="new-seed">NEW SEED</button></div>' +
      '<p id="seed-err" class="neg tiny" role="alert"></p><button class="btn btn-start" id="go">FIGHT &#9654;</button></section>');
    let pick = chosen;
    $$('.npc-card').forEach(b => b.addEventListener('click', () => {
      pick = b.dataset.npc;
      $$('.npc-card').forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', String(x === b)); });
    }));
    $('#new-seed').addEventListener('click', () => { $('#seed').value = L.randomSeed(); });
    $('#go').addEventListener('click', () => {
      const s = $('#seed').value.trim().toLowerCase();
      if (!HEX64.test(s)) { $('#seed-err').textContent = 'A seed is exactly 64 hex digits.'; return; }
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

  function renderPracticeFight(playFrom) {
    stopPlayer();
    const s = practice;
    const npc = N.ROSTER.find(n => n.id === s.npc);
    const link = location.href.split('#')[0] + '#practice/' + s.npc + '/' + s.seed;
    const over = !!s.outcome;
    const me = s.state.a;
    setView(screen('PRACTICE VS ' + npc.name, 'FREE &middot; LOCAL &middot; ' + esc(npc.id) + ' &middot; ' + esc(R.semantic_version.toUpperCase())) +
      '<section class="panel practice-meta"><dl class="kv"><dt>SEED</dt><dd class="id wrap">' + esc(s.seed) + '</dd>' +
      '<dt>REPLAY LINK</dt><dd><a class="wrap" href="' + esc(link) + '">' + esc(link) + '</a></dd>' +
      '<dt>RECORD</dt><dd>policy ' + esc(s.npc) + ', fight number ' + s.fight + ', ruleset ' + esc(s.rules_version) + '. Local achievement only: no QU, no rating.</dd></dl></section>' +
      (over ? '<section class="panel panel-yellow"><h3>RESULT</h3><p>' + resultBadge({ outcome: s.outcome }) + ' <b class="big">' + (s.outcome.winner === 'A' ? 'YOU WIN' : s.outcome.winner === 'B' ? esc(npc.name) + ' WINS' : 'DRAW') + '</b> ' + esc({ KO: 'by knockout.', DOUBLE_KO: 'double knockout.', HP: 'on remaining HP.', HP_TIE: 'equal HP after three rounds.' }[s.outcome.result] || '') + '</p>' +
        '<p><button class="btn btn-sm" id="rematch">REMATCH (SAME SEED)</button> <button class="btn btn-sm btn-cyan" id="newfight">NEW SEED</button> <a class="btn btn-sm" href="#practice">CHANGE NPC</a></p></section>' : planner(me, npc)) +
      '<section class="panel player-panel"><h3>' + (s.rounds.length ? 'ROUNDS SO FAR' : 'THE MAT') + '</h3><div id="player"></div></section>' +
      (s.rounds.length ? '<section class="panel"><h3>REVEALED NPC PLANS</h3><ul class="plain">' + s.rounds.map(r => '<li>ROUND ' + (r.round_index + 1) + ': ' + r.plans.B.actions.map((a, i) => NAMES[a] + (i === r.plans.B.power_slot ? '&#9733;' : '')).join(' ') + '</li>').join('') + '</ul></section>' : ''));
    const frames = practiceFrames(s);
    player = createPlayer($('#player'), { frames, ids: { A: 'practice:you', B: 'npc:' + s.npc }, names: { A: 'YOU', B: npc.name }, links: false, replay: {}, mySide: 'A', autoplay: false });
    if (playFrom != null) {
      player.seek(playFrom, false);
      if (motion()) player.start(); else player.seek(frames.length - 1, false);
    } else player.seek(frames.length - 1, false);
    if (over) {
      $('#rematch').addEventListener('click', () => { practice = L.practiceStart(R, s.npc, s.seed, 1); resetDraft(); renderPracticeFight(); });
      $('#newfight').addEventListener('click', () => { location.hash = '#practice/' + s.npc + '/' + L.randomSeed(); });
    } else wirePlanner();
  }

  function planner(me, npc) {
    const cost = a => R.base_costs[a] + (a === L.ID.BLOCK ? '+' + R.block_streak_cost + '/guard' : '');
    return '<section class="panel panel-green planner" id="planner"><h3>ROUND ' + (practice.state.round_index + 1) + ' &middot; YOUR SIX BEATS</h3>' +
      '<p class="tiny">' + esc(npc.name) + '\'s plan is <b>SEALED</b>: it was chosen from the round-start state and your executed moves in earlier rounds, before you pick. ' +
      'You: HP ' + me.hp + ', STAMINA ' + me.stamina + ', guard ' + me.guard_streak + (me.opening ? ', OPENING' : '') + ', power ' + (me.power_available ? 'READY' : 'SPENT') + '.</p>' +
      '<div class="slots" role="listbox" aria-label="Your plan">' + [0, 1, 2, 3, 4, 5].map(i => '<div class="slot" role="option" data-slot="' + i + '" tabindex="0"><span class="slot-no">' + (i + 1) + '</span><span class="slot-act"></span><button class="slot-pw" data-pw="' + i + '" title="Power strike on this beat (+' + R.power_cost + ' cost, +' + R.power_damage + ' damage if it lands)">&#9733;</button></div>').join('') + '</div>' +
      '<div class="palette">' + R.submitted_action_ids.map(a => '<button class="btn btn-sm act-btn act-' + NAMES[a].toLowerCase() + '" data-a="' + a + '"><span class="key">' + (a + 1) + '</span> ' + NAMES[a] + ' <span class="cost">' + cost(a) + '</span></button>').join('') + '</div>' +
      '<p class="tiny muted">Click an action to fill the selected beat (keys 1-6), click a beat to select it (LEFT/RIGHT), the star button or P for power on a JAB, KICK or THROW, BACKSPACE clears, ENTER fights. An unaffordable move still resolves: as EXHAUSTED.</p>' +
      '<p><button class="btn" id="fight" disabled>FIGHT &#9654;</button> <button class="btn btn-sm btn-cyan" id="clear">CLEAR</button> <span id="plan-err" class="neg tiny" role="alert"></span></p></section>';
  }

  function paintDraft() {
    const pwOk = practice.state.a.power_available === 1;
    $$('.slot').forEach(el => {
      const i = Number(el.dataset.slot), a = draft.actions[i];
      el.classList.toggle('sel', i === draft.sel);
      el.setAttribute('aria-selected', String(i === draft.sel));
      el.classList.toggle('filled', a != null);
      $('.slot-act', el).textContent = a == null ? '—' : NAMES[a];
      $('.slot-act', el).className = 'slot-act' + (a == null ? '' : ' act-' + NAMES[a].toLowerCase());
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
      '<section class="panel"><h3>REASON CODES</h3><p class="tiny">Replays label each beat with these codes. They explain; they are never hidden logic.</p><p class="codes">' + REASONS.map(r => '<span class="code">' + r + '</span>').join(' ') + '</p></section>');
    const d = await L.rulesetDigest(R, SHA);
    if (tok !== viewToken) return;
    const m = D.manifest;
    $('#digest').innerHTML = '<span class="id wrap">' + esc(d) + '</span><br>' + (m
      ? (m.ruleset_digest === d ? statusBadge('PASS') + ' equals the manifest\'s ruleset_digest.' : statusBadge('FAIL') + ' differs from the manifest\'s ' + esc(m.ruleset_digest) + '. Replays on this page would not be trustworthy.')
      : statusBadge('UNAVAILABLE') + ' no manifest loaded to compare with.') + '<br><span class="tiny muted">SHA-256("qdojo/combat/rules/v1\\0" || canonical JSON), computed in your browser.</span>';
  }

  // ---- router and chrome -------------------------------------------------------------

  async function route() {
    const h = decodeURIComponent(location.hash.replace(/^#/, '')) || 'book';
    const [name, ...rest] = h.split('/');
    const tok = ++viewToken;
    stopPlayer();
    $$('.hud-nav a[data-view]').forEach(a => a.classList.toggle('on', a.dataset.view === name || (name === 'fight' && a.dataset.view === 'fights') || (name === 'fighter' && a.dataset.view === 'fights')));
    try {
      if (name === 'book') await viewBook(tok);
      else if (name === 'fights') await viewFights(tok);
      else if (name === 'fight') await viewFight(tok, rest[0]);
      else if (name === 'fighter') await viewFighter(tok, rest[0]);
      else if (name === 'practice') viewPractice(tok, rest);
      else if (name === 'rules') await viewRules(tok);
      else { location.replace('#book'); return; }
    } catch (e) {
      if (tok === viewToken) setView(screen('ERROR') + '<section class="panel panel-red"><h3>COULD NOT RENDER</h3><p>' + esc(e.message) + '</p></section>');
    }
    if (tok === viewToken && name !== 'practice') $('#view').focus({ preventScroll: true });
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
    paintMotion();
    await loadSource();
    paintSource();
    window.addEventListener('hashchange', route);
    route();
  }

  boot();
})();
