/* Fight stages: procedural pixel-art arenas behind the replay player.
 *
 * Decoration only. A stage is chosen from the fight ID and drawn from a
 * seeded generator, so a fight always gets the same arena; nothing here reads
 * or changes a fight's numbers. No images: every pixel is a fillRect on a
 * small canvas that CSS scales up with image-rendering: pixelated.
 *
 * Each stage is four static layers (sky, far, mid, floor), rendered once per
 * size into offscreen canvases, plus an animated pass (petals, rain, neon,
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
  function ridge(c, W, base, amp, bottom, col, r, rough = 1) {
    const ph = [r() * 6.28, r() * 6.28, r() * 6.28], fr = [0.021 + r() * 0.01, 0.055 + r() * 0.02, 0.13 + r() * 0.05];
    for (let x = 0; x < W; x++) {
      const h = amp * (0.55 * Math.sin(x * fr[0] + ph[0]) + 0.3 * Math.sin(x * fr[1] + ph[1]) + 0.15 * rough * Math.sin(x * fr[2] + ph[2]) + 0.5);
      const y = Math.round(base - h);
      rect(c, x, y, 1, bottom - y, col);
    }
  }
  // 3x5 pixel font for signs.
  const FONT = {
    A: '010101111101101', B: '110101110101110', C: '011100100100011', D: '110101101101110', E: '111100110100111',
    F: '111100110100100', G: '011100101101011', H: '101101111101101', I: '111010010010111', J: '001001001101010',
    K: '101101110101101', L: '100100100100111', M: '101111111101101', N: '110101101101101', O: '010101101101010',
    P: '110101110100100', Q: '010101101110011', R: '110101110101101', S: '011100010001110', T: '111010010010010',
    U: '101101101101111', V: '101101101101010', W: '101101111111101', X: '101101010101101', Y: '101101010010010',
    Z: '111001010100111', 0: '111101101101111', 1: '010110010010111', 2: '110001010100111', 4: '101101111001001',
    7: '111001010010010', ' ': '000000000000000',
  };
  function text(c, str, x, y, col) {
    c.fillStyle = col;
    for (const ch of String(str)) {
      const g = FONT[ch] || FONT[' '];
      for (let i = 0; i < 15; i++) if (g[i] === '1') c.fillRect(x + (i % 3), y + Math.floor(i / 3), 1, 1);
      x += 4;
    }
  }
  const textW = s => String(s).length * 4 - 1;
  // Perspective floor lines: converging to (vx, vy); `every` px apart at the front edge.
  function converging(c, LW, hz, H, every, col, vyK = 1.4) {
    const vx = LW / 2, vy = hz - (H - hz) * vyK;
    c.fillStyle = col;
    for (let xb = vx % every - every * 6; xb < LW + every * 6; xb += every) {
      for (let y = hz; y < H; y++) {
        const x = vx + (xb - vx) * (y - vy) / (H - vy);
        if (x >= 0 && x < LW) c.fillRect(Math.round(x), y, 1, 1);
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
    for (let i = 0; i < s; i++) {
      rect(c, x - i, y + Math.floor(i / 2), 2 * i + 1, 1, top); // widening top
    }
    const mid = y + Math.floor(s / 2);
    for (let i = 0; i < s; i++) {
      rect(c, x - s + 1 + i, mid + Math.floor(i / 2), 1, s - 0, left);
      rect(c, x + s - 1 - i, mid + Math.floor(i / 2), 1, s - 0, right);
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

  // ---- people, flags, lanterns, roofs --------------------------------------------

  // One spectator, feet at `foot`. up: 0 arms down, 1 one fist up, 2 both up.
  function person(c, x, foot, p, up, jump) {
    const h = p.h, w = p.w, hs = p.hs, legH = Math.round(h * 0.36), tor = h - hs - legH;
    const y = foot - h - jump, hx = x + ((w - hs) >> 1);
    const lw = Math.max(1, (w - 1) >> 1);
    rect(c, x, y + hs + tor, lw, legH, p.pants); rect(c, x + w - lw, y + hs + tor, lw, legH, p.pants);
    rect(c, x, y + hs, w, tor, p.shirt); rect(c, x + w - 1, y + hs, 1, tor, p.shirtD); rect(c, x, y + hs, w, 1, p.shirtL);
    rect(c, hx, y, hs, hs, p.skin);
    rect(c, hx, y, hs, 1, p.hair); rect(c, hx + hs - 1, y, 1, hs - 1, p.hair);
    if (p.hat) { rect(c, hx - 1, y - 1, hs + 2, 1, p.hat); rect(c, hx, y - 2, hs, 1, p.hat); }
    if (up === 2) { rect(c, x - 1, y - 3, 1, hs + 4, p.skin); rect(c, x + w, y - 3, 1, hs + 4, p.skin); }
    else if (up === 1) { rect(c, x + w, y - 3, 1, hs + 4, p.skin); rect(c, x - 1, y + hs + 1, 1, tor - 1, p.shirtD); }
    else { rect(c, x - 1, y + hs + 1, 1, tor - 1, p.shirtD); rect(c, x + w, y + hs + 1, 1, tor - 1, p.shirtD); }
  }
  const SKINS = ['#f0c8a0', '#d9a066', '#b87a4a', '#8a5a3a', '#f6d8b8'];
  const HAIRS = ['#1b1010', '#3a2010', '#6b3a1a', '#1b1010', '#a0a0a0'];
  function makeCrowd(r, x0, x1, foot, n, pal, hr) {
    const out = [];
    for (let i = 0; i < n; i++) {
      const h = ri(r, hr[0], hr[1]), shirt = pickOf(r, pal.shirts);
      const skin = pickOf(r, pal.skins || SKINS);
      out.push({
        x: Math.round(x0 + (x1 - x0) * (i + 0.2 + r() * 0.6) / n), foot: foot + ri(r, 0, 1), h,
        w: Math.max(3, Math.round(h * 0.32)), hs: Math.max(2, Math.round(h * 0.2)),
        shirt, shirtD: shade(shirt, 0.7), shirtL: shade(shirt, 1.25), pants: pickOf(r, pal.pants), skin,
        hair: pal.bald && r() < 0.8 ? shade(skin, 0.85) : pickOf(r, pal.hairs || HAIRS),
        hat: pal.hats && r() < (pal.hatP || 0.3) ? pickOf(r, pal.hats) : null,
        cheer: r() < 0.65, sp: 5 + r() * 4, ph: r() * 6.28,
      });
    }
    return out;
  }
  function drawCrowd(c, people, t, X, depth, still) {
    for (const p of people) {
      let up = 0, jump = 0;
      if (still) up = p.cheer && p.ph > 3.5 ? 2 : p.cheer && p.ph > 2 ? 1 : 0;
      else if (p.cheer) { const k = Math.sin(t * p.sp + p.ph); up = k > 0.1 ? 2 : k > -0.5 ? 1 : 0; jump = k > 0.7 ? 1 : 0; }
      else jump = Math.sin(t * p.sp * 0.4 + p.ph) > 0.85 ? 1 : 0;
      person(c, X(p.x, depth), p.foot, p, up, jump);
    }
  }
  // A cloth flag on a pole, rippling; stripes are horizontal bands of colour.
  function flag(c, x, y, w, h, stripes, t, still, dir = 1) {
    for (let i = 0; i < w; i++) {
      const dy = still ? 0 : Math.round(Math.sin(t * 6 - i * 0.7) * 1.2 * (i / w));
      const lit = !still && Math.sin(t * 6 - i * 0.7 + 1.2) > 0.5;
      for (let k = 0; k < h; k++) {
        const col = stripes[Math.floor(k * stripes.length / h)];
        px(c, x + dir * (i + 1), y + k + dy, lit ? shade(col, 1.15) : col);
      }
    }
  }
  function lantern(c, x, y, col, glow) {
    if (glow > 0) alpha(c, glow, () => disc(c, x, y + 3, 7, '#ffb347'));
    rect(c, x - 1, y - 1, 3, 1, '#1b1010');
    rect(c, x - 3, y, 7, 7, col); rect(c, x - 2, y - 0, 5, 7, shade(col, 1.2));
    rect(c, x - 3, y + 2, 7, 1, shade(col, 0.65)); rect(c, x - 3, y + 4, 7, 1, shade(col, 0.65));
    rect(c, x - 1, y + 1, 2, 5, '#ffd27a');
    rect(c, x - 1, y + 7, 3, 1, '#1b1010'); px(c, x, y + 8, '#e0b040');
  }
  // A rope of lanterns between x0 and x1 with sag; they sway in the animated pass.
  function lanternRope(c, x0, x1, y, sag, n, cols, t, still, X, depth) {
    const at = u => y + Math.round(sag * (1 - Math.pow(2 * u - 1, 2)));
    for (let x = x0; x <= x1; x++) px(c, X(x, depth), at((x - x0) / (x1 - x0)), '#2a1a10');
    for (let i = 1; i < n; i++) {
      const u = i / n, lx = X(x0 + (x1 - x0) * u, depth), sw = still ? 0 : Math.round(Math.sin(t * 2 + i) * 0.8);
      lantern(c, lx + sw, at(u) + 1, cols[i % cols.length], still ? 0.2 : 0.18 + 0.06 * Math.sin(t * 8 + i * 2));
    }
  }
  // A curved East Asian roof: tiles, a dark ridge, upturned eaves.
  function roof(c, cx, y, w, h, tile, ridgeCol, trim) {
    for (let k = 0; k < h; k++) {
      const half = Math.round(w / 2 * (0.62 + 0.38 * k / Math.max(1, h - 1)));
      rect(c, cx - half, y + k, 2 * half, 1, tile);
      c.fillStyle = shade(tile, 0.72);
      for (let x = cx - half + (k & 1); x < cx + half; x += 3) c.fillRect(x, y + k, 1, 1);
    }
    const half = Math.round(w / 2);
    rect(c, cx - half, y + h, 2 * half, 1, trim || shade(tile, 0.5));
    for (const s of [-1, 1]) {
      px(c, cx + s * half - (s > 0 ? 1 : 0) + s, y + h - 1, tile); px(c, cx + s * half - (s > 0 ? 1 : 0) + 2 * s, y + h - 2, tile);
      px(c, cx + s * half - (s > 0 ? 1 : 0) + 2 * s, y + h - 3, ridgeCol);
    }
    const rh = Math.round(w / 2 * 0.62);
    rect(c, cx - rh, y - 1, 2 * rh, 2, ridgeCol);
  }
  function bricks(c, x0, y0, w, h, col, mortar, bw = 6) {
    rect(c, x0, y0, w, h, col);
    for (let y = y0; y < y0 + h; y += 3) {
      rect(c, x0, y, w, 1, mortar);
      for (let x = x0 + ((y / 3) & 1 ? bw >> 1 : 0); x < x0 + w; x += bw) rect(c, x, y, 1, 3, mortar);
    }
  }
  function palm(c, x, base, h, trunk, leaf, lean) {
    for (let k = 0; k < h; k++) {
      const xx = x + Math.round(lean * (k / h) * (k / h) * 6);
      rect(c, xx, base - k, 2, 1, k % 3 ? trunk : shade(trunk, 0.7));
    }
    const tx = x + Math.round(lean * 6), ty = base - h;
    for (const [dx, dy] of [[-1, 0.2], [1, 0.2], [-1, -0.5], [1, -0.5], [-0.4, 0.9], [0.4, 0.9]]) {
      for (let k = 0; k < 9; k++) {
        const fx = tx + Math.round(dx * k), fy = ty + Math.round(dy * k * 0.6 + (k * k) / 14);
        rect(c, fx, fy, 2, 1, k % 2 ? leaf : shade(leaf, 0.75));
      }
    }
  }
  function wheel(c, x, y, rad, col) {
    for (let a = 0; a < 24; a++) px(c, x + Math.round(Math.cos(a * 0.2618) * rad), y + Math.round(Math.sin(a * 0.2618) * rad), col);
    px(c, x, y, col);
  }
  function bicycle(c, x, y, col) {
    wheel(c, x, y, 3, '#1b1b1b'); wheel(c, x + 10, y, 3, '#1b1b1b');
    for (let k = 0; k <= 5; k++) { px(c, x + k, y - k * 0.8, col); px(c, x + 5 + k, y - 4, col); px(c, x + 5 + k * 0.1, y - 4 + k * 0.8, col); }
    rect(c, x + 3, y - 6, 3, 1, '#2a2a2a'); rect(c, x + 10, y - 6, 1, 6, col); rect(c, x + 9, y - 7, 3, 1, '#2a2a2a');
  }
  function textured(c, LW, hz, H, base, cols, r, density = 6) {
    gradient(c, 0, LW, hz, H, base);
    for (let i = 0; i < LW * (H - hz) / density; i++) px(c, ri(r, 0, LW), ri(r, hz, H), pickOf(r, cols));
  }
  function flagstones(c, LW, hz, H, rows, col, r) {
    for (let k = 0; k < rows; k++) {
      const y0 = hz + Math.round((H - hz) * Math.pow(k / rows, 1.6)), y1 = hz + Math.round((H - hz) * Math.pow((k + 1) / rows, 1.6));
      rect(c, 0, y0, LW, 1, col);
      const vx = LW / 2, sw = 10 + k * 7;
      for (let x = mod(vx + (k & 1) * sw / 2, sw) - sw; x < LW; x += sw) {
        const xb = vx + (x - vx) * (1 + 0.15 * k);
        rect(c, Math.round(xb), y0, 1, y1 - y0, col);
      }
      if (r) for (let i = 0; i < LW / 25; i++) px(c, ri(r, 0, LW), ri(r, y0 + 1, Math.max(y0 + 1, y1 - 1)), shade(col, 1.25));
    }
  }
  function birds(c, list, t, W, still, col) {
    if (still) return;
    for (const b of list) {
      const bx = mod(b.x + t * b.v, W + 20) - 10, by = b.y + Math.sin(t + b.ph) * 2, up = Math.sin(t * 8 + b.ph) > 0;
      px(c, bx, by, col); px(c, bx - 1, by - (up ? 1 : 0), col); px(c, bx + 1, by - (up ? 1 : 0), col);
      px(c, bx - 2, by - (up ? 2 : 0), col); px(c, bx + 2, by - (up ? 2 : 0), col);
    }
  }
  function smoke(c, x, y, t, puffs, col, still, rise = 40, a0 = 0.45) {
    for (const p of puffs) {
      const k = still ? p.ph : mod(t * p.v + p.ph, 1);
      alpha(c, a0 * (1 - k), () => disc(c, Math.round(x + p.dx * k * 6 + Math.sin(t * 1.5 + p.ph * 6) * 2 * k), Math.round(y - k * rise), 1 + Math.round(k * 3), col));
    }
  }
  const puffSet = (r, n) => particles(r, n, r => ({ ph: r(), dx: (r() - 0.5) * 2, v: 0.25 + r() * 0.2 }));
  const birdSet = (r, n, LW, y0, y1) => particles(r, n, r => ({ x: r() * LW, y: Math.round(y0 + r() * (y1 - y0)), v: 5 + r() * 6, ph: r() * 6 }));

  // ---- the stages ----------------------------------------------------------------
  //
  // Every function gets (c, LW, H, hz, r): layer width (view + margins), height,
  // the floor line, and a seeded generator. setup() returns what the animated
  // pass needs; anim(c, W, H, hz, t, st, X, still) draws it, X(x, depth)
  // mapping layer x to screen x for the current camera. Original scenes in the
  // spirit of early-90s arcade fighters: warm, busy, with a watching crowd.

  const DEPTH = { sky: 1, far: 0.75, mid: 0.4, floor: 0 };
  const crowdH = H => [Math.max(9, Math.round(H * 0.15)), Math.max(11, Math.round(H * 0.19))];

  const STAGES = [
    {
      key: 'castle', name: 'Castle Rooftop',
      sky(c, LW, H, hz, r) {
        gradient(c, 0, LW, 0, hz + 2, ['#0b0c2a', '#1b1f4f', '#2e3470', '#4a4a86', '#7a6488']);
        stars(c, LW, Math.round(H * 0.5), Math.round(LW / 5), r, ['#e8e4ff', '#8a8ac0']);
        const cx = Math.round(LW * 0.34), cy = Math.round(H * 0.38), rad = Math.round(H * 0.22);
        alpha(c, 0.15, () => disc(c, cx, cy, rad + 8, '#fff4d6'));
        alpha(c, 0.25, () => disc(c, cx, cy, rad + 3, '#fff4d6'));
        disc(c, cx, cy, rad, '#fff1cc'); disc(c, cx + 3, cy + 3, rad - 3, '#f4e2b0'); disc(c, cx - 2, cy - 2, rad - 6, '#fff6dc');
        for (let i = 0; i < 7; i++) disc(c, cx + ri(r, -rad + 5, rad - 5), cy + ri(r, -rad + 5, rad - 5), ri(r, 1, 3), '#e6d2a0');
      },
      far(c, LW, H, hz, r) {
        ridge(c, LW, hz - 6, H * 0.12, hz + 1, '#23285a', r);
        ridge(c, LW, hz - 1, H * 0.06, hz + 1, '#1a1d44', r, 2);
        for (let x = 0; x < LW; x += 2) if (r() < 0.25) px(c, x, hz - ri(r, 1, 4), pickOf(r, ['#ffcf6b', '#ff9a4a']));
      },
      mid(c, LW, H, hz, r) {
        // The keep: stone base, white walls, three tiled roofs with gold ridge fish.
        const kx = Math.round(LW * 0.78), bw = Math.round(Math.max(40, LW * 0.26));
        const base = hz - 3, sb = Math.round(H * 0.14);
        for (let k = 0; k < sb; k++) rect(c, kx - bw / 2 - (sb - k) * 0.3, base - sb + k, bw + (sb - k) * 0.6, 1, k % 3 ? '#5a5a6e' : '#474758');
        for (let i = 0; i < 20; i++) rect(c, kx - bw / 2 + ri(r, 0, bw), base - sb + ri(r, 0, sb - 1), 3, 1, '#6e6e84');
        let y = base - sb, w = bw - 6;
        for (let tier = 0; tier < 3; tier++) {
          const wh = Math.round(H * 0.08) - tier;
          rect(c, kx - w / 2, y - wh, w, wh, '#e8e4d8'); rect(c, kx + w / 2 - 3, y - wh, 3, wh, '#b8b4c8');
          for (let wx = kx - w / 2 + 3; wx < kx + w / 2 - 4; wx += 6) rect(c, wx, y - wh + 2, 2, 3, '#2a2438');
          roof(c, kx, y - wh - 5, w + 12, 5, '#3a4264', '#1e2240', '#23284a');
          px(c, kx - (w + 12) / 2 * 0.62 + 1, y - wh - 7, '#e0b040'); px(c, kx + (w + 12) / 2 * 0.62 - 2, y - wh - 7, '#e0b040');
          y = y - wh - 6; w = Math.round(w * 0.72);
        }
        // A twisted pine on the left.
        const px0 = Math.round(LW * 0.08);
        for (let k = 0; k < Math.round(H * 0.3); k++) px(c, px0 + Math.round(Math.sin(k * 0.2) * 2), hz - k, '#2a1a14');
        for (let i = 0; i < 4; i++) ellipse(c, px0 + ri(r, -6, 8), hz - Math.round(H * 0.22) - i * 5, ri(r, 5, 9), 2, i % 2 ? '#1f3a2e' : '#2a4a3a');
        // Parapet wall with tiles along the floor line.
        rect(c, 0, hz - 5, LW, 5, '#d8d4c8'); rect(c, 0, hz - 6, LW, 2, '#3a4264'); rect(c, 0, hz - 1, LW, 1, '#8a8698');
        for (let x = 3; x < LW; x += 16) rect(c, x, hz - 4, 3, 2, '#2a2438');
      },
      floor(c, LW, H, hz) {
        gradient(c, 0, LW, hz, H, ['#3a4060', '#4a5074', '#565c82']);
        for (let k = 0; k < 8; k++) {
          const y = hz + Math.round((H - hz) * Math.pow(k / 8, 1.5)), sp = 4 + k;
          rect(c, 0, y, LW, 1, '#2a2e48');
          for (let x = (k & 1) * (sp >> 1); x < LW; x += sp) { px(c, x, y + 1, '#7a80a8'); px(c, x + 1, y + 1, '#6a7094'); }
        }
        converging(c, LW, hz, H, 12, '#343a5a', 1.2);
      },
      setup(r, LW, H, hz) {
        return {
          clouds: particles(r, 3, r => ({ x: r() * LW, y: Math.round(H * (0.28 + r() * 0.2)), w: 20 + ri(r, 0, 20), v: 1.2 + r() })),
          banners: [Math.round(LW * 0.03), Math.round(LW * 0.97)], bats: birdSet(r, 2, LW, H * 0.2, H * 0.4),
          lanterns: { x0: Math.round(LW * 0.14), x1: Math.round(LW * 0.6), y: Math.round(H * 0.12) },
        };
      },
      anim(c, W, H, hz, t, st, X, still) {
        for (const cl of st.clouds) {
          const x = X(still ? cl.x : mod(cl.x + t * cl.v, W + 60) - 30, DEPTH.sky);
          alpha(c, 0.85, () => { rect(c, x, cl.y, cl.w, 2, '#2a2c5c'); rect(c, x + 4, cl.y - 1, cl.w - 8, 1, '#5a5a90'); rect(c, x + 8, cl.y + 2, cl.w - 12, 1, '#23244e'); });
        }
        lanternRope(c, st.lanterns.x0, st.lanterns.x1, st.lanterns.y, 8, 5, ['#d0342c', '#e0602a'], t, still, X, DEPTH.mid);
        st.banners.forEach((bx, i) => {
          const x = X(bx, DEPTH.mid);
          rect(c, x, hz - Math.round(H * 0.42), 1, Math.round(H * 0.42), '#2a1a10');
          flag(c, x, hz - Math.round(H * 0.4), 6, Math.round(H * 0.22), ['#f0ece0', '#c02a2a', '#f0ece0'], t + i, still, i ? -1 : 1);
        });
        birds(c, st.bats, t, W, still, '#0a0a1a');
      },
    },
    {
      key: 'market', name: 'Market Street',
      sky(c, LW, H, hz) { gradient(c, 0, LW, 0, hz + 2, ['#e89a50', '#f4c078', '#fde0a8']); },
      far(c, LW, H, hz, r) {
        // Two-storey shophouses with balconies, shutters and hanging sign boards.
        const top = Math.round(H * 0.1), sh = Math.round(H * 0.24);
        for (let x = -4; x < LW;) {
          const w = ri(r, 34, 46), col = pickOf(r, ['#e8d0a0', '#d8b888', '#c86a4a', '#6aa89a', '#e0c070']);
          rect(c, x, top + 6, w, hz - top - 6, col); rect(c, x + w - 2, top + 6, 2, hz - top - 6, shade(col, 0.75));
          roof(c, x + w / 2, top, w + 4, 5, pickOf(r, ['#3a6a4a', '#5a4a3a', '#3a4a6a']), '#2a2a2a');
          for (let wx = x + 4; wx < x + w - 8; wx += 10) {
            rect(c, wx, top + 12, 7, 9, '#3a2418'); rect(c, wx + 1, top + 13, 5, 7, '#ffd890');
            rect(c, wx - 2, top + 12, 2, 9, '#2a6a4a'); rect(c, wx + 7, top + 12, 2, 9, '#2a6a4a');
          }
          rect(c, x + 2, top + 23, w - 4, 1, '#3a2418');
          for (let bx = x + 2; bx < x + w - 2; bx += 2) px(c, bx, top + 24, '#3a2418');
          rect(c, x + 2, top + 25, w - 4, 1, '#3a2418');
          const sx = x + ri(r, 4, w - 10);
          rect(c, sx, top + 27, 6, sh - 8, pickOf(r, ['#b8202a', '#1b1b1b'])); rect(c, sx, top + 27, 6, 1, '#e0b040');
          for (let k = 0; k < 4; k++) rect(c, sx + 2, top + 30 + k * 4, 2, 2, '#e0b040');
          x += w;
        }
      },
      mid(c, LW, H, hz, r) {
        // Stalls: striped awnings, produce, hanging ducks, parked bicycles.
        const ay = hz - Math.round(H * 0.2);
        for (let x = 0; x < LW; x += 30) {
          const [a, b] = pickOf(r, [['#c02a2a', '#f0ece0'], ['#2a7a4a', '#f0ece0'], ['#e0a020', '#c02a2a']]);
          for (let k = 0; k < 28; k++) rect(c, x + k, ay, 1, 5 + ((k >> 2) & 1), (k >> 2) & 1 ? a : b);
          rect(c, x, ay + 5, 28, 1, shade(a, 0.6));
          rect(c, x + 2, hz - 8, 24, 2, '#6a4a2a'); rect(c, x + 3, hz - 6, 1, 6, '#4a3018'); rect(c, x + 24, hz - 6, 1, 6, '#4a3018');
          for (let k = 0; k < 5; k++) {
            const col = pickOf(r, ['#ff8c20', '#e03a2a', '#6ab83a', '#f0d040', '#a04ab0']);
            ellipse(c, x + 5 + k * 4, hz - 9, 2, 1, col); px(c, x + 5 + k * 4, hz - 11, shade(col, 1.3));
          }
          if (r() < 0.6) for (let k = 0; k < 3; k++) { rect(c, x + 8 + k * 5, ay + 6, 1, 2, '#2a1a10'); rect(c, x + 7 + k * 5, ay + 8, 3, 4, '#a0502a'); px(c, x + 8 + k * 5, ay + 9, '#d08040'); }
        }
        for (let i = 0; i < 3; i++) bicycle(c, ri(r, 4, LW - 16), hz - 3, pickOf(r, ['#c02a2a', '#2a5aa8', '#2a2a2a']));
      },
      floor(c, LW, H, hz, r) {
        textured(c, LW, hz, H, ['#a08868', '#b8a080', '#c4ae8e'], ['#9a8262', '#cdb898', '#8a7456'], r, 8);
        flagstones(c, LW, hz, H, 5, '#8a7456', r);
        rect(c, 0, hz, LW, 2, '#6a5a44');
      },
      setup(r, LW, H, hz) {
        const pal = { shirts: ['#f0ece0', '#3a5aa8', '#c02a2a', '#8a8a8a', '#2a6a4a', '#e0a020'], pants: ['#2a2a3a', '#3a3a5a', '#4a3a2a'], hats: ['#d8b870'], hatP: 0.25 };
        return {
          crowd: makeCrowd(r, 0, LW, hz - 1, Math.max(6, Math.round(LW / 9)), pal, crowdH(H)),
          rope: { y: Math.round(H * 0.1) },
          birds: birdSet(r, 2, LW, H * 0.05, H * 0.2),
        };
      },
      anim(c, W, H, hz, t, st, X, still) {
        lanternRope(c, 0, W + 16, st.rope.y, 7, 8, ['#d0342c', '#e0602a', '#d0342c'], t, still, X, DEPTH.far);
        drawCrowd(c, st.crowd, t, X, DEPTH.mid, still);
        birds(c, st.birds, t, W, still, '#4a3a3a');
      },
    },
    {
      key: 'temple', name: 'Mountain Temple',
      sky(c, LW, H, hz, r) {
        gradient(c, 0, LW, 0, hz + 2, ['#6a9ed0', '#9ac4e6', '#d4e6ee', '#f4e8c8']);
        for (let i = 0; i < 3; i++) { const x = ri(r, 0, LW), y = ri(r, Math.round(H * 0.1), Math.round(H * 0.3)); ellipse(c, x, y, 12, 2, '#f4f8fc'); ellipse(c, x + 5, y - 2, 6, 2, '#ffffff'); }
      },
      far(c, LW, H, hz, r) {
        for (const [fx, fh, col] of [[0.1, 0.7, '#6a8aa0'], [0.5, 0.82, '#5a7a92'], [0.9, 0.66, '#6a8aa0']]) {
          const x = LW * fx, top = hz - H * fh;
          for (let y = Math.round(top); y < hz; y++) { const half = (y - top) * 0.9; rect(c, x - half, y, 2 * half, 1, col); rect(c, x, y, half, 1, shade(col, 0.85)); }
        }
        alpha(c, 0.5, () => rect(c, 0, Math.round(hz - H * 0.3), LW, 3, '#e8f0f4'));
        ridge(c, LW, hz - 4, H * 0.12, hz + 1, '#3a6a5a', r);
        for (let i = 0; i < 10; i++) { const x = ri(r, 0, LW), h = ri(r, 5, 9); for (let k = 0; k < h; k++) rect(c, x - (k >> 1), hz - 6 - h + k, (k >> 1) * 2 + 1, 1, '#2a5040'); }
      },
      mid(c, LW, H, hz) {
        // The great hall: red columns, lattice doors, sweeping ochre roof, stone steps.
        const cx = Math.round(LW / 2), w = Math.round(LW * 0.62), top = Math.round(hz - H * 0.4);
        roof(c, cx, top - 10, Math.round(w * 0.7), 5, '#d89a30', '#6a3a1a', '#8a4a1a');
        rect(c, cx - w * 0.3, top - 5, w * 0.6, 5, '#b8302a');
        roof(c, cx, top, w + 16, 7, '#d89a30', '#6a3a1a', '#8a4a1a');
        rect(c, cx - w / 2, top + 8, w, hz - top - 14, '#b8302a');
        rect(c, cx - w / 2, top + 8, w, 2, '#6a1a14');
        for (let x = cx - w / 2 + 2; x < cx + w / 2 - 2; x += 12) {
          rect(c, x, top + 10, 3, hz - top - 16, '#8a1a14'); rect(c, x, top + 10, 1, hz - top - 16, '#d84a3a');
          for (let y = top + 13; y < hz - 9; y += 3) rect(c, x + 4, y, 7, 1, '#e0a040');
          for (let xx = x + 5; xx < x + 11; xx += 3) rect(c, xx, top + 12, 1, hz - top - 21, '#e0a040');
        }
        rect(c, cx - 6, top + 1, 12, 5, '#1b3a5a'); rect(c, cx - 5, top + 2, 10, 3, '#e0b040');
        for (let k = 0; k < 3; k++) rect(c, cx - w / 2 - 4 + k * 2, hz - 6 + k * 2, w + 8 - k * 4, 2, k % 2 ? '#9a9a9a' : '#b4b4b0');
        // Incense burner.
        rect(c, cx - 4, hz - 10, 9, 5, '#8a6a3a'); rect(c, cx - 5, hz - 11, 11, 1, '#b08a4a'); rect(c, cx - 3, hz - 5, 1, 3, '#5a4020'); rect(c, cx + 3, hz - 5, 1, 3, '#5a4020');
      },
      floor(c, LW, H, hz, r) {
        textured(c, LW, hz, H, ['#8a8a86', '#9a9a94', '#a8a8a0'], ['#7a8a6a', '#b4b4ac', '#80807a'], r, 7);
        flagstones(c, LW, hz, H, 6, '#6e6e6a', r);
      },
      setup(r, LW, H, hz) {
        const pal = { shirts: ['#e07820', '#f0a030', '#e07820', '#8a8a8a'], pants: ['#c05a10', '#6a6a6a'], bald: true };
        const n = Math.max(3, Math.round(LW / 22));
        return {
          monks: makeCrowd(r, 0, LW * 0.2, hz - 1, n, pal, crowdH(H)).concat(makeCrowd(r, LW * 0.8, LW, hz - 1, n, pal, crowdH(H))),
          smoke: puffSet(r, 6), sx: Math.round(LW / 2), birds: birdSet(r, 3, LW, H * 0.1, H * 0.3),
        };
      },
      anim(c, W, H, hz, t, st, X, still) {
        smoke(c, X(st.sx, DEPTH.mid), hz - 12, t, st.smoke, '#e8e8f0', still, 30, 0.5);
        drawCrowd(c, st.monks, t, X, DEPTH.mid, still);
        birds(c, st.birds, t, W, still, '#2a3048');
      },
    },
    {
      key: 'harbor', name: 'Harbor Dock',
      sky(c, LW, H, hz) {
        const wy = Math.round(hz - H * 0.18);
        gradient(c, 0, LW, 0, wy + 1, ['#3a2a5a', '#8a3a5a', '#e0604a', '#f8a050', '#ffd080']);
        const sx = Math.round(LW * 0.62);
        disc(c, sx, wy - 3, Math.round(H * 0.1), '#fff0b0'); rect(c, 0, wy - 1, LW, 1, '#f8a050');
        gradient(c, 0, LW, wy, hz + 2, ['#e07a4a', '#a04a4a', '#5a3050', '#3a2a4a']);
      },
      far(c, LW, H, hz, r) {
        const wy = Math.round(hz - H * 0.18);
        ridge(c, LW, wy, H * 0.05, wy + 1, '#5a2a4a', r);
        for (let i = 0; i < LW / 4; i++) rect(c, ri(r, 0, LW), ri(r, wy + 2, hz - 1), ri(r, 2, 6), 1, pickOf(r, ['#f8b060', '#c06050']));
      },
      mid(c, LW, H, hz, r) {
        // A freighter: dark hull, white stripe, portholes, bridge, masts.
        const sx = Math.round(LW * 0.04), sw = Math.round(LW * 0.56), deck = hz - Math.round(H * 0.2);
        for (let k = 0; k < Math.round(H * 0.18); k++) rect(c, sx + (k > H * 0.12 ? k - H * 0.12 : 0), deck + k, sw - 2 * (k > H * 0.12 ? k - H * 0.12 : 0), 1, k < 2 ? '#e8e4d8' : k % 7 === 0 ? '#3a1a1a' : '#5a1e1e');
        for (let x = sx + 6; x < sx + sw - 6; x += 7) disc(c, x, deck + 5, 1, '#ffd890');
        const bx = sx + sw - Math.round(sw * 0.28);
        rect(c, bx, deck - 16, 18, 16, '#e8e4d8'); rect(c, bx + 16, deck - 16, 2, 16, '#b8b4a8');
        for (let y = deck - 14; y < deck - 2; y += 4) rect(c, bx + 2, y, 13, 2, '#3a4a6a');
        rect(c, bx + 6, deck - 24, 4, 8, '#c02a2a'); rect(c, bx + 6, deck - 24, 4, 2, '#1b1b1b');
        for (const mx of [sx + 14, sx + Math.round(sw * 0.45)]) { rect(c, mx, deck - Math.round(H * 0.34), 1, Math.round(H * 0.34), '#3a2a2a'); rect(c, mx - 6, deck - Math.round(H * 0.26), 13, 1, '#3a2a2a'); }
        for (let x = sx + 20; x < bx - 4; x += 8) { const n = ri(r, 1, 2); for (let k = 0; k < n; k++) { const col = pickOf(r, ['#a83a2e', '#2e7a52', '#2e5aa8', '#c89a2e']); rect(c, x, deck - 4 - k * 4, 7, 4, col); rect(c, x, deck - 4 - k * 4, 7, 1, shade(col, 1.3)); } }
        // Crates and barrels on the right.
        const cx = Math.round(LW * 0.8);
        for (const [dx, dy] of [[0, 0], [10, 0], [5, -9], [20, 0]]) {
          rect(c, cx + dx, hz - 9 + dy, 9, 9, '#a0703a'); rect(c, cx + dx, hz - 9 + dy, 9, 1, '#c8904a'); rect(c, cx + dx, hz - 5 + dy, 9, 1, '#6a4a20'); rect(c, cx + dx + 4, hz - 9 + dy, 1, 9, '#6a4a20');
        }
        for (const x of [Math.round(LW * 0.7), Math.round(LW * 0.73)]) { rect(c, x, hz - 7, 5, 7, '#3a5a8a'); rect(c, x, hz - 5, 5, 1, '#1b2a4a'); rect(c, x + 1, hz - 7, 1, 7, '#5a7aaa'); }
        // Signal flag line from the mast (flutters in the animated pass).
      },
      floor(c, LW, H, hz, r) {
        gradient(c, 0, LW, hz, H, ['#6a4a30', '#8a6040', '#9a6c48']);
        for (let k = 0; k < 10; k++) rect(c, 0, hz + Math.round((H - hz) * Math.pow(k / 10, 1.4)), LW, 1, '#4a3020');
        for (let i = 0; i < LW / 3; i++) px(c, ri(r, 0, LW), ri(r, hz + 1, H), pickOf(r, ['#4a3020', '#a87450']));
        for (const x of [Math.round(LW * 0.05), Math.round(LW * 0.95)]) { rect(c, x - 3, hz + 1, 7, 6, '#1c1c24'); rect(c, x - 4, hz, 9, 2, '#2a2a36'); }
      },
      setup(r, LW, H, hz) {
        const deck = hz - Math.round(H * 0.2);
        const pal = { shirts: ['#f0ece0', '#f0ece0', '#3a5aa8', '#c02a2a', '#e0c070'], pants: ['#2a3a6a', '#2a2a3a', '#5a4a3a'], hats: ['#f0ece0', '#2a3a6a'], hatP: 0.4 };
        return {
          wy: Math.round(hz - H * 0.18), sun: Math.round(LW * 0.62),
          crowd: makeCrowd(r, LW * 0.02, LW * 0.98, hz - 1, Math.max(5, Math.round(LW / 12)), pal, crowdH(H)),
          line: { x0: Math.round(LW * 0.04) + 14, x1: Math.round(LW * 0.04) + Math.round(LW * 0.56 * 0.45), y: deck - Math.round(H * 0.34) },
          gulls: birdSet(r, 3, LW, H * 0.12, H * 0.35),
        };
      },
      anim(c, W, H, hz, t, st, X, still) {
        const sx = X(st.sun, DEPTH.sky);
        for (let y = st.wy + 2; y < hz - 1; y += 2) {
          const w = 3 + ((y - st.wy) >> 1), j = still ? 0 : Math.round(Math.sin(t * 3 + y) * 1.5);
          alpha(c, 0.6, () => rect(c, sx - (w >> 1) + j, y, w, 1, '#ffe0a0'));
        }
        const L = st.line, cols = ['#e0202a', '#f0d020', '#2a5ad0', '#f0ece0', '#2aa04a'];
        for (let i = 0; i < 7; i++) {
          const u = (i + 0.5) / 7, x = X(L.x0 + (L.x1 - L.x0) * u, DEPTH.mid), y = L.y + Math.round(6 * u) + 1;
          const fl = still ? 0 : Math.round(Math.sin(t * 7 + i) * 1);
          rect(c, x - 1, y, 3, 3 + fl, cols[i % cols.length]);
        }
        drawCrowd(c, st.crowd, t, X, DEPTH.mid, still);
        birds(c, st.gulls, t, W, still, '#f4f0f0');
      },
    },
    {
      key: 'airbase', name: 'Air Base',
      sky(c, LW, H, hz) { gradient(c, 0, LW, 0, hz + 2, ['#5a90c8', '#8ab8e0', '#c8dcec', '#f0e0c0']); },
      far(c, LW, H, hz, r) {
        ridge(c, LW, hz - 2, H * 0.08, hz + 1, '#8aa0a8', r);
        const tx = Math.round(LW * 0.9);
        rect(c, tx, hz - Math.round(H * 0.3), 4, Math.round(H * 0.3), '#c8c0b0'); rect(c, tx - 3, hz - Math.round(H * 0.34), 10, 4, '#3a5a6a'); rect(c, tx - 4, hz - Math.round(H * 0.35), 12, 1, '#6a6a6a');
      },
      mid(c, LW, H, hz, r) {
        // The hangar: corrugated walls, a dark open bay, and a jet parked inside.
        const hx0 = Math.round(LW * 0.08), hx1 = Math.round(LW * 0.84), top = Math.round(H * 0.08);
        rect(c, hx0, top, hx1 - hx0, hz - top, '#8a8a7a');
        for (let x = hx0; x < hx1; x += 3) rect(c, x, top, 1, hz - top, '#74746a');
        for (let k = 0; k < 6; k++) rect(c, hx0 - 2 + k, top - 1 - k, hx1 - hx0 + 4 - 2 * k, 1, '#6a6a60');
        const bx0 = hx0 + Math.round((hx1 - hx0) * 0.14), bx1 = hx1 - Math.round((hx1 - hx0) * 0.14), bt = top + Math.round(H * 0.1);
        rect(c, bx0, bt, bx1 - bx0, hz - bt, '#2a2a2c'); gradient(c, bx0, bx1 - bx0, bt, hz, ['#1a1a1c', '#2e2e30', '#3a3a3a']);
        rect(c, bx0 - 2, bt - 2, bx1 - bx0 + 4, 2, '#e0c020');
        for (let x = bx0; x < bx1; x += 8) px(c, x + 3, bt + 2, '#fff6c0');
        // Jet, side view, nose left: fuselage, canopy, delta wing, tail fin, lamps on it.
        const jx = Math.round((bx0 + bx1) / 2), jy = hz - Math.round(H * 0.13), jl = Math.round((bx1 - bx0) * 0.8), j0 = jx - jl / 2;
        for (let k = 0; k < jl; k++) {
          const u = k / jl, th = u < 0.18 ? Math.round(u / 0.18 * 3) : u > 0.92 ? 2 : 3;
          rect(c, j0 + k, jy - th, 1, 2 * th + 1, '#9aa0a8'); px(c, j0 + k, jy - th, '#c8ccd2'); px(c, j0 + k, jy + th, '#6a7078');
        }
        rect(c, j0 + jl * 0.14, jy - 5, jl * 0.14, 2, '#3a8ac0'); rect(c, j0 + jl * 0.16, jy - 6, jl * 0.1, 1, '#8ad8f8');
        for (let k = 0; k < jl * 0.34; k++) rect(c, j0 + jl * 0.36 + k, jy + 1, 1, Math.min(6, 1 + Math.round(k / (jl * 0.34) * 6)), k % 5 ? '#7a8088' : '#6a7078');
        for (let k = 0; k < 11; k++) rect(c, j0 + jl * 0.84 + k * 0.7, jy - 3 - k, Math.max(2, jl * 0.12 - k * 0.8), 1, k % 3 ? '#8a9098' : '#6a7078');
        rect(c, j0 + jl * 0.9, jy - 9, 3, 2, '#b8202a');
        rect(c, j0 + jl, jy - 2, 3, 5, '#3a3a3a'); rect(c, j0 + jl * 0.3, jy - 1, 4, 2, '#2a2a2a');
        for (const f of [0.2, 0.62]) { rect(c, j0 + jl * f, jy + 3, 1, 5, '#3a3a3a'); rect(c, j0 + jl * f - 1, jy + 7, 3, 2, '#1b1b1b'); }
        // A big striped flag hung on the wall, fuel drums, crates.
        const fx = hx0 + 3, fw = Math.round((hx1 - hx0) * 0.11), fh = Math.round(H * 0.18);
        for (let k = 0; k < fh; k++) rect(c, fx, top + 6 + k, fw, 1, Math.floor(k / 2) % 2 ? '#f0ece0' : '#b8202a');
        rect(c, fx, top + 6, Math.round(fw * 0.45), Math.round(fh * 0.5), '#2a3a7a');
        for (let i = 0; i < 6; i++) px(c, fx + 1 + (i % 3) * 2, top + 7 + Math.floor(i / 3) * 3, '#f0ece0');
        for (const x of [hx1 + 4, hx1 + 10]) { rect(c, x, hz - 8, 5, 8, '#4a5a2a'); rect(c, x, hz - 6, 5, 1, '#2a3a1a'); rect(c, x + 1, hz - 8, 1, 8, '#6a7a4a'); }
        rect(c, hx0 - 12, hz - 9, 10, 9, '#6a5a3a'); rect(c, hx0 - 12, hz - 9, 10, 1, '#8a7a5a');
      },
      floor(c, LW, H, hz, r) {
        textured(c, LW, hz, H, ['#9a968a', '#aaa698', '#b4b0a2'], ['#8a867a', '#bcb8aa'], r, 9);
        seams(c, LW, hz, H, 4, '#8a867a', 1.5); converging(c, LW, hz, H, 36, '#8a867a', 1.3);
        const vy = hz - (H - hz) * 1.3;
        for (let y = hz + 2; y < H; y++) { const k = (y - vy) / (H - vy); rect(c, LW / 2 - LW * 0.36 * k, y, 2, 1, '#e0c020'); rect(c, LW / 2 + LW * 0.36 * k, y, 2, 1, '#e0c020'); }
        for (let i = 0; i < 3; i++) alpha(c, 0.35, () => ellipse(c, ri(r, 10, LW - 10), ri(r, hz + 4, H - 4), ri(r, 4, 8), 1, '#3a3a34'));
      },
      setup(r, LW, H, hz) {
        const pal = { shirts: ['#6a7a3a', '#5a6a2a', '#8a7a4a', '#f0ece0'], pants: ['#4a5a2a', '#3a3a2a'], hats: ['#4a5a2a', '#2a2a2a'], hatP: 0.6 };
        return {
          crowd: makeCrowd(r, 0, LW * 0.24, hz - 1, Math.max(3, Math.round(LW / 26)), pal, crowdH(H)).concat(makeCrowd(r, LW * 0.72, LW, hz - 1, Math.max(3, Math.round(LW / 26)), pal, crowdH(H))),
          sock: { x: Math.round(LW * 0.96), y: hz - Math.round(H * 0.26) },
        };
      },
      anim(c, W, H, hz, t, st, X, still) {
        const x = X(st.sock.x, DEPTH.far);
        rect(c, x, st.sock.y, 1, Math.round(H * 0.26), '#6a6a6a');
        flag(c, x, st.sock.y, 7, 3, ['#ff6a1a', '#f0ece0', '#ff6a1a'], t, still, -1);
        drawCrowd(c, st.crowd, t, X, DEPTH.mid, still);
      },
    },
    {
      key: 'river', name: 'River Village',
      sky(c, LW, H, hz, r) {
        gradient(c, 0, LW, 0, hz + 2, ['#3a8ad8', '#6ab0e8', '#b0dcf4', '#e8f4f0']);
        for (let i = 0; i < 4; i++) { const x = ri(r, 0, LW), y = ri(r, Math.round(H * 0.08), Math.round(H * 0.3)); ellipse(c, x, y, 11, 3, '#ffffff'); ellipse(c, x + 6, y - 2, 6, 2, '#ffffff'); rect(c, x - 10, y + 3, 22, 1, '#c8e0f0'); }
      },
      far(c, LW, H, hz, r) {
        ridge(c, LW, hz - Math.round(H * 0.16), H * 0.14, hz + 1, '#3a8a4a', r);
        ridge(c, LW, hz - Math.round(H * 0.12), H * 0.08, hz + 1, '#2a6a3a', r, 2);
        for (let i = 0; i < 6; i++) palm(c, ri(r, 0, LW), hz - Math.round(H * 0.14), ri(r, 10, 16), '#6a5030', '#2a7a3a', r() - 0.5);
        const wy = hz - Math.round(H * 0.12);
        gradient(c, 0, LW, wy, hz + 1, ['#4a9ab0', '#3a8aa0', '#2a7090']);
        for (let i = 0; i < LW / 4; i++) rect(c, ri(r, 0, LW), ri(r, wy + 1, hz), ri(r, 2, 5), 1, '#8ad0e0');
      },
      mid(c, LW, H, hz, r) {
        // Painted stilt houses along the bank.
        const hs = [[0.02, '#e87aa0'], [0.2, '#f0c040'], [0.66, '#40b0b0'], [0.84, '#f08a40']];
        for (const [fx, col] of hs) {
          const x = Math.round(LW * fx), w = Math.round(Math.max(18, LW * 0.13)), fl = hz - Math.round(H * 0.1), h = Math.round(H * 0.16);
          for (let k = 2; k < w; k += 6) rect(c, x + k, fl, 1, hz - fl, '#5a3a20');
          rect(c, x, fl - h, w, h, col); rect(c, x + w - 2, fl - h, 2, h, shade(col, 0.75));
          rect(c, x + 3, fl - h + 3, 4, 5, '#3a2a20'); rect(c, x + w - 9, fl - h + 3, 4, 4, '#ffffff'); rect(c, x + w - 8, fl - h + 4, 2, 2, '#4a8ab0');
          for (let k = 0; k < 5; k++) rect(c, x - 2 + k, fl - h - 1 - k, w + 4 - 2 * k, 1, k % 2 ? '#b0b0b0' : '#c84a2a');
          rect(c, x, fl, w, 1, '#5a3a20');
        }
        // A canoe on the water.
        const bx = Math.round(LW * 0.44), by = hz - Math.round(H * 0.05);
        rect(c, bx, by, 16, 2, '#7a4a24'); rect(c, bx - 1, by - 1, 2, 1, '#7a4a24'); rect(c, bx + 15, by - 1, 2, 1, '#7a4a24'); rect(c, bx + 1, by, 14, 1, '#a0683a');
        palm(c, Math.round(LW * 0.36), hz, Math.round(H * 0.34), '#7a5a34', '#2a8a3a', 0.6);
        palm(c, Math.round(LW * 0.6), hz, Math.round(H * 0.3), '#7a5a34', '#3a9a3a', -0.5);
      },
      floor(c, LW, H, hz, r) {
        gradient(c, 0, LW, hz, H, ['#9a6a3a', '#b88050', '#c48c5a']);
        converging(c, LW, hz, H, 8, '#7a5028', 1.1);
        seams(c, LW, hz, H, 3, '#7a5028', 1.3);
        for (let i = 0; i < LW / 4; i++) px(c, ri(r, 0, LW), ri(r, hz + 1, H), '#d8a070');
      },
      setup(r, LW, H, hz) {
        const pal = { shirts: ['#f0d020', '#2aa04a', '#e0302a', '#f0ece0', '#2a6ad0', '#ff8ab0'], pants: ['#2a3a6a', '#f0ece0', '#3a2a1a'], hats: ['#e0c080'], hatP: 0.2 };
        return {
          crowd: makeCrowd(r, 0, LW, hz - 1, Math.max(6, Math.round(LW / 10)), pal, crowdH(H)),
          bunting: { y: Math.round(H * 0.14) }, boat: { x: Math.round(LW * 0.44), y: hz - Math.round(H * 0.05) },
          parrots: particles(r, 3, r => ({ x: r() * LW, y: Math.round(H * (0.12 + r() * 0.2)), v: 8 + r() * 6, ph: r() * 6, col: pickOf(r, ['#e0302a', '#2aa04a', '#f0c020']) })),
        };
      },
      anim(c, W, H, hz, t, st, X, still) {
        const cols = ['#e0302a', '#f0d020', '#2aa04a', '#2a6ad0', '#ff8ab0'];
        for (let x = 0, i = 0; x < W + 16; x += 6, i++) {
          const u = mod(x, 60) / 60, y = st.bunting.y + Math.round(5 * (1 - Math.pow(2 * u - 1, 2)));
          const sx = X(x, DEPTH.mid), fl = still ? 0 : Math.round(Math.sin(t * 6 + i) * 0.8);
          px(c, sx, y, '#3a2a1a'); rect(c, sx, y + 1, 4, 1, cols[i % 5]); rect(c, sx + 1, y + 2, 2 + fl, 1, cols[i % 5]); px(c, sx + 1 + fl, y + 3, cols[i % 5]);
        }
        const b = st.boat, bob = still ? 0 : Math.round(Math.sin(t * 2));
        alpha(c, 0.35, () => rect(c, X(b.x, DEPTH.mid) - 1, b.y + 3 + bob, 18, 1, '#8ad0e0'));
        drawCrowd(c, st.crowd, t, X, DEPTH.mid, still);
        if (!still) for (const p of st.parrots) { const x = mod(p.x + t * p.v, W + 20) - 10, y = p.y + Math.round(Math.sin(t * 2 + p.ph) * 3); rect(c, x, y, 3, 1, p.col); px(c, x + (Math.sin(t * 10 + p.ph) > 0 ? 1 : 0), y - 1, p.col); px(c, x + 3, y, '#f0d020'); }
      },
    },
    {
      key: 'golden', name: 'Golden Temple',
      sky(c, LW, H, hz) { gradient(c, 0, LW, 0, hz + 2, ['#2a2050', '#6a3a6a', '#c86a5a', '#f0a868', '#f8d090']); },
      far(c, LW, H, hz, r) {
        for (const fx of [0.12, 0.3, 0.7, 0.88]) {
          const x = Math.round(LW * fx), h = Math.round(H * (0.3 + r() * 0.14));
          for (let k = 0; k < h; k++) { const half = Math.max(0, Math.round((k / h) * 5)); rect(c, x - half, hz - h + k, 2 * half + 1, 1, k % 4 ? '#7a3a4a' : '#5a2a3a'); }
          px(c, x, hz - h - 1, '#e0b040');
        }
        ridge(c, LW, hz - 2, H * 0.06, hz + 1, '#3a2a3a', r);
      },
      mid(c, LW, H, hz) {
        // Hall pillars and roofs framing a great reclining golden statue.
        const g = '#e0a830', gl = '#f8d870', gd = '#a87020', ped = hz - Math.round(H * 0.08);
        rect(c, Math.round(LW * 0.14), ped, Math.round(LW * 0.72), hz - ped, '#9a2a20');
        rect(c, Math.round(LW * 0.14), ped, Math.round(LW * 0.72), 1, '#e0b040');
        for (let x = Math.round(LW * 0.16); x < LW * 0.84; x += 6) rect(c, x, ped + 2, 3, 2, '#e0b040');
        const x0 = Math.round(LW * 0.2), x1 = Math.round(LW * 0.8), bh = Math.round(H * 0.12);
        for (let x = x0 + 12; x < x1; x++) {
          const u = (x - x0 - 12) / (x1 - x0 - 12);
          const h = Math.round(bh * (0.72 + 0.28 * Math.sin(Math.min(1, u * 1.6) * Math.PI)) * (1 - 0.45 * u * u) - (u > 0.94 ? (u - 0.94) * 60 : 0));
          rect(c, x, ped - h, 1, h, g); rect(c, x, ped - h, 1, 2, gl); rect(c, x, ped - 2, 1, 2, gd);
          if ((x - x0) % 7 === 0 && u < 0.9) { px(c, x, ped - h + 3, gd); px(c, x + 1, ped - h + 4, gd); px(c, x + 2, ped - h + 5, gd); }
        }
        rect(c, x0, ped - 6, 14, 6, '#c02a2a'); rect(c, x0, ped - 6, 14, 1, '#e0b040');
        rect(c, x0 + 3, ped - bh - 12, 3, bh + 6, g); rect(c, x0 + 3, ped - bh - 12, 1, bh + 6, gl);
        disc(c, x0 + 9, ped - bh - 10, 5, g); disc(c, x0 + 8, ped - bh - 11, 3, gl);
        rect(c, x0 + 7, ped - bh - 17, 4, 3, gd); px(c, x0 + 9, ped - bh - 19, gl);
        rect(c, x0 + 6, ped - bh - 9, 2, 1, gd); rect(c, x0 + 10, ped - bh - 9, 2, 1, gd);
        rect(c, x0 + 12, ped - bh - 4, 6, 4, g);
        for (const fx of [0.05, 0.95]) {
          const px0 = Math.round(LW * fx) - 3, top = Math.round(H * 0.1);
          rect(c, px0, top, 6, hz - top, '#b8302a'); rect(c, px0 + 1, top, 1, hz - top, '#e05a4a');
          for (let y = top + 4; y < hz; y += 8) rect(c, px0, y, 6, 2, '#e0b040');
        }
        roof(c, Math.round(LW * 0.05), Math.round(H * 0.06), Math.round(LW * 0.22), 5, '#b83a2a', '#2a7a4a', '#e0b040');
        roof(c, Math.round(LW * 0.95), Math.round(H * 0.06), Math.round(LW * 0.22), 5, '#b83a2a', '#2a7a4a', '#e0b040');
        for (const fx of [0.33, 0.67]) { const x = Math.round(LW * fx); rect(c, x - 3, hz - 4, 7, 4, '#8a6a3a'); rect(c, x - 1, hz - 6, 1, 2, '#f0ece0'); rect(c, x + 1, hz - 6, 1, 2, '#f0ece0'); }
      },
      floor(c, LW, H, hz, r) {
        for (let k = 0; k < 8; k++) {
          const y0 = hz + Math.round((H - hz) * Math.pow(k / 8, 1.5)), y1 = hz + Math.round((H - hz) * Math.pow((k + 1) / 8, 1.5));
          rect(c, 0, y0, LW, y1 - y0, k % 2 ? '#8a3a2a' : '#9a4632');
        }
        converging(c, LW, hz, H, 14, '#6a2a1e', 1.2);
        alpha(c, 0.18, () => { for (let y = hz + 2; y < hz + (H - hz) * 0.5; y += 2) rect(c, LW * 0.22, y, LW * 0.56, 1, '#f8d870'); });
        for (let i = 0; i < LW / 5; i++) px(c, ri(r, 0, LW), ri(r, hz, H), '#b05a40');
      },
      setup(r, LW, H, hz) {
        const pal = { shirts: ['#f0ece0', '#e0a020', '#2a6ad0', '#c02a60', '#2aa06a'], pants: ['#2a2a3a', '#6a3a2a'] };
        return {
          crowd: makeCrowd(r, LW * 0.06, LW * 0.19, hz - 1, Math.max(3, Math.round(LW / 30)), pal, crowdH(H)).concat(makeCrowd(r, LW * 0.8, LW * 0.94, hz - 1, Math.max(3, Math.round(LW / 30)), pal, crowdH(H))),
          candles: [0.33, 0.67].flatMap(f => [-1, 1].map(d => ({ x: Math.round(LW * f) + d, y: hz - 7, ph: r() * 6 }))),
          smoke: puffSet(r, 4), bells: [0.05, 0.95].map(f => Math.round(LW * f)),
        };
      },
      anim(c, W, H, hz, t, st, X, still) {
        for (const cd of st.candles) {
          const x = X(cd.x, DEPTH.mid), fl = still ? 0 : Math.round(Math.sin(t * 13 + cd.ph));
          alpha(c, 0.3, () => disc(c, x, cd.y, 3, '#ffb347'));
          px(c, x, cd.y - fl, '#ffd27a'); px(c, x, cd.y + 1, '#ff8c00');
        }
        smoke(c, X(st.candles[0].x, DEPTH.mid), hz - 8, t, st.smoke, '#e8e0e8', still, 24, 0.35);
        st.bells.forEach((bx, i) => {
          const x = X(bx, DEPTH.mid) + (still ? 0 : Math.round(Math.sin(t * 3 + i) * 1.4)), y = Math.round(H * 0.06) + 8;
          rect(c, x, y, 1, 3, '#3a2a10'); rect(c, x - 1, y + 3, 3, 3, '#e0b040'); px(c, x, y + 6, '#a87020');
        });
        drawCrowd(c, st.crowd, t, X, DEPTH.mid, still);
      },
    },
    {
      key: 'strip', name: 'Neon Strip',
      sky(c, LW, H, hz, r) {
        gradient(c, 0, LW, 0, hz + 2, ['#0a0620', '#1a0a3a', '#3a1050', '#5a1a5a']);
        stars(c, LW, Math.round(H * 0.3), Math.round(LW / 12), r, ['#8a7ab0']);
      },
      far(c, LW, H, hz, r) {
        for (let x = -4; x < LW;) {
          const w = ri(r, 12, 22), h = Math.round(H * (0.4 + r() * 0.4));
          rect(c, x, hz - h, w, h + 1, pickOf(r, ['#1a1030', '#221440']));
          for (let wy = hz - h + 3; wy < hz - 4; wy += 3) for (let wx = x + 2; wx < x + w - 2; wx += 3) if (r() < 0.35) px(c, wx, wy, pickOf(r, ['#ffd27a', '#ff8ab0', '#8ae0ff']));
          x += w + ri(r, 1, 6);
        }
      },
      mid(c, LW, H, hz, r) {
        // Casino front: gold doors, marquee frames (lit in the animated pass), palms.
        const fy = hz - Math.round(H * 0.26);
        rect(c, 0, fy, LW, hz - fy, '#2a1030'); rect(c, 0, fy, LW, 2, '#e0b040');
        for (let x = 6; x < LW; x += 22) { rect(c, x, fy + 8, 12, hz - fy - 8, '#e0b040'); rect(c, x + 1, fy + 9, 10, hz - fy - 9, '#6a3a1a'); rect(c, x + 6, fy + 9, 1, hz - fy - 9, '#e0b040'); }
        for (const f of [0.03, 0.97]) palm(c, Math.round(LW * f), hz, Math.round(H * 0.4), '#1a1020', '#1a2a20', f < 0.5 ? 0.4 : -0.4);
        rect(c, Math.round(LW * 0.3) - 3, Math.round(H * 0.12), textW('CASINO') * 2 + 6, 16, '#12061e');
        rect(c, Math.round(LW * 0.66) - 2, Math.round(H * 0.18), textW('LUCKY 7') + 4, 9, '#12061e');
      },
      floor(c, LW, H, hz, r) {
        gradient(c, 0, LW, hz, H, ['#1a1420', '#221a2a', '#2a2032']);
        rect(c, 0, hz, LW, 3, '#4a3a4a'); rect(c, 0, hz + 3, LW, 1, '#6a5a6a');
        for (let i = 0; i < LW * (H - hz) / 10; i++) px(c, ri(r, 0, LW), ri(r, hz + 4, H), pickOf(r, ['#2a2232', '#161018']));
        const my = Math.round(hz + (H - hz) * 0.6);
        for (let x = 4; x < LW; x += 18) rect(c, x, my, 9, 1, '#d0c060');
      },
      setup(r, LW, H, hz) {
        const pal = { shirts: ['#e0202a', '#2a2a2a', '#f0ece0', '#a02ab0', '#e0b040', '#2a6ad0'], pants: ['#1a1a1a', '#2a2a4a'] };
        return {
          crowd: makeCrowd(r, 0, LW, hz - 1, Math.max(6, Math.round(LW / 10)), pal, crowdH(H)),
          big: { x: Math.round(LW * 0.3), y: Math.round(H * 0.12) }, lucky: { x: Math.round(LW * 0.66), y: Math.round(H * 0.18) },
          beams: [0.2, 0.8].map((f, i) => ({ x: Math.round(LW * f), ph: i * 2 })),
        };
      },
      anim(c, W, H, hz, t, st, X, still) {
        for (const b of st.beams) {
          const a = still ? 0.3 : Math.sin(t * 0.6 + b.ph) * 0.5, x = X(b.x, DEPTH.far);
          alpha(c, 0.1, () => { for (let k = 0; k < hz; k++) rect(c, x + Math.round(a * k), hz - k, 1 + Math.floor(k / 12), 1, '#e8e4ff'); });
        }
        const B = st.big, bx = X(B.x, DEPTH.mid), w = textW('CASINO') * 2 + 6;
        const chase = still ? 0 : Math.floor(t * 8);
        for (let i = 0; i < (w + 16) * 2; i += 2) {
          const onB = (i / 2 + chase) % 3 === 0, col = onB ? '#fff6c0' : '#8a6a20';
          const k = i / 2;
          if (k < w / 2) { px(c, bx - 3 + k * 2, B.y - 1, col); px(c, bx - 3 + k * 2, B.y + 16, col); }
        }
        const flick = still || noise('casino', Math.floor(t * 8)) > 0.07;
        alpha(c, flick ? 0.3 : 0.1, () => rect(c, bx - 2, B.y + 1, w - 2, 14, '#ff3cac'));
        c.fillStyle = flick ? '#ff6ac8' : '#5a2a4a';
        const g = 'CASINO';
        for (let n = 0, x = bx; n < g.length; n++, x += 8) {
          const glyph = FONT[g[n]];
          for (let i = 0; i < 15; i++) if (glyph[i] === '1') c.fillRect(x + (i % 3) * 2, B.y + 3 + Math.floor(i / 3) * 2, 2, 2);
        }
        const L = st.lucky, lx = X(L.x, DEPTH.mid), lon = still || Math.floor(t * 2) % 4 !== 3;
        if (lon) alpha(c, 0.3, () => rect(c, lx - 2, L.y, textW('LUCKY 7') + 4, 9, '#24e6ff'));
        text(c, 'LUCKY 7', lx, L.y + 2, lon ? '#8af4ff' : '#1a3a4a');
        alpha(c, 0.25, () => rect(c, bx, hz + 5, w - 6, 1, '#ff6ac8'));
        drawCrowd(c, st.crowd, t, X, DEPTH.mid, still);
      },
    },
    {
      key: 'factory', name: 'Snow Factory',
      sky(c, LW, H, hz) { gradient(c, 0, LW, 0, hz + 2, ['#5a6070', '#7a808e', '#9aa0aa', '#bcc0c6']); },
      far(c, LW, H, hz, r) {
        for (let x = -4; x < LW;) { const w = ri(r, 14, 28), h = Math.round(H * (0.12 + r() * 0.12)); rect(c, x, hz - h, w, h + 1, '#6a6e7a'); rect(c, x, hz - h, w, 1, '#e8eef4'); x += w; }
        for (const f of [0.18, 0.3, 0.82]) { const x = Math.round(LW * f), h = Math.round(H * 0.5); rect(c, x, hz - h, 5, h, '#7a5048'); rect(c, x, hz - h, 5, 1, '#e8eef4'); rect(c, x, hz - h + 4, 5, 1, '#e8e4dc'); }
      },
      mid(c, LW, H, hz, r) {
        // Brick works: lit windows, snow on the ledges, a great gear, pipes.
        const top = Math.round(hz - H * 0.36);
        bricks(c, 0, top, LW, hz - top, '#8a3a2a', '#6a2a20');
        rect(c, 0, top - 2, LW, 3, '#eef3f8'); rect(c, 0, top + 1, LW, 1, '#c8d4e0');
        for (let x = 4; x < LW - 12; x += 20) {
          if (Math.abs(x - LW / 2) < 20) continue;
          rect(c, x, top + 6, 12, 12, '#3a2a20'); rect(c, x + 1, top + 7, 10, 10, '#f0b860');
          rect(c, x + 6, top + 7, 1, 10, '#3a2a20'); rect(c, x + 1, top + 12, 10, 1, '#3a2a20');
          rect(c, x - 1, top + 18, 14, 2, '#eef3f8');
        }
        const gx = Math.round(LW / 2), gy = top + 14, gr = Math.round(H * 0.1);
        for (let a = 0; a < 12; a++) rect(c, gx + Math.round(Math.cos(a * 0.5236) * gr) - 1, gy + Math.round(Math.sin(a * 0.5236) * gr) - 1, 3, 3, '#5a5a62');
        disc(c, gx, gy, gr - 1, '#6a6a72'); disc(c, gx, gy, gr - 4, '#4a4a52'); disc(c, gx, gy, 2, '#8a8a92');
        rect(c, 0, hz - 12, LW, 3, '#5a6a72'); rect(c, 0, hz - 12, LW, 1, '#8a9aa2');
        for (let x = 8; x < LW; x += 26) rect(c, x, hz - 13, 3, 5, '#4a5a62');
        rect(c, gx - 12, hz - 10, 24, 10, '#4a4a52'); rect(c, gx - 11, hz - 9, 22, 1, '#6a6a72');
      },
      floor(c, LW, H, hz, r) {
        textured(c, LW, hz, H, ['#c8d4e0', '#dce4ee', '#eef3f8'], ['#b8c4d4', '#ffffff', '#a8b4c4'], r, 5);
        for (let i = 0; i < 4; i++) alpha(c, 0.5, () => ellipse(c, ri(r, 0, LW), ri(r, hz + 3, H - 2), ri(r, 6, 14), 1, '#8a8a8a'));
        for (const f of [0.35, 0.65]) { const vy = hz - (H - hz) * 1.2; for (let y = hz; y < H; y++) px(c, LW / 2 + (LW * f - LW / 2) * (y - vy) / (H - vy), y, '#a0acbc'); }
      },
      setup(r, LW, H, hz) {
        const pal = { shirts: ['#3a3a4a', '#5a3a2a', '#2a4a3a', '#6a2a2a'], pants: ['#2a2a2a', '#3a3a4a'], hats: ['#6a4a2a', '#3a2a1a', '#8a8a8a'], hatP: 0.85 };
        return {
          crowd: makeCrowd(r, 0, LW, hz - 1, Math.max(5, Math.round(LW / 12)), pal, crowdH(H)),
          snow: particles(r, Math.round(LW / 4), r => ({ x: r() * LW, y: r() * H, sp: 0.6 + r() * 0.6, sw: 1 + r() * 2, ph: r() * 6 })),
          chimneys: [0.18, 0.3, 0.82].map(f => Math.round(LW * f) + 2), cy: hz - Math.round(H * 0.5),
          puffs: puffSet(r, 6), gear: { x: Math.round(LW / 2), y: Math.round(hz - H * 0.36) + 14, r: Math.round(H * 0.1) },
        };
      },
      anim(c, W, H, hz, t, st, X, still) {
        st.chimneys.forEach((x, i) => smoke(c, X(x, DEPTH.far), st.cy - 2, t + i * 1.3, st.puffs, '#d8dce2', still, 34, 0.55));
        const G = st.gear, gx = X(G.x, DEPTH.mid), a0 = still ? 0 : t * 0.8;
        for (let a = 0; a < 4; a++) { const ang = a0 + a * Math.PI / 2; rect(c, gx + Math.round(Math.cos(ang) * (G.r - 5)) - 1, G.y + Math.round(Math.sin(ang) * (G.r - 5)) - 1, 2, 2, '#9a9aa2'); }
        drawCrowd(c, st.crowd, t, X, DEPTH.mid, still);
        c.fillStyle = '#ffffff';
        for (const s of st.snow) {
          const x = still ? s.x : mod(s.x + Math.sin(t * 1.2 + s.ph) * s.sw * 3 + t * 4, W + 6) - 3;
          const y = still ? s.y : mod(s.y + t * 16 * s.sp, H + 4) - 2;
          c.fillRect(Math.round(x), Math.round(y), s.sp > 0.9 ? 2 : 1, s.sp > 0.9 ? 2 : 1);
        }
      },
    },
    {
      key: 'datadojo', name: 'Qubic Data Dojo',
      sky(c, LW, H, hz) {
        gradient(c, 0, LW, 0, hz + 2, ['#2a1a14', '#3a2418', '#4a2e1e']);
        for (let x = 0; x < LW; x += 16) rect(c, x, 0, 1, hz, '#2a1810');
      },
      far(c, LW, H, hz) {
        // The back wall: shoji panels glowing faintly blue from the machines behind.
        const top = Math.round(H * 0.1);
        rect(c, 0, top, LW, hz - top, '#d8e4ea');
        for (let y = top; y < hz; y += 6) rect(c, 0, y, LW, 1, '#7a5a3a');
        for (let x = 0; x < LW; x += 5) rect(c, x, top, 1, hz - top, '#7a5a3a');
        alpha(c, 0.25, () => rect(c, 0, top, LW, hz - top, '#3a8ad0'));
        // The emblem banner: a ring and a cube, in gold on indigo.
        const cx = Math.round(LW / 2), bw = 22, bt = top + 2, bh = Math.round(H * 0.3);
        rect(c, cx - bw / 2 - 1, bt - 1, bw + 2, 1, '#3a2418');
        rect(c, cx - bw / 2, bt, bw, bh, '#1b2a6a'); rect(c, cx - bw / 2, bt, 1, bh, '#2a3a8a');
        for (let a = 0; a < 40; a++) px(c, cx + Math.round(Math.cos(a * 0.157) * 7), bt + 12 + Math.round(Math.sin(a * 0.157) * 7), '#e0b040');
        cube(c, cx, bt + 8, 4, '#fff1a0', '#e0b040', '#a87020');
        for (let k = 0; k < 3; k++) rect(c, cx - 5 + k * 4, bt + 24, 2, 3, '#e0b040');
      },
      mid(c, LW, H, hz) {
        const top = Math.round(H * 0.08), wood = '#5a3420';
        rect(c, 0, 0, LW, top, '#2e1a0e'); rect(c, 0, top, LW, 3, wood); rect(c, 0, top, LW, 1, '#8a5a34');
        // Server racks between the pillars (their lights blink in the animated pass).
        for (const f of [0.1, 0.22, 0.78, 0.9]) {
          const x = Math.round(LW * f) - 6, rt = top + 8;
          rect(c, x, rt, 12, hz - rt, '#1a1c24'); rect(c, x, rt, 12, 1, '#3a3c48'); rect(c, x, rt, 1, hz - rt, '#2a2c38');
          for (let y = rt + 3; y < hz - 2; y += 4) rect(c, x + 2, y, 8, 2, '#262a36');
        }
        for (const f of [0.03, 0.16, 0.84, 0.97]) { const x = Math.round(LW * f) - 3; rect(c, x, top, 6, hz - top, wood); rect(c, x + 1, top, 1, hz - top, '#8a5a34'); rect(c, x + 5, top, 1, hz - top, '#2e1a0e'); }
        rect(c, 0, hz - 3, LW, 3, '#2e1a0e');
      },
      floor(c, LW, H, hz) {
        gradient(c, 0, LW, hz, H, ['#b39a5e', '#cdb67a', '#d9c48a']);
        seams(c, LW, hz, H, 5, '#9c8650'); converging(c, LW, hz, H, 22, '#2f3f2a');
        alpha(c, 0.2, () => ellipse(c, LW / 2, hz + 6, LW * 0.2, 3, '#8ad0ff'));
      },
      setup(r, LW, H, hz) {
        const pal = { shirts: ['#ece5d4', '#ece5d4', '#ece5d4', '#1b2a6a'], pants: ['#ece5d4', '#1b1b1b', '#1b2a6a'] };
        const top = Math.round(H * 0.08) + 8;
        return {
          crowd: makeCrowd(r, LW * 0.26, LW * 0.42, hz - 1, Math.max(2, Math.round(LW / 50)), pal, crowdH(H)).concat(makeCrowd(r, LW * 0.58, LW * 0.74, hz - 1, Math.max(2, Math.round(LW / 50)), pal, crowdH(H))),
          leds: [0.1, 0.22, 0.78, 0.9].flatMap(f => particles(r, 8, r => ({ x: Math.round(LW * f) - 4 + ri(r, 0, 7), y: top + 3 + 4 * ri(r, 0, Math.max(1, Math.floor((hz - top - 6) / 4))), col: pickOf(r, ['#39ff5a', '#24e6ff', '#ffd200', '#39ff5a']) }))),
          cubes: particles(r, 3, (r, i) => ({ x: Math.round(LW * (0.3 + 0.2 * i)), y: Math.round(H * (0.3 + r() * 0.1)), ph: r() * 6 })),
        };
      },
      anim(c, W, H, hz, t, st, X, still) {
        for (const l of st.leds) if (still || noise('led' + l.x + ':' + l.y, Math.floor(t * 3)) > 0.3) px(c, X(l.x, DEPTH.mid), l.y, l.col);
        for (const q of st.cubes) {
          const y = q.y + (still ? 0 : Math.round(Math.sin(t * 1.5 + q.ph) * 2));
          alpha(c, 0.7, () => cube(c, X(q.x, DEPTH.far), y, 3, '#bff4ff', '#24a6d0', '#16608a'));
        }
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
