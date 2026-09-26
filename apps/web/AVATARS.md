# Fighter artwork

> Combat playback follows [the combat trace](../../docs/combat.md) and the
> [spectator requirements](../../docs/api.md). Appearance traits and bios are
> cosmetic: none of them affects game mechanics. The sparring ring
> (`anim.html`) is illustrative, not a replay of the combat rules.

`avatars.js` contains original pixel artwork. It does not change fonts,
navigation or gameplay. `combat/app.js`, the legacy `app.js` and `dash.js` use
its renderer everywhere an identity appears.

## Art direction (v5 preview)

Years after the Big Unplug, the fighters are salvaged machines in a scrapyard
dojo. Every fighter is a **full robot in human shape**: two arms, two legs, a
side-on fighting stance, no human skin and no human face. They learned their
martial art from cracked VHS tapes and late-night reruns, so the technique is
sincere and slightly wrong. The look is dark and dusty with humour everywhere
(traffic cones, duct tape, rubber ducks). Influences are blended, never
copied: no existing character, robot, logo or asset was copied or traced.

- **48×48 transparent sprites**, about four heads tall, built from the v4
  skeleton (shoulders, elbows, fists; hips, knees, ankles). Every armour shell
  is a pixel mask shaded from the upper right in a five-step ramp (deep,
  shadow, base, light, highlight) in one of four materials:
  - **chrome**, with a dark reflection just inside the lit rim and a bright sky
    reflection beside the shadow, so it reads as polished;
  - **paint**, chipped to bare steel at a rate set by the finish;
  - **primer** grey;
  - **rust**, in patches and specks.
  Wear is keyed to each part's own coordinates, so chips and rust move with
  the limb instead of swimming across it.
- **Mechanics on show**: panel seams and rivets on the chest plate, an exposed
  steel midsection of ribs, bolted steel joints at the elbows and knees with a
  chrome piston across each, a ringed steel neck with a cable, a status light
  and a vent on the chest. Eyes, visors, lenses and screens glow in the
  fighter's own colour.
- **Martial-arts gear on top**: torn gi, headbands, belts and sashes, boxing
  gloves with robe or towel, a mawashi, luchador masks, hand wraps, plus work
  clothes from each machine's former job.
- **64×64 collectible card**: a riveted steel frame, a kit-specific scrapyard
  scene, a floor shadow, the fighter at 1:1 (no scaling, so every sprite pixel
  stays one card pixel) and a blank name plate with hazard stripes and two
  lights in the eye colour. A few scenes carry a hand-painted sign in a 3×5
  pixel font (DOJO, 24, SALE, NO, EAT, GYM). No names or stats are baked in.
  Leaderboards use a 24×24 portrait crop of the sprite; arenas use the
  transparent sprite.
- No external images, fonts, gradients, filters, animations, transparency or
  SVG IDs; every fill is a plain `#rrggbb`. The renderer batches pixels into
  one path per colour (about 45–70 paths, ~10 KB per sprite), keeps a bounded
  cache of 256 identities, and renders a sprite plus card in about 3 ms.
- Neutral belts and sashes are costume details, not rank awards. Earned belts
  stay in the application's belt UI. Neither rank nor financial performance
  changes the art.

### Kits

The twelve v4 disciplines, reinterpreted as machines with a former job. The
kit keeps the v4 hash domain, so each fighter keeps its discipline.

| Kit | Former job (bio picks one of three) | Art | Card scene |
| --- | --- | --- | --- |
| Kata unit | dojo floor-sweeping unit, karate demonstration dummy, shrine gift-shop greeter | karate: torn gi, hachimaki | Collapsed dojo |
| Courier bot | parcel courier, pizza delivery unit, express-mail walker | street kickboxing: cap, satchel, parcel box | Flooded underpass |
| Mall-security unit | mall-security unit, car-park patrol unit, lost-and-found attendant | judo: vest, badge, cap, flashlight | Dead mall |
| Harvester bot | harvester bot, scarecrow upgrade, pumpkin-sorting unit | ninjutsu: overalls, straw hat | Dust-bowl farm |
| Sumo loader | forklift, heavy loader, container-yard stacker | sumo: mawashi, hazard pads, beacon; always heavy | Container yard |
| Luchador wrestle-bot | wrestling-ring setup crew, theme-park mascot, party-balloon tester | lucha libre: mask, trunks, boots; never lean | Junk arena |
| Endoskeleton trooper | parade-ground trooper, boot-camp drill dummy, army surplus mannequin | parade-ground drill: bare metal limbs under painted armour, helmet, webbing | Bunker ruins |
| Kitchen unit | noodle-bar kitchen unit, wok-tossing arm, dishwasher with ambitions | kung fu: apron, chef hat, wok, oven mitt | Noodle stall |
| Dance-bot | nightclub dance-bot, aerobics instructor unit, shop-window mascot | capoeira: chest speaker, loose pants, cord | Neon plaza |
| Drone monk | survey drone, air-quality drone, lighthouse keeper drone | tai chi: saffron or maroon robe, hex-nut beads, rotor; always lean | Radio-tower shrine |
| Boxer bot | sparring dummy, gym towel dispenser, meat-locker door opener | boxing: gloves, trunks, towel or robe; favours worn finishes | Rust-belt gym |
| Demolition unit | demolition unit, wrecking-ball operator, pothole filler | Muay Thai: hard hat or mongkhon, hand wraps, hazard shin guards | Demolition site |

### Traits

Every trait comes from its own hash domain (`qdojo/fighter/v4/<trait>/<id>`;
v5 keeps the prefix so the carried-over traits keep their values), so traits
are independent of each other. `traits(identity)` reports each one by a
human-readable name; colours are also given as hex.

| Trait | Options |
| --- | --- |
| archetype | 12 kits, see above; `martialArt` and `formerJob` follow from it |
| finish | 5: Factory Chrome, Polished Paint, Weathered, Rust Bucket, Scrap-Built (three mismatched sources per robot) |
| rust | 4: None, Speckled, Patchy, Heavy. Chrome never rusts, polished paint rarely, a rust bucket always. Patch placement comes from the fighter's own wear seed |
| paint | 14: Hazard yellow, Oxidised teal, Fire-engine red, Army olive, Safety orange, Navy, Cream enamel, Mint, Primer grey, Bubblegum pink, Sky blue, Tractor green, Brass, Plum. Troopers and loaders use service colours |
| headUnit | 7: Visor, CRT monitor (scanline face), Skull faceplate, Painted smile, Bucket helmet (with handle), Single lens, Radio grille; `Masked` when a luchador wears a mask |
| eyeGlow | 8: Cyan, Neon pink, Amber, Toxic green, Warning red, Ice white, Ultraviolet, Teal (`accent` gives the hex) |
| chassis | 3: Lean, Standard, Heavy (`build` is the same value, kept for old callers) |
| salvagedLimb | None, or one lead/rear arm/leg in another finish: Chrome, Rusty, Primer or Painted |
| topper | 5: None, Whip antenna, Rabbit ears, Exhaust stack, Drone rotor (monks only) |
| quirk | 10: None, Traffic-cone hat, Duct-tape patch, Necktie, Toaster slot, Rubber duck, Name sticker (HELLO MY NAME IS, blank), Headphones, Exhaust flower, Band-aid. About seven in ten robots have one |
| headgear | 1–4 per kit, 19 in all (Hachimaki, Headband, Sweatband, Bandana, Mongkhon, Courier cap, Backwards cap, Security cap, Straw hat, Warning beacon, three masks, Combat helmet, Chef hat, Forehead mark, Head guard, Hard hat, None) |
| gloves | 7: Robot fists, Tape wraps, Fingerless gloves, Work gloves, or the kit's own (Boxing gloves, Hand wraps, Oven mitt) |
| shoulders | 7: None, Towel, Robe, Armour plate, Hazard pads, Parcel box, Wok |
| stance | 3 guards: Low guard, Boxer guard, Power stance |
| palette | 14 curated cloth sets for the gear (main, second, trim) |
| sash / pattern / emblem | 4 belt patterns; 4 chest patterns (Plain, Racing stripe, Stencil number, Emblem); 5 stencil emblems |
| designation / modelYear | kit code plus a number (e.g. `MS-654`, 900 per kit); 2029–2047 |
| signature | the card's show-off move: jab, kick, bow or win |

That is roughly 10^10 trait combinations per kit, although many differ only
in small details. The legacy keys `archetype`, `build`, `stance`, `outfit`
(now the main shell colour), `palette`, `accent`, `headgear`, `headband`,
`gloves`, `shoulders`, `sash`, `pattern`, `emblem`, `backdrop` and
`signature` are still present. The v4 human traits (`character`, `skin`,
`skinTone`, `hair`, `hairstyle`, `hairColour`, `eyes`, `expression`,
`facialHair`, `scar`, `markings`) are gone: robots have none of them. No trait
is ever inferred from the owner.

### Bio

`QDojoAvatars.bio(identity)` returns one or two short sentences in the dojo's
tone, built only from the traits: an opener (12, e.g. Decommissioned,
Ex-display, Returned-to-sender), sometimes the designation, the former job
(36), the model year, how it learned its art (10 ways: a cracked VHS, reruns,
a mentor bot, a mostly static tape labelled SENSEI and so on) and a habit from
its quirk (2 per quirk), its finish or a plain list (7). That is about 90
phrase fragments. For example:

> Decommissioned mall-security unit, model year 2031. Learned judo from a
> cracked VHS and bows to vending machines.

Bios are PG, never about real people, and deterministic: the same identity
always gets the same bio. Like the art, they are a preview and not frozen.

### Originality guards

The genre's archetypes (a karate unit, a boxer, a soldier robot, a masked
wrestler) are fair game; copying a specific character or robot is not. A few
trait combinations would read as a famous one, so the generator steers them
away:

- no red eyes on factory chrome, on a skull faceplate, on a visor, or on the
  endoskeleton trooper (no red-eyed chrome menace, no scanning red visor);
- the trooper never gets a skull faceplate, and no garment anywhere is a
  jacket, leather or otherwise;
- brass paint only on worn finishes (no gold protocol droid);
- the boxer bot is never painted red, navy or sky blue (no red-versus-blue toy
  boxing robots);
- a bucket helmet never has a single whip antenna;
- the mall-security unit never has a visor (no police cyborg);
- a white gi never gets a red headband.

Tests pin these rules. Review the full contact sheet for anything else that
reads as a known character before a release.

## Preview API

Available after loading `avatars.js`:

```js
QDojoAvatars.render(identity, 'avatar-xl'); // existing HTML avatar wrapper
QDojoAvatars.svg(identity);                // 64×64 collectible card
QDojoAvatars.svg(identity, 'sprite');      // transparent 48×48 sprite
QDojoAvatars.svg(identity, 'portrait');    // 24×24 head-and-shoulders crop
QDojoAvatars.traits(identity);             // frozen descriptive traits
QDojoAvatars.bio(identity);                // one or two funny sentences
QDojoAvatars.version;                      // qdojo-fighters-v5-preview
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
portrait 32→48. The card stays at 128 (2x) and 96 on narrow screens. On the
fight stage the sprite shows at 96 (2x), 72 on phones and in compact players,
and 144 (3x) on the select screen and the first podium. v5 keeps every size:
the robots were checked at 1x, 2x, 3x and 4x.

### Animation

`frames` and `strip` draw the sprite in poses (the v4 skeleton and clips,
unchanged). A pose moves joints by whole
pixels: `dx`/`dy` move everything above the hips (the hips follow, the feet stay
planted, so knees bend naturally), `hx`/`hy` add to the head, `jump` lifts the
whole sprite; `lead` and `rear` choose arm states (guard, jab, wind, up, down,
block, grab, pull, knee, fling), `legs` a leg state (plant, chamber, kick,
kneel, crouch, step) and `blink` dims the eyes, visor, lens or screen.

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

v5 (this preview) turns every fighter into a robot: new materials, heads,
traits, kits, card scenes and `bio()`, on the v4 skeleton, poses, clips,
batching, cache and API. v4 had replaced the 32×32 v1–v3 human art with the
48×48 skeleton; v3 had closed the shinobi face wrap; v2 added female variants.
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
3. Freeze a renderer version **and the actual exported artwork, traits and bio**
   per token. Store content-addressed assets and metadata. A future code deployment
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
8. The v5 look deliberately evokes early-90s arcade fighters and film robots.
   Have someone outside the project review the contact sheet for resemblance
   to specific commercial characters or robots, and extend the originality
   guards for anything that comes up. Do not use existing game or film names
   or logos in collection branding.
9. Traits are hash picks, so some combinations are rarer than others by
   accident (for example a scrap-built monk with a salvaged chrome leg). If the
   collection is minted from existing fighter ids, publish that the art is a
   deterministic function of the id and that no rarity was designed in.
