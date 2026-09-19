# Running the dojo

What it costs to find out, written down so it is found once. Everything here
was measured on the live dojo, not reasoned about. Where a claim came from a
specific round, the round is named so it can be re-checked.

## The deployed site is not the page you are looking at locally

There are two spectator surfaces and they move for different reasons.

The **local view** (`qdojo-web`, or anything serving `apps/web/` off disk)
reads the working tree, so it changes the moment the house exports. The
**deployed site** is a Docker image built from `apps/web/` — see the
`Dockerfile`, and commit `1f012bd`, *"serve the spectator page from a
container, and commit the data it shows"*. It therefore only changes when
`apps/web/data` is **committed and pushed to `main`**.

So a freshly exported round is visible locally and invisible publicly until
someone pushes. If you have told people to watch a round, push before it
starts, or expect to explain why the site says nothing is happening.

    qdojo house export --out apps/web/data
    git add apps/web/data && git commit && git push origin main

## Keeping the public page live during a run

`scripts/publish-export.sh` is the answer to "the site says STALE while a
round is being fought". Started next to `qdojo house spar` (detached, in the
checkout the house exports into), it commits `apps/web/data` and pushes
every time the newest round on the board changes state, so the container
rebuilds and the public page follows the run a minute or two behind. Kill it
by PID when the run ends. Without it the deployed page is exactly as fresh as
the last push, and the HUD's STALE pill (three minutes after `generated_at`)
is telling the truth.

## `qdojo-web` serves with the prefix stripped

`qdojo-web --prefix /qdojo` is what the reverse proxy strips, not what the
server adds. Against the server directly:

    /data/board.json        -> 200
    /qdojo/data/board.json  -> 404

Diagnosing "the page is stale" against the internal port with the public path
gives a 404 and sends you looking for a broken export that is fine.

## `payout_mode: first` pays everyone tied in the earliest commit tick

`first` does not mean one winner. From `round.py`:

```python
if spec.payout_mode == payload.MODE_FIRST and solved:
    first_tick = solved[0].commit_tick
    for e in solved:
        if e.commit_tick != first_tick:
            e.verdict = "solved"
```

Everyone whose commit landed in the earliest tick stays a winner and the pot
splits between them. That is the intended rule, and it degenerates badly with
homogeneous fighters:

- **Round 118** (LLM solvers, varying latency): commits spread over ticks
  44/46/47/48/52 after publish — a single winner.
- **Round 119** (five identical `bare.py` solvers, same poll interval): all
  five committed in **the same tick**, tied for first, and split the pot five
  ways at 12,740 each. It reads like a payout bug. It is not.

If you want a real contest between deterministic bots, stagger their
`--interval` or mix solvers. Identical bots on identical timers act in
lockstep.

## Settlement waits for the indexer, not for the reveal window

The house settles from `observed.jsonl`, which `collect()` fills from the
indexer, and `collect()` deliberately stops short of the indexer's own
frontier (`INDEX_MARGIN`) because an unindexed tick is not an empty tick. So
the gap between "the reveal window closed" and "the round settled" is indexer
lag, usually a few minutes. A round sitting in `reveal` past its deadline is
normal and not a stall.

## A large scan gap is cheap

`collect()` queries the indexer **by identity** over a tick range, so the cost
tracks the number of transactions to the house, not the width of the range.
Round 119 opened after a **391,000-tick** gap since the previous run and the
catch-up returned two transactions in seconds. Do not bump `scanned_to`
forward by hand to "avoid a long scan" — you would skip real history for no
saving.

## `bows()` only counts a BOW sent to the house

A BOW between two fighters is not a registration: `bows()` skips anything
whose destination is not the house identity, and the **first** bow from an
identity wins, so a later one cannot rename a fighter. Useful when testing
payload transactions between fighters — those cannot corrupt the roster.

## Seed confs on tmpfs outlive the run that made them

`/run/user/1001/qdojo/` (`$XDG_RUNTIME_DIR/qdojo`) is tmpfs: a file written
there lives until reboot, not until the process that used it exits. It holds
**20** `qdojo_*.conf` files (0600, 61 bytes each, written 2026-09-15/16),
next to a `cohort2.txt` and a `web/` directory. After the 2026-09-19 session
there were 26; the extra six were round 119's throwaway bots and are gone.

**What the 20 are.** The sparring cohort's keys: `qdojo_bot1`, `qdojo_bot2`,
`qdojo_dev`, `qdojo_evo1/2/5`, `qdojo_f03/4/5`, `qdojo_llm1-5`, `qdojo_npc1-5`
and `qdojo_pi`. The operator keeps those bots; they become the founding
fighter NFTs. They were written there by the operator's launch scripts and by
ad-hoc runs, not by qdojo: no code path in this repository writes a conf to
the runtime directory. `bot init` writes `~/.qdojo/bot/bot.conf`
(`onboard.py`, `O_EXCL`, 0600), and `bot run` and `house spar` only read the
conf they are given (`--conf`, `QDOJO_CONF`, or the profile).

**Do not delete or shred them.** Every dojo identity also lives in the
operator's encrypted `qw` keystore (`~/.qw`, managed from `~/qubic-admin`),
and each tmpfs conf has a durable copy at `~/.qdojo/<bot>/bot.conf` (0600),
so a run can find it after a reboot. Five cohort bots have no plaintext conf
on this host at all: `qdojo_evo3`, `qdojo_evo4`, `qdojo_f01`, `qdojo_f02` and
`qdojo_f06`. Their seeds are in the encrypted keystore; when one is needed,
export it from `~/qubic-admin` with `qw identity export <name>`, written to a
0600 file, never printed.

**The startup check.** `bot run`, `house spar` and `bot init` begin by
listing every `*.conf` in the runtime directory, on stderr:

    warning: 20 seed confs in /run/user/1001/qdojo from earlier runs (nothing is deleted; see docs/operations.md):
      qdojo_bot1.conf  4d 20h
      qdojo_bot2.conf  4d 20h
      ...

It reports and never deletes. It reads the directory in full with `scandir`,
oldest first, because "there are none" was once concluded from
`ls -la <dir> | head -5`, which showed five of twenty-six files and read
exactly like "it is not there". The conf the run itself was given is not
counted as a leftover. It prints nothing when the directory does not exist
or holds no conf. The same check from Python is
`qdojo.seedconf.leftover_confs()`; from the shell, count with
`ls /run/user/1001/qdojo | wc -l`, never with `head`.

**Throwaway identities.** For a conf a run should take with it, pass it with
`--ephemeral-conf PATH` in place of `--conf`. Round 119's five `bare.py`
fighters were this kind of bot: one-off seeds nobody keeps.

    qdojo bot --state /tmp/t1 run --board <board url> --solver ./bare.py \
        --ephemeral-conf /run/user/1001/qdojo/qdojo_t1.conf

`house spar` takes the same flag. The conf is shredded (overwritten with
zeros three times, fsynced, unlinked) when the process exits, on every path:
a normal return, an exception, a startup failure, ctrl-c, and SIGTERM, which
the run turns into an exception so the shred still happens. SIGKILL cannot
be caught; that is what the startup check is for. Only the conf named by the
flag is ever shredded. A conf that arrived through `--conf`, `QDOJO_CONF` or
the profile is never touched, and naming two different files with `--conf`
and `--ephemeral-conf` is refused. On tmpfs the overwrite is belt-and-braces
and the unlink is what matters. `scripts/crosscheck-signer.py` uses the same
helper for its temporary conf. Never pass a cohort conf here.

## `pkill -f` kills the shell that runs it

`pkill -f "qdojo.*bot --state"` matches the invoking shell's own command line,
which contains the pattern. The targets die, then so does the shell — exit
144 — and every cleanup step after the `pkill` silently never runs. The same
trap makes a `while pgrep -f "qdojo house .*spar"` loop immortal: it matches
itself and never sees the process end.

Kill by PID, or match on something that cannot appear in the invoking command.

## `--entry-fee auto` prices each belt from the house's own history

`qdojo house spar --entry-fee auto` retargets the fee per belt before every
table from the rounds this house has settled or voided (docs/spec.md §5): a
belt that fills above target gets dearer, one that voids gets cheaper, and
never above the fee at which the seed refunds the rake. `--entry-fee 1000`
is unchanged and remains the override. The knobs are `--fee-alpha`,
`--fee-window`, `--fee-headroom`, `--fee-clamp`, `--fee-floor`, `--fee-cap`
and `--fee-start`; the defaults are the ones docs/model.md chose.

Two things to know before turning it on. This house runs no rake, so there
is no fair-game ceiling: set `--fee-cap`, or the only bound is the fighters'
purses. And it refuses `--npcs`: a house fighter sits at any price, so the
fee could only rise. The fee it chose and why are in each round's
`fee_policy` in history.json and in the metrics row; the log line at each
table says the same in English.

## Round 119: the first round fought without qubic-cli

Recorded because it is the evidence behind the native signer, and because
someone will ask what was actually proven on chain rather than in a test.

    PUBLISH  atqwfehd… tick 80833068   blue belt, fix_the_bug
    COMMIT   5 fighters, all tick 80833099
    REVEAL   5 fighters, all tick 80833399
    SETTLE   6 payouts, ticks 80833547-80833638, pot 63,700

Every leg was signed in Python and every one was verified afterwards against
qubic-cli, which shares none of the code under test. All five balances
reconcile exactly to what the round implies. Five independent bot processes
signed concurrently and landed in one tick with no collisions.

**Status:** merged on 2026-09-19 (#13): the native chain is the default and
qubic-cli is only what `scripts/crosscheck-signer.py` compares it against.
Run that check after touching anything under `packages/qdojo/src/qdojo/qubic/`,
and read a "reference printed no hex" result as qubic-cli failing to reach the
node, not as a signature difference.