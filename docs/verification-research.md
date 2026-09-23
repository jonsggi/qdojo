# Verification direction after the combat pivot

Combat-v1 is designed for direct deterministic contract execution.
The contract receives hidden-plan commitments and reveals, executes bounded
integer combat, and credits the result. No external oracle, EVM judge,
arbitrary verifier runtime or bot code execution is required.

[protocol.md](protocol.md) specifies byte/hash/state and timing rules.
[api.md](api.md) defines independent replay checks and evidence levels.
Hash agreement alone does not establish correct combat or confirmed payment.

The [earlier EVM/oracle research](archive/riddle-v0/docs/verification-research.md)
is preserved as deferred historical work. It is not an implementation dependency.
Platform primitives and actual costs still require a pinned Core commit,
conformance testing and worst-case execution/state measurements.
