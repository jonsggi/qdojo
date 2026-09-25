# Contributing

> **Purpose:** how to set up, test and change QDOJO without breaking its guarantees. \
> **Audience:** contributors, human or agent. \
> **Status:** guide. \
> **Last verified:** 2026-09-25

## Set up and test

```sh
uv sync            # or just run any `uv run …` command
make hooks         # pre-commit: blocks staged seeds, runs `make test`
make test          # Python tests, web unit tests, C++ engine and contract parity
make web-e2e       # headless browser suite (needs a cached Playwright Chromium)
make soak          # demo-arena soak, invariants checked every tick
make test-all      # all of the above
python3 docs/reference/check_docs.py   # doc links, rules matrix vs combat-v1.json
```

`make test` needs `uv` and Node; the C++ parity checks run when `g++` is present
and are skipped otherwise. The Qubic Core targets (`make qubic-verify`,
`qubic-core-test`, `qubic-core-syntax`) clone and build Core under
`/tmp/qdojo-qubic` and are slow; see `contracts/qubic/README.md`.

Published commands are tested: every `qdojo …` line in fenced blocks of
`README.md`, `docs/api.md`, `docs/protocol.md` and `apps/web/llms.txt` is fed to
the real argument parser (`packages/qdojo/tests/test_docs_commands.py`).

## Rules for changes

The normative documents ([docs index](README.md)) govern new work. Riddle code
is supported Legacy until explicitly retired.

- Keep core combat, protocol, matcher, rating and accounting pure with explicit
  state/tick inputs. No I/O, random damage, wall-clock ordering or float arithmetic.
- Test meaningful behavioral boundaries, especially simultaneous resolution,
  money conservation, wrong-context commitments and missing reveals.
  Use hand-derived expected vectors and independent implementations.
- Run relevant checks and `make test` before every commit. Document measured
  results; do not mark planned acceptance gates passed.
- Preserve byte-verified native signing. Changing qdojo.qubic crypto requires
  the existing reference signer crosscheck and authorization for any live query.
- Native transport is the default. A new contract call needs frozen byte vectors
  and a native implementation, not an implicit shell-out to qubic-cli.
- Parser/documentation tests must track both current instructions and labelled
  legacy examples. Never publish a planned command as runnable.
- Keep secrets in protected local configuration/journals, never argv, stdout,
  logs, exports or git. Planner subprocesses receive no signer secrets.
- Money-moving tools require readable plans and explicit live-action intent.
  Documentation/spec work does not authorize deployment, minting or transfers.
- Update the owning doc with behavior changes, along with API/protocol/artifact
  and fixtures when applicable. Candidate balance changes get new versions.
- Keep the arcade visual direction. New animations are trace presentations and
  cannot decide a hit, delay combat or fabricate a forfeit knockout.
- Label legacy and combat state/data explicitly; do not migrate financial
  obligations or ratings by reinterpretation.
