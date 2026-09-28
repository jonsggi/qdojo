/* Frame playback for the fighter strips in avatars.js.
 *
 * One animation loop for the whole page. The frame on screen is a pure
 * function of time, so a tab that slept catches up without drift. Strips are
 * built lazily per identity, clip and mode and kept in a small cache. With
 * prefers-reduced-motion the module does nothing: the static art stays.
 *
 * An avatar joins in by carrying data-anim and data-identity:
 *   idle     breathe, nothing else (lobby seats)
 *   profile  breathe, and every few seconds the fighter's signature move
 *   win      the salute, repeated
 *   lose     down on one knee, and stay there
 *   bow      a bow, repeated
 *   manual   nothing automatic; the page calls play()
 */
'use strict';
const QDojoAnim = (() => {
  const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const actors = new Map();  // element -> actor
  const strips = new Map();  // identity|clip|mode -> svg markup
  const queue = [];          // delayed plays: { at, actor, clip }
  const AUTO = { profile: a => QDojoAvatars.signature(a.identity), win: () => 'win', bow: () => 'bow', lose: () => 'lose' };
  let running = false;
  const now = () => performance.now();

  function hash(s) {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
    return h;
  }
  function stripFor(identity, clip, mode) {
    const key = identity + '|' + clip + '|' + mode;
    if (!strips.has(key)) {
      if (strips.size >= 128) strips.delete(strips.keys().next().value);
      strips.set(key, QDojoAvatars.strip(identity, clip, mode));
    }
    return strips.get(key);
  }
  function duration(clip, rate = 1) {
    const c = QDojoAvatars.clips[clip];
    return 1000 * c.frames.length / c.fps / rate;
  }

  function play(actor, clip, offset = 0) {
    if (!QDojoAvatars.clips[clip]) clip = 'idle';
    actor.clip = clip; actor.start = now() + offset; actor.shown = -1;
    actor.el.innerHTML = stripFor(actor.identity, clip, actor.mode);
    actor.groups = actor.el.querySelectorAll('g[data-frame]');
  }

  function attach(el) {
    const identity = el.dataset.identity;
    if (!identity) return;
    const actor = {
      el, identity, anim: el.dataset.anim,
      mode: el.classList.contains('avatar-xl') ? 'artwork' : 'sprite',
      seed: hash(identity), rate: 1, clip: 'idle', start: 0, shown: -1, groups: [], next: 0,
    };
    actors.set(el, actor);
    // Stagger the breathing by identity so a row of fighters never bobs in unison.
    play(actor, 'idle', -(actor.seed % 2000));
    actor.next = now() + 400 + actor.seed % 1600;
  }

  function tick(actor, t) {
    const spec = QDojoAvatars.clips[actor.clip], n = spec.frames.length;
    let i = Math.max(0, Math.floor((t - actor.start) / 1000 * spec.fps * actor.rate));
    if (actor.clip === 'idle') i %= n;
    else if (i >= n) {
      if (spec.hold) i = n - 1;
      else { play(actor, 'idle', -(actor.seed % 1000)); return tick(actor, t); }
    }
    if (i === actor.shown) return;
    actor.groups.forEach((g, k) => { g.style.display = k === i ? '' : 'none'; });
    actor.shown = i;
  }

  // Timed behaviours that belong to one avatar: the profile's signature move,
  // the winner's salute, the bow. The gap between moves comes from the identity.
  function step(actor, t) {
    const auto = AUTO[actor.anim];
    if (!auto || actor.clip !== 'idle' || t < actor.next) return;
    const clip = auto(actor);
    play(actor, clip);
    actor.next = clip === 'lose' ? Infinity : t + duration(clip, actor.rate) + 3000 + actor.seed % 5000;
  }

  function loop() {
    const t = now();
    for (let i = queue.length - 1; i >= 0; i--) {
      const q = queue[i];
      if (t < q.at) continue;
      queue.splice(i, 1);
      if (q.actor.el.isConnected && (q.clip !== 'hit' || q.actor.clip === 'idle')) play(q.actor, q.clip);
    }
    for (const actor of actors.values()) {
      if (!actor.el.isConnected) { actors.delete(actor.el); continue; }
      step(actor, t); tick(actor, t);
    }
    requestAnimationFrame(loop);
  }

  // Attach every animated avatar under root that is not attached yet. Cheap to
  // call after each render; already-attached elements are left alone.
  function mount(root = document) {
    if (reduced || typeof QDojoAvatars === 'undefined') return 0;
    let added = 0;
    root.querySelectorAll('.avatar[data-anim]').forEach(el => { if (!actors.has(el)) { attach(el); added++; } });
    if (!running && actors.size) { running = true; requestAnimationFrame(loop); }
    return added;
  }
  function playOn(el, clip, delay = 0) {
    const actor = actors.get(el);
    if (!actor) return false;
    if (delay > 0) queue.push({ at: now() + delay, actor, clip }); else play(actor, clip);
    return true;
  }
  function rateOn(el, rate) { const actor = actors.get(el); if (actor) actor.rate = rate; }
  function clipOf(el) { const actor = actors.get(el); return actor ? actor.clip : null; }

  return Object.freeze({ mount, play: playOn, rate: rateOn, clipOf, duration, reduced });
})();
