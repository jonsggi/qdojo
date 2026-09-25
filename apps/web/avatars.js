/* QDOJO fighters, v4 preview: original 48×48 arcade fighters and 64×64
 * collectible cards, drawn in the spirit of early-90s arcade fighting games
 * (athletic proportions, hard 3–4 tone shading, dark outlines) without copying
 * any existing character.
 *
 * Pure and deterministic: an identity string (usually a 64-hex fighter id) maps
 * to byte-identical SVG on every runtime. No randomness, clock, network,
 * external assets, gradients or filters. Every trait comes from its own hash
 * domain, so traits are independent of each other. Appearance never depends on
 * rank, results or the wallet owner.
 *
 * Bodies are built from a small skeleton: shoulders, elbows and fists; hips,
 * knees and ankles. Poses move joints by whole pixels, so every frame stays
 * crisp. Each body part is a pixel mask shaded from the upper right (shadow
 * band, base, light, highlight), hand details are added on top, overlapping
 * parts get a dark separation line and the whole figure a 1px ink outline.
 * `frames`/`strip` return frame sequences for the clips below; playback lives
 * in anim.js, not here.
 */
'use strict';
const QDojoAvatars = (() => {
  const SIZE = 48, N = SIZE * SIZE, CARD = 64, CX = 23;
  const VERSION = 'qdojo-fighters-v4-preview';
  const INK = '#140f1a';
  const cache = new Map();

  // ---- Deterministic picks ------------------------------------------------
  function hash(s) {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
    return h;
  }
  function mix(h) { // murmur3 finaliser: FNV alone leaves the low bits weak
    h ^= h >>> 16; h = Math.imul(h, 0x7feb352d) >>> 0;
    h ^= h >>> 15; h = Math.imul(h, 0x846ca68b) >>> 0;
    return (h ^ (h >>> 16)) >>> 0;
  }
  const roll = (id, domain) => mix(hash('qdojo/fighter/v4/' + domain + '/' + id));
  const pick = (id, domain, n) => roll(id, domain) % n;
  function weighted(id, domain, weights) {
    let r = roll(id, domain) % weights.reduce((a, b) => a + b, 0);
    for (let i = 0; i < weights.length; i++) { if (r < weights[i]) return i; r -= weights[i]; }
    return 0;
  }

  // ---- Colour ---------------------------------------------------------------
  // Ramps have five steps: deep, shadow, base, light, highlight. Shadows turn
  // toward violet and lights toward warm yellow, as hand-picked ramps do.
  function toHsl(hex) {
    const n = parseInt(hex.slice(1), 16);
    const r = (n >> 16) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2;
    if (mx === mn) return [0, 0, l];
    const d = mx - mn, s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
    const h = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return [h * 60, s, l];
  }
  function toHex(h, s, l) {
    s = Math.max(0, Math.min(1, s)); l = Math.max(0, Math.min(1, l));
    const c = (1 - Math.abs(2 * l - 1)) * s, hp = (((h % 360) + 360) % 360) / 60;
    const x = c * (1 - Math.abs((hp % 2) - 1)), m = l - c / 2;
    const [r, g, b] = hp < 1 ? [c, x, 0] : hp < 2 ? [x, c, 0] : hp < 3 ? [0, c, x] : hp < 4 ? [0, x, c] : hp < 5 ? [x, 0, c] : [c, 0, x];
    return '#' + [r, g, b].map(v => Math.round((v + m) * 255).toString(16).padStart(2, '0')).join('');
  }
  function mixHex(a, b, t) {
    const p = parseInt(a.slice(1), 16), q = parseInt(b.slice(1), 16);
    return '#' + [16, 8, 0].map(k => Math.round(((p >> k) & 255) * (1 - t) + ((q >> k) & 255) * t).toString(16).padStart(2, '0')).join('');
  }
  const ramps = new Map();
  function ramp(base) {
    if (ramps.has(base)) return ramps.get(base);
    const [h, s, l] = toHsl(base);
    const turn = (to, most) => { const d = ((to - h + 540) % 360) - 180; return h + Math.max(-most, Math.min(most, d)); };
    const r = [
      toHex(turn(260, 26), s * 0.75 + 0.1, l * 0.34),
      toHex(turn(260, 14), s * 0.92 + 0.05, l * 0.64),
      base,
      toHex(turn(55, 8), s * 0.95, l + (1 - l) * 0.3),
      toHex(turn(55, 14), s * 0.8, l + (1 - l) * 0.58),
    ];
    ramps.set(base, r);
    return r;
  }
  const backs = new Map();
  function back(r) { // one step darker for the far arm and leg
    const k = r.join();
    if (!backs.has(k)) backs.set(k, [r[0], r[0], r[1], r[2], r[3]]);
    return backs.get(k);
  }

  // ---- Trait tables -----------------------------------------------------------
  // Twelve original archetypes in the spirit of the classic arcade roster.
  const KITS = [
    { name: 'Dojo striker', backdrop: 'Sunset dojo', head: ['None', 'Hachimaki', 'Hachimaki'] },
    { name: 'Street brawler', backdrop: 'Midnight rooftop', head: ['None', 'Headband', 'Backwards cap', 'Bandana'] },
    { name: 'Circuit sentinel', backdrop: 'Reactor chamber', head: ['Visor helmet', 'Crested helmet', 'Cyber eye'] },
    { name: 'Neon shinobi', backdrop: 'Moon gate', head: ['Wrapped hood', 'Hood and faceplate'] },
    { name: 'Sumo wrestler', backdrop: 'Clay ring', head: ['None'] },
    { name: 'Pro wrestler', backdrop: 'Arena lights', head: ['None', 'None', 'Flame mask', 'Star mask', 'Stripe mask'] },
    { name: 'Commando', backdrop: 'Jungle base', head: ['None', 'Beret', 'Bandana', 'Headband'] },
    { name: 'Kung-fu master', backdrop: 'Lantern market', head: ['None', 'None', 'Headband'] },
    { name: 'Capoeira dancer', backdrop: 'Harbour dusk', head: ['None', 'Bandana', 'Headband'] },
    { name: 'Mountain mystic', backdrop: 'Mountain temple', head: ['None', 'Forehead mark'] },
    { name: 'Prize boxer', backdrop: 'Boxing gym', head: ['None', 'None', 'Head guard'] },
    { name: 'Muay Thai fighter', backdrop: 'River stadium', head: ['None', 'Mongkhon'] },
  ];
  const STANCES = ['Low guard', 'Boxer guard', 'Power stance'];
  const BUILDS = ['Lean', 'Standard', 'Heavy'];
  // Hand-picked skin ramps: deep, shadow, base, light, highlight.
  const SKINS = [
    ['Porcelain', ['#7a4640', '#cf9480', '#f1c5ab', '#fde0cc', '#fff2e6']],
    ['Rosy', ['#6a3530', '#bd735f', '#e2a488', '#f4c5ab', '#ffe0cf']],
    ['Honey', ['#5c321c', '#aa6a3a', '#d79c66', '#ecbd88', '#f9dcb0']],
    ['Olive', ['#4a2f1d', '#8f613a', '#bd8b58', '#d6ab77', '#edcda0']],
    ['Bronze', ['#42241a', '#80492b', '#aa6e45', '#c79062', '#e3b48a']],
    ['Umber', ['#301a10', '#5f3722', '#865233', '#a6714b', '#c4926b']],
    ['Deep', ['#22110b', '#472717', '#673c26', '#865639', '#a57353']],
    ['Ebony', ['#190c08', '#341b11', '#4d2e1e', '#6a442f', '#8a5e46']],
  ];
  const HAIRS = [
    ['Jet black', '#231f2a'], ['Dark brown', '#4b2e21'], ['Chestnut', '#7c4424'], ['Auburn', '#a4432a'],
    ['Golden', '#d9a843'], ['Platinum', '#e3dcc8'], ['Silver', '#a4a8b6'], ['Crimson', '#b8283a'],
    ['Steel blue', '#3d63a8'], ['Rose', '#d8628e'],
  ];
  const EYES = [['Brown', '#5e3622'], ['Hazel', '#8a6a2c'], ['Green', '#3b7f45'], ['Blue', '#3a6fc0'], ['Grey', '#6e7788'], ['Amber', '#c98a1c']];
  // Curated outfit palettes: main cloth, second cloth, trim. Warm and natural.
  const PALETTES = [
    ['Classic white', '#e9e3d3', '#34303c', '#c8343c'],
    ['Crimson', '#b3303a', '#2e2830', '#e6b44a'],
    ['Royal blue', '#2f4fa6', '#e6ddc6', '#e0a22e'],
    ['Jungle green', '#3e7a3c', '#5a4030', '#e2b24a'],
    ['Sunset orange', '#dd6d28', '#3a2a28', '#f2d266'],
    ['Midnight', '#2c3050', '#4c4c62', '#d8423c'],
    ['Tan leather', '#c49c66', '#5a3a26', '#b83a2e'],
    ['Royal purple', '#693a8c', '#2a2436', '#e6c04a'],
    ['Teal', '#2a8584', '#243039', '#e8d8a2'],
    ['Black and gold', '#2c2b32', '#1a191f', '#e0b042'],
    ['Rose', '#d25c86', '#3a2a3a', '#f2e2d2'],
    ['Sky', '#4a8fce', '#efebe0', '#c83242'],
    ['Olive drab', '#6b7042', '#3b3a2a', '#c9a352'],
    ['Maroon', '#7a2b31', '#2a2024', '#e6c67a'],
  ];
  const ACCENTS = ['#e8403c', '#e8b830', '#3a8ae8', '#48b058', '#f0ece0', '#a050c8'];
  const MALE_HAIR = ['Crew cut', 'Spiked', 'Swept back', 'Flat-top', 'Topknot', 'Mohawk', 'Shaggy', 'Tied-back', 'Buzzed'];
  const FEMALE_HAIR = ['Combat bob', 'High ponytail', 'Long braid', 'Sidecut', 'Twin buns', 'Pixie', 'Long loose'];
  const EXPRESSIONS = ['Determined', 'Fierce', 'Calm', 'Grinning'];
  const FACIAL = ['None', 'Stubble', 'Moustache', 'Goatee', 'Full beard', 'Chin strap'];
  const SCARS = ['None', 'Brow scar', 'Cheek scar', 'Nose bandage'];
  const GLOVES = ['Bare fists', 'Tape wraps', 'Fingerless gloves', 'Leather gloves'];
  const SHOULDERS = ['None', 'Shoulder guard', 'Studded pad'];
  const SASHES = ['Plain', 'Striped', 'Checked', 'Stitched'];
  const MARKINGS = ['None', 'Arm tattoo', 'Face paint', 'Cheek stripes', 'Chest tattoo'];
  const PATTERNS = ['Plain', 'Trim', 'Stripes', 'Emblem'];
  const EMBLEMS = ['Sun disc', 'Tomoe', 'Diamond', 'Wave', 'Crane'];
  const SIGNATURES = ['jab', 'kick', 'bow', 'win'];

  // Per-kit wardrobe. arms: what covers the upper arm; hands: forced glove.
  const BARE_CHEST = new Set([1, 4, 5, 8, 9, 10, 11]);
  const FACE_COVERED = new Set([3]);
  const GLOVE_FREE = new Set([0, 1, 3, 5, 6, 8]);
  const PAD_KITS = new Set([1, 3, 6]);

  // A character-art trait, never an inference about the wallet's owner. Same
  // hash domain as v1-v3 so a fighter keeps its character variant.
  function isFemale(identity) { return Boolean((hash('qdojo/fighter/character/v1/' + identity) >>> 24) & 1); }

  const looks = new Map();
  function look(identity) {
    if (looks.has(identity)) return looks.get(identity);
    const id = identity;
    const kit = pick(id, 'kit', KITS.length), K = KITS[kit];
    const female = isFemale(id);
    let build = weighted(id, 'build', [3, 5, 3]);
    if (kit === 4) build = 2;
    if (kit === 9) build = 0;
    if (kit === 5 && build === 0) build = 1;
    const headgear = K.head[pick(id, 'headgear', K.head.length)];
    const masked = kit === 2 && headgear !== 'Cyber eye' || kit === 3 || /mask$/.test(headgear);
    let hairstyle;
    if (masked) hairstyle = female ? 'Armoured braid' : null;
    else if (kit === 4) hairstyle = 'Topknot';
    else if (kit === 9) hairstyle = female ? 'Long braid' : 'Bald';
    else hairstyle = female ? FEMALE_HAIR[pick(id, 'hairstyle', FEMALE_HAIR.length)] : MALE_HAIR[pick(id, 'hairstyle', MALE_HAIR.length)];
    const faceShown = !masked && !FACE_COVERED.has(kit);
    const armsBare = kit !== 2 && kit !== 0;
    let marking = MARKINGS[weighted(id, 'marking', [6, 2, 2, 2, 2])];
    if ((marking === 'Face paint' || marking === 'Cheek stripes') && !faceShown) marking = 'None';
    if (marking === 'Chest tattoo' && !(BARE_CHEST.has(kit) && !female)) marking = 'None';
    if (marking === 'Arm tattoo' && !armsBare) marking = 'None';
    const gloves = kit === 2 ? 'Armoured gauntlets' : kit === 10 ? 'Boxing gloves' : kit === 11 ? 'Hand wraps'
      : kit === 7 ? 'Spiked bracelets' : GLOVE_FREE.has(kit) ? GLOVES[pick(id, 'gloves', GLOVES.length)] : 'Bare fists';
    const shoulders = kit === 2 ? 'Pauldron' : PAD_KITS.has(kit) ? SHOULDERS[weighted(id, 'shoulders', [5, 3, 2])] : 'None';
    const pattern = PATTERNS[pick(id, 'pattern', PATTERNS.length)];
    const pal = PALETTES[pick(id, 'palette', PALETTES.length)];
    const skin = pick(id, 'skin', SKINS.length);
    const hair = pick(id, 'hair', HAIRS.length);
    const L = {
      kit, K, female, build, headgear, hairstyle, faceShown, marking, gloves, shoulders, pattern,
      stance: pick(id, 'stance', 3), skin, hair, palette: pal[0],
      eyes: pick(id, 'eyes', EYES.length),
      expression: pick(id, 'expression', EXPRESSIONS.length),
      facial: female || !faceShown ? 0 : weighted(id, 'facial', [8, 3, 2, 2, 2, 2]),
      scar: faceShown ? weighted(id, 'scar', [7, 2, 2, 2]) : 0,
      sash: pick(id, 'sash', SASHES.length),
      emblem: pick(id, 'emblem', EMBLEMS.length),
      accent: ACCENTS[pick(id, 'accent', ACCENTS.length)],
      S: SKINS[skin][1], H: ramp(HAIRS[hair][1]), E: ramp(EYES[pick(id, 'eyes', EYES.length)][1]),
      Mn: ramp(pal[1]), Sc: ramp(pal[2]), Tr: ramp(pal[3]),
      Ac: ramp(ACCENTS[pick(id, 'accent', ACCENTS.length)]),
      Mt: ramp(mixHex(pal[1], '#9aa3b5', 0.72)),
    };
    if (looks.size >= 512) looks.delete(looks.keys().next().value);
    looks.set(identity, L);
    return L;
  }

  function traits(identity) {
    identity = String(identity || '');
    const L = look(identity);
    const band = ['Hachimaki', 'Headband', 'Bandana', 'Mongkhon'].includes(L.headgear);
    const hairShown = L.hairstyle && L.hairstyle !== 'Bald';
    return Object.freeze({
      archetype: L.K.name, stance: STANCES[L.stance], character: L.female ? 'Female' : 'Male',
      build: BUILDS[L.build], outfit: L.Mn[2], palette: L.palette,
      skin: L.S[2], skinTone: SKINS[L.skin][0],
      headgear: L.headgear, hairstyle: L.hairstyle,
      hair: hairShown ? L.H[2] : null, hairColour: hairShown ? HAIRS[L.hair][0] : null,
      headband: band, eyes: EYES[L.eyes][0],
      expression: L.faceShown ? EXPRESSIONS[L.expression] : 'Hidden',
      facialHair: FACIAL[L.facial], scar: SCARS[L.scar],
      gloves: L.gloves, shoulders: L.shoulders, sash: SASHES[L.sash], markings: L.marking,
      pattern: L.pattern, emblem: L.pattern === 'Emblem' ? EMBLEMS[L.emblem] : null,
      accent: L.accent, backdrop: L.K.backdrop, signature: signature(identity),
    });
  }

  // ---- Masks and the pixel canvas -------------------------------------------
  // A mask is a bitmap plus its bounding box, so painting a part only visits
  // the pixels near it.
  // The bitmap has a 4px margin so neighbour lookups never leave the array.
  const PAD = 4, W = SIZE + 2 * PAD;
  const at = (x, y) => (y + PAD) * W + x + PAD;
  // Masks are pooled: sprite() is synchronous, so it resets the pool on entry
  // and each mask is cleared (within its old bounding box) when handed out.
  const pool = [];
  let pooled = 0;
  function M() {
    if (pooled === pool.length) pool.push({ a: new Uint8Array(W * W), x0: SIZE, y0: SIZE, x1: -1, y1: -1 });
    const m = pool[pooled++];
    for (let y = m.y0; y <= m.y1; y++) m.a.fill(0, at(m.x0, y), at(m.x1, y) + 1);
    m.x0 = SIZE; m.y0 = SIZE; m.x1 = -1; m.y1 = -1;
    return m;
  }
  function put(m, x, y) {
    if (x < 0 || y < 0 || x >= SIZE || y >= SIZE) return;
    m.a[at(x, y)] = 1;
    if (x < m.x0) m.x0 = x; if (x > m.x1) m.x1 = x; if (y < m.y0) m.y0 = y; if (y > m.y1) m.y1 = y;
  }
  const each = (m, f) => { for (let y = m.y0; y <= m.y1; y++) for (let x = m.x0; x <= m.x1; x++) if (m.a[at(x, y)]) f(x, y, at(x, y)); };
  function rect(m, x, y, w, h) { for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) put(m, i, j); return m; }
  function rows(m, ox, oy, list) {
    list.forEach((s, j) => { if (s) for (let i = s[0]; i <= s[1]; i++) put(m, ox + i, oy + j); });
    return m;
  }
  function cap(m, x0, y0, x1, y1, r) { // a thick line with round ends
    const dx = x1 - x0, dy = y1 - y0, l2 = dx * dx + dy * dy || 1, rr = r * r;
    const xa = Math.floor(Math.min(x0, x1) - r), xb = Math.ceil(Math.max(x0, x1) + r);
    const ya = Math.floor(Math.min(y0, y1) - r), yb = Math.ceil(Math.max(y0, y1) + r);
    for (let y = ya; y <= yb; y++) for (let x = xa; x <= xb; x++) {
      let t = ((x - x0) * dx + (y - y0) * dy) / l2;
      t = t < 0 ? 0 : t > 1 ? 1 : t;
      const ex = x0 + dx * t - x, ey = y0 + dy * t - y;
      if (ex * ex + ey * ey <= rr) put(m, x, y);
    }
    return m;
  }
  function ell(m, cx, cy, rx, ry) {
    for (let y = Math.floor(cy - ry); y <= Math.ceil(cy + ry); y++) for (let x = Math.floor(cx - rx); x <= Math.ceil(cx + rx); x++) {
      const u = (x - cx) * ry, v = (y - cy) * rx;
      if (u * u + v * v <= rx * rx * ry * ry) put(m, x, y);
    }
    return m;
  }
  function tri(m, tx, ty, x0, x1, by) { // from a tip to a horizontal base
    const n = Math.abs(by - ty) || 1, dir = by >= ty ? 1 : -1;
    for (let k = 0; k <= n; k++) {
      const a = Math.round(tx + (x0 - tx) * k / n), b = Math.round(tx + (x1 - tx) * k / n);
      for (let i = Math.min(a, b); i <= Math.max(a, b); i++) put(m, i, ty + k * dir);
    }
    return m;
  }
  const and = (m, n) => { each(m, (x, y, i) => { m.a[i] &= n.a[i]; }); return m; };
  const minus = (m, n) => { each(n, (x, y, i) => { m.a[i] = 0; }); return m; };
  const or = (m, n) => { each(n, (x, y) => put(m, x, y)); return m; };

  function canvas() {
    const col = new Array(N).fill(null), rp = new Array(N).fill(null), lv = new Int8Array(N), own = new Int16Array(N);
    let part = 0;
    const ok = (x, y) => x >= 0 && y >= 0 && x < SIZE && y < SIZE;
        // Light from the upper right: a shadow band on the left and bottom, a lit
    // edge on the top and right, a highlight on the upper-right corners.
    // Overlapping parts can ask for a dark separation line on what they cover.
    function fill(m, r, o = {}) {
      part++;
      const a = m.a, band = o.band || 1, lo = o.min || 0, hi = o.max == null ? 4 : o.max, flat = o.flat, clip = o.clip;
      if (o.sep) {
        for (let y = m.y0; y <= m.y1; y++) for (let x = m.x0, p = at(x, y); x <= m.x1; x++, p++) {
          if (!a[p]) continue;
          if (x > 0 && !a[p - 1]) edge(y * SIZE + x - 1);
          if (x < SIZE - 1 && !a[p + 1]) edge(y * SIZE + x + 1);
          if (y > 0 && !a[p - W]) edge(y * SIZE + x - SIZE);
          if (y < SIZE - 1 && !a[p + W]) edge(y * SIZE + x + SIZE);
        }
      }
      for (let y = m.y0; y <= m.y1; y++) for (let x = m.x0, p = at(x, y), i = y * SIZE + x; x <= m.x1; x++, p++, i++) {
        if (!a[p] || (clip && !col[i])) continue;
        let l;
        if (flat != null) l = flat;
        else {
          if (!a[p - 1]) l = 1;
          else {
            const up = a[p - W], right = a[p + 1];
            if (!up && !right) l = 4;
            else if (!up || !right) l = 3;
            else if (!a[p + W]) l = 1;
            else if (band > 1 && (!a[p - 2] || !a[p + 2 * W])) l = 1;
            else if (band > 2 && !a[p - 3]) l = 1;
            else l = 2;
          }
          l = l < lo ? lo : l > hi ? hi : l;
        }
        col[i] = r[l]; rp[i] = r; lv[i] = l; own[i] = part;
      }
    }
    function edge(j) {
      if (col[j] && own[j] !== part) { col[j] = rp[j] ? rp[j][0] : INK; lv[j] = 0; }
    }
    function set(x, y, r, l = 2) {
      if (!ok(x, y)) return;
      const i = y * SIZE + x;
      if (typeof r === 'string') { col[i] = r; rp[i] = null; lv[i] = 2; } else { col[i] = r[l]; rp[i] = r; lv[i] = l; }
      own[i] = part;
    }
    // Shift an existing pixel within its own ramp: folds, creases, muscle.
    function tone(x, y, l) {
      if (!ok(x, y)) return;
      const i = y * SIZE + x;
      if (rp[i]) { col[i] = rp[i][l]; lv[i] = l; }
    }
    function shift(x, y, d) {
      if (!ok(x, y)) return;
      const i = y * SIZE + x;
      if (rp[i]) { const l = Math.max(0, Math.min(4, lv[i] + d)); col[i] = rp[i][l]; lv[i] = l; }
    }
    const filled = (x, y) => ok(x, y) && col[y * SIZE + x] !== null;
    const levelAt = (x, y) => ok(x, y) ? lv[y * SIZE + x] : -1;
    function out() {
      const o = col.slice();
      for (let y = 0, i = 0; y < SIZE; y++) for (let x = 0; x < SIZE; x++, i++) {
        if (col[i]) continue;
        if ((x > 0 && col[i - 1]) || (x < SIZE - 1 && col[i + 1]) || (y > 0 && col[i - SIZE]) || (y < SIZE - 1 && col[i + SIZE])) o[i] = INK;
      }
      // One path per colour, with horizontal pixel runs.
      const paths = new Map();
      for (let y = 0; y < SIZE; y++) for (let x = 0; x < SIZE;) {
        const color = o[y * SIZE + x];
        if (!color) { x++; continue; }
        let end = x + 1;
        while (end < SIZE && o[y * SIZE + end] === color) end++;
        const w = end - x;
        paths.set(color, (paths.get(color) || '') + `M${x} ${y}h${w}v1h-${w}z`);
        x = end;
      }
      return [...paths].map(([color, d]) => `<path fill="${color}" d="${d}"/>`).join('');
    }
    return { fill, set, tone, shift, filled, levelAt, out };
  }

  // ---- Skeleton -------------------------------------------------------------
  // Body sizes per build: shoulder and waist half-widths, limb radii.
  const BODY = [
    { sh: 8, waist: 5, hip: 3, upper: 2.6, fore: 2.4, thigh: 3.0, shin: 2.6, neck: 2.2, fist: 0, belly: 0 },
    { sh: 9, waist: 6, hip: 3, upper: 3.0, fore: 2.8, thigh: 3.4, shin: 2.9, neck: 2.6, fist: 1, belly: 0 },
    { sh: 11, waist: 8, hip: 4, upper: 3.6, fore: 3.2, thigh: 4.1, shin: 3.4, neck: 3.2, fist: 1, belly: 3 },
  ];
  // Arm states: [elbow dx, dy, fist dx, dy, hand], relative to the shoulder;
  // positive x is toward the opponent. guard is indexed by the stance trait.
  const LEAD = {
    guard: [[3, 7, 8, 4], [3, 7, 6, -1], [4, 6, 9, 0]],
    jab: [7, 0, 12, -1], cross: [7, 0, 12, -1], wind: [1, 7, 2, -1], up: [3, -7, 5, -13], down: [1, 7, 1, 13],
    block: [5, 3, 6, -6], grab: [6, 2, 12, 1, 'open'], pull: [-1, 6, -5, 1], knee: [2, 8, 1, 15, 'open'],
    fling: [3, 6, 7, 11, 'open'],
  };
  const REAR = {
    guard: [[-2, 8, 5, 6], [-1, 8, 6, 1], [-4, 6, -2, 11]],
    jab: [7, 1, 13, 0], cross: [7, 1, 13, 0], wind: [-2, 8, 5, 3], up: [-1, -7, -1, -14], down: [-1, 7, -1, 13],
    block: [5, 6, 11, 0], grab: [6, 3, 13, 2, 'open'], pull: [-3, 6, -7, 3], knee: [2, 8, 3, 15, 'open'],
    fling: [-3, 5, -7, 9, 'open'],
  };
  // Leg states: [knee dx, knee y, ankle dx, ankle y, foot] for rear and lead,
  // on the ground (x relative to the body's centre line).
  const LEGS = {
    plant: [[-8, 37, -11, 43, 'flat'], [9, 36, 10, 43, 'flat']],
    chamber: [[-4, 37, -6, 43, 'flat'], [10, 28, 7, 36, 'tuck']],
    kick: [[-4, 37, -6, 43, 'flat'], [12, 28, 19, 27, 'kick']],
    kneel: [[-4, 44, -11, 44, 'back'], [8, 35, 9, 43, 'flat']],
    crouch: [[-10, 39, -9, 43, 'flat'], [11, 38, 11, 43, 'flat']],
    step: [[-9, 39, -14, 43, 'flat'], [12, 35, 13, 43, 'flat']],
  };

  // ---- Clips ----------------------------------------------------------------
  // dx/dy move everything above the hips, hx/hy add to the head, jump lifts the
  // whole sprite. `hold` clips end on their last frame instead of returning to
  // idle. Every clip starts and ends near the guard so cuts between them read.
  const DOWN = { lead: 'down', rear: 'down' };
  const UP = { lead: 'up' };
  const BLOCK = { lead: 'block', rear: 'block' };
  const GRAB = { lead: 'grab', rear: 'grab', legs: 'step' };
  const PULL = { lead: 'pull', rear: 'pull' };
  const KNEE = { lead: 'knee', rear: 'knee', dx: 1, dy: 3, hx: 2, hy: 2 };
  const CROUCH = { legs: 'crouch', dy: 7, hy: 1 };
  const CLIPS = Object.freeze({
    idle: { fps: 5, frames: [{}, {}, { dy: 1 }, { dy: 1, blink: true }, { dy: 1 }, {}, { dy: 1 }, {}] },
    jab: { fps: 12, frames: [{ lead: 'wind' }, { lead: 'jab', dx: 1 }, { lead: 'jab', dx: 1 }, { lead: 'jab' }, { lead: 'wind' }, {}] },
    kick: { fps: 12, frames: [{ legs: 'chamber', dx: -1 }, { legs: 'kick', dx: -2, hx: -1 }, { legs: 'kick', dx: -2, hx: -1 }, { legs: 'kick', dx: -2, hx: -1 }, { legs: 'chamber', dx: -1 }, {}] },
    hit: { fps: 12, frames: [{ dx: -1, hx: -1, blink: true }, { dx: -2, hx: -3, hy: -1, blink: true, lead: 'fling', rear: 'fling' }, { dx: -2, hx: -3, hy: -1, blink: true, lead: 'fling', rear: 'fling' }, { dx: -1, hx: -1, blink: true }, {}] },
    bow: { fps: 6, frames: [DOWN, { ...DOWN, dx: 1, dy: 1, hx: 1, hy: 1 }, { ...DOWN, dx: 1, dy: 2, hx: 3, hy: 3, blink: true }, { ...DOWN, dx: 1, dy: 2, hx: 3, hy: 3, blink: true }, { ...DOWN, dx: 1, dy: 2, hx: 3, hy: 3, blink: true }, { ...DOWN, dx: 1, dy: 2, hx: 3, hy: 3, blink: true }, { ...DOWN, dx: 1, dy: 1, hx: 1, hy: 1 }, DOWN, {}] },
    win: { fps: 8, frames: [{ lead: 'wind' }, { ...UP, dy: -1 }, { ...UP, dy: -1, jump: 1 }, { ...UP, dy: -1, jump: 1, blink: true }, { ...UP, dy: -1 }, UP, { ...UP, dy: 1 }, { ...UP, blink: true }, UP, {}] },
    lose: { fps: 8, hold: true, frames: [{ dx: -1, hx: -1, blink: true }, { ...DOWN, dx: -1, dy: 1, hx: -1, hy: 1, blink: true }, { ...DOWN, dy: 5, hy: 2, blink: true, legs: 'kneel' }, { ...DOWN, dy: 5, hy: 2, blink: true, legs: 'kneel' }] },
    block: { fps: 10, frames: [{ ...BLOCK, dx: -1, hx: -1 }, { ...BLOCK, dx: -2, dy: 1, hx: -1, hy: 1 }, { ...BLOCK, dx: -2, dy: 1, hx: -1, hy: 1 }, { ...BLOCK, dx: -2, dy: 1, hx: -1, hy: 1, blink: true }, { ...BLOCK, dx: -1, hx: -1 }, {}] },
    duck: { fps: 10, frames: [{ legs: 'crouch', dy: 3 }, CROUCH, CROUCH, { ...CROUCH, blink: true }, CROUCH, { legs: 'crouch', dy: 3 }, {}] },
    throw: { fps: 10, frames: [{ ...GRAB, dx: 2, hx: 1 }, { ...GRAB, dx: 3, hx: 1 }, { ...GRAB, dx: 3, hx: 1 }, { ...PULL, dx: -1, hx: -2 }, { ...PULL, dx: -2, hx: -2, hy: -1 }, { ...PULL, dx: -1, hx: -1 }, {}] },
    recover: { fps: 6, frames: [{ ...KNEE, blink: true }, KNEE, { ...KNEE, blink: true }, { ...DOWN, dx: 1, dy: 2, hx: 1, hy: 1 }, { dy: 1 }, {}] },
    exhausted: { fps: 5, frames: [KNEE, { ...KNEE, dy: 4, hy: 3, blink: true }, KNEE, { ...KNEE, dy: 4, hy: 3 }, KNEE, {}] },
  });

  // ---- Heads ----------------------------------------------------------------
  // Three-quarter heads facing right: 12 rows, ear on the left, nose on the right.
  const HEAD = {
    m: [[3, 8], [1, 10], [0, 11], [0, 11], [0, 12], [0, 12], [0, 13], [0, 12], [1, 12], [1, 11], [2, 11], [4, 9]],
    f: [[3, 8], [1, 10], [0, 11], [0, 11], [0, 12], [0, 12], [0, 13], [0, 12], [1, 12], [1, 11], [3, 10], [5, 8]],
    h: [[3, 8], [1, 10], [0, 11], [0, 11], [0, 12], [0, 12], [0, 13], [0, 12], [0, 12], [0, 12], [1, 11], [3, 10]],
  };
  // Hair silhouettes in head coordinates, rows from `top`.
  const HAIR = {
    'Crew cut': { top: -2, rows: [[4, 8], [2, 10], [0, 11], [-1, 11], [-1, 11], [-1, 7], [-1, 3], [-1, 2], [0, 1]] },
    'Spiked': { top: -2, rows: [[4, 8], [2, 10], [0, 11], [-1, 11], [-1, 11], [-1, 7], [-1, 3], [-1, 2], [0, 1]],
      spikes: [[-4, -2, -1, 2, 1], [0, -4, 1, 5, 0], [5, -4, 3, 8, -1], [10, -4, 8, 11, 0], [-4, 4, -1, -1, 1], [13, 2, 10, 12, 2]] },
    'Swept back': { top: -3, rows: [[4, 10], [2, 12], [1, 13], [0, 12], [-1, 12], [-2, 11], [-2, 6], [-2, 3], [-1, 2], [0, 1]] },
    'Flat-top': { top: -4, rows: [[0, 10], [0, 11], [0, 11], [-1, 11], [-1, 11], [-1, 11], [-1, 11], [-1, 6], [-1, 3], [-1, 2]] },
    'Topknot': { top: -1, rows: [[2, 10], [0, 11], [-1, 11], [-1, 10], [-1, 5], [-1, 3], [-1, 2]], bun: [3, -2, 3, 1.6] },
    'Mohawk': { top: 0, rows: [], crest: true },
    'Shaggy': { top: -3, rows: [[3, 10], [1, 12], [-1, 13], [-1, 13], [-2, 13], [-2, 12], [-2, 9], [-2, 4], [-2, 3], [-2, 3], [-1, 2], [-1, 1]], tips: [[12, 4], [10, 4], [8, 3], [-2, 9], [0, 9]] },
    'Tied-back': { top: -1, rows: [[2, 10], [0, 11], [-1, 11], [-1, 11], [-1, 6], [-1, 3], [-1, 2]], tail: true },
    'Buzzed': { top: 0, rows: [], buzz: true },
    'Bald': { top: 0, rows: [] },
    'Combat bob': { top: -2, rows: [[4, 8], [2, 11], [0, 12], [-1, 12], [-1, 12], [-1, 9], [-1, 5], [-1, 4], [-1, 4], [-1, 4], [0, 4], [1, 4]] },
    'High ponytail': { top: -1, rows: [[2, 10], [0, 11], [-1, 11], [-1, 11], [-1, 7], [-1, 3], [-1, 2]], pony: true },
    'Long braid': { top: -1, rows: [[2, 10], [0, 11], [-1, 11], [-1, 11], [-1, 7], [-1, 3], [-1, 2]], braid: true },
    'Armoured braid': { top: 0, rows: [], braid: true },
    'Sidecut': { top: -3, rows: [[3, 10], [1, 12], [1, 13], [2, 13], [3, 13], [5, 13], [8, 12], [10, 12]], buzz: true },
    'Twin buns': { top: -1, rows: [[2, 10], [0, 11], [-1, 11], [-1, 11], [-1, 7], [-1, 3], [-1, 2]], buns: true },
    'Pixie': { top: -2, rows: [[3, 9], [1, 11], [-1, 12], [-1, 12], [-1, 12], [-1, 8], [-1, 3], [-1, 2], [0, 1]], tips: [[11, 4], [9, 4]] },
    'Long loose': { top: -2, rows: [[4, 8], [2, 11], [0, 12], [-1, 12], [-1, 12], [-1, 9], [-1, 5], [-1, 4], [-1, 4], [-1, 4], [0, 4], [1, 4]], long: true },
  };

  // ---- The sprite -------------------------------------------------------------
  function sprite(identity, pose = {}) {
    const L = look(identity), kit = L.kit, B = BODY[L.build];
    pooled = 0;
    const { dx = 0, dy = 0, hx = 0, hy = 0, jump = 0, lead = 'guard', rear = null, legs = 'plant', blink = false } = pose;
    const c = canvas();
    const bx = dx, by = dy - jump, gy = -jump;
    const HX = CX - 6 + dx + hx, HY = 4 + dy + hy - jump;
    const { S, H, E, Mn, Sc, Tr, Ac, Mt } = L;
    const female = L.female;
    const WRAP = ramp('#e6e0d2'), LEATHER = ramp('#5a3a2a'), DARK = ramp('#2c2a34'), GOLD = ramp('#d8a837');
    const WHITE = ['#6d6a7c', '#bdb8c2', '#f2eee6', '#ffffff', '#ffffff'];
    const hd = (x, y, r, l) => c.set(HX + x, HY + y, r, l);

    const legState = LEGS[legs] || LEGS.plant;
    const hips = [[CX - B.hip + bx, 31 + by], [CX + B.hip + 1 + bx, 31 + by]];
    const legJoints = side => {
      const s = legState[side], spread = (L.build - 1) * (side ? 1 : -1);
      return { hip: hips[side], knee: [CX + s[0] + spread, s[1] + gy], ankle: [CX + s[2] + spread, s[3] + gy], foot: s[4] };
    };
    const shoulders = [[CX - B.sh + 2 + bx, 18 + by], [CX + B.sh - 1 + bx, 18 + by]];

    // Which ramp covers what, per kit.
    const pants = { 0: Mn, 1: Sc, 2: Sc, 3: Mn, 6: Mn, 7: Sc, 8: Mn }[kit] || S;
    const shorts = { 4: Mn, 5: Mn, 9: Mn, 10: Mn, 11: Mn }[kit] || null;

    // Back layer: long hair, tails, scarves.
    backHair();
    if (kit === 3) { // shinobi scarf tails stream behind
      const m = M();
      cap(m, CX - 2 + bx, 16 + by, CX - 9 + bx, 18 + by, 1.6); cap(m, CX - 9 + bx, 18 + by, CX - 14 + bx, 17 + by, 1.2);
      cap(m, CX - 3 + bx, 17 + by, CX - 10 + bx, 22 + by, 1.3); cap(m, CX - 10 + bx, 22 + by, CX - 13 + bx, 25 + by, 1);
      c.fill(m, Tr, { band: 1 });
    }

    leg(0); leg(1);
    torso();
    waist();
    neck();
    arm(0);
    head();
    arm(1);
    return c.out();

    // ---------------------------------------------------------------- legs
    function leg(side) {
      const j = legJoints(side), R = side ? (x => x) : back;
      const { hip, knee, ankle } = j;
      const baggy = kit === 0 || kit === 3 || kit === 7 || kit === 8 ? 0.5 : 0;
      const thigh = cap(M(), hip[0], hip[1], knee[0], knee[1], B.thigh + baggy);
      const shin = cap(M(), knee[0], knee[1], ankle[0], ankle[1], B.shin + baggy * (kit === 8 ? 1.6 : 1));
      const whole = or(M(), thigh); or(whole, shin);
      c.fill(whole, R(pants), { band: 2, sep: side === 1 });
      const along = (t, a = knee, b = ankle) => [Math.round(a[0] + (b[0] - a[0]) * t), Math.round(a[1] + (b[1] - a[1]) * t)];
      if (pants !== S) {
        // Cloth folds behind the knee and at the hip crease.
        const k = along(0, knee, knee);
        c.tone(k[0] - 1, k[1], 1); c.tone(k[0], k[1] + 1, 1); c.tone(k[0] + 1, k[1] - 1, 3);
        const t = along(0.5, hip, knee);
        c.tone(t[0], t[1], 1); c.tone(t[0] + 1, t[1] + 1, 1);
        if (kit === 6) camo(whole);
        if (kit === 8) { const a = along(0.8); c.tone(a[0] - 1, a[1], 3); }
      } else {
        // Muscle: quad highlight and calf line on bare legs.
        const q = along(0.45, hip, knee); c.tone(q[0] + 1, q[1] - 1, 3); c.tone(q[0] + 2, q[1], 3);
        const kc = along(0.35); c.tone(kc[0] - 2, kc[1], 1);
      }
      // Shin gear per kit.
      if (kit === 2) { // armoured shin and knee plate
        const g = cap(M(), ...along(0.15), ...along(0.9), B.shin + 0.3); c.fill(g, R(Mt), { band: 1, sep: true });
        c.fill(ell(M(), knee[0] + 1, knee[1], 2.2, 2), R(Mt), { sep: true });
      } else if (kit === 3 || kit === 9) { // wrapped shins
        const g = cap(M(), ...along(0.35), ...along(0.95), B.shin + 0.2); c.fill(g, R(kit === 3 ? Sc : WRAP), { band: 1 });
        for (let t = 0.4; t < 0.95; t += 0.18) { const p = along(t); c.tone(p[0], p[1], 1); c.tone(p[0] - 1, p[1] - 1, 1); }
      } else if (kit === 5 || kit === 10 || kit === 6) { // boots up the shin
        const g = cap(M(), ...along(kit === 5 ? 0.25 : 0.5), ...ankle, B.shin + 0.4);
        c.fill(g, R(kit === 6 ? LEATHER : kit === 5 ? Sc : DARK), { band: 1, sep: true });
        if (kit === 5) { c.fill(ell(M(), knee[0] + 1, knee[1], 2.4, 2.2), R(Tr), { sep: true }); }
        for (let t = 0.6; t < 0.95; t += 0.2) { const p = along(t); c.set(p[0] + 1, p[1], kit === 10 ? WHITE : R(Tr), 3); }
      } else if (kit === 11) { // ankle wraps
        c.fill(cap(M(), ...along(0.8), ...ankle, B.shin + 0.2), R(WRAP), { band: 1 });
      } else if (kit === 7) { // white socks over the ankle
        c.fill(cap(M(), ...along(0.82), ...ankle, B.shin), R(WRAP), { band: 1 });
      }
      foot(j, side, R);
    }

    function camo(m) {
      each(m, (x, y) => {
        const k = (x * 7 + y * 13 + ((x * y) >> 2)) % 11;
        if (k === 0 || k === 1) c.shift(x, y, -1);
        else if (k === 5) c.set(x, y, Sc, 1);
      });
    }

    function foot(j, side, R) {
      const [ax, ay] = j.ankle, m = M(), w = L.build === 2 ? 1 : 0;
      let sole = null;
      if (j.foot === 'kick') { rect(m, ax - 1, ay - 2, 5 + w, 5); rect(m, ax + 2, ay - 3, 3, 1); sole = [ax + 4 + w, ay - 3, 1, 6]; }
      else if (j.foot === 'tuck') { rect(m, ax - 2, ay - 1, 5, 4); rect(m, ax + 2, ay + 2, 2, 2); }
      else if (j.foot === 'back') { rect(m, ax - 4, ay - 1, 6, 3); }
      else { rows(m, ax, ay - 1, [[-2, 2], [-2, 3], [-3, 4 + w], [-3, 5 + w], [-3, 5 + w]]); sole = [ax - 3, ay + 3, 9 + w, 1]; }
      const bare = kit === 0 || kit === 4 || kit === 8 || kit === 9 || kit === 11;
      const shoe = bare ? S : kit === 1 ? WRAP : kit === 2 ? Mt : kit === 6 ? LEATHER : kit === 5 ? Sc : kit === 10 ? DARK : DARK;
      c.fill(m, R(shoe), { band: 1, sep: true });
      if (bare) {
        if (j.foot === 'flat') { c.tone(ax + 3, ay + 3, 1); c.tone(ax + 1, ay + 3, 1); c.tone(ax - 1, ay, 3); }
        if (kit === 9) { c.set(ax - 2, ay, GOLD, 2); c.set(ax, ay, GOLD, 3); }
        return;
      }
      if (sole) for (let yy = sole[1]; yy < sole[1] + sole[3]; yy++) for (let xx = sole[0]; xx < sole[0] + sole[2]; xx++) {
        if (c.filled(xx, yy)) c.set(xx, yy, kit === 1 ? R(WRAP) : R(DARK), kit === 1 ? 3 : 0);
      }
      if (kit === 1 && j.foot === 'flat') { c.set(ax, ay + 1, R(Tr), 2); c.set(ax + 1, ay + 1, R(Tr), 2); c.set(ax + 2, ay + 2, R(Tr), 2); c.set(ax - 1, ay + 2, R(Tr), 3); }
      if (kit === 3 && j.foot === 'flat') { c.tone(ax + 3, ay + 2, 0); c.tone(ax + 3, ay + 3, 0); }
    }

    // --------------------------------------------------------------- torso
    function torsoMask() {
      const m = M(), sh = B.sh, w = B.waist;
      const spans = [[-3, 4], [-(sh - 2), sh - 1], [-sh, sh], [-sh, sh + 1], [-sh, sh + 1], [-sh, sh + 1], [-sh, sh + 1], [-sh, sh + 1],
        [-(sh - 1), sh + 1], [-(sh - 1), sh], [-(sh - 2), sh - 1], [-w, w + 1], [-w, w + 1], [-w, w + 1], [-w, w + 1], [-w, w + 1], [-w, w + 1]];
      spans.forEach(([a, b], k) => {
        const y = 15 + k;
        let r = b;
        if (B.belly && y >= 24 && y <= 30) r += y >= 26 && y <= 29 ? B.belly : B.belly - 1;
        for (let x = a; x <= r; x++) put(m, CX + x + bx, y + by);
      });
      return m;
    }

    function muscles(ramp_) {
      const x0 = CX + bx, y0 = by, t = (x, y, l) => c.tone(x0 + x, y0 + y, l);
      if (L.build === 2 && kit === 4) { // sumo: heavy chest and a round belly
        for (let x = -5; x <= 7; x++) t(x, 22 + (x > 1 ? 0 : 0), 1);
        t(1, 21, 1); t(1, 20, 1);
        for (let x = 5; x <= 10; x++) t(x, 25, 3);
        t(9, 26, 4); t(10, 27, 3); t(4, 27, 0); t(4, 28, 1);
        for (let x = -3; x <= 8; x++) t(x, 30, 1);
        return;
      }
      // Pecs: a lit upper edge, a shadow under, a sternum line.
      for (let x = -5; x <= 7; x++) if (x !== 1) t(x, 22, 1);
      t(-6, 21, 1); t(8, 21, 1);
      for (let y = 18; y <= 21; y++) t(1, y, 1);
      for (let x = 3; x <= 6; x++) t(x, 18, 3);
      t(4, 19, 4); t(5, 19, 3); t(-2, 18, 3); t(-1, 18, 3);
      // Abs: a centre line and three rows of blocks, the right side lit.
      for (let y = 23; y <= 29; y++) t(1, y, 1);
      for (const y of [24, 26, 28]) { t(-1, y, 1); t(0, y, 1); t(2, y, 1); t(3, y, 1); }
      for (const y of [23, 25, 27]) { t(2, y, 3); t(3, y, 3); }
      t(-3, 25, 1); t(-3, 26, 1); t(-3, 27, 1); t(5, 24, 1); t(5, 25, 1);
      if (L.build === 0) for (const y of [20, 22, 24]) { t(-4, y, 1); t(-3, y, 1); }
    }

    function torso() {
      const m = torsoMask(), x0 = CX + bx, y0 = by;
      const t = (x, y, l) => c.tone(x0 + x, y0 + y, l), s = (x, y, r, l) => c.set(x0 + x, y0 + y, r, l);
      const bareMale = BARE_CHEST.has(kit) && !female;
      const skinTop = BARE_CHEST.has(kit) || kit === 6 || kit === 0;
      // Shorts/pelvis first, then the torso over it.
      const pel = rect(M(), CX - B.waist + bx, 28 + by, B.waist * 2 + 2, 6);
      c.fill(pel, shorts || pants, { band: 2 });
      if (skinTop) { c.fill(m, S, { band: 2 }); if (bareMale || kit === 0 || kit === 6) muscles(S); }
      if (kit === 0) { // karate gi: jacket with a deep V and crossed lapels
        const g = minus(torsoMask(), rows(M(), x0, y0 + 15, [[-2, 4], [-1, 4], [-1, 4], [0, 3], [0, 3], [1, 3], [1, 2], [1, 2], [2, 2]]));
        if (female) c.fill(rows(M(), x0, y0 + 16, [[-1, 4], [-1, 4], [0, 3], [0, 3], [1, 3]]), Sc, { band: 1 });
        c.fill(g, Mn, { band: 2 });
        for (let k = 0; k <= 12; k++) { const x = -3 + Math.round(k * 0.45), y = 15 + k; s(x, y, L.pattern === 'Trim' ? Tr : Mn, 3); t(x - 1, y, 1); }
        for (let k = 0; k <= 5; k++) { s(5 - Math.round(k * 0.3), 15 + k, L.pattern === 'Trim' ? Tr : Mn, 3); }
        t(-5, 26, 1); t(-4, 27, 1); t(6, 25, 1); t(7, 26, 1); t(-6, 20, 1); t(-6, 21, 1);
      } else if (kit === 1) { // open vest over the chest, sports top for women
        if (female) c.fill(rows(M(), x0 - 4, y0 + 19, [[0, 11], [0, 11], [0, 11], [0, 11], [1, 10]]), Sc, { band: 1 });
        const v = and(torsoMask(), rect(M(), 0, 0, SIZE, SIZE));
        minus(v, rect(M(), x0 - 2, y0 + 15, 8, 17));
        c.fill(v, Mn, { band: 2 });
        for (let y = 15; y <= 31; y++) { t(-3, y, 3); t(6, y, 1); }
        s(-4, 16, Mn, 4); s(-3, 16, Mn, 4); s(7, 16, Mn, 4);
      } else if (kit === 2) { // cyborg: undersuit, chest plate, core light
        c.fill(m, Sc, { band: 2 });
        const p = rows(M(), x0, y0 + 17, [[-6, 7], [-7, 8], [-7, 8], [-7, 8], [-6, 8], [-6, 7], [-5, 6], [-3, 5]]);
        c.fill(p, Mt, { band: 1 });
        for (let x = -5; x <= 6; x++) t(x, 21, 1);
        t(1, 18, 1); t(1, 19, 1); t(1, 20, 1);
        c.fill(ell(M(), x0 + 3, y0 + 23, 1.6, 1.6), Ac, { flat: 3 }); s(3, 22, Ac, 4);
        for (const y of [26, 28, 30]) for (let x = -3; x <= 4; x++) t(x, y, 1);
      } else if (kit === 3) { // shinobi: wrapped tunic, crossing strap
        c.fill(m, Mn, { band: 2 });
        for (let k = -8; k <= 8; k += 4) for (let y = 23; y <= 31; y++) { const x = k + (y - 23); if (x > -B.waist && x < B.waist) t(x, y, 1); }
        const strap = cap(M(), x0 - 7, y0 + 17, x0 + 6, y0 + 29, 1.1);
        c.fill(and(strap, torsoMask()), Sc, { band: 1 });
        s(0, 23, Tr, 3); s(1, 23, Tr, 2);
      } else if (kit === 4) { // sumo
        if (female) c.fill(rows(M(), x0 - 8, y0 + 19, [[0, 18], [0, 19], [0, 19], [0, 19], [1, 18]]), Sc, { band: 1 });
      } else if (kit === 5 && female) { // wrestling singlet
        const g = minus(torsoMask(), rows(M(), x0 - 11, y0 + 15, [[0, 9], [0, 7], [0, 5], [0, 4]]));
        minus(g, rows(M(), x0 + 5, y0 + 15, [[0, 9], [1, 9], [3, 9], [4, 9]]));
        c.fill(g, Mn, { band: 2 });
      } else if (kit === 6) { // commando: tank top, dog tags
        const g = minus(torsoMask(), rows(M(), x0 - 12, y0 + 15, [[0, 9], [0, 7], [0, 5], [0, 4]]));
        minus(g, rows(M(), x0 + 4, y0 + 15, [[0, 9], [2, 9], [3, 9], [4, 9]]));
        minus(g, rows(M(), x0 - 1, y0 + 15, [[0, 4], [0, 4], [1, 3]]));
        c.fill(g, Mn, { band: 2 });
        t(-4, 27, 1); t(-3, 28, 1); t(5, 26, 1);
        s(2, 18, WHITE, 1); s(2, 19, WHITE, 1); s(2, 20, Mt, 3); s(3, 20, Mt, 2); s(2, 21, Mt, 2); s(3, 21, Mt, 1);
      } else if (kit === 7) { // kung-fu: sleeveless jacket, mandarin collar, frog buttons
        c.fill(m, Mn, { band: 2 });
        for (let x = -3; x <= 4; x++) s(x, 15, Tr, x > 1 ? 3 : 2);
        for (let y = 16; y <= 29; y++) t(3, y, 1);
        for (const y of [18, 21, 24, 27]) { s(3, y, Tr, 3); s(4, y, Tr, 2); s(2, y, Tr, 1); }
        t(-5, 25, 1); t(-4, 26, 1);
      } else if (kit === 8 && female) { // capoeira crop top
        c.fill(rows(M(), x0 - 8, y0 + 17, [[1, 17], [0, 18], [0, 18], [0, 18], [0, 18], [1, 17], [2, 16]]), Sc, { band: 1 });
      } else if (kit === 9) { // mystic: bare lean chest, prayer beads
        if (female) c.fill(rows(M(), x0 - 7, y0 + 17, [[1, 15], [0, 16], [0, 16], [0, 16], [0, 16], [1, 15]]), Mn, { band: 1 });
        const beads = [[-4, 16], [-4, 18], [-3, 20], [-2, 22], [0, 23], [2, 24], [4, 23], [6, 22], [7, 20], [7, 18], [6, 16]];
        for (const [x, y] of beads) { s(x, y, LEATHER, 2); s(x + 1, y, LEATHER, 3); s(x, y + 1, LEATHER, 1); }
        s(2, 25, Tr, 3); s(3, 25, Tr, 2); s(2, 26, Tr, 1); s(3, 26, Tr, 1);
      } else if ((kit === 10 || kit === 11) && female) { // tank / sports top
        c.fill(rows(M(), x0 - 8, y0 + 17, [[2, 16], [0, 18], [0, 18], [0, 18], [0, 18], [0, 18], [1, 17], [2, 16]]), kit === 10 ? Mn : Sc, { band: 1 });
      } else if (kit === 8 || kit === 5) {
        // bare chest, already shaded
      }
      if (L.marking === 'Chest tattoo') {
        for (const [x, y] of [[-4, 19], [-3, 18], [-2, 19], [-3, 20], [-4, 21], [-2, 21], [-3, 22]]) s(x, y, INK === INK ? S : S, 0);
      }
      // Outfit pattern on the main garment: trim edge, side stripes, emblem.
      const garment = kit === 0 || kit === 3 || kit === 6 || kit === 7 || (kit === 1) || (kit === 2);
      if (garment && L.pattern === 'Stripes') {
        for (let y = 17; y <= 30; y++) { s(-B.sh + 2 + (y > 25 ? 3 : 0), y, Tr, y % 2 ? 2 : 3); }
      } else if (garment && L.pattern === 'Emblem') {
        emblem(x0 - 5, y0 + 20);
      }
    }

    function emblem(x, y) {
      const E_ = [
        [[1, 0], [2, 0], [0, 1], [1, 1], [2, 1], [3, 1], [0, 2], [1, 2], [2, 2], [3, 2], [1, 3], [2, 3]],
        [[1, 0], [2, 0], [0, 1], [3, 1], [0, 2], [2, 2], [3, 2], [1, 3], [2, 3]],
        [[1, 0], [0, 1], [2, 1], [1, 2], [0, 1], [1, 1]],
        [[0, 1], [1, 0], [2, 1], [3, 0], [0, 2], [2, 2], [1, 3], [3, 3]],
        [[0, 0], [3, 0], [1, 1], [2, 1], [1, 2], [2, 2], [1, 3], [0, 2], [3, 2]],
      ][L.emblem];
      for (const [a, b] of E_) c.set(x + a, y + b, Tr, b === 0 ? 3 : 2);
    }

    // --------------------------------------------------------------- waist
    function waist() {
      const x0 = CX + bx, y0 = by, w = B.waist + (B.belly ? 1 : 0);
      const s = (x, y, r, l) => c.set(x0 + x, y0 + y, r, l);
      let r = Tr, top = 28, h = 2;
      if (kit === 0) r = L.sash % 2 ? Sc : DARK;
      if (kit === 1 || kit === 6) { r = LEATHER; }
      if (kit === 2) { r = DARK; h = 3; }
      if (kit === 4) { r = Mn; top = 27; h = 5; }
      if (kit === 5 || kit === 10 || kit === 11) { r = Tr; h = kit === 5 ? 1 : 3; }
      if (kit === 7) { h = 3; }
      if (kit === 8) { h = 1; top = 29; }
      if (kit === 9) { r = Tr; }
      const m = rect(M(), x0 - w, y0 + top, w * 2 + 2 + (B.belly ? 1 : 0), h);
      c.fill(m, r, { band: 1, sep: true });
      // Sash patterns.
      const sash = SASHES[L.sash];
      for (let x = -w; x <= w + 1; x++) for (let y = top; y < top + h; y++) {
        if (sash === 'Striped' && (x + 40) % 3 === 0) c.shift(x0 + x, y0 + y, 1);
        if (sash === 'Checked' && (x + y + 40) % 2 === 0 && h > 1) c.shift(x0 + x, y0 + y, -1);
        if (sash === 'Stitched' && y === top + (h > 2 ? 1 : 0) && x % 2 === 0) c.shift(x0 + x, y0 + y, 2);
      }
      if (kit === 0 || kit === 3 || kit === 7) { // knot and hanging tails
        s(3, top, r, 3); s(4, top, r, 3); s(3, top + 1, r, 1); s(4, top + 1, r, 2);
        const tails = cap(M(), x0 + 3, y0 + top + h, x0 + 2, y0 + top + h + 5, 0.8);
        cap(tails, x0 + 5, y0 + top + h, x0 + 6, y0 + top + h + 4, 0.8);
        c.fill(tails, r, { band: 1, sep: true });
      }
      if (kit === 1 || kit === 6) { s(3, top, Mt, 4); s(4, top, Mt, 3); s(3, top + 1, Mt, 2); s(4, top + 1, Mt, 1); }
      if (kit === 4) { // mawashi front and hanging cords
        const f = rect(M(), x0 + 1, y0 + top + h, 5, 3); c.fill(f, Mn, { band: 1, sep: true });
        for (let x = 0; x <= 7; x += 2) for (let y = top + h; y < top + h + 6; y++) if (!c.filled(x0 + x, y0 + y) || y > top + h + 2) c.set(x0 + x, y0 + y, Sc, y === top + h + 5 ? 1 : 2);
      }
      if (kit === 8) { // capoeira cord: knot and two ends
        const e = cap(M(), x0 + 4, y0 + top + 1, x0 + 3, y0 + top + 6, 0.6); cap(e, x0 + 5, y0 + top + 1, x0 + 6, y0 + top + 5, 0.6);
        c.fill(e, Tr, { band: 1 });
      }
      if (kit === 10 || kit === 11) { // trunk leg openings with a stripe
        s(-w, top + 3, Tr, 2); s(w + 1, top + 3, Tr, 3);
      }
      if ((kit === 5 || kit === 10 || kit === 11 || kit === 4) && L.pattern === 'Emblem') emblem(x0 + 1, y0 + top + h + 1);
    }

    function neck() {
      const m = cap(M(), CX + 1 + bx, 18 + by, CX + 1 + dx + hx, 14 + dy + hy - jump, B.neck);
      const r = kit === 3 ? Mn : kit === 2 && L.headgear !== 'Cyber eye' ? Sc : S;
      c.fill(m, r, { band: 2 });
      if (r === S) { c.tone(CX + 1 + bx - 1, 15 + by, 1); }
      if (kit === 6) { // dog tag chain
        for (let x = -2; x <= 3; x++) c.set(CX + x + bx, 16 + by + (x > 0 ? 1 : 0), WHITE, 1);
      }
    }

    // ---------------------------------------------------------------- arms
    function arm(side) {
      const state = side ? lead : rear == null ? 'guard' : rear;
      const table = side ? LEAD : REAR;
      let spec = typeof state === 'number' ? table.guard[state % 3] : table[state] || table.guard[L.stance];
      if (state === 'guard' || spec === table.guard) spec = table.guard[L.stance];
      const sh = shoulders[side], R = side ? (x => x) : back;
      const el = [sh[0] + spec[0], sh[1] + spec[1]], fh = [sh[0] + spec[2], sh[1] + spec[3]];
      const cyber = kit === 2 && side === 1;
      const upperR = cyber ? Mt : kit === 2 ? Sc : kit === 3 ? S : S;
      const foreR = cyber || kit === 2 ? Mt : S;
      const upper = cap(M(), sh[0], sh[1], el[0], el[1], B.upper);
      c.fill(upper, R(upperR), { band: 2, sep: true });
      // Deltoid cap and biceps highlight on bare arms.
      if (upperR === S) {
        c.shift(sh[0], sh[1] - 1, 1);
        const mid = [Math.round((sh[0] + el[0]) / 2), Math.round((sh[1] + el[1]) / 2)];
        c.tone(mid[0] + 1, mid[1], 3); c.tone(mid[0] + 1, mid[1] - 1, 3);
        if (L.marking === 'Arm tattoo' && side === 1) {
          for (let k = -1; k <= 1; k++) c.set(mid[0] + k, mid[1] + 1 + (k & 1), S, 0);
        }
      }
      if (kit === 0) { // gi sleeve over the shoulder
        const e = [Math.round(sh[0] + (el[0] - sh[0]) * 0.55), Math.round(sh[1] + (el[1] - sh[1]) * 0.55)];
        c.fill(cap(M(), sh[0], sh[1], e[0], e[1], B.upper + 0.7), R(Mn), { band: 2, sep: true });
      }
      if (kit === 11 || kit === 9) { // prajiad cord or gold armband
        const e = [Math.round(sh[0] + (el[0] - sh[0]) * 0.6), Math.round(sh[1] + (el[1] - sh[1]) * 0.6)];
        c.fill(cap(M(), e[0], e[1], e[0], e[1], B.upper + 0.3), R(kit === 9 ? GOLD : Tr), { band: 1 });
      }
      const fore = cap(M(), el[0], el[1], fh[0], fh[1], B.fore);
      c.fill(fore, R(foreR), { band: 1, sep: true });
      if (foreR === S) { const m2 = [Math.round((el[0] * 2 + fh[0]) / 3), Math.round((el[1] * 2 + fh[1]) / 3)]; c.tone(m2[0] + 1, m2[1] - 1, 3); }
      if (cyber) { c.tone(el[0], el[1], 0); c.set(el[0] + 1, el[1], Ac, 3); }
      // Wrist gear.
      const near = t => [Math.round(fh[0] + (el[0] - fh[0]) * t), Math.round(fh[1] + (el[1] - fh[1]) * t)];
      const wrist = (r, t0, t1, extra = 0.3) => c.fill(cap(M(), ...near(t0), ...near(t1), B.fore + extra), R(r), { band: 1, sep: true });
      const g = L.gloves;
      if (g === 'Tape wraps' || g === 'Hand wraps') wrist(WRAP, 0.25, 0.45, 0.2);
      if (g === 'Leather gloves' || g === 'Fingerless gloves') wrist(g === 'Leather gloves' ? LEATHER : DARK, 0.25, 0.4, 0.4);
      if (g === 'Spiked bracelets') {
        wrist(DARK, 0.25, 0.5, 0.5);
        const p = near(0.37); c.set(p[0], p[1] - 3, WHITE, 3); c.set(p[0] + 2, p[1] - 2, WHITE, 2); c.set(p[0] - 2, p[1] + 2, WHITE, 1);
      }
      if (kit === 3) wrist(Sc, 0.25, 0.75, 0.2);
      if (kit === 5) wrist(WRAP, 0.25, 0.4, 0.2);
      // Shoulder pads sit on top of the upper arm.
      if (L.shoulders !== 'None') {
        if (side === 1 || L.shoulders === 'Pauldron') {
          const p = ell(M(), sh[0] + (side ? 1 : -1), sh[1] - 1, 3.4, 2.6);
          c.fill(p, R(L.shoulders === 'Studded pad' ? LEATHER : Mt), { band: 1, sep: true });
          if (L.shoulders === 'Studded pad') { c.set(sh[0] - 1, sh[1] - 2, WHITE, 3); c.set(sh[0] + 2, sh[1] - 1, WHITE, 2); }
          if (L.shoulders === 'Pauldron') c.set(sh[0] + (side ? 2 : -2), sh[1] - 2, Ac, 3);
        }
      }
      hand(fh, spec[4] || 'fist', side, R);
    }

    function hand([hx0, hy0], type, side, R) {
      const g = L.gloves, heavy = B.fist;
      const cover = g === 'Boxing gloves' ? Tr : g === 'Leather gloves' ? LEATHER : g === 'Armoured gauntlets' ? Mt : g === 'Tape wraps' || g === 'Hand wraps' ? WRAP : S;
      if (g === 'Boxing gloves') {
        const m = ell(M(), hx0 + 0.5, hy0, 4, 3.6);
        c.fill(m, R(Tr), { band: 2, sep: true });
        c.set(hx0 - 3, hy0 + 2, R(WRAP), 2); c.set(hx0 - 2, hy0 + 3, R(WRAP), 2);
        c.set(hx0 + 1, hy0 - 2, R(Tr), 4); c.tone(hx0, hy0 + 1, 1); c.tone(hx0 - 1, hy0 + 1, 1);
        return;
      }
      if (type === 'open') {
        const m = rows(M(), hx0, hy0 - 2, [[-1, 3], [-2, 4 + heavy], [-2, 4 + heavy], [-2, 3]]);
        rect(m, hx0 - 1, hy0 - 3, 2, 1);
        c.fill(m, R(cover === WRAP ? S : cover), { band: 1, sep: true });
        c.tone(hx0 + 1, hy0 - 1, 1); c.tone(hx0 + 2, hy0, 1); c.tone(hx0 + 1, hy0 + 1, 1);
        return;
      }
      const m = rows(M(), hx0, hy0 - 3, [[-2, 2 + heavy], [-3, 3 + heavy], [-3, 3 + heavy], [-3, 3 + heavy], [-3, 3 + heavy], [-2, 2 + heavy]]);
      c.fill(m, R(cover), { band: 1, sep: true });
      // Knuckles facing forward and up: a highlight row, finger creases, a thumb.
      const k = hx0 + heavy;
      c.tone(k - 1, hy0 - 3, 3); c.tone(k + 1, hy0 - 3, 4); c.tone(k + 2, hy0 - 2, 4);
      c.tone(k + 1, hy0 - 1, 1); c.tone(k + 2, hy0 - 1, 1); c.tone(k + 1, hy0 + 1, 1); c.tone(k + 2, hy0 + 1, 1);
      c.tone(hx0 - 2, hy0, 3); c.tone(hx0 - 1, hy0, 3); c.tone(hx0 - 2, hy0 + 1, 1); c.tone(hx0 - 1, hy0 + 1, 1);
      if (g === 'Fingerless gloves') { for (let x = hx0 - 1; x <= k + 3; x++) c.set(x, hy0 - 3, R(S), 3); c.set(k + 3, hy0 - 2, R(S), 2); }
    }

    // ---------------------------------------------------------------- head
    function backHair() {
      const style = HAIR[L.hairstyle];
      if (!style) return;
      const m = M(), o = (x, y) => [HX + x, HY + y];
      if (style.pony) { cap(m, ...o(1, -2), ...o(-3, -1), 1.8); cap(m, ...o(-3, -1), ...o(-5, 5), 1.9); cap(m, ...o(-5, 5), ...o(-4, 11), 1.3); }
      if (style.tail) { cap(m, ...o(-1, 3), ...o(-3, 8), 1.5); cap(m, ...o(-3, 8), ...o(-3, 12), 1.1); }
      if (style.braid) for (let k = 0; k < 7; k++) ell(m, HX - 1 - (k > 3 ? 1 : 0), HY + 7 + k * 2.2, 1.6, 1.3);
      if (style.long) rows(m, HX, HY + 3, [[-2, 3], [-3, 3], [-3, 3], [-3, 3], [-4, 3], [-4, 2], [-4, 2], [-4, 2], [-4, 2], [-4, 2], [-4, 2], [-4, 1], [-4, 1], [-4, 1], [-3, 0], [-3, 0]]);
      c.fill(m, H, { band: 2 });
      if (style.braid) for (let k = 0; k < 7; k++) { c.tone(HX - 1 - (k > 3 ? 1 : 0), HY + 8 + k * 2.2 | 0, 0); }
      if (style.long) for (let y = 6; y <= 17; y += 1) c.tone(HX - 1 - (y % 3), HY + y, 1);
      if (style.pony || style.tail) { c.set(HX + (style.pony ? 1 : -1), HY + (style.pony ? -2 : 3), Tr, 2); c.set(HX + (style.pony ? 0 : -2), HY + (style.pony ? -2 : 3), Tr, 3); }
    }

    function head() {
      const hm = rows(M(), HX, HY, female ? HEAD.f : L.build === 2 ? HEAD.h : HEAD.m);
      c.fill(hm, S, { band: 2 });
      face();
      hair();
      headgear();
    }

    function face() {
      const brow = L.hairstyle && L.hairstyle !== 'Bald' && L.hairstyle !== 'Armoured braid' ? H : S;
      // Ear, jaw line and cheekbone.
      hd(2, 5, S, 3); hd(3, 5, S, 2); hd(3, 6, S, 0); hd(2, 6, S, 2); hd(2, 7, S, 1);
      hd(5, 9, S, 1); hd(6, 10, S, 1); hd(10, 6, S, 3);
      // Nose and mouth.
      hd(13, 6, S, 3); hd(12, 7, S, 1); hd(13, 7, S, 1);
      const ex = L.expression;
      if (ex === 3) { hd(8, 9, S, 0); hd(9, 9, WHITE, 3); hd(10, 9, WHITE, 2); hd(11, 9, S, 0); hd(9, 10, S, 1); }
      else if (ex === 1) { hd(8, 9, S, 0); hd(9, 9, S, 0); hd(10, 9, S, 0); hd(8, 10, S, 1); hd(10, 8, S, 1); }
      else { hd(9, 9, S, 0); hd(10, 9, S, 0); hd(10, 10, S, 3); }
      if (female) { hd(9, 9, '#9e3c4e'); hd(10, 9, '#b8505e'); }
      // Brows by expression.
      const bl = brow === H ? 0 : 0;
      if (ex === 1) { hd(7, 3, brow, bl); hd(8, 4, brow, bl); hd(9, 4, brow, bl); hd(11, 4, brow, bl); hd(12, 3, brow, bl); }
      else if (ex === 2) { hd(7, 3, brow, bl); hd(8, 3, brow, bl); hd(9, 3, brow, bl); hd(11, 3, brow, bl); hd(12, 3, brow, bl); }
      else { hd(7, 4, brow, bl); hd(8, 4, brow, bl); hd(9, 4, brow, bl); hd(11, 4, brow, bl); hd(12, 4, brow, bl); }
      if (female) { hd(7, 4, S, 1); }
      // Eyes: white, iris, a lash for women; a lid line when blinking.
      if (blink || ex === 2) {
        hd(7, 5, S, 0); hd(8, 5, S, 0); hd(11, 5, S, 0);
        if (ex === 2 && !blink) { hd(8, 6, E, 1); hd(11, 6, E, 1); }
      } else {
        hd(7, 5, WHITE, 2); hd(8, 5, E, 1); hd(8, 6, S, 1); hd(7, 6, S, 1);
        hd(11, 5, E, 1); hd(12, 5, WHITE, 1);
        if (female) { hd(6, 5, INK); hd(6, 4, INK); }
      }
      if (!L.faceShown) return;
      // Facial hair.
      const f = L.facial, stub = mixHex(S[1], H[0], 0.3);
      if (f === 1) for (let y = 8; y <= 11; y++) for (let x = 4; x <= 12; x++) if ((x + y) % 2 === 0 && y + x > 13 && c.filled(HX + x, HY + y) && !(y === 9 && x >= 9)) hd(x, y, stub);
      if (f === 2 || f === 3) { hd(9, 8, H, 1); hd(10, 8, H, 2); hd(11, 8, H, 2); hd(12, 8, H, 3); }
      if (f === 3) { hd(9, 10, H, 1); hd(10, 10, H, 2); hd(10, 11, H, 1); hd(9, 11, H, 1); hd(8, 10, H, 1); }
      if (f === 4) {
        const bm = rows(M(), HX, HY + 7, [[3, 4], [3, 5], [4, 12], [4, 12], [5, 11], [6, 10]]);
        c.fill(bm, H, { band: 1 });
        hd(10, 9, S, 0); hd(11, 9, S, 0); hd(12, 9, H, 1);
      }
      if (f === 5) { hd(4, 8, H, 1); hd(5, 9, H, 1); hd(6, 10, H, 1); hd(7, 11, H, 1); hd(8, 11, H, 1); hd(9, 11, H, 2); }
      // Scars.
      if (L.scar === 1) { hd(9, 3, S, 4); hd(9, 4, S, 4); hd(9, 6, S, 4); hd(10, 5, S, 0); }
      if (L.scar === 2) { hd(9, 7, S, 4); hd(10, 8, S, 4); hd(8, 7, S, 0); }
      if (L.scar === 3) { hd(11, 6, WRAP, 3); hd(12, 6, WRAP, 2); hd(13, 6, WRAP, 2); }
      // Markings.
      if (L.marking === 'Face paint') { for (let x = 4; x <= 12; x++) { if (x < 7 || x === 9 || x === 10 || x === 12) hd(x, 5, Tr, x < 6 ? 1 : 2); hd(x, 6, Tr, x < 6 ? 0 : 1); } }
      if (L.marking === 'Cheek stripes') { hd(8, 7, Tr, 2); hd(8, 8, Tr, 1); hd(10, 7, Tr, 3); hd(10, 8, Tr, 2); }
    }

    function hair() {
      const st = HAIR[L.hairstyle];
      if (!st) return;
      if (L.hairstyle === 'Bald') { hd(5, 1, S, 4); hd(6, 1, S, 4); hd(4, 2, S, 3); return; }
      const hm = rows(M(), HX, HY + st.top, st.rows);
      if (st.spikes) for (const [tx, ty, a, b, y] of st.spikes) tri(hm, HX + tx, HY + ty, HX + a, HX + b, HY + y);
      if (st.bun) ell(hm, HX + st.bun[0], HY + st.bun[1], st.bun[2], st.bun[3]);
      if (st.buns) { ell(hm, HX + 0, HY - 1, 2.3, 2.1); ell(hm, HX + 7, HY - 2, 2.3, 2.1); }
      if (st.crest) { cap(hm, HX - 1, HY + 3, HX + 2, HY - 3, 1.6); cap(hm, HX + 2, HY - 3, HX + 8, HY - 4, 1.8); cap(hm, HX + 8, HY - 4, HX + 11, HY - 1, 1.4); }
      if (st.tips) for (const [x, y] of st.tips) put(hm, HX + x, HY + y);
      if (st.buzz) { // close-cropped: recolour the scalp
        const scalp = and(rows(M(), HX, HY, [[3, 8], [1, 10], [0, 11], [0, 7], [0, 3], [0, 2], [0, 1]]), rows(M(), HX, HY, HEAD.m));
        const stub = ramp(mixHex(S[2], H[2], 0.6));
        c.fill(scalp, stub, { band: 2 });
      }
      if (st.rows.length || st.spikes || st.crest || st.bun || st.buns) c.fill(hm, H, { band: 2 });
      // Strands: a few darker lines sweeping back, a glossy highlight up front.
      const t = (x, y, l) => { const xx = HX + x, yy = HY + y; if (xx >= 0 && yy >= 0 && xx < SIZE && yy < SIZE && hm.a[at(xx, yy)]) c.tone(xx, yy, l); };
      t(2, 0, 1); t(3, 1, 1); t(6, -1, 1); t(7, 0, 1); t(0, 2, 1); t(-1, 3, 0); t(4, 0, 3); t(8, -1, 4); t(9, -1, 3); t(5, -1, 4);
      if (st.bun) { c.set(HX + 2, HY - 1, Tr, 2); c.set(HX + 3, HY - 1, Tr, 3); }
      if (st.buns) { c.set(HX + 1, HY, Tr, 3); c.set(HX + 7, HY - 1, Tr, 3); }
    }

    function headgear() {
      const g = L.headgear;
      const base = rows(M(), HX, HY, female ? HEAD.f : L.build === 2 ? HEAD.h : HEAD.m);
      const st = HAIR[L.hairstyle];
      if (st && st.rows.length) or(base, rows(M(), HX, HY + st.top, st.rows));
      const band = (y0, h, r, tails) => {
        const m = and(rect(M(), HX - 2, HY + y0, 17, h), base);
        c.fill(m, r, { band: 1, sep: true });
        for (let x = 4; x <= 12; x += 3) c.tone(HX + x, HY + y0, 3);
        if (tails) {
          const t = cap(M(), HX - 1, HY + y0 + 1, HX - 6, HY + y0 + 3, 0.9);
          cap(t, HX - 1, HY + y0 + 1, HX - 5, HY + y0 + 6, 0.9);
          c.fill(t, r, { band: 1 });
        }
      };
      if (g === 'Hachimaki') band(2, 2, L.pattern === 'Trim' ? WRAP : Tr, true);
      else if (g === 'Headband') band(2, 1, Tr, kit !== 6);
      else if (g === 'Mongkhon') {
        band(2, 1, Tr, false);
        const t = cap(M(), HX - 1, HY + 2, HX - 5, HY - 3, 0.8); c.fill(t, Tr, { band: 1 });
        c.set(HX - 3, HY - 1, WRAP, 3); c.set(HX + 5, HY + 2, WRAP, 3);
      } else if (g === 'Bandana') {
        const m = and(rows(M(), HX, HY - 2, [[3, 9], [1, 11], [0, 12], [-1, 12], [-1, 12], [-1, 11]]), or(rect(M(), 0, 0, SIZE, HY + 4), M()));
        c.fill(m, Tr, { band: 1, sep: true });
        for (let x = 0; x <= 11; x += 3) c.tone(HX + x, HY + 1 + (x % 2), 4);
        const t = cap(M(), HX - 1, HY + 2, HX - 5, HY + 5, 0.9); cap(t, HX - 1, HY + 2, HX - 4, HY + 7, 0.8); c.fill(t, Tr, { band: 1 });
      } else if (g === 'Backwards cap') {
        const m = rows(M(), HX, HY - 3, [[3, 9], [1, 11], [0, 12], [-1, 12], [-1, 12], [-1, 12]]);
        rect(m, HX - 5, HY + 1, 5, 2);
        c.fill(m, Mn, { band: 2, sep: true });
        c.set(HX + 5, HY - 3, Tr, 3); c.set(HX + 12, HY + 2, Tr, 2);
      } else if (g === 'Beret') {
        const m = ell(M(), HX + 5, HY - 1, 7, 2.6); c.fill(m, Tr, { band: 1, sep: true });
        c.fill(rect(M(), HX - 1, HY + 1, 13, 1), LEATHER, { band: 1 });
        c.set(HX + 2, HY - 3, Tr, 4);
      } else if (g === 'Head guard') {
        const m = rows(M(), HX, HY - 2, [[3, 9], [1, 11], [0, 12], [-1, 12], [-1, 12], [-1, 7], [-1, 6], [-1, 6], [-1, 5], [0, 6], [0, 7], [1, 8], [2, 8]]);
        c.fill(m, Tr, { band: 2, sep: true });
        for (let y = 0; y <= 8; y += 2) c.tone(HX + 1, HY + y, 1);
        c.tone(HX + 6, HY + 5, 1); c.tone(HX + 6, HY + 6, 1);
      } else if (g === 'Forehead mark') {
        hd(9, 2, Tr, 2); hd(9, 3, Tr, 1);
      } else if (g === 'Visor helmet' || g === 'Crested helmet') {
        const m = rows(M(), HX, HY - 2, [[3, 9], [1, 11], [0, 12], [-1, 12], [-1, 12], [-1, 12], [-1, 13], [-1, 14], [-1, 13], [-1, 13], [0, 13], [1, 12], [2, 11], [4, 10]]);
        c.fill(m, Mt, { band: 2 });
        const v = rect(M(), HX + 5, HY + 4, 10, 2); c.fill(v, Ac, { band: 1, max: 3, min: 2 });
        hd(13, 4, WHITE, 3); hd(12, 4, Ac, 4);
        for (let x = 6; x <= 12; x++) c.tone(HX + x, HY + 7, 1);
        hd(8, 8, Mt, 0); hd(10, 8, Mt, 0); hd(12, 8, Mt, 0);
        hd(3, 5, Mt, 0); hd(3, 6, Mt, 0); hd(2, 5, Mt, 3);
        if (g === 'Crested helmet') { const cr = tri(M(), HX + 1, HY - 4, HX + 3, HX + 9, HY - 2); c.fill(cr, Tr, { band: 1, sep: true }); }
      } else if (g === 'Cyber eye') {
        const p = rows(M(), HX, HY + 2, [[8, 12], [7, 12], [7, 13], [8, 12]]);
        c.fill(p, Mt, { band: 1, sep: true });
        hd(11, 4, Ac, 4); hd(10, 4, Ac, 3); hd(11, 5, Ac, 2);
      } else if (kit === 3) { // shinobi hood; only the eyes show
        const m = rows(M(), HX, HY - 2, [[3, 9], [1, 11], [0, 12], [-1, 12], [-1, 12], [-1, 12], [-1, 13], [-1, 13], [-1, 14], [-1, 13], [-1, 13], [0, 13], [1, 12], [3, 11]]);
        minus(m, rect(M(), HX + 6, HY + 4, 8, 2));
        c.fill(m, Mn, { band: 2 });
        const low = and(rect(M(), HX + 4, HY + 6, 12, 6), m);
        c.fill(low, g === 'Hood and faceplate' ? Mt : Sc, { band: 1 });
        for (let x = 6; x <= 12; x += 2) c.tone(HX + x, HY + 8, 1);
        c.tone(HX + 4, HY + 3, 0); c.tone(HX + 2, HY + 1, 1);
        for (let x = 6; x <= 13; x++) c.tone(HX + x, HY + 3, 3);
      } else if (/mask$/.test(g)) { // wrestling mask
        const m = rows(M(), HX, HY - 1, [[3, 9], [1, 11], [0, 12], [-1, 12], [-1, 12], [-1, 13], [-1, 13], [-1, 14], [-1, 13], [-1, 13], [0, 12], [1, 12], [3, 10]]);
        c.fill(m, Mn, { band: 2 });
        // Eye and mouth holes ringed in trim.
        for (const [x, y] of [[6, 4], [7, 4], [8, 4], [9, 4], [6, 5], [9, 5], [6, 6], [7, 6], [8, 6], [9, 6], [10, 4], [11, 4], [12, 4], [10, 5], [12, 5], [10, 6], [11, 6], [12, 6]]) hd(x, y, Tr, 2);
        hd(7, 5, WHITE, 2); hd(8, 5, blink ? S : E, blink ? 0 : 1); hd(11, 5, blink ? S : E, blink ? 0 : 1);
        for (const [x, y] of [[9, 8], [10, 8], [11, 8], [12, 8], [9, 10], [10, 10], [11, 10], [12, 10], [9, 9], [12, 9]]) hd(x, y, Tr, 2);
        hd(10, 9, S, 0); hd(11, 9, S, 1);
        if (g === 'Flame mask') for (const [x, y, l] of [[5, 4, 3], [4, 3, 3], [3, 2, 2], [2, 3, 2], [5, 6, 2], [4, 7, 2], [3, 7, 1], [2, 8, 1], [5, 1, 3], [4, 0, 3]]) hd(x, y, Tr, l);
        if (g === 'Star mask') for (const [x, y] of [[3, 2], [2, 3], [3, 3], [4, 3], [3, 4], [1, 4], [5, 4], [2, 5], [4, 5]]) hd(x, y, Tr, 3);
        if (g === 'Stripe mask') for (let x = -1; x <= 12; x++) { hd(x, x < 4 ? 1 : x < 8 ? 0 : 1, Tr, 3); hd(x, x < 4 ? 2 : x < 8 ? 1 : 2, Tr, 2); }
        for (let y = 5; y <= 9; y += 2) { hd(-1, y, WRAP, 2); hd(0, y + 1, WRAP, 1); }
      }
    }
  }

  // ---- Collectible card -----------------------------------------------------
  // 64×64: a frame, a kit-specific pixel scene, the fighter at 1:1, and a blank
  // name plate. No names or live stats are baked in.
  function artwork(identity, body) {
    const L = look(identity), kit = L.kit, a = L.accent, seed = roll(identity, 'scene');
    const parts = [];
    const r = (x, y, w, h, c) => { if (w > 0 && h > 0) parts.push(`<path fill="${c}" d="M${x} ${y}h${w}v${h}h-${w}z"/>`); };
    const bands = (list, y0) => { let y = y0; for (const [c, h] of list) { r(2, y, 60, h, c); y += h; } return y; };
    const dither = (y, c) => { for (let x = 2 + (y & 1); x < 62; x += 2) r(x, y, 1, 1, c); };
    const half = (rad, y) => { let w = 0; while ((w + 1) * (w + 1) + y * y <= rad * rad + rad) w++; return w; };
    const circle = (cx, cy, rad, c) => { for (let y = -rad; y <= rad; y++) { const w = half(rad, y); r(cx - w, cy + y, w * 2 + 1, 1, c); } };
    const stars = (n, y1, c) => { let s = seed; for (let i = 0; i < n; i++) { s = mix(s + i); r(3 + s % 58, 3 + (s >>> 8) % (y1 - 3), 1, 1, c); } };
    r(0, 0, 64, 64, INK);
    const floorY = 50;
    if (kit === 0) { // Sunset dojo: striped sun over a wooden hall
      bands([['#3b2458', 8], ['#6a2f68', 6], ['#a8416a', 6], ['#e0645a', 6], ['#f39a58', 8], ['#f7c46a', 16]], 2);
      dither(16, '#a8416a'); dither(22, '#e0645a'); dither(28, '#f39a58'); dither(36, '#f7c46a');
      circle(44, 26, 10, '#ffe08a'); for (const y of [26, 29, 32, 34]) r(34, y, 21, 1, '#f39a58');
      r(2, 30, 60, 3, '#4a2a2a'); r(2, 33, 60, 17, '#6e3f2c');
      for (let x = 2; x < 62; x += 10) { r(x, 33, 1, 17, '#4a2a22'); r(x + 1, 36, 7, 11, '#e7d7b0'); r(x + 1, 41, 7, 1, '#b99a72'); r(x + 4, 36, 1, 11, '#b99a72'); }
      r(2, 28, 60, 2, '#8a3b2e'); r(2, 27, 60, 1, '#c95a3a');
      r(2, floorY, 60, 11, '#8a5a36'); for (let y = floorY + 2; y < 61; y += 3) r(2, y, 60, 1, '#6c4228');
    } else if (kit === 1) { // Midnight rooftop: skyline and water tower
      bands([['#101433', 20], ['#16193f', 12], ['#1e1f4c', 16]], 2); stars(18, 26, '#8a8fc4');
      r(46, 6, 5, 5, '#e8e2c8'); r(47, 5, 3, 1, '#e8e2c8'); r(45, 7, 1, 3, '#e8e2c8'); r(48, 7, 2, 2, '#cfc6a6');
      let s = seed;
      for (let x = 2; x < 62;) { s = mix(s + x); const w = 5 + s % 6, h = 12 + (s >>> 5) % 18; r(x, floorY - h, w, h, '#0c0e26'); for (let y = floorY - h + 2; y < floorY - 2; y += 3) for (let xx = x + 1; xx < x + w - 1; xx += 2) if (mix(s + y * 7 + xx) % 3 === 0) r(xx, y, 1, 1, '#e8c860'); x += w + 1; }
      r(8, 18, 8, 7, '#3a2a2a'); r(9, 25, 1, 7, '#3a2a2a'); r(14, 25, 1, 7, '#3a2a2a'); r(8, 17, 8, 1, '#5a3a3a');
      r(2, floorY, 60, 11, '#3a3d52'); r(2, floorY, 60, 1, '#6a6d86'); for (let x = 4; x < 62; x += 8) r(x, floorY + 3, 5, 1, '#2c2e40');
    } else if (kit === 2) { // Reactor chamber: panels and a core ring
      r(2, 2, 60, 48, '#1a2236'); for (let x = 2; x < 62; x += 8) r(x, 2, 1, 48, '#26324c'); for (let y = 8; y < 50; y += 10) r(2, y, 60, 1, '#26324c');
      circle(32, 25, 18, '#2a3a58'); circle(32, 25, 16, a); circle(32, 25, 15, '#1a2a44'); circle(32, 25, 12, '#223452');
      r(4, 4, 4, 46, '#3a4a66'); r(56, 4, 4, 46, '#3a4a66'); r(5, 4, 1, 46, '#5a6e90'); r(57, 4, 1, 46, '#5a6e90');
      r(2, floorY, 60, 11, '#2a3448'); for (let x = 2; x < 62; x += 4) r(x, floorY, 2, 2, '#e0b030'); for (let x = 4; x < 62; x += 4) r(x, floorY, 2, 2, '#1a1a22');
    } else if (kit === 3) { // Moon gate at night
      bands([['#141233', 24], ['#1c1a45', 24]], 2); stars(14, 40, '#9a98d0');
      circle(40, 16, 10, '#f1e8c8'); r(36, 12, 3, 2, '#d8cda6'); r(43, 18, 2, 2, '#d8cda6'); r(38, 20, 2, 1, '#d8cda6');
      for (let y = 2; y < 50; y++) { const d = Math.abs(y - 28); const w = d < 22 ? half(22, d) : 0; r(2, y, Math.max(0, 32 - w - 2), 1, '#2d2350'); r(32 + w, y, Math.max(0, 30 - w), 1, '#2d2350'); }
      for (const x of [5, 9, 55]) { r(x, 6, 2, 44, '#2f5a3a'); for (let y = 10; y < 50; y += 7) r(x, y, 2, 1, '#1f3a28'); r(x + 2, 12 + x % 5, 3, 1, '#3f7a4a'); }
      r(2, floorY, 60, 11, '#2c2848'); for (let x = 2; x < 62; x += 6) r(x, floorY + 1 + (x % 4), 4, 1, '#3a3660');
    } else if (kit === 4) { // Clay ring under a hanging roof
      r(2, 2, 60, 48, '#3a2418'); for (let x = 2; x < 62; x += 6) r(x, 12, 1, 38, '#2e1c12');
      r(2, 2, 60, 6, '#24160f'); r(4, 8, 56, 3, '#5a2a6a'); for (let x = 6; x < 60; x += 6) r(x, 11, 3, 2, '#5a2a6a');
      r(4, 8, 2, 8, '#d23a2a'); r(58, 8, 2, 8, '#2a4ad2'); r(4, 16, 2, 2, '#b82a1e'); r(58, 16, 2, 2, '#1e36a8');
      r(10, 30, 44, 20, '#c9975e'); r(8, 44, 48, 6, '#b27f4a');
      r(2, floorY, 60, 11, '#c9975e'); r(6, floorY + 1, 52, 2, '#e8d49a'); r(6, floorY + 3, 52, 1, '#b8a468');
    } else if (kit === 5) { // Arena lights: spotlights, crowd, ropes
      r(2, 2, 60, 48, '#150f22');
      for (let y = 2; y < 50; y++) { const w = 4 + (y >> 2); r(20 - (w >> 1), y, w, 1, '#231a36'); r(44 - (w >> 1), y, w, 1, '#231a36'); }
      let s = seed; for (let y = 22; y < 38; y += 3) for (let x = 2 + (y % 2) * 2; x < 62; x += 4) { s = mix(s + x + y); r(x, y, 3, 2, ['#2a2040', '#322648', '#1f1830'][s % 3]); if (s % 23 === 0) r(x + 1, y, 1, 1, '#ffffff'); }
      for (const [y, col] of [[38, '#c8323c'], [42, '#e8e4dc'], [46, '#3a5ac8']]) r(2, y, 60, 1, col);
      r(3, 36, 3, 14, '#8a8a96'); r(58, 36, 3, 14, '#8a8a96');
      r(2, floorY, 60, 11, '#d6d2dc'); r(2, floorY, 60, 1, '#f2eef4'); for (let x = 2; x < 62; x += 7) r(x, floorY + 4, 4, 1, '#bcb8c4');
    } else if (kit === 6) { // Jungle base: palms, sandbags, a hangar
      bands([['#e8a860', 10], ['#e8c080', 10], ['#c8d0a0', 8], ['#8aa070', 20]], 2);
      r(36, 18, 24, 20, '#5a6048'); r(38, 14, 20, 4, '#6a7058'); r(40, 22, 16, 16, '#2a2e22'); r(47, 20, 2, 18, '#4a5040');
      for (const [x, h] of [[8, 30], [18, 24]]) { r(x, floorY - h, 2, h, '#5a3a22'); r(x - 5, floorY - h, 12, 2, '#2f6a2a'); r(x - 7, floorY - h + 2, 4, 2, '#2f6a2a'); r(x + 4, floorY - h + 2, 5, 2, '#2f6a2a'); r(x - 2, floorY - h - 2, 6, 2, '#3f8a38'); }
      for (let x = 2; x < 34; x += 5) { r(x, 44, 5, 3, '#b8a070'); r(x + 2, 41, 5, 3, '#c8b080'); }
      r(2, floorY, 60, 11, '#8a7a50'); for (let x = 2; x < 62; x += 5) r(x + (x % 3), floorY + 3, 2, 1, '#6a5a38');
    } else if (kit === 7) { // Lantern market: stalls, strings of lanterns
      bands([['#2a1830', 16], ['#3a2034', 32]], 2);
      for (let x = 2; x < 62; x += 12) { r(x, 20, 11, 30, '#4a2a26'); r(x, 20, 11, 3, '#8a2a24'); r(x + 2, 28, 7, 8, '#241410'); r(x + 3, 30, 5, 1, '#e8b050'); }
      for (let x = 4; x < 62; x += 7) { const y = 8 + ((x * 3) % 5); r(x, y, 4, 5, '#d8342c'); r(x + 1, y, 2, 5, '#f05a3a'); r(x, y - 1, 4, 1, '#e8b050'); r(x, y + 5, 4, 1, '#e8b050'); }
      r(2, 7, 60, 1, '#5a3a30');
      r(2, floorY, 60, 11, '#4a3a3a'); for (let x = 2; x < 62; x += 8) { r(x, floorY + 2, 7, 3, '#5a4848'); r(x + 4, floorY + 6, 7, 3, '#5a4848'); }
    } else if (kit === 8) { // Harbour at dusk: sea, boats, a pier
      bands([['#e87a4a', 8], ['#f0a060', 8], ['#f4c880', 8], ['#3a6a8a', 6], ['#2a5070', 6], ['#1e3e5a', 12]], 2);
      dither(10, '#f0a060'); dither(18, '#f4c880');
      circle(20, 25, 6, '#fff0b0'); r(12, 26, 17, 1, '#f4c880'); r(2, 26, 60, 0, '#000');
      for (let y = 34; y < 50; y += 3) r(6 + (y % 5), y, 10, 1, '#5a8aaa');
      r(40, 30, 14, 4, '#3a2a22'); r(46, 18, 1, 12, '#3a2a22'); r(47, 19, 6, 9, '#e8e0cc');
      r(2, floorY, 60, 11, '#8a6a48'); for (let x = 2; x < 62; x += 6) r(x, floorY, 1, 11, '#6a4e34');
    } else if (kit === 9) { // Mountain temple: daylight peaks and a pagoda
      bands([['#7aa8d8', 12], ['#9cc0e2', 10], ['#c4dcec', 10], ['#dce8ee', 16]], 2);
      for (let y = 18; y < 50; y++) { const w = (y - 18) * 2; r(18 - (w >> 1), y, w, 1, '#6a84a6'); r(40 - (w >> 2), y, w >> 1, 1, '#5a7496'); }
      r(15, 18, 6, 2, '#f4f4f8'); r(38, 26, 5, 2, '#f4f4f8');
      for (let k = 0; k < 4; k++) { r(46 - k, 14 + k * 8, 12 + k * 2, 2, '#3a2a3a'); r(48 - k, 16 + k * 8, 8 + k * 2, 6, '#8a3a2e'); }
      r(4, 10, 10, 2, '#ffffff'); r(6, 8, 6, 2, '#ffffff'); r(26, 6, 8, 2, '#ffffff');
      r(2, floorY, 60, 11, '#9a9084'); for (let x = 2; x < 62; x += 9) r(x, floorY + 2, 8, 4, '#aaa296');
    } else if (kit === 10) { // Boxing gym: brick wall, heavy bag, ropes
      r(2, 2, 60, 48, '#6a3428'); for (let y = 2; y < 50; y += 4) { r(2, y, 60, 1, '#4a2218'); for (let x = 2 + ((y >> 2) % 2) * 4; x < 62; x += 8) r(x, y, 1, 4, '#4a2218'); }
      r(8, 2, 1, 10, '#8a8a8a'); r(5, 12, 7, 18, '#9a2a2a'); r(6, 12, 2, 18, '#c23a3a'); r(5, 16, 7, 1, '#4a1414'); r(5, 26, 7, 1, '#4a1414');
      r(46, 6, 12, 8, '#e8d8a8'); r(47, 7, 10, 6, '#c83a2a'); r(49, 9, 6, 2, '#e8d8a8');
      for (const [y, col] of [[36, '#e8e4dc'], [41, '#c8323c'], [46, '#e8e4dc']]) r(2, y, 60, 1, col);
      r(2, floorY, 60, 11, '#3a5aa8'); r(2, floorY, 60, 1, '#6a8ad8');
    } else { // River stadium: warm lamps over the ring
      bands([['#1e2a3a', 14], ['#26364a', 14], ['#2e4258', 20]], 2);
      for (let x = 6; x < 62; x += 14) { r(x, 6, 6, 3, '#f0c060'); r(x + 2, 9, 2, 2, '#fff0b0'); r(x + 2, 2, 2, 4, '#3a3a3a'); }
      let s = seed; for (let y = 24; y < 38; y += 3) for (let x = 2 + (y % 2) * 2; x < 62; x += 4) { s = mix(s + x * 3 + y); r(x, y, 3, 2, ['#3a3040', '#2e2a3c', '#443848'][s % 3]); }
      for (const [y, col] of [[39, '#d83a3a'], [43, '#e8c050'], [47, '#3a6ad8']]) r(2, y, 60, 1, col);
      r(2, floorY, 60, 11, '#c8b890'); r(2, floorY, 60, 1, '#e8d8b0');
    }
    // Ground shadow under the fighter, then the fighter at 1:1.
    parts.push(`<g transform="translate(8 5)">${body}</g>`);
    // Frame: dark outer line, accent bevel, blank name plate.
    r(0, 0, 64, 2, INK); r(0, 62, 64, 2, INK); r(0, 0, 2, 64, INK); r(62, 0, 2, 64, INK);
    r(1, 1, 62, 1, a); r(1, 1, 1, 62, a); r(1, 62, 62, 1, '#3a3246'); r(62, 1, 1, 62, '#3a3246');
    r(2, 55, 60, 7, '#140f1a'); r(2, 55, 60, 1, '#4a4058'); r(4, 57, 56, 3, '#221a2c'); r(4, 57, 2, 3, a); r(58, 57, 2, 3, a);
    return parts.join('');
  }

  function assets(identity) {
    if (!cache.has(identity)) {
      if (cache.size >= 256) cache.delete(cache.keys().next().value);
      const body = sprite(identity);
      cache.set(identity, { body, art: artwork(identity, body) });
    }
    return cache.get(identity);
  }

  function svg(identity, mode = 'artwork') {
    identity = String(identity || '');
    const { body, art } = assets(identity);
    const viewBox = mode === 'portrait' ? '12 0 24 24' : mode === 'sprite' ? `0 0 ${SIZE} ${SIZE}` : `0 0 ${CARD} ${CARD}`;
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${viewBox}" shape-rendering="crispEdges" focusable="false">${mode === 'sprite' || mode === 'portrait' ? body : art}</svg>`;
  }

  // Frame bodies for one clip: each entry is the path markup of a 48×48 sprite,
  // or of the 64×64 card in artwork mode.
  function frames(identity, clip = 'idle', mode = 'sprite') {
    identity = String(identity || '');
    const c = CLIPS[clip] || CLIPS.idle;
    return c.frames.map((pose, i) => {
      const body = i === 0 && clip === 'idle' ? assets(identity).body : sprite(identity, pose);
      return mode === 'artwork' ? artwork(identity, body) : body;
    });
  }

  // One SVG holding every frame of a clip as a hidden group. Nothing in it
  // moves by itself; anim.js shows one <g data-frame> at a time.
  function strip(identity, clip = 'idle', mode = 'sprite') {
    const c = CLIPS[clip] || CLIPS.idle;
    const groups = frames(identity, clip, mode)
      .map((body, i) => `<g data-frame="${i}"${i ? ' style="display:none"' : ''}>${body}</g>`).join('');
    const viewBox = mode === 'artwork' ? `0 0 ${CARD} ${CARD}` : `0 0 ${SIZE} ${SIZE}`;
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${viewBox}" shape-rendering="crispEdges" focusable="false" data-clip="${clip}" data-fps="${c.fps}" data-frames="${c.frames.length}"${c.hold ? ' data-hold="1"' : ''}>${groups}</svg>`;
  }

  // The move a fighter shows off on its card. A character trait like the rest:
  // derived from the identity, never from rank or results.
  function signature(identity) {
    return SIGNATURES[hash('qdojo/fighter/signature/v1/' + String(identity || '')) % SIGNATURES.length];
  }

  function render(identity, className = '') {
    // A portrait crop at 24px; full character on the mat; artwork on big cards.
    const classes = String(className).split(/\s+/).filter(c => /^[a-zA-Z0-9_-]+$/.test(c));
    const mode = classes.includes('avatar-sm') ? 'portrait' : classes.includes('avatar-xl') ? 'artwork' : 'sprite';
    return `<span class="avatar ${classes.join(' ')}" aria-hidden="true">${svg(identity, mode)}</span>`;
  }
  return Object.freeze({ version: VERSION, size: SIZE, render, svg, traits, frames, strip, signature, clips: CLIPS });
})();
