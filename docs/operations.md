# Operating QDOJO combat

> **Purpose:** runtime authority, the production runbook for paid play, and the runbook for today's public demo arena. \
> **Audience:** operators. \
> **Status:** guide. §1–7 are the planned production runbook and are not in effect (nothing is deployed). §8 describes the demo arena that runs today. \
> **Last verified:** 2026-09-26 (§8 against the systemd units, `combat/live.py`, `combat/devnet.py`, `combat/store.py` and the `Dockerfile`)

The riddle deployment is documented in
[the historical runbook](archive/riddle-v0/docs/operations.md). Do not run
legacy house settlement against a combat state directory.

## 1. Runtime responsibilities

| Component | Authority |
|---|---|
| Qubic combat contract | Accepted actions, rules, deadlines, outcomes, escrow/credits, ratings and locks |
| Owner bot scheduler | Spending decisions, private plans/salts, authorized submissions |
| NPC service | Disclosed practice/exhibition policies; same limited observation as player |
| Indexer/exporter | Confirmed public copies and archival availability; no adjudication |
| Website/replay | Presentation and independent checks; no consensus authority |
| Operator monitoring | Reserve/capacity/availability and alerting; cannot choose winners |

Keep independent network/contract namespaces. Manifest mismatch fails closed.
Display legacy and combat activity distinctly; a static riddle snapshot is not
live combat data.

## 2. Before enabling paid admissions

Complete the acceptance report, pinned Core/ABI vectors, balance/cost evidence,
registry/rights/ownership tests, audit dispositions, custody reconciliation,
release manifest, public timing/fees and incident rehearsal. Confirm all balances
against live state, not stored display numbers. Configure reserve alerts with
capacity for peak settlement and failures.

Production values are explicit; no developer fixture implicitly becomes a
production fee or recipient. Publishing/minting/funding/deploying remains a
separately authorized release action.

## 3. During operation

Monitor execution reserve, service-generation changes, queue capacity/age,
active fight capacity, commit/reveal inclusion delay, protocol faults, nonce
conflicts, exporter lag, replay availability, withdrawal backlog and liabilities.
Break down population/results by independent fighters, known affiliation and NPC.

At every accounting checkpoint compare contract balance with liabilities and
record excluded execution-reserve capital. Don't report credited winnings as
withdrawn money. Never re-send a payout just because an indexer lacks a receipt.

Store private salts/plans before commit. Protect seed/config files with existing
platform-specific protections; no keys in argv, logs, exports or repositories.
Planner subprocesses do not receive signing secrets.

## 4. Incidents

- **Bot/model failure:** use configured fallback before commitment if possible;
  after commitment reveal the exact persisted plan. Stop future spending.
- **Indexer/site failure:** read confirmed contract state; restore exports.
  It does not pause fights or excuse a timeout.
- **Chain produces no ticks:** tick deadlines remain unchanged.
- **Contract-service gap/reserve exhaustion:** protocol generation changes;
  affected unfinished objects void/abort with defined refunds. Restore reserve
  using authorized house capital; do not take player escrow.
- **Bad release/configuration:** stop NEW admissions. Preserve accepted profiles
  and finalized credits. A maintenance flag cannot rewrite winners.
- **Evidence unavailable:** show unavailable and repair archive; never substitute
  "hash matched" for independent verification.
- **Withdrawal transfer failure:** preserve/restore credit according to tested
  platform semantics; retry idempotently after identifying the failure.

Protocol owns the exact service-gap rule. Do not invent an off-chain
"infrastructure failure" classification that selectively cancels losses.

## 5. Capacity and cups

Reserve event capacity before check-in; apply the fixed whole-level postponement
rule if necessary. New queue admissions cannot consume already reserved event
capacity. Expired/invalidated offers release money and locks once.
Full capacity is an admission error, never a reason to delete credits.

Archive accepted inputs and replays redundantly before old event-ring entries
roll over. Preserve current root/sequence evidence so exports can be checked.
Historical availability has its own uptime/retention report.

## 6. Legacy closeout

Inventory every old open round, payout intent, bond, carry amount and owner
before migration. Keep the original versioned records and balances until an
explicit closeout plan reconciles them. Don't infer "unreleased externally"
means the operator's historic funds/transactions do not exist.

No riddle rank, solve point, bond progress or historical payout is automatically
converted into a combat rating, season score, power upgrade or combat purse.
State migrations are reviewed, dry-run and reversible before any live action.

## 7. Documentation and publication

The new agent briefing is unsigned until separately published. Preserve the old
signed briefing in the archive; do not retain its provenance marker on changed
text. Public deployment must update help, API examples and frontend data together.
Check native/Windows onboarding against actual shipped combat commands, rather
than rebranding the old ./dojo riddle flow.

## 8. The public demo arena (simulated chain)

Until a Qubic deployment exists, qdojo.jonsggi.com shows a demo arena. It is
the reference contract on a simulated chain, with fake QU, simulated fighter
NFTs and operator-run demo bots, labelled as such on every page.

| Piece | Where |
|---|---|
| Arena runner | systemd user unit `qdojo-combat-live` on the ops host: `qdojo combat live --profile demo --tick-seconds 1.5 --export-every 6` from the `~/src/qdojo-live` checkout, under `infisical run` so LLM bots get their OpenRouter key from the environment |
| Arena state | `~/.qdojo/combat/arena/` (devnet journal, devnet.json with the manifest values, `snapshot.pickle` and `snapshot.prev.pickle`, assets.json, chain.json, market.json, bot plan journals) |
| Lineup | `~/.qdojo/combat/lineup-arena.json` (label, policy / planner / llm, founding, cups, duels, ranked, reliability); without `--lineup`, eight built-in demo bots |
| Public export | `~/.qdojo/combat/public/combat/v1/`, written by the runner every few ticks |
| Read API + data server | systemd user unit `qdojo-combat-api` ([deploy/systemd/qdojo-combat-api.service](../deploy/systemd/qdojo-combat-api.service)): `qdojo combat api` on the tailnet (100.101.145.63:8790). It follows the arena journal into `~/.qdojo/combat/readmodel.sqlite` (plus a private `readmodel.replica` snapshot), answers `/api/v1/` ([api.md](api.md) §3.2) and serves the export on every other path. It replaces `qdojo-combat-data` (the plain `http.server`) |
| Site | Dokploy builds `Dockerfile`; nginx proxies `/data/combat/v1/` to `QDOJO_LIVE_DATA` (falling back to the baked copy) and `/api/v1/` to `QDOJO_LIVE_API` (answering a JSON 503 when it is down, so the site uses the static files) |

The `demo` profile differs from the specified development values so a small
bot population keeps fighting and seasons turn over quickly: 2,400-tick epochs
(about an hour at 1.5 s per tick, so a four-epoch season lasts about four
hours), up to 6 rated starts per pair per epoch (specified: 2) and a 60-tick
rematch gap (specified: 120). Since 2026-09-26 a new demo arena allows 3
rated starts per pair and epoch instead of 6, and gets
stake tiers of 5,000 and 20,000 fake QU and a 1,000 bps fee profile for cup
entries, so rake covers the simulated execution cost
([economics report](economics-report.md), [product decisions](product-decisions.md#demo-arena-economics-2026-09-26)).
The export's manifest and deployment label say which profile produced the data.

A devnet records its manifest values in `devnet.json` when it is created and
replays with those, so changing a profile default in `combat/devnet.py` never
changes an existing arena. An arena created before 2026-09-26 has no recorded
values and replays with the old demo values (`LEGACY_PROFILES`: one 1,000 QU
tier). New values therefore need a fresh arena. The commit and reveal windows
are `devnet.DEMO_TIMING`, or `qdojo combat live --timing C,R` for a new arena;
cup level windows follow from them.

Event prices are host-side and apply on the next restart, relative to the
arena's tier-1 stake (`live.EVENTS`): duel stakes 1×, 2× and 3× the tier for
SINGLE, BO3 and BO5; cup entry 2×; cup sponsorship 0.1×, withheld while one
fighter won more than 2 of the last 6 sponsored cups. Ranked bots enter cups
unless their lineup entry says `"cups": false`. Demo bots decline duels from a
challenger rated more than 200 above them, or one they won less than a third
of at least 3 series against, and apply the same filters before they
challenge; the arena picks a pair and the challenger's bot decides (lineup keys `duel_max_rating_gap`,
`duel_h2h_series`, `duel_h2h_min_score`, `duel_max_stake`).

**Restarts and memory (AUD-024).** Every 600 ticks the arena compacts finished
fights, contests, offers and cups out of the contract's memory
(`store.compact`); per-fighter records, each fighter's last fights and late
budget settlements stay exact. Every 1,200 ticks (30 minutes) it writes a
state snapshot after a `digest` checkpoint in the journal. A restart loads
the newest snapshot that verifies (journal prefix SHA-256, code fingerprint,
manifest, payload hash, event digest, invariants) and replays only the
journal after it; otherwise the previous snapshot, otherwise the whole
journal. The log's first line says which: `restored at tick N by snapshot
snapshot.pickle in 2.1 s` or `by full replay … (skipped: …)`. Deleting the
snapshots is always safe: the next start replays the journal and writes a new
one. A new code version never loads an old snapshot (its fingerprint
differs), so the first restart after a deploy is a full replay.
`scripts/combat-restart-bench.py` measures both on a copy of the arena.
The read API (`qdojo combat api`) follows the same journal with its own,
never-compacted contract copy: it checks each `digest` checkpoint (a
mismatch stops its sync with `replica diverged`, and it keeps serving the
last good database), applies market payments (`xfer`), and replays with the
manifest recorded in devnet.json. An API from before 2026-09-26 does not know
these record kinds: deploy the API together with the arena.

**Export checks (AUD-025).** Every tenth export is checked against the contract
(`invariants.check_export`). A problem appears in the log as `export
invariant: fight N …` (a live fight published past its deadline, or a
finished fight not published final). The site then shows "DEADLINE PASSED";
restart the unit, which rewrites every non-final fight file.

**Market (AUD-023).** Owners of idle, non-founding fighters list them now and
then; simulated collectors bid around a value from rating, record and
experience, and buy when the bid meets the ask. The buyer pays the ask, the
seller gets it less a 250 bps market fee that goes to the house. Listings and
sales are in `market.json` next to `economics.json` (per-tier expected value,
event prices, the house's running P&L) in the public export.

The chain is `SimChain`: transactions land 1–3 ticks later, about 2% are
dropped, execution fees burn a reserve the operator tops up, and fighter NFTs
come from the simulated `AssetRegistry`, with the simulated market above.

**Read model.** The API's first start replays the whole journal (measured
2026-09-26: 199,182 records, 5,223 fights, about 4 min on this host, 95 MB
RSS, a 27 MB database); until then `/api/v1/` answers 503 `not_ready` and
the site uses the static export. Later starts resume from the snapshot. To
rebuild from scratch, stop the unit and run `qdojo combat readmodel rebuild
--devnet … --db … --export …`, or start it once with `--rebuild`. When the
arena directory is moved aside for a rules change, the API notices the new
journal and re-indexes by itself.

**Outside builders (off by default).** [build-a-bot.md](build-a-bot.md) §8
describes the builder's side. Three switches, all off today, because opening
a public write path and choosing quotas are operator decisions:

1. the arena: `--join-inbox ~/.qdojo/combat/arena/inbox.sqlite` on
   `qdojo combat live` (drains registrations and signed transactions into
   `SimChain` each tick, and flushes the journal every tick so remote bots
   see fresh state);
2. the API: the same `--join-inbox`, plus `--join-config` with a JSON file of
   `combat/join.py` `Limits` fields (outside-fighter cap, fake-QU grant,
   attachment cap, per-key burst, rate and daily quota, global inbox size);
3. the public proxy: `QDOJO_JOIN_OPEN=1` in the Dokploy environment (nginx
   otherwise answers 403 `join_closed` to every non-GET under `/api/v1/`).

[deploy/systemd/join.conf.example](../deploy/systemd/join.conf.example) has
the drop-ins. Outside fighters are listed in `arena/outside.json` and stay
labelled `outside` even after joining is switched off; their bots simply stop
being able to send. No builder code runs on the host.

**Client addresses** (for the per-IP write limit): nginx walks
`X-Forwarded-For` from the right through its own proxies (private ranges)
and Cloudflare's published edge ranges only, so entries a client writes
itself are never trusted; if the walk ends at a Cloudflare edge it uses
`CF-Connecting-IP`. It overwrites `X-Real-Client-IP` for the API, which reads
that header only from a peer in an exact trusted CIDR. Refresh the Cloudflare
ranges in the Dockerfile from cloudflare.com/ips when they change. Per-IP
limits are a courtesy; the per-key quotas are the real protection.

**Operate:**

```sh
systemctl --user status qdojo-combat-live qdojo-combat-api
journalctl --user -u qdojo-combat-live -n 50
systemctl --user restart qdojo-combat-live     # SIGTERM saves the journal; restart resumes exactly
```

Handling problems:
- **STALE on the site.** The runner has stopped exporting. Check the
  unit's status and log, then restart it.
- **Site shows the baked copy.** The data server or the tailnet is down.
  Check `qdojo-combat-api`, and whether the Dokploy host can reach this
  host's tailnet address.
- **Site says "recent fights only".** `/api/v1/status` did not answer for
  this network: the API is down, still indexing (503 `not_ready`), or
  pointed at another arena. `journalctl --user -u qdojo-combat-api`.
- **Stopping LLM spend.** LLM bots cap their spend per UTC day
  (`--daily-usd`) and fall back to a local policy. Removing their lineup
  entries and restarting stops all model calls.
- **Rules change.** A devnet's manifest profile and values are fixed when it
  is created; the marker refuses to reopen it under other rules. To change the
  rules, stop the unit, move the arena directory aside, and start fresh.
- **Slow restart.** The log's `restored … by full replay (skipped: …)` line
  says why no snapshot was used. After a code deploy that is expected once.
  A snapshot that fails to verify is never used; nothing needs repairing.

**Test the whole system:**

```sh
make test                                     # unit, parity (Python, C++), web unit tests
make web-e2e                                  # headless browser over every view
uv run python scripts/combat-soak.py --ticks 20000   # invariants every tick under drops, halts, churn;
                                              # then a steady phase checking every export (AUD-025)
uv run python scripts/combat-arena-metrics.py --ticks 10000   # house P&L, EV by strength, farming, ratings
uv run python scripts/combat-restart-bench.py ~/.qdojo/combat/arena --scratch /tmp/bench   # restart cost, on a copy
```
