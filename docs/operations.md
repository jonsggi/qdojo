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

`/run/user/1001/qdojo/*.conf` survive until reboot, not until the process
exits. After the 2026-09-19 session there were **26** of them, 20 dating from
the 2026-09-15/16 runs. They are `0600`, but they are still keys at rest.
Shred what a run created when it finishes:

    shred -u -z -n 3 /run/user/1001/qdojo/<name>.conf

Also: count before concluding one is missing. `ls -la <dir> | head -5` on that
directory shows five of twenty-six files and reads exactly like "it is not
there".

## `pkill -f` kills the shell that runs it

`pkill -f "qdojo.*bot --state"` matches the invoking shell's own command line,
which contains the pattern. The targets die, then so does the shell — exit
144 — and every cleanup step after the `pkill` silently never runs. The same
trap makes a `while pgrep -f "qdojo house .*spar"` loop immortal: it matches
itself and never sees the process end.

Kill by PID, or match on something that cannot appear in the invoking command.

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

**Status:** the native chain lives on branch `native-signer` and is **not
merged**. `scripts/crosscheck-signer.py` is its gate — run it after touching
anything under `packages/qdojo/src/qdojo/qubic/`, and note that a "reference
printed no hex" result is qubic-cli failing to reach the node, not a signature
difference.
