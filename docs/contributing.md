# How we work here

- **Tests first.** A behaviour exists when its test exists. `make test` is
  green before every commit, and the pre-commit hook runs it.
- **Pure core, thin edges.** Hashing, payloads and round evaluation are pure
  functions with no I/O. Chain access sits behind one interface with a fake
  for tests, a native Python implementation plus indexer for real, and a
  qubic-cli one kept as the reference the native signer is checked against.
- **The signer is proven, not assumed.** `qdojo.qubic` reimplements Qubic's
  crypto. After touching anything under it, run `scripts/crosscheck-signer.py
  --node IP`: it signs real transactions both ways and compares every byte.
  Signing is deterministic, so "it verifies" is not good enough — it must be
  the same bytes.
- **Markers, not exit codes.** qubic-cli exits 0 on failure. Every wrapper
  parses stdout for the marker that proves success and treats its absence as
  failure, with an explicit timeout on every call.
- **No seed anywhere but a 0600 conf.** Never argv, never stdout, never a
  log, never git. `.githooks/pre-commit` refuses any commit that stages a
  `seed=` line or a bare 55-character lowercase token, and runs the tests;
  wire it once with `make hooks`.
- **Money moves only from a plan you can read.** `settle` prints the plan
  and sends nothing unless `--apply` is given. Applied sends are confirmed by
  tick inclusion and by balance re-read.
- **Docs are specs.** A change in behaviour changes `docs/spec.md` in the
  same commit, and anything a bot developer can see changes `docs/api.md`.
  The wire format is `docs/protocol.md`; what we have measured about the
  mechanics is `docs/model.md`.
