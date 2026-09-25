# Fighter artwork

> Combat playback follows [the combat trace](../../docs/combat.md) and the
> [spectator requirements](../../docs/api.md). v4 adds block, duck, throw,
> recover and exhaustion clips; none of them affects game mechanics.
> Signature and appearance traits remain cosmetic. The sparring ring
> (`anim.html`) is illustrative, not a replay of the combat rules.

`avatars.js` contains original pixel artwork. It does not change fonts,
navigation or gameplay. `combat/app.js`, the legacy `app.js` and `dash.js` use
its renderer everywhere an identity appears.

## Art direction (v4 preview)

Fighters are drawn in the spirit of early-90s arcade fighting games: athletic,
muscular bodies with broad shoulders, big fists and a side-on fighting stance;
hard 3–4 tone shading from the upper right with muscle highlights; a dark 1px
outline; warm, saturated but natural palettes. Every design is original: no
character, costume or asset from an existing game was copied or traced.

- **48×48 transparent sprites**, about four heads tall. A sprite is built from a
  small skeleton (shoulders, elbows, fists; hips, knees, ankles). Each body part
  is a pixel mask shaded in a five-step ramp (deep, shadow, base, light,
  highlight; shadows lean violet, lights lean warm). Where a part overlaps
  another it draws a dark separation line on it. Faces (brows, eyes, nose,
  mouth, ear), knuckles, cloth folds, belt knots and muscle lines are placed by
  hand on top.
- **64×64 collectible card**: a frame, a kit-specific pixel scene, a floor
  shadow, the fighter at 1:1 (no scaling, so every sprite pixel stays one card
  pixel) and a blank name plate. No names or stats are baked in. Leaderboards
  use a 24×24 portrait crop of the sprite; arenas use the transparent sprite.
- No external images, fonts, gradients, filters, animations or SVG IDs. The
  renderer batches pixels into one path per colour (about 30–50 paths, ~9 KB
  per sprite), keeps a bounded cache of 256 identities, and renders a sprite
  plus card in well under a millisecond or two.
- Neutral belts and sashes are costume details, not rank awards. Earned belts
  stay in the application's belt UI. Neither rank nor financial performance
  changes the art.

### Traits

Every trait comes from its own hash domain (`qdojo/fighter/v4/<trait>/<id>`),
so traits are independent of each other. `traits(identity)` reports each one
by a human-readable name; colour traits are also given as hex.

| Trait | Options |
| --- | --- |
| archetype (kit) | 12: Dojo striker, Street brawler, Circuit sentinel (cyborg), Neon shinobi, Sumo wrestler, Pro wrestler, Commando, Kung-fu master, Capoeira dancer, Mountain mystic, Prize boxer, Muay Thai fighter |
| backdrop | 12, one per kit (Sunset dojo, Midnight rooftop, Reactor chamber, Moon gate, Clay ring, Arena lights, Jungle base, Lantern market, Harbour dusk, Mountain temple, Boxing gym, River stadium) |
| character | 2: Female, Male (a fictional character trait, see below) |
| build | 3: Lean, Standard, Heavy (sumo always heavy, mystic always lean, wrestlers never lean) |
| stance | 3 guards: Low guard, Boxer guard, Power stance |
| skinTone | 8 hand-picked ramps, Porcelain to Ebony |
| palette | 14 curated outfit sets (main, second, trim), e.g. Classic white, Crimson, Royal blue, Olive drab, Black and gold |
| accent | 6 (visors, core lights, card frame) |
| hairstyle | 9 male (Crew cut, Spiked, Swept back, Flat-top, Topknot, Mohawk, Shaggy, Tied-back, Buzzed), 7 female (Combat bob, High ponytail, Long braid, Sidecut, Twin buns, Pixie, Long loose); kits fix it where the costume demands (Bald mystic, Topknot sumo, Armoured braid under helmets, hoods and masks) |
| hairColour | 10 |
| eyes | 6 |
| expression | 4 (Determined, Fierce, Calm, Grinning); Hidden behind masks |
| facialHair | 6 (None, Stubble, Moustache, Goatee, Full beard, Chin strap), male faces only |
| scar | 4 (None, Brow scar, Cheek scar, Nose bandage) |
| headgear | 1–5 per kit, 17 in all (Hachimaki, Headband, Bandana, Backwards cap, Beret, Head guard, Mongkhon, Visor/Crested helmet, Cyber eye, two hoods, three wrestling masks, Forehead mark, None) |
| gloves | 4 free choices (Bare fists, Tape wraps, Fingerless gloves, Leather gloves) or the kit's own (Armoured gauntlets, Boxing gloves, Hand wraps, Spiked bracelets) |
| shoulders | None, Shoulder guard, Studded pad (brawler, shinobi, commando); Pauldron (sentinel) |
| sash | 4 belt patterns: Plain, Striped, Checked, Stitched |
| markings | 5: None, Arm tattoo, Face paint, Cheek stripes, Chest tattoo (only where the skin shows) |
| pattern / emblem | 4 outfit patterns (Plain, Trim, Stripes, Emblem) and 5 emblems (Sun disc, Tomoe, Diamond, Wave, Crane) |
| signature | the card's show-off move: jab, kick, bow or win |

That is roughly 10^11–10^12 trait combinations per kit, although many
differ only in small details (eye colour, accent, sash pattern). The legacy
keys `outfit`, `skin`, `hair`, `headband` and `accent` are still present.

- Female and male character variants exist across all kits, builds, guards and
  palettes, with the same hash domain as v1–v3 so a fighter keeps its variant.
  Female fighters wear full-coverage fighting gear (sports tops, singlets, crop
  tops, wraps) on bare-chested kits. This is a fictional **character** trait,
  never an inference about the wallet owner, and it carries no gameplay or
  rarity advantage. No trait is ever inferred from the owner.

### Originality guards

The genre's archetypes (karate gi, sumo, boxer, ninja, commando) are fair game;
copying a specific character is not. A few trait combinations would read as one
famous character, so the generator steers them away: a white gi never gets a red
headband, a red gi never gets blond hair, kung-fu fighters never wear twin buns,
commandos never have a flat-top (nor a beret with a long braid), pro wrestlers
never have a mohawk, sumo wrestlers never wear face paint, and the mystic wears
a draped robe and often has hair. Tests pin these rules. Review the full contact
sheet for anything else that reads as a known character before a release.

## Preview API

Available after loading `avatars.js`:

```js
QDojoAvatars.render(identity, 'avatar-xl'); // existing HTML avatar wrapper
QDojoAvatars.svg(identity);                // 64×64 collectible card
QDojoAvatars.svg(identity, 'sprite');      // transparent 48×48 sprite
QDojoAvatars.svg(identity, 'portrait');    // 24×24 head-and-shoulders crop
QDojoAvatars.traits(identity);             // frozen descriptive traits
QDojoAvatars.version;                      // qdojo-fighters-v4-preview
QDojoAvatars.size;                         // 48 (sprite edge in pixels)
QDojoAvatars.frames(identity, 'jab');      // sprite bodies, one per frame
QDojoAvatars.strip(identity, 'idle');      // one SVG, frames as hidden <g>
QDojoAvatars.strip(identity, 'win', 'artwork'); // same, on the 64×64 card
QDojoAvatars.signature(identity);          // jab, kick, bow or win
QDojoAvatars.clips;                        // clip table, see below
```

`render` picks the portrait for `avatar-sm`, the card for `avatar-xl` and the
sprite otherwise.

### Display sizes

Pixel art stays crisp at integer scales. On 1x screens that means multiples of
48 (sprite) or 64 (card); on 2x screens any multiple of 24 or 32 CSS pixels is
an integer number of device pixels per art pixel. v4 moved the CSS sizes
accordingly: `.avatar` 40→48, `.avatar-lg` 64→72, the lobby seat 64→72, the
phone arena corner 64→72, the attract-screen VS avatars 80→72, the champion
portrait 32→48. The card stays at 128 (2x) and 96 on narrow screens.

### Animation

`frames` and `strip` draw the sprite in poses. A pose moves joints by whole
pixels: `dx`/`dy` move everything above the hips (the hips follow, the feet stay
planted, so knees bend naturally), `hx`/`hy` add to the head, `jump` lifts the
whole sprite; `lead` and `rear` choose arm states (guard, jab, wind, up, down,
block, grab, pull, knee, fling), `legs` a leg state (plant, chamber, kick,
kneel, crouch, step) and `blink` closes the eyes.

| Clip | fps | frames | |
| --- | --- | --- | --- |
| idle | 5 | 8 | breathing bob and a blink; frame zero is the static sprite byte for byte |
| jab | 12 | 6 | wind-up, straight punch, retract |
| kick | 12 | 6 | knee chamber, extended kick, recover |
| hit | 12 | 5 | head snaps back, arms fling |
| bow | 6 | 9 | arms down, bow, straighten |
| win | 8 | 10 | fist pump with a hop |
| lose | 8 | 4 | down on one knee; holds its last frame |
| block | 10 | 6 | forearms up in front of the face, leaning back |
| duck | 10 | 7 | deep crouch under the guard |
| throw | 10 | 7 | step in and grab with both hands, pull back |
| recover | 6 | 6 | hands on knees, then back to guard |
| exhausted | 5 | 6 | hunched over, hands on knees, breathing |

Nothing in `avatars.js` plays a clip. `anim.js` does: one animation loop for
the page, frames chosen from the elapsed clock, strips built lazily. An avatar
opts in with `data-anim` (see the list at the top of `anim.js`). The combat
replay plays `jab`, `kick`, `throw`, `block`, `duck`, `recover` and
`exhausted` for the matching actions and `hit` when a fighter loses HP without
attacking or blocking. With `prefers-reduced-motion` the static art stays.
`anim.html` is the sparring ring used to check every clip. The signature move
is a character trait derived from the identity, never from rank or results.

### Rendering NFT masters

The SVG is the master. Rasterize it only at integer scales with
nearest-neighbour sampling, e.g. the card at 16× (1024×1024) or the sprite at
16× (768×768), and check the result at its actual display sizes. Any
non-integer scale produces uneven pixels. The SVG contains no wallet secrets or
user-provided markup.

### History

v4 (this preview) replaced the 32×32 v1–v3 art entirely: new size, skeleton,
kits, trait domains and card; it keeps the character-variant hash and the
signature move. v3 had closed the shinobi face wrap; v2 added female variants.
No tokens have been minted from any version. Freeze the actual assets before a
collection release.

Run the dependency-free regression suite:

```sh
node --test apps/web/tests/avatars.test.cjs
```

## Before an NFT release

This is a **preview art system**, not a mint implementation or final collection.
Do not treat the hash-derived appearance as guaranteed unique, unpredictable, or
rare: identities can be generated until desirable traits appear, and the finite
trait space permits duplicate art. The tests check the current public roster only.

Before minting:

1. Get explicit approval of the character designs and a full collection contact
   sheet. Curate silhouettes and palettes rather than relying only on recolours.
2. Decide collection size, allocation, duplicate policy, and whether custom or
   authored one-of-one characters will exist. Do not infer rarity from this hash.
3. Freeze a renderer version **and the actual exported artwork and traits** per
   token. Store content-addressed assets and metadata. A future code deployment
   must not silently alter previously sold artwork.
4. Specify how Qubic fighter identity, NFT ownership, and display rights relate.
   A transferred collectible is not automatically control of a fighting wallet.
5. Keep static art traits separate from dynamic belt/performance metadata. Define
   which fields can change, who controls them, and how changes are verified.
6. Establish an explicit artwork licence, commercial/display rights, and a legal
   review of collection branding and any financial or promotional claims. No
   third-party fighting-game characters or assets were imported here; that alone
   is not legal clearance.
7. Test the target marketplace's SVG support and provide a lossless PNG rendition
   if required. Validate metadata and storage before any mint or sale.
8. The v4 look deliberately evokes early-90s arcade fighters. Have someone
   outside the project review the contact sheet for resemblance to specific
   commercial characters, and extend the originality guards for anything that
   comes up. Do not use existing game names or logos in collection branding.
9. Traits are hash picks, so some combinations are rarer than others by
   accident (for example a heavy female sumo with a given palette). If the
   collection is minted from existing fighter ids, publish that the art is a
   deterministic function of the id and that no rarity was designed in.
