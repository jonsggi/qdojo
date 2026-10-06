# Gameplay brainstorm — round 1: independent exploration

Date: 2026-09-24. Requested model: Opus 5.5.
CLI-reported model: claude-opus-5-5.
Method: `claude -p`, high effort, tools disabled, isolated working directory.
Status: exploratory discussion, not an adopted change to the combat specification.
External claims inside the model's answer are unverified discussion material.

## Prompt from Codex

We are having a multi-round design debate about qdojo. I am the other design participant, acting for the owner. This is ROUND 1: independent exploration, not endorsement of an existing spec.

Owner's request: discuss with Opus 5.5 via claude -p, do several brainstorming rounds to find genuinely engaging gameplay suited to smart contracts and fighter NFTs. Do not use tools, edit files, access accounts, or take any action; return design analysis only.

CONTEXT:
- No external product release yet. Existing code was a riddle-solving competition, now archived as the future direction changed. Current committed design is only a candidate, not a launched contract.
- Audience: builders/optimizers who own a fighter, run their own bot, study opponents, improve code/prompts/policies and compete. AI optional. Spectators should understand why somebody won and want to watch.
- Qubic target: small bounded deterministic integer engine can settle moves and funds on-chain. Planning/training happens off-chain. Commit/reveal hides each side's choice until fixed; multiple dependent chain windows can cost time. Do not assume exact tick duration, zero execution cost, secure private contract state, unbiasable blockchain RNG or that blockchain/NFTs automatically add fun.
- Fighter NFT gives persistent identity, appearance, transferable ownership, record/rating/rivalries. All have equal competitive access; no purchased stat advantages. A trophy can represent an earned result. Ownership does not automatically transfer the bot's source code. Free practice needs no NFT/wallet; paid matches can require registration. House/NPC affiliation disclosed. Multiple fighters can share an owner.
- User liked at most three connected planning rounds, fast matches (rough target 45-60s after matching, not proven), public action histories to study, automatic funded matchmaking, voluntary duels, tournaments, and actual NPCs including a random beginner bot. These are design preferences, not instructions to preserve every provisional rule regardless of fun.
- Current candidate: 3 rounds x 6 simultaneous action beats. HP 100, stamina 60, state carries. JAB, KICK, BLOCK, DUCK, THROW, RECOVER, guard fatigue, short-lived counter-opening and one optional power strike per fight. Deterministic action matchup matrix, simultaneous hits/KO, signed commit/reveal. No position. Balance unproven; smoke samples of fixed NPCs were very one-sided; no advanced-policy campaign yet.
- Alternative I raised: a small grid capture-the-core arena with move/dash/strike/guard/recover, central pickup carried home, interception, public map and concealed plans. Also unproven. Do not anchor on my suggestion.
- Main uncertainty: fun may be limited to policy tuning; stationary payoff tables could collapse to a few robust mixtures; long blind scripts can feel arbitrary; grid navigation can become trivial routing; NFTs can be irrelevant decoration. Need strong honest criticism.

TASK:
Propose 5-7 meaningfully different core games suited to this setting, not just extra moves for the same game. For each: exact player/bot decision and what is observed; 20-second spectator story; source of tactical/engineering depth and surprising but explainable outcomes; why someone returns to improve; what the NFT legitimately contributes; on-chain resolution/latency fit; likely dominant strategy or failure mode. Then choose your top TWO and explain why you reject the others. Explicitly separate creative judgement from evidence. You may recommend abandoning both existing candidates. Be concrete, concise enough for debate (about 1600-2200 words maximum), and skeptical of manufactured scarcity, random win buttons, mandatory LLM calls, permanent stat grind, or feature accumulation. No need to flatter the proposal.

## Opus response

# Round 1: independent exploration of qdojo core games

I'm treating the owner's constraints (a small bounded integer engine, commit/reveal windows, at most 3 planning rounds, bots as the players, and NFTs as identity only) as the design space. I'm not treating either existing candidate as a baseline.

**The main design choice is what each player commits in a window. The action set matters less.** There are three options:

- **(a) One action per window.** This gives pure simultaneous-move payoff tables, and every window costs latency.
- **(b) A blind sequence of actions.** This is the current candidate's 6-beat scripts. Outcomes can feel arbitrary, because nobody can react inside the sequence.
- **(c) A small conditional policy.** The engine executes it tick by tick against the opponent's policy, reacting to observed state.

For an audience of bot builders, (c) is the most natural fit. It is also the riskiest, because it depends entirely on a good rule language. Several games below are organized around that choice.

---

## 1. Reflex Duel: conditional-policy footsies on a 1D line

**Decision and observation.** Each round, a fighter commits a prioritized list of up to about 12 rules. A rule has the form "if [condition] then [action]." Conditions can test:
- distance (0–6),
- the opponent's last action,
- own and opponent HP and stamina buckets,
- the tick index,
- whether the opponent just whiffed (attacked and missed).

Actions are: step in, step back, jab (range 1), kick (range 2, slow recovery), throw (range 0, beats guard), guard, rest.

The engine runs 8 ticks per round. Both fighters' first matching rules fire at the same time. After each round, both policies are revealed. The off-chain bot sees the full trace and every earlier policy, then writes the next one. There are 3 rounds.

**Spectator story (20 seconds).** The replay highlights which rule fired on each tick. For example: "In round 1, Blue kicked from max range. In round 2, Red added rule 2: *if Blue kicked last tick, step in and throw.* In round 3, Blue baited it with a feint step-back, then used a range-2 kick that Red's rule walked straight into." Every outcome traces to a readable line.

**Where the depth comes from.**
- Spacing and whiff-punishing are the proven core of real fighting games.
- Conditional rules create conditioning, bait, and counter-bait inside a round, without any extra chain windows.
- The engine is deterministic, so builders can run it locally as an exact simulator. That enables search over policies, self-play, and fitting an opponent model to their public history.
- Surprises come from two rule sets interacting, not from dice.

**Why players return.** You lost to a specific rule. You can read it, beat it offline, and requeue. The off-chain bot decides which policy to submit, given the opponent's history. That selector is private work, even though each submitted policy becomes public.

**What the NFT contributes.** Identity and appearance, a full match archive (the fighter's scouting file), named "signature rules" the community can refer to, rivalry records, and trophies. It adds nothing to stats.

**On-chain fit.** Cost is roughly 12 rules × 8 ticks × 2 fighters × 3 rounds, about 600 cheap predicate evaluations. A policy encodes in about 60 bytes. The match needs 6 chain windows (commit and reveal per round) plus settlement. There is no randomness.

**Likely failure modes.**
- **Rule language too weak:** play collapses to 2–3 archetypes.
- **Rule language too strong:** policies become unreadable and spectators lose the thread.
- **Stalling at max range:** needs an anti-stall rule such as a shrinking line or edge damage.
- **Fast meta convergence:** submitted policies are public, so the meta will settle quickly. That's acceptable if counters exist, and fatal if one robust generalist beats everything.
- **Round 1 is a blind guess.** It's symmetric, so tolerable.

---

## 2. Finite Arsenal: depletion duel

**Decision and observation.** Each fighter starts with the same visible set of 10 technique tokens:
- 3 jab, 2 kick, 2 throw, 2 guard, 1 finisher.

Each round, both commit an ordered sequence: 4 tokens in round 1, 3 in round 2, and the remaining 3 in round 3. In round 3 the set is forced, so only the order is chosen. A small matrix resolves each beat. Used tokens are revealed and gone, so both sides always know exactly what the other has left.

**Spectator story.** A remaining-inventory display carries the whole story: "Red spent both throws early. Blue knew Red had no answer to guard, so Blue turtled and landed the finisher on beat 9." Anyone who has played cards understands it.

**Where the depth comes from.**
- Counting and tempo.
- Backward induction as inventories shrink, which makes the endgame a legible puzzle.
- Deciding when to burn a scarce token.

Blind sequences are less arbitrary here than in the current candidate, because the visible constraint narrows the plausible orders. For builders, the engineering task resembles poker bots: solve or approximate the equilibrium (for example with counterfactual regret minimization), then deviate to exploit specific opponents.

**Why players return.** It's legible, fast to learn, and has a real solving problem underneath.

**What the NFT contributes.** The same as game 1. Possibly also a cosmetic token skin. Loadouts are never owned or purchased.

**On-chain fit.** Excellent. The state is tiny, it needs 6 windows, and there is no randomness.

**Likely failure mode: it is small enough to solve.** Small variants of Goofspiel, the closest known relative, have been solved computationally. If this one is solvable, top bots converge to near-equilibrium mixed play, and matches between them become expensive coinflips. The depth is also bounded: once solved, it's done. It may work better as an on-ramp and free practice mode than as the paid core.

---

## 3. Fronts: allocation with memory, a Blotto variant

**Decision and observation.** Each round, a fighter splits 20 effort points across head, body, and legs, for both attack and defense. Winning a zone carries forward as a lasting effect: legs damage slows you, body damage lowers your effort budget.

**Spectator story.** Bar charts clash: "Red stacked legs twice and crippled Blue's budget."

**Where the depth comes from.** Allocation interacts with persistent consequences.

**What the NFT contributes.** Identity only.

**On-chain fit.** Trivial.

**Likely failure mode.** Blotto games have no pure equilibrium, and good play is heavily randomized. Spectators see near-random splits winning or losing by 1–2 points. It reads as a coinflip even when it isn't.

**Verdict: reject.**

---

## 4. Siege: asymmetric hidden traps, roles swap

**Decision and observation.** The map is a small public graph of rooms and doors. The defender commits trap placements (hidden). The attacker commits a route and timing. They swap roles after each round, and total score across rounds decides the match. Revealed traps from earlier rounds build a record of each player's habits.

**Spectator story.** "He walked through the same door she trapped last time. She'd moved the trap."

**Where the depth comes from.** Reading habits from history, and map design.

**What the NFT contributes.** Identity only.

**On-chain fit.** Good, as long as path validation stays bounded.

**Likely failure mode.** Each round is essentially a hide-and-seek matrix game: graph Blotto with a costume. It depends heavily on map design, and outcomes read as "guessed right or wrong."

**Verdict: reject as the core. Maybe useful as a later event mode.**

---

## 5. Core Run: the grid capture-the-core proposal

**Decision and observation.** Blind multi-step move plans on a public grid: grab the central pickup, carry it home, intercept the opponent.

**Where the depth comes from.** Interception and collision timing.

**Likely failure modes.**
- **Trivial routing.** Shortest paths are computable, so play reduces to contesting the center and then a race.
- **Blind scripts on a grid make it worse.** Most collisions become guesses about timing.
- **Spectator overload.** Two plans on a grid are harder to follow than one line.

Movement only gets interesting if plans are reactive, which turns this back into game 1 with more geometry to render.

**Verdict: reject as the core.** If game 1's rule language works, a 2D arena can be a later extension of it.

---

## 6. Brawl Arena: N-player program free-for-all

**Decision and observation.** 4–8 bots in one arena, each submitting a policy.

**Spectator story.** The richest of all six. Chaos plus emergent alliances.

**Likely failure modes.** Fatal for paid matches:
- The owner allows multiple fighters per owner, which enables sybil collusion.
- Kingmaking.
- Balancing is much harder than head-to-head.

**Verdict: reject for funded play.** It might work as an unpaid showcase.

---

## 7. The current candidate as it stands

The 3×6 blind-beat design with a stationary matrix, no position, and one-off power strikes falls into both traps:
- Stationary payoff tables solve down to a few robust mixtures.
- Blind 6-beat scripts make individual hits feel arbitrary.

Stamina and guard fatigue add state, but no spatial or reactive dimension for skill to grow into.

---

## My top two, and why

**1. Reflex Duel (primary).** It is the only candidate where the bot builder's craft shows up directly in the game:
- local simulation,
- policy search,
- opponent modeling from public traces,
- readable rule-level explanations of every hit.

It keeps the fighter fiction and the 3-round structure. It fixes the blind-script problem without adding chain windows, because reaction happens inside the engine. It also answers the worry that "fun is only policy tuning": policy tuning is the game, and it's a legible one.

**2. Finite Arsenal (secondary: the low-risk counterweight).** It's cheap to build, instantly readable, and its solving task is honest. I would use it as:
- the free practice and beginner mode,
- a fallback if the rule language for game 1 can't be made balanced and readable.

It may also borrow depletion as a mechanic: game 1 could use finite special techniques instead of a single power strike.

**Recommendation.** Abandon both existing candidates as the paid core:
- Keep the fighter fiction, HP/stamina carry-over, signed commit/reveal, and deterministic integer resolution from the current design.
- Replace the blind beats with conditional policies on a 1D range line.

**Why I reject the others:**
- **Fronts and Siege:** their skill looks like luck from outside, which kills spectating.
- **Core Run:** its depth depends on reactive plans it doesn't have.
- **Brawl Arena:** collusion makes paid play unsafe.

---

## Judgement versus evidence

**Evidence (thin):**

| Claim | Basis |
|---|---|
| Finite two-player zero-sum games have mixed-strategy equilibria. Blotto has no pure one. | Mathematical fact. |
| Small Goofspiel-like games are solvable. | Known computational result. |
| Program-vs-program communities (Robocode, Core War, Screeps, Battlecode) sustain long engagement. | Historical. Shows the audience exists, not that this game works. |
| Each commit/reveal round costs at least two dependent windows. | Protocol fact. |
| One-sided smoke tests between fixed NPCs. | Near-zero information about balance: fixed scripts are expected to be lopsided. |

**Creative judgement (unproven):**
- Reflex Duel is fun and readable.
- A rule language of about 12 rules hits the right expressiveness.
- The 45–60 second target is achievable with 6 windows.
- Spectators follow the "fired rule" overlay.
- Depletion keeps sequences from feeling arbitrary.

---

## Cheap falsification before any chain work

1. **Build both engines offline.**
2. **Run a policy-population experiment for Reflex Duel.** Evolve or search policies and measure whether any single policy beats more than about 70% of the population. If one does, the rule language collapses, so redesign it. Also check whether counter-policies exist for each top policy.
3. **Solve or approximate the equilibrium for Finite Arsenal.** Measure how much a near-equilibrium bot gains against hand-written bots. If there's no exploitable edge and matches between experts are about 50/50, it stays the free mode.
4. **Show 10 replays to people who haven't seen the game.** Ask them "why did Red win?" If they can't answer, the game fails the spectator test whatever its depth.

---

## Other cross-cutting risks

**NFT transfer.** A transferred fighter carries a record earned by a different owner and bot. Show ratings and records "since last transfer," or the rating misrepresents who is playing.

**Non-reveal griefing.** A player can refuse to reveal after seeing the other side's commit. This needs bonded forfeits and a timeout rule in every design above.

**The NFT's real role.** It adds no gameplay. Its legitimate value is provenance: a permanent, public, scoutable career. If that isn't enough to justify it for a given feature, don't build that feature.
