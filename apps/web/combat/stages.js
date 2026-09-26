/* Fight stages: procedural pixel-art arenas behind the replay player.
 *
 * Decoration only. A stage is chosen from the fight ID and drawn from a
 * seeded generator, so a fight always gets the same arena; nothing here reads
 * or changes a fight's numbers. No images: every pixel is a fillRect on a
 * small canvas that CSS scales up with image-rendering: pixelated.
 *
 * The world is the robot dojo after the Big Unplug: scrapyards, dead malls,
 * acid rain, a crowd of scavenger robots, drones and a few humans in hazmat
 * ponchos betting bottle caps. Backdrops stay dark and desaturated and every
 * floor is lit, so the fighters pop.
 *
 * Each stage is four static layers (sky, far, mid, floor), rendered once per
 * size into offscreen canvases, plus an animated pass (crowd, rain, neon,
 * sparks) drawn at a low frame rate. The static layers pan a few pixels at
 * different speeds for parallax; the floor stays put under the fighters.
 *
 * One animation loop serves every stage on the page. It stops when nothing
 * needs drawing: motion off (body.still) or prefers-reduced-motion leaves a
 * single still frame; a hidden tab, an offscreen canvas (IntersectionObserver)
 * or a detached one draws nothing.
 *
 *   QDojoStages.mount(canvas, { seed, fps, scale })  -> { stage, destroy() }
 *   QDojoStages.pick(seed)                           -> stage index
 *   QDojoStages.list                                 -> [{ key, name }]
 *   QDojoStages.paint(ctx, W, H, index, seed, t, makeCanvas)  (tests, tools)
 */
'use strict';
const QDojoStages = (() => {
  const M = 8; // parallax margin (logical px) each side of every layer

  // ---- seeded randomness ---------------------------------------------------------

  function hash(s) {
    let h = 2166136261 >>> 0;
    s = String(s);
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
    return h;
  }
  function rng(seed) {
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const rngFor = (seed, part) => rng(hash(seed + '|' + part));
  const ri = (r, a, b) => a + Math.floor(r() * (b - a + 1));
  const pickOf = (r, list) => list[Math.floor(r() * list.length)];
  // A deterministic flicker: the same (key, slot) always gives the same value.
  const noise = (k, i) => (hash(k + ':' + i) % 1000) / 1000;

  // ---- pixel helpers -------------------------------------------------------------

  function rect(c, x, y, w, h, col) {
    x = Math.round(x); y = Math.round(y); w = Math.round(w); h = Math.round(h);
    if (w <= 0 || h <= 0) return;
    c.fillStyle = col;
    c.fillRect(x, y, w, h);
  }
  const px = (c, x, y, col) => rect(c, x, y, 1, 1, col);
  function alpha(c, a, fn) { const was = c.globalAlpha; c.globalAlpha = a; fn(); c.globalAlpha = was; }
  function line(c, x0, y0, x1, y1, col) {
    const n = Math.max(1, Math.round(Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0))));
    for (let i = 0; i <= n; i++) px(c, x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n, col);
  }

  // Vertical gradient in bands, with ordered dithering between the bands.
  function gradient(c, x0, W, y0, y1, cols) {
    const n = cols.length - 1, span = Math.max(1, y1 - y0);
    for (let y = y0; y < y1; y++) {
      const p = (y - y0) / span * n, i = Math.min(n - 1, Math.floor(p)), f = p - i;
      const a = cols[i], b = cols[i + 1];
      if (f < 0.2) { rect(c, x0, y, W, 1, a); continue; }
      if (f > 0.8) { rect(c, x0, y, W, 1, b); continue; }
      const base = f < 0.5 ? a : b, dot = f < 0.5 ? b : a, step = f > 0.35 && f < 0.65 ? 2 : 4;
      rect(c, x0, y, W, 1, base);
      c.fillStyle = dot;
      for (let x = x0 + ((y * (step === 2 ? 1 : 3)) % step); x < x0 + W; x += step) c.fillRect(x, y, 1, 1);
    }
  }
  function disc(c, cx, cy, r, col) {
    for (let dy = -r; dy <= r; dy++) {
      const w = Math.floor(Math.sqrt(r * r - dy * dy) + 0.35);
      rect(c, cx - w, cy + dy, 2 * w + 1, 1, col);
    }
  }
  function ellipse(c, cx, cy, rx, ry, col) {
    for (let dy = -ry; dy <= ry; dy++) {
      const w = Math.floor(rx * Math.sqrt(1 - (dy * dy) / (ry * ry || 1)) + 0.35);
      rect(c, cx - w, cy + dy, 2 * w + 1, 1, col);
    }
  }
  // A ridge line from summed sines with seeded phases; filled down to `bottom`.
  // Returns the top y of every column, so props can sit on the ridge.
  function ridge(c, W, base, amp, bottom, col, r, rough = 1) {
    const ph = [r() * 6.28, r() * 6.28, r() * 6.28], fr = [0.021 + r() * 0.01, 0.055 + r() * 0.02, 0.13 + r() * 0.05];
    const tops = [];
    for (let x = 0; x < W; x++) {
      const h = amp * (0.55 * Math.sin(x * fr[0] + ph[0]) + 0.3 * Math.sin(x * fr[1] + ph[1]) + 0.15 * rough * Math.sin(x * fr[2] + ph[2]) + 0.5);
      const y = Math.round(base - h);
      rect(c, x, y, 1, bottom - y, col);
      tops.push(y);
    }
    return tops;
  }
  // 3x5 pixel font for signs.
  const FONT = {
    A: '010101111101101', B: '110101110101110', C: '011100100100011', D: '110101101101110', E: '111100110100111',
    F: '111100110100100', G: '011100101101011', H: '101101111101101', I: '111010010010111', J: '001001001101010',
    K: '101101110101101', L: '100100100100111', M: '101111111101101', N: '110101101101101', O: '010101101101010',
    P: '110101110100100', Q: '010101101110011', R: '110101110101101', S: '011100010001110', T: '111010010010010',
    U: '101101101101111', V: '101101101101010', W: '101101111111101', X: '101101010101101', Y: '101101010010010',
    Z: '111001010100111', 0: '111101101101111', 1: '010110010010111', 2: '110001010100111', 3: '111001011001111',
    4: '101101111001001', 5: '111100110001110', 6: '011100110101010', 7: '111001010010010', 8: '010101010101010',
    9: '010101011001110', '/': '001001010100100', '!': '010010010000010', '-': '000000111000000', '.': '000000000000010',
    ':': '000010000010000', '?': '110001010000010', '+': '000010111010000', '\'': '010010000000000', ' ': '000000000000000',
  };
  // Pixel text: `s` is the pixel size, `shear` leans each glyph row sideways.
  function text(c, str, x, y, col, s = 1, shear = 0) {
    c.fillStyle = col;
    for (const ch of String(str).toUpperCase()) {
      const g = FONT[ch] || FONT[' '];
      for (let i = 0; i < 15; i++) {
        if (g[i] !== '1') continue;
        const row = Math.floor(i / 3);
        c.fillRect(Math.round(x + (i % 3) * s + row * s * shear), Math.round(y + row * s), s, s);
      }
      x += 4 * s;
    }
  }
  const textW = (str, s = 1) => (String(str).length * 4 - 1) * s;
  // A painted board with centred lines of text; returns its size.
  const boardSize = (lines, s = 1, pad = 2) => ({ w: Math.max(...lines.map(l => textW(l, s))) + 2 * pad + 2, h: lines.length * 6 * s - s + 2 * pad + 2 });
  function board(c, x, y, lines, o) {
    const s = o.s || 1, pad = o.pad == null ? 2 : o.pad, { w, h } = boardSize(lines, s, pad);
    x = Math.round(x); y = Math.round(y);
    rect(c, x, y, w, h, o.edge || '#0d0f12');
    rect(c, x + 1, y + 1, w - 2, h - 2, o.bg);
    if (o.r) for (let i = 0; i < (w * h) / 14; i++) px(c, x + 1 + ri(o.r, 0, w - 3), y + 1 + ri(o.r, 0, h - 3), shade(o.bg, 0.8));
    lines.forEach((ln, i) => text(c, ln, x + 1 + pad + ((w - 2 - 2 * pad - textW(ln, s)) >> 1), y + 1 + pad + i * 6 * s, o.fg, s));
    if (o.cross) for (const d of [0, 1]) { line(c, x + d, y, x + w - 2 + d, y + h - 1, o.cross); line(c, x + d, y + h - 1, x + w - 2 + d, y, o.cross); }
    if (o.nails) { px(c, x + 1, y + 1, '#9aa6b2'); px(c, x + w - 2, y + 1, '#9aa6b2'); }
    if (o.drip && o.r) for (let i = 0; i < 3; i++) rect(c, x + ri(o.r, 2, w - 3), y + h, 1, ri(o.r, 1, 3), o.drip);
    return { w, h };
  }
  // Hazard stripes (diagonal), for barriers, doors and trims.
  function hazard(c, x, y, w, h, a = '#b8922a', b = '#15171a', s = 2) {
    x = Math.round(x); y = Math.round(y);
    for (let yy = 0; yy < h; yy++) for (let xx = 0; xx < w; xx += s) rect(c, x + xx, y + yy, Math.min(s, w - xx), 1, Math.floor((xx + yy + 1000 * s) / s / 2) % 2 ? a : b);
  }
  // Perspective floor lines: converging to (vx, vy); `every` px apart at the front edge.
  function converging(c, LW, hz, H, every, col, vyK = 1.4, x0 = 0, x1 = LW) {
    const vx = LW / 2, vy = hz - (H - hz) * vyK;
    c.fillStyle = col;
    for (let xb = vx % every - every * 6; xb < LW + every * 6; xb += every) {
      for (let y = hz; y < H; y++) {
        const x = vx + (xb - vx) * (y - vy) / (H - vy);
        if (x >= x0 && x < x1) c.fillRect(Math.round(x), y, 1, 1);
      }
    }
  }
  function seams(c, LW, hz, H, n, col, pow = 1.9) {
    for (let k = 1; k < n; k++) rect(c, 0, hz + Math.round((H - hz) * Math.pow(k / n, pow)), LW, 1, col);
  }
  function stars(c, LW, y1, n, r, cols) {
    for (let i = 0; i < n; i++) px(c, ri(r, 0, LW - 1), ri(r, 0, y1), pickOf(r, cols));
  }
  function cube(c, x, y, s, top, left, right) {
    // A small isometric cube; (x, y) is the top corner.
    for (let i = 0; i < s; i++) rect(c, x - i, y + Math.floor(i / 2), 2 * i + 1, 1, top);
    const mid = y + Math.floor(s / 2);
    for (let i = 0; i < s; i++) {
      rect(c, x - s + 1 + i, mid + Math.floor(i / 2), 1, s, left);
      rect(c, x + s - 1 - i, mid + Math.floor(i / 2), 1, s, right);
    }
    rect(c, x - s + 1, mid, 2 * s - 1, 1, top);
  }
  function shade(hex, k) {
    const n = parseInt(hex.slice(1), 16);
    const f = v => Math.max(0, Math.min(255, Math.round(k < 1 ? v * k : v + (255 - v) * (k - 1))));
    return '#' + ((1 << 24) | (f((n >> 16) & 255) << 16) | (f((n >> 8) & 255) << 8) | f(n & 255)).toString(16).slice(1);
  }
  function particles(r, n, fn) { const out = []; for (let i = 0; i < n; i++) out.push(fn(r, i)); return out; }
  const mod = (a, n) => ((a % n) + n) % n;
  function speckle(c, x0, y0, w, h, n, cols, r) { for (let i = 0; i < n; i++) px(c, x0 + ri(r, 0, w - 1), y0 + ri(r, 0, h - 1), pickOf(r, cols)); }
  // Rust streaks running down from y.
  function streaks(c, x0, y, w, n, maxLen, col, r) { for (let i = 0; i < n; i++) rect(c, x0 + ri(r, 0, w - 1), y, 1, ri(r, 1, maxLen), col); }
  // A pool of light on the floor, where the fighters stand.
  function floorLight(c, LW, hz, H, col, a = 0.16) {
    const cy = hz + Math.round((H - hz) * 0.58), ry = Math.round((H - hz) * 0.46);
    for (const [k, f] of [[1, 1], [0.72, 1.3], [0.45, 1.6]]) alpha(c, a * f * 0.6, () => ellipse(c, Math.round(LW / 2), cy, Math.round(LW * 0.46 * k), Math.max(1, Math.round(ry * k)), col));
  }
  // Dark vignette on a layer: fades its top towards the HUD.
  function veil(c, LW, y0, y1, col, a) { for (let y = y0; y < y1; y++) alpha(c, a * (1 - (y - y0) / Math.max(1, y1 - y0)), () => rect(c, 0, y, LW, 1, col)); }

  // ---- props -----------------------------------------------------------------------

  function tyres(c, x, base, n, rw) {
    for (let k = 0; k < n; k++) {
      const y = base - 2 - k * 3;
      ellipse(c, x, y, rw, 2, '#131417'); rect(c, x - rw + 1, y - 2, 2 * rw - 1, 1, '#2c2f34');
      rect(c, x - rw, y, 2 * rw + 1, 1, '#1d1f23');
    }
    ellipse(c, x, base - 2 - (n - 1) * 3 - 1, Math.max(1, rw - 2), 0, '#070809');
  }
  // A car hulk in side view; (x, base) is the rear wheel's ground point.
  function car(c, x, base, w, col, r, glass = '#0b0e11') {
    const h = Math.max(5, Math.round(w * 0.32)), lower = Math.round(h * 0.55), rows = h - lower;
    rect(c, x, base - lower - 1, w, lower, col); rect(c, x, base - lower - 1, w, 1, shade(col, 1.25));
    rect(c, x, base - 2, w, 1, shade(col, 0.6));
    const cx = x + Math.round(w * 0.2), cw = Math.round(w * 0.55);
    for (let k = 0; k < rows; k++) {
      const ins = Math.round((rows - k) * 0.8);
      rect(c, cx + ins, base - h - 1 + k, cw - 2 * ins, 1, k === 0 ? shade(col, 1.2) : col);
      if (k > 0) rect(c, cx + ins + 1, base - h - 1 + k, cw - 2 * ins - 2, 1, glass);
    }
    rect(c, cx + (cw >> 1), base - h, 1, rows, col);
    const wr = Math.max(1, Math.round(h * 0.26));
    for (const f of [0.2, 0.8]) { disc(c, x + Math.round(w * f), base - wr, wr, '#0a0b0d'); px(c, x + Math.round(w * f), base - wr, '#3a3f44'); }
    if (r) { speckle(c, x, base - lower - 1, w, lower, Math.round(w / 3), ['#7a3a16', '#5a2a12', shade(col, 0.8)], r); streaks(c, x, base - lower, w, 3, lower - 1, '#6a3014', r); }
  }
  // A car seen from behind (drive-in rows).
  function carRear(c, x, base, w, col) {
    const h = Math.max(5, Math.round(w * 0.55)), lower = Math.round(h * 0.55);
    rect(c, x, base - lower, w, lower - 1, col); rect(c, x, base - lower, w, 1, shade(col, 1.25));
    rect(c, x + 2, base - h, w - 4, h - lower, col); rect(c, x + 3, base - h + 1, w - 6, h - lower - 1, '#0b0e11');
    rect(c, x, base - 2, 2, 2, '#0a0b0d'); rect(c, x + w - 2, base - 2, 2, 2, '#0a0b0d');
    rect(c, x + (w >> 1) - 2, base - lower + 2, 4, 1, '#9aa6b2');
    return { tl: [x + 1, base - lower + 1], tr: [x + w - 2, base - lower + 1] };
  }
  function cone(c, x, base) {
    rect(c, x - 2, base - 1, 5, 1, '#8a3a12');
    for (let k = 0; k < 4; k++) rect(c, x - (k >> 1), base - 2 - k, (k >> 1) * 2 + 1, 1, k === 1 ? '#c8c8c0' : '#c2551b');
    px(c, x, base - 6, '#c2551b');
  }
  function duck(c, x, y) { rect(c, x, y + 1, 3, 2, '#f2c230'); px(c, x + 2, y, '#f2c230'); px(c, x + 3, y, '#e07a1a'); }
  function drum(c, x, base, col, ooze) {
    rect(c, x, base - 6, 5, 6, col); rect(c, x, base - 6, 5, 1, shade(col, 1.3));
    rect(c, x, base - 4, 5, 1, shade(col, 0.6)); rect(c, x + 4, base - 5, 1, 5, shade(col, 0.7));
    if (ooze) { rect(c, x + 1, base - 6, 2, 1, ooze); px(c, x + 1, base - 5, ooze); rect(c, x - 2, base - 1, 4, 1, ooze); }
  }
  // Warning triangle with "!" (hazard signs).
  function warnSign(c, x, y, col = '#c9a02a') {
    for (let k = 0; k < 6; k++) rect(c, x - k, y + k, 2 * k + 1, 1, col);
    rect(c, x - 5, y + 6, 11, 1, shade(col, 0.6));
    rect(c, x, y + 2, 1, 2, '#15171a'); px(c, x, y + 5, '#15171a');
  }
  // A lattice beam between two points (cranes, towers, pylons).
  function lattice(c, x0, y0, x1, y1, thick, col) {
    const dx = x1 - x0, dy = y1 - y0, len = Math.max(1, Math.hypot(dx, dy)), nx = -dy / len * thick, ny = dx / len * thick;
    line(c, x0, y0, x1, y1, col); line(c, x0 + nx, y0 + ny, x1 + nx, y1 + ny, col);
    const steps = Math.max(1, Math.floor(len / (thick * 1.6 + 1)));
    for (let i = 0; i < steps; i++) {
      const u = i / steps, v = (i + 1) / steps;
      line(c, x0 + dx * u, y0 + dy * u, x0 + dx * v + nx, y0 + dy * v + ny, col);
    }
  }

  // ---- the crowd: scavenger robots, drones, humans in hazmat ponchos ------------------

  const EYES = ['#ff4fa0', '#36e0ff', '#f2c230', '#e0342b', '#7dff9a', '#36e0ff'];
  const METALS = [['#6e3a1c', '#7a4424', '#5e3a2a', '#86502c'], ['#5c6672', '#6c7784', '#4f5864'], ['#2c605a', '#357068'], ['#4a4640', '#3e4248', '#54504a']];
  const PONCHOS = ['#8a7424', '#8a4e1e', '#6a7a2a', '#7a2a24', '#8a7424'];
  const PROPS = ['#ff4fa0', '#f2c230', '#36e0ff', '#e0342b'];
  const KINDS = ['bot', 'tv', 'drone', 'hazmat', 'cart'];

  // mix: weights per kind, plus umbrella / geiger (share of the crowd carrying them).
  function makeCrowd(r, x0, x1, foot, n, hr, mix = {}) {
    const w = Object.assign({ bot: 5, tv: 2, drone: 1, hazmat: 2, cart: 0 }, mix);
    const kinds = KINDS.filter(k => w[k] > 0), tot = kinds.reduce((s, k) => s + w[k], 0);
    const out = [];
    for (let i = 0; i < n; i++) {
      let u = r() * tot, kind = kinds[kinds.length - 1];
      for (const k of kinds) { if ((u -= w[k]) < 0) { kind = k; break; } }
      const h = ri(r, hr[0], hr[1]);
      const body = kind === 'hazmat' ? pickOf(r, PONCHOS) : pickOf(r, pickOf(r, METALS));
      const pr = r();
      out.push({
        kind, x: Math.round(x0 + (x1 - x0) * (i + 0.2 + r() * 0.6) / n), foot: foot + ri(r, 0, 1), h,
        w: Math.max(4, Math.round(h * (kind === 'tv' ? 0.42 : 0.36))), body, dark: shade(body, 0.6), lite: shade(body, 1.35),
        eye: pickOf(r, EYES), ant: r() < 0.45, tread: r() < 0.35, spot: r() < 0.5,
        prop: pr < 0.2 ? 'finger' : pr < 0.38 ? 'cap' : null, propCol: pickOf(r, PROPS),
        umb: !!mix.umbrella && r() < mix.umbrella, umbCol: pickOf(r, ['#3a2a4a', '#1f3a3a', '#4a2020', '#2a2a2a']),
        geiger: !!mix.geiger && kind === 'hazmat',
        cheer: r() < 0.7, sp: 5 + r() * 4, ph: r() * 6.28,
      });
    }
    return out;
  }
  // Arms and what the right hand holds; (x, y) is the torso's top-left.
  function arms(c, x, y, w, reach, up, p, blink) {
    const col = p.dark;
    if (up === 2) { rect(c, x - 1, y - reach, 1, reach + 2, col); rect(c, x + w, y - reach, 1, reach + 2, col); }
    else { rect(c, x - 1, y + 1, 1, reach, col); if (up === 0) rect(c, x + w, y + 1, 1, reach, col); else rect(c, x + w, y - reach, 1, reach + 2, col); }
    if (!up) return;
    const hx = x + w, hy = y - reach;
    if (p.prop === 'finger') { rect(c, hx - 1, hy - 2, 3, 3, p.propCol); rect(c, hx, hy - 4, 1, 2, p.propCol); px(c, hx - 1, hy - 2, shade(p.propCol, 1.4)); }
    else if (p.prop === 'cap') { rect(c, hx - 1, hy - 2, 3, 1, '#b8322a'); rect(c, hx - 1, hy - 1, 3, 1, '#c9ced4'); if (blink) px(c, hx + 1, hy - 3, '#ffffff'); }
  }
  function drawBot(c, x, foot, p, up, jump, t, still) {
    const h = p.h, w = p.w, legH = Math.max(2, Math.round(h * 0.28)), hs = Math.max(3, Math.round(h * 0.3)), tor = Math.max(2, h - legH - hs);
    const y = foot - h - jump, ty = y + hs, blink = !still && Math.sin(t * 9 + p.ph * 3) > 0.6;
    if (p.tread) { rect(c, x - 1, foot - legH, w + 2, legH, '#141619'); for (let k = 0; k < w + 2; k += 2) px(c, x - 1 + k, foot - 1, '#3a3f44'); rect(c, x + (w >> 1) - 1, ty + tor, 2, foot - legH - ty - tor, p.dark); }
    else { const lw = Math.max(1, (w - 2) >> 1); rect(c, x, ty + tor, lw, foot - ty - tor, p.dark); rect(c, x + w - lw, ty + tor, lw, foot - ty - tor, p.dark); }
    rect(c, x, ty, w, tor, p.body); rect(c, x, ty, w, 1, p.lite); rect(c, x + w - 1, ty + 1, 1, tor - 1, p.dark);
    if (tor > 3) px(c, x + 1, ty + 2, blink ? p.eye : shade(p.eye, 0.55));
    if (p.spot) px(c, x + w - 2, ty + tor - 1, '#8a4a1c');
    if (p.kind === 'tv') {
      const hw = w + 2, hx = x - 1;
      rect(c, hx, y - 1, hw, hs + 1, '#1a1c20'); rect(c, hx + 1, y, hw - 2, hs - 1, shade(p.eye, 0.35));
      px(c, hx + 2, y + 1, p.eye); px(c, hx + hw - 3, y + 1, p.eye);
      if (up) rect(c, hx + 2, y + hs - 2, hw - 4, 1, p.eye);
      px(c, hx + 1, y - 2, '#4b5563'); px(c, hx, y - 3, '#9aa6b2'); px(c, hx + hw - 2, y - 2, '#4b5563'); px(c, hx + hw - 1, y - 3, '#9aa6b2');
    } else {
      const hx = x + ((w - hs) >> 1);
      rect(c, hx, y, hs, hs, p.body); rect(c, hx, y, hs, 1, p.lite); rect(c, hx + hs - 1, y + 1, 1, hs - 1, p.dark);
      const ey = y + Math.max(1, (hs - 1) >> 1);
      if (hs >= 4) rect(c, hx + 1, ey, hs - 2, 1, p.eye); else px(c, hx + 1, ey, p.eye);
      if (p.ant) { rect(c, hx + hs - 2, y - 2, 1, 2, p.dark); px(c, hx + hs - 2, y - 3, blink ? '#ffffff' : p.eye); }
    }
    if (p.umb) {
      const ux = x + (w >> 1);
      rect(c, ux - 5, y - 4, 11, 1, p.umbCol); rect(c, ux - 4, y - 5, 9, 1, p.umbCol); rect(c, ux - 2, y - 6, 5, 1, shade(p.umbCol, 1.3));
      rect(c, x + w, y - 4, 1, hs + 5, '#15171a'); rect(c, x - 1, ty + 1, 1, tor - 1, p.dark);
      return;
    }
    arms(c, x, ty, w, hs + 2, up, p, blink);
  }
  function drawDrone(c, x, foot, p, up, t, still) {
    const w = p.w + 1, bob = still ? 0 : Math.round(Math.sin(t * 3 + p.ph) * 1.5) + (up === 2 ? 1 : 0);
    const y = foot - p.h - 1 - bob;
    rect(c, x, y + 2, w, 3, p.body); rect(c, x, y + 2, w, 1, p.lite); rect(c, x + 1, y + 3, w - 2, 1, '#0d0f12'); px(c, x + (w >> 1), y + 3, p.eye);
    px(c, x - 1, y + 1, p.dark); px(c, x + w, y + 1, p.dark);
    const f = still ? 0 : Math.floor(t * 14 + p.ph) & 1;
    if (f) { rect(c, x - 3, y, 5, 1, '#8b939c'); rect(c, x + w - 2, y, 5, 1, '#8b939c'); } else { rect(c, x - 2, y, 3, 1, '#5a626c'); rect(c, x + w - 1, y, 3, 1, '#5a626c'); }
    px(c, x + 1, y + 5, p.dark); px(c, x + w - 2, y + 5, p.dark);
    if (p.prop === 'finger') { rect(c, x + (w >> 1), y + 5, 1, 2, '#4b5563'); rect(c, x + (w >> 1) - 1, y + 7, 3, 2, p.propCol); px(c, x + (w >> 1), y + 6, p.propCol); }
  }
  function drawHazmat(c, x, foot, p, up, jump, t, still) {
    const h = p.h, w = p.w + 1, hs = Math.max(3, Math.round(h * 0.28)), y = foot - h - jump, hx = x + ((w - hs) >> 1);
    const pb = Math.max(3, h - hs - 2), cx = x + w / 2;
    rect(c, x + 1, foot - 2, 1, 2, '#15171a'); rect(c, x + w - 2, foot - 2, 1, 2, '#15171a');
    for (let k = 0; k < pb; k++) { const half = (w / 2 + 0.5) * (0.55 + 0.45 * k / pb); rect(c, cx - half, y + hs + k, 2 * half, 1, k % 4 === 3 ? shade(p.body, 0.8) : p.body); }
    rect(c, cx - 0.5, y + hs, 1, pb, shade(p.body, 0.75));
    rect(c, hx, y, hs, hs, p.body); rect(c, hx, y, hs, 1, p.lite);
    rect(c, hx + 1, y + 1, hs - 2, hs - 1, '#12171b'); px(c, hx + 1, y + 1, '#9fe8ff');
    if (hs > 3) px(c, hx + hs - 2, y + 1, '#9fe8ff');
    const blink = !still && Math.sin(t * 9 + p.ph * 3) > 0.6;
    if (p.geiger) {
      const gx = up ? x + w : x - 2, gy = up ? y - hs - 1 : y + hs + 2;
      rect(c, gx - 1, gy, 2, 2, '#c9a02a');
      if (still || noise('geiger' + p.x, Math.floor(t * 10)) > 0.4) px(c, gx, gy, '#7dff9a');
    }
    const q = Object.assign({}, p, { dark: p.body, prop: p.geiger ? null : p.prop });
    arms(c, x, y + hs, w, hs + 1, up, q, blink);
  }
  function drawCart(c, x, foot, p, up, jump, t, still) {
    const cb = Math.max(4, Math.round(p.h * 0.36)), bw = p.w + 4, by = foot - 2 - cb;
    // the rider: head and shoulders over the basket
    const rider = Object.assign({}, p, { tread: false, umb: false });
    const hs = Math.max(3, Math.round(p.h * 0.3));
    const top = by - hs - 2 - jump;
    const hx = x + 1 + ((p.w - hs) >> 1);
    rect(c, x + 1, top + hs, p.w, by - top - hs + 1, p.body); rect(c, x + 1, top + hs, p.w, 1, p.lite);
    rect(c, hx, top, hs, hs, p.body); rect(c, hx, top, hs, 1, p.lite); rect(c, hx + 1, top + Math.max(1, (hs - 1) >> 1), Math.max(1, hs - 2), 1, p.eye);
    arms(c, x + 1, top + hs, p.w, hs, up, rider, !still && Math.sin(t * 9 + p.ph * 3) > 0.6);
    rect(c, x - 1, by, bw, 1, '#8b939c'); rect(c, x - 1, by + cb - 1, bw, 1, '#6a727a');
    for (let k = 0; k < bw; k += 2) rect(c, x - 1 + k, by + 1, 1, cb - 2, '#5a626c');
    rect(c, x - 1, by + (cb >> 1), bw, 1, '#4b5563');
    rect(c, x + bw - 1, by - 2, 1, 3, '#8b939c'); rect(c, x + bw - 1, by - 2, 2, 1, '#e0342b');
    rect(c, x, foot - 2, bw - 2, 1, '#4b5563'); px(c, x, foot - 1, '#0d0f12'); px(c, x + bw - 3, foot - 1, '#0d0f12');
  }
  function drawCrowd(c, crowd, t, X, depth, still) {
    for (const p of crowd) {
      let up = 0, jump = 0;
      if (still) up = p.cheer && p.ph > 3.5 ? 2 : p.cheer && p.ph > 2 ? 1 : 0;
      else if (p.cheer) { const k = Math.sin(t * p.sp + p.ph); up = k > 0.1 ? 2 : k > -0.5 ? 1 : 0; jump = k > 0.7 ? 1 : 0; }
      else jump = Math.sin(t * p.sp * 0.4 + p.ph) > 0.85 ? 1 : 0;
      const x = X(p.x, depth);
      if (p.kind === 'drone') drawDrone(c, x, p.foot, p, up, t, still);
      else if (p.kind === 'hazmat') drawHazmat(c, x, p.foot, p, up, jump, t, still);
      else if (p.kind === 'cart') drawCart(c, x, p.foot, p, up, jump, t, still);
      else drawBot(c, x, p.foot, p, up, jump, t, still);
    }
  }

  // ---- animated bits shared by stages ------------------------------------------------

  function smoke(c, x, y, t, puffs, col, still, rise = 40, a0 = 0.45) {
    for (const p of puffs) {
      const k = still ? p.ph : mod(t * p.v + p.ph, 1);
      alpha(c, a0 * (1 - k), () => disc(c, Math.round(x + p.dx * k * 6 + Math.sin(t * 1.5 + p.ph * 6) * 2 * k), Math.round(y - k * rise), 1 + Math.round(k * 3), col));
    }
  }
  const puffSet = (r, n) => particles(r, n, r => ({ ph: r(), dx: (r() - 0.5) * 2, v: 0.25 + r() * 0.2 }));
  // Neon text: glow and tube when on, dead glass when off.
  function neon(c, str, x, y, col, on, s = 1) {
    if (on) alpha(c, 0.22, () => rect(c, x - 2, y - 2, textW(str, s) + 4, 5 * s + 4, col));
    text(c, str, x, y, on ? shade(col, 1.25) : shade(col, 0.32), s);
  }
  // Drifting motes (dust, pollen, fallout).
  function motes(c, list, t, W, H, col, still) {
    c.fillStyle = col;
    for (const m of list) {
      const x = still ? m.x : mod(m.x + Math.sin(t * 0.7 + m.ph) * 4 + t * m.vx, W + 4) - 2;
      const y = still ? m.y : mod(m.y + t * m.vy, H);
      if (still || Math.sin(t * 3 + m.ph * 5) > -0.6) c.fillRect(Math.round(x), Math.round(y), 1, 1);
    }
  }
  const moteSet = (r, n, LW, y0, y1, vx, vy) => particles(r, n, r => ({ x: r() * LW, y: y0 + r() * (y1 - y0), ph: r() * 6.28, vx: vx * (0.5 + r()), vy: vy * (0.5 + r()) }));
  function beacon(c, x, y, on, col = '#e0342b') { px(c, x, y, on ? shade(col, 1.3) : shade(col, 0.45)); if (on) alpha(c, 0.3, () => disc(c, x, y, 2, col)); }

  // ---- the stages ----------------------------------------------------------------
  //
  // Every function gets (c, LW, H, hz, r): layer width (view + margins), height,
  // the floor line, and a seeded generator. setup() returns what the animated
  // pass needs; anim(c, W, H, hz, t, st, X, still) draws it, X(x, depth)
  // mapping layer x to screen x for the current camera. Original scenes of the
  // robot dojo after the Big Unplug: dark and dusty, lit floor, a crowd of
  // scavengers, and a hand-painted joke somewhere in every one.

  const DEPTH = { sky: 1, far: 0.75, mid: 0.4, floor: 0 };
  const crowdH = H => [Math.max(9, Math.round(H * 0.15)), Math.max(11, Math.round(H * 0.19))];
  const crowdN = (LW, per) => Math.max(4, Math.round(LW / per));
  // Narrow stages (phones) centre their main sign instead of placing it by fraction.
  const narrow = LW => LW < 200;
  // Two crowds, leaving the centre clear so the scene reads between the fighters.
  function crowdSides(r, LW, foot, H, per, mix, x0 = 0, x1 = LW, gap = narrow(LW) ? 0.2 : 0.09) {
    const n = crowdN(x1 - x0, per), a = LW * (0.5 - gap), b = LW * (0.5 + gap);
    if (a <= x0) return makeCrowd(r, Math.max(b, x0), x1, foot, Math.max(2, crowdN(x1 - Math.max(b, x0), per)), crowdH(H), mix);
    const na = Math.max(2, Math.round(n * (a - x0) / Math.max(1, x1 - x0 - (b - a))));
    return makeCrowd(r, x0, a, foot, na, crowdH(H), mix).concat(makeCrowd(r, b, x1, foot, Math.max(2, n - na), crowdH(H), mix));
  }

  // Sign spots shared by a static layer and its animated pass.
  const roofSigns = (LW, H) => narrow(LW)
    ? { bar: { x: Math.round(LW / 2 - textW('OIL BAR', 2) / 2), y: Math.round(H * 0.4) }, bolts: { x: -99, y: Math.round(H * 0.44) } }
    : { bar: { x: Math.round(LW * 0.52), y: Math.round(H * 0.36) }, bolts: { x: Math.round(LW * 0.14), y: Math.round(H * 0.39) } };
  const marquee = (LW, H, bs) => narrow(LW) ? { x: LW - M - bs.w - 1, y: Math.round(H * 0.34) } : { x: Math.round(LW * 0.8 - bs.w / 2), y: Math.round(H * 0.37) };
  const screenAt = (LW, H) => narrow(LW) ? { x: Math.round(LW * 0.05), y: Math.round(H * 0.12), w: Math.round(LW * 0.36), h: Math.round(H * 0.34) } : { x: Math.round(LW * 0.05), y: Math.round(H * 0.3), w: Math.round(LW * 0.36), h: Math.round(H * 0.3) };

  const STAGES = [
    {
      key: 'scrapyard', name: 'Scrapyard Dojo',
      sky(c, LW, H, hz, r) {
        gradient(c, 0, LW, 0, hz + 2, ['#0d0f12', '#151417', '#2a1d17', '#4a2a1a', '#6a381c']);
        const sx = Math.round(LW * 0.24), sy = Math.round(hz - H * 0.22);
        alpha(c, 0.14, () => disc(c, sx, sy, Math.round(H * 0.17), '#c2551b'));
        alpha(c, 0.4, () => disc(c, sx, sy, Math.round(H * 0.08), '#d86a2a'));
        for (let i = 0; i < 5; i++) alpha(c, 0.3, () => rect(c, ri(r, -30, LW), ri(r, Math.round(H * 0.2), hz - 6), ri(r, 30, 80), 1, '#3a2418'));
      },
      far(c, LW, H, hz, r) {
        const tops = ridge(c, LW, hz - 2, H * 0.3, hz + 1, '#1d1612', r, 3);
        for (let i = 0; i < LW / 5; i++) { const x = ri(r, 0, LW - 1); rect(c, x, tops[x] + ri(r, 0, 3), ri(r, 2, 5), ri(r, 1, 3), pickOf(r, ['#2a2019', '#33261c', '#231c18', '#3a2a1e'])); }
        for (let i = 0; i < LW / 30; i++) { const x = ri(r, 0, LW - 1); line(c, x, tops[x], x + ri(r, -3, 3), tops[x] - ri(r, 3, 7), '#231a14'); }
        // The crane: a lattice tower, a boom reaching left, a cab with a lit window.
        const cx = Math.round(LW * 0.84), top = Math.round(H * 0.12), tipX = cx - Math.round(LW * 0.2);
        lattice(c, cx, hz, cx, top, 3, '#241c18');
        lattice(c, tipX, top, cx + 10, top, 2, '#241c18');
        rect(c, cx + 6, top - 1, 6, 5, '#1a1412');
        rect(c, cx - 3, top + 3, 8, 5, '#2e2219'); rect(c, cx - 2, top + 4, 3, 2, '#8a6a2a');
        line(c, cx + 1, top - 5, tipX + 4, top, '#241c18'); line(c, cx + 1, top - 5, cx + 10, top, '#241c18');
      },
      mid(c, LW, H, hz, r) {
        // Corrugated fence behind the crowd, patched with rust.
        const fy = hz - Math.round(H * 0.16);
        rect(c, 0, fy, LW, hz - fy, '#2a2522');
        for (let x = 0; x < LW; x += 2) rect(c, x, fy, 1, hz - fy, '#221d1a');
        for (let i = 0; i < LW / 18; i++) { const x = ri(r, 0, LW), w = ri(r, 4, 10); rect(c, x, fy + ri(r, 0, 3), w, ri(r, 3, 8), pickOf(r, ['#4a2a18', '#3a2a20', '#2c3434'])); }
        streaks(c, 0, fy, LW, Math.round(LW / 6), hz - fy - 2, '#3a2218', r);
        rect(c, 0, fy, LW, 1, '#3e3833');
        for (let x = 4; x < LW; x += 30) rect(c, x, fy - 2, 2, hz - fy + 2, '#1a1614');
        // Scrap: stacked car hulks, tyre stacks, a traffic cone.
        car(c, Math.round(LW * 0.02), hz - 1, 30, '#4a3024', r);
        car(c, Math.round(LW * 0.04), hz - 11, 26, '#2f3e3e', r);
        car(c, Math.round(LW * 0.86), hz - 1, 28, '#3a3a44', r);
        tyres(c, Math.round(LW * 0.28), hz, 4, 5); tyres(c, Math.round(LW * 0.7), hz, 3, 5); tyres(c, Math.round(LW * 0.75), hz, 5, 5);
        cone(c, Math.round(LW * 0.36), hz); cone(c, Math.round(LW * 0.64), hz);
        const lines = ['NO RUSTING', 'IN THE DOJO'], bs = boardSize(lines);
        board(c, Math.round(LW / 2 - bs.w / 2), fy - bs.h - 2, lines, { bg: '#d9d2bc', fg: '#8a1e12', edge: '#1a1412', r, nails: true, drip: '#6a3014' });
        rect(c, Math.round(LW / 2 - bs.w / 2) + 3, fy - 2, 1, 2, '#1a1412'); rect(c, Math.round(LW / 2 + bs.w / 2) - 4, fy - 2, 1, 2, '#1a1412');
      },
      floor(c, LW, H, hz, r) {
        gradient(c, 0, LW, hz, H, ['#241c16', '#34281e', '#43342a']);
        speckle(c, 0, hz, LW, H - hz, Math.round(LW * (H - hz) / 7), ['#2c221a', '#4e3e30', '#1e1712'], r);
        // A tatami made of car mats, edged in duct tape.
        const cx = LW / 2, rows = 4, cols = 6;
        for (let y = hz + 2; y < H; y++) {
          const u = (y - hz - 2) / Math.max(1, H - hz - 2), half = LW * (0.3 + 0.16 * u), row = Math.floor(Math.pow(u, 0.75) * rows);
          for (let k = 0; k < cols; k++) {
            const x0 = cx - half + 2 * half * k / cols, x1 = cx - half + 2 * half * (k + 1) / cols;
            const base = (k + row) & 1 ? '#34373c' : '#2a2c31';
            rect(c, x0, y, x1 - x0, 1, y & 1 ? shade(base, 1.12) : base);
            px(c, x0, y, '#16181b');
          }
          rect(c, cx - half - 1, y, 2, 1, '#8b939c'); rect(c, cx + half - 1, y, 2, 1, '#8b939c');
        }
        rect(c, LW * 0.2, hz + 2, LW * 0.6, 1, '#8b939c');
        floorLight(c, LW, hz, H, '#ffd9a0', 0.2);
      },
      setup(r, LW, H, hz) {
        const top = Math.round(H * 0.12);
        return {
          crowd: crowdSides(r, LW, hz - 1, H, 11, { hazmat: 1 }),
          hook: { x: Math.round(LW * 0.84) - Math.round(LW * 0.2) + 2, y: top + 3, len: Math.round(H * 0.22) },
          dust: moteSet(r, Math.round(LW / 14), LW, H * 0.2, hz, 3, -1.5),
        };
      },
      anim(c, W, H, hz, t, st, X, still) {
        const k = st.hook, a = still ? 0.12 : Math.sin(t * 1.3) * 0.22, x0 = X(k.x, DEPTH.far);
        const hx = x0 + Math.sin(a) * k.len, hy = k.y + Math.cos(a) * k.len;
        line(c, x0, k.y, hx, hy, '#15110e');
        rect(c, hx - 1, hy, 3, 2, '#3a3f44'); px(c, hx + 1, hy + 2, '#3a3f44'); px(c, hx, hy + 3, '#3a3f44');
        duck(c, Math.round(hx) - 1, Math.round(hy) + 3);
        drawCrowd(c, st.crowd, t, X, DEPTH.mid, still);
        motes(c, st.dust, t, W, H, '#8a6a4a', still);
      },
    },
    {
      key: 'arcade', name: 'Ruined Arcade',
      sky(c, LW, H, hz, r) {
        gradient(c, 0, LW, 0, hz + 2, ['#07080b', '#0e0f15', '#15131d', '#1c1826']);
        const ch = Math.round(H * 0.18);
        for (let x = 0; x < LW; x += 12) rect(c, x, 0, 1, ch, '#050508');
        for (let y = 0; y < ch; y += 6) rect(c, 0, y, LW, 1, '#050508');
        for (let i = 0; i < LW / 24; i++) rect(c, ri(r, 0, LW / 12) * 12 + 1, ri(r, 0, 2) * 6 + 1, 11, 5, '#020203');
        for (let i = 0; i < LW / 20; i++) { const x = ri(r, 0, LW); rect(c, x, 0, 1, ri(r, 4, ch + 6), '#0a0a0e'); }
      },
      far(c, LW, H, hz, r) {
        const top = Math.round(H * 0.18);
        rect(c, 0, top, LW, hz - top, '#1a1624');
        for (let x = 0; x < LW; x += 8) rect(c, x, top, 3, hz - top, '#1d1928');
        rect(c, 0, top, LW, 2, '#0d0b12');
        for (let i = 0; i < LW / 26; i++) {
          const x = ri(r, 0, LW - 12), y = top + ri(r, 4, Math.max(5, Math.round(H * 0.18))), col = pickOf(r, ['#4a2a3a', '#2a3a4a', '#4a4028', '#3a2a4a']);
          rect(c, x, y, 9, 12, col); rect(c, x + 1, y + 2, 7, 5, shade(col, 0.6)); rect(c, x + 1, y + 8, 7, 1, shade(col, 1.3)); px(c, x + 8, y, '#1a1624');
        }
        // A door and its exit sign, crossed out in red paint.
        const dx = Math.round(LW * 0.1);
        rect(c, dx, hz - Math.round(H * 0.26), 14, Math.round(H * 0.26), '#0b0a10'); rect(c, dx + 1, hz - Math.round(H * 0.26) + 1, 12, Math.round(H * 0.26), '#14121a');
        board(c, dx, hz - Math.round(H * 0.26) - 10, ['EXIT'], { bg: '#1c4a32', fg: '#6ad08a', edge: '#0b0a10', cross: '#e0342b' });
      },
      mid(c, LW, H, hz, r) {
        // Dead cabinets: marquee, black screen, control deck, coin door.
        const ch = Math.round(H * 0.36), step = 18, lx = Math.round(LW / 2) - 7;
        const cab = (x, col, top) => {
          rect(c, x, top, 14, ch, col); rect(c, x, top, 1, ch, shade(col, 1.3)); rect(c, x + 13, top, 1, ch, shade(col, 0.6));
          rect(c, x + 1, top + 1, 12, 4, shade(col, 1.5));
          rect(c, x + 2, top + 6, 10, 9, '#050608'); rect(c, x + 3, top + 7, 8, 7, '#0c1014');
          rect(c, x - 1, top + 16, 16, 3, shade(col, 1.2)); px(c, x + 3, top + 16, '#e0342b'); px(c, x + 6, top + 16, '#36e0ff'); px(c, x + 8, top + 16, '#f2c230');
        };
        for (let x = 2, i = 0; x < LW - 10; x += step, i++) {
          if (Math.abs(x + 7 - LW / 2) < 16) continue;
          const col = pickOf(r, ['#2a1e3a', '#1e2a3a', '#3a1e22', '#20302a', '#2a2a2a']), top = hz - ch;
          rect(c, x, top, 14, ch, col); rect(c, x, top, 1, ch, shade(col, 1.3)); rect(c, x + 13, top, 1, ch, shade(col, 0.6));
          rect(c, x + 1, top + 1, 12, 4, shade(col, 1.5)); rect(c, x + 2, top + 2, 10, 2, pickOf(r, ['#5a3a1a', '#3a4a5a', '#5a2a3a']));
          rect(c, x + 2, top + 6, 10, 9, '#050608'); rect(c, x + 3, top + 7, 8, 7, '#0c1014');
          if (r() < 0.3) line(c, x + 3, top + 7, x + 9, top + 13, '#2a3a44');
          rect(c, x - 1, top + 16, 16, 3, shade(col, 1.2)); px(c, x + 3, top + 16, '#e0342b'); px(c, x + 6, top + 16, '#36e0ff'); px(c, x + 8, top + 16, '#f2c230');
          rect(c, x + 5, top + 22, 4, 5, '#0d0f12'); px(c, x + 6, top + 23, '#c2551b'); px(c, x + 6, top + 25, '#c2551b');
          if (r() < 0.15) board(c, x + 1, top + 20, ['OUT', 'OF', 'ORDER'], { bg: '#d9d2bc', fg: '#15171a', pad: 1, edge: '#9a9480' });
        }
        cab(lx, '#2a2438', hz - ch);
        rect(c, lx + 2, hz - ch + 2, 10, 2, '#8a6a1a');
        const lines = ['INSERT BOLT'], bs = boardSize(lines);
        board(c, Math.round(LW / 2 - bs.w / 2), hz - ch + 21, lines, { bg: '#15171a', fg: '#f2c230', edge: '#4b5563' });
      },
      floor(c, LW, H, hz, r) {
        gradient(c, 0, LW, hz, H, ['#1c1428', '#261a34', '#2e2040']);
        // Loud carpet: squiggles and triangles, spaced out with depth.
        for (let k = 0; k < 6; k++) {
          const y = hz + 2 + Math.round((H - hz - 4) * Math.pow(k / 6, 1.4)), sp = 8 + k * 3;
          for (let x = (k & 1) * (sp >> 1); x < LW; x += sp) {
            px(c, x, y, '#7a2a52'); px(c, x + 1, y + 1, '#7a2a52'); px(c, x + 2, y, '#7a2a52');
            px(c, x + (sp >> 1), y + 2, '#1f6a6a'); rect(c, x + (sp >> 1) - 1, y + 3, 3, 1, '#1f6a6a');
          }
        }
        for (let i = 0; i < 5; i++) alpha(c, 0.55, () => ellipse(c, ri(r, 0, LW), ri(r, hz + 3, H - 2), ri(r, 3, 9), ri(r, 1, 2), '#120c18'));
        alpha(c, 0.4, () => ellipse(c, ri(r, LW * 0.3, LW * 0.7), H - 4, 6, 1, '#3a2a14'));
        floorLight(c, LW, hz, H, '#e0c8ff', 0.2);
      },
      setup(r, LW, H, hz) {
        return {
          crowd: crowdSides(r, LW, hz - 1, H, 12, { tv: 5, hazmat: 1 }),
          live: Math.round(LW / 2) - 7, top: hz - Math.round(H * 0.36),
          dust: moteSet(r, Math.round(LW / 18), LW, H * 0.2, hz, 1, 0.6),
        };
      },
      anim(c, W, H, hz, t, st, X, still) {
        // The one cabinet that still boots: attract-mode bars and a stutter.
        const x = X(st.live, DEPTH.mid) + 3, y = st.top + 7, f = still ? 0 : Math.floor(t * 12);
        const on = still || noise('cab', f) > 0.12;
        if (on) {
          alpha(c, 0.3, () => rect(c, x - 3, y - 3, 14, 13, '#36e0ff'));
          for (let k = 0; k < 7; k++) rect(c, x, y + k, 8, 1, ['#ff4fa0', '#f2c230', '#36e0ff', '#7dff9a'][(k + (f >> 2)) % 4]);
          rect(c, x, y + (f % 7), 8, 1, '#ffffff');
        }
        drawCrowd(c, st.crowd, t, X, DEPTH.mid, still);
        motes(c, st.dust, t, W, H, '#5a4a6a', still);
      },
    },
    {
      key: 'rooftop', name: 'Acid Rain Rooftop',
      sky(c, LW, H, hz, r) {
        gradient(c, 0, LW, 0, hz + 2, ['#05070a', '#09110f', '#0f1c1c', '#16302f', '#1e3a37']);
        for (let i = 0; i < 3; i++) alpha(c, 0.2, () => ellipse(c, ri(r, 0, LW), ri(r, 4, Math.round(H * 0.3)), ri(r, 30, 60), 3, '#2a4442'));
      },
      far(c, LW, H, hz, r) {
        for (let x = -4; x < LW;) {
          const w = ri(r, 10, 24), h = Math.round(H * (0.25 + r() * 0.5)), col = pickOf(r, ['#0b1313', '#0e1818', '#101a1c']);
          rect(c, x, hz - h, w, h + 1, col);
          for (let wy = hz - h + 3; wy < hz - 3; wy += 3) for (let wx = x + 2; wx < x + w - 1; wx += 3) if (r() < 0.16) px(c, wx, wy, pickOf(r, ['#3a5a4a', '#6a4a5a', '#8a7a3a', '#2a4a5a']));
          if (r() < 0.25) rect(c, x + 1, hz - h + ri(r, 2, 8), w - 2, 1, pickOf(r, ['#5a2a4a', '#1f5a5a']));
          x += w + ri(r, 0, 4);
        }
        const tx = Math.round(LW * 0.6);
        rect(c, tx, hz - Math.round(H * 0.82), 12, Math.round(H * 0.82), '#0c1414'); rect(c, tx + 5, hz - Math.round(H * 0.82) - 8, 2, 8, '#0c1414');
      },
      mid(c, LW, H, hz, r) {
        // Parapet, a water tank, AC units, vent stacks, dark sign boards for the neon.
        rect(c, 0, hz - 5, LW, 5, '#222c2b'); rect(c, 0, hz - 5, LW, 1, '#3a4644'); streaks(c, 0, hz - 4, LW, Math.round(LW / 8), 3, '#1a2221', r);
        const wx = Math.round(LW * 0.86), wt = hz - Math.round(H * 0.42);
        for (const d of [1, 12]) rect(c, wx + d, wt + 14, 1, hz - wt - 14, '#141a1a');
        rect(c, wx, wt, 14, 14, '#2a2420'); for (let y = wt + 2; y < wt + 14; y += 3) rect(c, wx, y, 14, 1, '#1a1614');
        for (let k = 0; k < 4; k++) rect(c, wx + k, wt - 4 + k, 14 - 2 * k, 1, '#221e1a');
        for (const f of [0.08, 0.3]) { const x = Math.round(LW * f); rect(c, x, hz - 14, 16, 9, '#2e3838'); rect(c, x, hz - 14, 16, 1, '#4a5654'); disc(c, x + 5, hz - 10, 3, '#161c1c'); line(c, x + 3, hz - 10, x + 7, hz - 10, '#3a4644'); for (let y = hz - 12; y < hz - 6; y += 2) rect(c, x + 10, y, 5, 1, '#1c2424'); }
        for (const f of [0.2, 0.74]) { const x = Math.round(LW * f); rect(c, x, hz - 18, 3, 13, '#394443'); rect(c, x - 1, hz - 19, 5, 2, '#4a5654'); }
        const P = roofSigns(LW, H);
        rect(c, P.bar.x - 2, P.bar.y - 2, textW('OIL BAR', 2) + 4, 14, '#0a0f10'); rect(c, P.bar.x + 4, P.bar.y - 6, 1, 4, '#15171a'); rect(c, P.bar.x + textW('OIL BAR', 2) - 5, P.bar.y - 6, 1, 4, '#15171a');
        rect(c, P.bolts.x - 2, P.bolts.y - 2, textW('BOLTS 2 GO') + 4, 9, '#0a0f10');
      },
      floor(c, LW, H, hz, r) {
        gradient(c, 0, LW, hz, H, ['#161e20', '#1e2829', '#263232']);
        speckle(c, 0, hz, LW, H - hz, Math.round(LW * (H - hz) / 10), ['#121819', '#2c3838'], r);
        for (let i = 0; i < 4; i++) ellipse(c, ri(r, 0, LW), ri(r, hz + 4, H - 3), ri(r, 8, 18), 1, '#0e1415');
        floorLight(c, LW, hz, H, '#bfe8e0', 0.2);
      },
      setup(r, LW, H, hz) {
        return {
          crowd: crowdSides(r, LW, hz - 1, H, 13, { umbrella: 0.35, drone: 2 }),
          rain: particles(r, Math.round(LW / 2.2), r => ({ x: r() * (LW + 30), y: r() * H, v: 70 + r() * 40, l: 2 + ri(r, 0, 2) })),
          splash: particles(r, Math.round(LW / 12), r => ({ x: r() * LW, y: hz + 2 + r() * (H - hz - 3), ph: r() })),
          vents: [0.2, 0.74].map(f => Math.round(LW * f) + 1), puffs: puffSet(r, 5),
          ...roofSigns(LW, H),
          tower: { x: Math.round(LW * 0.6) + 5, y: hz - Math.round(H * 0.82) - 8 },
        };
      },
      anim(c, W, H, hz, t, st, X, still) {
        beacon(c, X(st.tower.x, DEPTH.far), st.tower.y, still || Math.floor(t * 1.5) % 2 === 0);
        st.vents.forEach((x, i) => smoke(c, X(x, DEPTH.mid), hz - 20, t + i * 1.7, st.puffs, '#8aa6a0', still, 26, 0.35));
        const f = still ? 0 : Math.floor(t * 10), barOn = still || noise('bar', f) > 0.08, boltOn = still || Math.floor(t * 1.2) % 5 !== 4;
        const bx = X(st.bar.x, DEPTH.mid), gx = X(st.bolts.x, DEPTH.mid);
        neon(c, 'OIL', bx, st.bar.y, '#ff4fa0', barOn, 2);
        neon(c, 'BAR', bx + textW('OIL ', 2) + 1, st.bar.y, '#ff4fa0', barOn && noise('bar2', f) > 0.25, 2);
        neon(c, 'BOLTS 2 GO', gx, st.bolts.y, '#36e0ff', boltOn);
        if (barOn) alpha(c, 0.25, () => rect(c, bx, hz + 6, textW('OIL BAR', 2) - 4, 1, '#ff4fa0'));
        if (boltOn) alpha(c, 0.25, () => rect(c, gx, hz + 9, textW('BOLTS 2 GO') - 2, 1, '#36e0ff'));
        drawCrowd(c, st.crowd, t, X, DEPTH.mid, still);
        alpha(c, 0.45, () => {
          c.fillStyle = '#8fb8b0';
          for (const d of st.rain) {
            const x = still ? d.x : mod(d.x - t * d.v * 0.3, W + 30) - 10, y = still ? d.y : mod(d.y + t * d.v, H);
            for (let k = 0; k < d.l; k++) c.fillRect(Math.round(x - k * 0.3), Math.round(y - k), 1, 1);
          }
          c.fillStyle = '#a8d0c8';
          for (const s of st.splash) {
            const k = still ? s.ph : mod(t * 2 + s.ph, 1);
            if (k < 0.3) { const x = Math.round(s.x), y = Math.round(s.y); c.fillRect(x - 1, y - 1, 1, 1); c.fillRect(x + 1, y - 1, 1, 1); c.fillRect(x, y, 1, 1); }
          }
        });
      },
    },
    {
      key: 'mall', name: 'Dead Mall Food Court',
      sky(c, LW, H, hz, r) {
        gradient(c, 0, LW, 0, hz + 2, ['#0a0b0e', '#101217', '#16191f', '#1c1f26']);
        // A skylight with broken panes.
        const sy = Math.round(H * 0.02), sh = Math.round(H * 0.16), x0 = Math.round(LW * 0.2), x1 = Math.round(LW * 0.8);
        rect(c, x0, sy, x1 - x0, sh, '#1a262c');
        for (let x = x0; x < x1; x += 8) for (let y = sy; y < sy + sh; y += 5) if (r() < 0.35) rect(c, x + 1, y + 1, 7, 4, '#2e4048');
        for (let x = x0; x <= x1; x += 8) rect(c, x, sy, 1, sh, '#0a0b0e');
        for (let y = sy; y <= sy + sh; y += 5) rect(c, x0, y, x1 - x0, 1, '#0a0b0e');
        alpha(c, 0.06, () => { for (let k = 0; k < hz - sy - sh; k++) rect(c, x0 + 6 - k * 0.3, sy + sh + k, x1 - x0 - 12 + k * 0.6, 1, '#b8d0d8'); });
      },
      far(c, LW, H, hz, r) {
        // The upper level: shuttered shops behind a balcony rail.
        const by = Math.round(H * 0.24), bh = Math.round(H * 0.16);
        rect(c, 0, by, LW, bh, '#1a1c22');
        for (let x = 0; x < LW; x += 26) {
          rect(c, x + 2, by + 3, 22, bh - 3, '#23262d');
          for (let y = by + 4; y < by + bh; y += 2) rect(c, x + 2, y, 22, 1, '#2c3038');
          rect(c, x + 2, by, 22, 3, pickOf(r, ['#3a2a2a', '#2a2a3a', '#2a3a30']));
        }
        rect(c, 0, by + bh, LW, 3, '#2a2d34'); rect(c, 0, by + bh, LW, 1, '#4b5563');
        for (let x = 0; x < LW; x += 3) rect(c, x, by + bh - 4, 1, 4, '#3a3f48');
        rect(c, 0, by + bh - 5, LW, 1, '#4b5563');
        rect(c, 0, by + bh + 3, LW, hz - by - bh - 3, '#15171c');
        // A dead escalator climbing to the right.
        const ex0 = Math.round(LW * 0.74), ex1 = Math.round(LW * 0.98);
        for (let x = ex0; x < ex1; x++) {
          const u = (x - ex0) / (ex1 - ex0), yt = Math.round(hz - 4 - u * (hz - 4 - by - bh));
          rect(c, x, yt, 1, 4, x % 3 ? '#2e3138' : '#1e2026'); px(c, x, yt - 3, '#0d0f12'); px(c, x, yt - 4, '#4b5563');
        }
        // The food court sign has lost some letters.
        rect(c, Math.round(LW * 0.26 - 24), by + bh + 4, 47, 9, '#101116'); text(c, 'FO D  C URT', Math.round(LW * 0.26 - 21), by + bh + 6, '#c05a3a');
      },
      mid(c, LW, H, hz, r) {
        // The broken fountain, between the fighters.
        const fx = Math.round(LW / 2), fw = Math.round(Math.min(26, LW * 0.12));
        ellipse(c, fx, hz - 3, fw, 3, '#4b5058'); ellipse(c, fx, hz - 3, fw - 2, 2, '#1c2620'); rect(c, fx - fw, hz - 3, 2 * fw + 1, 3, '#3e434b');
        rect(c, fx - fw, hz - 3, 2 * fw + 1, 1, '#6a707a');
        rect(c, fx - 1, hz - 7, 3, 4, '#4b5058'); ellipse(c, fx, hz - 7, 4, 1, '#5a6068'); rect(c, fx - 4, hz - 7, 9, 1, '#6a707a');
        line(c, fx - 4, hz - 3, fx - 2, hz - 1, '#15171a'); line(c, fx + 7, hz - 2, fx + 9, hz - 3, '#15171a');
        // Toppled tables and chairs.
        for (const f of [0.08, 0.3, 0.68, 0.9]) {
          const x = Math.round(LW * f);
          if (r() < 0.5) { rect(c, x, hz - 6, 10, 1, '#5a4a3a'); rect(c, x + 4, hz - 5, 2, 5, '#2a2622'); }
          else { rect(c, x, hz - 3, 2, 3, '#5a4a3a'); rect(c, x + 2, hz - 2, 8, 2, '#4a3a2a'); }
          rect(c, x + 12, hz - 4, 3, 1, '#8a2a24'); rect(c, x + 12, hz - 3, 1, 3, '#2a2622'); rect(c, x + 14, hz - 3, 1, 3, '#2a2622');
        }
        const lines = ['BETS IN', 'BOTTLE CAPS', 'ONLY'], bs = boardSize(lines);
        const bx = Math.round(LW / 2 - bs.w / 2), bt = hz - 9 - bs.h, wy = Math.round(H * 0.4);
        rect(c, bx + 3, wy, 1, bt - wy, '#3a3f48'); rect(c, bx + bs.w - 4, wy, 1, bt - wy, '#3a3f48');
        board(c, bx, bt, lines, { bg: '#15171a', fg: '#e8edf2', edge: '#4b5563' });
        cube(c, bx + bs.w - 5, bt + bs.h + 1, 2, '#f2c230', '#b8922a', '#8a6a1a');
      },
      floor(c, LW, H, hz, r) {
        gradient(c, 0, LW, hz, H, ['#3a3832', '#4a463e', '#56524a']);
        const vy = hz - (H - hz) * 1.3;
        for (let y = hz; y < H; y++) {
          const k = Math.floor((H - hz) * Math.pow((y - hz) / (H - hz), 0.6) / 4), sp = Math.max(4, 10 * (y - vy) / (H - vy));
          for (let x = LW / 2 - Math.ceil(LW / 2 / sp) * sp, n = 0; x < LW; x += sp, n++) if ((n + k) & 1) rect(c, x, y, Math.ceil(sp), 1, '#2e2c28');
        }
        speckle(c, 0, hz, LW, H - hz, Math.round(LW * (H - hz) / 12), ['#26241f', '#6a665c'], r);
        rect(c, 0, hz, LW, 1, '#1e1d1a');
        floorLight(c, LW, hz, H, '#f0e6c8', 0.18);
      },
      setup(r, LW, H, hz) {
        return {
          crowd: crowdSides(r, LW, hz - 1, H, 13, { cart: 5, bot: 3, tv: 1 }),
          tube: { x: Math.round(LW * 0.1), y: Math.round(H * 0.2) }, fx: Math.round(LW / 2), drops: particles(r, 4, r => ({ ph: r(), dx: ri(r, -5, 5) })),
        };
      },
      anim(c, W, H, hz, t, st, X, still) {
        const f = still ? 0 : Math.floor(t * 10), on = still || noise('tube', f) > 0.3;
        const tx = X(st.tube.x, DEPTH.far);
        rect(c, tx, st.tube.y, 24, 1, on ? '#e8f4f0' : '#3a4044');
        if (on) alpha(c, 0.12, () => rect(c, tx - 4, st.tube.y + 1, 32, 8, '#e8f4f0'));
        const fx = X(st.fx, DEPTH.mid);
        for (const d of st.drops) { const k = still ? d.ph : mod(t * 1.2 + d.ph, 1); px(c, fx + Math.round(d.dx * k * 0.6), hz - 8 + Math.round(k * 5), '#6a8a8a'); }
        drawCrowd(c, st.crowd, t, X, DEPTH.mid, still);
      },
    },
    {
      key: 'harbour', name: 'Rusted Harbour',
      sky(c, LW, H, hz, r) {
        gradient(c, 0, LW, 0, hz + 2, ['#0d0f12', '#17171d', '#2a2024', '#4e2e22', '#7a4224']);
        for (let i = 0; i < 4; i++) alpha(c, 0.35, () => rect(c, ri(r, -20, LW), ri(r, Math.round(H * 0.3), Math.round(H * 0.5)), ri(r, 40, 90), 1, '#8a4a2a'));
      },
      far(c, LW, H, hz, r) {
        const wy = hz - Math.round(H * 0.13);
        // A freighter, listing, down by the stern.
        const x0 = Math.round(LW * 0.08), x1 = Math.round(LW * 0.66), hh = Math.round(H * 0.2), tilt = H * 0.09 / Math.max(1, x1 - x0);
        const deck = x => Math.round(wy - hh + (x - x0) * tilt);
        for (let x = x0; x < x1; x++) {
          const bow = Math.max(0, 6 - (x - x0)), y = deck(x) + bow;
          rect(c, x, y, 1, wy - y, '#36201a'); px(c, x, y, '#5a3424'); px(c, x, y + 3, '#2a1812'); px(c, x, wy - 2, '#5a1e16');
        }
        streaks(c, x0 + 4, deck(x0) + 3, x1 - x0 - 4, Math.round((x1 - x0) / 5), hh - 5, '#5a2a14', r);
        const sx = x1 - 22;
        for (let x = sx; x < sx + 18; x++) { const y = deck(x); rect(c, x, y - 14, 1, 14, '#40291e'); if (x % 3 === 0) { px(c, x, y - 12, '#8a6a2a'); px(c, x, y - 7, '#15110f'); } }
        for (let x = sx + 6; x < sx + 11; x++) { rect(c, x, deck(x) - 21, 1, 7, '#2a1812'); px(c, x, deck(x) - 19, '#7a2a16'); }
        for (let x = x0 + 10; x < sx - 4; x += 9) rect(c, x, deck(x) - 4, 7, 4, pickOf(r, ['#3a2018', '#1e2a2a', '#2a2a36']));
        // Gantry cranes.
        for (const f of [0.74, 0.92]) {
          const gx = Math.round(LW * f), top = Math.round(H * 0.18);
          lattice(c, gx - 6, wy, gx - 4, top, 1, '#1e1a1c'); lattice(c, gx + 6, wy, gx + 4, top, 1, '#1e1a1c');
          lattice(c, gx - 24, top, gx + 12, top, 2, '#1e1a1c');
        }
        // Oil-slick water.
        gradient(c, 0, LW, wy, hz + 1, ['#0c1214', '#101a1c', '#141f20']);
        for (let i = 0; i < LW / 8; i++) rect(c, ri(r, 0, LW), ri(r, wy + 1, hz), ri(r, 3, 10), 1, pickOf(r, ['#1c2a2a', '#0a0e10']));
      },
      mid(c, LW, H, hz, r) {
        // Containers stacked at both ends; one says what everybody knows.
        const ch = Math.round(H * 0.14);
        const cont = (x, y, w, col) => {
          rect(c, x, y, w, ch, col); for (let k = x + 1; k < x + w; k += 2) rect(c, k, y + 1, 1, ch - 2, shade(col, 0.8));
          rect(c, x, y, w, 1, shade(col, 1.3)); rect(c, x, y + ch - 1, w, 1, shade(col, 0.55)); streaks(c, x, y + 1, w, Math.round(w / 5), ch - 2, '#5a2a14', r);
        };
        cont(-6, hz - ch - 2, 42, '#6a2e16'); cont(0, hz - 2 * ch - 2, 30, '#2c524c');
        const lines = ['DOJO OPEN', '24/7 SINCE', 'THE END'], bs = boardSize(lines, 1, 1);
        const cw = Math.max(46, bs.w + 6), cx = LW - M - cw - (narrow(LW) ? 0 : 6);
        const ch2 = Math.max(ch, bs.h + 3);
        rect(c, cx, hz - ch2 - 2, cw, ch2, '#2a3a5a'); for (let k = cx + 1; k < cx + cw; k += 2) rect(c, k, hz - ch2 - 1, 1, ch2 - 2, '#243350');
        rect(c, cx, hz - ch2 - 2, cw, 1, '#3e5078'); streaks(c, cx, hz - ch2 - 1, cw, 8, ch2 - 2, '#5a2a14', r);
        lines.forEach((ln, i) => text(c, ln, cx + 3 + ((cw - 6 - textW(ln)) >> 1), hz - ch2 + 1 + i * 6, '#d9d2bc'));
        cont(cx + 8, hz - ch2 - ch - 2, 30, '#7a4a1a');
        // The quay edge, with bollards.
        rect(c, 0, hz - 2, LW, 2, '#3a3834'); rect(c, 0, hz - 2, LW, 1, '#5a5650');
        for (let x = Math.round(LW * 0.25); x < LW * 0.8; x += Math.round(LW * 0.18)) { rect(c, x, hz - 6, 4, 4, '#1a1c1e'); rect(c, x - 1, hz - 7, 6, 1, '#2a2c30'); }
      },
      floor(c, LW, H, hz, r) {
        gradient(c, 0, LW, hz, H, ['#2a2824', '#36322c', '#423c34']);
        seams(c, LW, hz, H, 4, '#1e1c18', 1.5); converging(c, LW, hz, H, 36, '#1e1c18', 1.3);
        for (let i = 0; i < LW / 5; i++) px(c, ri(r, 0, LW), ri(r, hz + 2, H - 1), '#5a544a');
        for (let i = 0; i < 6; i++) alpha(c, 0.5, () => ellipse(c, ri(r, 0, LW), ri(r, hz + 3, H - 2), ri(r, 4, 12), 1, '#5a2a14'));
        rect(c, 0, hz + 2, LW, 1, '#8a7424');
        floorLight(c, LW, hz, H, '#ffd9b0', 0.18);
      },
      setup(r, LW, H, hz) {
        const wy = hz - Math.round(H * 0.13);
        return {
          crowd: crowdSides(r, LW, hz - 2, H, 12, { drone: 2 }, LW * 0.12, LW * 0.84),
          sheen: particles(r, Math.round(LW / 14), r => ({ x: r() * LW, y: wy + 1 + ri(r, 0, Math.max(0, hz - wy - 2)), w: ri(r, 4, 12), col: pickOf(r, ['#6a2a6a', '#2a6a6a', '#6a6a2a', '#3a4a8a']), v: 1 + r() * 2 })),
          lights: [0.74, 0.92].map(f => ({ x: Math.round(LW * f) - 24, y: Math.round(H * 0.18) })),
        };
      },
      anim(c, W, H, hz, t, st, X, still) {
        for (const s of st.sheen) alpha(c, 0.4, () => rect(c, X(still ? s.x : mod(s.x + t * s.v, W + 20) - 10, DEPTH.far), s.y, s.w, 1, s.col));
        st.lights.forEach((l, i) => beacon(c, X(l.x, DEPTH.far), l.y, still || Math.floor(t * 1.2 + i) % 2 === 0));
        drawCrowd(c, st.crowd, t, X, DEPTH.mid, still);
      },
    },
    {
      key: 'freeway', name: 'Overgrown Freeway',
      sky(c, LW, H, hz, r) {
        gradient(c, 0, LW, 0, hz + 2, ['#0c100e', '#141a17', '#1e2621', '#2c362e', '#3c4638']);
        for (let i = 0; i < 4; i++) alpha(c, 0.25, () => ellipse(c, ri(r, 0, LW), ri(r, 6, Math.round(H * 0.4)), ri(r, 20, 50), 2, '#3a4a40'));
      },
      far(c, LW, H, hz, r) {
        ridge(c, LW, hz - 2, H * 0.1, hz + 1, '#18201a', r, 2);
        // A broken overpass, vines hanging off the deck, a sign hanging askew.
        const dy = Math.round(H * 0.26), dh = 6, gap0 = Math.round(LW * 0.52), gap1 = Math.round(LW * 0.62);
        for (const [a, b] of [[0, gap0], [gap1, LW]]) {
          rect(c, a, dy, b - a, dh, '#2a2e2c'); rect(c, a, dy, b - a, 1, '#3a403c'); rect(c, a, dy + dh - 1, b - a, 1, '#1a1e1c');
          for (let x = a; x < b; x += 3) if (r() < 0.6) rect(c, x, dy + dh, 1, ri(r, 1, 9), pickOf(r, ['#1f3a22', '#2a4a2a', '#18301c']));
        }
        for (let k = 0; k < 5; k++) line(c, gap0 + k, dy + 2 + k, gap0 + k + 1, dy + dh + 2 + ri(r, 0, 4), '#4a3a2a');
        for (const f of [0.12, 0.4, 0.8]) { const x = Math.round(LW * f); rect(c, x, dy + dh, 7, hz - dy - dh, '#222624'); rect(c, x, dy + dh, 1, hz - dy - dh, '#2e3430'); }
        const lines = ['DOJO', 'NEXT RIGHT'], bs = boardSize(lines, 1, 2), sx = narrow(LW) ? Math.round(LW / 2 - bs.w / 2) : Math.round(LW * 0.24), sy = dy + dh + 3;
        line(c, sx + 4, dy + dh, sx + 4, sy, '#4b5563'); line(c, sx + bs.w - 6, dy + dh, sx + bs.w - 3, sy + 3, '#4b5563');
        for (let y = 0; y < bs.h; y++) rect(c, sx + Math.round(y * 0.35), sy + y + Math.round(y > 0 ? 0 : 0), bs.w, 1, y === 0 || y === bs.h - 1 ? '#d8dccf' : '#1f4a32');
        lines.forEach((ln, i) => text(c, ln, sx + 3 + ((bs.w - 6 - textW(ln)) >> 1) + Math.round((3 + i * 6) * 0.35), sy + 3 + i * 6, '#d8dccf', 1, 0.35));
      },
      mid(c, LW, H, hz, r) {
        // Jersey barriers and cars swallowed by vines.
        for (let x = 0; x < LW; x += 20) { for (let k = 0; k < 6; k++) rect(c, x + 2 - (k >> 1), hz - 6 + k, 14 + (k >> 1) * 2, 1, k ? '#4a4c48' : '#5e605a'); if (r() < 0.3) rect(c, x + 5, hz - 4, 6, 1, pickOf(r, ['#8a3a4a', '#3a6a8a'])); }
        const vine = (x0, y0, w, h) => { for (let i = 0; i < (w * h) / 3; i++) px(c, x0 + ri(r, 0, w), y0 + ri(r, 0, h), pickOf(r, ['#1f3a22', '#2a4a2a', '#3a5a2a', '#18301c'])); };
        for (const [f, col] of [[0.02, '#3a3040'], [0.3, '#4a3a24'], [0.72, '#2a3a4a'], [0.88, '#44302a']]) {
          const x = Math.round(LW * f), w = 26;
          car(c, x, hz - 1, w, col, r); vine(x - 1, hz - Math.round(w * 0.36), w + 2, Math.round(w * 0.3));
          for (let k = 0; k < 3; k++) line(c, x + ri(r, 0, w), hz - 1, x + ri(r, 0, w), hz - 10, '#2a4a2a');
        }
        for (let i = 0; i < LW / 3; i++) { const x = ri(r, 0, LW); rect(c, x, hz - ri(r, 1, 4), 1, 4, pickOf(r, ['#2a4a2a', '#3a5a2a', '#4a5a2a'])); }
        cone(c, Math.round(LW * 0.44), hz);
      },
      floor(c, LW, H, hz, r) {
        gradient(c, 0, LW, hz, H, ['#222422', '#2c2e2c', '#363836']);
        speckle(c, 0, hz, LW, H - hz, Math.round(LW * (H - hz) / 9), ['#1a1c1a', '#40423e'], r);
        // Faded lane dashes, converging.
        const vy = hz - (H - hz) * 1.2;
        for (const f of [0.3, 0.7]) for (let y = hz + 1; y < H; y++) if (Math.floor(Math.sqrt(y - hz) * 1.4) % 2 === 0) px(c, LW / 2 + (LW * f - LW / 2) * (y - vy) / (H - vy), y, '#6a6440');
        // Cracks with weeds.
        for (let i = 0; i < 7; i++) {
          let x = ri(r, 0, LW), y = ri(r, hz + 2, H - 2);
          for (let k = 0; k < 12; k++) { px(c, x, y, '#141614'); x += ri(r, -1, 1) + 1; y += ri(r, -1, 1); if (k % 4 === 0) px(c, x, y - 1, '#3a5a2a'); }
        }
        floorLight(c, LW, hz, H, '#e8f0d0', 0.18);
      },
      setup(r, LW, H, hz) {
        return {
          crowd: crowdSides(r, LW, hz - 1, H, 12, { hazmat: 3, drone: 1 }),
          flies: moteSet(r, Math.round(LW / 12), LW, H * 0.3, H * 0.95, 1.5, -0.8),
        };
      },
      anim(c, W, H, hz, t, st, X, still) {
        drawCrowd(c, st.crowd, t, X, DEPTH.mid, still);
        motes(c, st.flies, t, W, H, '#d8e87a', still);
      },
    },
    {
      key: 'drivein', name: 'Drive-In Ruin',
      sky(c, LW, H, hz, r) {
        gradient(c, 0, LW, 0, hz + 2, ['#04050a', '#080a14', '#0e1020', '#16162a']);
        stars(c, LW, Math.round(H * 0.5), Math.round(LW / 7), r, ['#8a8ab0', '#50507a', '#c8c8e0']);
      },
      far(c, LW, H, hz, r) {
        // The screen on its scaffold, torn at the corners.
        const { x: sx, w: sw, y: sy, h: sh } = screenAt(LW, H);
        for (let x = sx + 4; x < sx + sw; x += 10) { rect(c, x, sy + sh, 1, hz - sy - sh, '#1a1a20'); line(c, x, sy + sh, x + 10, hz, '#15151a'); }
        rect(c, sx - 2, sy - 2, sw + 4, sh + 4, '#1c1c22'); rect(c, sx, sy, sw, sh, '#5a564a');
        for (let i = 0; i < 4; i++) { const x = sx + ri(r, 0, sw - 6), y = sy + (r() < 0.5 ? 0 : sh - 4); rect(c, x, y, ri(r, 3, 7), ri(r, 2, 4), '#101018'); }
        // Speaker posts and a snack-bar roof on the right.
        const kx = Math.round(LW * 0.7), ky = hz - Math.round(H * 0.2);
        rect(c, kx, ky, Math.round(LW * 0.26), hz - ky, '#1e1a1e'); rect(c, kx - 2, ky - 2, Math.round(LW * 0.26) + 4, 3, '#2e262a');
        rect(c, kx + 4, ky + 4, 10, 5, '#3a3020'); rect(c, kx + 18, ky + 4, 10, 5, '#2a2018');
      },
      mid(c, LW, H, hz, r) {
        // The marquee: what's on tonight (its bulbs chase in the animated pass).
        const lines = ['NOW SHOWING', 'THE MONTAGE'], bs = boardSize(lines), { x: mx, y: my } = marquee(LW, H, bs);
        rect(c, mx + 4, my + bs.h, 2, hz - my - bs.h, '#1a1a20'); rect(c, mx + bs.w - 6, my + bs.h, 2, hz - my - bs.h, '#1a1a20');
        board(c, mx, my, lines, { bg: '#e8e2cc', fg: '#15171a', edge: '#6a1e1e' });
        // Rows of dead cars facing the screen; posts with speakers.
        const cols = ['#3a2a2a', '#2a3440', '#3a3a2a', '#2e2a3a', '#40302a'];
        for (let x = 2, i = 0; x < LW - 10; x += 26, i++) {
          if (i % 3 === 1) { rect(c, x + 22, hz - 10, 1, 10, '#2a2a30'); rect(c, x + 21, hz - 11, 3, 2, '#3a3a44'); }
          carRear(c, x, hz, 18, pickOf(r, cols));
        }
      },
      floor(c, LW, H, hz, r) {
        gradient(c, 0, LW, hz, H, ['#24221f', '#2e2b27', '#38342f']);
        speckle(c, 0, hz, LW, H - hz, Math.round(LW * (H - hz) / 5), ['#1a1816', '#46413a', '#3e3a34'], r);
        for (const f of [0.34, 0.66]) { const vy = hz - (H - hz) * 1.2; for (let y = hz; y < H; y++) { const x = LW / 2 + (LW * f - LW / 2) * (y - vy) / (H - vy); px(c, x, y, '#1a1816'); px(c, x + 3, y, '#1a1816'); } }
        floorLight(c, LW, hz, H, '#f0e0c0', 0.2);
      },
      setup(r, LW, H, hz) {
        const lines = ['NOW SHOWING', 'THE MONTAGE'], bs = boardSize(lines);
        const cars = [];
        for (let x = 2; x < LW - 10; x += 26) cars.push(x);
        return {
          crowd: crowdSides(r, LW, hz - 1, H, 14, { hazmat: 2, drone: 2 }, narrow(LW) ? 0 : Math.round(LW * 0.43)),
          screen: screenAt(LW, H),
          marquee: Object.assign(marquee(LW, H, bs), { w: bs.w, h: bs.h }), cars, hz,
        };
      },
      anim(c, W, H, hz, t, st, X, still) {
        // The montage: a robot silhouette trains on the screen, with a flicker and scratches.
        const S = st.screen, sx = X(S.x, DEPTH.far), f = still ? 0 : Math.floor(t * 12);
        const lum = still ? 0 : noise('film', f) * 0.12;
        alpha(c, 0.55 + lum, () => rect(c, sx, S.y, S.w, S.h, '#b8b098'));
        const u = Math.max(1, Math.round(S.h / 13)), gx = sx + Math.round(S.w * 0.3), gy = S.y + S.h - 2 - 10 * u;
        const POSES = [
          [[3, 0, 2, 2], [3, 2, 2, 4], [2, 6, 1, 4], [5, 6, 1, 4], [5, 2, 2, 1], [6, 1, 1, 1], [1, 3, 2, 1], [1, 2, 1, 1]],
          [[3, 0, 2, 2], [3, 2, 2, 4], [2, 6, 1, 4], [5, 6, 1, 4], [5, 2, 4, 1], [1, 3, 2, 1], [1, 2, 1, 1]],
          [[3, 0, 2, 2], [3, 2, 2, 4], [3, 6, 1, 4], [5, 5, 2, 1], [6, 6, 1, 2], [0, 1, 3, 1], [5, 1, 3, 1]],
          [[2, 0, 2, 2], [2, 2, 2, 4], [2, 6, 1, 4], [4, 4, 4, 1], [0, 2, 2, 1], [4, 2, 1, 1]],
          [[3, 1, 2, 2], [3, 3, 2, 3], [2, 6, 1, 4], [5, 6, 1, 4], [1, 2, 2, 1], [5, 2, 2, 1], [0, 1, 1, 1], [7, 1, 1, 1]],
        ];
        const pose = POSES[still ? 2 : Math.floor(t * 1.6) % POSES.length];
        for (const [x, y, w, h] of pose) rect(c, gx + x * u, gy + y * u, w * u, h * u, '#101014');
        px(c, gx + 4 * u, gy + (pose === POSES[4] ? 1 : 0) * u + Math.floor(u / 2), '#e0342b');
        if (!still) for (let k = 0; k < 2; k++) if (noise('scr' + k, f) > 0.6) rect(c, sx + Math.round(noise('sx' + k, f) * S.w), S.y, 1, S.h, '#e8e2cc');
        // Marquee bulbs chase.
        const Mq = st.marquee, mx = X(Mq.x, DEPTH.mid), ch = still ? 0 : Math.floor(t * 8);
        for (let i = 0; i < Mq.w; i += 2) { const on = (i / 2 + ch) % 3 === 0; px(c, mx + i, Mq.y - 1, on ? '#fff2a0' : '#6a5a20'); px(c, mx + Mq.w - 1 - i, Mq.y + Mq.h, on ? '#fff2a0' : '#6a5a20'); }
        // Tail lights glow as if the cars remember.
        for (const x of st.cars) { const on = still || noise('tl' + x, Math.floor(t * 2)) > 0.2; const lx = X(x, DEPTH.mid); px(c, lx + 1, st.hz - 5, on ? '#e0342b' : '#4a1410'); px(c, lx + 16, st.hz - 5, on ? '#e0342b' : '#4a1410'); }
        drawCrowd(c, st.crowd, t, X, DEPTH.mid, still);
      },
    },
    {
      key: 'refinery', name: 'Refinery at Dusk',
      sky(c, LW, H, hz, r) {
        gradient(c, 0, LW, 0, hz + 2, ['#0d0f12', '#1a1320', '#33191f', '#5a2a1e', '#8a4420']);
        for (let i = 0; i < 5; i++) alpha(c, 0.3, () => rect(c, ri(r, -20, LW), ri(r, Math.round(H * 0.15), Math.round(H * 0.55)), ri(r, 40, 100), ri(r, 1, 2), '#1e1418'));
      },
      far(c, LW, H, hz, r) {
        const col = '#17111a';
        for (let x = -4; x < LW;) {
          const kind = r(), w = ri(r, 6, 14);
          if (kind < 0.4) { const h = Math.round(H * (0.3 + r() * 0.3)); rect(c, x, hz - h, w >> 1, h, col); for (let y = hz - h + 4; y < hz; y += 6) rect(c, x - 1, y, (w >> 1) + 3, 1, col); }
          else if (kind < 0.7) { const rr = ri(r, 4, 7); disc(c, x + rr, hz - rr - 4, rr, col); rect(c, x + 1, hz - 5, 1, 5, col); rect(c, x + 2 * rr - 1, hz - 5, 1, 5, col); }
          else { const h = Math.round(H * 0.12); rect(c, x, hz - h, w + 4, h, col); }
          if (r() < 0.4) px(c, x + 1, hz - ri(r, 4, Math.round(H * 0.3)), '#c89a3a');
          x += w + ri(r, 1, 5);
        }
        for (let y = hz - Math.round(H * 0.14); y < hz; y += 4) rect(c, 0, y, LW, 1, col);
        const fx = Math.round(LW * 0.63), top = Math.round(H * 0.36);
        rect(c, fx, top, 3, hz - top, col); lattice(c, fx - 3, hz, fx - 1, top + 6, 1, col); lattice(c, fx + 6, hz, fx + 4, top + 6, 1, col);
      },
      mid(c, LW, H, hz, r) {
        // A storage tank, pipe runs with valves, and the dojo's two rules.
        const tx = Math.round(LW * 0.02), tw = 40, th = Math.round(H * 0.26);
        rect(c, tx, hz - th, tw, th, '#3a2c26'); rect(c, tx, hz - th, tw, 1, '#5a4438');
        for (let k = 0; k < 3; k++) rect(c, tx + tw - 1 - k, hz - th, 1, th, shade('#3a2c26', 0.8 - k * 0.1));
        for (let y = hz - th + 4; y < hz; y += 5) rect(c, tx, y, tw, 1, '#2e231e');
        streaks(c, tx, hz - th + 1, tw, 10, th - 3, '#6a3014', r);
        for (let k = 0; k < th; k += 2) px(c, tx + tw + 2, hz - th + k, '#4b5563');
        const lines = ['OIL ON', 'OIL OFF'], bs = boardSize(lines, 1, 2), px0 = Math.round(LW / 2 - bs.w / 2), py = hz - 16 - bs.h;
        rect(c, 0, py - 2, LW, 2, '#2a2426'); rect(c, 0, py - 2, LW, 1, '#4a3e3a');
        rect(c, px0 + 3, py, 1, 2, '#15171a'); rect(c, px0 + bs.w - 4, py, 1, 2, '#15171a');
        board(c, px0, py + 2, lines, { bg: '#1f3a36', fg: '#e8edf2', edge: '#0d0f12', r, nails: true });
        for (const [y, col] of [[hz - 7, '#4a3c34'], [hz - 12, '#3a3a40']]) {
          rect(c, 0, y, LW, 3, col); rect(c, 0, y, LW, 1, shade(col, 1.3)); rect(c, 0, y + 2, LW, 1, shade(col, 0.7));
          for (let x = ri(r, 4, 20); x < LW; x += ri(r, 26, 46)) { rect(c, x, y - 1, 3, 5, shade(col, 0.8)); if (r() < 0.6) { rect(c, x - 1, y - 4, 5, 1, '#9a2a1e'); rect(c, x + 1, y - 4, 1, 3, '#9a2a1e'); } }
        }
        warnSign(c, Math.round(LW * 0.68), hz - 22); warnSign(c, Math.round(LW * 0.3), hz - 22);
      },
      floor(c, LW, H, hz, r) {
        gradient(c, 0, LW, hz, H, ['#262422', '#322e2a', '#3e3934']);
        for (let y = hz + 1; y < H; y += 2) for (let x = (y >> 1) & 1 ? 0 : 2; x < LW; x += 4) px(c, x, y, '#4a443c');
        seams(c, LW, hz, H, 4, '#1a1816', 1.5); converging(c, LW, hz, H, 40, '#1a1816', 1.3);
        for (let i = 0; i < 5; i++) alpha(c, 0.5, () => ellipse(c, ri(r, 0, LW), ri(r, hz + 3, H - 2), ri(r, 4, 12), 1, '#0e0c0a'));
        floorLight(c, LW, hz, H, '#ffc890', 0.22);
      },
      setup(r, LW, H, hz) {
        return {
          crowd: crowdSides(r, LW, hz - 1, H, 12, { hazmat: 3 }, LW * 0.14, LW),
          flare: { x: Math.round(LW * 0.63) + 1, y: Math.round(H * 0.36) }, puffs: puffSet(r, 6),
          valve: { x: Math.round(LW * 0.5), y: hz - 13 },
        };
      },
      anim(c, W, H, hz, t, st, X, still) {
        const F = st.flare, fx = X(F.x, DEPTH.far), f = still ? 0 : Math.floor(t * 12);
        const g = still ? 0.5 : 0.35 + noise('glow', f >> 1) * 0.3;
        alpha(c, 0.18 * g + 0.05, () => disc(c, fx, F.y - 4, 12, '#ff8a2a'));
        smoke(c, fx, F.y - 10, t, st.puffs, '#2a1e20', still, 30, 0.6);
        for (let k = 0; k < 7; k++) {
          const hgt = Math.round((7 - Math.abs(k - 3) * 2) * (0.6 + (still ? 0.3 : noise('fl' + k, f) * 0.6)));
          const x = fx - 3 + k;
          rect(c, x, F.y - hgt, 1, hgt, '#e0342b'); rect(c, x, F.y - Math.round(hgt * 0.7), 1, Math.round(hgt * 0.7), '#f28a2a'); if (k > 1 && k < 5) rect(c, x, F.y - Math.round(hgt * 0.35), 1, Math.round(hgt * 0.35), '#ffe070');
        }
        smoke(c, X(st.valve.x, DEPTH.mid), st.valve.y, t * 1.4, st.puffs, '#a8a4a0', still, 14, 0.3);
        drawCrowd(c, st.crowd, t, X, DEPTH.mid, still);
      },
    },
    {
      key: 'reactor', name: 'Reactor Crater',
      sky(c, LW, H, hz, r) {
        gradient(c, 0, LW, 0, hz + 2, ['#040706', '#08100d', '#0e1a15', '#15291f', '#1e3d2c']);
        alpha(c, 0.12, () => ellipse(c, Math.round(LW / 2), hz, Math.round(LW * 0.4), Math.round(H * 0.3), '#7dff9a'));
        alpha(c, 0.1, () => ellipse(c, Math.round(LW / 2), hz, Math.round(LW * 0.22), Math.round(H * 0.18), '#7dff9a'));
        stars(c, LW, Math.round(H * 0.3), Math.round(LW / 14), r, ['#3a5a4a']);
      },
      far(c, LW, H, hz, r) {
        // A cracked cooling tower, the crater rim on both sides.
        const cx = Math.round(LW * 0.18), top = Math.round(H * 0.18), th = hz - top;
        for (let y = top; y < hz; y++) {
          const u = (y - top) / th, half = Math.round(LW * 0.07 * (0.72 + 0.5 * Math.pow(u - 0.55, 2) * 2));
          rect(c, cx - half, y, 2 * half, 1, '#141c18'); px(c, cx - half, y, '#1e2a24');
        }
        for (let k = 0; k < 8; k++) rect(c, cx + 2 + ri(r, -1, 1), top + k, 3 - (k >> 2), 1, '#0a100d');
        const tops = ridge(c, LW, hz - 1, H * 0.2, hz + 1, '#0f1713', r, 2);
        for (let x = Math.round(LW * 0.38); x < LW * 0.62; x++) rect(c, x, tops[x], 1, 2, '#0a100d');
        for (let x = 0; x < LW; x++) if (r() < 0.1) px(c, x, tops[x], '#2a4a38');
      },
      mid(c, LW, H, hz, r) {
        // Hazard barriers, warning signs on posts, leaking drums, and advice.
        for (const [a, b] of [[0, Math.round(LW * 0.3)], [Math.round(LW * 0.7), LW]]) { hazard(c, a, hz - 6, b - a, 3, '#b8922a', '#15171a', 2); rect(c, a, hz - 3, b - a, 3, '#2a2c2a'); for (let x = a + 3; x < b; x += 16) rect(c, x, hz - 3, 2, 3, '#15171a'); }
        for (const f of [0.08, 0.4, 0.6, 0.93]) { const x = Math.round(LW * f); rect(c, x, hz - 16, 1, 16, '#2a2e2c'); warnSign(c, x, hz - 22); }
        drum(c, Math.round(LW * 0.33), hz, '#3a4a2a', '#5ad07a'); drum(c, Math.round(LW * 0.35) + 5, hz, '#4a3a22', null); drum(c, Math.round(LW * 0.66), hz, '#3a3a3a', '#5ad07a');
        const lines = ['DO NOT LICK', 'THE REACTOR'], bs = boardSize(lines);
        const bx = Math.round(LW / 2 - bs.w / 2), by = hz - 9 - bs.h;
        rect(c, bx + 4, by + bs.h, 1, hz - by - bs.h, '#2a2e2c'); rect(c, bx + bs.w - 5, by + bs.h, 1, hz - by - bs.h, '#2a2e2c');
        board(c, bx, by, lines, { bg: '#c9a02a', fg: '#15171a', edge: '#15171a', r });
      },
      floor(c, LW, H, hz, r) {
        gradient(c, 0, LW, hz, H, ['#1a1e1b', '#222723', '#2a302b']);
        speckle(c, 0, hz, LW, H - hz, Math.round(LW * (H - hz) / 9), ['#141815', '#343a35'], r);
        for (let i = 0; i < 8; i++) {
          let x = ri(r, 0, LW), y = ri(r, hz + 2, H - 2);
          for (let k = 0; k < 14; k++) { px(c, x, y, k % 3 ? '#2f8a50' : '#5ad07a'); x += ri(r, -1, 1) + (i & 1 ? 1 : -1); y += ri(r, -1, 1); }
        }
        floorLight(c, LW, hz, H, '#d8ffe0', 0.18);
      },
      setup(r, LW, H, hz) {
        return {
          crowd: crowdSides(r, LW, hz - 1, H, 12, { hazmat: 6, bot: 3, tv: 1, drone: 1, geiger: true }),
          fallout: moteSet(r, Math.round(LW / 10), LW, H * 0.1, H, 0.5, -3),
        };
      },
      anim(c, W, H, hz, t, st, X, still) {
        const pulse = still ? 0.5 : 0.5 + 0.5 * Math.sin(t * 1.8);
        alpha(c, 0.05 + 0.06 * pulse, () => ellipse(c, Math.round(W / 2), hz, Math.round(W * 0.3), Math.round(H * 0.14), '#7dff9a'));
        drawCrowd(c, st.crowd, t, X, DEPTH.mid, still);
        motes(c, st.fallout, t, W, H, '#7dff9a', still);
      },
    },
    {
      key: 'bunker', name: 'Qubic Data Bunker',
      sky(c, LW, H, hz, r) {
        gradient(c, 0, LW, 0, hz + 2, ['#0a0c0f', '#12151a', '#191d22', '#1e2328']);
        const ch = Math.round(H * 0.12);
        rect(c, 0, ch, LW, 2, '#2a3036'); rect(c, 0, ch + 4, LW, 1, '#262b30');
        for (let x = 0; x < LW; x += 14) { for (let k = 0; k < 12; k++) px(c, x + k, ch + 2 + Math.round(Math.sin(k / 11 * Math.PI) * 3), pickOf(r, ['#1c2a44', '#3a1c1c', '#1c1c1c'])); }
      },
      far(c, LW, H, hz, r) {
        // Concrete wall, the blast door with hazard trim, and the banner.
        const top = Math.round(H * 0.18);
        rect(c, 0, top, LW, hz - top, '#1f2429');
        for (let y = top; y < hz; y += 5) { rect(c, 0, y, LW, 1, '#181c20'); for (let x = ((y / 5) & 1) * 6; x < LW; x += 12) rect(c, x, y, 1, 5, '#181c20'); }
        speckle(c, 0, top, LW, hz - top, Math.round(LW / 2), ['#272d33', '#15191c'], r);
        const cx = Math.round(LW / 2), cy = Math.round(hz - H * 0.24), rr = Math.round(H * 0.2);
        hazard(c, cx - rr - 4, cy - rr - 4, 2 * rr + 9, 2 * rr + 9, '#8a6e20', '#15171a', 2);
        rect(c, cx - rr - 2, cy - rr - 2, 2 * rr + 5, 2 * rr + 5, '#1f2429');
        disc(c, cx, cy, rr, '#3a4046'); disc(c, cx, cy, rr - 2, '#2e3338'); disc(c, cx, cy, Math.max(1, rr - 5), '#353b41');
        for (let a = 0; a < 8; a++) px(c, cx + Math.round(Math.cos(a * 0.785) * (rr - 1)), cy + Math.round(Math.sin(a * 0.785) * (rr - 1)), '#5a626c');
        disc(c, cx, cy, 2, '#5a626c'); rect(c, cx - rr + 3, cy, 2 * rr - 5, 1, '#262b30');
        // QDOJO banner at the left.
        const bx = narrow(LW) ? M + 6 : Math.round(LW * 0.22) - 22, by = Math.round(H * 0.37);
        rect(c, bx, by, 44, 16, '#6a1418'); rect(c, bx, by, 44, 1, '#8a2a24'); rect(c, bx, by + 15, 44, 1, '#3a0c0e');
        for (let x = bx; x < bx + 44; x += 4) px(c, x + 2, by + 16, '#6a1418');
        text(c, 'QDOJO', bx + 3, by + 3, '#f2c230', 2);
      },
      mid(c, LW, H, hz, r) {
        const top = Math.round(H * 0.22);
        for (const f of [0.06, 0.16, 0.84, 0.94]) {
          const x = Math.round(LW * f) - 6;
          rect(c, x, top, 12, hz - top, '#15171c'); rect(c, x, top, 12, 1, '#3a3f4a'); rect(c, x, top, 1, hz - top, '#262a32');
          for (let y = top + 3; y < hz - 2; y += 4) rect(c, x + 2, y, 8, 2, '#20242c');
        }
        // A monitor on a stand.
        const mx = Math.round(LW * 0.72) - 20, my = Math.round(H * 0.38);
        rect(c, mx + 18, my + 22, 4, hz - my - 22, '#262a32'); rect(c, mx + 12, hz - 2, 16, 2, '#262a32');
        rect(c, mx, my, 40, 22, '#2a2e36'); rect(c, mx + 2, my + 2, 36, 18, '#07100e');
        for (let i = 0; i < 5; i++) { const x = ri(r, 0, LW); line(c, x, hz, x + ri(r, 4, 14), hz - 1, '#1c2a44'); }
      },
      floor(c, LW, H, hz, r) {
        gradient(c, 0, LW, hz, H, ['#2c3238', '#363d44', '#40474e']);
        seams(c, LW, hz, H, 5, '#1c2126', 1.6); converging(c, LW, hz, H, 26, '#1c2126', 1.3);
        for (let k = 0; k < 5; k++) { const y = hz + 2 + Math.round((H - hz - 3) * Math.pow(k / 5, 1.6)); for (let x = (k & 1) * 3; x < LW; x += 6) px(c, x, y + 1, '#4e565e'); }
        floorLight(c, LW, hz, H, '#a8f0ff', 0.2);
      },
      setup(r, LW, H, hz) {
        const top = Math.round(H * 0.22);
        return {
          crowd: crowdSides(r, LW, hz - 1, H, 14, { tv: 3, drone: 2, hazmat: 1 }, LW * 0.16, LW * 0.84),
          leds: [0.06, 0.16, 0.84, 0.94].flatMap(f => particles(r, 8, r => ({ x: Math.round(LW * f) - 4 + ri(r, 0, 7), y: top + 3 + 4 * ri(r, 0, Math.max(1, Math.floor((hz - top - 6) / 4))), col: pickOf(r, ['#39ff5a', '#36e0ff', '#f2c230', '#39ff5a']) }))),
          mon: { x: Math.round(LW * 0.72) - 20, y: Math.round(H * 0.38) },
          lamp: { x: Math.round(LW / 2), y: Math.round(hz - H * 0.24) - Math.round(H * 0.2) - 6 },
        };
      },
      anim(c, W, H, hz, t, st, X, still) {
        for (const l of st.leds) if (still || noise('led' + l.x + ':' + l.y, Math.floor(t * 3)) > 0.3) px(c, X(l.x, DEPTH.mid), l.y, l.col);
        // Beacon over the door.
        const lx = X(st.lamp.x, DEPTH.far), sw = still ? 0 : Math.sin(t * 3);
        rect(c, lx - 1, st.lamp.y, 3, 2, '#c2551b');
        if (!still) alpha(c, 0.1, () => { for (let k = 0; k < 18; k++) rect(c, lx + Math.round(sw * k * 1.6) - (k >> 2), st.lamp.y + 2 + k, 1 + (k >> 1), 1, '#f2a030'); });
        // The monitor: the sensei is rebooting.
        const mx = X(st.mon.x, DEPTH.mid), my = st.mon.y;
        text(c, 'SENSEI IS', mx + 3, my + 3, '#7dff9a'); text(c, 'REBOOTING', mx + 3, my + 9, '#7dff9a');
        const p = still ? 0.6 : mod(t * 0.15, 1);
        rect(c, mx + 3, my + 16, 34, 2, '#10301e'); rect(c, mx + 3, my + 16, Math.round(34 * p), 2, '#7dff9a');
        drawCrowd(c, st.crowd, t, X, DEPTH.mid, still);
      },
    },
  ];

  const list = STAGES.map(s => Object.freeze({ key: s.key, name: s.name }));
  const pick = seed => hash('stage:' + seed) % STAGES.length;

  // ---- build and paint -------------------------------------------------------------

  const defaultCanvas = (w, h) => { const cv = document.createElement('canvas'); cv.width = w; cv.height = h; return cv; };

  // Static layers for one stage at one size; cached per instance.
  function build(index, seed, W, H, makeCanvas) {
    const S = STAGES[index], LW = W + 2 * M, hz = Math.round(H * 0.68);
    const layers = {};
    for (const name of ['sky', 'far', 'mid', 'floor']) {
      const cv = makeCanvas(LW, H), c = cv.getContext('2d');
      if (name === 'floor') S.floor(c, LW, H, hz, rngFor(seed, name));
      else S[name](c, LW, H, hz, rngFor(seed, name));
      layers[name] = cv;
    }
    return { S, W, H, LW, hz, layers, st: S.setup(rngFor(seed, 'anim'), LW, H, hz) };
  }
  function drawFrame(ctx, B, t, still) {
    const cam = still ? 0 : Math.sin(t * 0.35) * (M - 2);
    const X = (x, depth) => Math.round(x - M + cam * depth);
    ctx.drawImage(B.layers.sky, X(0, DEPTH.sky), 0);
    ctx.drawImage(B.layers.far, X(0, DEPTH.far), 0);
    ctx.drawImage(B.layers.mid, X(0, DEPTH.mid), 0);
    ctx.drawImage(B.layers.floor, X(0, DEPTH.floor), 0);
    B.S.anim(ctx, B.W, B.H, B.hz, t, B.st, X, still);
    // A soft vignette at the floor's front edge grounds the fighters.
    alpha(ctx, 0.35, () => rect(ctx, 0, B.H - 2, B.W, 2, '#000000'));
  }
  // Paint one frame without the DOM (tests, tools): same pixels as mount().
  function paint(ctx, W, H, index, seed, t, makeCanvas) {
    const B = build(index, String(seed), W, H, makeCanvas || defaultCanvas);
    drawFrame(ctx, B, t || 0, !t);
    return B;
  }

  // ---- mounting and the shared loop ----------------------------------------------------

  const mounted = new Set();
  let raf = 0, watching = false;
  const reducedMq = typeof matchMedia === 'function' ? matchMedia('(prefers-reduced-motion: reduce)') : null;
  const isStill = () => (reducedMq && reducedMq.matches) || (typeof document !== 'undefined' && document.body && document.body.classList.contains('still'));

  function layout(m) {
    const cw = m.canvas.clientWidth, ch = m.canvas.clientHeight;
    if (!cw || !ch) return false;
    const scale = m.scale || (ch >= 280 ? 3 : 2);
    const W = Math.max(40, Math.ceil(cw / scale)), H = Math.max(30, Math.ceil(ch / scale));
    if (m.B && m.B.W === W && m.B.H === H) return true;
    m.canvas.width = W; m.canvas.height = H;
    m.ctx = m.canvas.getContext('2d');
    m.ctx.imageSmoothingEnabled = false;
    m.B = build(m.index, m.seed, W, H, defaultCanvas);
    m.drawnStill = false;
    return true;
  }
  function draw(m, now) {
    if (!m.B && !layout(m)) return;
    const still = isStill();
    drawFrame(m.ctx, m.B, still ? 0 : (now - m.t0) / 1000, still);
    m.last = now;
    m.drawnStill = still;
  }
  function prune() {
    for (const m of mounted) if (!m.canvas.isConnected) destroy(m);
  }
  function destroy(m) {
    mounted.delete(m);
    if (m.io) m.io.disconnect();
    if (m.ro) m.ro.disconnect();
  }
  function loop(now) {
    raf = 0;
    if (typeof document !== 'undefined' && document.hidden) return;
    const still = isStill();
    let animating = false;
    for (const m of Array.from(mounted)) {
      if (!m.canvas.isConnected) { destroy(m); continue; }
      if (still) { if (!m.drawnStill) draw(m, now); continue; }
      if (!m.visible) continue;
      animating = true;
      if (now - m.last >= 1000 / m.fps - 4) draw(m, now);
    }
    if (animating) raf = requestAnimationFrame(loop);
  }
  function kick() { if (!raf && mounted.size) raf = requestAnimationFrame(loop); }
  function watch() {
    if (watching || typeof document === 'undefined') return;
    watching = true;
    document.addEventListener('visibilitychange', kick);
    if (typeof MutationObserver === 'function' && document.body) new MutationObserver(kick).observe(document.body, { attributes: true, attributeFilter: ['class'] });
    if (reducedMq && reducedMq.addEventListener) reducedMq.addEventListener('change', kick);
  }

  /* Draw a stage into `canvas` (sized by CSS) and keep it animated while it is
   * visible. opts: { seed (fight ID), fps (default 12), scale (logical px per
   * CSS px; default 3 on tall canvases, else 2) }. */
  function mount(canvas, opts = {}) {
    prune();
    watch();
    const seed = String(opts.seed == null ? '0' : opts.seed);
    const m = { canvas, seed, index: pick(seed), fps: opts.fps || 12, scale: opts.scale || 0, t0: typeof performance !== 'undefined' ? performance.now() - (hash(seed) % 10000) : 0, last: -1e9, visible: true, B: null, ctx: null, drawnStill: false };
    canvas.dataset.stage = STAGES[m.index].key;
    canvas.setAttribute('aria-hidden', 'true');
    mounted.add(m);
    if (typeof IntersectionObserver === 'function') {
      m.io = new IntersectionObserver(es => { m.visible = es[es.length - 1].isIntersecting; kick(); });
      m.io.observe(canvas);
    }
    if (typeof ResizeObserver === 'function') {
      m.ro = new ResizeObserver(() => { if (layout(m)) { draw(m, typeof performance !== 'undefined' ? performance.now() : 0); } kick(); });
      m.ro.observe(canvas);
    }
    if (layout(m)) draw(m, typeof performance !== 'undefined' ? performance.now() : 0);
    kick();
    return { stage: list[m.index], destroy: () => destroy(m) };
  }

  return Object.freeze({ mount, pick, paint, list, count: () => mounted.size, hash });
})();
if (typeof module !== 'undefined') module.exports = QDojoStages;
