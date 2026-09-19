/* QDOJO — the local fighter page.
 *
 * Small on purpose: it does NOT load the 145 KB spectator app, which is an
 * eleven-screen router with a poll loop. It reuses style.css and avatars.js,
 * both of which stand alone, and draws the few panels that matter here.
 */
'use strict';

const T = new URLSearchParams(location.search).get('t') || '';
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = n => (n === null || n === undefined || Number.isNaN(Number(n))) ? '—' : Number(n).toLocaleString('en-US');
const pct = x => x === null || x === undefined ? '—' : `${Math.round(Number(x) * 100)}%`;

let S = null, editing = null;

async function api(path, opts) {
  const r = await fetch(path + (path.includes('?') ? '&' : '?') + 't=' + encodeURIComponent(T), opts);
  return { ok: r.ok, data: await r.json().catch(() => null) };
}

function stat(k, v, cls = '') {
  return `<div class="stat ${cls}"><div class="k">${esc(k)}</div><div class="v">${v}</div></div>`;
}

function beltBand(b) {
  const known = ['white', 'yellow', 'orange', 'green', 'blue'].includes(String(b || '').toLowerCase());
  return `<div class="beltband beltband-${known ? String(b).toLowerCase() : 'other'}">${esc(String(b || 'white').toUpperCase())} BELT</div>`;
}

// ---------------------------------------------------------------- panels

function whoPanel(p, house) {
  const id = p.identity || '';
  return `<div class="panel panel-yellow">
    <h3>YOUR FIGHTER</h3>
    <div class="fcb-top">
      <div class="fcb-avatar">${id ? QDojoAvatars.render(id, 'avatar-xl').replace('<span class="avatar', `<span data-anim="profile" data-identity="${esc(id)}" class="avatar`) : ''}</div>
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

function trainingPanel(t) {
  const c = t && t.scorecard;
  if (!c || !c.fought) return '';
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
    Run <span class="mono">./dojo train</span> again after you edit a prompt.</p>
  </div>`;
}

function housePanel(h) {
  if (!h) return `<div class="panel"><h3>AS THE HOUSE PUBLISHES IT</h3>
    <p>You have not fought a real round yet, so the house has nothing to say about you.
    Everything above is training. When you want a seat: <span class="mono">./dojo rite</span>.</p></div>`;
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
  return `<div class="panel"><h3>THIS MACHINE<small>WHAT YOUR BOT DID, INCLUDING WHAT THE HOUSE HAS NOT EXPORTED YET</small></h3>
    <div class="tscroll"><table class="fame-table"><thead><tr>
      <th>ROUND</th><th>STATE</th><th class="num">STAKE</th><th>ANSWER</th><th class="num">SOLVER FAILS</th>
    </tr></thead><tbody>${rounds.map(r => `<tr>
      <td>R${r.round_id}</td>
      <td>${r.skipped ? '<span class="badge badge-pending">SAT OUT</span>'
                      : (r.reveal_tick ? '<span class="badge badge-reveal">REVEALED</span>'
                                       : (r.entered ? '<span class="badge badge-seated">SEATED</span>' : '—'))}</td>
      <td class="num qu">${r.stake == null ? '—' : fmt(r.stake)}</td>
      <td class="mono tiny">${esc(r.answer == null ? '—' : String(r.answer).slice(0, 40))}</td>
      <td class="num ${r.solver_failures ? 'neg' : ''}">${fmt(r.solver_failures)}</td>
    </tr>`).join('')}</tbody></table></div></div>`;
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

function render() {
  if (!S) return;
  const hasChainRecord = !!S.house;
  $('#body').innerHTML = [
    whoPanel(S.profile || {}, S.house),
    hasChainRecord ? housePanel(S.house) : trainingPanel(S.training),
    hasChainRecord ? trainingPanel(S.training) : housePanel(null),
    localPanel(S.rounds),
    promptsPanel(S.prompts, S.read_only),
  ].filter(Boolean).join('');
  if (typeof QDojoAnim !== 'undefined') QDojoAnim.mount($('#body'));
  if (editing) openEditor(editing);
}

async function openEditor(name) {
  editing = name;
  const { ok, data } = await api('/api/prompt?name=' + encodeURIComponent(name));
  const el = $('#editor');
  if (!el) return;
  if (!ok) { el.innerHTML = `<p class="tiny neg">${esc((data && data.error) || 'could not read it')}</p>`; return; }
  el.innerHTML = editorHTML(name, data.text, S.read_only);
  const close = $('#close'); if (close) close.onclick = () => { editing = null; render(); };
  const save = $('#save');
  if (save) save.onclick = async () => {
    save.textContent = 'SAVING…';
    const r = await fetch('/api/prompt?t=' + encodeURIComponent(T), {
      method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-QDojo-Token': T },
      body: JSON.stringify({ name, text: $('#prompt-text').value }),
    });
    const d = await r.json().catch(() => ({}));
    save.textContent = 'SAVE';
    $('#saved').innerHTML = r.ok
      ? '<span class="pos">SAVED · IN EFFECT NEXT ROUND</span>'
      : `<span class="neg">${esc(d.error || 'not saved')}</span>`;
  };
}

document.addEventListener('click', e => {
  const t = e.target.closest('[data-prompt]');
  if (t) openEditor(t.dataset.prompt);
});

(async function boot() {
  const { ok, data } = await api('/api/fighter');
  if (!ok) {
    $('#body').innerHTML = `<div class="panel panel-red"><h3>USE THE LINK THE COMMAND PRINTED</h3>
      <p>This page needs the one-time token in that URL. Look in the terminal where you ran
      <span class="mono">./dojo dash</span>.</p></div>`;
    return;
  }
  S = data;
  render();
  setInterval(async () => { const r = await api('/api/fighter'); if (r.ok) { S = r.data; render(); } }, 10000);
})();
