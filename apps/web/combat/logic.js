/* Pure spectator logic for combat.html: no DOM, no fetch, no clock.
 *
 * Everything the page shows about a fight is re-derived here from the revealed
 * plan bytes with combat/engine.js. The exported traces and outcome are only
 * compared against; they are never displayed as if they were checked.
 *
 *   deriveReplay   plans -> round-by-round engine results (the only source the
 *                  replay view renders)
 *   verifyReplay   api.md section 4 checks, each PASS / FAIL / UNAVAILABLE,
 *                  and the honest level they add up to
 *   timeline       the frames a replay steps through (beats, breaks, unplayed
 *                  suffix, end)
 *   explainSide    combat.md section 9 sentences for one side of one beat
 *   fighterStats   observed play from completed fights; never a prediction
 *   practice*      a local, free fight against a disclosed NPC
 *
 * <script src="combat/logic.js"> (after engine.js and npcs.js) defines
 * window.QDojoCombatLogic; in Node, require() returns the same object.
 */
'use strict';
(function (root, factory) {
  const node = typeof module === 'object' && module && module.exports;
  const api = node ? factory(require('./engine.js'), require('./npcs.js')) : factory(root.QDojoCombat, root.QDojoNpcs);
  if (node) module.exports = api;
  if (root) root.QDojoCombatLogic = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (E, N) {
  const NAMES = E.ACTIONS;
  const ID = {};
  NAMES.forEach((n, i) => { ID[n] = i; });
  const SIDES = ['A', 'B'];

  // ---- bytes -----------------------------------------------------------------

  const fromHex = N.fromHex, toHex = N.toHex;
  const ascii = s => Array.from(s, ch => ch.charCodeAt(0));
  function uLE(value, width) {
    // value may be a decimal string (u64 IDs); BigInt keeps it exact.
    let v = BigInt(value);
    if (v < 0n || v >= (1n << BigInt(8 * width))) throw new Error('value ' + value + ' does not fit u' + 8 * width);
    const out = [];
    for (let i = 0; i < width; i++) { out.push(Number(v & 255n)); v >>= 8n; }
    return out;
  }
  function readLE(bytes, at, width) {
    let v = 0n;
    for (let i = width - 1; i >= 0; i--) v = (v << 8n) | BigInt(bytes[at + i]);
    return v;
  }
  function concat(parts) {
    const n = parts.reduce((s, p) => s + p.length, 0);
    const out = new Uint8Array(n);
    let at = 0;
    for (const p of parts) { out.set(p, at); at += p.length; }
    return out;
  }
  function id32(hex, what) {
    if (typeof hex !== 'string' || !/^[0-9a-f]{64}$/.test(hex)) throw new Error(what + ' must be 64 lowercase hex digits');
    return fromHex(hex);
  }

  /* SHA-256 as an async bytes -> hex function. crypto.subtle where the page has
   * it (secure contexts, Node >= 19); the bundled synchronous one otherwise. */
  function defaultSha256() {
    const subtle = typeof globalThis !== 'undefined' && globalThis.crypto && globalThis.crypto.subtle;
    if (subtle) {
      const f = async bytes => toHex(new Uint8Array(await subtle.digest('SHA-256', bytes)));
      f.engine = 'crypto.subtle';
      return f;
    }
    const g = async bytes => toHex(N.sha256(bytes));
    g.engine = 'bundled JS SHA-256 (crypto.subtle unavailable)';
    return g;
  }

  // ---- ruleset digest (protocol.md section 2) --------------------------------

  function canonicalJson(v) {
    if (v === null) return 'null';
    if (typeof v === 'number') {
      if (!Number.isInteger(v)) throw new Error('canonical JSON takes integers only');
      return String(v);
    }
    if (typeof v === 'string') {
      if (!/^[\x20-\x7e]*$/.test(v)) throw new Error('canonical JSON takes printable ASCII strings only');
      return JSON.stringify(v);
    }
    if (typeof v === 'boolean') return String(v);
    if (Array.isArray(v)) return '[' + v.map(canonicalJson).join(',') + ']';
    return '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + canonicalJson(v[k])).join(',') + '}';
  }
  function rulesetDigest(rules, sha) {
    return sha(concat([ascii('qdojo/combat/rules/v1\0'), ascii(canonicalJson(rules))]));
  }

  /* The export's ruleset artifact wins when it hashes to the manifest digest;
   * the embedded copy is the fallback, and is used only if it hashes there too.
   * Returns { rules, source, digest, ok, note }. */
  async function chooseRuleset(opts) {
    const sha = opts.sha256 || defaultSha256(), want = opts.manifestDigest;
    const ex = opts.exported && opts.exported.rules;
    if (ex && typeof ex === 'object') {
      try {
        const d = await rulesetDigest(ex, sha);
        if (!want || d === want) return { rules: ex, source: 'export', digest: d, ok: !!want, note: 'Loaded from the export; its SHA-256 ' + (want ? 'equals the manifest digest.' : 'could not be compared (no manifest).') };
      } catch (e) { /* malformed artifact: fall through to the embedded copy */ }
    }
    // `embedded` is one ruleset or a list of them (ruleset.js embeds every
    // packaged candidate): use the one whose digest the manifest names.
    const list = Array.isArray(opts.embedded) ? opts.embedded : [opts.embedded];
    let rules = list[0], d = await rulesetDigest(rules, sha);
    for (const r of list.slice(1)) {
      if (!want || d === want) break;
      const x = await rulesetDigest(r, sha);
      if (x === want) { rules = r; d = x; }
    }
    const why = ex ? 'The export\'s ruleset artifact does not hash to the manifest digest; ' : 'The export has no ruleset body; ';
    return { rules, source: 'embedded', digest: d, ok: !want || d === want, note: why + 'using the embedded ' + rules.semantic_version + ' copy, which ' + (!want ? 'could not be compared.' : d === want ? 'hashes to the manifest digest.' : 'does NOT hash to the manifest digest.') };
  }

  // ---- fight context (protocol.md section 2) ---------------------------------

  const CONTEXT_LEN = 254 + 2 * 136;
  const MODES = ['ranked', 'duel', 'cup', 'exhibition'];

  function parseContext(hex) {
    const b = fromHex(hex);
    if (b.length !== CONTEXT_LEN) throw new Error('context is ' + b.length + ' bytes, expected ' + CONTEXT_LEN);
    let at = 0;
    const raw = n => { const s = toHex(b.subarray(at, at + n)); at += n; return s; };
    const num = n => { const v = readLE(b, at, n); at += n; return v; };
    const ctx = {
      network_id: raw(32), contract_id: raw(32), contest_id: String(num(8)), fight_id: String(num(8)),
      mode: MODES[Number(num(1))] || 'unknown', series_format: Number(num(1)), cup_id: String(num(8)),
      season_id: Number(num(4)), start_tick: String(num(8)), ruleset_digest: raw(32),
      commit_ticks: Number(num(2)), reveal_ticks: Number(num(2)), fee_profile_id: Number(num(4)),
      stake_per_fighter: String(num(8)), rake_bps: Number(num(2)), house_bps: Number(num(2)),
      dev_bps: Number(num(2)), share_bps: Number(num(2)),
      house_recipient: raw(32), dev_recipient: raw(32), share_recipient: raw(32), participants: {},
    };
    for (const s of SIDES) {
      ctx.participants[s] = {
        fighter_id: raw(32), owner: raw(32), operator: raw(32), auth_version: Number(num(4)),
        payout_recipient: raw(32), lifetime_rating: Number(num(2)), season_rating: Number(num(2)),
      };
    }
    return ctx;
  }

  function stateBytes(s) { return fromHex(E.encodeState(s)); }
  function roundStateBytes(contextDigestHex, roundIndex, a, b) {
    return concat([ascii('qdojo/combat/state/v1\0'), id32(contextDigestHex, 'context_digest'), [roundIndex], stateBytes(a), stateBytes(b)]);
  }
  function commitmentPreimage(f) {
    const plan = fromHex(f.plan_bytes);
    if (plan.length !== 7) throw new Error('plan is seven bytes');
    return concat([
      ascii('qdojo/combat/commit/v1\0'), id32(f.network_id, 'network_id'), id32(f.contract_id, 'contract_id'),
      uLE(f.fight_id, 8), uLE(f.round_index, 1), id32(f.context_digest, 'context_digest'),
      id32(f.round_state_digest, 'round_state_digest'), id32(f.fighter_id, 'fighter_id'),
      id32(f.operator, 'operator'), uLE(f.auth_version, 4), id32(f.salt, 'salt'), plan,
    ]);
  }

  // ---- independent replay ----------------------------------------------------

  const planIds = p => ({ actions: p.actions.map(a => (typeof a === 'number' ? a : ID[a])), power_slot: p.power_slot });
  const samePlan = (x, y) => x.power_slot === y.power_slot && x.actions.length === y.actions.length && x.actions.every((a, i) => a === y.actions[i]);
  const stateEq = (x, y) => !!x && !!y && ['hp', 'stamina', 'opening', 'guard_streak', 'power_available'].every(k => x[k] === y[k]);

  /* Resolves every revealed round from the fight's initial state, chaining the
   * engine's own end states. Uses the committed plan bytes; the JSON plans are
   * a display copy and are compared in verification, never used here. */
  function deriveReplay(rules, replay) {
    const out = { rounds: [], outcome: null, end: null, error: null };
    let state = E.newFight(rules);
    try {
      for (const r of replay.rounds || []) {
        if (out.outcome) throw new Error('a round is recorded after the fight ended');
        if (r.round_index !== state.round_index) throw new Error('round ' + r.round_index + ' is out of order (expected ' + state.round_index + ')');
        const pa = E.decodePlan(r.plan_bytes.A, rules), pb = E.decodePlan(r.plan_bytes.B, rules);
        const res = E.resolveRound(rules, state, pa, pb);
        out.rounds.push({
          round_index: r.round_index, start: state, plans: { A: pa, B: pb }, result: res,
          unexecuted: { A: pa.actions.slice(res.executed), B: pb.actions.slice(res.executed) },
        });
        state = res.end;
        out.outcome = res.outcome;
      }
    } catch (e) {
      out.error = e.message;
    }
    out.end = state;
    return out;
  }

  const namesOf = ids => ids.map(i => NAMES[i]);
  const TRACE_KEYS = ['intended', 'effective', 'power', 'cost', 'cost_paid', 'base_damage', 'bonus_damage', 'computed_damage', 'actual_hp_lost', 'strain', 'recovered'];
  // Newer exports split the bonus; older ones only carry bonus_damage.
  const OPTIONAL_TRACE_KEYS = ['opening_bonus', 'power_bonus'];

  function compareTrace(mine, theirs, where) {
    if (!theirs) return where + ': beat missing from the export';
    for (const k of TRACE_KEYS.concat(OPTIONAL_TRACE_KEYS.filter(k => k in theirs))) {
      const want = (k === 'intended' || k === 'effective') ? NAMES[mine[k]] : mine[k];
      if (theirs[k] !== want) return where + ' ' + k + ': export says ' + JSON.stringify(theirs[k]) + ', engine says ' + JSON.stringify(want);
    }
    if (!stateEq(mine.before, theirs.before)) return where + ': pre-beat state differs';
    if (!stateEq(mine.after, theirs.after)) return where + ': post-beat state differs';
    if (JSON.stringify(mine.reasons) !== JSON.stringify(theirs.reasons)) return where + ' reasons: export ' + JSON.stringify(theirs.reasons) + ', engine ' + JSON.stringify(mine.reasons);
    return null;
  }

  // Every difference between the export's claims and the independent replay.
  function replayMismatches(replay, derived) {
    const bad = [];
    if (derived.error) bad.push('engine refused the revealed plans: ' + derived.error);
    derived.rounds.forEach((d, i) => {
      const r = replay.rounds[i], res = d.result, tag = 'round ' + d.round_index;
      if (!r.start || !stateEq(r.start.A, d.start.a) || !stateEq(r.start.B, d.start.b)) bad.push(tag + ': published start state differs from the replayed one');
      if (r.executed_beats !== res.executed) bad.push(tag + ': export says ' + r.executed_beats + ' beats executed, engine ' + res.executed);
      if (!Array.isArray(r.beats) || r.beats.length !== res.beats.length) bad.push(tag + ': export has ' + (r.beats || []).length + ' beats, engine ' + res.beats.length);
      res.beats.forEach((bt, k) => {
        const theirs = (r.beats || [])[k];
        for (const s of SIDES) {
          const m = compareTrace(bt[s.toLowerCase()], theirs && theirs[s], tag + ' beat ' + k + ' ' + s);
          if (m) bad.push(m);
        }
      });
      for (const s of SIDES) {
        if (JSON.stringify((r.unexecuted || {})[s] || []) !== JSON.stringify(namesOf(d.unexecuted[s]))) bad.push(tag + ' ' + s + ': unexecuted suffix differs');
      }
      if (!r.end || !stateEq(r.end.A, res.end.a) || !stateEq(r.end.B, res.end.b)) bad.push(tag + ': published end state differs');
      // A terminal round has no break. The reference exporter writes {A:0,B:0}
      // there rather than null; both are read as "no recovery happened".
      const br = res.break_recovery;
      const theirsBr = r.break_recovery && (r.break_recovery.A || r.break_recovery.B || !res.outcome) ? r.break_recovery : null;
      if (JSON.stringify(theirsBr) !== JSON.stringify(br ? { A: br.a, B: br.b } : null)) bad.push(tag + ': break recovery differs');
    });
    const forfeit = isForfeit(replay);
    if (forfeit && 'forfeit_round' in replay && replay.forfeit_round !== derived.end.round_index) {
      bad.push('forfeit_round: export says ' + replay.forfeit_round + ', the replayed state is at round ' + derived.end.round_index);
    }
    // A fight still in progress claims no outcome; its revealed rounds must
    // then not have ended it either.
    const claimsEnd = !!replay.outcome || !!(replay.result && replay.result.kind);
    if (!forfeit && !claimsEnd) {
      if (derived.outcome) bad.push('the revealed rounds already ended the fight by ' + derived.outcome.result + ', but the export shows it in progress');
    } else if (!forfeit) {
      const o = replay.outcome || {};
      if (!derived.outcome) bad.push('the revealed rounds do not end the fight, but the export claims ' + (o.result || 'a result'));
      else if (o.winner !== derived.outcome.winner || o.result !== derived.outcome.result) {
        bad.push('outcome: export says ' + (o.result || '?') + ' winner ' + o.winner + ', engine says ' + derived.outcome.result + ' winner ' + derived.outcome.winner);
      }
      if (replay.result && 'winner' in replay.result && replay.result.winner !== (derived.outcome || {}).winner) bad.push('result record names a different winner');
    } else if (derived.outcome) {
      bad.push('the export records a forfeit, but the revealed rounds already ended the fight by ' + derived.outcome.result);
    }
    if (replay.final && (derived.rounds.length || forfeit)) {
      if (!stateEq(replay.final.A, derived.end.a) || !stateEq(replay.final.B, derived.end.b)) bad.push('final state differs from the replayed one');
    }
    return bad;
  }

  function isForfeit(x) {
    const r = x && x.result;
    const k = ['FORFEIT', 'DOUBLE_FAULT', 'VOID'];
    return !!r && (k.includes(r.kind) || k.includes(r.result) || !!(x.outcome && k.includes(x.outcome.result)));
  }

  // ---- verification levels (api.md section 4) --------------------------------

  const LEVELS = {
    COMBAT_VERIFIED: 'Every relevant check passed, including chain confirmation.',
    REPLAY_MATCH: 'Commitments and an independent replay match. Chain inclusion is not established by this export.',
    HASH_MATCH_ONLY: 'Hashes match, but there was nothing to replay independently.',
    UNVERIFIED: 'No revealed plan could be checked, so the result itself is not independently verified.',
    FAILED: 'At least one check failed. Do not trust this record.',
  };

  function levelOf(checks) {
    const st = Object.fromEntries(checks.map(c => [c.id, c.status]));
    if (checks.some(c => c.status === 'FAIL')) return 'FAILED';
    if (checks.every(c => c.status === 'PASS')) return 'COMBAT_VERIFIED';
    if (st.ruleset === 'PASS' && st.commitments === 'PASS' && st.replay === 'PASS') return 'REPLAY_MATCH';
    if (st.commitments === 'PASS') return 'HASH_MATCH_ONLY';
    return 'UNVERIFIED';
  }

  /* opts: { rules, manifest, sha256 (async bytes -> hex) }.
   * Returns { checks: [{id, label, status, evidence, details}], level, derived }. */
  async function verifyReplay(replay, opts) {
    const rules = opts.rules, sha = opts.sha256 || defaultSha256(), manifest = opts.manifest;
    const checks = [];
    const add = (id, label, status, evidence, details) => checks.push({ id, label, status, evidence, details: details || [] });

    // 1. ruleset digest
    const mine = await rulesetDigest(rules, sha);
    let ctx = null, ctxErr = null;
    try { ctx = parseContext(replay.context_bytes); } catch (e) { ctxErr = e.message; }
    if (!manifest) add('ruleset', 'Ruleset digest matches the manifest', 'UNAVAILABLE', 'No manifest was loaded.');
    else {
      const claims = [['manifest', manifest.ruleset_digest], ['replay', replay.ruleset_digest], ['fight context', ctx && ctx.ruleset_digest]];
      const off = claims.filter(([, v]) => v !== mine);
      add('ruleset', 'Ruleset digest matches the manifest', off.length ? 'FAIL' : 'PASS',
        off.length ? 'Recomputed ' + mine + '; differs from ' + off.map(([k, v]) => k + ' ' + (v || 'missing')).join(', ') + '.'
          : 'Recomputed SHA-256 of the canonical ruleset (' + rules.semantic_version + ') = ' + mine + ', equal to the manifest, replay and fight context.');
    }

    // 2. inputs confirmed on chain: a same-source export cannot establish it.
    const ev = replay.evidence || {};
    const claimed = ev.inputs_confirmed;
    const status2 = claimed === 'FAIL' ? 'FAIL' : claimed === 'PASS' && ev.source !== 'same-source export' ? 'PASS' : 'UNAVAILABLE';
    add('inputs', 'Input transactions confirmed on chain', status2,
      status2 === 'UNAVAILABLE' ? 'Export evidence: inputs_confirmed=' + (claimed || 'missing') + ', source=' + (ev.source || 'unknown') + '. A same-source export cannot prove chain inclusion; check an independent node.'
        : 'Export evidence: inputs_confirmed=' + claimed + ' (' + (ev.source || 'unknown source') + ').');

    // 3. context, round-start digests and commitments
    const derived = deriveReplay(rules, replay);
    const cdet = [];
    let cfail = false;
    let ctxDigest = null;
    if (ctxErr) { cfail = true; cdet.push('context bytes unreadable: ' + ctxErr); } else {
      ctxDigest = await sha(concat([ascii('qdojo/combat/context/v1\0'), fromHex(replay.context_bytes)]));
      const okDigest = ctxDigest === replay.context_digest;
      cfail = cfail || !okDigest;
      cdet.push((okDigest ? 'PASS' : 'FAIL') + ' context_digest ' + ctxDigest + (okDigest ? '' : ' (export says ' + replay.context_digest + ')'));
      const idOk = ctx.network_id === replay.network_id && ctx.contract_id === replay.contract_id && ctx.fight_id === String(replay.fight_id);
      cfail = cfail || !idOk;
      cdet.push((idOk ? 'PASS' : 'FAIL') + ' context names network, contract and fight ' + ctx.fight_id);
      for (const s of SIDES) {
        const p = ctx.participants[s], q = (replay.fighters || {})[s] || {};
        const ok = p.fighter_id === q.fighter_id && p.operator === q.operator && p.auth_version === q.auth_version;
        cfail = cfail || !ok;
        if (!ok) cdet.push('FAIL fighter ' + s + ' in the export differs from the committed context');
      }
    }
    const rounds = replay.rounds || [];
    for (let i = 0; i < rounds.length; i++) {
      const r = rounds[i], d = derived.rounds[i], tag = 'round ' + r.round_index;
      if (!ctx || !ctxDigest) break;
      if (!d) { cfail = true; cdet.push('FAIL ' + tag + ': cannot rebuild its start state (' + (derived.error || 'replay stopped') + ')'); continue; }
      const rsd = await sha(roundStateBytes(ctxDigest, r.round_index, d.start.a, d.start.b));
      const rsdOk = rsd === r.round_state_digest;
      cfail = cfail || !rsdOk;
      cdet.push((rsdOk ? 'PASS' : 'FAIL') + ' ' + tag + ' round_state_digest ' + rsd.slice(0, 16) + '...' + (rsdOk ? '' : ' (export ' + String(r.round_state_digest).slice(0, 16) + '...)'));
      for (const s of SIDES) {
        const p = ctx.participants[s];
        let got = null, err = null;
        try {
          got = await sha(commitmentPreimage({
            network_id: ctx.network_id, contract_id: ctx.contract_id, fight_id: ctx.fight_id,
            round_index: r.round_index, context_digest: ctxDigest, round_state_digest: rsd,
            fighter_id: p.fighter_id, operator: p.operator, auth_version: p.auth_version,
            salt: r.salts[s], plan_bytes: r.plan_bytes[s],
          }));
        } catch (e) { err = e.message; }
        const want = (r.commitments || {})[s];
        const ok = !err && got === want;
        let planOk = true;
        try { planOk = samePlan(planIds(r.plans[s]), E.decodePlan(r.plan_bytes[s])); } catch (e) { planOk = false; }
        cfail = cfail || !ok || !planOk;
        cdet.push((ok ? 'PASS' : 'FAIL') + ' ' + tag + ' ' + s + ' plan+salt -> ' + (got ? got.slice(0, 16) + '...' : 'error: ' + err) + (ok ? ' = commitment' : ' != commitment ' + String(want).slice(0, 16) + '...'));
        if (!planOk) cdet.push('FAIL ' + tag + ' ' + s + ': displayed plan differs from the committed plan bytes');
      }
    }
    if (!rounds.length) {
      add('commitments', 'Revealed plans and salts match their commitments', ctxErr ? 'FAIL' : cfail ? 'FAIL' : 'UNAVAILABLE',
        (cfail ? 'The fight context does not match its digest or the export. ' : 'Fight context digest recomputed and matches. ') +
        (isForfeit(replay) ? 'No plan was revealed before the forfeit, so there is no commitment to open.' : 'No revealed rounds in this export.'), cdet);
    } else {
      add('commitments', 'Revealed plans and salts match their commitments', cfail ? 'FAIL' : 'PASS',
        cfail ? 'At least one digest or commitment does not match; see details.'
          : 'SHA-256 over protocol.md section 2 preimages (' + (sha.engine || 'SHA-256') + '): context, ' + rounds.length + ' round-start digest(s) and ' + 2 * rounds.length + ' commitments recomputed.', cdet);
    }

    // 4. independent integer replay
    const bad = replayMismatches(replay, derived);
    if (!rounds.length) {
      add('replay', 'Independent replay reproduces every post-state and the outcome', bad.length ? 'FAIL' : 'UNAVAILABLE',
        bad.length ? bad[0] : 'Forfeit with no revealed round: there is nothing to replay. The result is a protocol timeout, not a knockout; its deadline is not checkable from this export.', bad);
    } else {
      const beats = derived.rounds.reduce((n, d) => n + d.result.beats.length, 0);
      add('replay', 'Independent replay reproduces every post-state and the outcome', bad.length ? 'FAIL' : 'PASS',
        bad.length ? bad.length + ' mismatch(es); first: ' + bad[0]
          : 'combat/engine.js replayed ' + derived.rounds.length + ' round(s), ' + beats + ' beats from the committed plan bytes; every state, trace and ' +
            (isForfeit(replay) ? 'the pre-forfeit state match (forfeit is a timeout, not replayed).' : derived.outcome ? 'the outcome (' + derived.outcome.result + ') match.' : 'the state so far match (fight still in progress).'), bad);
    }

    // 5. accounting and rating, recomputed from the settlement and the committed terms.
    const acc = ctx ? checkSettlement(replay, ctx, derived) : { status: 'FAIL', evidence: 'Fight context unreadable.', details: [] };
    add('accounting', 'Accounting and rating follow the outcome', acc.status, acc.evidence, acc.details);

    return { checks, level: levelOf(checks), derived };
  }

  // ---- settlement (api.md section 4 check 5) ----------------------------------

  const BPS = 10000n;

  /* docs/competition.md section 1: integer, zero-sum, from both OLD ratings.
   * Returns the amount moved from B to A. */
  function ratingDelta(ra, rb, scoreA) {
    const ea = Math.min(1900, Math.max(100, 1000 + 2 * (ra - rb)));
    const raw = 32 * (scoreA - ea);
    let d = Math.sign(raw) * Math.floor(Math.abs(raw) / 2000);
    if (d > 0) d = Math.min(d, rb, 3000 - ra);
    else if (d < 0) d = -Math.min(-d, ra, 3000 - rb);
    return d || 0;
  }

  /* Protocol fee split: rake = floor(purse * rake_bps / 1e4); dev and share
   * are floored shares of the rake; the house keeps the rest. */
  function splitPurse(purse, t) {
    const rake = purse * BigInt(t.rake_bps) / BPS;
    const dev = rake * BigInt(t.dev_bps) / BPS, share = rake * BigInt(t.share_bps) / BPS;
    return { winner: purse - rake, rake, house: rake - dev - share, dev, share };
  }

  function checkSettlement(replay, ctx, derived) {
    const st = replay.settlement;
    const details = [];
    if (!st) {
      return {
        status: 'UNAVAILABLE', details,
        evidence: 'No settlement on this fight' + (replay.mode === 'duel' || replay.mode === 'cup' ? ' (a series settles once, on its last fight)' : '') + '; nothing to check.',
      };
    }
    if (ctx.mode === 'cup') return { status: 'UNAVAILABLE', details, evidence: 'Cup purses settle at the cup level, not per contest.' };
    let fail = false;
    const note = (ok, text) => { details.push((ok ? 'PASS ' : 'FAIL ') + text); if (!ok) fail = true; };
    const cr = st.contest_result || {}, kind = cr.kind, winner = cr.winner == null ? null : cr.winner;
    let stake;
    try { stake = BigInt(st.stake_per_fighter); } catch (e) { stake = -1n; }
    note(stake >= 0n && String(stake) === ctx.stake_per_fighter, 'stake ' + st.stake_per_fighter + ' per fighter equals the committed context (' + ctx.stake_per_fighter + ')');
    const series = st.series_fights || [];
    note(series[series.length - 1] === String(replay.fight_id), 'settled on the last fight of its series (' + series.join(', ') + ')');
    // A one-fight contest's result must agree with this fight.
    if (series.length === 1) {
      const mine = isForfeit(replay) ? (replay.result || {}) : { kind: 'COMBAT', winner: derived.outcome ? derived.outcome.winner : undefined };
      const mw = mine.winner == null ? null : mine.winner;
      note(kind === mine.kind && winner === mw, 'contest result ' + kind + ' winner ' + winner + ' matches this fight (' + mine.kind + ' winner ' + mw + ')');
    } else if (!isForfeit(replay) && kind === 'COMBAT') {
      note(derived.outcome && derived.outcome.winner === winner, 'series winner ' + winner + ' also won this deciding fight');
      details.push('NOTE earlier series fights (' + series.slice(0, -1).join(', ') + ') are verified on their own pages, not re-tallied here');
    }
    // Credits: exact deltas at termination.
    const got = {};
    for (const [who, v] of Object.entries(st.credits || {})) {
      let n = null;
      try { n = /^[0-9]+$/.test(String(v)) ? BigInt(v) : null; } catch (e) { n = null; }
      if (n === null) note(false, 'credit to ' + who.slice(0, 8) + '... is not a decimal amount: ' + v);
      else if (n !== 0n) got[who] = n;
    }
    if (stake >= 0n) {
      if ((kind === 'COMBAT' || kind === 'FORFEIT') && (winner === 'A' || winner === 'B')) {
        // A duel's single rake applies to the series purse: one split, once.
        const sp = splitPurse(2n * stake, ctx);
        const exp = {};
        const add = (who, v) => { if (v > 0n) exp[who] = (exp[who] || 0n) + v; };
        add(ctx.participants[winner].payout_recipient, sp.winner);
        add(ctx.house_recipient, sp.house);
        add(ctx.dev_recipient, sp.dev);
        add(ctx.share_recipient, sp.share);
        for (const k of new Set(Object.keys(got).concat(Object.keys(exp)))) {
          note((got[k] || 0n) === (exp[k] || 0n), 'credit ' + k.slice(0, 8) + '...: export ' + String(got[k] || 0n) + ', expected ' + String(exp[k] || 0n));
        }
        details.push('NOTE purse ' + String(2n * stake) + ', rake ' + String(sp.rake) + ' (' + ctx.rake_bps + ' bps): winner ' + String(sp.winner) +
          ', house ' + String(sp.house) + ', dev ' + String(sp.dev) + ', share ' + String(sp.share));
      } else {
        // Draw, double fault or void: each stake back to its payer, no rake.
        // Each stake goes back to the side's payer, exactly; nobody else is credited.
        const payers = st.payers || {};
        const exp = {};
        for (const x of SIDES) {
          const p = payers[x];
          if (typeof p !== 'string' || !/^[0-9a-f]{64}$/.test(p)) { note(false, 'settlement names no valid payer for side ' + x); continue; }
          if (stake > 0n) exp[p] = (exp[p] || 0n) + stake;
        }
        for (const k of new Set(Object.keys(got).concat(Object.keys(exp)))) {
          const role = SIDES.filter(x => payers[x] === k).map(x => 'payer ' + x).join(', ') || 'not a payer';
          note((got[k] || 0n) === (exp[k] || 0n), 'refund ' + k.slice(0, 8) + '... (' + role + '): export ' + String(got[k] || 0n) + ', expected ' + String(exp[k] || 0n) + ' (stake back, no rake)');
        }
      }
    }
    // Ratings: ranked only; combat results and unilateral forfeits move them.
    if (ctx.mode === 'ranked') {
      const r = st.ratings;
      if (!r || !r.A || !r.B) note(false, 'ranked settlement carries no ratings');
      else {
        const rated = kind === 'COMBAT' || kind === 'FORFEIT';
        const score = winner === 'A' ? 2000 : winner === 'B' ? 0 : 1000;
        for (const [key, snap] of [['lifetime', 'lifetime_rating'], ['season', 'season_rating']]) {
          const [ap, aq] = r.A[key] || [], [bp, bq] = r.B[key] || [];
          note(ap === ctx.participants.A[snap] && bp === ctx.participants.B[snap], key + ' pre ratings ' + ap + '/' + bp + ' equal the snapshot in the fight context');
          const ok = Number.isInteger(ap) && Number.isInteger(bp) && ap >= 0 && bp >= 0 && ap <= 3000 && bp <= 3000;
          const d = rated && ok ? ratingDelta(ap, bp, score) : 0;
          note(ok && aq === ap + d && bq === bp - d, key + ' ' + ap + '/' + bp + ' -> ' + aq + '/' + bq +
            (rated ? '; formula gives ' + (ap + d) + '/' + (bp - d) : '; unrated (' + kind + '), so unchanged'));
        }
      }
    } else if (st.ratings) {
      const same = SIDES.every(x => ['lifetime', 'season'].every(k => { const v = (st.ratings[x] || {})[k] || []; return v[0] === v[1]; }));
      note(same, ctx.mode + ' fights never change ratings');
    }
    return {
      status: fail ? 'FAIL' : 'PASS', details,
      evidence: fail ? 'The settlement does not follow the outcome and the committed terms; see details.'
        : 'Credits recomputed from the committed fee terms (rake ' + ctx.rake_bps + ' bps)' + (ctx.mode === 'ranked' ? ' and ratings from the integer formula' : '; no rating change') +
          ': all match. Credits are ledger entries, not proof that a withdrawal executed.',
    };
  }

  // ---- replay timeline -------------------------------------------------------

  /* Frames in display order. Every state shown comes from the derived replay. */
  function timeline(replay, derived) {
    const frames = [];
    const init = derived.rounds.length ? derived.rounds[0].start : null;
    if (init) frames.push({ kind: 'start', round: 0, a: init.a, b: init.b });
    for (const d of derived.rounds) {
      const res = d.result;
      if (d.round_index > 0) frames.push({ kind: 'round', round: d.round_index, a: d.start.a, b: d.start.b });
      res.beats.forEach(bt => frames.push({
        kind: 'beat', round: d.round_index, beat: bt.beat, a: bt.a.after, b: bt.b.after, trace: { A: bt.a, B: bt.b },
      }));
      const suffix = d.unexecuted;
      if (suffix.A.length || suffix.B.length) {
        const lastA = res.end.a, lastB = res.end.b;
        for (let k = 0; k < suffix.A.length; k++) {
          frames.push({
            kind: 'unexecuted', round: d.round_index, beat: res.executed + k, a: lastA, b: lastB,
            intended: { A: suffix.A[k], B: suffix.B[k] },
            power: { A: d.plans.A.power_slot === res.executed + k, B: d.plans.B.power_slot === res.executed + k },
          });
        }
      }
      if (res.break_recovery) {
        frames.push({ kind: 'break', round: d.round_index, a: res.end.a, b: res.end.b, recovery: { A: res.break_recovery.a, B: res.break_recovery.b }, before: res.before_break });
      }
    }
    const endState = derived.rounds.length ? derived.end : null;
    if (isForfeit(replay)) {
      // The state at the deadline is the re-derived one (the fight's start
      // state when no round was played); no beat is invented.
      frames.push({ kind: 'forfeit', round: derived.end.round_index, a: derived.end.a, b: derived.end.b, result: replay.result, played: derived.rounds.length });
    } else if (derived.outcome) {
      frames.push({ kind: 'end', round: derived.rounds[derived.rounds.length - 1].round_index, a: endState.a, b: endState.b, outcome: derived.outcome });
    }
    return frames;
  }

  // ---- labels and explanations -----------------------------------------------

  const OTHER = { A: 'B', B: 'A' };

  function outcomeLabel(x) {
    if (isForfeit(x) && (x.result || {}).kind === 'DOUBLE_FAULT') {
      return { kind: 'timeout', short: 'DOUBLE FAULT', text: 'DOUBLE FAULT: both fighters missed the ' + String(x.result.stage || 'deadline').toLowerCase() + ' deadline. No winner; stakes refunded. Not a knockout.' };
    }
    if (isForfeit(x) && (x.result || {}).kind === 'VOID') {
      return { kind: 'timeout', short: 'VOID', text: 'VOID: the service could not complete this fight. No winner; stakes refunded. Not a knockout.' };
    }
    if (isForfeit(x)) {
      const r = x.result || {};
      const loser = r.winner ? OTHER[r.winner] : null;
      const stage = r.stage ? r.stage.toLowerCase() : 'deadline';
      return { kind: 'timeout', short: 'TIMEOUT', text: 'TIMEOUT: ' + (loser ? 'fighter ' + loser : 'a fighter') + ' missed the ' + stage + ' deadline' + (r.tick ? ' (tick ' + r.tick + ')' : '') + '. ' + (r.winner ? r.winner + ' wins by forfeit.' : 'No winner.') + ' Not a knockout.' };
    }
    const o = x && x.outcome;
    if (!o) return { kind: 'open', short: 'IN PROGRESS', text: 'No result yet.' };
    if (o.result === 'KO') return { kind: 'ko', short: 'KO', text: 'K.O. ' + o.winner + ' wins by knockout.' };
    if (o.result === 'DOUBLE_KO') return { kind: 'draw', short: 'DOUBLE KO', text: 'DOUBLE K.O. Both hit zero HP on the same beat: draw.' };
    if (o.result === 'HP') return { kind: 'hp', short: 'DECISION', text: o.winner + ' wins on remaining HP after three rounds.' };
    if (o.result === 'HP_TIE') return { kind: 'draw', short: 'DRAW', text: 'Equal HP after three rounds: draw.' };
    return { kind: 'other', short: String(o.result || '?'), text: String(o.result || 'Unknown result') + '.' };
  }

  const lc = n => NAMES[n].toLowerCase();

  /* Sentences for one side of one executed beat, from that side's trace and
   * the opponent's. who/them are display names. */
  /* Why a fighter was hit, in plain words (docs/model.md section 3): what its
   * own action could not stop. null when nothing hit it. */
  function causeOf(t, o) {
    if (o.computed_damage <= 0) return null;
    switch (t.effective) {
      case ID.RECOVER: return 'Recovering leaves a fighter wide open: any attack lands in full, and being hit cuts the recovery.';
      case ID.EXHAUSTED: return 'An unaffordable move becomes EXHAUSTED: no move at all, so the attack lands in full.';
      case ID.DUCK: return 'Ducking dodges jabs and throws, but not a kick.';
      case ID.BLOCK: return 'A block stops jabs and kicks, but not a throw.';
      case ID.THROW: return 'A throw loses to a jab or a kick: it is interrupted and takes the hit.';
      case ID.JAB:
        if (o.effective === ID.DUCK) return 'The duck slipped under the jab and countered.';
        return 'Both attacked on the same beat, so both hits landed: a trade.';
      case ID.KICK: return 'Both attacked on the same beat, so both hits landed: a trade.';
      default: return null;
    }
  }

  // openingDamage: the ruleset's opening bonus (4 in candidate 1, 8 in candidate 2).
  function explainSide(t, o, who, them, openingDamage = 4) {
    const out = [];
    const poss = x => (x === 'YOU' ? 'YOUR' : x + "'s");
    const act = lc(t.intended), oact = lc(o.effective);
    if (t.effective === ID.EXHAUSTED) {
      out.push(poss(who) + ' ' + act + ' cost ' + t.cost + ' with only ' + t.before.stamina + ' stamina left: EXHAUSTED, paid nothing and stood exposed' +
        (t.actual_hp_lost > 0 ? ', taking ' + o.computed_damage + ' from the ' + oact + '.' : '.'));
    } else {
      out.push(who + ' ' + act + (t.power ? ' (POWER)' : '') + ': paid ' + t.cost_paid + ' stamina.');
      if (t.computed_damage > 0) {
        const parts = ['base ' + t.base_damage];
        if (t.opening_bonus) parts.push('opening +' + t.opening_bonus);
        if (t.power_bonus) parts.push('power +' + t.power_bonus);
        out.push('Hit ' + them + ' for ' + t.computed_damage + (parts.length > 1 ? ' (' + parts.join(', ') + ')' : '') + '.');
      } else if (t.reasons.includes('BLOCKED')) out.push('Blocked by ' + them + ': zero HP damage.');
      else if (t.reasons.includes('EVADED')) out.push(them + ' ducked it: zero damage.');
      else if (t.reasons.includes('THROW_INTERRUPTED')) out.push(poss(them) + ' ' + oact + ' interrupted the throw.');
      else if (t.reasons.includes('THROW_CLASH')) out.push('Throw met throw: both fail, both pay.');
    }
    if (t.actual_hp_lost > 0 && t.effective !== ID.EXHAUSTED) {
      out.push('Took ' + o.computed_damage + ' from ' + poss(them) + ' ' + oact + (t.reasons.includes('RECOVERY_PUNISHED') ? ' while recovering' : '') +
        ': HP ' + t.before.hp + ' -> ' + t.after.hp + (t.actual_hp_lost < o.computed_damage ? ' (only ' + t.actual_hp_lost + ' HP was left)' : '') + '.');
      const why = causeOf(t, o);
      if (why) out.push('Why: ' + why);
    } else if (t.effective === ID.EXHAUSTED && t.actual_hp_lost > 0) {
      out.push('Why: ' + causeOf(t, o));
    } else if (o.computed_damage === 0 && t.effective === ID.BLOCK && o.effective !== ID.BLOCK && [ID.JAB, ID.KICK].includes(o.effective)) {
      out.push('Blocked ' + poss(them) + ' ' + oact + ': HP unchanged.');
    }
    if (t.strain > 0) out.push('Guard strain: -' + t.strain + ' stamina from blocking a kick (no HP lost).');
    if (t.recovered > 0) out.push('Recovered +' + t.recovered + ' stamina (now ' + t.after.stamina + ').');
    if (t.reasons.includes('OPENING_EXPIRED')) out.push('Opening expired unused.');
    if (t.reasons.includes('POWER_WASTED')) {
      out.push('Power spent with no damage: wasted. The power bonus only adds to a strike that lands, and ' +
        (o.effective === ID.BLOCK ? 'this one was blocked.' : o.effective === ID.DUCK ? 'this one was ducked.' : t.effective === ID.EXHAUSTED ? 'the move was never made.' : 'this one did not land.'));
    }
    if (t.effective === ID.DUCK && t.computed_damage > 0) out.push('Countered the ' + oact + ' from the duck.');
    if (t.reasons.includes('OPENING_EARNED')) out.push('Earned an OPENING: +' + openingDamage + ' on the next beat if it lands.');
    if (t.reasons.includes('DOUBLE_KO')) out.push('DOUBLE K.O.: both fighters reached 0 HP on the same beat, so the fight is a draw.');
    else if (t.reasons.includes('KO')) out.push(who + ' is knocked out (0 HP) by ' + poss(them) + ' ' + oact + '.');
    return out;
  }

  /* One sentence for a whole beat: what happened and why, both sides. */
  function beatHeadline(a, b, names) {
    const N = names || { A: 'A', B: 'B' };
    const act = t => NAMES[t.effective] + (t.power && t.effective !== ID.EXHAUSTED ? ' (POWER)' : '');
    const pair = [['A', a, b], ['B', b, a]];
    if (a.reasons.includes('DOUBLE_KO')) {
      return 'DOUBLE K.O.: ' + N.A + "'s " + act(a) + ' and ' + N.B + "'s " + act(b) + ' land together and both reach 0 HP: a draw.';
    }
    for (const [s, t, o] of pair) {
      if (t.reasons.includes('KO')) {
        const w = s === 'A' ? 'B' : 'A';
        return 'K.O.: ' + N[w] + "'s " + act(o) + ' (' + o.computed_damage + ') finishes ' + N[s] + ', who ' +
          (t.effective === ID.EXHAUSTED ? 'could not afford a ' + NAMES[t.intended] : 'chose ' + NAMES[t.effective]) + '. ' + causeOf(t, o);
      }
    }
    for (const [s, t] of pair) {
      if (t.effective === ID.EXHAUSTED) {
        return N[s] + ' could not afford ' + NAMES[t.intended] + ' (' + t.cost + ' stamina, had ' + t.before.stamina + ') and stood EXHAUSTED' +
          ((s === 'A' ? b : a).computed_damage > 0 ? ', taking ' + (s === 'A' ? b : a).computed_damage + '.' : '.');
      }
    }
    if (a.actual_hp_lost > 0 && b.actual_hp_lost > 0) {
      return 'TRADE: ' + N.A + "'s " + act(a) + ' and ' + N.B + "'s " + act(b) + ' both land (' + a.computed_damage + ' and ' + b.computed_damage + ').';
    }
    for (const [s, t, o] of pair) {
      if (t.computed_damage > 0) {
        const w = s === 'A' ? 'B' : 'A';
        return N[s] + "'s " + act(t) + ' hits ' + N[w] + "'s " + NAMES[o.effective] + ' for ' + t.computed_damage + '. ' + causeOf(o, t);
      }
    }
    for (const [s, t, o] of pair) {
      if (t.reasons.includes('POWER_WASTED')) {
        return N[s] + "'s powered " + NAMES[t.effective] + ' ' + (o.effective === ID.BLOCK ? 'is blocked' : o.effective === ID.DUCK ? 'is ducked' : 'misses') + ': no damage, and the power strike is spent.';
      }
    }
    if (a.reasons.includes('THROW_CLASH')) return 'Throw meets throw: both fail and both pay.';
    for (const [s, t, o] of pair) {
      if (t.reasons.includes('BLOCKED')) return N[s === 'A' ? 'B' : 'A'] + ' blocks ' + N[s] + "'s " + NAMES[t.effective] + ': no HP lost' + (o.strain ? ', ' + o.strain + ' stamina of guard strain.' : '.');
      if (t.reasons.includes('EVADED')) return N[s === 'A' ? 'B' : 'A'] + ' ducks ' + N[s] + "'s " + NAMES[t.effective] + ': no damage, and an opening for the next beat.';
    }
    return 'No damage: ' + N.A + ' ' + NAMES[a.effective] + ', ' + N.B + ' ' + NAMES[b.effective] + '.';
  }

  /* Hindsight for practice: against the opponent's recorded action on this
   * beat, which of my actions would have netted the most HP? Not a claim that
   * the opponent would have played the same way. */
  function hindsight(rules, before, mySide, trace) {
    const me = mySide === 'A' ? before.a : before.b, opp = mySide === 'A' ? before.b : before.a;
    const oppT = trace[OTHER[mySide]], myT = trace[mySide];
    if (me.hp === 0 || opp.hp === 0) return null;
    const net = (m, o) => o.actual_hp_lost - m.actual_hp_lost;
    const actual = net(myT, oppT);
    let best = null;
    for (const a of rules.submitted_action_ids) {
      const r = mySide === 'A' ? E.resolveBeat(rules, me, opp, a, oppT.intended, false, oppT.power) : E.resolveBeat(rules, opp, me, oppT.intended, a, oppT.power, false);
      const m = r.trace[mySide === 'A' ? 0 : 1], o = r.trace[mySide === 'A' ? 1 : 0];
      const v = net(m, o);
      if (!best || v > best.net) best = { action: a, net: v, dealt: o.actual_hp_lost, taken: m.actual_hp_lost };
    }
    if (!best || best.net <= actual) return null;
    return {
      action: best.action, net: best.net, actual,
      text: 'HINDSIGHT: against the recorded ' + lc(oppT.intended) + ', an unpowered ' + lc(best.action) + ' would have dealt ' + best.dealt +
        ' and taken ' + best.taken + ' (net ' + (best.net >= 0 ? '+' : '') + best.net + ' HP vs ' + (actual >= 0 ? '+' : '') + actual + '). Not proof the opponent would have played the same.',
    };
  }

  // ---- fighter scouting ------------------------------------------------------

  /* items: [{ replay, derived }] for fights this fighter was in. Counts only
   * executed effective actions from the independent replay; the unexecuted
   * suffix is reported separately and never counted as play. */
  function fighterStats(fid, items) {
    const perRound = [0, 1, 2].map(() => new Array(NAMES.length).fill(0));
    const unexecuted = new Array(NAMES.length).fill(0);
    const recoverByBeat = new Array(6).fill(0);
    const s = {
      fights: 0, replayed: 0, forfeits: 0, results: {}, perRound, unexecuted, recoverByBeat,
      recoverPunished: 0, recovers: 0,
      power: { rounds: 0, used: 0, landed: 0, wasted: 0, unplayed: 0, byRound: [0, 0, 0] },
      opening: { held: 0, converted: 0, earned: 0 }, exhausted: 0, beats: 0,
    };
    for (const { replay, derived } of items) {
      const side = replay.fighters.A.fighter_id === fid ? 'A' : replay.fighters.B.fighter_id === fid ? 'B' : null;
      if (!side) continue;
      s.fights++;
      const mode = replay.mode || 'unknown';
      const res = s.results[mode] || (s.results[mode] = { W: 0, L: 0, D: 0, FW: 0, FL: 0 });
      if (isForfeit(replay)) {
        s.forfeits++;
        res[replay.result.winner === side ? 'FW' : 'FL']++;
      } else if (derived.outcome) {
        const w = derived.outcome.winner;
        res[w === null ? 'D' : w === side ? 'W' : 'L']++;
      }
      if (derived.error) continue;
      if (derived.rounds.length) s.replayed++;
      const key = side.toLowerCase();
      for (const d of derived.rounds) {
        const plan = d.plans[side];
        if (plan.power_slot >= 0) {
          s.power.rounds++;
          if (plan.power_slot >= d.result.executed) s.power.unplayed++;
        }
        for (const bt of d.result.beats) {
          const t = bt[key];
          s.beats++;
          perRound[d.round_index][t.effective]++;
          if (t.effective === ID.EXHAUSTED) s.exhausted++;
          if (t.effective === ID.RECOVER) { s.recovers++; recoverByBeat[bt.beat]++; if (t.reasons.includes('RECOVERY_PUNISHED')) s.recoverPunished++; }
          if (t.power) { s.power.used++; s.power.byRound[d.round_index]++; if (t.power_bonus > 0) s.power.landed++; else s.power.wasted++; }
          if (t.before.opening === 1) { s.opening.held++; if (t.opening_bonus > 0) s.opening.converted++; }
          if (t.after.opening === 1) s.opening.earned++;
        }
        for (const a of d.unexecuted[side]) unexecuted[a]++;
      }
    }
    return s;
  }

  // ---- series (cups, duels) --------------------------------------------------

  /* Series scores are exported in fight-slot order: wins_a belongs to the
   * lexicographically smaller fighter ID (slot A), whatever order the pairing
   * lists its fighters in. Returns { fighter hex: wins }. */
  function seriesWins(a, b, wa, wb) {
    const out = {};
    if (!a || !b) { if (a) out[a] = wa; if (b) out[b] = wb; return out; }
    out[a < b ? a : b] = wa;
    out[a < b ? b : a] = wb;
    return out;
  }

  // ---- live site helpers (arena, leaderboard, freshness) ----------------------

  /* Phase and ticks left for an active fight, against the export's snapshot
   * tick. Ticks are time, never health. */
  function livePhase(summary, tick) {
    const phase = String(summary.phase || '');
    const last = phase === 'COMMIT' ? summary.commit_last : phase === 'REVEAL' ? summary.reveal_last : null;
    if (last == null || tick == null) return { phase, deadline: last == null ? null : String(last), left: null, overdue: false };
    const left = BigInt(last) - BigInt(tick);
    return { phase, deadline: String(last), left: left < 0n ? 0 : Number(left), overdue: left < 0n };
  }

  /* Who has acted in the current window: flags only, never a sealed plan. */
  function actedFlags(summary) {
    const c = new Set(summary.committed || []), r = new Set(summary.revealed || []);
    return Object.fromEntries(SIDES.map(s => [s, r.has(s) ? 'REVEALED' : c.has(s) ? 'COMMITTED' : 'WAITING']));
  }

  /* A fighter's last n finished fights, newest first, from fight summaries.
   * Missing (pruned) summaries are skipped, not guessed. */
  function recentForm(fid, summaries, n) {
    const out = [];
    const done = summaries.filter(s => s && s.phase === 'DONE' && s.result && s.fighters)
      .sort((a, b) => Number(b.fight_id) - Number(a.fight_id));
    for (const s of done) {
      const side = s.fighters.A.fighter_id === fid ? 'A' : s.fighters.B.fighter_id === fid ? 'B' : null;
      if (!side) continue;
      const r = s.result, kind = r.kind || 'COMBAT';
      const how = kind === 'COMBAT' ? (r.result || '') : kind;
      const mark = r.winner == null ? (kind === 'COMBAT' ? 'D' : 'N') : r.winner === side ? 'W' : 'L';
      out.push({ fight_id: String(s.fight_id), mark, how, forfeit: kind === 'FORFEIT' });
      if (out.length >= (n || 5)) break;
    }
    return out;
  }

  /* Ranked order: rating, then wins, then fewer faults, then ID (stable). */
  function leaderboard(fighters) {
    const faults = f => Object.values(f.faults_by_epoch || {}).reduce((a, b) => a + (Number(b) || 0), 0);
    return fighters.filter(Boolean).map(f => ({ f, faults: faults(f) })).sort((x, y) =>
      (y.f.lifetime_rating - x.f.lifetime_rating) || (((y.f.record || {}).W || 0) - ((x.f.record || {}).W || 0)) ||
      (x.faults - y.faults) || (x.f.fighter_id < y.f.fighter_id ? -1 : 1));
  }

  /* How old the export is. wallMs is when it was written (generated_at, or
   * the HTTP Last-Modified of index.json); unknown age is not called fresh. */
  const STALE_MS = 5 * 60 * 1000;
  function freshness(wallMs, nowMs, staleMs) {
    if (!Number.isFinite(wallMs)) return { ageMs: null, stale: false, known: false };
    const ageMs = Math.max(0, nowMs - wallMs);
    return { ageMs, stale: ageMs > (staleMs || STALE_MS), known: true };
  }
  function ageText(ms) {
    if (ms == null) return 'unknown age';
    const s = Math.round(ms / 1000);
    if (s < 90) return s + 's ago';
    if (s < 5400) return Math.round(s / 60) + 'm ago';
    if (s < 172800) return Math.round(s / 3600) + 'h ago';
    return Math.round(s / 86400) + 'd ago';
  }

  // ---- practice (docs/npcs.md section 1) -------------------------------------

  function randomSeed() {
    const b = new Uint8Array(32);
    if (globalThis.crypto && globalThis.crypto.getRandomValues) globalThis.crypto.getRandomValues(b);
    else for (let i = 0; i < 32; i++) b[i] = Math.floor(Math.random() * 256);
    return toHex(b);
  }

  /* The human is slot A, the NPC slot B; both start from the ruleset's
   * identical initial state. */
  function practiceStart(rules, npcId, seed, fightNumber) {
    if (!/^[0-9a-f]{64}$/.test(seed)) throw new Error('seed must be 64 lowercase hex digits');
    const s = {
      npc: npcId, seed, fight: fightNumber || 1, rules_version: rules.semantic_version,
      state: E.newFight(rules), rounds: [], outcome: null, npcPlan: null,
    };
    s.npcPlan = practiceNpcPlan(rules, s);
    return s;
  }

  // The NPC plans from the round-start state and the human's executed actions
  // in earlier rounds only: it is sealed before the human picks.
  function practiceNpcPlan(rules, s) {
    const history = s.rounds.map(r => r.result.beats.map(bt => bt.a.effective));
    return N.planFor(s.npc, rules, { round_index: s.state.round_index, self: s.state.b, opponent: s.state.a, opponent_history: history }, s.seed, s.fight);
  }

  function practicePlay(rules, s, humanPlan) {
    if (s.outcome) throw new Error('the fight is over');
    const plan = E.validatePlan(rules, humanPlan, s.state.a);
    const start = s.state;
    const res = E.resolveRound(rules, start, plan, s.npcPlan);
    s.rounds.push({
      round_index: start.round_index, start, plans: { A: plan, B: s.npcPlan }, result: res,
      unexecuted: { A: plan.actions.slice(res.executed), B: s.npcPlan.actions.slice(res.executed) },
    });
    s.state = res.end;
    s.outcome = res.outcome;
    s.npcPlan = s.outcome ? null : practiceNpcPlan(rules, s);
    return res;
  }

  return Object.freeze({
    NAMES, ID, LEVELS,
    fromHex, toHex, concat, uLE, canonicalJson, rulesetDigest, chooseRuleset, defaultSha256,
    parseContext, roundStateBytes, commitmentPreimage,
    deriveReplay, replayMismatches, verifyReplay, levelOf, isForfeit, ratingDelta, splitPurse, checkSettlement,
    timeline, outcomeLabel, explainSide, causeOf, beatHeadline, hindsight, fighterStats,
    randomSeed, practiceStart, practiceNpcPlan, practicePlay,
    seriesWins, livePhase, actedFlags, recentForm, leaderboard, freshness, ageText, STALE_MS,
  });
});
