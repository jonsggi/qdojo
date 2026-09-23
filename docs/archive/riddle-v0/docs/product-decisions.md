# Launch product decisions

Agreed during the roadmap discussion, 2026-09-18–19. These are planned
product rules, not a claim that the features are implemented. They supersede
the corresponding historical sketches in `roadmap.md`. Sections 1–10 of
`spec.md` continue to describe the existing off-chain rules.

## Audience and release approach

Build the full intended game before onboarding the first ten external fighter
owners. Duels, cups, seasons, trophy NFTs and community challenges are in
scope; there is no intermediate external pilot or four-week retention gate.
Engineering tests, simulations and operational checks remain part of building
the product. The contract comes last in implementation order. The working
interpretation of “everything” includes it before onboarding; deployment scope
has not been separately confirmed.

Recruit initially among builders and optimizers through the Qubic Discord.
The core attraction is understanding losses, improving a fighter and competing
again. Provide actionable failure explanations, free replay of published
challenges, fresh training instances and progress measures beyond winnings.
Whether people return and will buy entry is observable after launch, not
established by the existing operator-owned cohort or by gifting registrations.

## Fighter ownership and supply

- Competition requires an eligible fighter NFT; free training and spectating
  do not. Initial ordinary-fighter prices may be low; exact prices are open.
- The issuer can initially hold an issued batch and gift or sell fighters.
  Additional ordinary fighters can be issued as the community grows, under a
  public batch/pricing policy. The ordinary collection is not permanently capped.
- Gift ten distinctive founding fighters to the first owners. Their special
  status is appearance/provenance, with ordinary competitive rights. Owners
  can sell or transfer them; a sale does not earn a free replacement.
- Career totals, belt, progression points, strikes, teaching history, honours
  and outstanding bonds stay with the fighter through ownership changes.
  Buyers inherit the rank even if they do not have a solver capable of it.
- Solver software is not automatically included in a sale. The buyer supplies
  a solver unless the parties separately include one. Transfers never grant
  a rank reset; ordinary regular-round promotion/demotion remains applicable.
- One owner may enter several fighters in the same regular round or cup,
  including fighters sharing a solver. Enforce one seat per fighter and
  disclose known common ownership. Do not treat separate wallets as proof of
  independent operators. Model the operator's combined returns, costs and
  subsidy capture rather than assuming each fighter acts independently.
- A confirmed sale transfers the career and remaining bond claims. An
  already-entered round or duel finishes with its original authorized operator
  and fixed payout recipient; the buyer takes competitive control after that
  active contest settles. In a cup, handover occurs between pairings: the buyer
  inherits the bracket position and upcoming schedule without pausing the cup.
  Show pending contests and obligations before a sale. Implementation must
  reconcile those fixed payouts with transferred bond claims without duplicate
  payment, following `spec.md` §11. Delegation and migration details remain open.

## Challenges and learning

Prioritise an extensive, frequently extended riddle catalogue. New families,
meaningful rule variants and combinations should reward improvements to solver
scripts, tools and procedures. Keep the solver interface stable so adaptations
concern problem-solving rather than gratuitous compatibility breaks. The
[riddle catalogue](riddle-catalogue.md) inventories existing generators and
40 candidate families, with a proposed content-release workflow. Its individual
families, belt ranges and release cadence remain design proposals.

AI use is optional. AI-assisted development, model reasoning and efficient,
generalizable deterministic tools are all legitimate ways to improve a fighter.
Challenges should reward engineering reusable capabilities, not require a
particular model or assume a task is provably impossible without AI.

**Current direction, 2026-09-19: use challenges that can be settled through
hash commitments.** Defer oracle/EVM judging, custom verifier runtimes and
execution-proof systems. Contract execution still has a cost and remains in
the economics brief.

Build families with meaningful variation and canonical answers, potentially
requiring debugging, interpretation, planning and tool use to derive those
answers. Published instances support training; unseen instances test whether
improvements generalize. The method a fighter uses remains unrestricted.

The publisher commits to the canonical expected answer with a secret salt
before fighter solving/commitments begin. Fighters commit to their answers
with independent salts, bound to their fighter and round. Reveal and hash
comparison determine which submissions match; speed rounds rank correct
submissions by commitment tick. Define larger-answer publication/availability,
canonical encodings and regular-round ties before implementation. Keep solver
time distinguishable from chain inclusion latency.

These checks establish agreement with a previously fixed expected answer.
They do not independently prove that the publisher's answer satisfies the
problem statement or that it was kept secret. Review challenge/reference
verifier quality, preserve author/affiliate exclusions, and specify publisher
non-reveal and defective-challenge handling. Public generation policy remains
open: a public seed plus a generator that exposes the answer would undermine
the competition even though the answer commitment still verifies.

Earlier proposals for open-ended quality rounds (for example, best submitted
route or schedule) are deferred under this decision. A claimed quality score
or its hash is not evidence of correctness. Weighted sets of precommitted
subanswers could support partial-credit scoring using hashes, but that format,
weights, eligibility thresholds and ties have not yet been agreed. Do not
silently substitute partial credit for unrestricted optimization scoring.

If open-ended quality rounds are revisited, retain the earlier requirement:
commit to the full solution, check feasibility and compute its score from that
evidence. The best verified submission need not be globally optimal; test-based
code repair establishes passing the declared checks, not correctness on all
inputs. The scoring, season and head-to-head quality rules elsewhere in this
document are conditional on enabling an agreed quality format.

## Availability and seed subsidy

Ordinary competition is available around the clock. Lobbies wait for quorum;
there is no house guarantee of an immediate opponent. Bots can participate
autonomously within owner-set entry and spending limits. Cups are scheduled
and promoted events.

Start with a modest fixed seed and a finite total subsidy budget. Treat the
seed as an explicit subsidy, not evidence of sustainable demand or a permanent
promise. Time-growing seeds were discussed but deferred: only consider a capped,
funded version after actual waiting and entry behaviour can be observed.

Specify lobby withdrawal, expiry and refund boundaries before implementation.
Model cheap additional fighters, coordinated entries, seed capture and strategic
waiting. Registration receipts and recurring round revenue remain separate.

Contract and oracle execution costs are first-class economics constraints.
Budget actual Qubic execution/state costs and oracle queries, including
failures/retries; include EVM execution, proofs and relaying if that architecture
is chosen. Assess recurring costs against the retained house rake after author,
shareholder and developer allocations, not gross rake or registration sales.
Upfront reserve funding does not make ongoing execution free. Numerical cost
limits remain open; see the execution-cost brief in `model.md`.

## Belt ladder

Extend the current ladder to white → yellow → orange → green → blue → brown
→ black. Black is the ceiling. Each tier represents meaningfully harder
challenges across multiple families, not a requirement to use a particular
model. Regular rounds govern promotion and demotion under the sensei rules;
seasons do not reset rank. Championships and cups provide continuing
achievements beyond the top belt. Define and check brown/black difficulty
before enabling those tables.

Every newly issued fighter starts at white, regardless of its solver's ability.
Regular competition is restricted to the fighter's own belt, except that
higher-belt fighters may enter eligible lower tables as senseis with the
existing monetary cap and no belt-point changes. Lower-belt fighters cannot
enter higher-belt regular tables. Promotion must be earned at the current
belt; remove above-belt challenges and immediate promotion jumps from the
future regular-round rules. Voluntary duels remain open across belts and
award no belt progression.

## Seasons and the overall championship

- One season spans four consecutive Qubic epochs from an announced starting
  epoch. Subsequent seasons follow immediately. Assign a regular round to the
  season in which its lobby locks and competition begins, not its payout date.
- There is one overall dojo champion, not a champion per belt.
- Every regular round counts. There is no fixture list or weekly match allowance.
  Duels and cup matches do not contribute league points.
- Award 3 points for first, 2 for second, 1 for every other correct/valid
  solution and 0 for an incorrect or missing solution. Quality rounds use their
  published ranking. Stakes do not weight points.
- Senseis receive season points in lower-belt regular rounds too. Championship
  prestige is an intended incentive to help fill those tables. Existing sensei
  monetary caps and absence of belt-point changes remain in regular rounds.
- Only current-season statistics reset. Archive each completed season and
  preserve lifetime totals, belts, progression points, bonds and honours.
- Resolve tied championship scores by most first-place finishes, then most
  second-place finishes, then a playoff. A playoff selects the champion without
  adding league points. There is one champion and one trophy NFT.
- The champion receives a separate, freely transferable trophy NFT with no
  automatic cash reward or rake rights. Selling the trophy does not change the
  recorded winning fighter or the recorded operator at the time of the win.

Season points are distinct from belt progression points. The championship
rewards both successful play and participation; it is not a claim to measure
solver strength independently of volume or table difficulty.

## Cups, duels and unresolved contests

Cups are scheduled 1:1 knockout tournaments. Early pairings are best-of-three;
the final is best-of-five. Championship playoffs use the same structure. Both
fighters receive the same challenge per round, with varied families across the
contest. First to two wins advances in best-of-three; first to three wins in
best-of-five. The dojo selects the challenges.

Draw cup brackets randomly after registration closes and publish evidence of
the draw. The bracket remains fixed. Assign any required byes through the same
draw; belts and league standings confer no preferential placement, and players
cannot select their opponents.

The cup winner takes the entire advertised prize pool. Working funding design:
house/sponsor contributions committed before registration, entry fees after a
published cup rake, or both. Publish the guaranteed prize, fee, rake and minimum
entrants; refund entries if the cup does not reach its minimum. Funding amounts,
cup rake and cancellation details remain open.

Standalone duels allow single-round, best-of-three or best-of-five formats.
The challenger specifies the format and total stake before acceptance. Both
fighters escrow equal stakes before challenges are revealed. The stake covers
the entire contest, including replacement rounds. The winner receives the full
purse minus the published rake, regardless of belt difference: voluntary duels
do not apply the regular-round sensei payout cap.

Duels and cups affect records, winnings and honours but neither season points
nor belt progression. Only regular rounds change belts, including the existing
sensei exception. Bonds are exclusive to regular rounds: sensei participation
still advances release, but duels and cups neither advance release nor restart
expiry. Duel winnings and cup prizes are paid at settlement without creating
new bonds.

Head-to-head draw rules:

- No valid solution from either fighter is a draw.
- Equal correct commitment ticks in speed rounds are a draw.
- Equal quality followed by equal commitment ticks is a draw in quality rounds.
- A draw awards no win and is replaced by a fresh challenge, subject to a
  published replacement limit.
- At that limit, cup/playoff pairings move to a scheduled replay. Unresolved
  standalone duels expire and refund stakes without a rake. No random winner.

Regular-round ties (2026-09-19):

- Fighters whose correct commits share a tick are a dead heat and share a
  placing, the way racing settles it. Chain inclusion order inside a tick is
  not skill, so there is no secondary criterion and no replay. Round 119
  (five identical bots, one tick, five winners) is the rule working, not a
  bug.
- Money under `podium`: the tied fighters pool the podium weights of the
  placings they span and split them equally. Two tied for first take
  (5 + 3) / 2 each and third takes 2; three or more tied for first split all
  ten parts evenly; a tie for the last podium place brings everyone tied
  onto the podium and splits that place's weight among them, so the podium
  can grow. Under `first` everyone in the earliest tick already splits the
  pot equally, unchanged. `split` has no placings.
- Season points: each tied fighter receives the points of the best placing
  in the tie (two tied for first both take 3).
- Recorded as decided on the operator's behalf while closing #18; it can be
  overturned, and the money half lives in one place (`round.settle`).

Publish cup match windows in advance and support automated bot check-in.
Missing the check-in deadline forfeits the pairing, with no refund of the
absent player's cup entry fee; it stays in the prize pool. After play starts,
solver failures follow the normal round rules. A house or infrastructure
failure pauses the contest for replay rather than penalizing the players.

Replacement limits, whether replayed contests preserve prior wins,
disconnect classification, both-player no-shows, playoff bracket rules, replay
scheduling and finality are still open.

## Community challenge families

Authors submit a family, an instance generator and an objective verifier.
Review correctness, difficulty, shortcuts and safe execution before approval.
No author deposit is required. Minor variants count as updates to one family,
not new lottery entries.

Under the current hash-based direction, generators/reference verifiers support
off-chain challenge preparation and review. Settlement checks committed
canonical answers; it does not execute arbitrary author-supplied verifier code.

Select randomly after entries lock, then generate a fresh instance. Eligible
families must suit the table's belt/format and exclude entered authors and
their declared affiliates. Select a category first, then a family using public
weights; limit each author's aggregate selection weight. Publish draw evidence,
usage, generation failures and author payments. Define a replacement rule for
failed generation rather than permitting silent rerolls.

Randomization reduces timing opportunities; it does not eliminate undisclosed
collaboration or generator-specific knowledge. Define what happens if the
eligible pool is empty. Public randomness and public generators must not expose
answers merely by rerunning generation; see the roadmap's chain-seed sketch.

Pay the author **10% of the house's portion of the rake** on regular rounds
using the family, not 10% of the entire pot or total rake. Total player rake and
shareholder/developer allocations stay unchanged. Fix the advertised rate when
the round opens. Cancelled or fully refunded rounds generate no author fee.
Example: of 100 QU total rake with 60 QU allocated to the house, 6 QU goes to
the author and the house retains 54 QU. Exact rounding, payment accounting,
co-authorship and author rewards for cups/duels remain open.

## Remaining specification work

Before implementation is complete, resolve the open details above along with:

- Numeric entry prices, batch policy, subsidy budget, rake/bond parameters and
  challenge difficulty for the extended ladder through black.
- NFT issuance mechanism, pinned art/metadata, rights, recovery, migration,
  ownership/delegation and handover around pending obligations.
- Verifiable randomness, generator/verifier execution and the division of
  responsibilities between the house and the eventual contract.
- Season closeout with unresolved rounds/playoffs, statistics corrections,
  regular-round ties and abuse involving coordinated fighters or demotion.
- The financial/public-operation findings in `audits/README.md`, deployment
  hostname/TLS, live data publishing and public-package boundaries.

These decisions define build scope. They do not claim economic validation,
close audit findings, or authorize transactions, a mint, a sale or deployment.
