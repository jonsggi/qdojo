# AUD-012 — LLM bots forfeited by reusing a spent power strike

- **Status:** Fixed in `0918949` (deployed 2026-09-25)
- **Priority:** P0 — fair play
- **Type:** Bot correctness
- **Evidence:** All 109 QWEN-235 and 62 GEM-LITE forfeits/double faults were reveals rejected with "power strike already spent"
- **Scope:** `combat/bot.py`, `combat/llm_planner.py`, `combat/planner.py`

## Finding

No plan was validated against the fighter's state before commit, and the LLM prompt did not say plainly that power was gone ([simulation audit](../reports/2026-09-25-simulation-audit.md) §1.3).

## Acceptance criteria

- [x] `planner.legal_plan()` validates every plan with the engine's own `validate_plan`; a spent power slot is dropped, other illegal plans fall back.
- [x] The LLM prompt states power is spent and `power_slot` must be -1.
- [x] Soak: 0 power forfeits in 52 contests against 6 in 8 before.

**Source:** [2026-09-25 combat review](../reports/2026-09-25-simulation-audit.md).
