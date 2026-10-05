# Builder beta plan

> **Purpose:** the plan for a small free cohort of independent bot builders on the devnet arena: who, how they enter, the limits, what is measured, and what decides the next milestone. \
> **Audience:** the owner (who runs the beta and enables entry), the study team, and builders deciding whether to join. \
> **Status:** proposal (written 2026-10-03 for AUD-039, AUD-038 and the AUD-027 product follow-up). Nothing here has happened yet: no one has been recruited and outside entry is **off**. Every step marked **Needs owner** waits for the owner. \
> **Last reviewed:** 2026-10-03

The measurement method is fixed before recruiting, in
[validation-protocol.md](validation-protocol.md). The decision this beta
feeds is recorded in [product decisions](product-decisions.md#next-milestone-independent-builder-beta-2026-10-03).

## Contents

- [1. Goal and scope](#1-goal-and-scope)
- [2. Cohort and recruitment](#2-cohort-and-recruitment)
- [3. Entry policy and eligibility](#3-entry-policy-and-eligibility)
- [4. Limits](#4-limits)
- [5. Operator checklist: enabling entry](#5-operator-checklist-enabling-entry)
- [6. Free devnet QU](#6-free-devnet-qu)
- [7. What is measured](#7-what-is-measured)
- [8. Disclosure and privacy](#8-disclosure-and-privacy)
- [9. Support](#9-support)
- [10. Timeline](#10-timeline)
- [11. Success metrics and exit criteria](#11-success-metrics-and-exit-criteria)
- [12. Deferred work and paid-launch dependencies](#12-deferred-work-and-paid-launch-dependencies)

## 1. Goal and scope

The next milestone's audience is **independent bot builders**, with free
practice as their introduction. The beta tests one loop with real people:
**build → compete → study → revise**. It answers:

- Can someone who has never seen QDOJO get a bot into an arena fight from
  the public instructions, and how long does it take?
- Do they come back, change their planner and explain why it got better?
- Can they read a replay well enough to know what decided a fight?

It does not test willingness to pay, real-money economics or the NFT market.
The arena stays a devnet: a simulated Qubic chain, devnet QU with no monetary
value, house bots run by the operator.

## 2. Cohort and recruitment

| Item | Plan |
|---|---|
| Size | **10 independent builders** in the main cohort, plus **2 pilot** participants a week earlier (internal-adjacent, logged as `cohort_phase = pilot`) to shake out the instructions. Ten is a research target, not a statistical proof (AUD-039) |
| Who counts as independent | Has not contributed to QDOJO, is not the owner or a house-bot operator, and has not seen the code before recruitment. Contributors and the owner may take part, logged with `house_or_test = y` and excluded from every rate |
| Skills | Can run Python 3.11+ from a terminal. No Qubic, blockchain or game-AI experience required; the study wants a mix |
| Recruitment | **Needs owner.** Invitations from the owner to: the Qubic developer community, one or two bot-programming communities (e.g. CodinGame, Battlesnake, Screeps players), and personal networks. Aim for at most 3 from any one source, so one community's habits do not dominate. No paid incentive; credit in the results write-up for those who want it |
| Consent | Each participant reads §8 and agrees before the session. They may stop at any time; a dropout stays in the denominator with its reason (if they give one) |
| Pseudonyms | The study team assigns P01–P10 (reviewers R01…). The mapping from pseudonym to contact stays with the owner, outside the repository and outside the cohort log |

## 3. Entry policy and eligibility

This is the policy to publish with the beta (AUD-027 follow-up). The site's
builder page shows the entry state from the deployment (builder-journey track);
this document is the policy text it links to.

**Who may enter.** Anyone, during the beta window, on the devnet arena, by
running `qdojo combat join` ([build-a-bot.md](build-a-bot.md) §8). Cohort
participants get a heads-up; the path itself is public, so outside
non-participants may also register. They count as outside builders in the
aggregate measurements but not in the cohort log.

**One fighter per key.** A key registers one fighter, for good. Names are 3–16
letters, digits, `-` or `_`; names starting with `test-` are reserved for the
operator's smoke tests and do not count as builders. Offensive or
impersonating names are removed by the operator (the fighter stays in the
record, renamed in the site's metadata).

**The builder runs the bot.** No builder code runs on the arena host. A bot
that stops simply stops fighting; a missed reveal forfeits as on a real chain.

**Eligibility for events against house bots.** During the beta an outside
fighter may enter everything a house fighter can:

| Event | Eligible | Notes |
|---|---|---|
| Ranked queue (tiers 5,000 and 20,000 devnet QU) | Yes | Same matchmaking and per-pair caps as house bots |
| Duels | Yes, both offering and accepting | House demo bots decline challengers rated 200+ above them or ones they beat less than a third of the time (the published duel filters); attachments above 20,000 devnet QU are refused, so BO3/BO5 at tier 2 are out of reach |
| Cups | Yes | Entry fee 10,000 devnet QU; the house's cup sponsorship applies as for anyone |
| Seasons, belts, titles | Yes | Ratings, belts and titles are the arena's record; they carry no prize of value |
| Market | No new action | Outside fighters' NFTs are minted to the builder. House collectors may bid on them as on any fighter; nothing on the site can buy or sell |

**Fair play from the house.** For the cohort window the operator freezes the
ruleset (candidate 3, digest `cf19b7cf…`) and the house lineup (file hash and
bot versions recorded at the start, §5 step 1). House bots see only what the
public chain shows any bot; the operator does not tune a house bot against a
specific outside fighter. One scheduled change is part of the study: a single
house sparring bot switches style at a recorded tick in week 2 to measure
adaptation ([validation-protocol.md](validation-protocol.md) H7); it is
announced in advance as "one house bot will change style during the beta",
without the date or the new style. Any other correction (a bug fix, a rules
fix) is recorded with its tick, and results before and after are reported
separately.

**Disclosure.** Every fighter is labelled HOUSE or OUTSIDE in the export, the
API and the site. House bots are operator-run; some are LLM-driven, some are
scripted NPCs ([npcs.md](npcs.md)). The house's own P&L is published on the
economy page as a simulation.

**When entry closes.** At the end of the beta window, or earlier if §5's
rollback is needed. Outside fighters stay in the record and stay labelled
OUTSIDE; their bots simply can no longer send.

## 4. Limits

Recommended values, in
[deploy/systemd/join-limits.beta.json](../deploy/systemd/join-limits.beta.json)
(every field of `combat/join.py` `Limits`; a test checks the file loads):

| Limit | Default | Beta | Why |
|---|---:|---:|---|
| `max_outside_fighters` (all time) | 8 | **16** | 10 cohort + 2 pilot + room for a lost key or a non-participant. Each outside fighter adds ranked pairs; 36 fighters stay well inside what the arena handles today (20 fighters, ~2,000 fights a day) |
| `registrations_per_day` (global) | 10 | 10 | A whole cohort can register in one day; a script cannot fill the arena in one |
| `registrations_per_ip_day` | 2 | 2 | A retry after a mistake, not a farm |
| `grant_qu` (once per key) | 100,000 | **1,000,000** | 200 straight losses at tier 1. Devnet QU has no value; running dry mid-beta would end someone's participation for a reason the study does not care about |
| `max_amount` (per transaction) | 20,000 | 20,000 | Covers tier 2 ranked and cup entry; keeps one bad budget from staking everything at once |
| `tx_burst` / `tx_per_second` | 20 / 1.0 | 20 / 1.0 | A bot sends a few transactions a minute; the live house bots' busiest one sends ~2,700 a day |
| `tx_per_day` (per key) | 20,000 | 20,000 | Seven times a busy bot |
| `reads_per_second` (per IP) | 20 | 20 | `join` reads chain state once per poll |
| `max_pending` (all keys) | 400 | 400 | Bounds the inbox the arena drains each tick |
| `tick_behind` / `tick_ahead` | 30 / 60 | 30 / 60 | Stale or future transactions are refused with `stale` |

The per-IP limits are a courtesy; per-key quotas are the real protection
([operations.md](operations.md) §8). The arena host has two CPUs: if the API's
CPU stays above 50% with the cohort connected, halve `reads_per_second` first.

## 5. Operator checklist: enabling entry

**Needs owner.** Enabling opens a public write path, so only the owner runs
this. It uses the three switches of [operations.md](operations.md) §8 and the
drop-ins in [deploy/systemd/join.conf.example](../deploy/systemd/join.conf.example).
Commands assume the live checkout `~/src/qdojo-live` and the units as
installed on 2026-10-03.

**Preconditions** (do not start until all hold):

- [ ] AUD-029 and AUD-030 fixed and deployed (the starter planner handles
  candidate 3; the CLI, site and docs agree on the active rules), and the
  AUD-041 journey check passes against the deployment.
- [ ] The deployed code includes `/api/v1/community`
  (`curl -s https://qdojo.jonsggi.com/api/v1/community | jq .schema` prints
  `qdojo.combat.api.community.v1`). Its first start after the deploy replays
  the whole journal (code changed); wait for `caught_up`.
- [ ] A support channel exists (§9) and the invitation text links it.

**1. Record the frozen state** in the study log (not the repository):

```sh
date -u +%FT%TZ
git -C ~/src/qdojo-live rev-parse HEAD
sha256sum ~/.qdojo/combat/lineup-arena.json
curl -s https://qdojo.jonsggi.com/api/v1/status | jq '{tick: .generated_tick, join_enabled, deployment}'
jq -r .ruleset_digest ~/.qdojo/combat/arena/devnet.json     # cf19b7cf…: candidate 3
```

**2. Limits file:**

```sh
cp ~/src/qdojo-live/deploy/systemd/join-limits.beta.json ~/.qdojo/combat/join-limits.json
```

**3. Switch 1, the arena drains the inbox:**

```sh
mkdir -p ~/.config/systemd/user/qdojo-combat-live.service.d
cat > ~/.config/systemd/user/qdojo-combat-live.service.d/join.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/home/klabautermann/.local/bin/infisical run --env=dev --silent -- /home/klabautermann/.local/bin/uv run qdojo combat live --profile demo-c3 --devnet /home/klabautermann/.qdojo/combat/arena --lineup /home/klabautermann/.qdojo/combat/lineup-arena.json --export /home/klabautermann/.qdojo/combat/public/combat/v1 --tick-seconds 1.5 --export-every 6 --join-inbox /home/klabautermann/.qdojo/combat/arena/inbox.sqlite
EOF
```

If `systemctl --user cat qdojo-combat-live` shows a different `ExecStart`
than the one above, copy that one and append only `--join-inbox …`.

**4. Switch 2, the API accepts registrations and transactions:**

```sh
mkdir -p ~/.config/systemd/user/qdojo-combat-api.service.d
cat > ~/.config/systemd/user/qdojo-combat-api.service.d/join.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/home/klabautermann/.local/bin/uv run qdojo combat api --host 100.101.145.63 --port 8790 --db /home/klabautermann/.qdojo/combat/readmodel.sqlite --devnet /home/klabautermann/.qdojo/combat/arena --export /home/klabautermann/.qdojo/combat/public/combat/v1 --cors-origin https://qdojo.jonsggi.com --join-inbox /home/klabautermann/.qdojo/combat/arena/inbox.sqlite --join-config /home/klabautermann/.qdojo/combat/join-limits.json
EOF
systemctl --user daemon-reload
systemctl --user restart qdojo-combat-live qdojo-combat-api
journalctl --user -u qdojo-combat-live -n 5     # "restored at tick N by snapshot …" (a full replay if the code changed)
```

**5. Check from the tailnet before opening the proxy** (the API answers there
even while nginx still refuses writes):

```sh
API=http://100.101.145.63:8790/api/v1
curl -s $API/status | jq .join_enabled                      # true
curl -s $API/join | jq '.limits, .outside_fighters'          # the beta values; 0
curl -s -X POST $API/join/register -d '{}' | jq .error.code  # bad_body
curl -s -X POST $API/tx -d '{"tx":"00"}' | jq .error.code    # bad_tx
```

**6. Switch 3, the public proxy:** in Dokploy set `QDOJO_JOIN_OPEN=1` for the
site and redeploy. Then from outside the tailnet:

```sh
curl -s https://qdojo.jonsggi.com/api/v1/join | jq .enabled  # true
```

**7. Smoke test as a builder** from a machine that is not the arena host,
with a released checkout and the public instructions only:

```sh
uv run qdojo combat join --arena https://qdojo.jonsggi.com --name test-smoke1 --register-only
# interrupted registration: run it again; it must report the same fighter, not a new one
uv run qdojo combat join --arena https://qdojo.jonsggi.com --name test-smoke1 --register-only
# a second name from the same key is refused (one_per_key):
uv run qdojo combat join --arena https://qdojo.jonsggi.com --name test-smoke2 --key ~/.qdojo/combat/join/test-smoke1.seed --register-only
# fight until one fight finishes, then open it on the site and check VERIFIED
uv run qdojo combat join --arena https://qdojo.jonsggi.com --name test-smoke1 --npc scout-v1 --seconds 900
curl -s https://qdojo.jonsggi.com/api/v1/community | jq .fighters   # operator_tests: 1, outside: 0
```

Stop the smoke-test bot afterwards. `test-` fighters are reported as
`operator_tests` and never as builders.

**8. Record** in AUD-027: the deployment (commit, date), the limits file hash,
and the smoke test's fight ID and verified replay. The product milestone in
AUD-027 closes only after an *independent* builder completes the same journey
(a cohort participant, §11).

**Rollback** (any time; nothing is lost):

```sh
# Dokploy: QDOJO_JOIN_OPEN=0 (or remove it) and redeploy: writes get 403 join_closed at once
rm ~/.config/systemd/user/qdojo-combat-live.service.d/join.conf ~/.config/systemd/user/qdojo-combat-api.service.d/join.conf
systemctl --user daemon-reload && systemctl --user restart qdojo-combat-live qdojo-combat-api
```

Outside fighters stay in `arena/outside.json` and stay labelled OUTSIDE.

**Watch during the beta:** `journalctl --user -u qdojo-combat-live | grep outside`
(registrations issued and rejected), the API's CPU (`systemctl --user status
qdojo-combat-api`), and `/api/v1/community` daily.

## 6. Free devnet QU

- Each registered key gets **1,000,000 devnet QU once**, at registration
  (§4). Devnet QU has no monetary value, cannot be bought, sold or withdrawn,
  and does not carry over to testnet or mainnet.
- No top-ups in the normal course. There is no operator command for one; a
  builder who runs dry mid-beta registers a fresh key and fighter (the
  arena has room for that, §4), and the study log notes it.
- Winnings and losses are part of the simulated economy. They are never
  described as earnings, and the beta's results never cite them as demand.

## 7. What is measured

Two sources, both defined before recruiting:

**Aggregate arena measurements** (`GET /api/v1/community`, [api.md](api.md)
§3.2; shown as the COMMUNITY panel at the top of the site's economy page,
above a line that marks everything below it as simulated):

| Measure | Definition |
|---|---|
| Outside fighters registered | Outside fighters by arena day of issue; `test-` fighters reported separately |
| Active builders per day and week | Builder keys whose bot sent at least one included transaction that arena day / in the last seven |
| Fights by pairing | Finished fights house vs house, outside vs house, outside vs outside: total, today, last seven days, per day |
| Bot runs | A key's first transaction, and every transaction after 1,200 quiet ticks (30 minutes): a restart, usually after a planner change. A proxy for revisions, cross-checked against the cohort log |
| Week-2 return | Builders active again (and, stricter, with a new bot run) 7–13 arena days after their first active day |

These come only from public chain and arena data. They count keys, not
people, and a running bot is not a visit: human return and revisions are
measured in the cohort log, not here.

**The cohort log** ([validation-protocol.md](validation-protocol.md) §4; the
template is [fixtures/beta-cohort-template.csv](fixtures/beta-cohort-template.csv)):
one row per pseudonymous participant: start and first-fight times, assistance
needed, where and why they dropped off, starter or independent approach,
second submission, week-2 return, whether they could explain and demonstrate
an improvement, and three 1–5 survey answers. `scripts/beta-study.py cohort`
prints the aggregate, with drop-offs in every denominator.

## 8. Disclosure and privacy

What participants are told before they start:

- The arena is a devnet: simulated chain, devnet QU with no value, house bots
  run by the operator. Some house bots are driven by LLMs, some are scripts.
- Their fighter, its record and every fight are public, labelled OUTSIDE,
  forever (the record outlives the beta).
- The study records, under a pseudonym: timings, where they got stuck, what
  help they needed, their answers to the survey and the replay review. No
  name, e-mail, address or IP in the study data. The pseudonym-to-contact
  mapping stays with the owner and is deleted at the end of the beta.
- The arena measures participation only from the public chain: which key
  sent transactions when. The site has no analytics, cookies or visitor
  tracking for this.
- Results are published as aggregates (counts, rates, distributions) and
  failed cases described without identifying anyone.

## 9. Support

**Needs owner:** create the channel and put its link in the invitation.

- **Bugs and doc ambiguities:** GitHub issues on the public repository with a
  `beta` label. Every ambiguity becomes a doc fix (model.md §3).
- **Help during a session:** one private chat the owner chooses (a Discord
  channel or e-mail), answered within a working day. Every intervention is
  logged as assistance (`hint`, `hands_on`) in the cohort log, because the
  onboarding measure depends on it.
- **Status:** the site's header (LIVE/STALE) and `/api/v1/status`. Planned
  restarts are announced in the channel.

## 10. Timeline

Weeks are counted from the day entry opens (§5 done). Dates are the owner's
to set; nothing is scheduled by this document.

| Week | What |
|---|---|
| −1 | Preconditions (§5). Pilot: 2 participants run the whole journey; fix what they hit, record it as `pilot` |
| 0 | Entry opens. Onboarding sessions (observed, timed: protocol tasks T1–T3) |
| 1 | Compete and revise. Mid-week check-in; first readability review (5 reviewers, T5) |
| 2 | The scheduled house-bot style switch (H7). Week-2 return is measured from each participant's first day |
| 3 | Closing survey and interview (T6). Entry closes at the end of the week |
| 4 | Aggregate report published in [validation-status.md](validation-status.md); next-milestone decision recorded in product decisions |

## 11. Success metrics and exit criteria

The thresholds are the protocol's ([validation-protocol.md](validation-protocol.md)
§3). The beta **supports moving to the next milestone** (testnet with the
mainnet QBAY collection mirrored, [testnet.md](testnet.md)) when all of:

1. At least **7 of 10** independent builders reach a first completed arena
   fight (H2), and an independent builder has completed the AUD-027 journey
   end to end (register, fight, open a verified replay).
2. At least **half** of those who started reach it within **10 minutes**
   without hands-on help (H3; dropouts count as over).
3. Every readability reviewer identifies the cause of at least **8 of 10**
   decisive exchanges (H1, model.md §3).
4. At least **5 of 10** make a second submission and at least **6 of 10** can
   explain and demonstrate an improvement (H4, H5).
5. No blocker issue (crash, lost fight, unverifiable replay) is open.

**If not met**, the next cycle fixes what the drop-off reasons and failed
review items point at (onboarding, debrief, replay layout: AUD-032, AUD-035,
AUD-036) and runs a second cohort; testnet work continues in parallel only
where it does not change the builder's journey. Week-2 return (H6) and the
adaptation measures (H7) are reported but do not gate: ten people cannot show
retention, and model.md §2 asks for a report. Willingness to pay is not
measured and stays unvalidated whatever the result.

## 12. Deferred work and paid-launch dependencies

**Deferred for this milestone:** new market features, royalties beyond the
current simulated ledger, more collection mechanics, paid stakes, new moves
or rules (they would confound what participants learn, AUD-038). **Continues:**
contract and testnet work ([testnet.md](testnet.md)), the QBAY mirror
([nft.md](nft.md)), and fixes the cohort surfaces.

**Explicit dependencies of any paid launch**, untouched by this beta: real
Qubic execution costs and hosting/provider costs (AUD-018), player expected
value with real fees (AUD-019), the licence (AUD-028), production art and
release terms (AUD-009, AUD-010), and the hard gates of [model.md](model.md) §7.
