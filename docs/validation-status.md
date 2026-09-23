# Combat candidate 1 — validation status

Updated 2026-09-22 for the specification begun 2026-09-21.
This is a record of local checks, not the release acceptance report required
by [model.md](model.md).

## Passed during documentation work

- Hand-derived combat vectors in [combat.md](combat.md).
- 1,980 paired boundary/side-symmetry checks in the executable specification aid.
- Frozen SHA-256 context/state/commitment fixture consistency.
- Active Markdown links and Markdown-vs-JSON damage matrix agreement.
- Repository suite: 676 Python tests passed, 2 skipped; 65 browser tests passed.
- Whitespace error check for tracked edits.

The repository suite mainly verifies existing legacy behavior. It does not
establish that production combat, the matcher, money state machine or contract
are implemented.

Candidate ruleset digest:
`12085c86a61ffd106430b6690acbd522c5a94f90ed8024585817f4939fe4842c`.

The reference and commands are in [reference/combat_v1.py](reference/combat_v1.py)
and [the handoff](../GPT6_HANDOFF.md). Frozen protocol data is in
[fixtures/commitment-v1.json](fixtures/commitment-v1.json).

## Illustrative NPC smoke run

200 seeds per pairing, each repeated with fighter slots swapped: 400 fights
per row, 2,400 total. The policies are deliberately simple; turtle never attacks.
Score is win=1/draw=0.5/loss=0 from the first named policy's perspective.

| Pair | W / D / L | Score | Reached third round |
|---|---|---:|---:|
| random / jabber | 96 / 16 / 288 | 0.260 | 96.0% |
| random / turtle | 400 / 0 / 0 | 1.000 | 97.0% |
| random / kicker | 94 / 22 / 284 | 0.263 | 84.5% |
| jabber / turtle | 400 / 0 / 0 | 1.000 | 100.0% |
| jabber / kicker | 400 / 0 / 0 | 1.000 | 0.0% |
| turtle / kicker | 0 / 0 / 400 | 0.000 | 100.0% |

This demonstrates reproducibility and some easily exploited behavior.
It does NOT demonstrate viable competitive diversity, opponent learning,
optimal play or acceptable competitive pacing. In particular, the fixed
jabber/kicker matchup ends in round zero throughout this sample, and the
defensive turtle is intentionally weak. Do not hide those results or use
this pool as the competent-policy pool for release thresholds.

## Not yet established

Independent C++/browser parity; full property campaign; advanced/adaptive
policy performance and ablations; best-response exploit search; economic
sustainability; real contract cost/capacity; network timing; ownership/ABI/
refund behavior; partial-tick reserve-outage protection; live migration;
external player engagement or willingness to pay.

Implementation must complete the P0–P8 work packages and acceptance gates.
A parameter change requires a new candidate/digest, revised fixtures and
appropriate reevaluation. No paid activation is authorized by this report.
