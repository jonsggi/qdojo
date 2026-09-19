# EVM oracle as a settlement interface

Research checked 2026-09-19. **Deferred:** the user selected challenges settled
through hash commitments for now, taking execution/oracle costs into account.
This remains a researched alternative, not the selected launch architecture,
an implemented integration or demonstrated mainnet service.

## What exists

Qubic Core [v1.304.0](https://github.com/qubic/core/releases/tag/v1.304.0),
published 2026-09-09 for epoch 230, added reading from EVM blockchains.
The generic
[EvmLogRead interface](https://github.com/qubic/core/blob/9896264e9de2224bd30be71248eeba9077b56203/src/oracle_interfaces/EvmLogRead.h)
queries `(chainId, txHash, receiptLocalLogIndex)` and returns the emitting
address, topics and raw data of a single event. It does not execute a checker,
interpret event meaning or validate the truth of an arbitrary emitted score.

The inspected interface lists Ethereum, Optimism, BSC, Polygon, Fantom, Base,
Avalanche, Arbitrum and Sepolia. Actual availability depends on oracle-machine
configuration and quorum service; inclusion in the interface is not an
end-to-end availability test. Its fee is 1,000 QU per query and its event-data
capacity is 256 bytes, plus up to four topics.

The
[reference service](https://github.com/qubic/oracle-machine/blob/d385397f6513adfe6101001b772e3adf7d2be902/oracles/read_evm_log/read_evm_log_service.py)
retrieves receipts through configured RPC providers and requires their
normalized replies to agree. It checks the finalized head by default; optional
per-chain configuration instead permits a confirmation-depth policy. Provider
errors/disagreement cause abstention. The supported chain's finality policy,
provider configuration and Qubic oracle quorum are part of the trust model.
This is not a Qubic light-client proof of EVM execution.

## Candidate design

Keep NFT careers, entries, commitments, ranking rules and QU custody in the
Qubic dojo contract. Build a fixed integration with the existing oracle and
an event format for verified challenge results.

An EVM checker validates a submitted solution and computes its score before
emitting the result event. New challenge families can deploy new approved EVM
checkers without replacing the Qubic contract, provided the initial Qubic
design includes a controlled registry and a stable result interface. Every
round pins its chain, checker/emitter identity and immutable version before
entry; a proxy or mutable dependency must not silently change active rules.

The result must bind the dojo deployment, round, fighter, challenge digest,
solution digest and checker version to its validity and score. The Qubic
consumer verifies the oracle status, chain, emitter, event signature and all
bindings against its actual round/entry state, and consumes a result only once.
The EVM checker must compute the digests of the data it actually checks rather
than merely echoing caller-provided hashes.

Relay revealed solutions to the EVM checker, then import its finalized result
through EvmLogRead. House-sponsored relaying can keep EVM gas and wallets out
of the player flow; permissionless relay support avoids making the house the
only path to completion. Race order remains based on Qubic commitment ticks,
with separate deadlines for reveal and verification. Local preview scores
must be distinguished from settled results.

A checker that simply lets the house emit a score preserves trusted house
judging; the oracle does not upgrade it into independent computation. Heavy
code execution still needs a suitable bounded verifier or execution-proof
system on the EVM side. This architecture changes where verification happens
and how families are added; it does not remove verification work.

## Engineering checks before selection

- Demonstrate a route/schedule checker accepting a valid solution and rejecting
  invalid solutions and fabricated claimed scores.
- Exercise the full event-to-Qubic path with wrong emitters, wrong challenge
  and solution bindings, duplicate events, late/missing results and retries.
- Confirm the chosen network is actually served by quorum, inspect its
  finality policy, and measure settlement latency.
- Measure EVM gas and Qubic query costs against small entry fees. Consider
  batch result commitments only with explicit completeness, input-binding and
  per-entry proof rules; a Merkle root alone proves neither truth nor completeness.
- Compare all verification expenses against retained house rake after author,
  shareholder and developer allocations. Include Qubic execution/state fees,
  failed query attempts and relaying, and set cost/retry budgets. The numerical
  example in `model.md` shows why even one query per small round may be too
  expensive under the existing illustrative rake parameters.
- Keep oracle failures distinct from player failures. Specify bounded retry,
  cancellation/refund and season/cup progression behaviour before release.

No live queries, transactions or deployments were performed during this research.
