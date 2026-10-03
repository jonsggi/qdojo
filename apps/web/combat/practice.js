/* Practice support for combat.html: shared replay links, the post-fight
 * debrief and the local practice record. Pure: no DOM, no storage, no clock.
 *
 *   shareCode / parseShare / replayShare
 *       a completed practice fight as a compact link tail: the player's plans
 *       per round plus seed, NPC policy, fight number and ruleset digest. The
 *       NPC's plans, every beat and the result are re-derived by the engine;
 *       the link's check value only detects a mismatch, it is never shown as
 *       fact (docs/npcs.md section 5).
 *   debrief
 *       key beats, observed causes, habits, a hindsight plan and one tip, all
 *       counted from engine traces (combat.md section 9). Nothing is invented
 *       for a beat that was not played.
 *   progress*
 *       the per-ruleset, per-NPC practice record and the learning ladder.
 *
 * <script src="combat/practice.js"> (after logic.js) defines
 * window.QDojoPractice; in Node, require() returns the same object.
 */
'use strict';
(function (root, factory) {
  const node = typeof module === 'object' && module && module.exports;
  const api = node ? factory(require('./engine.js'), require('./npcs.js'), require('./logic.js'))
    : factory(root.QDojoCombat, root.QDojoNpcs, root.QDojoCombatLogic);
  if (node) module.exports = api;
  if (root) root.QDojoPractice = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (E, N, L) {
  const NAMES = E.ACTIONS;
  const ID = {};
  NAMES.forEach((n, i) => { ID[n] = i; });
  const POWERABLE = [ID.JAB, ID.KICK, ID.THROW];
  const OTHER = { A: 'B', B: 'A' };
  const word = a => NAMES[a].replace(/_/g, ' ');

  // ---- shared replay links (docs/npcs.md section 5) ---------------------------

  const SHARE_VERSION = 'p1';
  const MAX_TAIL = 160;          // p1 needs at most ~60 characters; anything longer is refused
  const DIGEST_PREFIX = 16;      // hex digits of the ruleset digest carried in the link
  const CHECK_LEN = 8;           // hex digits of the result check

  function planCode(p) { return p.actions.join('') + (p.power_slot >= 0 ? String(p.power_slot) : 'n'); }

  /* The link tail for a finished practice fight s (L.practiceStart/practicePlay). */
  async function shareCode(s, rulesDigest, sha) {
    if (!s.outcome) throw new Error('only a finished fight can be shared');
    const check = await resultCheck(s, sha);
    return [SHARE_VERSION, s.fight, String(rulesDigest).slice(0, DIGEST_PREFIX), s.rounds.map(r => planCode(r.plans.A)).join('-'), check].join('.');
  }

  /* Hash of what the engine derived: every executed beat (both effective
   * actions and HPs) and the outcome. Short, because it only detects a
   * mismatch; the page always shows its own derivation. */
  async function resultCheck(s, sha) {
    const parts = [s.npc, s.seed, s.fight, s.rules_version];
    for (const r of s.rounds) for (const b of r.result.beats) parts.push([b.a.effective, b.b.effective, b.a.after.hp, b.b.after.hp].join(','));
    parts.push(s.outcome ? s.outcome.result + ':' + s.outcome.winner : 'open');
    const bytes = Array.from('qdojo/practice/v1\0' + parts.join('|'), ch => ch.charCodeAt(0) & 0xff);
    return (await sha(new Uint8Array(bytes))).slice(0, CHECK_LEN);
  }

  /* Parses #practice/<npc>/<seed>/<tail>. Returns { ok, error } or { ok, ...fields }.
   * Only the syntax is checked here; replayShare runs the fight. */
  function parseShare(npc, seed, tail) {
    const bad = error => ({ ok: false, error });
    if (typeof tail !== 'string' || !tail) return bad('The link has no fight in it.');
    if (tail.length > MAX_TAIL) return bad('The link is too long to be a practice replay (' + tail.length + ' characters; at most ' + MAX_TAIL + ').');
    const f = tail.split('.');
    if (f[0] !== SHARE_VERSION) return bad('This replay link uses format "' + f[0].slice(0, 8) + '"; this site reads format ' + SHARE_VERSION + '.');
    if (f.length !== 5) return bad('The link is incomplete: it needs a fight number, a ruleset, the plans and a check value.');
    if (!N.ROSTER.some(n => n.id === npc)) return bad('Unknown practice opponent "' + String(npc).slice(0, 20) + '".');
    if (!/^[0-9a-f]{64}$/.test(seed || '')) return bad('The seed must be 64 lowercase hex digits.');
    if (!/^[1-9][0-9]{0,5}$/.test(f[1])) return bad('The fight number must be a positive whole number.');
    if (!new RegExp('^[0-9a-f]{' + DIGEST_PREFIX + '}$').test(f[2])) return bad('The ruleset reference must be ' + DIGEST_PREFIX + ' hex digits.');
    if (!new RegExp('^[0-9a-f]{' + CHECK_LEN + '}$').test(f[4])) return bad('The check value must be ' + CHECK_LEN + ' hex digits.');
    const rounds = f[3].split('-');
    if (rounds.length < 1 || rounds.length > 3) return bad('A fight has one to three rounds; the link has ' + rounds.length + '.');
    const plans = [];
    for (let i = 0; i < rounds.length; i++) {
      const m = /^([0-8]{6})([0-5n])$/.exec(rounds[i]);
      if (!m) return bad('Round ' + (i + 1) + ' of the link is not six moves and a power slot.');
      plans.push({ actions: Array.from(m[1], Number), power_slot: m[2] === 'n' ? -1 : Number(m[2]) });
    }
    return { ok: true, version: SHARE_VERSION, npc, seed, fight: Number(f[1]), digest: f[2], plans, check: f[4] };
  }

  /* Re-derives a parsed link under the ruleset whose digest starts with the
   * link's prefix. rulesets: [{ rules, digest }]. Returns { ok, error } or
   * { ok, s, rules, check, match }: s is a finished practice fight. */
  async function replayShare(parsed, rulesets, sha) {
    const bad = error => ({ ok: false, error });
    const hit = rulesets.find(x => x.digest.startsWith(parsed.digest));
    if (!hit) return bad('The fight was played under a ruleset this site does not carry (digest ' + parsed.digest + '...). It cannot be replayed faithfully here, so it is not replayed at all.');
    let s;
    try {
      s = L.practiceStart(hit.rules, parsed.npc, parsed.seed, parsed.fight);
      parsed.plans.forEach((p, i) => {
        if (s.outcome) throw new Error('the fight was already over after round ' + i + ', but the link has more rounds');
        L.practicePlay(hit.rules, s, p);
      });
    } catch (e) {
      return bad('These plans are not a legal fight under ' + hit.rules.semantic_version + ': ' + String(e.message).replace(/^combat: /, '') + '.');
    }
    if (!s.outcome) return bad('The link holds ' + parsed.plans.length + ' round' + (parsed.plans.length > 1 ? 's' : '') + ' of an unfinished fight. Only finished fights are shared.');
    const check = await resultCheck(s, sha);
    return { ok: true, s, rules: hit.rules, check, match: check === parsed.check };
  }

  // ---- debrief (AUD-032) -------------------------------------------------------

  const execBeats = rounds => {
    const out = [];
    for (const r of rounds) for (const b of r.result.beats) out.push({ round: r.round_index, beat: b.beat, A: b.a, B: b.b });
    return out;
  };

  function observe(beats, side) {
    const o = { side, beats: beats.length, exhausted: [], punished: [], powerWasted: null, powerLanded: null, blockedOrDucked: 0, interrupted: 0,
      feints: 0, baited: 0, guardBreaks: 0, standBonus: 0, strain: 0, openingsExpired: 0, openingsEarned: 0, counts: {} };
    for (const x of beats) {
      const t = x[side];
      const at = { round: x.round, beat: x.beat };
      o.counts[t.effective] = (o.counts[t.effective] || 0) + 1;
      if (t.effective === ID.EXHAUSTED) o.exhausted.push(Object.assign({ intended: t.intended, cost: t.cost, had: t.before.stamina, lost: t.actual_hp_lost }, at));
      if (t.reasons.includes('RECOVERY_PUNISHED')) o.punished.push(Object.assign({ lost: t.actual_hp_lost, by: x[OTHER[side]].effective }, at));
      if (t.reasons.includes('POWER_WASTED')) o.powerWasted = Object.assign({ action: t.effective, against: x[OTHER[side]].effective }, at);
      if (t.reasons.includes('POWER_USED')) o.powerLanded = Object.assign({ action: t.effective, dealt: t.computed_damage }, at);
      if (t.reasons.includes('BLOCKED') || t.reasons.includes('EVADED')) o.blockedOrDucked++;
      if (t.reasons.includes('THROW_INTERRUPTED')) o.interrupted++;
      if (t.effective === ID.FEINT) o.feints++;
      if (t.reasons.includes('FEINT_BAITED')) o.baited++;
      if (t.reasons.includes('GUARD_BROKEN')) o.guardBreaks++;
      if (t.stand_bonus) o.standBonus += t.stand_bonus;
      o.strain += t.strain || 0;
      if (t.reasons.includes('OPENING_EXPIRED')) o.openingsExpired++;
      if (t.reasons.includes('OPENING_EARNED')) o.openingsEarned++;
    }
    return o;
  }

  /* Habits seen in executed beats only (never the unplayed suffix). */
  function habits(beats, rounds, side) {
    const counts = {};
    for (const x of beats) counts[x[side].effective] = (counts[x[side].effective] || 0) + 1;
    const top = Object.keys(counts).map(Number).sort((p, q) => counts[q] - counts[p] || p - q).map(a => ({ action: a, n: counts[a] }));
    // A beat position that showed the same action in every round that reached it (two rounds or more).
    const slots = [];
    for (let i = 0; i < 6; i++) {
      const seen = rounds.map(r => r.result.beats[i]).filter(Boolean).map(b => (side === 'A' ? b.a : b.b).effective);
      if (seen.length >= 2 && seen.every(a => a === seen[0])) slots.push({ beat: i, action: seen[0], rounds: seen.length });
    }
    return { total: beats.length, top, slots };
  }

  /* Swing of one beat for side P: HP dealt minus HP taken. */
  const swingOf = (x, P) => x[OTHER[P]].actual_hp_lost - x[P].actual_hp_lost;

  /* The beat-by-beat best reply to the opponent's recorded plan for one
   * round, by beam search, then re-run through the engine for exact
   * numbers. Exact for that round only: the NPC's plan was sealed before the
   * human chose, but later rounds would have changed. */
  function betterRound(rules, round, side, width) {
    const opp = round.plans[OTHER[side]];
    const start = round.start;
    const me0 = side === 'A' ? start.a : start.b, op0 = side === 'A' ? start.b : start.a;
    const ids = rules.submitted_action_ids;
    let beam = [{ me: me0, op: op0, acts: [], pw: -1, score: 0, over: false }];
    for (let i = 0; i < 6; i++) {
      const next = [];
      for (const c of beam) {
        if (c.over) { next.push(Object.assign({}, c, { acts: c.acts.concat([ID.RECOVER]) })); continue; }
        for (const a of ids) {
          for (const pw of (c.pw < 0 && c.me.power_available === 1 && POWERABLE.includes(a)) ? [false, true] : [false]) {
            const opPw = opp.power_slot === i;
            const r = side === 'A' ? E.resolveBeat(rules, c.me, c.op, a, opp.actions[i], pw, opPw) : E.resolveBeat(rules, c.op, c.me, opp.actions[i], a, opPw, pw);
            const m = side === 'A' ? r.trace[0] : r.trace[1], o = side === 'A' ? r.trace[1] : r.trace[0];
            const me = side === 'A' ? r.a : r.b, op = side === 'A' ? r.b : r.a;
            if (me.hp === 0) continue;   // never suggest a plan that gets knocked out
            next.push({ me, op, acts: c.acts.concat([a]), pw: pw ? i : c.pw, score: c.score + o.actual_hp_lost - m.actual_hp_lost, over: op.hp === 0 });
          }
        }
      }
      next.sort((p, q) => q.score - p.score || q.me.stamina - p.me.stamina);
      beam = next.slice(0, width || 48);
      if (!beam.length) return null;
    }
    const best = beam[0];
    const plan = { actions: best.acts, power_slot: best.pw };
    const res = side === 'A' ? E.resolveRound(rules, start, plan, opp) : E.resolveRound(rules, start, opp, plan);
    const lost = k => res.beats.reduce((n, b) => n + b[k].actual_hp_lost, 0);
    const mk = side === 'A' ? 'a' : 'b', ok = side === 'A' ? 'b' : 'a';
    return { plan, dealt: lost(ok), taken: lost(mk), ko: !!(res.outcome && res.outcome.winner === side) };
  }

  /* The debrief for one fight.
   *   rounds   practice s.rounds or deriveReplay(...).rounds (same shape)
   *   outcome  the derived outcome, or null
   *   opts     { rules, mySide: 'A'|'B'|null, names: {A,B}, forfeit: label|null, lessons: npc id -> lesson }
   * Every number comes from a trace or from an engine run. */
  function debrief(rounds, outcome, opts) {
    const rules = opts.rules, P = opts.mySide || null, names = opts.names || { A: 'A', B: 'B' };
    const beats = execBeats(rounds);
    const out = { played: beats.length, rounds: rounds.length, forfeit: opts.forfeit || null, key: [], causes: [], habits: null, better: null, tip: null, practice: null };
    if (!beats.length) return out;
    // Key beats: the largest HP swings, the finishing blow always included, in fight order.
    const P0 = P || 'A';
    const swings = beats.map((x, i) => ({ i, x, s: swingOf(x, P0), size: x.A.actual_hp_lost + x.B.actual_hp_lost }));
    const finish = swings.filter(w => w.x.A.reasons.includes('KO') || w.x.B.reasons.includes('KO') || w.x.A.reasons.includes('DOUBLE_KO'));
    const pick = swings.filter(w => w.size > 0).sort((p, q) => Math.abs(q.s) - Math.abs(p.s) || q.size - p.size || p.i - q.i).slice(0, 3);
    for (const f of finish) if (!pick.includes(f)) pick.push(f);
    pick.sort((p, q) => p.i - q.i);
    out.key = pick.map(w => ({
      round: w.x.round, beat: w.x.beat, swing: w.s, dealt: w.x[OTHER[P0]].actual_hp_lost, taken: w.x[P0].actual_hp_lost,
      finish: finish.includes(w), headline: L.beatHeadline(w.x.A, w.x.B, names),
    }));
    // Causes: what the traces show, per side; for practice only the player's
    // own costly habits, plus the opponent's tricks that worked.
    const sides = P ? [P] : ['A', 'B'];
    for (const s of sides) {
      const o = observe(beats, s), who = P ? 'You' : names[s], their = P ? 'your' : names[s] + "'s";
      const where = list => list.map(x => 'R' + (x.round + 1) + ' B' + (x.beat + 1)).join(', ');
      const sum = (list, k) => list.reduce((n, x) => n + x[k], 0);
      if (o.exhausted.length) out.causes.push({ kind: 'exhausted', side: s, n: o.exhausted.length, text: who + ' ran out of stamina ' + o.exhausted.length + ' time' + (o.exhausted.length > 1 ? 's' : '') + ' (' + where(o.exhausted) + '): the move became EXHAUSTED, paid nothing and stood open' + (sum(o.exhausted, 'lost') ? ', costing ' + sum(o.exhausted, 'lost') + ' HP.' : '.') });
      if (o.punished.length) out.causes.push({ kind: 'punished', side: s, n: o.punished.length, text: who + ' got hit while recovering ' + o.punished.length + ' time' + (o.punished.length > 1 ? 's' : '') + ' (' + where(o.punished) + ') for ' + sum(o.punished, 'lost') + ' HP; a hit recovery also refills less stamina.' });
      if (o.powerWasted) out.causes.push({ kind: 'power', side: s, n: 1, text: who + ' spent the power strike on a ' + word(o.powerWasted.action) + ' that the ' + word(o.powerWasted.against) + ' stopped (R' + (o.powerWasted.round + 1) + ' B' + (o.powerWasted.beat + 1) + '): wasted, it is once per fight.' });
      if (o.blockedOrDucked >= 3) out.causes.push({ kind: 'stopped', side: s, n: o.blockedOrDucked, text: o.blockedOrDucked + ' of ' + their + ' attacks were blocked or ducked: stamina paid for nothing.' });
      if (o.interrupted >= 2) out.causes.push({ kind: 'interrupted', side: s, n: o.interrupted, text: o.interrupted + ' of ' + their + ' throws were interrupted by strikes.' });
      if (o.openingsExpired >= 2) out.causes.push({ kind: 'openings', side: s, n: o.openingsExpired, text: who + ' earned ' + o.openingsExpired + ' openings that expired unused: the bonus only lands on the very next beat.' });
      if (o.baited) out.causes.push({ kind: 'feint', side: s, n: o.baited, text: (P ? 'Your' : names[s] + "'s") + ' feint baited a guard ' + o.baited + ' time' + (o.baited > 1 ? 's' : '') + (o.guardBreaks ? ', and ' + o.guardBreaks + ' strike' + (o.guardBreaks > 1 ? 's' : '') + ' went through the block after it.' : ', but no strike followed through the dropped guard.') });
      if (o.standBonus) out.causes.push({ kind: 'stand', side: s, n: o.standBonus, text: who + ' added ' + o.standBonus + ' damage with LAST STAND bonuses for trailing.' });
      if (o.strain >= 12) out.causes.push({ kind: 'strain', side: s, n: o.strain, text: who + ' lost ' + o.strain + ' stamina to guard strain from blocking kicks.' });
    }
    if (P) {
      const opp = observe(beats, OTHER[P]);
      if (opp.baited) out.causes.push({ kind: 'feint-them', side: OTHER[P], n: opp.baited, text: names[OTHER[P]] + "'s feint baited your guard " + opp.baited + ' time' + (opp.baited > 1 ? 's' : '') + '.' });
      if (opp.punished.length) out.causes.push({ kind: 'punished-them', side: OTHER[P], n: opp.punished.length, text: 'You caught ' + names[OTHER[P]] + ' recovering ' + opp.punished.length + ' time' + (opp.punished.length > 1 ? 's' : '') + ' for ' + opp.punished.reduce((n, x) => n + x.lost, 0) + ' HP.' });
      if (opp.exhausted.length) out.causes.push({ kind: 'exhausted-them', side: OTHER[P], n: opp.exhausted.length, text: names[OTHER[P]] + ' ran out of stamina ' + opp.exhausted.length + ' time' + (opp.exhausted.length > 1 ? 's' : '') + '.' });
    }
    // Habits: the opponent's in practice, both sides in a replay.
    out.habits = (P ? [OTHER[P]] : ['A', 'B']).map(s => Object.assign({ side: s, name: names[s] }, habits(beats, rounds, s)));
    if (!P) {
      // A replay suggests practice, from the loser's (or both sides') costliest habit.
      const loser = outcome && outcome.winner ? OTHER[outcome.winner] : null;
      const c = out.causes.find(x => !loser || x.side === loser);
      const map = { exhausted: 'mixed-v1', punished: 'kicker-v1', stopped: 'turtle-v1', interrupted: 'jabber-v1', power: 'turtle-v1', openings: 'jabber-v1', strain: 'kicker-v1', feint: 'turtle-v1', stand: 'scout-v1' };
      const npc = c ? map[c.kind] : 'scout-v1';
      out.practice = { npc, why: c ? 'rehearse what ' + names[c.side] + ' struggled with: ' + c.kind.replace('-', ' ') : 'try both styles yourself against an adaptive opponent' };
      return out;
    }
    // Hindsight plan: the played round where a different plan against the
    // opponent's recorded (sealed) plan would have netted the most more.
    let better = null;
    for (const r of rounds) {
      const b = betterRound(rules, r, P);
      if (!b) continue;
      const k = P === 'A' ? 'a' : 'b', ok = P === 'A' ? 'b' : 'a';
      const dealt = r.result.beats.reduce((n, x) => n + x[ok].actual_hp_lost, 0), taken = r.result.beats.reduce((n, x) => n + x[k].actual_hp_lost, 0);
      const gain = (b.dealt - b.taken) - (dealt - taken);
      if (gain >= 6 && (!better || gain > better.gain)) better = Object.assign({ round: r.round_index, actualDealt: dealt, actualTaken: taken, gain, oppPlan: r.plans[OTHER[P]] }, b);
    }
    out.better = better;
    // One tip, the most costly observed habit first; a counter computed by the engine otherwise.
    const mine = observe(beats, P), them = out.habits[0];
    const lostTo = list => list.reduce((n, x) => n + x.lost, 0);
    const won = outcome && outcome.winner === P;
    if (won && !mine.exhausted.length && lostTo(mine.punished) < 8) out.tip = { kind: 'next', text: 'Clean work: ' + (out.better ? 'the hindsight plan above shows there was still more on the table. ' : '') + 'Take the next challenge, or rematch on a new seed to check it was not luck.' };
    else if (mine.exhausted.length) out.tip = { kind: 'stamina', text: 'Budget stamina: watch the small ST number under each beat while you plan. When it turns red the move will be EXHAUSTED; put a RECOVER or a cheap move before it.' };
    else if (mine.punished.length && lostTo(mine.punished) >= 8) {
      const atk = [...new Set(mine.punished.map(x => word(x.by)))].join(' or ');
      out.tip = { kind: 'recover', text: 'Recover where ' + names[OTHER[P]] + ' does not attack: every RECOVER that met a ' + atk + ' cost you HP. Check which beats it attacked in the recap and recover elsewhere.' };
    } else if (them && them.top[0] && them.total >= 4 && them.top[0].n * 2 >= them.total && them.top[0].action !== ID.RECOVER) {
      const a = them.top[0].action, s0 = rounds[0].start;
      const me = P === 'A' ? s0.a : s0.b, op = P === 'A' ? s0.b : s0.a;
      let best = null;
      for (const x of rules.submitted_action_ids) {
        const r = P === 'A' ? E.resolveBeat(rules, me, op, x, a, false, false) : E.resolveBeat(rules, op, me, a, x, false, false);
        const m = P === 'A' ? r.trace[0] : r.trace[1], o = P === 'A' ? r.trace[1] : r.trace[0];
        const net = o.actual_hp_lost - m.actual_hp_lost;
        if (!best || net > best.net) best = { x, net, dealt: o.actual_hp_lost, taken: m.actual_hp_lost };
      }
      out.tip = { kind: 'counter', text: names[OTHER[P]] + ' played ' + word(a) + ' on ' + them.top[0].n + ' of ' + them.total + ' beats. On a fresh beat the engine scores ' + word(best.x) + ' against ' + word(a) + ' at +' + best.dealt + ' / -' + best.taken + ' HP. Try it where you expect the ' + word(a) + '.' };
    } else if (mine.powerWasted) out.tip = { kind: 'power', text: 'Put POWER on a JAB, KICK or THROW where the opponent will not block or duck: it only adds damage to a strike that lands.' };
    else if (mine.blockedOrDucked >= 3) out.tip = { kind: 'stopped', text: 'Your attacks kept meeting a guard or a duck. A THROW beats a BLOCK; a KICK beats a DUCK. Mix in the one that answers what it shows.' };
    else out.tip = { kind: 'mix', text: 'Look at the key beats above: change the move on the beat that cost you most, and keep the rest of the plan.' };
    return out;
  }

  // ---- local practice record (AUD-033) ------------------------------------------

  const PROGRESS_VERSION = 1;
  // The recommended order: read a pattern, punish recovery, crack a guard,
  // spend without a pattern to read, out-budget a budgeter, then adapt.
  const LADDER = Object.freeze([
    { npc: 'jabber-v1', step: 'READ A PATTERN', goal: 'Duck the jabs and punish the recover.' },
    { npc: 'kicker-v1', step: 'PUNISH THE RECOVERY', goal: 'Big kicks cost stamina; hit it while it vents.' },
    { npc: 'turtle-v1', step: 'CRACK A GUARD', goal: 'Throws and low attacks beat a wall of blocks.' },
    { npc: 'random-v1', step: 'SPEND WISELY', goal: 'No pattern to read: win on stamina and safe trades.' },
    { npc: 'mixed-v1', step: 'OUT-BUDGET A BUDGETER', goal: 'It manages stamina too; manage yours better.' },
    { npc: 'scout-v1', step: 'ADAPT', goal: 'It adapts to what you did last round. Change before it does.' },
  ]);

  function emptyProgress() { return { v: PROGRESS_VERSION, rules: {}, seen: [], steps: {} }; }

  /* Reads a stored record. Anything malformed or from another version gives
   * an empty record with damaged=true, so the page can say so. */
  function parseProgress(text) {
    if (text == null) return { p: emptyProgress(), damaged: false };
    let j;
    try { j = JSON.parse(text); } catch (e) { return { p: emptyProgress(), damaged: true }; }
    const okRec = r => r && typeof r === 'object' && ['w', 'l', 'd'].every(k => Number.isInteger(r[k]) && r[k] >= 0);
    if (!j || j.v !== PROGRESS_VERSION || typeof j.rules !== 'object' || !j.rules || !Array.isArray(j.seen)) return { p: emptyProgress(), damaged: true };
    const p = emptyProgress();
    for (const [rv, byNpc] of Object.entries(j.rules)) {
      if (!/^[a-z0-9.-]{1,64}$/.test(rv) || !byNpc || typeof byNpc !== 'object') continue;
      for (const [npc, r] of Object.entries(byNpc)) {
        if (!N.ROSTER.some(n => n.id === npc) || !okRec(r)) continue;
        (p.rules[rv] = p.rules[rv] || {})[npc] = {
          w: r.w, l: r.l, d: r.d,
          best: r.best && Number.isFinite(r.best.rank) && typeof r.best.label === 'string' ? { rank: r.best.rank, label: r.best.label.slice(0, 40) } : null,
        };
      }
    }
    p.seen = j.seen.filter(k => typeof k === 'string' && k.length <= 200).slice(-300);
    if (j.steps && typeof j.steps === 'object') for (const k of ['named', 'fought', 'debrief', 'build']) if (j.steps[k] === true) p.steps[k] = true;
    return { p, damaged: false };
  }

  /* How good a result is (higher is better) and how it reads. */
  function resultRank(s, side) {
    const P = side || 'A', o = s.outcome, me = P === 'A' ? s.state.a : s.state.b, op = P === 'A' ? s.state.b : s.state.a;
    const margin = me.hp - op.hp;
    if (o.winner === P && o.result === 'KO') return { rank: 3000 - 100 * s.state.round_index + margin, label: 'WIN · KO R' + (s.state.round_index + 1), outcome: 'w' };
    if (o.winner === P) return { rank: 2000 + margin, label: 'WIN · +' + margin + ' HP', outcome: 'w' };
    if (!o.winner) return { rank: 1000, label: o.result === 'DOUBLE_KO' ? 'DRAW · DOUBLE KO' : 'DRAW', outcome: 'd' };
    return { rank: 100 + margin, label: o.result === 'KO' ? 'LOSS · KO R' + (s.state.round_index + 1) : 'LOSS · ' + margin + ' HP', outcome: 'l' };
  }

  /* Adds a finished fight once (key = the fight's own share identity).
   * Returns { added, rec, improved, milestone } and mutates p. */
  function recordResult(p, s, key) {
    const rv = s.rules_version;
    const byNpc = p.rules[rv] = p.rules[rv] || {};
    const rec = byNpc[s.npc] = byNpc[s.npc] || { w: 0, l: 0, d: 0, best: null };
    if (p.seen.includes(key)) return { added: false, rec, improved: false, milestone: null };
    const before = laddersDone(p, rv);
    const r = resultRank(s, 'A');
    rec[r.outcome]++;
    const improved = !rec.best || r.rank > rec.best.rank;
    if (improved) rec.best = { rank: r.rank, label: r.label };
    p.seen.push(key);
    if (p.seen.length > 300) p.seen = p.seen.slice(-300);
    p.steps.fought = true;
    const after = laddersDone(p, rv);
    const milestone = LADDER.find(x => after.includes(x.npc) && !before.includes(x.npc)) || null;
    return { added: true, rec, improved, milestone, result: r };
  }

  const laddersDone = (p, rv) => LADDER.filter(x => ((p.rules[rv] || {})[x.npc] || {}).w > 0).map(x => x.npc);

  /* The first ladder step not yet won under this ruleset, or null when clear. */
  function nextChallenge(p, rv) {
    const done = laddersDone(p, rv);
    return LADDER.find(x => !done.includes(x.npc)) || null;
  }

  /* Fights recorded under other rulesets: kept, never combined. */
  function otherRulesets(p, rv) {
    return Object.entries(p.rules).filter(([k]) => k !== rv).map(([k, byNpc]) => ({ rules: k, fights: Object.values(byNpc).reduce((n, r) => n + r.w + r.l + r.d, 0) })).filter(x => x.fights > 0);
  }

  return Object.freeze({
    SHARE_VERSION, MAX_TAIL, planCode, shareCode, resultCheck, parseShare, replayShare,
    debrief, betterRound,
    LADDER, PROGRESS_VERSION, emptyProgress, parseProgress, resultRank, recordResult, nextChallenge, laddersDone, otherRulesets,
  });
});
