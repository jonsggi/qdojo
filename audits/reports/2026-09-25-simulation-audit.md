# QDOJO combat simulation audit — live demo arena, 2026-09-25

**Scope:** the live `qdojo-combat-live.service` demo arena, running from `~/src/qdojo-live` at commit `caeac8b`.
Its combat code is identical to the main checkout. The profile is `demo`, with 1.5 s ticks and 19 fighters.

**Method:** the audit was read-only. I copied `~/.qdojo/combat/arena`, the export and the lineup to a scratchpad.
I replayed the 160,382-record journal (86 MB) offline into a full contract at **tick 83,619**, about 34.8 h of play.
The replay took 107–135 s, and conservation and `invariants.check` both passed.
Everything below comes from that replay, the bots' private plan journals, `journalctl`, the public export and a few offline `qdojo combat evaluate` runs.
I did not signal, restart or write to the live service.

**Supporting files** (in [`2026-09-25-simulation/`](2026-09-25-simulation/)):
- `fighters.csv`: per-fighter record, forfeits and rating.
- `fights.csv`: one row per fight (4,098 rows).
- `scripts/`: the analysis scripts. Run them with `uv run python audits/reports/2026-09-25-simulation/scripts/<x>.py <scratch-dir>` after `replay.py`.

> **Status (2026-09-26):** recommendations 1–4 are fixed and deployed; the
> tracked issues are [AUD-011 to AUD-028](../README.md#combat-review-2026-09-25).
> Numbers below describe the arena **before** those fixes.

---

## Executive summary

| # | Question | Verdict |
|---|---|---|
| 1 | Does it work? | **The contract and live loop work.** There are no stuck fights on-chain, invariants hold, and it keeps real time (tick drift about 40 s in 34 h). **The "stuck" fights are an exporter caching bug:** 162 of the 200 published fight files are frozen at their last in-progress snapshot. Two bot-side bugs distort everything else: (a) LLM planners reuse a spent power strike, so their reveal is rejected and they forfeit (166 forfeit losses plus 5 double faults); (b) history-based policies never receive history live, so 4 "reader"/"repeat" fighters play mixed-v1. |
| 2 | Economics | **Conservation holds, but the house loses heavily and skill is barely rewarded.** Simulated execution fees burned 1.06 M QU against 361 k QU of total rake (216 k to the house), plus 140 k in cup sponsorship. An average honest bot loses about 50–100 QU per 1,000-QU fight. The profits go to three exploit patterns: a fixed counter-script farming cups (**oni, +413 k, 25 of 27 cups**), a scout bot farming auto-accepted duels (**tengu, +241 k, 138–5 in series**), and the top two ranked bots. |
| 3 | Balance and depth | **Mechanically sound but shallow in practice.** KICK is the best action in this population (net +7.5 HP per beat). DUCK (−4.8) and THROW (−0.1) are near-useless. Power and opening add only about 5% of damage. The fighters form a clear rock-paper-scissors cycle. Because half the field is effectively mixed-v1, a single fixed six-action script (oni) beats almost everyone. The LLMs are mid-pack (0.48–0.63 combat score) at about $0.002 per win. |
| 4 | Is it fun? | **Not yet, for spectators.** A ranked fight takes 123 s (target: median 60 s, p95 90 s). Each round is 42 s of waiting for 6 beats that land at once, and 80% of fights never show their ending on the site. There is real drama underneath: 26% of fights are won by the fighter trailing after round 1, 6% by overcoming a deficit of 30 HP or more, and 148 decisions came down to 4 HP or less. Cups are monotonous (oni wins every time). |
| 5 | Top recommendations | (1) Fix the exporter write-once bug. (2) Validate plans against state before commit (the power bug). (3) Pass `prior` rounds into `policy_chooser`. (4) Back off on cooldown instead of re-queuing every tick. (5) Shorten demo timing and publish a per-beat live view. |

---

## 1. What works and what doesn't

### 1.1 The "deadline passed, awaiting advance" fights: root cause

**The contract is not stuck. The public export is stale.**

At tick 83,619 the replayed contract has only **3 non-DONE fights** (#4096–#4098), all within their deadlines, with `fights_in_use` at 3 of 16.
Fight **#3900** actually ended at **tick 79,350 by KO, winner A**, after three rounds resolved at ticks 79,295, 79,322 and 79,350.
Its published file `fights/3900.json` carries `generated_tick 79347`, `phase REVEAL`, `round_index 2`, `reveal_last 79358` and `result null`.
That is the last export taken while it was live, and it never changed afterwards.

The cause is in `packages/qdojo/src/qdojo/combat/export.py`, `export_all`:

```python
# A finished fight never changes again: write it once, ...
final = fight.phase == "DONE" and c.contests[fight.contest_id].status == "DONE"
if final and (root / f"fights/{fid}.json").exists():
    continue
```

The check tests whether a file exists, not whether the file was written in its final state.
The arena exports every 6 ticks and a fight lasts about 82 ticks, so almost every fight is written while live.
When it finishes, its file already exists and is never rewritten. `fights/<id>/replay.json` is skipped in the same way, so it lacks the final round, the result and the settlement.

**Measured on the copied export (200 fight files):**

| Mode | Stale summary and replay | Correct |
|---|---:|---:|
| ranked | **140** | 2 (the 2 live fights) |
| duel | 15 | 23 |
| cup | 7 | 13 |
| **total** | **162** | 38 |

The only duel and cup fights that come out correct are those that finished while their series was still running, because `final` was still false then.
The last fight of every series is stale.

The public site shows the same thing: `https://qdojo.jonsggi.com/data/combat/v1/fights/4000.json` still says `REVEAL`, round 2, `generated_tick 81687`, while the site's manifest is at tick 84,165.

**Consequences:**
- The site's `phaseBadge` (`apps/web/combat/app.js:325`) renders these as "DEADLINE PASSED, AWAITING ADVANCE".
- `latestDone()` filters on `phase === 'DONE'`, so recent results come almost only from mid-series duel and cup fights.
- Replays of about 80% of fights stop before the finish.
- The e2e suite hides the bug: `apps/web/tests/e2e/run.cjs:197` accepts `/TICKS? LEFT|DEADLINE PASSED/` as a pass.

**Ruled out:**
- **Settlement backlog:** zero fights are past a deadline in the contract.
- **The processing cap:** `end_tick` handles at most 16 non-DONE fights, and there are never more than about 4.
- **Chain halts:** there are no `begin` or skip records, `generation` is 1 and `halted_ticks` is 0.
- **Crashed bots:** the log has no `bot … error` lines.
- **LLM timeouts:** the fallback rate is 0.3–4% (§3.6).

**Fix:** rewrite a fight file until it has been written in final form. For example, keep an in-memory or persisted set of fight ids already exported as final, or read the existing file's `phase`/`result`. Also tighten the e2e test so an overdue live fight fails it.

### 1.2 Liveness and health of the loop

| Check | Result |
|---|---|
| Real time | Tick 81,000 logged at 20:25:58 against 20:25:19 predicted from the start at 10:40:42. That is about 40 s of drift in 34 h; the loop keeps pace. |
| Restarts | One, at tick 15 (2026-09-24 10:40:41). None since. |
| Service gaps or voids | None: `generation 1`, no `begin` records, `halted_ticks 0`. The reserve was topped up six times (1.2 M funded; 137 k left). |
| Invariants | `invariants.check(world)` returns `[]`. `check_conservation()` passes: 54 T minted equals 54 T held. |
| Log errors | None. There are 355 journal lines since 09-24, all cup, duel and sale notices, and zero `error` lines. **The log records no bot-level rejections at all**, so the bugs in §1.3 are invisible to the operator. |
| Journal growth | 86 MB and 160 k records in 34.8 h (about 2.5 MB/h). A restart replays the whole journal: about 110–135 s now, growing linearly. That is about 9 min after one week. |
| Export cost | A warm `export_all` on the live-size state takes 0.41 s every 6 ticks (9 s), about 4.5% CPU. `fighter()` scans every historic fight for each of the 19 fighters, so the cost grows with history. |
| State growth | `c.fights` (4,098), `contests` (3,477) and `offers` (7,235) are never pruned. `end_tick` scans every fight each tick (about 0.5 ms now). model.md §4 says "Empty ticks must not scan historic fights". |

### 1.3 Forfeits and timeouts per fighter

There were 4,095 finished fights: 3,043 ranked, 653 duel and 399 cup.
Of these, **240 were forfeits or double faults: 220 ranked (187 at reveal, 28 at commit, 5 double faults) and 20 cup forfeits at reveal** (full table in `fighters.csv`).

| Fighter | Driver | Fights | Forfeit losses | % | Stage | Cause (verified from the bot's `secret-plans.jsonl`) |
|---|---|---:|---:|---:|---|---|
| ronin | mixed-v1, reliability 0.06 | 85 | 69 | **81%** | 41 reveal, 28 commit | By design: it acts on 6% of ticks. |
| QWEN-235 | llm qwen3-235b | 182 | 104 (+5 double faults) | **57%** | all reveal | **All 109:** the plan sets `power_slot` after power was already spent, so the reveal is rejected with `BAD_PLAN` and the bot forfeits. |
| GEM-LITE | llm gemini-2.5-flash-lite | 558 | 62 | 11% | all reveal | **All 62:** the same power-reuse bug. |
| KEN.EXE | llm gemini-3.1-flash-lite | 440 | 0 | 0% | — | — |
| All scripted bots | — | — | 0 | 0% | — | — |

**The LLM forfeit bug** (examples: fight #22 round 3 for QWEN, #10 round 3 for GEM-LITE):
- The planner (`llm_planner.py`) calls `planner.parse_plan`, which checks syntax only.
- `Bot._fight_step` commits whatever the chooser returns.
- The contract then rejects the reveal in `validate_plan` ("power strike already spent this fight").
- The bot also re-sends the rejected reveal until the deadline: QWEN made 709 reveal sends for 367 commits.

**Fix:** in `Bot._fight_step`, before persisting the plan, run `engine.validate_plan(rules, my_state, plan)`. On failure, drop the power slot, or fall back to a legal plan. The same guard belongs in `llm_planner` after parsing.
It costs one function call and would have saved QWEN and GEM-LITE 166 lost stakes (about 166 k QU, plus 5 double faults) and their ratings.

**Cooldown spam.** After each fault a fighter gets a 240-tick cooldown, and after 3 faults in an epoch a ranked suspension.
The live `Budget` sets `stop_after_faults=10**6`, which disables the bot's one-fault stop.
The bot does not read `cooldown_until`, so it sends `QUEUE_ENTER` every tick and each one is rejected:

| Owner | QUEUE_ENTER calls | Offers accepted |
|---|---:|---:|
| QWEN-235 | **16,688** | 182 |
| GEM-LITE | 6,640 | 567 |
| Whole arena | 31,233 | 6,695 |

That is about 24.5 k wasted calls, **about 245 k QU (23%) of all simulated execution fees**.
This is the combat-bot sibling of **AUD-005** (fail closed): here the bot is fail-safe on money but fail-noisy on calls, and the demo overrides the safe default.

### 1.4 Cups, duels, market

**Cups work mechanically.**
- 27 complete and 1 running; none cancelled, aborted or postponed.
- There were 191 pairings, all DONE, with 4–8 entrants each.
- A cup takes about 2,990 ticks (**about 75 min**) from creation to its final.

But **oni won 25 of 27** and EVO-GEM won 2. oni spends almost its whole life in cups: 34 ranked fights, with a median gap of 1,105 ticks between contests.
The strongest ranked fighters (kappa, EVO-DS) are not cup-enabled in the lineup, so the cup field is mostly weak mixed-v1 clones.

**Duels work mechanically.**
- 270 duel contests: 65 SINGLE, 137 BO3, 68 BO5.
- Stakes of 1k, 2k or 3k.
- Every challenge was accepted, because the arena picks two idle duel bots and bots auto-accept anything in budget. No duel expired.
- 7 series ended drawn.

But the duel roster is fixed at 4 bots, and **tengu (scout-v1) won 138 series and lost 5**, against baku (effectively mixed-v1), EVO-DS2 (mixed-v1) and EVO-GEM2 (kicker-v1).
Duels here are a transfer from three bots to one.

**The market is a simulated ownership change, not a market.**
- `Arena._maybe_market` mints 10^12 QU for a new collector identity and transfers the asset.
- **No price is paid** and nothing goes to the seller.
- There were 34 sales: tengu 17×, baku 11×, ronin 5×, kappa 1×. Founding fighters are excluded by design.
- Rating, record and faults travel with the fighter, as specified. The bot is re-created with a fresh budget state directory (ronin has 6).
- **There are no market prices to evaluate.** The "market" row of the economics question cannot be answered until sales carry a price.

### 1.5 Rating drift and belts

Ratings are zero-sum. The 15 ranked-active fighters sum to exactly 15,000.

**Lifetime rating snapshots** (the spread keeps widening; not converged):

| Fighter | 10k | 30k | 50k | 70k | 83.6k | Belt |
|---|---:|---:|---:|---:|---:|---|
| kappa (search) | 1227 | 1308 | 1430 | 1510 | **1605** | blue |
| EVO-DS (search) | 1257 | 1468 | 1481 | 1565 | 1554 | blue |
| oni (script) | 1327 | 1342 | 1342 | 1356 | 1356 | green (34 fights) |
| RYUBOT (scout) | 1062 | 1161 | 1294 | 1266 | 1348 | green |
| EVO-GEM (script) | 1016 | 1211 | 1280 | 1325 | 1319 | green |
| KEN.EXE (LLM) | 1064 | 1184 | 1210 | 1283 | 1248 | orange |
| kirin (jabber) | 1055 | 1036 | 1080 | 1115 | 1117 | orange |
| raiju (kicker) | 888 | 897 | 895 | 889 | 933 | yellow |
| EVO-DS3, kitsune, PI-AGENT, tanuki (effectively mixed) | ~870–935 | ~745–905 | ~760–890 | ~730–830 | **741–832** | white |
| GEM-LITE (LLM) | 796 | 880 | 747 | 710 | 621 | white |
| QWEN-235 (LLM) | 891 | 660 | 576 | 558 | 505 | white (26 fights placed) |
| ronin (flaky) | 782 | 550 | 421 | 351 | **305** | provisional white (3 combat fights; forfeits drain rating) |

The spread grew from 545 to 1,300 points.
No fighter reached brown or black.
**11 of 19 fighters display white**: 6 placed white plus 5 still provisional (ronin and the 4 duel-only bots stuck at 1000).
White therefore conflates "new" with "bad".

**Matchmaking isolates the top.**
- The ranked pair `EVO-DS`–`kappa` met **210 times**, exactly the demo cap of 6 per epoch × 35 epochs.
- Median queue wait is 32 ticks (48 s), p90 is 88 ticks, max 238.
- 597 of 6,695 offers expired.

**Seasons are 9,600 ticks (4 h).** Season ratings stay within about ±100 of 1000, so the champion is noisy:
- S6 went to KEN.EXE, S7 to **PI-AGENT (a mixed-v1 clone at 754 lifetime)**, and S8 to raiju.
- In S7, kappa and EVO-DS led the standings but **failed the four-distinct-opponents rule**, because the rating window lets them fight only each other.
- The qualification rules therefore exclude exactly the best fighters.

### 1.6 Other anomalies

- **The site misdescribes drivers.** Fighter files say `driver: reader-v1`, `repeat-last-winner` and `search-v1`, but live they run mixed-v1, mixed-v1 and search-blind respectively (§3.1).
- **LLM spend history is overwritten.** `llm_planner.Spend` keeps only the current UTC day in `spend.json`, so yesterday's spend is lost. Keep a per-day history.
- **Planner stderr is discarded.** The fallback reason and per-call cost never reach a log.

---

## 2. Economics

### 2.1 Money flows over 34.8 h (fake QU)

| Flow | QU | Per hour |
|---|---:|---:|
| Total rake (500 bps) | 361,100 | 10,364 |
| House share (60%) | 216,660 | 6,218 |
| Dev share (10%) | 36,110 | — |
| Shareholder pool (30%) | 108,330 | — |
| Cup sponsorship paid by the house (28 × 5,000) | 140,000 | 4,023 |
| **Simulated execution fees burned** | **1,062,798** | **30,504** |
| Operator reserve top-ups | 1,200,000 | — |

**House operating net** = 216,660 − 1,062,798 − 140,000 ≈ **−986 k QU**. That is −28 k per hour, and the house takes in about **1/5 of what it burns**.

**Fee breakdown** (`FeeModel` per_call 10, per_tick 1, per_resolved_round 20):
- calls: 76,656 × 10 = 767 k;
- ticks: 84 k;
- resolved rounds: 10,681 × 20 = 214 k.

**Per 1,000-QU ranked fight:**
- about 13 calls (2 entries plus 4 per round × 2.7 rounds), about 2.7 rounds, and about 82 ticks shared with about 3 other fights;
- execution cost ≈ **180–200 QU**;
- rake **100** (house 60).

**At the 1,000-QU tier every fight is subsidised by about 120–140 QU of house money.** The fee model is a candidate, not a measured Core cost. The structure still matters:
- per-call fees scale with protocol chatter, and rake scales with stake;
- the 1,000 tier cannot pay for itself unless calls cost about 5 QU or less, or rake is at least 10%;
- 23% of calls are the rejected-entry spam from §1.3.

economics-report.md explicitly excluded execution fees. This run is the first measurement of them, and it is negative for the house.

### 2.2 Who gains and who loses

Net QU per fighter over all modes (the sum of player nets equals −rake + sponsorship − in-flight escrow, which is correct):

| Fighter | Ranked n | Ranked net | Per ranked fight | Duel net | Cup net | **Total** |
|---|---:|---:|---:|---:|---:|---:|
| oni (script-vs-mixed) | 34 | +25,100 | +738 | — | +388,300 | **+413,400** |
| tengu (scout, duel-only) | — | — | — | +241,100 | — | **+241,100** |
| EVO-DS (search) | 323 | +52,100 | +161 | — | — | +52,100 |
| kappa (search) | 356 | +40,400 | +114 | — | — | +40,400 |
| EVO-GEM, kirin, raiju, KEN.EXE, RYUBOT | 171–716 | −21k…+6.5k | −30…+31 | — | −46k…+38k | −47.5k…−2.2k |
| EVO-DS3, kitsune, tanuki, PI-AGENT (mixed-v1 level) | 607–763 | −44k…−60k | **−69 … −97** | — | −42k…−48k | −60k…−107k |
| GEM-LITE, QWEN-235 (LLM with the forfeit bug) | 154–559 | −40k…−75k | −134 / −264 | — | 0 / −40k | −75k / −81k |
| ronin (flaky) | 85 | −62,900 | **−740** | — | — | −62,900 |
| EVO-DS2, EVO-GEM2, baku (duel victims) | — | — | — | −50k…−141k | — | −50k…−141k |

**Is it sustainable?**
- For players as a whole it behaves as the model says: they lose exactly the rake, and skill moves QU from weak to strong.
- It is **not sustainable for the house** at this fee model (§2.1).
- It is **not attractive for an honest player**: 12 of 19 fighters are net negative, and all the large gains come from structural farming, not ranked skill.

### 2.3 Honest player expected value

A newcomer of average skill in this pool is roughly mixed-v1 level. Such a bot:
- plays about 22 ranked fights per hour (for example, EVO-DS3 played 763 in 34.8 h);
- loses about **70–100 QU per 1,000-QU fight**, which is 5 QU of pure rake plus a skill deficit against the scripted and search fighters;
- therefore loses about **−1.5 k to −2.2 k QU per hour**.

A bot that plays at exactly 0.5 loses 50 QU per fight (half the purse rake), about −1.1 k per hour.
Only a bot at the search-v1 level (about 0.6 score) nets positive: +114 to +161 per fight, which is 11–16% of stake.

This matches economics-report.md in sign: the stronger bot is positive and the weaker negative at 500 bps.
The magnitudes are about 2–3× smaller than the report's reader-vs-mixed (+363 / −460) because the live pool is more even.

### 2.4 Exploitability

| Vector | Evidence here | Severity |
|---|---|---|
| **Cup farming with a fixed counter-script** | oni's one fixed plan (`script-vs-mixed-v1`, 64% KICK) won 25/27 cups, **+388 k net**, including 125 k of house sponsorship. It works because most of the cup field is effectively mixed-v1. | High in the demo. In production it is limited by who enters, but sponsorship is a direct house-to-bot transfer. |
| **Duel farming weak auto-accepters** | tengu 138–5 in series, +241 k. Named duels have no rating gate by design (competition.md §4), and demo bots accept any in-budget challenge. | High for naive bots. Real owners must be able to set accept filters (max rating gap, min score history). The bot has no such setting. |
| **Rating isolation and season qualification** | The top pair fought each other 210 times, then failed the distinct-opponent rule; S7 went to a 754-rated fighter. | Medium: season titles are noisy and gameable by skipping. |
| **Sybil or collusion** | Demo loosens pair caps to 6 per epoch and a 60-tick rematch gap. Two same-operator fighters with distinct owner identities could trade about 6 draws per epoch. Draws are not raked, so rating or qualification can be moved for free. | Medium. Known and documented (economics-report, competition.md §3); unchanged here. |
| **Stalling to force timeouts** | No profitable stall exists. A missing commit or reveal forfeits the whole contest and stake to the opponent. The only abuse is being matched against a flaky bot, which the FIFO book does not let you choose. ronin donated 69 stakes to whoever it drew. | Low. |
| **Invalid-reveal abort** | The last revealer sees the first revealer's plan, but cannot change its own. Refusing to reveal forfeits the stake, so there is no free option. | None found. |
| **Cooldown retry spam** | Not a player exploit, but in production each rejected call costs the caller, which should stop it. In the demo it costs the house 245 k. | Low for players; high cost in the demo. |

---

## 3. Balance and strategic depth

Data: 3,855 COMBAT fights and 110,008 executed fighter-beats.

### 3.1 Two live-only policy bugs distort the meta

**History is never passed.** `bot.policy_chooser` builds `npcs.Observation(round, self, opp, history, slot)` but **never sets `prior`**. Policies that read `obs.prior` therefore behave as if it were round 0 every round:

- **reader-v1** (tanuki, PI-AGENT) returns `mixed_v1` whenever `prior` is empty. Its live action mix (JAB 25, KICK 16, BLOCK 17, DUCK 16, THROW 8, RECOVER 17) is identical to kitsune's mixed-v1.
- **repeat-last-winner** (EVO-DS3, baku) repeated a previous-round plan in **0 of 1,433** and **0 of 580** rounds. By design it should always repeat.
- **search-v1** (kappa, EVO-DS) silently runs as **search-blind**.
- scout-v1 uses `opponent_history`, which is populated, so it works. raiju repeats 1,167 of 1,167, as a fixed script should.

**Offline counterfactual** (`qdojo combat evaluate`, 60 paired seeds, suite `audit-20260925`):

| Policy vs oni's script (`script-vs-mixed-v1`) | Offline, with history | Live, without history |
|---|---:|---:|
| reader-v1 | **0.646** (67/21/32) | 0.07 (as mixed-v1*) |
| mixed-v1 | 0.029 | 0.00–0.07 |
| scout-v1 | 0.142 | 0.21 |
| search-blind | 0.250 | 0.09 |
| search-v1 (with history, 40 seeds) | **0.475** (33/10/37) | 0.09 (as search-blind) |

Also offline: reader-v1 scores **1.000** against kicker-v1, while live the history-less clones score **0.33** against it.
**oni's dominance, the cup farming and the duel farming are all downstream of this one missing field.**

### 3.2 Action frequencies and value

| Action | Share (all) | R1 | R2 | R3 | Mean damage dealt | Mean damage taken | **Net** |
|---|---:|---:|---:|---:|---:|---:|---:|
| JAB | 24.3% | 24.8 | 23.1 | 25.4 | 7.54 | 5.97 | +1.57 |
| **KICK** | 25.8% | 27.9 | 26.7 | 19.8 | 13.89 | 6.40 | **+7.49** |
| BLOCK | 12.8% | 12.1 | 11.9 | 16.0 | 0 | 0.89 | −0.89 |
| DUCK | 10.4% | 9.9 | 9.6 | 12.7 | 0 | 4.78 | −4.78 |
| THROW | 6.3% | 7.0 | 5.7 | 5.8 | 5.68 | 5.80 | −0.12 |
| RECOVER | 18.6% | 18.4 | 19.3 | 17.7 | 0 | 8.26 | −8.26 (it buys stamina) |
| EXHAUSTED | 1.9% | 0.0 | 3.6 | 2.5 | 0 | 8.36 | −8.36 |

**Score as a function of the share of an action in a fighter's own executed beats:**

| Action | 0–10% | 10–20% | 20–30% | 30–40% | 40%+ |
|---|---:|---:|---:|---:|---:|
| KICK | 0.32 | 0.43 | 0.55 | **0.64** | 0.61 |
| DUCK | **0.55** | 0.48 | 0.40 | 0.27 | **0.11** |
| BLOCK | 0.53 | 0.50 | 0.44 | 0.40 | 0.38 |
| THROW | 0.51 | 0.48 | 0.45 | 0.38 | 0.38 |
| JAB | 0.47 | 0.50 | 0.48 | 0.51 | 0.56 |

**Readings:**
- **KICK is the dominant action in this population.** Every top performer is kick-heavy: oni 64%, EVO-GEM 65%, search 48%.
- **DUCK is close to useless.** Its opening reward (+4 on the next hit) does not pay for its 18-damage exposure to KICK when kicks are 26% of all beats.
- **THROW is niche.** It pays only against BLOCK or RECOVER and is interrupted by the two most common actions.
- The most common beat pairings are JAB–KICK (13.4%), JAB–RECOVER (9.3%), KICK–RECOVER (8.1%) and KICK–KICK (7.2%). These are trades, not reads.

KICK is not a universal best, though: jabber-v1 beat kicker-v1 **145–0** live. The rules have counters; the population lacks them.

### 3.3 Power, opening, guard

- **Power:**
  - landed in 48.4% of fighter-fights, was wasted or blocked in 21.9%, and never used in 29.7%;
  - 4,603 of 5,417 uses are in the **final round** (round 3): bots hoard it, so it rarely shapes the fight's middle;
  - mean bonus damage is **1.93 HP per fighter-fight**.
- **Opening:** 0.55 bonus hits per fighter-fight, 2.20 HP.
- Together power and opening add about **4 HP per side per fight**, about 5% of damage dealt. That is too small to be a decision anyone would watch for.
- **Guard:**
  - BLOCK is roughly neutral (−0.9);
  - guard strain (block against kick) occurs on 6.4% of beats;
  - streak fatigue rarely bites, because bots seldom block three times in a row.
- **Exhaustion:** 1.9% of beats (the model gate is below 10%). It is concentrated in the scripts: oni 18% and EVO-GEM 25% of their beats, because a fixed plan ignores stamina.

### 3.4 Fight shape (model.md bands)

| Measure | Band | Ranked | Duel | Cup | All |
|---|---|---:|---:|---:|---:|
| KO | — | 61.6% | 75.2% | 80.2% | 65.7% |
| Decision (HP) | — | 33.0% | 20.4% | 13.5% | 28.9% |
| Double KO | — | 4.2% | 3.8% | 6.1% | 4.3% |
| Draws (double KO + HP tie) | ≤15% | 5.4% | 4.4% | 6.3% | 5.3% ✓ |
| Reach round 3 | ≥40% | 73.1% | 72.7% | 49.9% | 70.7% ✓ |
| Round-1 KO | ≤20% | 0.0% | 0.0% | 0.8% | 0.1% ✓ |
| Trailer after R1 wins | 10–40% | 25.1% | 35.0% | 21.1% | 26.4% ✓ |
| Exhausted beats | <10% | — | — | — | 1.9% ✓ |
| Median beats per fight | — | 15 | 14 | 12 | 15 |
| Median final HP margin | — | 18 | 24 | 22 | 20 |

**The single most common KO beat is round 3, beat 1** (550 of 2,700 KOs and double KOs). Round-3 KOs total 1,572, round-2 KOs 1,124 and round-1 KOs 4. Many fights are effectively over on the first beat of the last round, when saved power and a fresh plan meet a low-HP opponent.
The leader after round 2 goes on to win 77%.

### 3.5 Round-by-round adaptation

Mean HP differential per round (damage dealt minus damage taken):

| Fighter | Type | R1 | R2 | R3 |
|---|---|---:|---:|---:|
| tengu | scout-v1 | −0.8 | **+30.0** | +4.3 |
| RYUBOT | scout-v1 | **−24.0** | **+24.5** | +1.4 |
| oni | fixed script | **+29.8** | −4.5 | +3.8 |
| EVO-GEM | fixed script | **+26.5** | −15.3 | +7.8 |
| kappa / EVO-DS | search-blind* | +6.6 / +5.3 | −0.4 / +1.3 | +2.1 / +1.3 |
| mixed-v1 clones | — | −0.2…−4.0 | −1.5…−15.3 | −1.2…−4.6 |
| KEN.EXE | LLM | −7.9 | +2.4 | +1.9 |
| QWEN-235 | LLM | −3.1 | +9.5 | +5.1 |

Round 1 belongs to the prepared scripts and rounds 2–3 to the adapters.
This scout-versus-script swing is the most interesting dynamic in the game, and the best evidence that commit/reveal with public rounds creates depth.
The history bug suppresses it for 6 of 16 scripted fighters.

### 3.6 Head-to-head (all modes; row's score against column, n)

Rows play columns. `mixed*` means reader-v1 or repeat-last-winner running as mixed-v1; `search*` means search-v1 running as search-blind.

| Row → Column | LLM | jabber | kicker | mixed | mixed* | scout | script-vs-mixed | script-vs-scout | search* |
|---|---|---|---|---|---|---|---|---|---|
| LLM | .50 | .80 | .34 | .60 | .55 | .36 | .16 | .28 | .18 |
| jabber-v1 | .20 | — | **1.00** | .57 | .71 | .11 | .00 | .00 | .12 |
| kicker-v1 | .66 | **.00** | — | .60 | .67 | .08 | .00 | — | .00 |
| scout-v1 | .64 | .89 | .92 | .88 | .87 | — | .21 | .43 | .21 |
| script-vs-mixed (oni) | .84 | 1.00 | 1.00 | 1.00 | .93 | **.79** | — | 1.00 | **.91** |
| script-vs-scout (EVO-GEM) | .72 | 1.00 | — | 1.00 | .96 | .57 | .00 | — | .21 |
| search* | .82 | .88 | 1.00 | 1.00 | .92 | .79 | **.09** | .79 | .50 |

There is a clear cycle: jabber beats kicker, kicker beats mixed, scout beats every fixed style, and scripts beat scout.
The exception is **oni**, which scores at least 0.79 against everything it met often. A single published deterministic six-action script winning almost universally is the model.md §2 red flag ("No single published deterministic six-action script should win universally").
The offline reader-v1 result (0.646) shows the rules contain the counter; the live lineup does not field it.

### 3.7 LLM planners

| Planner | Model | Combat score | Fights (combat) | Fallback rounds | Forfeits | Spend today (21.5 h) | $/call | $/win |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| KEN.EXE | gemini-3.1-flash-lite | 0.503 | 437 | 0.3% | 0 | $0.281 | $0.00043 | **$0.0025** |
| GEM-LITE | gemini-2.5-flash-lite | 0.477 | 462 | 1.3% | 62 | $0.217 | $0.00025 | $0.0016 |
| QWEN-235 | qwen3-235b-a22b-2507 | **0.632** | 34 | 4.2% | 109 | $0.017 | $0.00009 | $0.0004 |

**How the fallback share was measured:** I reconstructed each round's observation and replayed the deterministic mixed-v1 fallback, which is seeded from the observation hash. The false-positive rate on a non-LLM control (tanuki) is 1 in 1,965.

**Findings:**
- The LLMs really play. Timeouts are not the problem, and **the $1/day caps are nowhere near binding** (projected $0.02–0.31 per day).
- **Against scripted bots they are mid-pack.** They beat jabber (0.80) and mixed (0.55–0.60) but lose to kicker (0.34), scout (0.36), the scripts (0.16–0.28) and search (0.18).
- They adapt modestly: KEN.EXE goes from −7.9 in R1 to +2.4 and +1.9.
- QWEN has the best combat score of the three but, **once forfeits are counted, the worst money result**. Its rating fell from 891 to 505 almost entirely through forfeits.
- The system prompt (`prompts/combat/planner-system.md`) omits:
  - that a clean, unanswered JAB also earns an opening;
  - that power is consumed even when wasted;
  - that the plan is rejected if power is already spent. This is the direct cause of the forfeits.


---

## 4. Is it fun?

### 4.1 As a spectator

**Pacing is the biggest problem.**

| Measure | Value |
|---|---|
| Ranked fight, match to result | median 82 ticks = **123 s**, p95 126 s. model.md §4 targets median ≤60 s and p95 ≤90 s. |
| Round cadence | Every **28 ticks = 42 s**. The contract waits for the full 24-tick commit window even when both commits land in 2–4 ticks (protocol.md §4: "Do not shorten the commit window"), then 1–3 ticks of reveal latency. |
| Beat delivery | All 6 beats land at once, so the viewer waits about 40 s and then sees about 2 s of action. |
| Duel series | median 249 s, p90 458 s. |
| Cup | about 75 min per cup. |
| Idle gap between a fighter's contests | median 46 ticks (69 s); p90 323 ticks. |
| Concurrency | about 118 fights per hour, about 4 live at once against a capacity of 16. |

**Readability suffers from the export bug.** About 80% of fights show "DEADLINE PASSED, AWAITING ADVANCE" forever, and their replays end before the KO.
A spectator cannot see how most fights end, which undercuts every other quality.

**There is real drama underneath:**
- 26% of fights are won by the fighter trailing after round 1;
- 221 fights (6%) were won after trailing by 30 HP or more; the biggest was a 58-HP comeback in #4037 (RYUBOT over EVO-GEM, KO) and #3637;
- 148 decisions were settled by 4 HP or less (closest: 2 HP, e.g. #171 GEM-LITE vs kirin);
- 5.3% draws, mostly double KOs (#4086, #4082, …);
- the outcome mix is healthy at 66% KO, 29% decision and 5% draw.

**Variety is poor:**
- the same 82 ranked pairs repeat, with EVO-DS vs kappa 210 times;
- cups are a coronation (oni 25/27), and duels a massacre (tengu 138–5);
- the fighters' "personalities" are mislabelled (§1.6), and half are mixed-v1 under different names.

**Outcomes feel partly earned.** The scout-versus-script round swing (§3.5) is legible and satisfying.
But power and opening are too small to notice (about 4 HP per side), and most KOs are straight KICK trades rather than reads.

### 4.2 As a bot builder

The engine is clean and deterministic, and the rules are small enough to hold in your head.
A public simulator, NPC ladder and `evaluate` tool are exactly what a builder wants.

Three things currently punish or mislead a builder:
1. **A one-byte mistake costs the entire stake.** A plan with a spent power slot is a forfeit, and neither the SDK nor the bot catches it before committing.
2. **The advertised history is missing live.** The bot contract passes `prior_rounds` in the observation, but the built-in policy adapter drops it.
3. **The meta is solvable by one script** because the field is thin, so the most profitable "bot" is a constant.

### 4.3 What would make it more exciting

- **Stream beats instead of batching them.** Replay each round's 6 beats over about 10–15 s while the next commit window runs; the protocol already allows this. Or cut the demo tick to 0.5 s, or use a commit window of 8–10 ticks for scripted-only fights.
- **A visible stake in each round.** Show HP bars, the round swing and the trailing-fighter comeback odds in real time.
- **Make power and opening decisive,** for example power +8 damage, or opening +6 and lasting two beats. Make DUCK safer against KICK so reads matter more than trades. This needs a new candidate version and the model.md campaign.
- **Rotate lineups and seed variety:** cup-enable kappa and EVO-DS, keep the duel roster larger, add real reader and history bots once §3.1 is fixed, and cap one fighter's cup wins per day in the demo.
- **Narrate:** use per-fight captions from the trace reason codes ("KICK into DUCK, 18 + opening 4").

---

## 5. Recommendations, ranked by impact

| # | Recommendation | Impact | Evidence |
|---|---|---|---|
| 1 | **Fix the exporter write-once bug** (`export.py` `export_all`): rewrite `fights/<id>.json` and `replay.json` until written as final. Make `run.cjs:197` fail on overdue live fights. | The site shows endings and results for about 80% more fights. It removes the "stuck fights" symptom entirely. | 162 of 200 stale files; #3900 ended at 79,350 KO but is published as R3 REVEAL; the public #4000 is stale (§1.1). |
| 2 | **Validate the plan against state before commit** (`Bot._fight_step` and `llm_planner`): run `validate_plan`; on failure strip `power_slot` or fall back. Stop re-sending a reveal rejected with `BAD_PLAN`. Tell the LLM prompt that power is gone. | 171 invalid-plan forfeits and double faults (166 lost stakes, about 166 k QU) avoided; QWEN goes from worst to competitive. | All 109 QWEN and 62 GEM-LITE forfeits are "power strike already spent" (§1.3). |
| 3 | **Pass `prior` into `npcs.Observation` in `bot.policy_chooser`** (rebuild `RoundResult`s from `obs["prior_rounds"]`, or change the policies to read the observation's history). Until fixed, label fighters by their effective behaviour on the site. | Restores reader-v1, repeat-last-winner and search-v1. It ends oni's and tengu's farming and makes rounds 2–3 matter. | Repeat rate 0 of 1,433 for repeat-last-winner; reader's mix equals mixed-v1; offline reader-v1 scores 0.646 against oni's script versus 0.07 live (§3.1). |
| 4 | **Respect cooldown and suspension in the bot** (read `cooldown_until` and `suspended_epoch`, back off). Stop overriding `stop_after_faults` in the live budget, or set it to a sane number. | Cuts about 23% of simulated execution fees (about 245 k QU) and chain spam. Aligns with AUD-005. | QWEN made 16,688 QUEUE_ENTER calls for 182 accepted offers (§1.3). |
| 5 | **Re-price the economics with execution cost included:** re-run `combat-economics.py` including `FeeModel`, and choose tiers and rake so rake at least covers the per-fight execution cost. Consider a small per-call or entry fee paid by players. | The house currently burns about 5× its take: −986 k in 34.8 h. | §2.1. |
| 6 | **Pace the demo for spectators:** a demo timing profile (for example commit 8 / reveal 6, or tick 0.75 s for scripted-only pairs) plus per-beat playback during the next commit window. | A ranked fight goes from 123 s toward the 60 s target; the viewer waits about 10 s instead of 40 s per round. | §4.1; model.md §4 target missed by about 2×. |
| 7 | **Fix event balance in the demo lineup:** cup-enable the strong ranked bots, widen the duel roster, give bots duel accept filters (rating gap, stake), and cap sponsorship capture. | Cups and duels become contests rather than farms. | oni 25/27 cups, +388 k; tengu 138–5, +241 k (§1.4, §2.4). |
| 8 | **Season qualification and matchmaking:** in the demo, raise `max_rating_gap` or relax distinct opponents in proportion to population, so top-rated fighters can qualify. | Champions reflect skill rather than luck. | S7 champion at 754 lifetime; kappa and EVO-DS disqualified (§1.5). |
| 9 | **Operational hygiene:** snapshot state so restarts do not replay the whole journal; prune `fights`, `contests` and `offers` from hot state; keep `end_tick` from scanning history; log planner fallbacks and costs; keep per-day LLM spend history. | Bounded restart time (currently about 2 min, growing about 3 s per hour of runtime) and an audit trail. | §1.2, §1.6. |
| 10 | **Balance candidate 2 (after 1–4, then re-measure):** KICK net +7.5 and DUCK −4.8 in this population. If they persist with a healthy field, consider KICK cost 13–14 or 12 damage against JAB, DUCK counter-damage against KICK, and bigger power and opening. Keep this behind a new ruleset digest and the full model.md campaign. | More reads, fewer trades. | §3.2–3.3. |

---

## 6. Offline runs and reproducibility

- **Replay:** `scripts/replay.py` rebuilds the world from the copied journal (107–135 s) and pickles it. `extract.py` flattens it into `data.json`. `a1.py`–`a6.py`, `revealfail.py`, `llmfallback.py`, `stuck.py` and `csvs.py` produce the tables above.
- **Evaluate** (suite `audit-20260925`, 60 paired seeds = 120 fights per cell):
  - reader-v1: 0.646 against script-vs-mixed-v1, 1.000 against kicker-v1;
  - mixed-v1: 0.029 / 0.329;
  - scout-v1: 0.142 / 0.887;
  - search-blind: 0.250 / 0.988.
- **search-v1 with history against script-vs-mixed-v1** (40 paired seeds, 80 fights): 0.475 (33/10/37), against 0.250 for search-blind. History roughly doubles search's score against oni.
- **`scripts/combat-soak.py --ticks 4000 --seed 20260925`:**
  - 0 invariant violations, 0 unsettled budgets;
  - but only 26 contests in 4,000 ticks, because its deliberately thin reserve halts 675 ticks (generation 676);
  - it never runs the exporter, so it **cannot catch §1.1**;
  - its lineup has no LLM planner and no history-dependent failure check, so it **cannot catch §1.3 or §3.1** either.
  - Add a steady-state soak phase with a normal reserve that exports each N ticks and asserts every DONE fight's published file is DONE, plus a bot-level assertion that no reveal is rejected with `BAD_PLAN`.

Numbers are for fake QU on a simulated chain with operator-run bots. They are not evidence of external demand, and not a Qubic cost measurement.
