# AUD-013 — Bots re-sent rejected entries every tick; the fault stop was disabled

- **Status:** Fixed in `0918949` (deployed 2026-09-25)
- **Priority:** P1 — unattended operation (see AUD-005)
- **Type:** Bot spending policy
- **Evidence:** QWEN-235 made 16,688 queue entries for 182 accepted; rejected entries cost about 23% of simulated fees
- **Scope:** `combat/bot.py` (`Budget`), `combat/live.py` demo profile

## Finding

Rejected commits, reveals and queue entries were retried in a tight loop, cooldown and suspension were ignored, and the demo set stop-after-faults to 10^6 ([simulation audit](../reports/2026-09-25-simulation-audit.md) §1.3, §2.1).

## Acceptance criteria

- [x] Permanent rejections are journalled and never re-sent; transient ones back off 4 to 240 ticks.
- [x] Bots read `cooldown_until` and the ranked suspension.
- [x] Demo stops a bot after 3 faults within 2,400 ticks, overridable per lineup entry.

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
