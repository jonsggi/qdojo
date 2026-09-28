#!/usr/bin/env node
/* Freeze fighter NFT art and metadata (AUD-009, docs/nft.md §7). No dependencies.
 *
 *   node scripts/nft-freeze.cjs freeze --tokens tokens.json --out DIR [--avatars apps/web/avatars.js]
 *   node scripts/nft-freeze.cjs verify --out DIR [--avatars apps/web/avatars.js]
 *
 * freeze: for every token, renders the 64x64 card and 48x48 sprite SVGs with
 * apps/web/avatars.js, rasterizes them to lossless PNG masters at 16x
 * (1024 px card, 768 px sprite; nearest neighbour, whole pixels only), writes
 * metadata JSON in the common NFT shape (name, description = the fighter's
 * bio, image, external_url, attributes from its traits) and stores every file
 * content-addressed as DIR/objects/<sha256>.<ext>. DIR/manifest.json lists
 * each token's files and hashes, the renderer's version and source hash, and
 * a root hash over the token list. The output is byte-for-byte deterministic.
 *
 * verify: every object's bytes still hash to its name and manifest entry;
 * the renderer still draws every token's SVG byte for byte; every PNG decodes
 * to exactly the pixels of that SVG; the metadata still says what the traits
 * and bio say. Exit 0 when all hold, 1 with a list of differences otherwise.
 *
 * tokens.json: {"collection": {...}, "site": "https://…/combat.html",
 *               "tokens": [{"fighter_id", "serial", "name", "fighter_name", "issuer", "founding", "creator"}]}
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');
const crypto = require('node:crypto');
const vm = require('node:vm');

const SCHEMA = 'qdojo.nft.freeze.v1';
const SCALE = 16;
const sha = b => crypto.createHash('sha256').update(b).digest('hex');

function args(argv) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith('--')) out[argv[i].slice(2)] = argv[++i];
    else out._.push(argv[i]);
  }
  return out;
}

function loadRenderer(file) {
  const src = fs.readFileSync(file, 'utf8');
  const A = vm.runInContext(src + '\nQDojoAvatars;', vm.createContext({}));
  return { A, sha256: sha(src), version: A.version };
}

// ---- SVG -> pixels ----------------------------------------------------------------
// The renderer's SVG is a list of <path fill="#rrggbb" d="M x y h w v h h -w z ..."/>,
// optionally inside one <g transform="translate(dx dy)">, painted in order. Anything
// else is refused rather than guessed at.
function rasterize(svg, size) {
  const rgba = new Uint8Array(size * size * 4);
  const vb = /viewBox="0 0 (\d+) (\d+)"/.exec(svg);
  if (!vb || Number(vb[1]) !== size || Number(vb[2]) !== size) throw new Error('unexpected viewBox');
  let dx = 0, dy = 0;
  const tokens = svg.match(/<g transform="translate\((-?\d+) (-?\d+)\)">|<\/g>|<path fill="#([0-9a-f]{6})" d="([^"]*)"\/>|<[^>]+>/g) || [];
  for (const t of tokens) {
    let m;
    if ((m = /^<g transform="translate\((-?\d+) (-?\d+)\)">$/.exec(t))) { dx = Number(m[1]); dy = Number(m[2]); continue; }
    if (t === '</g>') { dx = dy = 0; continue; }
    if ((m = /^<path fill="#([0-9a-f]{6})" d="([^"]*)"\/>$/.exec(t))) {
      const c = [parseInt(m[1].slice(0, 2), 16), parseInt(m[1].slice(2, 4), 16), parseInt(m[1].slice(4, 6), 16)];
      const re = /M(-?\d+) (-?\d+)h(-?\d+)v(-?\d+)h(-?\d+)z/g;
      let consumed = 0, r;
      while ((r = re.exec(m[2]))) {
        if (r.index !== consumed) throw new Error('unsupported path data');
        consumed = re.lastIndex;
        const x = Number(r[1]) + dx, y = Number(r[2]) + dy, w = Number(r[3]), h = Number(r[4]);
        if (Number(r[5]) !== -w || w <= 0 || h <= 0) throw new Error('path is not a rectangle');
        for (let yy = Math.max(0, y); yy < Math.min(size, y + h); yy++) {
          for (let xx = Math.max(0, x); xx < Math.min(size, x + w); xx++) {
            const o = (yy * size + xx) * 4;
            rgba[o] = c[0]; rgba[o + 1] = c[1]; rgba[o + 2] = c[2]; rgba[o + 3] = 255;
          }
        }
      }
      if (consumed !== m[2].length) throw new Error('unsupported path data');
      continue;
    }
    if (/^<svg /.test(t) || t === '</svg>') continue;
    throw new Error('unsupported SVG element ' + t.slice(0, 40));
  }
  return rgba;
}

// ---- PNG (indexed colour when it fits, else RGBA; filter 0; zlib) -----------------
const CRC = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
  return t;
})();
function crc32(buf) { let c = 0xffffffff; for (const b of buf) c = CRC[(c ^ b) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; }
function chunk(type, data) {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
}
function encodePng(rgba, size, scale) {
  const W = size * scale;
  const colours = new Map();
  for (let i = 0; i < size * size; i++) {
    const k = ((rgba[i * 4] << 24) | (rgba[i * 4 + 1] << 16) | (rgba[i * 4 + 2] << 8) | rgba[i * 4 + 3]) >>> 0;
    if (!colours.has(k)) colours.set(k, colours.size);
  }
  const indexed = colours.size <= 256;
  const bpp = indexed ? 1 : 4;
  const raw = Buffer.alloc(W * (W * bpp + 1));
  for (let y = 0; y < W; y++) {
    const row = y * (W * bpp + 1);
    raw[row] = 0;                                     // filter: none
    const sy = Math.floor(y / scale);
    for (let x = 0; x < W; x++) {
      const s = (sy * size + Math.floor(x / scale)) * 4;
      if (indexed) {
        raw[row + 1 + x] = colours.get(((rgba[s] << 24) | (rgba[s + 1] << 16) | (rgba[s + 2] << 8) | rgba[s + 3]) >>> 0);
      } else {
        raw.set(rgba.subarray(s, s + 4), row + 1 + x * 4);
      }
    }
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(W, 0); ihdr.writeUInt32BE(W, 4);
  ihdr[8] = 8; ihdr[9] = indexed ? 3 : 6; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  const parts = [Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr)];
  if (indexed) {
    const keys = [...colours.keys()];
    const plte = Buffer.alloc(keys.length * 3), trns = Buffer.alloc(keys.length);
    keys.forEach((k, i) => { plte[i * 3] = k >>> 24; plte[i * 3 + 1] = (k >>> 16) & 255; plte[i * 3 + 2] = (k >>> 8) & 255; trns[i] = k & 255; });
    parts.push(chunk('PLTE', plte));
    if (keys.some(k => (k & 255) !== 255)) parts.push(chunk('tRNS', trns));
  }
  parts.push(chunk('IDAT', zlib.deflateSync(raw, { level: 9 })), chunk('IEND', Buffer.alloc(0)));
  return Buffer.concat(parts);
}
// Decodes exactly what encodePng writes (8-bit, filter 0, indexed or RGBA), back to native-size RGBA.
function decodePng(buf, size, scale) {
  let off = 8, ihdr, plte, trns;
  const idat = [];
  while (off < buf.length) {
    const len = buf.readUInt32BE(off), type = buf.toString('ascii', off + 4, off + 8), data = buf.subarray(off + 8, off + 8 + len);
    if (crc32(buf.subarray(off + 4, off + 8 + len)) !== buf.readUInt32BE(off + 8 + len)) throw new Error('bad PNG CRC');
    if (type === 'IHDR') ihdr = data; else if (type === 'PLTE') plte = data; else if (type === 'tRNS') trns = data; else if (type === 'IDAT') idat.push(data);
    off += 12 + len;
  }
  const W = ihdr.readUInt32BE(0), indexed = ihdr[9] === 3, bpp = indexed ? 1 : 4;
  if (W !== size * scale || ihdr[8] !== 8) throw new Error('unexpected PNG geometry');
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const out = new Uint8Array(size * size * 4);
  for (let y = 0; y < W; y++) {
    const row = y * (W * bpp + 1);
    if (raw[row] !== 0) throw new Error('unexpected PNG filter');
    for (let x = 0; x < W; x++) {
      let px;
      if (indexed) { const i = raw[row + 1 + x]; px = [plte[i * 3], plte[i * 3 + 1], plte[i * 3 + 2], trns && i < trns.length ? trns[i] : 255]; }
      else px = raw.subarray(row + 1 + x * 4, row + 5 + x * 4);
      const o = (Math.floor(y / scale) * size + Math.floor(x / scale)) * 4;
      if (y % scale === 0 && x % scale === 0) out.set(px, o);
      else if (out[o] !== px[0] || out[o + 1] !== px[1] || out[o + 2] !== px[2] || out[o + 3] !== px[3]) throw new Error('PNG is not an integer-scaled master');
    }
  }
  return out;
}

// ---- metadata ---------------------------------------------------------------------
const TRAITS = [['archetype', 'Kit'], ['martialArt', 'Martial art'], ['formerJob', 'Former job'], ['designation', 'Designation'],
  ['modelYear', 'Model year'], ['chassis', 'Chassis'], ['stance', 'Stance'], ['finish', 'Finish'], ['rust', 'Rust'],
  ['paint', 'Paint'], ['headUnit', 'Head unit'], ['eyeGlow', 'Eye glow'], ['salvagedLimb', 'Salvaged limb'],
  ['topper', 'Topper'], ['quirk', 'Quirk'], ['headgear', 'Headgear'], ['gloves', 'Gloves'], ['shoulders', 'Shoulders'],
  ['palette', 'Cloth'], ['sash', 'Sash'], ['pattern', 'Chest pattern'], ['emblem', 'Emblem'], ['backdrop', 'Card scene'],
  ['signature', 'Signature move']];
function attributes(traits) {
  return TRAITS.filter(([k]) => traits[k] != null && traits[k] !== '').map(([k, label]) =>
    (typeof traits[k] === 'number' ? { trait_type: label, value: traits[k], display_type: 'number' } : { trait_type: label, value: String(traits[k]) }));
}
function metadata(tok, A, renderer, files, collection, site) {
  const id = tok.fighter_id;
  const title = (tok.fighter_name ? String(tok.fighter_name).toUpperCase() + ' · ' : '') + tok.name + ' #' + tok.serial;
  return {
    name: title,
    description: A.bio(id) + ' Art is a deterministic function of the fighter ID, rendered by ' + renderer.version +
      '; no rarity was designed in. Owning this token owns the fighter; its record and rating stay with the fighter.',
    image: files.card_png.path,
    image_sha256: files.card_png.sha256,
    external_url: site ? site + '#nft/' + id : null,
    attributes: attributes(A.traits(id)).concat(tok.founding ? [{ trait_type: 'Founding', value: 'Yes' }] : []),
    properties: {
      collection: collection.name || 'QDOJO fighters', fighter_id: id, serial: tok.serial,
      asset: { issuer: tok.issuer || collection.issuer || null, name: tok.name, shares: 1 },
      renderer: { version: renderer.version, sha256: renderer.sha256 },
      files: ['card_png', 'card_svg', 'sprite_png', 'sprite_svg'].map(k => ({ role: k, uri: files[k].path, type: k.endsWith('png') ? 'image/png' : 'image/svg+xml', sha256: files[k].sha256, ...(files[k].width ? { width: files[k].width, height: files[k].width } : {}) })),
      dynamic: 'none: rank, belts, titles and record are live game data, not metadata',
    },
  };
}

// ---- freeze -------------------------------------------------------------------------
function render(tok, A) {
  const card = A.svg(tok.fighter_id), sprite = A.svg(tok.fighter_id, 'sprite');
  const cardPx = rasterize(card, 64), spritePx = rasterize(sprite, 48);
  return { card, sprite, cardPx, spritePx };
}

function freeze(opts) {
  const input = JSON.parse(fs.readFileSync(opts.tokens, 'utf8'));
  const renderer = loadRenderer(opts.avatars);
  const A = renderer.A;
  const out = opts.out;
  fs.mkdirSync(path.join(out, 'objects'), { recursive: true });
  const put = (bytes, ext) => {
    const h = sha(bytes), rel = 'objects/' + h + '.' + ext;
    fs.writeFileSync(path.join(out, rel), bytes);
    return { path: rel, sha256: h };
  };
  const tokens = [];
  const seen = new Map();
  const duplicates = [];
  for (const tok of [...input.tokens].sort((a, b) => a.serial - b.serial)) {
    if (!/^[0-9a-f]{64}$/.test(tok.fighter_id)) throw new Error('bad fighter id ' + tok.fighter_id);
    const r = render(tok, A);
    const files = {
      card_svg: put(Buffer.from(r.card, 'utf8'), 'svg'),
      sprite_svg: put(Buffer.from(r.sprite, 'utf8'), 'svg'),
      card_png: { ...put(encodePng(r.cardPx, 64, SCALE), 'png'), pixels_sha256: sha(r.cardPx), width: 64 * SCALE },
      sprite_png: { ...put(encodePng(r.spritePx, 48, SCALE), 'png'), pixels_sha256: sha(r.spritePx), width: 48 * SCALE },
    };
    const meta = metadata(tok, A, renderer, files, input.collection || {}, input.site);
    files.metadata = put(Buffer.from(JSON.stringify(meta, null, 1) + '\n', 'utf8'), 'json');
    // Visual duplicates: identical sprite pixels, whatever the SVG bytes (AUD-009).
    const px = files.sprite_png.pixels_sha256;
    if (seen.has(px)) duplicates.push([seen.get(px), tok.fighter_id]); else seen.set(px, tok.fighter_id);
    tokens.push({ fighter_id: tok.fighter_id, serial: tok.serial, name: tok.name, fighter_name: tok.fighter_name || null, ...files });
  }
  const manifest = {
    schema: SCHEMA, collection: input.collection || {}, site: input.site || null,
    renderer: { version: renderer.version, file: 'apps/web/avatars.js', sha256: renderer.sha256 },
    scale: SCALE, count: tokens.length, duplicates, tokens,
    root: sha(JSON.stringify(tokens)),
  };
  fs.writeFileSync(path.join(out, 'manifest.json'), JSON.stringify(manifest, null, 1) + '\n');
  console.log(JSON.stringify({ tokens: tokens.length, root: manifest.root, renderer: renderer.version, duplicates: duplicates.length }));
}

// ---- verify -------------------------------------------------------------------------
function verify(opts) {
  const out = opts.out;
  const m = JSON.parse(fs.readFileSync(path.join(out, 'manifest.json'), 'utf8'));
  const renderer = loadRenderer(opts.avatars);
  const A = renderer.A;
  const bad = [];
  if (m.schema !== SCHEMA) bad.push('manifest schema ' + m.schema);
  if (sha(JSON.stringify(m.tokens)) !== m.root) bad.push('manifest root does not match its token list');
  if (m.renderer.sha256 !== renderer.sha256) console.error('note: avatars.js changed since the freeze (' + m.renderer.version + ' -> ' + renderer.version + '); checking the art itself');
  const read = (f, what) => {
    const b = fs.readFileSync(path.join(out, f.path));
    if (sha(b) !== f.sha256 || path.basename(f.path).split('.')[0] !== f.sha256) bad.push(what + ': stored bytes do not hash to their name');
    return b;
  };
  for (const t of m.tokens) {
    const tag = t.name + ' (' + t.fighter_id.slice(0, 12) + ')';
    const r = render(t, A);
    if (sha(Buffer.from(r.card, 'utf8')) !== t.card_svg.sha256) bad.push(tag + ': the renderer draws a different card SVG');
    if (sha(Buffer.from(r.sprite, 'utf8')) !== t.sprite_svg.sha256) bad.push(tag + ': the renderer draws a different sprite SVG');
    read(t.card_svg, tag + ' card.svg'); read(t.sprite_svg, tag + ' sprite.svg');
    for (const [k, size, px] of [['card_png', 64, r.cardPx], ['sprite_png', 48, r.spritePx]]) {
      const b = read(t[k], tag + ' ' + k);
      try {
        const got = decodePng(b, size, m.scale);
        if (sha(got) !== t[k].pixels_sha256) bad.push(tag + ': ' + k + ' pixels differ from the manifest');
        if (sha(got) !== sha(px)) bad.push(tag + ': ' + k + ' pixels differ from the renderer');
      } catch (e) { bad.push(tag + ': ' + k + ': ' + e.message); }
    }
    const meta = JSON.parse(read(t.metadata, tag + ' metadata').toString('utf8'));
    if (!meta.description.startsWith(A.bio(t.fighter_id))) bad.push(tag + ': the bio changed');
    const want = JSON.stringify(attributes(A.traits(t.fighter_id)));
    if (JSON.stringify(meta.attributes.filter(a => a.trait_type !== 'Founding')) !== want) bad.push(tag + ': the traits changed');
    if (meta.image_sha256 !== t.card_png.sha256) bad.push(tag + ': metadata image hash differs');
  }
  if (bad.length) { console.error(bad.join('\n')); process.exit(1); }
  console.log(JSON.stringify({ verified: m.tokens.length, root: m.root, renderer: renderer.version }));
}

if (require.main === module) {
  const a = args(process.argv.slice(2));
  const cmd = a._[0];
  a.avatars = a.avatars || path.resolve(__dirname, '../apps/web/avatars.js');
  if (!a.out || (cmd === 'freeze' && !a.tokens) || !['freeze', 'verify'].includes(cmd)) {
    console.error('usage: nft-freeze.cjs freeze --tokens FILE --out DIR | verify --out DIR  [--avatars FILE]');
    process.exit(2);
  }
  try { (cmd === 'freeze' ? freeze : verify)(a); } catch (e) { console.error('nft-freeze: ' + e.message); process.exit(1); }
}
module.exports = { rasterize, encodePng, decodePng, attributes };
