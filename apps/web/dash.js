/* QDOJO — the cockpit: your fighter's page, on your own machine.
 *
 * Small on purpose: it does NOT load the 145 KB spectator app, which is an
 * eleven-screen router with a poll loop. It reuses style.css and avatars.js,
 * both of which stand alone, and draws the panels that matter here.
 *
 * Every panel owns a container and a clock of its own. STATUS redraws every
 * three seconds, the rest every ten, and the SETTINGS form only when you ask
 * or after a save -- so a poll never wipes the value you are typing.
 */
'use strict';

// ---- pure helpers: no DOM, no fetch; tested in apps/web/tests/dash.test.cjs ----
const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = n => (n === null || n === undefined || Number.isNaN(Number(n))) ? '—' : Number(n).toLocaleString('en-US');
const pct = x => x === null || x === undefined ? '—' : `${Math.round(Number(x) * 100)}%`;
const signed = n => (n === null || n === undefined) ? '—' : (Number(n) > 0 ? '+' : '') + fmt(n);

function ageText(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const s = Math.max(0, Math.floor(Number(seconds)));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m${String(s % 60).padStart(2, '0')}s`;
  return `${Math.floor(s / 3600)}h${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}m`;
}

// The STATUS tile's uptime: a live, growing counter only while the bot is
// actually running. A stale heartbeat means the bot is gone, so its "up"
// freezes at the span between its start and its last heartbeat instead of
// counting from `started_at` to now, which would read a dead bot as running.
function upText(st, now) {
  if (!st.started_at) return '—';
  if (st.state === 'running') return ageText(now - st.started_at);
  if (st.state === 'stale' && st.heartbeat_at) return ageText(st.heartbeat_at - st.started_at);
  return '—';
}

// Cumulative net QU per settled round as an SVG polyline. Two points minimum;
// with one settled round there is nothing to draw a line between.
function sparkPath(series, w = 600, h = 80) {
  const pts = (series || []).map(p => Number(p[1])).filter(v => !Number.isNaN(v));
  if (pts.length < 2) return null;
  const lo = Math.min(0, ...pts), hi = Math.max(0, ...pts);
  const y = v => hi === lo ? h / 2 : h - ((v - lo) / (hi - lo)) * (h - 6) - 3;
  const x = i => (i / (pts.length - 1)) * w;
  return { points: pts.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' '),
           zeroY: y(0), last: pts[pts.length - 1], min: lo, max: hi };
}

// The form control for one manifest row. The current stored value is shown;
// the default is the placeholder, so "empty" visibly means "the default".
function settingControl(row, readOnly) {
  const dis = readOnly ? 'disabled' : '';
  const key = esc(row.key);
  const val = row.value === null || row.value === undefined ? '' : String(row.value);
  if (row.type === 'enum') {
    const cur = val || (row.default ?? '');
    return `<select data-key="${key}" ${dis}>${(row.choices || []).map(c =>
      `<option value="${esc(c)}" ${c === cur ? 'selected' : ''}>${c === '' ? '(none)' : esc(c)}</option>`).join('')}</select>`;
  }
  if (row.type === 'bool') {
    const cur = val || (row.default ?? 'false');
    return `<select data-key="${key}" ${dis}>${['true', 'false'].map(c =>
      `<option value="${c}" ${c === cur ? 'selected' : ''}>${c}</option>`).join('')}</select>`;
  }
  if (row.type === 'int' || row.type === 'float') {
    const min = row.min === undefined ? '' : `min="${esc(row.min)}"`, max = row.max === undefined ? '' : `max="${esc(row.max)}"`;
    return `<input type="number" data-key="${key}" value="${esc(val)}" placeholder="${esc(row.default ?? '')}"
      step="${row.type === 'int' ? '1' : 'any'}" ${min} ${max} ${dis}>`;
  }
  if (row.type === 'secret') {
    const name = row.env_name || '';
    return `<input type="text" data-key="${key}" value="${esc(val)}" placeholder="${esc(row.default ?? 'VARIABLE_NAME')}"
      autocomplete="off" spellcheck="false" ${dis}>
      <span class="secret-state ${row.set_in_env ? 'pos' : 'neg'}">${name ? `$${esc(name)} is ${row.set_in_env ? 'SET' : 'NOT SET'} in this environment` : 'no variable named'}</span>`;
  }
  const list = (row.suggestions || []).length ? `<datalist id="dl-${key}">${row.suggestions.map(s => `<option value="${esc(s)}">`).join('')}</datalist>` : '';
  return `<input type="text" data-key="${key}" value="${esc(val)}" placeholder="${esc(row.default ?? '')}"
    ${list ? `list="dl-${key}"` : ''} autocomplete="off" spellcheck="false" ${dis}>${list}`;
}

function sourceBadge(source) {
  const cls = { shell: 'badge-winner', profile: 'badge-reveal', default: 'badge-settled', unset: 'badge-pending' }[source] || 'badge-settled';
  return `<span class="badge ${cls}">${esc(String(source || '—').toUpperCase())}</span>`;
}

// One word for a metrics row: the verdict once settled, else what the bot did.
function rowState(r) {
  if (r.verdict) return r.verdict;
  if (r.dead) return 'dead';
  if (r.skipped) return 'sat out';
  if (r.entered) return 'pending';
  if (r.solver_failures) return 'no answer';
  return 'seen';
}
// ---- end pure helpers ----

const T = new URLSearchParams(location.search).get('t') || '';
const $ = (s, el = document) => el.querySelector(s);

let S = null, editing = null, promptsKey = '';

async function api(path, opts) {
  const r = await fetch(path + (path.includes('?') ? '&' : '?') + 't=' + encodeURIComponent(T), opts);
  return { ok: r.ok, data: await r.json().catch(() => null) };
}

function put(path, body) {
  return fetch(path + '?t=' + encodeURIComponent(T), {
    method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-QDojo-Token': T },
    body: JSON.stringify(body),
  });
}

function stat(k, v, cls = '', vcls = '') {
  return `<div class="stat ${cls}"><div class="k">${esc(k)}</div><div class="v ${vcls}">${v}</div></div>`;
}

function beltBand(b) {
  const known = ['white', 'yellow', 'orange', 'green', 'blue'].includes(String(b || '').toLowerCase());
  return `<div class="beltband beltband-${known ? String(b).toLowerCase() : 'other'}">${esc(String(b || 'white').toUpperCase())} BELT</div>`;
}

const badgeFor = v => ({ winner: 'badge-winner', solved: 'badge-solved', wrong: 'badge-wrong', pending: 'badge-pending',
  'sat out': 'badge-settled', dead: 'badge-no_commit', 'no answer': 'badge-late', seen: 'badge-settled',
  no_reveal: 'badge-no_reveal', no_commit: 'badge-no_commit', absent: 'badge-no_commit', void: 'badge-void',
  outranked: 'badge-outranked' }[v] || 'badge-settled');

// ---------------------------------------------------------------- panels

function statusPanel(st) {
  const cls = { running: 'panel-green', stale: 'panel-red', idle: '' }[st.state] || '';
  const label = { running: 'RUNNING', stale: 'STALE', idle: 'IDLE' }[st.state] || '?';
  const sub = st.state === 'running' ? 'BOT RUN IS POLLING THE BOARD'
            : st.state === 'stale' ? 'A HEARTBEAT IS THERE BUT OLD: THE BOT DIED, OR THE MACHINE SLEPT'
            : 'NO BOT IS RUNNING FOR THIS STATE DIR';
  const up = upText(st, Date.now() / 1000);
  const rounds = (st.rounds || []).map(r => `<tr>
    <td>R${esc(r.round_id)}</td><td>${esc(r.belt || '—')}</td><td>${esc(r.kind || r.title || '—')}</td>
    <td>${esc(r.state || '—')}</td><td class="wrap" style="white-space:normal">${esc(r.did)}</td></tr>`).join('');
  const acts = (st.last_actions || []).slice(-6).map(a =>
    `${new Date(a.at * 1000).toTimeString().slice(0, 8)} ${esc(a.text)}`).join('\n');
  return `<div class="panel ${cls}">
    <h3>STATUS<small>${sub}</small></h3>
    <div class="stats">
      ${stat('BOT', label, st.state === 'running' ? 'green' : st.state === 'stale' ? 'red' : '', `state-${st.state}`)}
      ${stat('PID', st.pid == null ? '—' : esc(st.pid))}
      ${stat('HEARTBEAT', st.age == null ? '—' : `${ageText(st.age)} AGO`, st.state === 'stale' ? 'red' : '')}
      ${stat('POLL', st.interval == null ? '—' : `EVERY ${esc(st.interval)}S`)}
      ${stat('TICK', st.tick == null ? '—' : fmt(st.tick), 'cyan')}
      ${stat(st.state === 'stale' ? 'RAN' : 'UP', up)}
    </div>
    ${rounds ? `<div class="tscroll"><table class="fame-table"><thead><tr>
      <th>ROUND</th><th>BELT</th><th>KIND</th><th>STATE</th><th>WHAT THE BOT DID</th></tr></thead><tbody>${rounds}</tbody></table></div>`
             : '<p class="tiny muted">no round on the board yet.</p>'}
    ${acts ? `<pre class="actions" style="margin-top:12px">${acts}</pre>` : ''}
    ${st.last_error ? `<p class="tiny neg" style="margin:10px 0 0">warning ${new Date(st.last_error.at * 1000).toTimeString().slice(0, 8)}: ${esc(st.last_error.text)}</p>` : ''}
    <p class="tiny muted" style="margin:10px 0 0">${st.solver && st.solver.length ? `solver <span class="mono">${esc(st.solver.join(' '))}</span> · ` : ''}${st.board ? `board <span class="mono wrap">${esc(st.board)}</span>` : 'start one: <span class="mono">./dojo fight</span>'}</p>
  </div>`;
}

function whoPanel(p, house) {
  const id = p.identity || '';
  return `<div class="panel panel-yellow">
    <h3>YOUR FIGHTER</h3>
    <div class="fcb-top">
      <div class="fcb-avatar">${id ? QDojoAvatars.render(id, 'avatar-xl') : ''}</div>
      <div class="fcb-info">
        <div class="fcb-name">${esc(p.name || 'UNNAMED')}</div>
        <div class="fcb-id mono wrap">${esc(id || 'no identity yet — run ./dojo rite')}</div>
        <div class="fcb-meta">
          <span>${esc(p.model || 'no model — a plain script')}</span>
          <span>KEY ${esc(p.key_source || 'none')}</span>
        </div>
      </div>
    </div>
    ${house ? beltBand(house.belt) : ''}
    <p class="tiny muted" style="margin:10px 0 0">The key itself is not here and never was: qdojo records
    only the name of the place you keep it.</p>
  </div>`;
}

function sparkline(series) {
  const sp = sparkPath(series);
  if (!sp) return '<p class="tiny muted" style="margin:0 0 20px">net QU draws itself here once two rounds have settled.</p>';
  const color = sp.last >= 0 ? 'var(--green)' : 'var(--red)';
  return `<p class="tiny muted" style="margin:0 0 6px">NET QU OVER SETTLED ROUNDS · now ${signed(sp.last)}</p>
    <svg class="spark" viewBox="0 0 600 80" preserveAspectRatio="none" aria-label="net QU over settled rounds">
      <line x1="0" y1="${sp.zeroY.toFixed(1)}" x2="600" y2="${sp.zeroY.toFixed(1)}"></line>
      <polyline points="${sp.points}" stroke="${color}"></polyline>
    </svg>`;
}

function metricsPanel(m) {
  if (!m || !m.rounds_seen) return `<div class="panel panel-cyan"><h3>METRICS<small>RECORDED ON THIS MACHINE BY BOT RUN</small></h3>
    <p>Nothing recorded yet. <span class="mono">./dojo fight</span> writes a line per round it sees to
    <span class="mono">metrics.jsonl</span> in your state directory; <span class="mono">qdojo bot metrics</span> reads the same file.</p></div>`;
  const kinds = Object.entries(m.by_kind || {}).sort((a, b) => b[1].seen - a[1].seen).map(([k, b]) => `<tr>
    <td>${esc(k)}</td><td class="num">${fmt(b.seen)}</td><td class="num">${fmt(b.entered)}</td><td class="num">${fmt(b.settled)}</td>
    <td class="num">${fmt(b.solved)}</td><td class="num">${pct(b.solve_rate)}</td><td class="num ${b.net < 0 ? 'neg' : 'pos'}">${signed(b.net)}</td></tr>`).join('');
  const rows = (m.last || []).map(r => {
    const st = rowState(r);
    return `<tr>
      <td>R${esc(r.round_id)}</td><td>${esc(r.belt || '—')}</td><td>${esc(r.kind || '—')}</td>
      <td><span class="badge ${badgeFor(st)}">${esc(st.toUpperCase())}</span></td>
      <td class="mono tiny">${esc(r.answer == null ? '—' : String(r.answer).slice(0, 24))}</td>
      <td class="num">${r.solver_seconds == null ? '—' : esc(r.solver_seconds) + 's'}</td>
      <td class="num qu">${r.stake ? fmt(r.stake) : '—'}</td>
      <td class="num ${r.net < 0 ? 'neg' : r.net > 0 ? 'pos' : ''}">${signed(r.net)}</td>
      <td class="tiny muted" style="white-space:normal">${esc(r.why || (r.verdict === 'wrong' && r.truth != null ? `answer was ${r.truth}` : ''))}</td>
    </tr>`;
  }).join('');
  return `<div class="panel panel-cyan">
    <h3>METRICS<small>RECORDED ON THIS MACHINE BY BOT RUN · SAME NUMBERS AS qdojo bot metrics</small></h3>
    <div class="stats">
      ${stat('ROUNDS SEEN', fmt(m.rounds_seen))}
      ${stat('ENTERED', fmt(m.entered))}
      ${stat('SAT OUT', fmt(m.skipped))}
      ${stat('SOLVED', `${fmt(m.solved)} / ${fmt(m.settled)}`, 'green')}
      ${stat('SOLVE RATE', pct(m.solve_rate), 'green')}
      ${stat('PAID', fmt(m.wins))}
      ${stat('AVG SOLVE', m.avg_solve_seconds == null ? '—' : `${m.avg_solve_seconds}s`, 'cyan')}
      ${stat('BEST SOLVE', m.best_solve_seconds == null ? '—' : `${m.best_solve_seconds}s`, 'cyan')}
      ${stat('NET QU', signed(m.net), m.net < 0 ? 'red' : 'green')}
      ${stat('STREAK', signed(m.streak), m.streak < 0 ? 'red' : '')}
      ${stat('PENDING', fmt(m.pending))}
      ${stat('SOLVER FAILED', fmt(m.solver_failed), m.solver_failed ? 'red' : '')}
    </div>
    ${sparkline(m.net_series)}
    ${kinds ? `<div class="tscroll"><table class="fame-table"><thead><tr>
      <th>KIND</th><th class="num">SEEN</th><th class="num">ENTERED</th><th class="num">SETTLED</th><th class="num">SOLVED</th><th class="num">RATE</th><th class="num">NET</th>
    </tr></thead><tbody>${kinds}</tbody></table></div>` : ''}
    <div class="tscroll" style="margin-top:14px"><table class="fame-table"><thead><tr>
      <th>ROUND</th><th>BELT</th><th>KIND</th><th>STATE</th><th>ANSWER</th><th class="num">SOLVE</th><th class="num">STAKE</th><th class="num">NET</th><th>NOTE</th>
    </tr></thead><tbody>${rows}</tbody></table></div>
  </div>`;
}

function settingsPanel(doc) {
  const readOnly = !!doc.read_only;
  const rows = doc.settings || [];
  const body = rows.map(r => `<tr data-row="${esc(r.key)}">
      <td class="s-key"><b>${esc((r.label || r.key).toUpperCase())}</b><code>${esc(r.key)}</code>${r.unknown ? '<div class="tiny neg">not in the manifest</div>' : ''}</td>
      <td class="s-val">${settingControl(r, readOnly)}<span class="s-msg" data-msg="${esc(r.key)}"></span></td>
      <td class="tiny mono">${r.type === 'secret' ? (r.default ? `$${esc(r.default)}` : '—') : esc(r.default ?? '—')}</td>
      <td>${sourceBadge(r.source)}</td>
      <td class="s-act">${readOnly ? '' : `<button class="btn btn-sm btn-cyan" data-save="${esc(r.key)}">SAVE</button>
        ${r.value !== null && r.value !== undefined ? `<button class="btn btn-sm" data-unset="${esc(r.key)}">UNSET</button>` : ''}`}</td>
      <td class="s-help tiny">${esc(r.help || '')}${r.type === 'secret' ? ' <span class="pos">Only the variable NAME is stored.</span>' : ''}</td>
    </tr>`).join('');
  return `<div class="panel panel-yellow">
    <h3>SETTINGS<small>${readOnly ? 'READ ONLY' : 'WHAT YOUR SOLVER IS TOLD · A RUNNING BOT PICKS A CHANGE UP ON ITS NEXT POLL'}</small></h3>
    ${doc.error ? `<p class="neg">${esc(doc.error)}</p>` : ''}
    ${rows.length ? `<div class="tscroll"><table class="fame-table sform"><thead><tr>
      <th>SETTING</th><th>VALUE</th><th>DEFAULT</th><th>SOURCE</th><th></th><th>HELP</th>
    </tr></thead><tbody>${body}</tbody></table></div>`
    : `<p>This solver declares no settings${doc.shipped ? '' : ' (no manifest beside it)'}. Declare one in the file below and it appears here.</p>`}
    <p class="tiny muted" style="margin:12px 0 0">declared in <span class="mono">${esc(doc.shipped || '(no shipped manifest)')}</span>
      and <span class="mono">${esc(doc.user)}</span> — yours wins on a clash. Same rows: <span class="mono">qdojo bot settings</span>.
      <button class="btn btn-sm" id="settings-refresh" style="margin-left:8px">REFRESH</button></p>
  </div>`;
}

function trainingPanel(t) {
  const c = t && t.scorecard;
  if (!c || !c.fought) return `<div class="panel panel-cyan"><h3>TRAINING<small>FIGHTS THAT NEVER TOUCH THE CHAIN</small></h3>
    <p>No training fight yet. <span class="mono">./dojo train</span> runs your solver against rounds that really happened, for nothing.</p></div>`;
  const rows = (t.attempts || []).slice(0, 12).map(a => `<tr>
    <td>R${a.round_id}</td><td>${esc(a.belt)}</td>
    <td>${a.correct ? '<span class="badge badge-winner">RIGHT</span>'
                    : (a.error ? '<span class="badge badge-pending">NO ANSWER</span>'
                               : '<span class="badge badge-wrong">WRONG</span>')}</td>
    <td class="num">${a.solve_ticks == null ? '—' : '+' + a.solve_ticks + 'T'}</td>
    <td class="num qu">${a.would_pay == null ? '—' : fmt(a.would_pay)}</td>
    <td class="tiny muted">${esc(a.error || a.why_unpriced || (a.correct ? '' : `answer was ${a.truth}`))}</td>
  </tr>`).join('');
  return `<div class="panel panel-cyan">
    <h3>TRAINING<small>FIGHTS THAT NEVER TOUCHED THE CHAIN</small></h3>
    <div class="stats">
      ${stat('FOUGHT', fmt(c.fought))}
      ${stat('SOLVED', `${fmt(c.solved)} / ${fmt(c.fought)}`, 'green')}
      ${stat('MEDIAN SOLVE', c.median_solve_ticks == null ? '—' : c.median_solve_ticks + ' T', 'cyan')}
      ${stat('WOULD HAVE PLACED', fmt(c.would_have_placed))}
      ${stat('HYPOTHETICAL PURSE', fmt(c.would_have_earned), 'green')}
    </div>
    <div class="tscroll"><table class="fame-table"><thead><tr>
      <th>ROUND</th><th>BELT</th><th>VERDICT</th><th class="num">SOLVE</th><th class="num">WOULD PAY</th><th>NOTE</th>
    </tr></thead><tbody>${rows}</tbody></table></div>
    <p class="tiny muted" style="margin:10px 0 0">None of this is real money and none of it is on chain.
    Run <span class="mono">./dojo train</span> again after you edit a prompt or a setting.</p>
  </div>`;
}

function housePanel(h) {
  if (!h) return `<div class="panel"><h3>AS THE HOUSE PUBLISHES IT</h3>
    <p>You have not fought a real round yet, so the house has nothing to say about you.
    When you want a seat: <span class="mono">./dojo rite</span>.</p></div>`;
  return `<div class="panel panel-green">
    <h3>AS THE HOUSE PUBLISHES IT<small>WHAT EVERYONE ELSE CAN SEE</small></h3>
    <div class="stats stats-profile">
      ${stat('ROUNDS', fmt(h.rounds_played))}${stat('SOLVED', fmt(h.solved), 'cyan')}
      ${stat('WINS', fmt(h.wins), 'green')}${stat('LOSSES', fmt(h.losses), 'red')}
      ${stat('SOLVE RATE', pct(h.solve_rate))}${stat('WIN RATE', pct(h.win_rate))}
      ${stat('EARNED', fmt(h.earned), 'green')}${stat('STAKED', fmt(h.staked))}
      ${stat('NET', fmt(h.net), Number(h.net) < 0 ? 'red' : 'green')}
      ${stat('POINTS', fmt(h.points))}${stat('STRIKES', fmt(h.strikes), 'red')}
    </div>
  </div>`;
}

function localPanel(rounds) {
  if (!rounds || !rounds.length) return '';
  return `<div class="panel"><h3>THIS MACHINE<small>WHAT YOUR BOT SENT, INCLUDING WHAT THE HOUSE HAS NOT EXPORTED YET</small></h3>
    <div class="tscroll"><table class="fame-table"><thead><tr>
      <th>ROUND</th><th>STATE</th><th class="num">STAKE</th><th>ANSWER</th><th class="num">SOLVER FAILS</th>
    </tr></thead><tbody>${rounds.map(r => `<tr>
      <td>R${r.round_id}</td>
      <td>${r.skipped ? '<span class="badge badge-pending">SAT OUT</span>'
                      : (r.reveal_tick ? '<span class="badge badge-reveal">REVEALED</span>'
                                       : (r.commit_tick ? '<span class="badge badge-commit">COMMITTED</span>'
                                                        : (r.entered ? '<span class="badge badge-seated">SEATED</span>' : '—')))}</td>
      <td class="num qu">${r.stake == null ? '—' : fmt(r.stake)}</td>
      <td class="mono tiny">${esc(r.answer == null ? '—' : String(r.answer).slice(0, 40))}</td>
      <td class="num ${r.solver_failures ? 'neg' : ''}">${fmt(r.solver_failures)}</td>
    </tr>`).join('')}</tbody></table></div></div>`;
}

function logPanel(lines) {
  if (!lines || !lines.length) return '';
  return `<div class="panel"><h3>LOG<small>THE TAIL OF bot.log · qdojo bot log</small></h3>
    <pre class="actions log">${lines.map(esc).join('\n')}</pre></div>`;
}

function promptsPanel(list, readOnly) {
  if (!list || !list.length) return `<div class="panel panel-red"><h3>PROMPTS</h3>
    <p>No prompt files yet. <span class="mono">qdojo prompts install</span> puts an editable copy where you can reach it.</p></div>`;
  return `<div class="panel panel-cyan">
    <h3>YOUR PROMPTS<small>${readOnly ? 'READ ONLY' : 'EDIT, SAVE, AND THE NEXT ROUND USES IT'}</small></h3>
    <p class="clean-list">${list.map(p =>
      `<button class="btn btn-sm ${editing === p.name ? 'btn-cyan' : ''}" data-prompt="${esc(p.name)}">${esc(p.name)}${p.mine ? '' : ' (shipped)'}</button>`).join(' ')}</p>
    <div id="editor"></div>
  </div>`;
}

function editorHTML(name, text, readOnly) {
  return `<p class="tiny muted">${esc(name)} — the part above the <span class="mono">---</span> line is a note to
  you and is never sent to the model.</p>
  <textarea id="prompt-text" class="code" ${readOnly ? 'readonly' : ''}
    style="width:100%;min-height:340px;background:var(--black);color:var(--green);border:3px solid var(--green);padding:12px;font-family:var(--font-text);font-size:13px;line-height:1.5"
    >${esc(text)}</textarea>
  <p class="clean-list" style="margin-top:10px">
    ${readOnly ? '' : '<button class="btn btn-cyan" id="save">SAVE</button>'}
    <button class="btn btn-sm" id="close">CLOSE</button>
    <span id="saved" class="tiny"></span>
  </p>`;
}

// ------------------------------------------------------------------ render

const SLOTS = ['status', 'who', 'metrics', 'settings', 'training', 'house', 'local', 'log', 'prompts'];
const WIDE = new Set(['metrics', 'settings', 'log', 'prompts']);

function scaffold() {
  $('#body').innerHTML = `<div class="cockpit">${SLOTS.map(s =>
    `<div id="p-${s}" class="${WIDE.has(s) ? 'wide' : ''}"></div>`).join('')}</div>`;
}

function setSlot(name, html) {
  const el = $('#p-' + name);
  if (el && el.innerHTML !== html) el.innerHTML = html;
}

function renderFighter() {
  if (!S) return;
  setSlot('who', whoPanel(S.profile || {}, S.house));
  setSlot('training', trainingPanel(S.training));
  setSlot('house', housePanel(S.house));
  setSlot('local', localPanel(S.rounds));
  // The prompts panel holds the editor: redraw it only when the list changed
  // and nothing is being edited, or a poll would wipe the text mid-sentence.
  const key = JSON.stringify(S.prompts) + S.read_only;
  if (key !== promptsKey && !editing) { promptsKey = key; setSlot('prompts', promptsPanel(S.prompts, S.read_only)); }
}

function renderStatus(st) {
  setSlot('status', statusPanel(st));
  const pill = $('#hud-bot');
  if (pill) {
    pill.textContent = `BOT ${({ running: 'RUNNING', stale: 'STALE', idle: 'IDLE' })[st.state] || '?'}`;
    pill.className = 'pill ' + ({ running: 'pill-live', stale: 'pill-lost', idle: 'pill-demo' })[st.state];
  }
}

async function refreshSettings() {
  const { ok, data } = await api('/api/settings');
  if (ok && data) setSlot('settings', settingsPanel(data));
}

async function pollStatus() { const r = await api('/api/status'); if (r.ok && r.data) renderStatus(r.data); }
async function pollMetrics() { const r = await api('/api/metrics'); if (r.ok && r.data) setSlot('metrics', metricsPanel(r.data)); }
async function pollLog() { const r = await api('/api/log?n=30'); if (r.ok && r.data) setSlot('log', logPanel(r.data.lines)); }
async function pollFighter() { const r = await api('/api/fighter'); if (r.ok && r.data) { S = r.data; renderFighter(); } }

async function openEditor(name) {
  editing = name;
  setSlot('prompts', promptsPanel(S.prompts, S.read_only));
  const { ok, data } = await api('/api/prompt?name=' + encodeURIComponent(name));
  const el = $('#editor');
  if (!el) return;
  if (!ok) { el.innerHTML = `<p class="tiny neg">${esc((data && data.error) || 'could not read it')}</p>`; return; }
  el.innerHTML = editorHTML(name, data.text, S.read_only);
  const close = $('#close'); if (close) close.onclick = () => { editing = null; promptsKey = ''; renderFighter(); };
  const save = $('#save');
  if (save) save.onclick = async () => {
    save.textContent = 'SAVING…';
    const r = await put('/api/prompt', { name, text: $('#prompt-text').value });
    const d = await r.json().catch(() => ({}));
    save.textContent = 'SAVE';
    $('#saved').innerHTML = r.ok
      ? '<span class="pos">SAVED · IN EFFECT NEXT ROUND</span>'
      : `<span class="neg">${esc(d.error || 'not saved')}</span>`;
  };
}

async function saveSetting(key) {
  const input = $(`[data-key="${CSS.escape(key)}"]`), msg = $(`[data-msg="${CSS.escape(key)}"]`);
  if (!input) return;
  msg.innerHTML = 'SAVING…';
  const r = await put('/api/settings', { key, value: input.value });
  const d = await r.json().catch(() => ({}));
  if (r.ok) { await refreshSettings(); const m = $(`[data-msg="${CSS.escape(key)}"]`); if (m) m.innerHTML = '<span class="pos">SAVED · LIVE ON THE NEXT POLL</span>'; }
  else msg.innerHTML = `<span class="neg">${esc(d.error || 'not saved')}</span>`;
}

async function unsetSetting(key) {
  const r = await put('/api/settings', { key, unset: true });
  const d = await r.json().catch(() => ({}));
  await refreshSettings();
  const m = $(`[data-msg="${CSS.escape(key)}"]`);
  if (m) m.innerHTML = r.ok ? '<span class="pos">UNSET · THE DEFAULT APPLIES</span>' : `<span class="neg">${esc(d.error || 'not unset')}</span>`;
}

document.addEventListener('click', e => {
  const p = e.target.closest('[data-prompt]');
  if (p) return openEditor(p.dataset.prompt);
  const s = e.target.closest('[data-save]');
  if (s) return saveSetting(s.dataset.save);
  const u = e.target.closest('[data-unset]');
  if (u) return unsetSetting(u.dataset.unset);
  if (e.target.closest('#settings-refresh')) return refreshSettings();
});
document.addEventListener('keydown', e => {
  // Enter in a settings field saves that field, like a form would.
  if (e.key === 'Enter' && e.target.matches && e.target.matches('.sform input')) { e.preventDefault(); saveSetting(e.target.dataset.key); }
});

(async function boot() {
  const { ok, data } = await api('/api/fighter');
  if (!ok) {
    $('#body').innerHTML = `<div class="panel panel-red"><h3>USE THE LINK THE COMMAND PRINTED</h3>
      <p>This page needs the one-time token in that URL. Look in the terminal where you ran
      <span class="mono">./dojo dash</span>.</p></div>`;
    return;
  }
  scaffold();
  S = data;
  renderFighter();
  await Promise.all([pollStatus(), pollMetrics(), refreshSettings(), pollLog()]);
  setInterval(pollStatus, 3000);
  setInterval(pollMetrics, 10000);
  setInterval(pollLog, 10000);
  setInterval(pollFighter, 10000);
})();
