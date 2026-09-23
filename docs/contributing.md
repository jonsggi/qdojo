# Contributing during the combat pivot

The [combat specification](spec.md) and [pivot plan](pivot-plan.md) govern new
work. Current riddle code is supported legacy behavior until explicitly migrated.

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
