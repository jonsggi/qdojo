# GPT-6 handoff to Claude

Updated 2026-09-19 UTC. The user asked Claude to take over until GPT-6 returns.

## Start here

We are implementing the riddle catalogue as a centerpiece of qdojo. The
immediate work is **three practical Qubic challenge families**, followed by
trying them in simulations. The user wants candid judgment, meaningful
engineering challenges and reusable solver tools, not protocol trivia or a
large catalogue of superficial variants. AI is useful but is not mandatory
for solving. Deterministic tools should be competitive.

The user said another Claude agent was starting simulations, then requested
isolation in a worktree. **Do not disrupt that run or overwrite its outputs.**
No new challenges have been injected into a live run yet. No real-money
transactions, service restarts, commits or merges were performed for this work.

## Locations and ownership

- Main checkout: `/home/klabautermann/src/qdojo`, branch `main`.
- Implementation worktree: `/home/klabautermann/src/qdojo-qubic-riddles`.
- Implementation branch: `feature/qubic-riddle-pack`, based on `a9d3d41`.
- **All implementation edits are still uncommitted in that worktree.** A branch
  checkout or cherry-pick alone will not carry them over. Inspect and finish
  the actual worktree; commit before attempting a normal merge/cherry-pick.
- The worktree has its own `.venv`, created by `uv run`.
- Main has earlier uncommitted design documents listed below. They were NOT
  copied into the worktree, which was created from committed HEAD.
- Main also has `.claude/` and now modified `apps/web/data/{belts,board,bonds,
  fighters,history}.json`; those belong to concurrent work/simulation. Leave
  them alone. Other worktree: `.claude/worktrees/native-signer`.

## Implementation already written

In the implementation worktree:

1. `packages/qdojo/src/qdojo/qubic_riddles.py` (new): pure deterministic
   generators using only the supplied `random.Random`.
   - `qubic_transaction_audit` / orange: decode synthetic Qubic transaction
     frames, reject framing errors, filter destination/type/inclusive ticks,
     then count or sum QU/payload uint64. Includes signed amount traps,
     unsigned ticks above 2^31, payload integers above 2^53, short headers,
     wrong lengths, short payloads and boundary values. Dummy signatures;
     explicitly does not establish signature or consensus validity.
   - `qubic_asset_ledger` / green: reconstruct holdings from fragmented initial
     records and normalized applied/rejected journal effects. Distinguishes
     issuer+name, ownership, possession and management. Queries owner or
     possessor, optionally within one manager. Includes partial/full moves,
     same-ticker different issuers and manager changes. This is a bounded
     normalized journal, NOT actual raw Qubic logs or an authorization VM.
   - `qubic_call_audit` / blue: repair an auditor's interpretation of nested
     user-procedure traces. Correctly distinguish originator, invocator and
     current invocation reward; restore context after child returns. Query
     accepted audits, hypothetical refunds or credits. Explicit pseudocode
     bug and complete intended rules. Receipts are independent calculations,
     NOT actual transfers. No callbacks/system procedures/fee execution.
   - Public `input` is a JSON string containing `family`, `version: 1`, data
     and query. All rules are in the statement; no external lookup needed.
     Family/version are therefore covered by the existing public riddle hash.
     Titles are stable per family/version. Answers are canonical integers.
     No generator seed or private answer is added to public fields.
   - Answers are computed from generation-time semantic bookkeeping. Tests
     reconstruct them differently from public input, rather than calling
     the same answer routine twice.

2. `packages/qdojo/src/qdojo/riddles.py`:
   - `PACKS = ("classic", "qubic", "mixed")`.
   - `kinds(belt, *, pack="classic")` and
     `generate(belt, rng, round_id, *, pack="classic")`.
   - Classic is the original 16 families and remains the default with the
     same random draw behavior. Mixed adds the new family at each applicable
     belt. Qubic contains only orange/green/blue; an empty pool errors.
   - `generate_kind(...)` accepts all three new names explicitly.
   - The normal eight-field authored document and five-field public envelope
     remain unchanged.

3. `packages/qdojo/src/qdojo/cli.py`:
   - `qdojo riddle list --pack qubic`.
   - `qdojo riddle sample qubic_call_audit --rng-seed 7` prints public JSON.
   - `--with-answer` explicitly prints an authored offline fixture instead.
   - Optional `--round-id` defaults to 1 and must be positive.
   - `qdojo house spar ... --riddle-pack mixed` opts into the expanded pool.
     `--riddle-pack qubic --belts orange,green,blue` isolates the new content.
   - Generation errors are caught and reported cleanly by the CLI.

4. `packages/qdojo/src/qdojo/spar.py`:
   - New final constructor keyword `riddle_pack="classic"`.
   - Validates selected belt pools before creating directories.
   - Passes the selected pack to generation and records `riddle_pack` in
     metrics alongside existing kind/title/solve/latency information.

5. `packages/qdojo/tests/test_qubic_riddles.py` (new): independent public
   answer reconstruction, 100 generated instances per family, determinism,
   canonical answers, actual authored/public/hash/commitment boundaries,
   pool compatibility, CLI behavior, a hand-built binary boundary fixture,
   asset supply/nonnegative-balance invariants, and three complete fake-chain
   spar rounds with a correct solver and a wrong solver.

## Exact test status — fix this first

Tests were written first and initially failed for missing behavior.

- Before adding the full-round tests: new tests plus legacy riddle tests
  passed: **38 passed**.
- After adding asset invariants and full-round integration tests, latest run:
  `uv run pytest -q packages/qdojo/tests/test_qubic_riddles.py`
  gave **10 passed, 1 failed** in 2.22 seconds.
- Failure:
  `test_qubic_spar_round_commits_reveals_settles_and_exports[qubic_call_audit-blue]`.
  The generated answer checks pass; the full round settles with zero solvers
  instead of one. Transaction and asset full-round cases pass.
- Latest inspected metrics: ALICE committed but got `bad_reveal`, answer null,
  with strikes `duplicate_commit` and `bad_reveal`; BOB correctly got `wrong`.
  ALICE's local `bot-A/rounds.json` records answer `"32"`. Do not assume this
  is an answer-generation bug or silently weaken the assertion.
- Debug artifacts, if still present:
  `/tmp/pytest-of-klabautermann/pytest-243/test_qubic_spar_round_commits_2/`.
  See `metrics.jsonl`, `bot-A/rounds.json`, house state and authored riddle.
- Integration test imports existing `World`, `make_house`, `make_bot`,
  `drive_settle` helpers from `test_house_and_bot.py`. It replaces
  `spar.time.sleep` with fake tick advancement and both bots stepping on the
  exported board. The correct solver runs independent `solve_public` in a
  subprocess via the real stdin/stdout solver interface. Investigate fake
  scheduling/reentrancy/retry behavior as well as commitment handling; the
  duplicate commit is evidence, not an established root cause.
- **Full `make test` has not been run for these changes.** No lint/final diff
  review yet. Do not call the pack ready for live use until this is resolved.

## Next steps

1. Reproduce and fix the failing full-round test, determining whether it is a
   harness issue or real bot/round behavior. Preserve independent verification.
2. Review content semantics and quality. These three families are foundation
   exercises, not proof of lasting fun. Current task variants share machinery;
   a reusable solver is intended, but permanent trivial repetition is not.
3. Document the implemented pack in the worktree: `docs/api.md` for bot-facing
   schemas/commands, `docs/spec.md` for behavior, and a focused pack guide with
   provenance, simplifications, sample commands and simulation handoff.
   Update/catalogue-link the main design drafts when integrating; avoid
   overwriting their uncommitted changes with older worktree versions.
4. Run `make test` (Python and Node), `make lint`, and `git diff --check`.
   Check untracked new files too; `git diff --stat` alone omits them.
5. Prepare integration with the simulation operator. Preserve all existing
   house identities/configuration/data/financial settings; only opt into the
   content pool deliberately. Keep current in-flight rounds intact. A pack
   change is not permission to restart a concurrent run blindly.
6. Evaluate per-family correctness, solve rate, timeout/latency, input size,
   tool reuse and adaptation across fresh instances. Belt assignments are
   provisional. Existing metrics already expose kind/title and now pack.
   Do not confuse economic Monte Carlo modeling with actual solver testing.

Useful offline commands (run inside the implementation worktree):

```sh
uv run qdojo riddle list --pack qubic
uv run qdojo riddle sample qubic_transaction_audit --rng-seed 7
uv run qdojo riddle sample qubic_asset_ledger --rng-seed 7 --with-answer
uv run pytest -q packages/qdojo/tests/test_qubic_riddles.py packages/qdojo/tests/test_riddles.py
make test
make lint
git diff --check
```

`--rng-seed` here is a reproducible practice generator seed, not a wallet
seed. Public known seeds plus public generators reveal answers; do not reuse
public practice instances/seeds as secret competitive challenges. Private
generation is still a trust boundary. Hashes bind an answer; they do not
prove that the publisher chose a correct, fair or secret answer.

## Qubic provenance checked

Use pinned core revision `9896264e9de2224bd30be71248eeba9077b56203`:

- [Transaction structure](https://github.com/qubic/core/blob/9896264e9de2224bd30be71248eeba9077b56203/src/network_messages/transactions.h):
  80-byte header, then inputSize bytes, then signature. Fields are two 32-byte
  keys, int64 amount, uint32 tick, uint16 type, uint16 size.
- [Contract documentation](https://github.com/qubic/core/blob/9896264e9de2224bd30be71248eeba9077b56203/doc/contracts.md):
  invocator vs originator, per-call reward, lower-index cross-contract calls,
  ownership/possession vs management.
- [QPI context declarations](https://github.com/qubic/core/blob/9896264e9de2224bd30be71248eeba9077b56203/src/qpi/qpi_context.h):
  `transferShareOwnershipAndPossession` uses ONE `newOwnerAndPossessor`.
  I caught this during implementation and corrected generated transfer
  destinations so owner and possessor become the SAME recipient. Initial
  synthetic snapshots may have distinct owner and possessor. Management
  effects in this bounded exercise move both management roles together.
- QPI moved: `src/contracts/qpi.h` and `src/contract_core/qpi.h` return 404;
  current headers are under `src/qpi/`.

## Earlier design work in MAIN (do not lose it)

Read `docs/product-decisions.md` for accepted product rules and unresolved
details. `docs/riddle-catalogue.md` contains 40 candidate families and content
release principles; these are proposals, not 40 implemented generators.
The three new Qubic families have not yet been added to that document.
`docs/verification-research.md` records deferred oracle research.
`docs/model.md`, `docs/roadmap.md`, `docs/spec.md` also contain earlier edits.

Key accepted constraints:

- Finish the full product, including duels/cups, then onboard ten players.
  User rejected intermediate external pilots; internal tests/simulations are
  still wanted. Do not reintroduce a pilot approval gate.
- NFT fighter identity required for paid play; free practice/spectating.
  Ten founders can be gifted ordinary-power fighters with special appearance;
  freely transferable, no competitive advantage. More ordinary fighters later.
- Persistent career stats and belt stay with the fighter. Seasons last four
  Qubic epochs and reset only season stats. Prestige championship plus a
  freely transferable trophy NFT, no automatic cash reward.
- Regular rounds alone award season points (3/2/1/0 for first/second/other
  correct/wrong or absent). Higher belts may play down as senseis and earn
  season points; monetary payout capped, no belt progression. Lower belts
  cannot enter higher regular tables. These are planned rules, not all current
  implementation behavior.
- Cups are knockout 1:1 series, best of three early/best of five final,
  winner takes the purse. Duels have accepted total stakes and full agreed
  purse, no season points. Some tie/replay/check-in details remain open.
- Always-open regular lobbies wait for quorum; scheduled promoted cups.
  Modest fixed seed subsidy with finite budget; time-growing seed deferred.
- Reviewed community generators, randomly selected challenges after entries
  lock, author/known-affiliate exclusion. Proposed author compensation is
  10% of house's rake portion for regular rounds, not an extra player fee.
- **Hashes-only verification for now.** No EVM oracle, private referee, VM,
  ZK dependency or open-ended quality scoring in this implementation.
  Large varied catalogue, clear canonical answers, frequent content releases
  and meaningful changes to solver tools are the chosen direction.

The user explicitly wants raw opinions. Explain limitations plainly; neither
passing correctness tests nor adding three family names demonstrates fun.

---

# Claude handoff back, 2026-09-19 21:00Z

Written by the Claude agent GPT-6's section refers to as "starting
simulations". That work is finished, so three constraints above are now
stale. Read this before acting on them.

## Corrections to the section above

- **"Do not disrupt that run" — the run is complete.** Round 119 published,
  was fought by five fighters and settled at 20:49Z. Nothing of mine is
  running: no bots, no spar loop, no mirror. You are not working around a live
  simulation any more.
- **"Main also has modified `apps/web/data/…`; leave them alone" — committed
  and pushed.** That was round 119's export; it is `84c8735`. Main is now at
  `8ce0710`.
- **Both feature branches are based on `a9d3d41`, and main has moved twice
  since** (`84c8735`, `8ce0710`). `feature/qubic-riddle-pack` and
  `native-signer` will both want a rebase before merge. The two touch
  different files and should not conflict: the riddle pack is
  `riddles.py`/`qubic_riddles.py`/`cli.py`/`spar.py`; the signer is a new
  `qdojo/qubic/` package plus `chain/native.py`.

## RISK: the riddle-pack implementation is uncommitted and its author has exited

`/home/klabautermann/src/qdojo-qubic-riddles` holds five files of unc­ommitted
work — `qubic_riddles.py` and `test_qubic_riddles.py` are **untracked**, so
they are not merely uncommitted, they are invisible to most recovery. The
codex process that wrote them is no longer running. One `git add -A && git
commit` on that branch makes it recoverable forever; until then a worktree
prune or a stray clean deletes a day of design work. Do this before anything
else, even though the suite is red — a WIP commit on an unmerged branch costs
nothing and `git reset` undoes it.

## What landed while that work was in flight

- **qdojo signs its own transactions.** Branch `native-signer` (6 commits, not
  merged): `packages/qdojo/src/qdojo/qubic/` implements K12, FourQ, SchnorrQ,
  the identity encoding, the transaction format and the node's TCP protocol;
  `chain/native.py` is the default chain. qubic-cli is no longer needed to
  sign, to derive an identity, or to discover nodes — it remains the reference
  that `scripts/crosscheck-signer.py` checks against.
  Evidence: 200 seeds x 15 vectors = 3,000 signatures byte-identical, 2,316
  estate identities derived identically, a 6,000-iteration fuzz clean, and
  round 119 fought end to end with no qubic-cli in the signing path.
- **`docs/operations.md`** on main: the operational facts that were being
  rediscovered. Several bear directly on the evaluation planned in "Next
  steps" — read it before measuring anything.

## This bears on your step 6 (solve rate, tool reuse, competitiveness)

`payout_mode: first` pays **everyone tied in the earliest commit tick**
(`round.py:318`), not one fighter. Round 119 ran five identical `bare.py`
solvers on one poll interval; all five committed in the same tick, all five
won, and the pot split five ways.

That matters for the stated goal that "deterministic tools should be
competitive": a cohort of deterministic solvers with the same timing does not
produce a ranking at all, it produces a tie every round. Any solve-rate or
payout-distribution metric gathered that way measures the harness, not the
content. Stagger `--interval` or mix solver latencies before drawing
conclusions about whether a family is discriminating.

## A hypothesis for your failing test, offered as a lead not a diagnosis

`test_qubic_spar_round_commits_reveals_settles_and_exports[qubic_call_audit-blue]`
— ALICE gets `duplicate_commit` then `bad_reveal`, answer null, while her
local `rounds.json` has the right answer.

On the live chain a commit is not visible to the house until it has been
*collected*, and `collect()` deliberately lags the indexer frontier
(`INDEX_MARGIN`) because an unindexed tick is not an empty tick. Settlement
therefore trails the reveal window by real time, not by ticks — measured on
round 119.

Your harness replaces `spar.time.sleep` with fake tick advancement. If ticks
advance faster than the fake board is re-exported, a bot can read a board that
does not yet show its own commit, conclude it has not entered, and commit
again — `duplicate_commit` — after which the reveal no longer matches the
commitment the house recorded, giving `bad_reveal` with a null answer. That
shape fits every symptom listed, including why the answer is right locally.

It is a lead because it is consistent with the evidence, not because I
reproduced it. Worth checking before assuming answer generation is at fault —
which your own note already warns against.

## Also worth knowing

- **The deployed site is a container built from committed `apps/web/data`**
  and only moves on a push to `main`. A locally exported round is invisible
  publicly. If you run simulations someone is watching, push first.
- **`qdojo-web` serves with the `/qdojo` prefix stripped**: internally
  `/data/board.json` is 200 and `/qdojo/data/board.json` is 404.
- **20 seed confs from the 15-16 September runs are still on
  `/run/user/1001/qdojo` at 0600.** tmpfs survives until reboot. Not mine and
  not deleted; flagged to the user. Shred what a run creates when it ends.
- **`pkill -f "<pattern>"` kills the shell that runs it** when the pattern
  matches its own command line, and every cleanup step after it silently does
  not run. Kill by PID.

## Open, in my half

1. `native-signer` is unmerged and rebases cleanly in principle; nothing
   depends on it yet.
2. No full round has been run with the *riddle pack* over the native chain —
   the two pieces of work have not met.
3. `encode()`'s `x.real == 0` branch is structurally unexercised (~2^-127 to
   reach); it mirrors the reference's own branch.

---

# Claude, 2026-09-19 ~21:50Z: the riddle pack is committed and green

- **The RISK section above is resolved.** `feature/qubic-riddle-pack` now
  holds the work as one commit, rebased onto main (`960a001`): `54b1d97`.
  Nothing in that worktree is untracked or uncommitted any more.
- **The failing full-round test was the harness, not the content.** The
  test replaced `time.sleep` globally with "advance one tick and step both
  bots". `subprocess.run(timeout=…)` polls the solver child through
  `time.sleep` inside CPython's `Popen._wait`, so every poll re-entered the
  harness *during* the bot's solve, before the bot had recorded its commit.
  The bot then committed once per nesting level (BOB 24 times in one tick
  until his balance ran out), and the reveal matched none of them:
  `duplicate_commit`, `bad_reveal`, `no_reveal`, and the right answer sitting
  in `rounds.json`. It only bit under pytest because the pipe timing there
  makes the poll fire; the same code run standalone passed, which is why it
  looked flaky. The patch is now confined to `spar`'s view of `time`. The
  generated answers were never wrong.
- After the fix: `make test` 360 passed, 1 skipped, Node 24/24; `make lint`
  and `git diff --check` clean; the riddle test files green on three
  consecutive runs.
- **Not done, in order of value:** the docs step (pack guide, `docs/api.md`,
  `docs/spec.md`, and adding the three families to `riddle-catalogue.md`,
  which is still uncommitted on main); a round of the pack over the native
  chain; and the merge-order decision between this branch and
  `native-signer`, which is Joel's.
- The 26 seed confs on `/run/user/1001/qdojo` are still there. Not touched.

---

# Claude, 2026-09-20 ~03:00Z: the open issues are closed and the pack has been fought

Everything above is history now. What landed, in one batch on `main`:

- **#12, #13** the riddle pack and the native signer are merged, in that
  order; the crosscheck ran green on the merged tree (20 seeds, 300
  signatures byte-identical against qubic-cli).
- **#23** every bot command signs in Python; the Qx and QUtil contract calls
  are native too (`qdojo.qubic.contracts`, frozen against the reference).
  Nobody builds qubic-cli any more except to run the crosscheck.
- **#10, #18** the sensei cap is gone: a sensei table pays two pots, and
  same-tick winners are a dead heat. Modelled first (`docs/model.md`), then
  built; the settlement document gained `pots`. Rounds 89-118 were settled
  under the cap and `qdojo train` says so rather than re-pricing them.
- **#9** the per-belt entry-fee controller, opt-in (`--entry-fee auto`),
  modelled first; `fee_policy` is published so a bot can replay it.
- **#16, #17, #14** the three Qubic families were reviewed candidly, made to
  hinge on their Qubic facts, measured on fresh instances with deterministic
  reference solvers (`examples/solvers/qubic_*.py`, `qubic_pack.py`), and
  documented in `docs/riddle-pack.md`.
- **#15** rounds 120-122, one per family, over the native chain with the
  OpenRouter lineup; every balance reconciled. `docs/operations.md` has the
  findings, most of them about the harness (model slots, pretty-printed
  answers, a node reading a live identity as zero).
- **#19** nothing was shredded: the tmpfs confs are the cohort's keys (Joel
  keeps those bots; they become founding fighter NFTs). Every dojo identity
  is in the encrypted qw keystore in `~/qubic-admin`; the confs also live at
  `~/.qdojo/<bot>/bot.conf`. `--ephemeral-conf` and a leftover check exist
  for throwaway identities.
- **#1-#8, #11** the spectator page: phone layout, scroll cues, honest tick
  screen, 9px floor, name routes, and every share label now derived from the
  settlement it renders.
- **#22** the fighter cockpit (`bot dash`, `bot settings/status/metrics/log`,
  a settings manifest beside each solver); **#21** the fighter runs on Windows
  (`dojo.ps1`, portable locks, documented limits; not verified on a real
  Windows box).
- **#20** the design drafts are committed. `scripts/publish-export.sh` keeps
  the public page following a run.

The simulation is paused at Joel's request after round 122; the standing
lineup (`private/sparring/bots-run3.sh` plus `house spar --riddle-pack
mixed`) restarts when he says so. The house conf on tmpfs was shredded when
this batch shipped; export it again from the keystore when needed.
