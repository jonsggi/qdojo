# AUD-026 — Full history needs a read model, not static files

- **Status:** Open
- **Priority:** P1 — product foundation
- **Type:** Architecture
- **Evidence:** The site keeps the 200 most recent fights as static JSON; fighter pages, form and scouting are limited to what is still published
- **Scope:** Exporter, data server, site

## Finding

Static files with retention cannot serve full-history stats, pagination, seasons or search ([product review](../reports/2026-09-25-product-review.md)).

## Acceptance criteria

- [ ] A SQLite or Postgres read model fed from the event journal, rebuildable at any time.
- [ ] A small read API for fighters, fights, seasons and search; the chain or contract stays the source of truth.
- [ ] The site reads the API with the static export as fallback.

**Source:** [2026-09-25 combat review]([product review](../reports/2026-09-25-product-review.md)).
