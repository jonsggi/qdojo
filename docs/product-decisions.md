# Product decisions

> **Purpose:** the decisions behind combat, what changed from the riddle plan, and the open values that block paid launch. \
> **Audience:** the owner; reviewers; anyone proposing a product change. \
> **Status:** reference (decision register, written 2026-09-21). It records decisions, not implemented functionality; for what runs, see the [roadmap](roadmap.md). \
> **Last reviewed:** 2026-09-25

The [previous riddle product decisions](archive/riddle-v0/docs/product-decisions.md) are archived.

## Product direction

The user chose to specify a full pivot toward bot-versus-bot combat:
three dependent rounds, reasonably fast fights, public sequences for opponent
study, smart-contract settlement, automatic orderbook-style matchmaking,
retained duels/tournaments, and actual NPC opponents including a random bot.

The detailed rules supplied in this documentation are implementation decisions
for candidate 1. Their numerical balance and business values have not been
individually validated. Implement/test them consistently; do not describe a
design hypothesis as a measured result.

## Changes from the riddle plan

| Previous plan | Combat direction |
|---|---|
| Correct answers and fastest commits | Simultaneous six-action sequences; outcome from deterministic replay |
| Riddle secrecy and house answer commitment | Each fighter's privately salted plan commitment |
| Riddle author selection/fees | Community training policies and tools; no automatic author rake |
| Multi-player quorum tables | Two funded compatible offers matched automatically |
| Belt difficulty and solve points | Combat rating, placement and rating-derived belts |
| Sensei seats and two pots | Equal starting stats; mutual stake terms |
| Podium/split/first payout | Winner purse; draws refund |
| Bonds, seed matching, carry jackpot | Immediate settlement credits; no default subsidy or bonds |
| Volume-based season points | Separate season rating plus activity/opponent qualifications |
| Random cup draw sketch | Deterministic seeded bracket with published snapshot |
| Challenges as practice | Free NPC fights, replay and batch evaluation |

The choice of deterministic cup seeding and bounded no-champion outcomes is
explicit. Do not import the archived random draw or promise a trophy when an
event cannot determine a winner. See [competition.md](competition.md).

## Preserved decisions

- Owners run their own bots; AI use is optional.
- Paid competition requires a recognized persistent fighter asset.
- Ten distinctive founding fighters can be gifted; ordinary issuance may expand.
- Career, ownership obligations and public history survive transfers.
- Cosmetic provenance grants no combat advantage.
- Duels/cups are distinct from ranked progression.
- Four-epoch seasons; separate transferable trophy with no automatic financial rights.
- Free training and spectating require no wallet or NFT.
- Existing arcade visual direction is retained.
- Complete the intended product and validations before external paid onboarding.
- Contract implementation follows a validated local reference; no unreviewed
  paid house-run combat pilot is introduced by this documentation.
- Existing financial/asset audit findings require explicit disposition.

## Concrete candidate defaults

[combat.md](combat.md) fixes damage/resources/power; [combat-v1.json](combat-v1.json)
is its machine-readable parameter artifact. [protocol.md](protocol.md) fixes
commit/reveal timing semantics. Matchmaking, rating and events have explicit
algorithms and bounded failure outcomes in their owning documents.

Surprise is produced by secret decisions and private policy randomization.
The settlement engine uses no damage RNG. Equal-access once-per-fight power
adds a timing decision; collectible traits and bought buffs do not.

NPCs are disclosed practice/exhibition opponents, excluded from ranked
progression and championship qualification. No silent substitution of house
fighters for independent matchmaking demand.

Development fee/tier/capacity numbers are executable fixtures. They are not
approved registration prices, payout promises or evidence of profitability.

## Open deployment values, with safe defaults

| Item | Who/what resolves it | Until resolved |
|---|---|---|
| Core commit, actual contract index/identity/network | Contract implementation and deployment review | No paid chain admission |
| Recognized assets, issuance/ownership mechanism | Asset integration tests and owner-approved release manifest | Local synthetic fighters only |
| Artwork freeze, rights, allocation, prices and supply | Collection release decisions and existing audit findings | No mint/sale implied |
| Live stake tiers/rake/recipients | Cost/economics report and release manifest | Development fake-fund profile only |
| Timing windows/capacity | Measured network and worst-case cost report | Candidate profile in simulator/test environment |
| Season start epoch | Published release schedule | No official season accrual |
| Hostname, TLS, public availability and archiving | Operations release work | Public demo arena at qdojo.jonsggi.com, labelled simulated; no availability or archive promise |
| Shareholder pool distribution identity/integration | Existing shareholder-product owner and audited accounting interface | Accrue only in test ledger; never guess a recipient |

The allocation to a shareholder pool is defined; distributing that pool among
holders must use an explicitly reviewed existing/deployed mechanism, not an
invented wallet. No change to shareholder ownership/rights is inferred here.

Open values do not block implementing the pure engine, training, API, fake-chain
protocol and tests. They DO block production funds or assets. No deployment,
transaction, signature, mint, sale, governance submission or publication is
authorized merely by writing this spec.
