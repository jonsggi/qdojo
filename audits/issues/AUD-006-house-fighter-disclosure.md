# AUD-006 — Publish house affiliations and resolve the author-participation policy

- **Status:** Open
- **Priority:** P1 — product/trust gate before accepting outside stakes
- **Type:** Fairness policy / public provenance
- **Evidence:** Documentation and code reviewed; no allegation or evidence of cheating
- **Scope:** `docs/spec.md` §§1, 2, 5; `docs/PHASE-ZERO.md` “State at closeout”; `packages/qdojo/src/qdojo/house.py:170`, `:212`, `:608–624`; `packages/qdojo/src/qdojo/round.py:294–323`

## Finding

The spec says an author's identities never play its authored rounds, while also
allowing house fighters to fill seats. The closeout says the house and all 18
fighters belong to the same operator. This was an operator-owned sparring cohort,
not evidence of independent public adoption; the docs provide that context but
the spectator roster does not.

`house_fighters` is kept in private round metadata and excludes those stakes from
seed matching. The public round export does not include that affiliation list.
The winner-selection path does not exclude house fighters merely because they
are in that list. Funding affiliation and answer-author access are distinct
facts and should not be conflated.

## Impact

Outside entrants cannot readily distinguish operator-funded opponents, independent
participants, or identities with potential access to authored answers. A salted
answer commitment prevents one kind of goalpost change; it does not prevent an
author sharing an answer with an affiliated fighter.

## Acceptance criteria

- [ ] Specify whether operator-funded bots may win outsider-funded pots, and separately whether answer authors/identities with answer access may participate.
- [ ] Reconcile that decision across the specification, CLI behavior and closeout/sparring documentation.
- [ ] Publish per-round affiliation snapshots and match-eligibility data, with clear “house/sparring” badges on fighter cards and results.
- [ ] Bind the relevant policy and affiliations into published evidence and the future on-chain rules; identify what still relies on operator disclosure.
- [ ] Enforce the chosen eligibility policy in the pure evaluator with tests for affiliated, author-associated and independent fighters.
- [ ] Label the historical operator-owned cohort accurately without rewriting old settlement hashes or implying those rounds were independent public contests.

**Related:** [AUD-007](AUD-007-live-pot-matching.md), [AUD-008](AUD-008-verification-scope.md).
