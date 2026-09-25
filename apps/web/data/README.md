# Public data

What the static site reads. Every file here is a public view; contract state
and confirmed actions decide combat, never these files.

| Path | What | Written by |
|---|---|---|
| `combat/v1/` | Combat export: `manifest.json`, `index.json`, `book.json`, `fights/`, `fighters/`, `events/`, `rulesets/`, `npcs.json`, `results.json`, `cups.json`, `duels.json`, `seasons.json` (the committed snapshot predates the last three). Schemas: [api.md](../../../docs/api.md) §3 | `qdojo combat live` or `qdojo combat devnet export` |
| `combat/v1/sample/` | A devnet sample the site falls back to when no `manifest.json` is found | `scripts/combat-sample-data.py` |
| `*.json`, `rounds/`, `settlements/`, `ticks/` | Legacy riddle exports and history, read by `legacy.html` | the riddle house exporter |
| `sample-*.json`, `make-sample.py` | Legacy riddle sample data | `make-sample.py` |

In production the `combat/v1/` copy committed here is only a fallback: nginx
proxies `/data/combat/v1/` to the live demo arena's data server and serves this
baked copy only when that server is unreachable (the site then shows STALE).
See [operations.md](../../../docs/operations.md) §8.

Do not reinterpret or overwrite legacy riddle files as combat data. Missing or
lagging data is unknown, never proof that a bot did not act.
