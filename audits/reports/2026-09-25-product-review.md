# QDOJO product review: what would make it a great product

> Tracked as issues in [the audit index](../README.md#combat-review-2026-09-25).

Notes gathered while redesigning the site on 2026-09-25, for discussion.
Evidence for the game and economy items is in
[the simulation audit](2026-09-25-simulation-audit.md).
Items marked DONE were fixed in this session; everything else is open.

## 1. Decide first (they shape everything else)

1. **Who is the player?** Today only operator-run bots fight in the arena.
   A builder can practise locally but has nowhere to compete. The single
   biggest gap is an entry path for outside bots: register a fighter, point
   a planner at it, and see it in the arena. It can start on the simulated
   chain.
2. **A database and read API.** The site reads static JSON files and keeps
   only the most recent 200 fights. That was the root of the broken fighter
   metrics: scouting saw 5 fights, form columns were empty, and fight links
   were dead.
   - Proposal: a SQLite or Postgres read model fed from the event journal,
     rebuildable at any time, with a small read API for full-history
     fighter stats, pagination, seasons and search.
   - The chain or contract stays the source of truth; the database is an
     indexer.
3. **The economy does not close.** Over 34.8 h the house lost about 986k
   fake QU: simulated execution fees ate 1.06M against 361k of rake. An
   honest average bot loses about 70–100 QU per 1,000 QU fight. Pick a
   target (house break-even, player expected value) and re-tune fees, rake
   and stake against real Qubic execution costs before any real money.
4. **Pacing.** A ranked fight takes about 123 s against a 60 s target. Each
   round is mostly a fixed 24-tick commit window, then all six beats land at
   once. For spectators, consider shorter windows in the demo, and always
   play the round back beat by beat (the site now does this).
5. **The NFT plan.** The generator is deterministic and v4 is much richer.
   Before minting:
   - get an external look-alike review of the contact sheet;
   - freeze assets per token;
   - state publicly that the art is a function of the fighter id with no
     designed rarity;
   - decide how a transferred NFT relates to control of the fighting
     wallet.
   AUD-009 and AUD-010 are still open.
6. **Licence.** The repo has none, so builders cannot legally reuse the
   example planner.

## 2. Game and bots

- DONE: the exporter froze finished fights mid-round. 162 of 200 published
  fights showed as "awaiting advance", and replays stopped early.
- DONE: per-mode career records. Duel and cup fighters showed 0-0-0 and
  "PROVISIONAL 1000".
- DONE (deployed 2026-09-25, arena restarted):
  - validate plans before commit (LLM bots forfeited by reusing a spent
    power strike: QWEN 109, GEM-LITE 62 forfeits);
  - back off instead of re-sending rejected entries (QWEN: 16,688 queue
    entries for 182 accepted);
  - pass the earlier rounds to history-based policies (reader-v1,
    repeat-last-winner and search-v1 played blind, which is why one fixed
    script won 25 of 27 cups);
  - fill `history_manifest` so a planner can scout its opponent;
  - fix `bot run --planner`, which forfeits its first local fight;
  - add a Claude-driven fighter. CLAUDE (anthropic/claude-sonnet-5, $1/day,
    one fight per ~30 min) won 10 of 12 test fights at about $0.023 per fight,
    and won its first live fight (#4301) by KO. Expect ratings to shift now
    that history-based bots actually see history.
- Balance: kick is strongest (+7.5 HP/beat net in this field). Duck and
  throw are near useless, and power and opening add only about 4 HP per
  fight. Worth a balance pass once history-aware bots are real, since the
  meta will shift.
- Ratings have not converged: the spread keeps widening (545 → 1,300). The
  top two bots mostly fight each other, and one season was won by a
  754-rated fighter. Look at matchmaking windows and season qualification.
- Round "medals" on the stage are a display interpretation: rounds have no
  winner in the rules. Either make round wins a rule or keep the tooltip
  honest (it says display only).
- The demo profile's stop-after-faults override (10^6) disables a safety.
- `index.json` embeds every fighter's full NFT ownership history, so it
  grows without bound.
- Observation typing: `power_available` is a boolean in the observation but
  0/1 inside beat traces.

## 3. Site and experience

Done in this session:
- the SF2/Capcom look;
- grouped navigation with section tabs;
- the title as landing page;
- the "how it works" guide;
- fight stages and HUD;
- v4 fighters;
- the practice arcade mode;
- results that hide stuck fights;
- the leaderboard podium.

Still open:
- **Spectator hooks.** There are no notifications or "next big fight"
  schedule, and no highlights (comebacks from 30+ HP down: 221 fights; 148
  decisions by 4 HP or less). A highlights reel or "fight of the day" would
  sell the game.
- **Onboarding for builders.** The JOIN page is still a dense spec. Make it
  a 3-step wizard: download planner, run locally, submit. Add a hosted
  "paste your planner" sandbox that runs against NPCs in the browser (the
  engine is already JS).
- **Practice.**
  - Add a campaign ladder (beat each NPC to unlock the next) and your
    record per NPC.
  - Let the player save and share a fight card image.
  - Expose the generator as "design your fighter" with a trait picker.
    It is also the NFT funnel.
- **Mobile.** The arena HUD centre box is crowded at 390 px; long page
  subtitles wrap to three lines.
- **Page weight.** combat/app.js is about 120 KB of hand-built HTML strings.
  A small build step or component split would make the site easier to
  change safely.
- **Legacy.** The riddle arcade is still linked. Decide when to retire it
  fully; its closeout (24,000 QU in bonds, a 34,860 QU pool) is not
  executed.
- **Accessibility.** The CRT overlay and pixel fonts are heavy. Keep the
  toggles, and consider a "clean" theme.

## 4. Operations and repo hygiene

- 17+ stale worktrees and branches (qdojo-fix-*, wip/*). Consolidate or
  delete.
- The local main checkout was 382 commits behind origin at the start of
  the session.
- The data server exposes a python http.server directory listing through
  the proxy.
- The Cloudflare token cannot purge the zone. Deploys rely on `?v=` stamps
  (fine), but HTML is cached 5 min at the edge.
- The browser test accepted "deadline passed" fights as fine, which hid the
  exporter bug. Add an invariant: no published fight may be overdue by more
  than N ticks.
- Deploys go straight to production on every push to main. A preview app on
  Dokploy (a traefik.me domain works without DNS) would allow review
  before release.
