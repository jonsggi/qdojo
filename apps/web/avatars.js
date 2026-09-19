/* Original 32×32 arcade fighters and 64×64 collectible compositions.
 * No external assets, fonts, randomness, network, or animation. Appearance does
 * not depend on live rank. This is preview art, not a minted NFT collection.
 * Keep the old skin/gi/hair picks so returning fighters retain their colours.
 *
 * Poses: a sprite can be drawn with integer pixel offsets for the body and the
 * head, a jump, lead/rear arm states, a leg state and a blink. The default pose
 * is byte-identical to the static art. `frames`/`strip` return frame sequences
 * for the clips below; playback lives in anim.js, not here.
 */
'use strict';
const QDojoAvatars = (() => {
  const SIZE = 32;
  const SKIN = ['#f5c9a3', '#d9a066', '#8d5524', '#e0ac69', '#c68642', '#ffdbac'];
  const GI = ['#f4f4f4', '#ff2a2a', '#1b2cc1', '#39ff5a', '#ffd200', '#ff3cac', '#24e6ff', '#ff8c00', '#8a2be2', '#111111'];
  const HAIR = ['#111111', '#ffd200', '#8b3a0e', '#ff2a2a', '#f4f4f4', '#24e6ff', '#39ff5a', '#ff3cac'];
  const VERSION = 'qdojo-fighters-v3-preview';
  const KITS = ['Dojo striker', 'Street brawler', 'Circuit sentinel', 'Neon shinobi'];
  const STANCES = ['Low guard', 'Boxer guard', 'Power stance'];
  const CUTS = ['Swept', 'Flat-top', 'Spiked', 'Tied-back'];
  const FEMALE_CUTS = ['Combat bob', 'High ponytail', 'Long braid', 'Sidecut'];
  const BACKDROPS = ['Sunset dojo', 'Midnight rooftop', 'Reactor chamber', 'Moon gate'];
  const ACCENTS = ['#24e6ff', '#ffd200', '#ff4b69', '#a2ff7a', '#f4f4f4'];
  const INK = '#080b20';
  const cache = new Map();
  // Frame clips. Integer pixel moves only, so the art stays crisp at any scale.
  // dx/dy move everything above the belt, hx/hy add to the head, jump lifts the
  // whole sprite. `hold` clips end on their last frame instead of returning to
  // idle. Every clip starts and ends near the guard so cuts between them read.
  const DOWN = { lead: 'down', rear: 0 };
  const UP = { lead: 'up', rear: 'up' };
  const CLIPS = Object.freeze({
    idle: { fps: 4, frames: [{}, { dy: 1 }, { dy: 1, blink: true }, { dy: 1 }, {}, {}, { blink: true }, {}] },
    jab: { fps: 12, frames: [{ lead: 'wind' }, { lead: 'jab', dx: 1 }, { lead: 'jab', dx: 1 }, { lead: 'jab' }, {}, {}] },
    kick: { fps: 12, frames: [{ legs: 'chamber', dx: -1, hx: -1 }, { legs: 'kick', dx: -1, hx: -1 }, { legs: 'kick', dx: -1, hx: -1 }, { legs: 'kick' }, { legs: 'chamber' }, {}] },
    hit: { fps: 12, frames: [{ dx: -1, hx: -1, blink: true }, { dx: -2, hx: -3, hy: -1, blink: true }, { dx: -2, hx: -3, hy: -1, blink: true }, { dx: -1, hx: -1, blink: true }, {}] },
    bow: { fps: 6, frames: [DOWN, { ...DOWN, dx: 1, dy: 1, hx: 1, hy: 1 }, { ...DOWN, dx: 1, dy: 2, hx: 2, hy: 3, blink: true }, { ...DOWN, dx: 1, dy: 2, hx: 2, hy: 3, blink: true }, { ...DOWN, dx: 1, dy: 2, hx: 2, hy: 3, blink: true }, { ...DOWN, dx: 1, dy: 2, hx: 2, hy: 3, blink: true }, { ...DOWN, dx: 1, dy: 1, hx: 1, hy: 1 }, DOWN, {}] },
    win: { fps: 8, frames: [UP, { ...UP, jump: 2 }, { ...UP, jump: 4 }, { ...UP, jump: 4, blink: true }, { ...UP, jump: 2 }, { ...UP, dy: 1 }, UP, { ...UP, blink: true }, UP, {}] },
    lose: { fps: 8, hold: true, frames: [{ dx: -1, hx: -1, blink: true }, { ...DOWN, dx: -1, dy: 1, hx: -1, hy: 1, blink: true }, { ...DOWN, dy: 5, hy: 2, blink: true, legs: 'kneel' }, { ...DOWN, dy: 5, hy: 2, blink: true, legs: 'kneel' }] },
  });
  const SIGNATURES = ['jab', 'kick', 'bow', 'win'];

  function hash(s) {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
    return h;
  }
  function shade(hex, amount) {
    const n = parseInt(hex.slice(1), 16);
    return '#' + [n >> 16, (n >> 8) & 255, n & 255]
      .map(c => Math.max(0, Math.min(255, c + amount)).toString(16).padStart(2, '0')).join('');
  }

  // A character-art trait, never an inference about the wallet's owner. Use a
  // separate hash domain so every kit/guard/palette can have either variant.
  function isFemale(identity) { return Boolean((hash('qdojo/fighter/character/v1/' + identity) >>> 24) & 1); }

  function traits(identity) {
    identity = String(identity || '');
    const h = hash(identity), d = hash('qdojo/fighter/v1/' + identity), kit = d % 4;
    const female = isFemale(identity), cut = (d >>> 9) % 4;
    return Object.freeze({
      archetype: KITS[kit], stance: STANCES[(d >>> 5) % 3],
      character: female ? 'Female' : 'Male',
      outfit: GI[(h >>> 4) % GI.length], skin: SKIN[h % SKIN.length],
      headgear: kit === 2 ? (cut % 2 ? 'Crested helmet' : 'Visor helmet')
        : kit === 3 ? 'Wrapped hood' : female ? FEMALE_CUTS[cut] : CUTS[cut],
      hairstyle: female ? (kit >= 2 ? 'Armoured braid' : FEMALE_CUTS[cut]) : kit < 2 ? CUTS[cut] : null,
      hair: kit < 2 || female ? HAIR[(h >>> 8) % HAIR.length] : null,
      headband: kit < 2 && Boolean((h >>> 16) & 1),
      accent: ACCENTS[(d >>> 13) % ACCENTS.length], backdrop: BACKDROPS[kit],
    });
  }

  function sprite(identity, pose = {}) {
    const { dx = 0, dy = 0, hx = 0, hy = 0, jump = 0, lead = 'guard', rear = null, legs = 'plant', blink = false } = pose;
    let ox = 0, oy = 0; // current pose offset, set per body part below
    const body = () => { ox = dx; oy = dy - jump; };
    const head = () => { ox = dx + hx; oy = dy + hy - jump; };
    const ground = () => { ox = 0; oy = -jump; };
    const h = hash(identity), detail = hash('qdojo/fighter/v1/' + identity);
    const skin = SKIN[h % SKIN.length], gi = GI[(h >>> 4) % GI.length], hair = HAIR[(h >>> 8) % HAIR.length];
    // Four hand-drawn kits and three fighting guards; trait picks are independent
    // of the legacy colour hash, so similar uniforms need not mean similar bots.
    const kit = detail % 4, stance = (detail >>> 5) % 3, cut = (detail >>> 9) % 4;
    const accent = ACCENTS[(detail >>> 13) % ACCENTS.length];
    const female = isFemale(identity);
    const cloth = gi === '#111111' ? '#343b53' : gi;
    const dark = shade(cloth, -65), light = shade(cloth, 42);
    const skinDark = shade(skin, -46), skinLight = shade(skin, 23);
    const pixels = Array(SIZE * SIZE).fill(null);
    const rect = (x, y, w, ht, c) => {
      x += ox; y += oy;
      for (let yy = y; yy < y + ht; yy++) for (let xx = x; xx < x + w; xx++) {
        if (xx >= 0 && xx < SIZE && yy >= 0 && yy < SIZE) pixels[yy * SIZE + xx] = c;
      }
    };
    const dot = (x, y, c) => rect(x, y, 1, 1, c);

    // Hair behind the body: a strong silhouette at thumbnail size. Female
    // sentinels and shinobi keep their protective headgear with an exposed braid.
    head();
    if (female) {
      const hairLight = shade(hair, 48);
      if (kit >= 2 || cut === 2) {
        rect(9, 7, 3, 4, hair); rect(8, 10, 3, 5, hair);
        rect(7, 14, 3, 5, hair); rect(8, 18, 2, 3, hair);
        for (let y = 10; y <= 18; y += 3) dot(y < 14 ? 9 : 8, y, hairLight);
        rect(8, 20, 2, 1, accent); dot(9, 21, hair);
      } else if (cut === 1) {
        rect(9, 3, 3, 3, accent); rect(6, 3, 4, 4, hair);
        rect(4, 5, 4, 6, hair); rect(3, 10, 3, 4, hair);
        rect(4, 14, 3, 2, hair); rect(5, 6, 1, 5, hairLight);
        rect(6, 3, 2, 1, hairLight);
      } else if (cut === 0) {
        rect(10, 6, 3, 7, hair); rect(19, 5, 3, 8, hair);
        rect(10, 12, 2, 3, hair); rect(20, 12, 2, 2, hair);
        rect(10, 7, 1, 4, hairLight);
      }
    }

    // Wide planted legs, trouser folds, ankle wraps, and individually lit boots.
    ground();
    const BOOT = '#22283f', BOOT_LIGHT = '#7b8da6';
    if (legs === 'plant') {
      rect(11, 22, 10, 3, dark);
      rect(10, 24, 5, 5, cloth); rect(9, 27, 5, 2, cloth);
      rect(10, 24, 2, 3, light); rect(13, 24, 2, 4, dark);
      rect(18, 24, 5, 3, dark); rect(20, 26, 4, 3, cloth);
      rect(21, 26, 2, 3, light);
      rect(9, 28, 5, 1, accent); rect(20, 28, 4, 1, accent);
      rect(8, 29, 6, 2, BOOT); rect(20, 29, 7, 2, BOOT);
      rect(8, 29, 3, 1, BOOT_LIGHT); rect(24, 29, 3, 1, BOOT_LIGHT);
    } else if (legs === 'kneel') { // Down on one knee, the other foot planted ahead.
      rect(11, 27, 10, 2, dark);
      rect(9, 28, 4, 3, cloth); rect(4, 29, 6, 2, cloth); rect(4, 29, 3, 1, light);
      rect(1, 29, 4, 2, BOOT); rect(1, 29, 2, 1, BOOT_LIGHT);
      rect(18, 27, 5, 2, cloth); rect(21, 26, 3, 4, dark); rect(21, 28, 3, 1, accent);
      rect(20, 29, 6, 2, BOOT); rect(24, 29, 2, 1, BOOT_LIGHT);
    } else { // The rear leg moves under the hips; the front leg chambers or kicks.
      rect(11, 22, 10, 3, dark);
      rect(11, 24, 5, 5, cloth); rect(10, 27, 5, 2, cloth);
      rect(11, 24, 2, 3, light); rect(14, 24, 2, 4, dark);
      rect(10, 28, 5, 1, accent); rect(9, 29, 6, 2, BOOT); rect(9, 29, 3, 1, BOOT_LIGHT);
      if (legs === 'kick') {
        rect(18, 22, 5, 3, dark); rect(22, 21, 5, 3, cloth); rect(23, 21, 3, 1, light);
        rect(26, 21, 1, 3, accent); rect(27, 20, 4, 4, BOOT); rect(27, 20, 4, 1, BOOT_LIGHT);
      } else {
        rect(18, 22, 5, 3, cloth); rect(19, 22, 3, 1, light); rect(21, 24, 3, 3, dark);
        rect(20, 27, 4, 1, accent); rect(19, 28, 6, 2, BOOT); rect(19, 28, 3, 1, BOOT_LIGHT);
      }
    }

    // Rear arm: low fist, boxer guard, a wide power stance, or raised.
    body();
    const arm = kit === 1 ? skin : cloth, armDark = kit === 1 ? skinDark : dark;
    const rearStance = rear == null ? stance : rear;
    if (rearStance === 'up') {
      rect(8, 16, 4, 3, arm); rect(8, 9, 3, 8, armDark);
      rect(8, 9, 3, 1, accent); rect(7, 5, 4, 4, skinDark);
      rect(7, 5, 4, 3, skin); dot(8, 5, skinLight);
    } else if (rearStance === 0) {
      rect(8, 16, 4, 5, arm); rect(7, 19, 4, 4, armDark);
      rect(6, 21, 4, 2, accent); rect(5, 23, 5, 3, skinDark);
      rect(5, 23, 4, 2, skin); dot(6, 23, skinLight);
    } else if (rearStance === 1) {
      rect(7, 16, 5, 4, armDark); rect(6, 13, 4, 6, arm);
      rect(6, 13, 4, 2, accent); rect(5, 10, 5, 3, skinDark);
      rect(5, 10, 4, 2, skin); dot(6, 10, skinLight);
    } else {
      rect(7, 16, 5, 4, arm); rect(5, 18, 4, 3, armDark);
      rect(4, 18, 2, 3, accent); rect(2, 17, 3, 4, skin);
      rect(2, 20, 3, 1, skinDark); dot(2, 17, skinLight);
    }

    // Torso silhouette. Each kit changes the shoulders and chest, not just hue.
    rect(12, 14, 8, 2, cloth); rect(10, 16, 12, 5, cloth);
    rect(11, 21, 10, 3, dark); rect(11, 16, 2, 5, light);
    rect(19, 16, 3, 7, dark); rect(14, 14, 4, 3, skinDark);
    rect(14, 14, 3, 2, skin);
    if (kit === 0) { // Cross-over gi, lapels, folded sleeve.
      rect(13, 16, 2, 2, light); rect(14, 18, 2, 2, light);
      rect(15, 20, 2, 2, light); rect(17, 16, 2, 2, INK);
      rect(16, 18, 2, 2, INK); dot(15, 20, INK);
      rect(10, 19, 3, 1, dark);
    } else if (kit === 1) { // Sleeveless fighter, open vest and knuckle wraps.
      rect(14, 16, 4, 6, skin); rect(17, 17, 1, 5, skinDark);
      rect(14, 18, 3, 1, skinDark); rect(13, 16, 1, 6, accent);
      rect(18, 16, 1, 6, accent); dot(15, 20, skinLight);
    } else if (kit === 2) { // Cyber armour with square pauldrons and a core light.
      rect(8, 15, 5, 3, dark); rect(8, 15, 4, 1, light);
      rect(20, 15, 4, 3, dark); rect(20, 15, 4, 1, light);
      rect(13, 17, 6, 4, '#323d59'); rect(14, 17, 4, 1, '#748da7');
      rect(15, 19, 2, 2, accent); dot(15, 19, '#ffffff');
      rect(12, 22, 3, 1, light); rect(18, 22, 2, 1, light);
    } else { // Wrapped shinobi tunic and diagonal harness.
      rect(13, 16, 2, 2, INK); rect(14, 18, 2, 2, INK);
      rect(15, 20, 2, 2, INK); rect(16, 22, 2, 1, INK);
      dot(14, 17, accent); dot(15, 19, accent); dot(16, 21, accent);
      rect(10, 16, 2, 2, light);
    }

    if (female) {
      // Tailored, full-coverage fighting gear: a tapered jacket/armour silhouette,
      // reinforced seams and a sports top under the brawler's open vest.
      rect(10, 19, 1, 2, INK); rect(11, 21, 1, 2, INK);
      rect(20, 21, 1, 2, INK); rect(12, 21, 1, 2, light);
      rect(19, 21, 1, 2, dark);
      if (kit === 1) {
        rect(14, 18, 4, 4, dark); rect(14, 18, 4, 1, accent);
        rect(14, 19, 1, 2, cloth); rect(17, 19, 1, 3, INK);
      } else if (kit === 2) {
        rect(9, 15, 3, 1, accent); rect(21, 15, 3, 1, accent);
        rect(13, 21, 6, 1, INK); rect(14, 22, 4, 1, '#748da7');
      } else {
        rect(12, 20, 1, 2, accent); rect(18, 21, 1, 2, light);
      }
      // Knee guards and taller boots echo the jacket without changing the pose.
      if (legs === 'plant') {
        ground();
        rect(10, 26, 4, 2, dark); rect(10, 26, 2, 1, light);
        rect(20, 26, 4, 2, dark); rect(21, 26, 2, 1, light);
        rect(9, 28, 5, 1, '#48516a'); rect(20, 28, 4, 1, '#48516a');
        dot(10, 28, accent); dot(22, 28, accent);
        body();
      }
    }

    // Raised leading fist, bent elbow, wrist tape, visible knuckle highlights.
    if (lead === 'jab') { // Arm straight out, fist at shoulder height.
      rect(20, 16, 4, 4, armDark); rect(23, 15, 4, 3, arm);
      rect(25, 15, 1, 3, accent);
      rect(26, 14, 4, 4, skinDark); rect(26, 14, 4, 3, skin);
      rect(27, 14, 2, 1, skinLight);
      if (kit === 2) {
        rect(26, 14, 4, 3, cloth); rect(27, 14, 2, 1, light);
        rect(26, 16, 3, 1, accent); rect(20, 17, 3, 2, '#536781');
      }
    } else if (lead === 'up') { // Arm straight up: the winner's salute.
      rect(20, 16, 4, 3, armDark); rect(22, 9, 3, 8, arm);
      rect(22, 9, 3, 1, accent); rect(21, 5, 4, 4, skinDark);
      rect(21, 5, 4, 3, skin); dot(22, 5, skinLight);
      if (kit === 2) {
        rect(21, 5, 4, 3, cloth); rect(22, 5, 2, 1, light);
        rect(21, 7, 3, 1, accent);
      }
    } else if (lead === 'down') { // Arm hanging at the side.
      rect(20, 17, 4, 4, armDark); rect(21, 20, 3, 4, arm);
      rect(21, 23, 3, 1, accent); rect(20, 24, 4, 3, skinDark);
      rect(20, 24, 4, 2, skin); dot(21, 24, skinLight);
      if (kit === 2) {
        rect(20, 24, 4, 2, cloth); rect(21, 24, 2, 1, light);
        rect(20, 26, 3, 1, accent);
      }
    } else if (lead === 'wind') { // Fist pulled to the chin before the punch.
      rect(20, 18, 4, 4, armDark); rect(22, 17, 3, 4, arm);
      rect(22, 14, 3, 4, arm); rect(22, 14, 3, 1, accent);
      rect(21, 11, 4, 3, skinDark); rect(21, 11, 4, 2, skin);
      dot(22, 11, skinLight);
      if (kit === 2) {
        rect(21, 11, 4, 3, cloth); rect(22, 11, 2, 1, light);
        rect(21, 13, 3, 1, accent); rect(20, 20, 3, 2, '#536781');
      }
    } else {
      rect(20, 18, 4, 4, armDark); rect(22, 17, 4, 4, arm);
      rect(24, 14, 3, 5, arm); rect(24, 14, 3, 2, accent);
      rect(23, 11, 5, 3, skinDark); rect(23, 10, 4, 3, skin);
      rect(24, 10, 2, 1, skinLight); dot(27, 12, skin);
      if (kit === 2) { // Armoured glove and elbow plate.
        rect(23, 10, 4, 3, cloth); rect(24, 10, 2, 1, light);
        rect(24, 12, 3, 1, accent); rect(20, 20, 3, 2, '#536781');
      }
    }

    // A neutral utility sash, NOT a randomly awarded rank belt. Earned rank is
    // displayed by the application's belt tags, outside the immutable artwork.
    rect(11, 23, 10, 2, INK); rect(11, 23, 10, 1, '#48516a');
    rect(16, 23, 2, 2, '#a2b1c5');
    rect(17, 25, 2, 2, '#48516a'); dot(19, 26, '#48516a');

    // Three-quarter face, jaw shadow, brow and a bright eye.
    head();
    rect(12, 6, 8, 6, skin); rect(13, 12, 7, 2, skinDark);
    rect(11, 9, 2, 3, skinDark); rect(19, 9, 2, 2, skin);
    rect(14, 7, 5, 1, skinLight); rect(12, 7, 1, 4, skinDark);
    rect(15, 8, 2, 1, INK); rect(18, 8, 2, 1, INK);
    if (!blink) { dot(16, 9, '#ffffff'); dot(19, 9, '#ffffff'); }
    dot(17, 10, skinDark); rect(16, 12, 3, 1, '#703746');
    if (female) {
      rect(13, 12, 1, 2, INK); dot(14, 13, INK); dot(19, 13, INK);
      dot(14, 8, INK); dot(20, 8, INK);
      rect(16, 12, 3, 1, skinDark); rect(16, 12, 2, 1, '#9a465f');
      dot(14, 11, skinLight);
    }

    if (kit === 3) { // Hood and face wrap, leaving only the eye slit open.
      rect(12, 4, 7, 2, dark); rect(11, 6, 2, 3, cloth);
      rect(19, 6, 2, 3, dark); rect(12, 6, 7, 2, cloth);
      rect(11, 9, 1, 3, dark); rect(20, 9, 1, 2, dark);
      rect(12, 10, 8, 4, dark); rect(13, 10, 7, 1, light);
      rect(10, 12, 3, 2, accent); rect(8, 13, 3, 1, accent);
    } else if (kit === 2) { // Helmet and luminous visor.
      rect(12, 3, 7, 2, dark); rect(11, 5, 10, 3, cloth);
      rect(12, 5, 7, 1, light); rect(11, 8, 2, 4, dark);
      rect(14, 8, 7, 2, INK); rect(15, 8, 5, 1, accent);
      dot(20, 8, '#ffffff'); rect(12, 12, 3, 2, '#536781');
      if (cut % 2) { rect(15, 1, 2, 3, accent); dot(15, 1, '#ffffff'); }
    } else {
      // Both character variants have four authored hair silhouettes.
      if (female) {
        rect(12, 3, 7, 3, hair); rect(11, 5, 3, 3, hair);
        rect(13, 3, 4, 1, shade(hair, 48));
        if (cut === 0) { // Asymmetric bob, visible fringe and jaw-length sides.
          rect(17, 4, 4, 3, hair); rect(19, 6, 2, 2, hair);
          dot(18, 7, hair); rect(20, 7, 1, 4, shade(hair, 48));
        } else if (cut === 1) {
          rect(11, 3, 2, 3, hair); rect(17, 5, 3, 2, hair);
          dot(19, 7, hair);
        } else if (cut === 2) {
          rect(12, 4, 2, 4, hair); rect(17, 5, 3, 1, hair);
          rect(10, 7, 2, 1, accent);
        } else { // Swept fringe over a close-cropped side.
          rect(12, 2, 4, 2, hair); rect(11, 4, 3, 5, hair);
          rect(18, 4, 2, 3, shade(hair, 32));
          rect(13, 6, 2, 2, hair); dot(14, 8, hair);
        }
      } else if (cut === 0) {
        rect(12, 3, 7, 3, hair); rect(11, 5, 3, 3, hair);
        rect(17, 5, 4, 2, hair); rect(13, 3, 3, 1, shade(hair, 48));
      } else if (cut === 1) {
        rect(12, 2, 7, 4, hair); rect(11, 4, 2, 4, hair);
        rect(12, 2, 7, 1, shade(hair, 48));
      } else if (cut === 2) {
        rect(12, 4, 8, 2, hair); rect(12, 2, 2, 3, hair);
        rect(15, 1, 2, 4, hair); rect(18, 2, 2, 3, hair);
        dot(15, 1, shade(hair, 64)); rect(11, 5, 2, 3, hair);
      } else {
        rect(12, 4, 8, 2, hair); rect(11, 5, 3, 3, hair);
        rect(9, 6, 3, 2, hair); rect(8, 8, 2, 4, hair);
        rect(7, 11, 2, 2, hair); rect(12, 4, 4, 1, shade(hair, 48));
      }
      // Keep the old headband trait. Its two tails extend beyond the head.
      if ((h >>> 16) & 1) {
        rect(11, 6, 9, 1, '#ff4242'); rect(11, 7, 2, 1, '#a51235');
        rect(8, 6, 3, 1, '#ff4242'); rect(6, 5, 3, 1, '#ff4242');
        rect(9, 7, 2, 1, '#ff8b78'); rect(8, 8, 2, 1, '#ff4242');
      }
    }

    // A one-pixel ink outline keeps every kit readable against bright panels.
    const outlined = pixels.slice();
    for (let y = 0; y < SIZE; y++) for (let x = 0; x < SIZE; x++) {
      if (!pixels[y * SIZE + x]) continue;
      for (const [dx, dy] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) {
        const xx = x + dx, yy = y + dy;
        if (xx >= 0 && xx < SIZE && yy >= 0 && yy < SIZE && !pixels[yy * SIZE + xx]) outlined[yy * SIZE + xx] = INK;
      }
    }
    // One path per colour, with horizontal pixel runs: ~20 SVG nodes rather
    // than hundreds of rects each time a fighter appears in a history table.
    const paths = new Map();
    for (let y = 0; y < SIZE; y++) for (let x = 0; x < SIZE;) {
      const color = outlined[y * SIZE + x];
      if (!color) { x++; continue; }
      let end = x + 1;
      while (end < SIZE && outlined[y * SIZE + end] === color) end++;
      const w = end - x;
      paths.set(color, (paths.get(color) || '') + `M${x} ${y}h${w}v1h-${w}z`);
      x = end;
    }
    return [...paths].map(([color, d]) => `<path fill="${color}" d="${d}"/>`).join('');
  }

  function artwork(identity, body) {
    const t = traits(identity), kit = KITS.indexOf(t.archetype), a = t.accent;
    const parts = [];
    const r = (x, y, w, h, c) => parts.push(`<path fill="${c}" d="M${x} ${y}h${w}v${h}h-${w}z"/>`);
    r(0, 0, 64, 64, INK); r(2, 2, 60, 60, '#131838');
    // Pixel-stepped halo; deliberately hard-edged, never a soft/glowing filter.
    r(16, 9, 32, 38, '#232955'); r(12, 13, 40, 30, '#232955');
    r(9, 19, 46, 18, '#232955');
    if (kit === 0) {
      r(20, 10, 24, 26, '#ff8c42'); r(16, 14, 32, 18, '#ff8c42');
      for (let y = 25; y < 37; y += 4) r(16, y, 32, 2, '#232955');
      r(7, 21, 50, 3, '#892946'); r(6, 20, 52, 2, '#f15b66');
      r(12, 23, 3, 25, '#a53751'); r(49, 23, 3, 25, '#a53751');
      r(9, 29, 46, 2, '#f15b66'); r(5, 18, 3, 4, '#f15b66'); r(56, 18, 3, 4, '#f15b66');
    } else if (kit === 1) {
      // Staggered towers and tiny lit windows behind the rooftop fighter.
      for (let i = 0; i < 7; i++) {
        const x = 3 + i * 8, y = 23 + ((i * 7) % 13);
        r(x, y, 7, 48 - y, '#0c112c');
        for (let yy = y + 3; yy < 44; yy += 5) { r(x + 2, yy, 1, 2, '#576084'); r(x + 5, yy, 1, 2, '#3b4169'); }
      }
      r(45, 9, 9, 1, a); r(49, 5, 1, 9, a);
      r(4, 18, 9, 12, '#090c23'); r(5, 19, 7, 10, a); r(7, 21, 3, 6, '#161530');
    } else if (kit === 2) {
      r(11, 10, 42, 34, '#2b4262'); r(13, 12, 38, 30, '#101b36');
      for (let x = 16; x <= 48; x += 8) r(x, 14, 1, 26, '#2b4262');
      for (let y = 18; y <= 38; y += 5) r(15, y, 34, 1, '#2b4262');
      r(6, 15, 2, 28, a); r(56, 15, 2, 28, a);
      r(6, 13, 7, 2, a); r(51, 13, 7, 2, a);
      r(3, 37, 7, 7, '#435775'); r(54, 37, 7, 7, '#435775');
      r(4, 38, 3, 2, a); r(55, 38, 3, 2, a);
    } else {
      r(20, 9, 24, 27, '#aba4ea'); r(16, 13, 32, 19, '#aba4ea');
      r(22, 9, 18, 27, '#cbc9f7');
      r(5, 29, 54, 2, '#535087'); r(8, 26, 48, 3, '#34375f');
      r(11, 23, 42, 3, '#535087'); r(9, 31, 3, 17, '#535087'); r(52, 31, 3, 17, '#535087');
      r(4, 37, 5, 5, a); r(55, 37, 5, 5, a);
    }
    r(2, 48, 60, 14, '#101429'); r(2, 48, 60, 1, a);
    for (let y = 53; y <= 61; y += 5) r(2, y, 60, 1, '#303956');
    r(10, 49, 1, 13, '#303956'); r(53, 49, 1, 13, '#303956');
    r(15, 57, 35, 3, '#080b20');
    parts.push(`<g transform="translate(8 8) scale(1.5)">${body}</g>`);
    // Screen-printed corner registration marks, not rarity indicators.
    for (const [x, y] of [[3, 3], [56, 3], [3, 59], [56, 59]]) r(x, y, 5, 2, a);
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
    const viewBox = mode === 'portrait' ? '6 0 24 24' : mode === 'sprite' ? '0 0 32 32' : '0 0 64 64';
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${viewBox}" shape-rendering="crispEdges" focusable="false">${mode === 'sprite' || mode === 'portrait' ? body : art}</svg>`;
  }

  // Frame bodies for one clip: each entry is the path markup of a 32×32 sprite,
  // or of the 64×64 composition in artwork mode.
  function frames(identity, clip = 'idle', mode = 'sprite') {
    identity = String(identity || '');
    const c = CLIPS[clip] || CLIPS.idle;
    return c.frames.map(pose => mode === 'artwork' ? artwork(identity, sprite(identity, pose)) : sprite(identity, pose));
  }

  // One SVG holding every frame of a clip as a hidden group. Nothing in it
  // moves by itself; anim.js shows one <g data-frame> at a time.
  function strip(identity, clip = 'idle', mode = 'sprite') {
    const c = CLIPS[clip] || CLIPS.idle;
    const groups = frames(identity, clip, mode)
      .map((body, i) => `<g data-frame="${i}"${i ? ' style="display:none"' : ''}>${body}</g>`).join('');
    const viewBox = mode === 'artwork' ? '0 0 64 64' : '0 0 32 32';
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
  return Object.freeze({ version: VERSION, render, svg, traits, frames, strip, signature, clips: CLIPS });
})();
