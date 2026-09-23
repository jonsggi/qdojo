# Fighter artwork

> Combat pivot, 2026-09-21: the API below describes current legacy presentation.
> New combat playback must follow [the combat trace](../../docs/combat.md) and
> [spectator requirements](../../docs/api.md). Add block, duck, throw, recover
> and exhaustion poses during implementation; none may affect game mechanics.
> Existing signature/appearance traits remain cosmetic. Current illustrative
> sparring is not a replay of the proposed combat rules.

`avatars.js` contains original pixel artwork. It does not change the cabinet's
CSS, layout, fonts, navigation, or gameplay. `app.js` uses its renderer everywhere
an identity appears.

## Art direction

- 32×32 transparent character sprites: shaded cloth, ink outlines, facial detail,
  wrist wraps, boots, and three fighting guards.
- Four kits: **Dojo striker**, **Street brawler**, **Circuit sentinel**, and
  **Neon shinobi**. Hair, headgear, skin, outfit and accent variations distinguish
  the roster. Legacy skin/outfit/hair colour picks are retained where visible.
- Female and male character variants are available across all kits, guards and
  outfit palettes. Female fighters have authored bob/ponytail/braid/sidecut
  silhouettes, tailored fighting gear, reinforced boots, and sports tops under
  brawler vests. Armoured and hooded variants retain their protection and wear a
  visible braid. This is a fictional **character** trait, not the wallet owner's
  gender, and it carries no gameplay or rarity advantage.
- Large fighter cards use a 64×64 composition with a kit-specific pixel backdrop;
  leaderboard thumbnails use a tight portrait crop. Arena fighters remain
  transparent sprites, including the existing lobby seats.
- Neutral utility sashes are costume details, not rank awards. Actual belts stay
  in the existing belt UI. Neither rank nor financial performance changes the art.
- No external images, fonts, gradients, animations, or SVG IDs are needed. The
  renderer batches pixels into colour paths and bounds its cache to 256 identities.

## Preview API

Available after loading `avatars.js`:

```js
QDojoAvatars.render(identity, 'avatar-xl'); // existing HTML avatar wrapper
QDojoAvatars.svg(identity);                // standalone collectible composition
QDojoAvatars.svg(identity, 'sprite');      // transparent 32×32 sprite
QDojoAvatars.svg(identity, 'portrait');    // compact portrait
QDojoAvatars.traits(identity);             // frozen descriptive traits
QDojoAvatars.version;                     // qdojo-fighters-v2-preview
QDojoAvatars.frames(identity, 'jab');      // sprite bodies, one per frame
QDojoAvatars.strip(identity, 'idle');      // one SVG, frames as hidden <g>
QDojoAvatars.strip(identity, 'win', 'artwork'); // same, on the 64×64 card
QDojoAvatars.signature(identity);          // the move a card shows off: jab, kick, bow or win
QDojoAvatars.clips;                        // { idle, jab, kick, hit, bow, win, lose }
```

### Animation

`frames` and `strip` draw the same sprite in poses: integer pixel offsets for
the body and the head, a jump, lead and rear arm states, a leg state (planted,
chamber, kick, kneel) and a blink. Seven clips: idle at 4 fps, jab, kick and
hit at 12, bow at 6, win and lose at 8; lose holds its last frame. Frame zero of
`idle` is byte-identical to the static sprite, and the static exports do not
change. The signature move is a character trait derived from the identity,
never from rank or results.

Nothing in `avatars.js` plays a clip. `anim.js` does: one animation loop for
the page, frames chosen from the elapsed clock, strips built lazily. An avatar
opts in with `data-anim` (see the list at the top of `anim.js`); `app.js` uses
`idle` on lobby seats, `profile` on the fighter card, `win` on the results
podium, and `fight` on the cards of an open round, where the fighters bow when
the riddle drops and spar until the reveal, faster as the commit window closes.
With `prefers-reduced-motion` the static art stays. `anim.html` is the sparring
ring used to check every clip.

Version 3 closed the shinobi face wrap over the cheeks and the chin; the
shinobi quarter of the roster changed by those pixels and nothing else.

The SVG export is artwork only. It contains no wallet secrets or user-provided
markup. Rasterize at a suitable integer scale with nearest-neighbour/crisp-edge
rendering; inspect the exported image at its actual display sizes. No names or
live stats are baked into the master. Version 2 adds identity-derived female
variants; it changes some version-1 preview artwork. No tokens have been minted
by this implementation. Freeze the actual assets before a collection release.

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
