# Public data

What the static site reads. Every file here is a public view; contract state
and confirmed actions decide combat, never these files.

| Path | What | Written by |
|---|---|---|
| `combat/v1/` (served, not committed) | The live combat export: `manifest.json`, `index.json`, `book.json`, `fights/`, `fighters/`, `events/`, `rulesets/`, `npcs.json`, `results.json`, `cups.json`, `duels.json`, `seasons.json`, `titles.json`, `market.json`, `economics.json`, `nfts/`. Schemas: [api.md](../../../docs/api.md) §3 | `qdojo combat live` (served by `qdojo combat api`) |
| `combat/v1/sample/` | A devnet sample the site falls back to when no `manifest.json` is found | `scripts/combat-sample-data.py` |

In production nginx
proxies `/data/combat/v1/` to the live arena's data server and serves this
recorded sample only when that server is unreachable (the site then says the arena is offline). A live export is never committed.
See [operations.md](../../../docs/operations.md) §8.

Missing or lagging data is unknown, never proof that a bot did not act.
