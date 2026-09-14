# How we work here

- **Tests first.** A behaviour exists when its test exists. `make test` is
  green before every commit, and the pre-commit hook runs it.
- **Pure core, thin edges.** Hashing, payloads and round evaluation are pure
  functions with no I/O. Chain access sits behind one interface with a fake
  for tests and a qubic-cli plus indexer implementation for real.
- **Markers, not exit codes.** qubic-cli exits 0 on failure. Every wrapper
  parses stdout for the marker that proves success and treats its absence as
  failure, with an explicit timeout on every call.
- **No seed anywhere but a 0600 conf.** Never argv, never stdout, never a
  log, never git. `bin/audit-secrets` style scanning is on the roadmap.
- **Money moves only from a plan you can read.** `settle` prints the plan
  and sends nothing unless `--apply` is given. Applied sends are confirmed by
  tick inclusion and by balance re-read.
- **Docs are specs.** A change in behaviour changes `docs/spec.md` in the
  same commit.
