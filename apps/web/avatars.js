/* QDOJO fighters, v5 preview: salvaged robots in human shape, fighting in a
 * scrapyard dojo years after the Big Unplug. Original 48×48 sprites and 64×64
 * collectible cards in the spirit of early-90s arcade fighters, without copying
 * any existing character or robot.
 *
 * Pure and deterministic: an identity string (usually a 64-hex fighter id) maps
 * to byte-identical SVG on every runtime. No randomness, clock, network,
 * external assets, gradients or filters. Every trait comes from its own hash
 * domain, so traits are independent of each other. Appearance never depends on
 * rank, results or the wallet owner.
 *
 * Bodies are built from a small skeleton: shoulders, elbows and fists; hips,
 * knees and ankles. Poses move joints by whole pixels, so every frame stays
 * crisp. Each armour shell is a pixel mask shaded from the upper right in a
 * material (chrome, paint, primer, rust), then weathered in its own local
 * coordinates (chips, rust patches) so the wear moves with the part. Elbows,
 * knees and necks are exposed joints with bolts and pistons. Martial-arts gear
 * is layered on top. `frames`/`strip` return frame sequences for the clips
 * below; playback lives in anim.js, not here.
 */
'use strict';
const QDojoAvatars = (() => {
  const SIZE = 48, N = SIZE * SIZE, CARD = 64, CX = 23;
  const VERSION = 'qdojo-fighters-v5-preview';
  const INK = '#0d0f12';
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
  // Twelve machines with a former job, each sincerely practising a martial art
  // it learned from a tape. The kit keeps the v4 hash domain, so every fighter
  // keeps its discipline: the v4 dojo striker is now the kata unit, and so on.
  const KITS = [
    { name: 'Kata unit', art: 'karate', code: 'KT', backdrop: 'Collapsed dojo', head: ['Hachimaki', 'Hachimaki', 'None'],
      jobs: ['dojo floor-sweeping unit', 'karate demonstration dummy', 'shrine gift-shop greeter'] },
    { name: 'Courier bot', art: 'street kickboxing', code: 'CR', backdrop: 'Flooded underpass', head: ['Courier cap', 'Backwards cap', 'Bandana', 'None'],
      jobs: ['parcel courier', 'pizza delivery unit', 'express-mail walker'] },
    { name: 'Mall-security unit', art: 'judo', code: 'MS', backdrop: 'Dead mall', head: ['Security cap', 'Security cap', 'None'],
      jobs: ['mall-security unit', 'car-park patrol unit', 'lost-and-found attendant'] },
    { name: 'Harvester bot', art: 'ninjutsu', code: 'HV', backdrop: 'Dust-bowl farm', head: ['Straw hat', 'Straw hat', 'Bandana', 'None'],
      jobs: ['harvester bot', 'scarecrow upgrade', 'pumpkin-sorting unit'] },
    { name: 'Sumo loader', art: 'sumo', code: 'SL', backdrop: 'Container yard', head: ['Warning beacon', 'Warning beacon', 'None'],
      jobs: ['forklift', 'heavy loader', 'container-yard stacker'] },
    { name: 'Luchador wrestle-bot', art: 'lucha libre', code: 'LX', backdrop: 'Junk arena', head: ['Flame mask', 'Star mask', 'Stripe mask', 'None'],
      jobs: ['wrestling-ring setup crew', 'theme-park mascot', 'party-balloon tester'] },
    { name: 'Endoskeleton trooper', art: 'parade-ground drill', code: 'TR', backdrop: 'Bunker ruins', head: ['Combat helmet', 'Combat helmet', 'None'],
      jobs: ['parade-ground trooper', 'boot-camp drill dummy', 'army surplus mannequin'] },
    { name: 'Kitchen unit', art: 'kung fu', code: 'KC', backdrop: 'Noodle stall', head: ['Chef hat', 'Chef hat', 'Headband', 'None'],
      jobs: ['noodle-bar kitchen unit', 'wok-tossing arm', 'dishwasher with ambitions'] },
    { name: 'Dance-bot', art: 'capoeira', code: 'DB', backdrop: 'Neon plaza', head: ['Sweatband', 'Bandana', 'None'],
      jobs: ['nightclub dance-bot', 'aerobics instructor unit', 'shop-window mascot'] },
    { name: 'Drone monk', art: 'tai chi', code: 'DM', backdrop: 'Radio-tower shrine', head: ['None', 'Forehead mark'],
      jobs: ['survey drone', 'air-quality drone', 'lighthouse keeper drone'] },
    { name: 'Boxer bot', art: 'boxing', code: 'BX', backdrop: 'Rust-belt gym', head: ['None', 'None', 'Head guard'],
      jobs: ['sparring dummy', 'gym towel dispenser', 'meat-locker door opener'] },
    { name: 'Demolition unit', art: 'Muay Thai', code: 'DX', backdrop: 'Demolition site', head: ['Hard hat', 'Hard hat', 'Mongkhon', 'None'],
      jobs: ['demolition unit', 'wrecking-ball operator', 'pothole filler'] },
  ];
  const STANCES = ['Low guard', 'Boxer guard', 'Power stance'];
  const BUILDS = ['Lean', 'Standard', 'Heavy'];
  const FINISHES = ['Factory Chrome', 'Polished Paint', 'Weathered', 'Rust Bucket', 'Scrap-Built'];
  const RUSTS = ['None', 'Speckled', 'Patchy', 'Heavy'];
  const HEADS = ['Visor', 'CRT monitor', 'Skull faceplate', 'Painted smile', 'Bucket helmet', 'Single lens', 'Radio grille'];
  // Glow colours for eyes, visors and status lights.
  const GLOWS = [['Cyan', '#36e0ff'], ['Neon pink', '#ff4fa0'], ['Amber', '#f2c230'], ['Toxic green', '#86f04a'],
    ['Warning red', '#f0443a'], ['Ice white', '#dff4ff'], ['Ultraviolet', '#a66cff'], ['Teal', '#3aecc0']];
  // Paints for the armour shells. Brass never goes on a shiny finish.
  const PAINTS = [['Hazard yellow', '#d9a52a'], ['Oxidised teal', '#3a9d8f'], ['Fire-engine red', '#c23a2e'], ['Army olive', '#6b7042'],
    ['Safety orange', '#dc6a26'], ['Navy', '#34507e'], ['Cream enamel', '#d6cdb2'], ['Mint', '#79bf9f'], ['Primer grey', '#7c828b'],
    ['Bubblegum pink', '#d46f98'], ['Sky blue', '#5a97cc'], ['Tractor green', '#3f7c3e'], ['Brass', '#b48d3a'], ['Plum', '#74417a']];
  const SALVAGE_LIMBS = ['None', 'Lead arm', 'Rear arm', 'Lead leg', 'Rear leg'];
  const TOPPERS = ['None', 'Whip antenna', 'Rabbit ears', 'Exhaust stack', 'Drone rotor'];
  const QUIRKS = ['None', 'Traffic-cone hat', 'Duct-tape patch', 'Necktie', 'Toaster slot', 'Rubber duck', 'Name sticker',
    'Headphones', 'Exhaust flower', 'Band-aid'];
  // Curated cloth palettes for the gear: main cloth, second cloth, trim.
  const PALETTES = [
    ['Classic white', '#e9e3d3', '#34303c', '#c8343c'],
    ['Crimson', '#b3303a', '#2e2830', '#e6b44a'],
    ['Royal blue', '#2f4fa6', '#e6ddc6', '#e0a22e'],
    ['Jungle green', '#3e7a3c', '#5a4030', '#e2b24a'],
    ['Sunset orange', '#dd6d28', '#3a2a28', '#f2d266'],
    ['Midnight', '#2c3050', '#4c4c62', '#d8423c'],
    ['Tan canvas', '#c49c66', '#5a3a26', '#b83a2e'],
    ['Royal purple', '#693a8c', '#2a2436', '#e6c04a'],
    ['Teal', '#2a8584', '#243039', '#e8d8a2'],
    ['Black and gold', '#2c2b32', '#1a191f', '#e0b042'],
    ['Rose', '#d25c86', '#3a2a3a', '#f2e2d2'],
    ['Sky', '#4a8fce', '#efebe0', '#c83242'],
    ['Olive drab', '#6b7042', '#3b3a2a', '#c9a352'],
    ['Maroon', '#7a2b31', '#2a2024', '#e6c67a'],
  ];
  const GLOVES = ['Robot fists', 'Tape wraps', 'Fingerless gloves', 'Work gloves'];
  const SASHES = ['Plain', 'Striped', 'Checked', 'Stitched'];
  const PATTERNS = ['Plain', 'Racing stripe', 'Stencil number', 'Emblem'];
  const EMBLEMS = ['Sun disc', 'Tomoe', 'Diamond', 'Wave', 'Crane'];
  const SIGNATURES = ['jab', 'kick', 'bow', 'win'];
  const GLOVE_FREE = new Set([0, 1, 3, 5, 6, 8]);

  // Fixed material ramps: deep, shadow, base, light, highlight.
  const CHROME = ['#1b2129', '#4b5563', '#9aa6b2', '#e8edf2', '#ffffff'];
  const STEEL = ['#15181e', '#2b313b', '#454d5a', '#6b7483', '#a3adba'];
  const CHIP = ['#2b313b', '#5b636e', '#8b95a0', '#bcc4cc', '#dfe5ea'];
  const RUST = ['#3a170a', '#6e2c0f', '#8a3b12', '#c2551b', '#e07a3a'];
  const RUSTY = ['#3a1a0c', '#6a3016', '#8e4a26', '#b0673a', '#cf8a5a'];

  // Materials: a ramp, a kind, a chip rate and a rust level (0-3).
  function glowRamp(c) { return [mixHex(c, '#000000', 0.62), mixHex(c, '#000000', 0.32), c, mixHex(c, '#ffffff', 0.45), mixHex(c, '#ffffff', 0.8)]; }
  function material(kind, hex, rust, chips) {
    if (kind === 'chrome') return { kind, R: CHROME, rust: 0, chips: 0, name: 'Chrome' };
    if (kind === 'rusty') return { kind, R: RUSTY, rust: 3, chips: 0, name: 'Rusty' };
    if (kind === 'primer') return { kind, R: ramp('#7c828b'), rust, chips: 0.03, name: 'Primer' };
    return { kind, R: ramp(hex), rust, chips, name: 'Painted' };
  }

  const looks = new Map();
  function look(identity) {
    if (looks.has(identity)) return looks.get(identity);
    const id = identity;
    const kit = pick(id, 'kit', KITS.length), K = KITS[kit];
    let build = weighted(id, 'build', [3, 5, 3]);
    if (kit === 4) build = 2;
    if (kit === 9) build = 0;
    if (kit === 5 && build === 0) build = 1;
    const finish = weighted(id, 'finish', kit === 10 ? [1, 2, 4, 4, 3] : [2, 3, 4, 3, 2]);
    const rust = [0, weighted(id, 'rust', [4, 1]), 1 + weighted(id, 'rust', [1, 1]), 2 + weighted(id, 'rust', [1, 3]),
      1 + weighted(id, 'rust', [1, 2, 1])][finish];
    let paint = pick(id, 'paint', PAINTS.length);
    if (kit === 6) paint = [3, 8, 5, 3][pick(id, 'paint', 4)];                  // trooper: service colours
    if (kit === 4) paint = [0, 4, 0, 11, 2][pick(id, 'paint', 5)];             // loader: forklift colours
    // Originality guards. The genre's archetypes are fair game; a few
    // combinations would read as one famous robot, so steer them away.
    if (paint === 12 && finish < 2) paint = 4;                                 // no gold protocol droid
    if (kit === 10 && (paint === 2 || paint === 5 || paint === 10)) paint = 7; // no red-vs-blue toy boxers
    let head = pick(id, 'head', HEADS.length);
    if (kit === 2 && head === 0) head = 5;                                     // no visored police cyborg
    if (kit === 6 && head === 2) head = 0;                                     // no skull-faced soldier
    let glow = pick(id, 'glow', GLOWS.length);
    if (glow === 4 && (finish === 0 || head === 0 || head === 2 || kit === 6)) glow = 2; // no red-eyed chrome menace
    let headgear = K.head[pick(id, 'headgear', K.head.length)];
    const masked = /mask$/.test(headgear);
    let topper = weighted(id, 'topper', [4, 2, 2, 2, 0]);
    let quirk = weighted(id, 'quirk', [5, 2, 2, 2, 2, 2, 2, 2, 2, 2]);
    if (kit === 9) { topper = 4; if (quirk === 8 || quirk === 1) quirk = quirk === 8 ? 5 : 9; } // the monk hovers on a rotor
    if (quirk === 8) topper = 3;                                               // the flower needs an exhaust
    if (head === 4 && topper === 1) topper = 2;                                // bucket heads get rabbit ears
    if (quirk === 4 && (kit === 3 || kit === 7)) quirk = 6;                    // no toaster under a bib or apron
    const hat = !/band$|mark$|mask$|^None$|Hachimaki|Mongkhon|Bandana|Headband/.test(headgear);
    if (quirk === 1 && hat) headgear = 'None';                                 // the cone replaces the hat
    let salvage = weighted(id, 'salvage', [7, 1, 1, 1, 1]);
    const pal = PALETTES[pick(id, 'palette', PALETTES.length)];
    const gloves = kit === 10 ? 'Boxing gloves' : kit === 11 ? 'Hand wraps' : kit === 7 ? ['Oven mitt', 'Robot fists'][pick(id, 'gloves', 2)]
      : kit === 2 ? 'Work gloves' : GLOVE_FREE.has(kit) ? GLOVES[pick(id, 'gloves', GLOVES.length)] : 'Robot fists';
    const shoulders = kit === 10 ? ['Towel', 'Towel', 'Robe', 'None'][pick(id, 'shoulders', 4)] : kit === 6 ? 'Armour plate'
      : kit === 4 ? 'Hazard pads' : kit === 1 ? ['None', 'Parcel box'][pick(id, 'shoulders', 2)] : kit === 7 ? 'Wok' : 'None';

    // Materials. Shiny finishes salvage rusty or primed parts; worn ones
    // salvage chrome or another colour.
    const P = PAINTS[paint][1];
    const chips = [0, 0.012, 0.05, 0.075, 0.06][finish];
    const body = finish === 0 ? material('chrome') : finish === 1 ? material('paint', P, rust, chips)
      : finish === 2 ? material('paint', mixHex(P, '#77706a', 0.28), rust, chips)
      : finish === 3 ? material('paint', mixHex(P, '#7a3c1c', 0.38), rust, chips)
      : material('paint', mixHex(P, '#77706a', 0.18), rust, chips);
    const other = PAINTS[(paint + 3 + pick(id, 'salvage-paint', PAINTS.length - 4)) % PAINTS.length];
    const salvKind = finish < 2 ? ['rusty', 'primer', 'paint'][pick(id, 'salvage-finish', 3)] : ['chrome', 'primer', 'paint'][pick(id, 'salvage-finish', 3)];
    const salvMat = salvKind === 'paint' ? material('paint', mixHex(other[1], '#77706a', finish < 2 ? 0 : 0.25), finish ? rust : 0, chips || 0.02)
      : material(salvKind, null, finish ? rust : 1, 0);
    // Scrap-built machines are assembled from three sources.
    const scrap = [body, material('primer', null, rust), material('paint', mixHex(other[1], '#77706a', 0.3), rust, chips), material('chrome')];
    const partMat = {};
    for (const part of ['torso', 'head', 'lead-arm', 'rear-arm', 'lead-leg', 'rear-leg', 'pelvis']) {
      partMat[part] = finish === 4 ? scrap[[0, 0, 1, 2, 3][pick(id, 'scrap/' + part, 5)] % 4] : body;
    }
    if (finish === 4) partMat.torso = body;
    // The trooper is an endoskeleton: bare metal limbs under painted armour.
    let plate = body;
    if (kit === 6) {
      plate = finish === 0 ? material('paint', P, 0, 0.012) : body;
      const skeleton = finish < 2 ? material('chrome') : material('paint', '#6b7483', rust, chips);
      for (const part of ['lead-arm', 'rear-arm', 'lead-leg', 'rear-leg', 'pelvis']) if (partMat[part] === body || finish < 2) partMat[part] = skeleton;
      partMat.torso = partMat.head = plate;
    }
    if (salvage) partMat[SALVAGE_LIMBS[salvage].toLowerCase().replace(' ', '-')] = salvMat;
    const L = {
      kit, K, build, finish, rust, paint, head: masked ? -1 : head, glow, headgear, masked, topper, quirk, salvage, salvMat,
      gloves, shoulders, stance: pick(id, 'stance', 3), palette: pal[0],
      sash: pick(id, 'sash', SASHES.length), pattern: PATTERNS[pick(id, 'pattern', PATTERNS.length)],
      emblem: pick(id, 'emblem', EMBLEMS.length), body, partMat, plate,
      robe: ramp(['#d9822a', '#8a2b31', '#c8a24a'][pick(id, 'robe', 3)]),
      designation: K.code + '-' + (100 + pick(id, 'designation', 900)),
      year: 2029 + pick(id, 'year', 19),
      G: glowRamp(GLOWS[glow][1]), P: ramp(P),
      Mn: ramp(pal[1]), Sc: ramp(pal[2]), Tr: ramp(pal[3]),
      seed: roll(id, 'wear'),
    };
    if (looks.size >= 512) looks.delete(looks.keys().next().value);
    looks.set(identity, L);
    return L;
  }

  function traits(identity) {
    identity = String(identity || '');
    const L = look(identity);
    const band = ['Hachimaki', 'Headband', 'Bandana', 'Mongkhon', 'Sweatband'].includes(L.headgear);
    return Object.freeze({
      archetype: L.K.name, martialArt: L.K.art, formerJob: L.K.jobs[pick(identity, 'bio/job', 3)],
      designation: L.designation, modelYear: L.year,
      chassis: BUILDS[L.build], build: BUILDS[L.build], stance: STANCES[L.stance],
      finish: FINISHES[L.finish], rust: RUSTS[L.rust], paint: PAINTS[L.paint][0], outfit: L.body.R[2],
      headUnit: L.masked ? 'Masked' : HEADS[L.head], eyeGlow: GLOWS[L.glow][0], accent: GLOWS[L.glow][1],
      salvagedLimb: L.salvage ? L.salvMat.name + ' ' + SALVAGE_LIMBS[L.salvage].toLowerCase() : 'None',
      topper: TOPPERS[L.topper], quirk: QUIRKS[L.quirk],
      headgear: L.headgear, headband: band, gloves: L.gloves, shoulders: L.shoulders,
      palette: L.palette, sash: SASHES[L.sash], pattern: L.pattern,
      emblem: L.pattern === 'Emblem' ? EMBLEMS[L.emblem] : null,
      backdrop: L.K.backdrop, signature: signature(identity),
    });
  }

  // ---- Bio --------------------------------------------------------------------
  // One or two short sentences in the dojo's tone, built only from traits.
  const OPENERS = ['Decommissioned', 'Retired', 'Surplus', 'Salvaged', 'Factory-recalled', 'Refurbished', 'Discontinued',
    'Unclaimed', 'Second-hand', 'Ex-display', 'Lightly used', 'Returned-to-sender'];
  const LEARNED = [
    a => `Learned ${a} from a cracked VHS`,
    a => `Picked up ${a} from late-night reruns`,
    a => `Studied ${a} under a mentor bot with one working speaker`,
    a => `Taught itself ${a} from a mostly static tape labelled SENSEI`,
    a => `Learned ${a} from a training montage it only half remembers`,
    a => `Copied every ${a} move from a warped tape played at double speed`,
    a => `Found a ${a} manual in a dumpster and read it upside down`,
    a => `Learned ${a} from a rusty sensei who only said "oil on, oil off"`,
    a => `Watched one ${a} rerun eleven thousand times`,
    a => `Downloaded ${a} over a very bad connection`,
  ];
  const QUIRK_BITS = {
    'Traffic-cone hat': ['wears a traffic cone it believes is a crown', 'refuses to fight without its lucky traffic cone'],
    'Duct-tape patch': ['is held together by duct tape and optimism', 'patches every dent with one more strip of duct tape'],
    'Necktie': ['wears a necktie in case the fight turns into a job interview', 'straightens its necktie before every bell'],
    'Toaster slot': ['makes toast between rounds', 'offers its opponent toast after every bout'],
    'Rubber duck': ['consults a rubber duck before sealing its cartridge', 'will not step into the ring without its rubber duck'],
    'Name sticker': ['still wears a blank HELLO MY NAME IS sticker', 'keeps meaning to fill in its name sticker'],
    'Headphones': ['hears a training montage nobody else can', 'shadow-boxes to a soundtrack only it can hear'],
    'Exhaust flower': ['keeps a flower in its exhaust for luck', 'waters the flower in its exhaust every morning'],
    'Band-aid': ['puts band-aids on its dents', 'believes band-aids work on metal'],
  };
  const PLAIN_BITS = ['bows to vending machines', 'bows to every opponent and most doors', 'apologises to the punching bag',
    'polishes itself before every bout', 'counts its bolts after every round', 'salutes the scoreboard', 'keeps a spare oil can for the other fighter'];
  const FINISH_BITS = [['still has the factory stickers on'], ['has never missed a coat of wax'], ['squeaks a little on the backswing'],
    ['leaves a trail of rust flakes on the mat'], ['is three different robots, officially']];
  function bio(identity) {
    identity = String(identity || '');
    const t = traits(identity), L = look(identity);
    const b = n => pick(identity, 'bio/' + n, 1 << 30);
    const opener = OPENERS[b('opener') % OPENERS.length];
    const job = t.formerJob;
    const lead = b('shape') % 3 === 0
      ? `Unit ${t.designation}, ${/^[AEIOU]/.test(opener) ? 'an' : 'a'} ${opener.toLowerCase()} ${job}, model year ${t.modelYear}.`
      : `${opener} ${job}, model year ${t.modelYear}.`;
    const learned = LEARNED[b('learned') % LEARNED.length](t.martialArt);
    let habit;
    if (QUIRK_BITS[t.quirk]) habit = QUIRK_BITS[t.quirk][b('habit') % 2];
    else if (b('habit') % 3 === 0) habit = FINISH_BITS[L.finish][0];
    else habit = PLAIN_BITS[b('habit') % PLAIN_BITS.length];
    return `${lead} ${learned} and ${habit}.`;
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
          // Chrome: a dark reflection just inside the lit rim and a bright
          // sky reflection next to the shadow band, so metal reads as polished.
          if (o.chrome && l === 2) {
            if (!a[p + 2] || !a[p - 2 * W]) l = 1;
            else if (!a[p - 2] || !a[p - 3]) l = 3;
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
    // Swap a pixel onto another ramp at the same light level: rust, chips.
    function recolor(x, y, r, most = 4) {
      if (!ok(x, y)) return;
      const i = y * SIZE + x;
      if (!col[i]) return;
      const l = Math.min(lv[i], most);
      col[i] = r[l]; rp[i] = r; lv[i] = l;
    }
    const rampAt = (x, y) => ok(x, y) ? rp[y * SIZE + x] : null;
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
    return { fill, set, tone, shift, recolor, rampAt, filled, levelAt, out };
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

  // ---- The sprite -------------------------------------------------------------
  // Frame-stable noise: keyed to a part's own coordinates, so wear moves with it.
  const nz = (s, u, v) => mix((s ^ Math.imul(u + 97, 73856093) ^ Math.imul(v + 97, 19349663)) >>> 0) / 4294967296;
  const TAPE = ['#4a4e56', '#7e838b', '#a9aeb5', '#cdd1d6', '#eceef0'];
  const ENAMEL = ['#6a6258', '#b3aa98', '#e6dcc4', '#f6efdd', '#fffaf0'];
  const CONE = ['#5a1e08', '#b3440f', '#f06a1e', '#ff9a4a', '#ffc890'];
  const DUCK = ['#6a4a08', '#c8960e', '#f5cf2a', '#ffe66a', '#fff4b0'];
  const WHITE = ['#6d6a7c', '#bdb8c2', '#f2eee6', '#ffffff', '#ffffff'];
  const HAZARD = ramp('#f2c230'), WRAP = ramp('#e6e0d2'), LEATHER = ramp('#5a3a2a'), DARK = ramp('#2c2a34');
  const GOLD = ramp('#d8a837'), STRAW = ramp('#d6b25a'), BOX = ramp('#b0824a'), CABLE = ramp('#c8342c'), SKY = ramp('#2c3a4a');
  const TOAST = ramp('#d9a45a'), PETAL = ramp('#ff6fb0'), LEAF = ramp('#4aa04a'), BLUSH = '#e8849a', PAINT_INK = '#2a1c1c';
  // Head silhouettes in head coordinates (x 0..13 facing right, y 0..11).
  const DOME = [[3, 9], [1, 11], [0, 12], [0, 12], [0, 13], [0, 13], [0, 13], [0, 13], [0, 12], [1, 12], [2, 11], [4, 10]];
  const HEAD_SIL = [
    DOME,
    [[1, 12], [0, 13], [-1, 13], [-1, 13], [-1, 13], [-1, 13], [-1, 13], [-1, 13], [-1, 13], [-1, 13], [0, 13], [1, 12]],
    [[3, 9], [1, 11], [0, 12], [0, 12], [0, 13], [0, 13], [0, 13], [1, 13], [2, 12], [3, 12], [4, 11], [5, 10]],
    DOME,
    [[1, 11], [1, 11], [0, 12], [0, 12], [0, 12], [0, 12], [0, 13], [0, 13], [0, 13], [0, 13], [-1, 14], [-1, 14]],
    DOME,
    [[2, 11], [0, 13], [0, 13], [0, 13], [0, 13], [0, 13], [0, 13], [0, 13], [0, 13], [0, 13], [0, 13], [1, 12]],
  ];
  const MASK_SIL = [[3, 9], [1, 11], [0, 12], [-1, 12], [-1, 12], [-1, 13], [-1, 13], [-1, 13], [-1, 13], [-1, 13], [0, 12], [1, 12], [3, 10]];
  // 3×5 pixel font for stencils and hand-painted signs.
  const FONT = {
    0: '111101101101111', 1: '010110010010111', 2: '111001111100111', 3: '111001011001111', 4: '101101111001001',
    5: '111100111001111', 6: '111100111101111', 7: '111001010010010', 8: '111101111101111', 9: '111101111001111',
    A: '010101111101101', D: '110101101101110', E: '111100110100111', G: '011100101101011', J: '001001001101010',
    K: '101101110101101', L: '100100100100111', M: '101111111101101', N: '110101101101101', O: '010101101101010',
    P: '110101110100100', R: '110101110101101', S: '011100010001110', T: '111010010010010', U: '101101101101111',
    Y: '101101010010010', '/': '001001010100100', '-': '000000111000000', '!': '010010010000010', ' ': '000000000000000',
  };

  function sprite(identity, pose = {}) {
    const L = look(identity), kit = L.kit, B = BODY[L.build];
    pooled = 0;
    const { dx = 0, dy = 0, hx = 0, hy = 0, jump = 0, lead = 'guard', rear = null, legs = 'plant', blink = false } = pose;
    const c = canvas();
    const bx = dx, by = dy - jump, gy = -jump;
    const HX = CX - 6 + dx + hx, HY = 4 + dy + hy - jump;
    const { G, Mn, Sc, Tr } = L;
    const same = r => r;
    const hd = (x, y, r, l) => c.set(HX + x, HY + y, r, l);
    const lerp = (a, b, t) => [Math.round(a[0] + (b[0] - a[0]) * t), Math.round(a[1] + (b[1] - a[1]) * t)];
    const eye = blink ? 1 : 3, shine = blink ? 1 : 4;
    const headMat = L.partMat.head;

    const legState = LEGS[legs] || LEGS.plant;
    const hips = [[CX - B.hip + bx, 31 + by], [CX + B.hip + 1 + bx, 31 + by]];
    const legJoints = side => {
      const s = legState[side], spread = (L.build - 1) * (side ? 1 : -1);
      return { hip: hips[side], knee: [CX + s[0] + spread, s[1] + gy], ankle: [CX + s[2] + spread, s[3] + gy], foot: s[4] };
    };
    const shoulders = [[CX - B.sh + 2 + bx, 18 + by], [CX + B.sh - 1 + bx, 18 + by]];
    const thin = kit === 6 ? 1 : 0; // the trooper's limbs are bare endoskeleton rods

    // Which cloth covers the legs, and how far down (a fraction of the thigh,
    // or past the knee as a fraction of the shin).
    const LEGWEAR = { 0: [Mn, 0.85, 0], 1: [Sc, 0.6, 0], 3: [Mn, 1, 0.55], 5: [Mn, 0.3, 0], 7: [Sc, 1, 0.35], 8: [Mn, 1, 0.5],
      9: [L.robe, 0.8, 0], 10: [Mn, 0.5, 0], 11: [Mn, 0.5, 0] }[kit];

    // Back layer: exhaust, parcel box, wok, robe.
    backLayer();
    leg(0); leg(1);
    torso();
    waist();
    neck();
    arm(0);
    if (L.quirk === 5) duck();
    head();
    arm(1);
    front();
    return c.out();

    // ------------------------------------------------------------ materials
    function shell(m, part, R, o, spots, mat = L.partMat[part]) {
      const r = R(mat.R);
      c.fill(m, r, { band: 2, ...o, chrome: mat.kind === 'chrome' });
      weather(m, mat, r, part, spots || [], o.ox || 0, o.oy || 0);
    }
    function weather(m, mat, r, part, spots, ox, oy) {
      if (!mat.rust && !mat.chips) return;
      const key = (L.seed ^ hash(part)) >>> 0;
      const n = Math.min(spots.length, mat.rust);
      each(m, (x, y) => {
        if (c.rampAt(x, y) !== r) return;
        const u = x - ox, v = y - oy;
        for (let k = 0; k < n; k++) {
          const [sx, sy, sr] = spots[k], ex = x - sx, ey = y - sy, d2 = ex * ex + ey * ey;
          if (d2 <= sr * sr * (0.45 + 0.7 * nz(key + k, u, v))) {
            c.recolor(x, y, RUST, d2 < (sr - 1) * (sr - 1) && nz(key + 7, u, v) < 0.3 ? 1 : 3);
            return;
          }
        }
        if (mat.rust && nz(key + 11, u, v) < 0.012 * mat.rust) { c.recolor(x, y, RUST, 2); return; }
        if (mat.chips && c.levelAt(x, y) >= 2 && nz(key + 5, u, v) < mat.chips) c.recolor(x, y, CHIP);
      });
    }
    function spotsAlong(part, a, b, r0) {
      const key = (L.seed ^ hash(part + '/spots')) >>> 0, out = [];
      for (let k = 0; k < 3; k++) {
        const h = mix(key + k), t = 0.15 + (h % 70) / 100, off = ((h >>> 8) % 3) - 1;
        out.push([a[0] + (b[0] - a[0]) * t + off, a[1] + (b[1] - a[1]) * t, r0 + ((h >>> 12) % 3) * 0.5]);
      }
      return out;
    }
    function spotsBox(part, ox, oy, u0, u1, v0, v1, r0) {
      const key = (L.seed ^ hash(part + '/spots')) >>> 0, out = [];
      for (let k = 0; k < 3; k++) {
        const h = mix(key + k);
        out.push([ox + u0 + h % (u1 - u0 + 1), oy + v0 + (h >>> 8) % (v1 - v0 + 1), r0 + ((h >>> 12) % 3) * 0.6]);
      }
      return out;
    }
    function rivet(x, y) { c.tone(x, y, 4); c.tone(x, y + 1, 0); }
    function glyphs(text, x, y, r, l) {
      let cx = x;
      for (const ch of text) {
        const g = FONT[ch] || FONT[' '];
        for (let k = 0; k < 15; k++) if (g[k] === '1') c.set(cx + k % 3, y + (k / 3 | 0), r, l);
        cx += 4;
      }
    }
    function hazard(m) { each(m, (x, y) => { if ((x + y) % 4 < 2) c.recolor(x, y, HAZARD); else c.recolor(x, y, STEEL, 1); }); }

    // ----------------------------------------------------------- back layer
    function backLayer() {
      const x0 = CX + bx, y0 = by;
      if (L.topper === 3) { // exhaust stack rising behind the rear shoulder
        c.fill(cap(M(), x0 - 7, y0 + 22, x0 - 11, y0 + 9, 1.3), CHROME, { band: 1, chrome: true });
        c.fill(rect(M(), x0 - 13, y0 + 7, 4, 2), STEEL, { band: 1, sep: true });
        c.set(x0 - 12, y0 + 7, STEEL, 0); c.set(x0 - 11, y0 + 7, STEEL, 0);
        if (L.quirk === 8) { // a flower in the exhaust
          c.fill(cap(M(), x0 - 11, y0 + 7, x0 - 11, y0 + 4, 0.5), LEAF, { flat: 2 });
          c.fill(ell(M(), x0 - 11, y0 + 3, 1.6, 1.4), PETAL, { band: 1 });
          c.set(x0 - 11, y0 + 3, GOLD, 4); c.set(x0 - 12, y0 + 5, LEAF, 3);
        }
      }
      if (L.shoulders === 'Parcel box') { // courier: a parcel strapped to the back
        const m = rect(M(), x0 - 13, y0 + 14, 8, 9);
        c.fill(m, BOX, { band: 1 });
        for (let y = 14; y < 23; y++) c.set(x0 - 10, y0 + y, TAPE, 3);
        c.set(x0 - 12, y0 + 16, WHITE, 2); c.set(x0 - 12, y0 + 17, WHITE, 2); c.set(x0 - 13 + 1, y0 + 20, BOX, 0);
      }
      if (L.shoulders === 'Wok') { // kitchen unit: a wok worn on the back like a shell
        const m = ell(M(), x0 - 8, y0 + 21, 4.5, 6);
        c.fill(m, DARK, { band: 1 });
        c.fill(cap(M(), x0 - 10, y0 + 15, x0 - 13, y0 + 10, 0.7), LEATHER, { band: 1 });
        c.tone(x0 - 7, y0 + 18, 3); c.tone(x0 - 7, y0 + 19, 3);
      }
      if (L.shoulders === 'Robe') { // boxer: the back of a satin robe and its hood
        const m = rows(M(), x0 - B.sh - 1, y0 + 15, [[1, 6], [0, 6], [0, 5], [0, 5], [0, 5], [0, 5], [0, 5], [0, 5], [0, 5], [0, 5], [0, 5], [0, 5], [0, 5], [0, 5], [0, 5], [0, 5], [1, 5], [1, 5]]);
        c.fill(m, Tr, { band: 2 });
        c.fill(ell(M(), x0 - 4, y0 + 15, 4, 2), Tr, { band: 1 });
      }
    }

    // ---------------------------------------------------------------- legs
    function leg(side) {
      const j = legJoints(side), R = side ? same : back, part = side ? 'lead-leg' : 'rear-leg';
      const { hip, knee, ankle } = j;
      const along = (t, a = knee, b = ankle) => lerp(a, b, t);
      const heavyShin = kit === 4 || kit === 10 ? 0.4 : 0;
      shell(cap(M(), hip[0], hip[1], knee[0], knee[1], B.thigh - thin), part, R, { sep: side === 1, ox: hip[0], oy: hip[1] }, spotsAlong(part + 't', hip, knee, 1.2));
      shell(cap(M(), knee[0], knee[1], ankle[0], ankle[1], B.shin - thin + heavyShin), part, R, { band: 1, sep: true, ox: knee[0], oy: knee[1] }, spotsAlong(part + 's', knee, ankle, 1.1));
      // A shin plate seam and rivet.
      const sp = along(0.55);
      c.tone(sp[0] + 1, sp[1], 4); c.tone(sp[0] + 1, sp[1] + 1, 0);
      // Exposed knee: a steel joint with a bolt, a piston behind it.
      const kr = Math.max(1.6, B.shin - 0.8);
      c.fill(ell(M(), knee[0], knee[1], kr, kr), R(STEEL), { band: 1, sep: true });
      c.set(knee[0] + 1, knee[1] - 1, R(STEEL), 4); c.set(knee[0], knee[1], R(STEEL), 3);
      const pa = along(0.5, hip, knee), pb = along(0.5);
      c.fill(cap(M(), pa[0] - 2, pa[1], pb[0] - 2, pb[1], 0.5), R(CHROME), { flat: 3, clip: true });
      // Cloth over the legs.
      if (LEGWEAR) {
        const [r, th, sh] = LEGWEAR;
        const end = sh ? along(sh) : along(th, hip, knee), wide = kit === 8 || kit === 0 ? 0.9 : kit === 11 ? 1.2 : 0.6;
        const m = cap(M(), hip[0], hip[1], ...(sh ? knee : end), B.thigh + wide);
        if (sh) cap(m, knee[0], knee[1], ...end, B.shin + wide * (kit === 8 ? 1.4 : 1));
        c.fill(m, R(r), { band: 2, sep: true });
        // Tattered or rolled hem.
        for (let k = -3; k <= 3; k += 2) if (kit === 0 || kit === 9 || kit === 3) c.set(end[0] + k, end[1] + 2, R(r), 1);
        if (kit === 3 || kit === 7) for (let k = -3; k <= 3; k++) if (c.filled(end[0] + k, end[1] + 1)) c.set(end[0] + k, end[1] + 1, R(r), 3);
        const fold = along(0.5, hip, knee); c.tone(fold[0], fold[1], 1); c.tone(fold[0] + 1, fold[1] + 1, 1);
        if (kit === 8) { const a = along(0.3); c.tone(a[0] - 1, a[1], 3); }
      }
      // Gear on the shins.
      if (kit === 5 || kit === 10) { // boots
        c.fill(cap(M(), ...along(kit === 5 ? 0.3 : 0.5), ...ankle, B.shin + 0.5), R(kit === 5 ? Sc : DARK), { band: 1, sep: true });
        for (let t = 0.6; t < 0.95; t += 0.2) { const p = along(t); c.set(p[0] + 1, p[1], kit === 10 ? WHITE : R(Tr), 3); }
        if (kit === 5) c.fill(ell(M(), knee[0] + 1, knee[1], 2.4, 2.2), R(Tr), { sep: true });
      } else if (kit === 11) { // hazard-striped shin guards and ankle wraps
        const g = cap(M(), ...along(0.3), ...along(0.7), B.shin + 0.3);
        c.fill(g, R(STEEL), { band: 1, sep: true }); hazard(g);
        c.fill(cap(M(), ...along(0.82), ...ankle, B.shin + 0.2), R(WRAP), { band: 1 });
      } else if (kit === 6) { // trooper: armour plates on thigh and shin
        const tp = cap(M(), ...along(0.25, hip, knee), ...along(0.55, hip, knee), B.thigh - 0.6);
        shell(tp, part + 'p', R, { band: 1, sep: true, ox: hip[0], oy: hip[1] }, [], L.plate);
        const sg = cap(M(), ...along(0.4), ...along(0.7), B.shin - 0.7);
        shell(sg, part + 'q', R, { band: 1, sep: true, ox: knee[0], oy: knee[1] }, [], L.plate);
      }
      foot(j, side, R, part);
    }

    function foot(j, side, R, part) {
      const [ax, ay] = j.ankle, m = M(), w = L.build === 2 ? 1 : 0;
      let sole = null;
      if (j.foot === 'kick') { rect(m, ax - 1, ay - 2, 5 + w, 5); rect(m, ax + 2, ay - 3, 3, 1); sole = [ax + 4 + w, ay - 3, 1, 6]; }
      else if (j.foot === 'tuck') { rect(m, ax - 2, ay - 1, 5, 4); rect(m, ax + 2, ay + 2, 2, 2); }
      else if (j.foot === 'back') { rect(m, ax - 4, ay - 1, 6, 3); }
      else { rows(m, ax, ay - 1, [[-2, 2], [-2, 3], [-3, 4 + w], [-3, 5 + w], [-3, 5 + w]]); sole = [ax - 3, ay + 3, 9 + w, 1]; }
      const boot = kit === 5 ? Sc : kit === 10 ? DARK : kit === 1 ? WRAP : null;
      if (boot) c.fill(m, R(boot), { band: 1, sep: true });
      else shell(m, part, R, { band: 1, sep: true, ox: ax, oy: ay });
      if (sole) for (let yy = sole[1]; yy < sole[1] + sole[3]; yy++) for (let xx = sole[0]; xx < sole[0] + sole[2]; xx++) {
        if (c.filled(xx, yy)) c.set(xx, yy, R(boot === WRAP ? WRAP : STEEL), boot === WRAP ? 3 : 1);
      }
      if (j.foot === 'flat') {
        if (kit === 1) { c.set(ax, ay + 1, R(Tr), 2); c.set(ax + 1, ay + 1, R(Tr), 2); c.set(ax + 2, ay + 2, R(Tr), 3); }
        else { c.tone(ax + 1, ay, 4); c.tone(ax - 1, ay + 1, 0); c.tone(ax + 3, ay + 2, 3); }
      }
      // The ankle joint.
      c.set(ax, ay - 1, R(STEEL), 1); c.set(ax + 1, ay - 1, R(STEEL), 3);
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

    function torso() {
      const x0 = CX + bx, y0 = by;
      const t = (x, y, l) => c.tone(x0 + x, y0 + y, l), s = (x, y, r, l) => c.set(x0 + x, y0 + y, r, l);
      const sh = B.sh, heavy = L.build === 2;
      // Pelvis block, then an exposed midsection of steel ribs, then the chest.
      shell(rect(M(), x0 - B.waist, y0 + 28, B.waist * 2 + 2, 6), 'pelvis', same, { band: 2, ox: x0, oy: y0 });
      const mid = and(torsoMask(), rect(M(), 0, y0 + 22, SIZE, 7));
      c.fill(mid, STEEL, { band: 1 });
      for (let y = 23; y <= 28; y++) for (let x = -B.waist - 1; x <= B.waist + 2 + B.belly; x++) if (c.filled(x0 + x, y0 + y) && y % 2) t(x, y, x > 2 ? 3 : 2);
      for (let y = 23; y <= 28; y++) { t(1, y, 0); t(2, y, 4); }
      const chestEnd = heavy ? 25 : 22;
      const chest = and(torsoMask(), rect(M(), 0, y0 + 15, SIZE, chestEnd - 15 + 1));
      shell(chest, 'torso', same, { band: 2, sep: true, ox: x0, oy: y0 }, spotsBox('torso', x0, y0, -sh + 2, sh - 1, 16, chestEnd - 1, 1.4));
      if (heavy) { // a round belly plate
        const belly = ell(M(), x0 + 3, y0 + 27, B.waist + 1, 3);
        shell(belly, 'torso', same, { band: 1, sep: true, ox: x0, oy: y0 }, spotsBox('belly', x0, y0, -2, 8, 25, 29, 1.2));
        for (let x = -3; x <= 9; x += 4) rivet(x0 + x, y0 + 26);
      }
      // Seams, rivets, a vent and a status light.
      for (let y = 17; y < chestEnd; y++) t(1, y, 1);
      t(1, 16, 0);
      rivet(x0 - sh + 3, y0 + 17); rivet(x0 + sh - 1, y0 + 17); rivet(x0 - sh + 4, y0 + chestEnd - 2); rivet(x0 + sh - 2, y0 + chestEnd - 2);
      for (let x = 4; x <= 6; x++) { t(x, 20, 0); t(x, 21, 3); }
      s(-2, 19, G, eye); s(-3, 19, G, 1);
      if (L.pattern === 'Racing stripe') for (let y = 16; y < chestEnd; y++) { s(-1, y, Tr, 3); s(0, y, Tr, 2); }
      else if (L.pattern === 'Stencil number') glyphs(L.designation.slice(-2), x0 - sh + 3, y0 + 18, STEEL, 0);
      else if (L.pattern === 'Emblem') emblem(x0 + 3, y0 + 16);
      gearTorso(x0, y0, t, s);
    }

    function gearTorso(x0, y0, t, s) {
      const sh = B.sh;
      if (kit === 0) { // torn gi jacket, open wide over the chest plate
        const g = minus(torsoMask(), rows(M(), x0, y0 + 15, [[-2, 5], [-1, 5], [-1, 5], [0, 5], [0, 5], [0, 4], [1, 4], [1, 3], [1, 3], [2, 3]]));
        minus(g, rect(M(), 0, y0 + 25, SIZE, 10));
        c.fill(g, Mn, { band: 2, sep: true });
        for (let k = 0; k <= 9; k++) { const x = -3 + Math.round(k * 0.5); s(x, 15 + k, Mn, 3); }
        for (let x = -sh; x <= sh + 1; x += 2) if (c.filled(x0 + x, y0 + 24)) s(x, 25, Mn, 1); // tattered hem
        t(-5, 22, 1); t(-4, 23, 1); t(6, 21, 1);
      } else if (kit === 1) { // courier: a satchel strap across the chest
        c.fill(and(cap(M(), x0 - sh + 1, y0 + 16, x0 + sh, y0 + 27, 0.9), torsoMask()), Sc, { band: 1, sep: true });
        s(4, 23, GOLD, 3);
      } else if (kit === 2) { // security vest with a badge
        const v = minus(and(torsoMask(), rect(M(), 0, y0 + 15, SIZE, 13)), rows(M(), x0, y0 + 15, [[-1, 3], [-1, 3], [0, 3], [0, 2], [0, 2], [1, 2]]));
        c.fill(v, Sc, { band: 2, sep: true });
        for (let y = 21; y <= 27; y++) t(1, y, 0);
        for (const [x, y, l] of [[4, 18, 4], [3, 19, 3], [4, 19, 3], [5, 19, 3], [4, 20, 2], [3, 21, 1], [5, 21, 1]]) s(x, y, GOLD, l);
        for (let x = -5; x <= -2; x++) s(x, 24, Sc, 3); // pocket
      } else if (kit === 3) { // overalls bib with straps
        c.fill(and(rows(M(), x0 - 5, y0 + 20, [[0, 10], [0, 10], [0, 10], [0, 11], [0, 11], [0, 11], [0, 11], [0, 11], [0, 11]]), torsoMask()), Mn, { band: 1, sep: true });
        c.fill(cap(M(), x0 - 4, y0 + 20, x0 - sh + 3, y0 + 15, 0.6), Mn, { band: 1 });
        c.fill(cap(M(), x0 + 5, y0 + 20, x0 + sh - 2, y0 + 15, 0.6), Mn, { band: 1 });
        s(-4, 20, GOLD, 4); s(5, 20, GOLD, 4); for (let x = -2; x <= 3; x++) s(x, 22, Mn, 3); s(-2, 23, Mn, 1); s(3, 23, Mn, 1);
      } else if (kit === 6) { // trooper: webbing straps and a chest plate stencil
        c.fill(and(cap(M(), x0 - sh + 2, y0 + 15, x0 + 5, y0 + 28, 0.8), torsoMask()), DARK, { band: 1 });
        c.fill(and(cap(M(), x0 + sh - 1, y0 + 15, x0 - 3, y0 + 28, 0.8), torsoMask()), DARK, { band: 1 });
        for (let x = 5; x <= 7; x++) s(x, 17, HAZARD, 3);
      } else if (kit === 7) { // apron over the chest and a mandarin collar
        c.fill(and(rows(M(), x0 - 4, y0 + 18, [[1, 8], [0, 9], [0, 9], [0, 10], [0, 10], [-1, 11], [-1, 11], [-1, 11], [-1, 12], [-1, 12], [-1, 12], [-1, 12], [-1, 12]]), torsoMask()), WRAP, { band: 1, sep: true });
        for (let x = -3; x <= 4; x++) s(x, 15, Tr, x > 1 ? 3 : 2);
        s(1, 24, Tr, 1); s(2, 25, Tr, 1); s(4, 27, TOAST, 1); // a sauce stain
        c.fill(cap(M(), x0 - 3, y0 + 18, x0 - sh + 3, y0 + 15, 0.5), WRAP, { flat: 2 });
      } else if (kit === 8) { // dance-bot: a speaker cone built into the chest
        c.fill(ell(M(), x0 + 3, y0 + 19, 3, 3), STEEL, { band: 1, sep: true });
        c.fill(ell(M(), x0 + 3, y0 + 19, 1.6, 1.6), DARK, { band: 1 });
        s(3, 19, CHROME, 3); s(4, 18, CHROME, 4); s(0, 17, G, eye); s(6, 17, G, eye);
      } else if (kit === 9) { // monk: robe over one shoulder and prayer beads of hex nuts
        const drape = and(cap(M(), x0 - 6, y0 + 15, x0 + 7, y0 + 29, 3.2), torsoMask());
        c.fill(drape, L.robe, { band: 1, sep: true });
        for (let k = 0; k < 4; k++) { t(-3 + k * 3, 19 + k * 3, 1); t(-2 + k * 3, 20 + k * 3, 3); }
        for (const [x, y] of [[-4, 16], [-4, 18], [-3, 20], [-2, 22], [0, 23], [2, 24], [4, 23], [6, 22], [7, 20], [7, 18], [6, 16]]) { s(x, y, CHROME, 3); s(x + 1, y, CHROME, 1); }
      } else if (kit === 11 || kit === 4) { // hazard stripes on the chest plate edge
        const g = and(rect(M(), 0, y0 + 15, SIZE, 2), torsoMask());
        minus(g, rect(M(), x0 - 3, y0 + 14, 8, 4));
        hazard(g);
      }
      if (L.shoulders === 'Robe') { // open robe fronts down both sides
        c.fill(and(rows(M(), x0 - sh, y0 + 15, [[0, 3], [0, 3], [0, 3], [0, 3], [0, 3], [0, 3], [0, 3], [0, 3], [1, 3], [1, 3], [2, 4], [3, 5], [3, 5], [3, 5], [3, 5], [3, 5]]), torsoMask()), Tr, { band: 1, sep: true });
        c.fill(and(rows(M(), x0 + sh - 3, y0 + 15, [[0, 4], [0, 4], [0, 4], [0, 4], [1, 4], [1, 4], [1, 4], [1, 3], [0, 2], [-1, 1], [-2, 0], [-3, -1], [-3, -1], [-3, -1]]), torsoMask()), Tr, { band: 1, sep: true });
      }
    }

    function emblem(x, y) {
      const E_ = [
        [[1, 0], [2, 0], [0, 1], [1, 1], [2, 1], [3, 1], [0, 2], [1, 2], [2, 2], [3, 2], [1, 3], [2, 3]],
        [[1, 0], [2, 0], [0, 1], [3, 1], [0, 2], [2, 2], [3, 2], [1, 3], [2, 3]],
        [[1, 0], [0, 1], [2, 1], [1, 2], [1, 1]],
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
      if (kit === 1 || kit === 2 || kit === 6) r = kit === 6 ? DARK : LEATHER;
      if (kit === 3) { r = LEATHER; h = 1; top = 29; }
      if (kit === 4) { r = Mn; top = 27; h = 5; }
      if (kit === 5 || kit === 10 || kit === 11) { r = Tr; h = kit === 5 ? 1 : 3; }
      if (kit === 7) h = 3;
      if (kit === 8) { h = 1; top = 29; }
      if (kit === 9) r = Tr;
      // Shorts and skirts hang from the pelvis first.
      if (LEGWEAR) c.fill(rect(M(), x0 - B.waist, y0 + 29, B.waist * 2 + 2 + (B.belly ? 1 : 0), 5), LEGWEAR[0], { band: 2 });
      const m = rect(M(), x0 - w, y0 + top, w * 2 + 2 + (B.belly ? 1 : 0), h);
      c.fill(m, r, { band: 1, sep: true });
      const sash = SASHES[L.sash];
      for (let x = -w; x <= w + 1; x++) for (let y = top; y < top + h; y++) {
        if (sash === 'Striped' && (x + 40) % 3 === 0) c.shift(x0 + x, y0 + y, 1);
        if (sash === 'Checked' && (x + y + 40) % 2 === 0 && h > 1) c.shift(x0 + x, y0 + y, -1);
        if (sash === 'Stitched' && y === top + (h > 2 ? 1 : 0) && x % 2 === 0) c.shift(x0 + x, y0 + y, 2);
      }
      if (kit === 0 || kit === 7) { // knot and hanging tails
        s(3, top, r, 3); s(4, top, r, 3); s(3, top + 1, r, 1); s(4, top + 1, r, 2);
        const tails = cap(M(), x0 + 3, y0 + top + h, x0 + 2, y0 + top + h + 5, 0.8);
        cap(tails, x0 + 5, y0 + top + h, x0 + 6, y0 + top + h + 4, 0.8);
        c.fill(tails, r, { band: 1, sep: true });
      }
      if (kit === 1 || kit === 2 || kit === 6 || kit === 3) { s(3, top, CHROME, 4); s(4, top, CHROME, 3); s(3, top + 1, CHROME, 2); s(4, top + 1, CHROME, 1); }
      if (kit === 2) { // a flashlight on the belt
        c.fill(rect(M(), x0 - w - 1, y0 + top + 1, 2, 5), DARK, { band: 1, sep: true });
        s(-w - 1, top + 6, HAZARD, 4); s(-w, top + 6, HAZARD, 3);
      }
      if (kit === 4) { // mawashi front and hanging cords
        c.fill(rect(M(), x0 + 1, y0 + top + h, 5, 3), Mn, { band: 1, sep: true });
        for (let x = 0; x <= 7; x += 2) for (let y = top + h; y < top + h + 6; y++) if (!c.filled(x0 + x, y0 + y) || y > top + h + 2) c.set(x0 + x, y0 + y, Sc, y === top + h + 5 ? 1 : 2);
      }
      if (kit === 8) { // capoeira cord
        const e = cap(M(), x0 + 4, y0 + top + 1, x0 + 3, y0 + top + 6, 0.6); cap(e, x0 + 5, y0 + top + 1, x0 + 6, y0 + top + 5, 0.6);
        c.fill(e, Tr, { band: 1 });
      }
      if (kit === 7) { // apron skirt
        c.fill(rows(M(), x0 - 3, y0 + top + h, [[0, 10], [0, 10], [0, 10], [-1, 10], [-1, 11], [-1, 11]]), WRAP, { band: 1, sep: true });
      }
      if ((kit === 5 || kit === 10 || kit === 11 || kit === 4) && L.pattern === 'Emblem') emblem(x0 + 1, y0 + top + h + 1);
    }

    function neck() {
      const top = [CX + 1 + dx + hx, 14 + dy + hy - jump], bot = [CX + 1 + bx, 18 + by];
      const m = cap(M(), bot[0], bot[1], top[0], top[1], Math.max(1.8, B.neck - 0.5));
      c.fill(m, STEEL, { band: 1 });
      each(m, (x, y) => { if ((y - top[1]) % 2 === 0) c.tone(x, y, x > top[0] ? 4 : 3); });
      c.set(bot[0] - 2, bot[1] - 2, CABLE, 2); c.set(bot[0] - 2, bot[1] - 3, CABLE, 3);
    }

    // ---------------------------------------------------------------- arms
    function arm(side) {
      const state = side ? lead : rear == null ? 'guard' : rear;
      const table = side ? LEAD : REAR;
      let spec = table[state] || table.guard[L.stance];
      if (state === 'guard' || spec === table.guard) spec = table.guard[L.stance];
      const sh = shoulders[side], R = side ? same : back, part = side ? 'lead-arm' : 'rear-arm';
      const el = [sh[0] + spec[0], sh[1] + spec[1]], fh = [sh[0] + spec[2], sh[1] + spec[3]];
      shell(cap(M(), sh[0], sh[1], el[0], el[1], B.upper - thin), part, R, { sep: true, ox: sh[0], oy: sh[1] }, spotsAlong(part + 'u', sh, el, 1.1));
      shell(cap(M(), el[0], el[1], fh[0], fh[1], B.fore + 0.2 - thin), part, R, { band: 1, sep: true, ox: el[0], oy: el[1] }, spotsAlong(part + 'f', el, fh, 1.1));
      // Exposed elbow: a bolted steel joint and a piston along the underside.
      const er = Math.max(1.5, B.fore - 1);
      c.fill(ell(M(), el[0], el[1], er, er), R(STEEL), { band: 1, sep: true });
      c.set(el[0] + 1, el[1] - 1, R(STEEL), 4); c.set(el[0], el[1], R(STEEL), 3);
      const pa = lerp(sh, el, 0.45), pb = lerp(el, fh, 0.55);
      c.fill(cap(M(), pa[0], pa[1] + 1, pb[0], pb[1] + 1, 0.5), R(CHROME), { flat: 3, clip: true });
      // A shoulder cap plate over the socket.
      const capM = ell(M(), sh[0] + (side ? 1 : -1), sh[1] - 1, B.upper + 0.4, B.upper - 0.2);
      if (L.shoulders === 'Armour plate' || L.shoulders === 'Hazard pads') {
        const p = ell(M(), sh[0] + (side ? 1 : -1), sh[1] - 1, B.upper + 1.2, B.upper);
        shell(p, part + 'p', R, { band: 1, sep: true, ox: sh[0], oy: sh[1] }, [], kit === 6 ? L.plate : L.partMat[part]);
        if (L.shoulders === 'Hazard pads') hazard(p);
        else if (side) c.set(sh[0] + 2, sh[1] - 2, R(HAZARD), 3);
      } else {
        shell(capM, part, R, { band: 1, sep: true, ox: sh[0], oy: sh[1] });
        rivet(sh[0] + (side ? 2 : -1), sh[1] - 1);
      }
      if (kit === 11) { // prajiad armband
        const e = lerp(sh, el, 0.6);
        c.fill(cap(M(), e[0], e[1], e[0], e[1], B.upper + 0.2), R(Tr), { band: 1 });
      }
      if (kit === 0) { // torn gi sleeve over the shoulder
        const e = lerp(sh, el, 0.45);
        c.fill(cap(M(), sh[0], sh[1], e[0], e[1], B.upper + 0.8), R(Mn), { band: 2, sep: true });
      }
      const near = t => lerp(fh, el, t);
      const wrist = (r, t0, t1, extra = 0.3) => c.fill(cap(M(), ...near(t0), ...near(t1), B.fore + extra), R(r), { band: 1, sep: true });
      const g = L.gloves;
      if (g === 'Tape wraps' || g === 'Hand wraps') wrist(WRAP, 0.25, 0.45, 0.2);
      if (g === 'Work gloves' || g === 'Fingerless gloves') wrist(g === 'Work gloves' ? LEATHER : DARK, 0.25, 0.4, 0.4);
      hand(fh, spec[4] || 'fist', side, R, part);
    }

    function hand([hx0, hy0], type, side, R, part) {
      const g = L.gloves, heavy = B.fist;
      if (g === 'Boxing gloves') {
        c.fill(ell(M(), hx0 + 0.5, hy0, 4, 3.6), R(Tr), { band: 2, sep: true });
        c.set(hx0 - 3, hy0 + 2, R(WRAP), 2); c.set(hx0 - 2, hy0 + 3, R(WRAP), 2);
        c.set(hx0 + 1, hy0 - 2, R(Tr), 4); c.tone(hx0, hy0 + 1, 1); c.tone(hx0 - 1, hy0 + 1, 1);
        return;
      }
      if (g === 'Oven mitt' && side === 1) {
        c.fill(rows(M(), hx0, hy0 - 3, [[-2, 2], [-3, 3], [-3, 4], [-3, 4], [-3, 4], [-3, 3], [-2, 2]]), R(Tr), { band: 2, sep: true });
        c.set(hx0 + 3, hy0 - 3, R(Tr), 3); c.set(hx0 + 4, hy0 - 4, R(Tr), 4);
        for (let x = -2; x <= 2; x += 2) c.tone(hx0 + x, hy0, 1);
        return;
      }
      const cover = g === 'Work gloves' ? LEATHER : g === 'Tape wraps' || g === 'Hand wraps' ? WRAP : null;
      if (type === 'open') { // three claw fingers
        const m = rows(M(), hx0, hy0 - 2, [[-1, 3], [-2, 4 + heavy], [-2, 4 + heavy], [-2, 3]]);
        rect(m, hx0 - 1, hy0 - 3, 2, 1);
        if (cover && cover !== WRAP) c.fill(m, R(cover), { band: 1, sep: true }); else shell(m, part, R, { band: 1, sep: true, ox: hx0, oy: hy0 });
        c.tone(hx0 + 2, hy0 - 1, 0); c.tone(hx0 + 2, hy0 + 1, 0); c.tone(hx0 + 1, hy0, 1);
        return;
      }
      const m = rows(M(), hx0, hy0 - 3, [[-2, 2 + heavy], [-3, 3 + heavy], [-3, 3 + heavy], [-3, 3 + heavy], [-3, 3 + heavy], [-2, 2 + heavy]]);
      if (cover) c.fill(m, R(cover), { band: 1, sep: true }); else shell(m, part, R, { band: 1, sep: true, ox: hx0, oy: hy0 });
      // Blocky knuckle segments facing forward, a bolt on the back of the hand.
      const k = hx0 + heavy;
      for (let y = hy0 - 2; y <= hy0 + 1; y++) c.tone(k + 1, y, 1);
      c.tone(k + 2, hy0 - 3, 4); c.tone(k + 2, hy0 - 1, 3); c.tone(k + 2, hy0 + 1, 3); c.tone(k + 3, hy0 - 2, 4);
      c.tone(hx0 - 1, hy0 - 1, 4); c.tone(hx0 - 1, hy0, 0);
      if (g === 'Fingerless gloves') for (let x = hx0 - 1; x <= k + 3; x++) c.tone(x, hy0 - 3, 3);
    }

    // ---------------------------------------------------------------- head
    function headSil() {
      return L.masked ? MASK_SIL : HEAD_SIL[L.head];
    }
    function head() {
      const R = headMat.R;
      const hm = rows(M(), HX, HY, headSil());
      if (L.topper === 1 || L.topper === 2) antenna();
      if (L.masked) {
        c.fill(hm, Mn, { band: 2 });
        mask();
      } else {
        c.fill(hm, R, { band: 2, chrome: headMat.kind === 'chrome' });
        weather(hm, headMat, R, 'head', spotsBox('head', HX, HY, 1, 11, 1, 10, 1.2), HX, HY);
        [visor, crt, skull, smile, bucket, lens, radio][L.head](R);
      }
      headgear();
      if (L.quirk === 7) headphones();
      if (L.quirk === 9) { hd(2, 2, TOAST, 3); hd(3, 2, TOAST, 4); hd(4, 3, TOAST, 3); hd(3, 3, TOAST, 2); hd(3, 2, WHITE, 3); }
      if (L.quirk === 1) cone();
      if (L.topper === 4) rotor();
    }
    function ear() { hd(1, 5, STEEL, 1); hd(2, 5, STEEL, 3); hd(1, 6, STEEL, 0); hd(2, 6, STEEL, 2); hd(2, 4, STEEL, 4); }

    function visor(R) {
      for (let x = 5; x <= 13; x++) { hd(x, 3, R, 0); hd(x, 4, G, x >= 10 && x <= 12 ? shine : eye); hd(x, 5, G, blink ? 0 : 2); }
      hd(12, 4, blink ? G : WHITE, blink ? 1 : 3);
      for (let x = 6; x <= 12; x++) hd(x, 2, R, 3);
      for (const x of [9, 11]) { hd(x, 8, R, 0); hd(x, 9, R, 0); }
      hd(10, 8, R, 3); hd(12, 8, R, 3);
      ear();
    }
    function crt(R) {
      for (let y = 1; y <= 10; y++) for (let x = -1; x <= 3; x++) c.shift(HX + x, HY + y, -1);
      for (const y of [3, 5, 7]) for (let x = 0; x <= 2; x++) hd(x, y, R, 0);
      const SCR = [mixHex(G[0], '#000000', 0.55), mixHex(G[0], '#000000', 0.3), G[0], G[1], G[2]];
      for (let y = 2; y <= 8; y++) for (let x = 5; x <= 12; x++) hd(x, y, SCR, y % 2 ? 0 : 1);
      hd(12, 2, SCR, 4); hd(11, 2, SCR, 3);
      if (blink) { hd(6, 5, G, 3); hd(7, 5, G, 3); hd(10, 5, G, 3); hd(11, 5, G, 3); }
      else { hd(7, 4, G, 4); hd(7, 5, G, 3); hd(10, 4, G, 4); hd(10, 5, G, 3); }
      hd(7, 7, G, 3); hd(8, 8, G, 3); hd(9, 8, G, 3); hd(10, 7, G, 3);
      hd(10, 10, CHROME, 4); hd(12, 10, CHROME, 3); hd(7, 10, R, 0); hd(8, 10, R, 0);
    }
    function skull(R) {
      for (const [x, y] of [[6, 4], [7, 4], [6, 5], [7, 5], [6, 6], [10, 4], [11, 4], [12, 4], [10, 5], [11, 5], [12, 5], [11, 6]]) hd(x, y, STEEL, 0);
      hd(7, 5, G, shine); hd(11, 5, G, shine); hd(12, 5, G, eye); hd(6, 5, G, blink ? 0 : 1);
      hd(13, 7, STEEL, 0); hd(12, 8, STEEL, 0); hd(8, 7, R, 1); hd(9, 8, R, 1);
      for (let x = 6; x <= 12; x++) { hd(x, 9, x % 2 ? R : STEEL, x % 2 ? 4 : 0); if (x < 12) hd(x, 10, x % 2 ? STEEL : R, x % 2 ? 0 : 3); }
      hd(3, 3, R, 4); hd(3, 4, R, 0); hd(9, 2, R, 4);
    }
    function smile(R) {
      c.fill(ell(M(), HX + 9.5, HY + 6, 4, 4.6), ENAMEL, { band: 1, sep: true });
      hd(8, 4, G, eye); hd(8, 5, G, shine); hd(11, 4, G, eye); hd(11, 5, G, shine);
      if (blink) { hd(8, 4, ENAMEL, 1); hd(11, 4, ENAMEL, 1); }
      for (const [x, y] of [[7, 7], [8, 8], [9, 8], [10, 8], [11, 8], [12, 7], [7, 2], [8, 2], [11, 2], [12, 2]]) hd(x, y, PAINT_INK);
      hd(7, 6, BLUSH); hd(12, 6, BLUSH);
      ear();
    }
    function bucket(R) {
      for (let x = 0; x <= 13; x++) { c.tone(HX + x, HY + 2, 1); c.tone(HX + x, HY + 9, 1); }
      for (let x = 5; x <= 13; x++) { hd(x, 5, G, x >= 9 && x <= 11 ? shine : eye); hd(x, 6, R, 0); hd(x, 4, R, 0); }
      c.tone(HX + 8, HY + 1, 1); c.tone(HX + 9, HY + 1, 0); c.tone(HX + 4, HY + 7, 3);
      rivet(HX + 3, HY + 3); rivet(HX + 12, HY + 7);
      // A handle arching over the top.
      c.fill(or(or(cap(M(), HX - 1, HY + 5, HX, HY - 1, 0.5), cap(M(), HX, HY - 1, HX + 6, HY - 3, 0.5)), cap(M(), HX + 6, HY - 3, HX + 12, HY - 1, 0.5)), STEEL, { flat: 3 });
      hd(12, 0, STEEL, 2);
    }
    function lens(R) {
      c.fill(ell(M(), HX + 10, HY + 5, 3, 3), STEEL, { band: 1, sep: true });
      c.fill(ell(M(), HX + 10, HY + 5, 1.8, 1.8), G, { flat: blink ? 0 : 2 });
      hd(10, 5, G, shine); hd(11, 4, blink ? G : WHITE, blink ? 1 : 3);
      for (const x of [8, 10, 12]) hd(x, 9, R, 0);
      ear();
    }
    function radio(R) {
      for (let x = 3; x <= 10; x++) hd(x, -2, STEEL, x > 7 ? 3 : 2);
      hd(3, -1, STEEL, 1); hd(10, -1, STEEL, 2);
      hd(7, 3, G, shine); hd(8, 3, G, eye); hd(11, 3, G, shine); hd(12, 3, G, eye);
      for (let y = 5; y <= 9; y++) for (let x = 6; x <= 12; x++) hd(x, y, x % 2 ? R : STEEL, x % 2 ? 3 : 0);
      c.fill(ell(M(), HX + 2.5, HY + 5.5, 1.6, 1.6), CHROME, { band: 1, sep: true });
      hd(2, 5, PAINT_INK); hd(3, 1, R, 4);
    }
    function mask() {
      for (const [x, y] of [[6, 4], [7, 4], [8, 4], [9, 4], [6, 5], [9, 5], [6, 6], [7, 6], [8, 6], [9, 6], [10, 4], [11, 4], [12, 4], [13, 4], [10, 5], [13, 5], [10, 6], [11, 6], [12, 6], [13, 6]]) hd(x, y, Tr, 2);
      hd(7, 5, G, eye); hd(8, 5, G, shine); hd(11, 5, G, eye); hd(12, 5, G, shine);
      for (const [x, y] of [[9, 8], [10, 8], [11, 8], [12, 8], [9, 10], [10, 10], [11, 10], [12, 10], [9, 9], [12, 9]]) hd(x, y, Tr, 2);
      hd(10, 9, STEEL, 0); hd(11, 9, STEEL, 1);
      const g = L.headgear;
      if (g === 'Flame mask') for (const [x, y, l] of [[5, 4, 3], [4, 3, 3], [3, 2, 2], [2, 3, 2], [5, 6, 2], [4, 7, 2], [3, 7, 1], [2, 8, 1], [5, 1, 3], [4, 0, 3]]) hd(x, y, Tr, l);
      if (g === 'Star mask') for (const [x, y] of [[3, 2], [2, 3], [3, 3], [4, 3], [3, 4], [1, 4], [5, 4], [2, 5], [4, 5]]) hd(x, y, Tr, 3);
      if (g === 'Stripe mask') for (let x = -1; x <= 12; x++) { hd(x, x < 4 ? 1 : x < 8 ? 0 : 1, Tr, 3); hd(x, x < 4 ? 2 : x < 8 ? 1 : 2, Tr, 2); }
      for (let y = 5; y <= 9; y += 2) { hd(-1, y, WRAP, 2); hd(0, y + 1, WRAP, 1); }
    }

    function antenna() {
      if (L.topper === 1) {
        c.fill(cap(M(), HX + 3, HY + 1, HX + 1, HY - 4, 0.5), STEEL, { flat: 3 });
        c.fill(ell(M(), HX + 1, HY - 4, 1, 1), CABLE, { band: 1 }); c.set(HX + 1, HY - 5, CABLE, 4);
      } else {
        c.fill(or(cap(M(), HX + 5, HY + 1, HX + 2, HY - 4, 0.5), cap(M(), HX + 7, HY + 1, HX + 10, HY - 4, 0.5)), CHROME, { flat: 3 });
        c.set(HX + 2, HY - 4, CHROME, 4); c.set(HX + 10, HY - 4, CHROME, 4);
      }
    }
    function rotor() {
      c.fill(rect(M(), HX + 5, HY - 3, 2, 3), STEEL, { band: 1 });
      const blade = rect(M(), HX - 1, HY - 4, 15, 1);
      c.fill(blade, CHROME, { flat: 3 });
      hd(5, -4, STEEL, 1); hd(6, -4, STEEL, 2); hd(-1, -4, CHROME, 1); hd(13, -4, CHROME, 4);
    }
    function cone() {
      const m = tri(M(), HX + 6, HY - 5, HX + 2, HX + 10, HY - 1);
      c.fill(m, CONE, { band: 1, sep: true });
      for (let x = 3; x <= 9; x++) if (c.filled(HX + x, HY - 3)) c.set(HX + x, HY - 3, WHITE, x > 6 ? 3 : 2);
      c.fill(rect(M(), HX + 1, HY - 1, 11, 2), CONE, { band: 1, sep: true });
    }
    function headphones() {
      c.fill(or(or(cap(M(), HX + 1, HY + 4, HX + 2, HY - 1, 0.6), cap(M(), HX + 2, HY - 1, HX + 8, HY - 2, 0.6)), cap(M(), HX + 8, HY - 2, HX + 10, HY, 0.6)), DARK, { band: 1 });
      c.fill(ell(M(), HX + 2, HY + 5.5, 1.8, 2.2), DARK, { band: 1, sep: true });
      hd(2, 5, G, eye); hd(3, 4, Tr, 3);
    }

    function headgear() {
      const g = L.headgear;
      const base = rows(M(), HX, HY, headSil());
      const boxy = L.head === 1 || L.head === 6;
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
      const by0 = boxy ? 0 : L.head === 4 ? 2 : 1;
      if (g === 'Hachimaki') band(by0, 2, L.palette === 'Classic white' ? Sc : Tr, true); // never white gi + red band
      else if (g === 'Headband' || g === 'Sweatband') band(by0, g === 'Sweatband' ? 2 : 1, g === 'Sweatband' ? WRAP : Tr, g === 'Headband');
      else if (g === 'Mongkhon') {
        band(by0, 1, Tr, false);
        c.fill(cap(M(), HX - 1, HY + by0, HX - 5, HY - 3, 0.8), Tr, { band: 1 });
        c.set(HX - 3, HY - 1, WRAP, 3); c.set(HX + 5, HY + by0, WRAP, 3);
      } else if (g === 'Bandana') {
        const m = and(rows(M(), HX, HY - 2, [[3, 9], [1, 11], [0, 12], [-1, 13], [-1, 13], [-1, 13]]), rect(M(), 0, 0, SIZE, HY + 3));
        c.fill(m, Tr, { band: 1, sep: true });
        for (let x = 0; x <= 11; x += 3) c.tone(HX + x, HY + (x % 2), 4);
        const t = cap(M(), HX - 1, HY + 1, HX - 5, HY + 4, 0.9); cap(t, HX - 1, HY + 1, HX - 4, HY + 6, 0.8); c.fill(t, Tr, { band: 1 });
      } else if (g === 'Courier cap' || g === 'Backwards cap' || g === 'Security cap') {
        const m = rows(M(), HX, HY - 3, g === 'Security cap' ? [[0, 13], [0, 13], [1, 12], [1, 12]] : [[3, 9], [1, 11], [0, 12], [0, 12]]);
        if (g === 'Backwards cap') rect(m, HX - 4, HY, 4, 1); else rect(m, HX + 10, HY, 6, 1);
        c.fill(m, g === 'Security cap' ? Sc : Mn, { band: 2, sep: true });
        if (g === 'Security cap') { hd(8, -2, GOLD, 4); hd(9, -2, GOLD, 3); hd(8, -1, GOLD, 2); for (let x = 1; x <= 12; x++) hd(x, 0, DARK, 1); }
        else c.set(HX + 6, HY - 3, Tr, 3);
      } else if (g === 'Straw hat') {
        c.fill(rows(M(), HX, HY - 3, [[3, 10], [2, 11], [2, 11]]), STRAW, { band: 1, sep: true });
        c.fill(rect(M(), HX - 4, HY, 22, 1), STRAW, { band: 1, sep: true });
        for (let x = 2; x <= 11; x++) hd(x, -1, Tr, 2);
        for (let x = -3; x <= 17; x += 3) c.tone(HX + x, HY, 1);
      } else if (g === 'Warning beacon') {
        c.fill(rect(M(), HX + 4, HY - 1, 5, 1), STEEL, { band: 1, sep: true });
        c.fill(ell(M(), HX + 6, HY - 2, 1.8, 1.6), HAZARD, { band: 1, sep: true });
        hd(7, -3, HAZARD, 4); hd(6, -2, HAZARD, 3);
      } else if (g === 'Combat helmet' || g === 'Hard hat') {
        const r = g === 'Hard hat' ? HAZARD : L.P;
        const m = rows(M(), HX, HY - 2, [[3, 10], [1, 12], [0, 13], [0, 13], [-1, 14]]);
        if (g === 'Hard hat') rect(m, HX - 2, HY + 2, 18, 1);
        c.fill(m, r, { band: 2, sep: true });
        if (g === 'Hard hat') for (let y = -2; y <= 1; y++) c.tone(HX + 7, HY + y, 3);
        else { c.tone(HX + 5, HY, 0); c.tone(HX + 6, HY, 0); c.set(HX + 9, HY, HAZARD, 3); }
      } else if (g === 'Chef hat') {
        c.fill(rect(M(), HX + 1, HY - 1, 11, 2), WHITE, { band: 1, sep: true });
        c.fill(or(ell(M(), HX + 4, HY - 3, 3, 2), ell(M(), HX + 9, HY - 3, 3, 2)), WHITE, { band: 1, sep: true });
        c.tone(HX + 6, HY - 3, 1);
      } else if (g === 'Head guard') {
        const m = rows(M(), HX, HY - 2, [[3, 9], [1, 11], [0, 12], [-1, 12], [-1, 12], [-1, 5], [-1, 5], [-1, 5], [-1, 4], [0, 5], [0, 5]]);
        c.fill(m, Tr, { band: 2, sep: true });
        for (let y = 0; y <= 8; y += 2) c.tone(HX + 1, HY + y, 1);
      } else if (g === 'Forehead mark') {
        hd(9, 1, Tr, 3); hd(9, 2, Tr, 1); hd(10, 1, Tr, 2);
      }
    }

    // ------------------------------------------------------ front details
    function duck() { // a rubber duck riding on the rear shoulder
      const [sx, sy] = shoulders[0];
      c.fill(ell(M(), sx - 2, sy - 4, 2.4, 1.6), DUCK, { band: 1, sep: true });
      c.fill(ell(M(), sx - 1, sy - 7, 1.5, 1.5), DUCK, { band: 1, sep: true });
      c.set(sx + 1, sy - 7, CONE, 3); c.set(sx + 1, sy - 6, CONE, 2); c.set(sx - 1, sy - 8, INK);
    }
    function front() {
      const x0 = CX + bx, y0 = by, s = (x, y, r, l) => c.set(x0 + x, y0 + y, r, l);
      if (L.shoulders === 'Towel') { // a towel around the neck, both ends hanging down the chest
        const m = or(cap(M(), x0 - 1, y0 + 14, x0 - 4, y0 + 23, 1.3), cap(M(), x0 + 3, y0 + 14, x0 + 5, y0 + 22, 1.3));
        c.fill(m, WHITE, { band: 1, sep: true });
        for (const y of [17, 20]) { c.tone(x0 - 3, y0 + y, 1); c.tone(x0 + 4, y0 + y, 1); }
        s(-5, 23, Tr, 2); s(-4, 23, Tr, 3); s(-3, 23, Tr, 3); s(4, 22, Tr, 2); s(5, 22, Tr, 3); s(6, 22, Tr, 3);
      }
      if (L.quirk === 3) { // necktie
        c.fill(rect(M(), x0 + 1, y0 + 16, 2, 2), Tr, { band: 1, sep: true });
        c.fill(rows(M(), x0 + 1, y0 + 18, [[0, 1], [0, 1], [-1, 1], [-1, 2], [-1, 2], [-1, 2], [0, 1]]), Tr, { band: 1, sep: true });
        c.tone(x0 + 1, y0 + 19, 1); c.tone(x0 + 2, y0 + 21, 1);
      }
      if (L.quirk === 4) { // a toaster slot, toast ready
        for (let x = -2; x <= 3; x++) { s(x, 18, STEEL, 0); s(x, 19, STEEL, 2); }
        c.fill(rows(M(), x0 - 1, y0 + 15, [[0, 3], [0, 3], [0, 3]]), TOAST, { band: 1, sep: true });
        s(-1, 15, TOAST, 1); s(2, 15, TOAST, 1); s(0, 15, TOAST, 0); s(1, 15, TOAST, 0);
      }
      if (L.quirk === 6) { // HELLO MY NAME IS sticker, blank
        c.fill(rect(M(), x0 - 6, y0 + 18, 5, 4), WHITE, { flat: 2, sep: true });
        for (let x = -6; x <= -2; x++) s(x, 18, CABLE, 3);
        s(-5, 20, INK); s(-4, 20, CHIP, 1);
      }
      if (L.quirk === 2) { // duct tape, criss-crossed
        const key = mix(L.seed + 3), ux = -4 + key % 5, uy = 17 + (key >>> 4) % 4;
        c.fill(and(or(cap(M(), x0 + ux - 2, y0 + uy - 1, x0 + ux + 2, y0 + uy + 1, 0.6), cap(M(), x0 + ux - 2, y0 + uy + 1, x0 + ux + 2, y0 + uy - 1, 0.6)), torsoMask()), TAPE, { band: 1 });
      }
    }
  }

  // ---- Collectible card -----------------------------------------------------
  // 64×64: a riveted scrap-metal frame, a kit-specific scrapyard scene, the
  // fighter at 1:1, and a blank name plate. No names or live stats baked in.
  function artwork(identity, body) {
    const L = look(identity), kit = L.kit, a = GLOWS[L.glow][1], seed = roll(identity, 'scene');
    const parts = [];
    const r = (x, y, w, h, c) => { if (w > 0 && h > 0) parts.push(`<path fill="${c}" d="M${x} ${y}h${w}v${h}h-${w}z"/>`); };
    const bands = (list, y0) => { let y = y0; for (const [c, h] of list) { r(2, y, 60, h, c); y += h; } return y; };
    const dither = (y, c) => { for (let x = 2 + (y & 1); x < 62; x += 2) r(x, y, 1, 1, c); };
    const half = (rad, y) => { let w = 0; while ((w + 1) * (w + 1) + y * y <= rad * rad + rad) w++; return w; };
    const circle = (cx, cy, rad, c) => { for (let y = -rad; y <= rad; y++) { const w = half(rad, y); r(cx - w, cy + y, w * 2 + 1, 1, c); } };
    const specks = (n, x0, y0, w, h, c, k = 0) => { let s = seed + k; for (let i = 0; i < n; i++) { s = mix(s + i); r(x0 + s % w, y0 + (s >>> 8) % h, 1, 1, c); } };
    const text = (str, x, y, c) => { for (const ch of str) { const g = FONT[ch] || FONT[' ']; for (let k = 0; k < 15; k++) if (g[k] === '1') r(x + k % 3, y + (k / 3 | 0), 1, 1, c); x += 4; } };
    const hazardBar = (x, y, w, h) => { r(x, y, w, h, '#1a1a1a'); for (let i = 0; i < w; i += 4) r(x + i, y, Math.min(2, w - i), h, '#f2c230'); };
    const rain = c => { let s = seed + 99; for (let i = 0; i < 22; i++) { s = mix(s + i); r(3 + s % 58, 3 + (s >>> 8) % 42, 1, 3, c); } };
    const smog = (y, c) => { r(2, y, 60, 1, c); dither(y + 1, c); };
    r(0, 0, 64, 64, INK);
    const floorY = 50;
    if (kit === 0) { // Collapsed dojo: smoggy sunset through a broken roof
      bands([['#2a1d17', 8], ['#4a2a22', 6], ['#7a3a22', 6], ['#b0552a', 6], ['#d9823a', 22]], 2);
      dither(16, '#7a3a22'); dither(22, '#b0552a'); dither(28, '#d9823a');
      circle(44, 24, 7, '#f2c26a'); for (const y of [23, 26, 28]) r(37, y, 15, 1, '#d9823a');
      r(2, 30, 60, 20, '#3a2418'); for (let x = 2; x < 62; x += 10) { r(x, 30, 1, 20, '#24160f'); r(x + 1, 33, 7, 12, '#8a7456'); r(x + 4, 33, 1, 12, '#5a4a36'); }
      r(13, 36, 3, 4, '#24160f'); r(33, 34, 4, 6, '#24160f'); r(45, 38, 3, 3, '#24160f'); // torn paper screens
      r(2, 28, 60, 2, '#5a2a1e'); r(2, 10, 26, 2, '#24160f'); r(20, 12, 2, 18, '#24160f'); r(30, 6, 2, 8, '#24160f'); // broken beams
      for (let k = 0; k < 8; k++) r(26 + k * 2, 6 + k, 2, 1, '#24160f');
      r(3, 14, 17, 7, '#e7d7b0'); r(3, 20, 17, 1, '#8a3b12'); text('DOJO', 4, 15, '#8a3b12');
      r(2, floorY, 60, 11, '#6e4a30'); for (let y = floorY + 2; y < 61; y += 3) r(2, y, 60, 1, '#553722');
      specks(10, 2, floorY, 60, 5, '#8a3b12');
    } else if (kit === 1) { // Flooded underpass: concrete, acid rain, a pink sign
      r(2, 2, 60, 48, '#16302f'); r(2, 2, 60, 8, '#2a3a3a'); r(2, 10, 60, 2, '#0d1a1a');
      for (const x of [8, 30, 52]) { r(x, 12, 6, 38, '#3a4a48'); r(x, 12, 1, 38, '#5a6a66'); r(x + 5, 12, 1, 38, '#243030'); }
      r(3, 14, 11, 7, '#0d1a1a'); r(4, 15, 9, 5, '#ff4fa0'); text('24', 5, 15, '#0d1a1a');
      r(40, 22, 8, 5, '#0d1a1a'); r(41, 23, 6, 3, '#36e0ff');
      rain('#3aa597');
      r(2, floorY, 60, 11, '#1e3a3c'); for (let y = floorY + 1; y < 61; y += 2) r(4 + (y * 7) % 11, y, 12, 1, '#2e5a5a');
      r(18, floorY + 3, 9, 1, '#ff4fa0'); r(41, floorY + 5, 6, 1, '#36e0ff');
    } else if (kit === 2) { // Dead mall: dark shopfronts, a glowing vending machine
      r(2, 2, 60, 48, '#1e1a24'); r(2, 2, 60, 6, '#2a2432');
      for (let x = 2; x < 62; x += 15) { r(x, 12, 14, 30, '#12101a'); r(x + 1, 13, 12, 18, '#243040'); r(x + 1, 22, 12, 1, '#12101a'); r(x + 7, 13, 1, 18, '#12101a'); }
      r(3, 9, 22, 4, '#3aa597'); text('SALE', 5, 8, '#e8edf2'); r(26, 16, 3, 3, '#12101a'); // crooked sign
      r(46, 18, 10, 24, '#8a2a2a'); r(47, 19, 8, 12, '#ffd27a'); for (let y = 21; y < 31; y += 3) r(47, y, 8, 1, '#c28a3a'); r(48, 34, 6, 3, '#12101a');
      r(2, 42, 60, 8, '#2a2432'); for (let x = 2; x < 62; x += 6) r(x, 42, 3, 1, '#4b5563');
      r(2, floorY, 60, 11, '#3a3440'); for (let x = 2; x < 62; x += 8) { r(x, floorY, 1, 11, '#2a2432'); } r(2, floorY + 5, 60, 1, '#2a2432');
      specks(8, 2, floorY, 60, 10, '#8a3b12');
    } else if (kit === 3) { // Dust-bowl farm: orange sky, broken windmill, dead corn
      bands([['#8a3b12', 10], ['#c2551b', 10], ['#d9823a', 10], ['#e0a060', 18]], 2);
      dither(12, '#c2551b'); dither(22, '#d9823a'); dither(32, '#e0a060');
      circle(16, 18, 5, '#f7d08a');
      r(44, 14, 2, 36, '#3a2418'); r(40, 48, 10, 2, '#3a2418'); for (let k = 0; k < 6; k++) { r(45 - k * 2, 13 - k, 2, 1, '#3a2418'); r(45 + k, 13 + k * 2, 1, 2, '#3a2418'); r(46 + k * 2, 12, 2, 1, '#3a2418'); }
      for (let x = 2; x < 36; x += 4) { r(x, 36, 1, 14, '#6a4a22'); r(x - 1, 38 + (x % 3), 1, 2, '#8a6a32'); r(x + 1, 41 - (x % 2), 1, 2, '#8a6a32'); }
      r(2, 44, 60, 1, '#3a2418'); for (let x = 36; x < 62; x += 6) r(x, 41, 1, 9, '#3a2418');
      r(2, floorY, 60, 11, '#9a6a3a'); specks(20, 2, floorY, 60, 11, '#7a4a22');
    } else if (kit === 4) { // Container yard: stacked rusty containers, a crane
      bands([['#2a1d17', 16], ['#3a2a22', 32]], 2);
      r(40, 4, 2, 30, '#4b5563'); r(20, 4, 36, 2, '#4b5563'); for (let x = 22; x < 56; x += 3) r(x, 6, 1, 1, '#9aa6b2'); r(24, 6, 1, 12, '#9aa6b2'); r(22, 18, 5, 3, '#f2c230');
      const cols = ['#8a3b12', '#3aa597', '#c2551b', '#34507e', '#6b7042'];
      let s = seed; for (let row = 0; row < 3; row++) for (let x = 2 - row * 5; x < 62; x += 14) { s = mix(s + x + row); const c = cols[s % cols.length]; r(Math.max(2, x), 38 - row * 9, Math.min(13, 62 - Math.max(2, x)), 8, c); for (let k = 1; k < 13; k += 2) r(Math.max(2, x) + k, 39 - row * 9, 1, 6, mixHex(c, '#000000', 0.3)); }
      r(2, floorY, 60, 11, '#4a4034'); hazardBar(2, floorY, 60, 2); specks(10, 2, floorY + 3, 60, 8, '#8a3b12');
    } else if (kit === 5) { // Junk arena: tyres, chain ropes, drone crowd
      r(2, 2, 60, 48, '#0d0f12');
      for (let y = 2; y < 50; y++) { const w = 4 + (y >> 2); r(18 - (w >> 1), y, w, 1, '#1d2226'); r(46 - (w >> 1), y, w, 1, '#1d2226'); }
      let s = seed; for (let y = 16; y < 34; y += 3) for (let x = 2 + (y % 2) * 2; x < 62; x += 4) { s = mix(s + x + y); r(x, y, 3, 2, ['#1a1e22', '#22282e', '#15181c'][s % 3]); if (s % 13 === 0) r(x + 1, y, 1, 1, s % 2 ? '#36e0ff' : '#ff4fa0'); }
      for (const y of [37, 42]) for (let x = 2; x < 62; x += 2) r(x, y + (x % 4 ? 0 : 1), 2, 1, '#9aa6b2');
      for (let x = 4; x < 62; x += 9) { circle(x, 47, 3, '#15181c'); r(x - 1, 46, 3, 3, '#2b313b'); }
      r(2, floorY, 60, 11, '#5a4a3a'); r(2, floorY, 60, 1, '#8a7456'); specks(12, 2, floorY + 2, 60, 9, '#3a2a22');
    } else if (kit === 6) { // Bunker ruins: concrete, barbed wire, searchlights
      bands([['#101418', 20], ['#16302f', 28]], 2);
      for (let y = 2; y < 40; y++) { r(12 + (y >> 1), y, 3, 1, '#1e3a38'); r(48 - (y >> 2), y, 2, 1, '#1e3a38'); }
      r(2, 30, 60, 20, '#3a3e38'); r(2, 30, 60, 2, '#555a50'); r(18, 36, 26, 4, '#0d0f12'); r(20, 37, 22, 2, '#1a1e1a');
      for (let x = 2; x < 62; x += 3) { r(x, 27, 2, 1, '#6b7483'); r(x + 1, 26 + (x % 2) * 2, 1, 1, '#6b7483'); }
      for (let x = 4; x < 62; x += 6) { r(x, 44, 5, 3, '#6b7042'); r(x + 2, 41, 5, 3, '#7a8050'); }
      r(4, 32, 11, 7, '#c2551b'); text('NO', 6, 33, '#f2c230');
      r(2, floorY, 60, 11, '#4a4a3e'); specks(14, 2, floorY, 60, 11, '#2e2e26');
    } else if (kit === 7) { // Noodle stall in the rain
      bands([['#101422', 16], ['#1a1830', 32]], 2);
      r(4, 20, 56, 30, '#2a1d17'); r(2, 16, 60, 4, '#8a3b12'); for (let x = 2; x < 62; x += 6) r(x, 16, 3, 4, '#c2551b');
      r(6, 26, 52, 10, '#16100c'); r(8, 28, 48, 6, '#3a2418'); circle(20, 30, 2, '#9aa6b2'); circle(34, 30, 2, '#9aa6b2');
      for (let k = 0; k < 4; k++) r(19 + (k % 2), 22 - k * 2, 1, 2, '#6b7483');
      r(44, 4, 16, 7, '#0d0f12'); text('EAT', 46, 5, '#ff4fa0'); r(45, 11, 14, 1, '#ff4fa0');
      for (let x = 6; x < 62; x += 12) { r(x, 21, 4, 5, '#e0342b'); r(x + 1, 22, 2, 3, '#ff8a5a'); }
      rain('#3a4a6a');
      r(2, floorY, 60, 11, '#2a2a30'); for (let x = 2; x < 62; x += 8) r(x, floorY + 3, 6, 1, '#3a3a44'); r(8, floorY + 6, 10, 1, '#ff4fa0');
    } else if (kit === 8) { // Neon plaza: cracked tiles under a flickering arch
      bands([['#140c24', 24], ['#1e1030', 24]], 2);
      for (let y = 6; y < 50; y++) { const d = Math.abs(y - 28), w = d < 22 ? half(22, d) : 0; if (w) { r(32 - w - 1, y, 1, 1, '#ff4fa0'); r(32 + w, y, 1, 1, '#36e0ff'); } }
      r(10, 8, 44, 1, '#ff4fa0'); r(10, 9, 44, 1, '#8a2a5a');
      specks(16, 3, 3, 58, 20, '#6a5a9a');
      r(5, 30, 6, 20, '#2a1a3a'); r(53, 34, 6, 16, '#2a1a3a'); r(6, 31, 4, 3, '#36e0ff'); r(54, 35, 4, 3, '#ff4fa0');
      r(2, floorY, 60, 11, '#3a2a4a'); for (let x = 2; x < 62; x += 6) r(x, floorY, 1, 11, '#2a1a3a'); for (let y = floorY + 3; y < 61; y += 4) r(2, y, 60, 1, '#2a1a3a');
      r(20, floorY + 2, 1, 5, '#140c24'); r(21, floorY + 6, 3, 1, '#140c24');
    } else if (kit === 9) { // Radio-tower shrine at dusk, prayer flags
      bands([['#2a1d3a', 10], ['#4a2a4a', 10], ['#8a4a4a', 10], ['#c27a4a', 18]], 2);
      dither(12, '#4a2a4a'); dither(22, '#8a4a4a'); dither(32, '#c27a4a');
      for (let y = 6; y < 50; y++) { const w = (y - 6) >> 2; r(44 - w, y, 1, 1, '#1a1420'); r(46 + w, y, 1, 1, '#1a1420'); if (y % 5 === 0) r(44 - w, y, w * 2 + 3, 1, '#1a1420'); }
      r(45, 3, 1, 3, '#1a1420'); r(44, 3, 3, 1, '#e0342b');
      for (let y = 34; y < 50; y++) { const w = (y - 34) * 2; r(10 - (w >> 2), y, w, 1, '#3a2a30'); }
      const flags = ['#e0342b', '#f2c230', '#3aa597', '#e8edf2', '#36e0ff'];
      for (let k = 0; k < 10; k++) r(4 + k * 4, 16 + (k * k) % 3 + (k > 5 ? 10 - k : k) , 3, 3, flags[k % 5]);
      r(2, floorY, 60, 11, '#5a4a44'); for (let x = 2; x < 62; x += 9) r(x, floorY + 2, 8, 4, '#6a5a52');
    } else if (kit === 10) { // Rust-belt gym: brick, a taped heavy bag, a poster
      r(2, 2, 60, 48, '#5a2a1e'); for (let y = 2; y < 50; y += 4) { r(2, y, 60, 1, '#3a1a12'); for (let x = 2 + ((y >> 2) % 2) * 4; x < 62; x += 8) r(x, y, 1, 4, '#3a1a12'); }
      r(8, 2, 1, 10, '#9aa6b2'); r(5, 12, 7, 18, '#6a2a22'); r(6, 12, 2, 18, '#8a3a2e'); r(5, 18, 7, 2, '#a9aeb5'); r(5, 25, 7, 1, '#a9aeb5');
      r(45, 6, 14, 10, '#e7d7b0'); r(46, 7, 12, 8, '#8a3b12'); text('GYM', 46, 8, '#e7d7b0');
      specks(30, 2, 2, 60, 34, '#8a3b12', 5);
      for (const [y, col] of [[36, '#a9aeb5'], [41, '#8a3b12'], [46, '#a9aeb5']]) r(2, y, 60, 1, col);
      r(2, floorY, 60, 11, '#34507e'); r(2, floorY, 60, 1, '#5a7aa8'); r(30, floorY + 4, 6, 3, '#a9aeb5');
    } else { // Demolition site: a wrecking ball, half a building, hazard fence
      bands([['#3a3a3e', 12], ['#5a4a44', 12], ['#8a6a54', 24]], 2);
      dither(14, '#5a4a44'); dither(26, '#8a6a54');
      r(4, 16, 22, 34, '#4a3e38'); for (let y = 18; y < 48; y += 5) for (let x = 6; x < 24; x += 5) r(x, y, 3, 3, '#1e1a18');
      r(20, 16, 6, 8, '#8a6a54'); r(22, 24, 4, 5, '#8a6a54'); // bitten corner
      r(34, 4, 26, 2, '#f2c230'); r(56, 4, 2, 46, '#f2c230'); r(42, 6, 1, 14, '#6b7483'); circle(42, 23, 4, '#2b313b'); r(41, 21, 2, 1, '#6b7483');
      specks(24, 26, 28, 30, 20, '#b09078');
      r(2, floorY, 60, 11, '#7a6a5a'); hazardBar(2, floorY - 4, 60, 2); for (let x = 2; x < 62; x += 10) r(x, floorY - 6, 1, 6, '#1a1a1a');
      specks(12, 2, floorY + 2, 60, 9, '#5a4a3a');
    }
    // Ground shadow under the fighter, then the fighter at 1:1.
    const floor = ['#6e4a30', '#1e3a3c', '#3a3440', '#9a6a3a', '#4a4034', '#5a4a3a', '#4a4a3e', '#2a2a30', '#3a2a4a', '#5a4a44', '#34507e', '#7a6a5a'][kit];
    r(15, floorY, 36, 1, mixHex(floor, '#000000', 0.3)); r(18, floorY + 1, 30, 1, mixHex(floor, '#000000', 0.4));
    parts.push(`<g transform="translate(8 5)">${body}</g>`);
    // Frame: rusted steel bevel, rivets, hazard-striped name plate with glow lights.
    r(0, 0, 64, 2, INK); r(0, 62, 64, 2, INK); r(0, 0, 2, 64, INK); r(62, 0, 2, 64, INK);
    r(1, 1, 62, 1, '#9aa6b2'); r(1, 1, 1, 62, '#9aa6b2'); r(1, 62, 62, 1, '#4b5563'); r(62, 1, 1, 62, '#4b5563');
    specks(6, 2, 1, 60, 1, '#c2551b', 7);
    for (const [x, y] of [[1, 1], [62, 1], [1, 62], [62, 62]]) r(x, y, 1, 1, '#e8edf2');
    r(2, 55, 60, 7, '#15181c'); r(2, 55, 60, 1, '#4b5563'); hazardBar(2, 61, 60, 1);
    r(4, 57, 56, 3, '#22282e'); r(4, 57, 2, 3, a); r(58, 57, 2, 3, a);
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
    // A portrait crop at 24px; the full robot on the mat; artwork on big cards.
    const classes = String(className).split(/\s+/).filter(c => /^[a-zA-Z0-9_-]+$/.test(c));
    const mode = classes.includes('avatar-sm') ? 'portrait' : classes.includes('avatar-xl') ? 'artwork' : 'sprite';
    return `<span class="avatar ${classes.join(' ')}" aria-hidden="true">${svg(identity, mode)}</span>`;
  }
  return Object.freeze({ version: VERSION, size: SIZE, render, svg, traits, bio, frames, strip, signature, clips: CLIPS });
})();
