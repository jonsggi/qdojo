# Riddle catalogue and content releases

Direction agreed 2026-09-19: build an extensive, regularly extended catalogue
that rewards adapting solver scripts, tools and procedures, while keeping
settlement based on answer commitments. The 40 candidates below are a design
inventory, not implemented or individually approved generators. Suggested
belts require calibration; each live instance has one belt.

## The experience

A fighter recognises a task, interprets its rules, chooses tools, computes an
answer and checks its work. Familiar capabilities remain useful; new families,
meaningful variants and combinations give owners reasons to improve them.
AI can interpret unfamiliar tasks or build tools; deterministic procedures can
solve familiar work cheaply. Neither method is required or penalised.

Keep the solver interface stable. The interesting adaptations are better
parsing, algorithms, planning, validation and tool selection. Changing a title
or breaking the input envelope merely to invalidate scripts is not difficulty.
Every live problem must contain complete rules for its variant.

The answer can be small even when solving is substantial: repair a parser,
reconcile the resulting event stream, then return the final inventory count.
A fighter may solve the specification directly instead of repairing the code;
an output-based challenge does not prove which method was used.

## What exists

[`riddles.py`](../packages/qdojo/src/qdojo/riddles.py) has 16 classic kinds,
the default pool:

| Belt | Kinds |
|---|---|
| White | `sum_lines`, `count_letter`, `max_int`, `longest_word` |
| Yellow | `reverse_string`, `caesar_decode`, `xor_bytes`, `digit_sum` |
| Orange | `nth_prime`, `collatz_steps`, `program_output`, `recurrence_sum` |
| Green | `pow_nonce`, `prime_count`, `sha256_hex` |
| Blue | `fix_the_bug`, with seven internal templates |

The blue family already asks for the corrected function's integer output,
rather than an arbitrary patch. Brown/black content is not implemented.

The Qubic riddle pack
([`qubic_riddles.py`](../packages/qdojo/src/qdojo/qubic_riddles.py)) adds
three opt-in families, off by default and selected per spar with
`--riddle-pack qubic` or `mixed`:

| Belt | Family | Asks for |
|---|---|---|
| Orange | `qubic_transaction_audit` | a sum or count over wire-format transaction frames that pass validity and a query |
| Green | `qubic_asset_ledger` | one identity's shares of one asset after a normalized journal is replayed |
| Blue | `qubic_call_audit` | accepted audits, or refunds or credits to one identity, over nested contract-call traces |

Each carries its family name and rule version inside the hashed `input`,
which is the explicit, versioned family identity asked for below. [The pack
guide](riddle-pack.md) has the provenance, the simplifications, the candid
review of each family and the measurements on fresh instances; the belts
are provisional until live rounds exist.

[`bare.py`](../examples/solvers/bare.py) dispatches on title words, and
[`evo.py`](../examples/solvers/evo.py) caches generated tools by title shape.
These are limited baselines. Future family identities should be explicit and
versioned; tools must still understand each instance's rules. An ID alone
does not establish that an old tool handles a new variant.

## Forty candidate families and extensions

Each answer needs one defensible canonical value. Specify ordering, ties,
encoding, numeric semantics and bounds; reject ambiguous instances. Supply
the necessary data with the riddle: no live API, internet fact or LLM judge
is needed to determine the answer.

### Data and events

| ID | Task and answer | Meaningful variations | Candidate belts |
|---|---|---|---|
| DATA-01 Ledger reconciliation | Apply transactions and return an exact balance. | Reversals, duplicates, cancellation and idempotency. | White–green |
| DATA-02 Sessions | Reconstruct sessions and return a count or duration. | Gap rules, boundary inclusivity and equal-time ordering. | Yellow–blue |
| DATA-03 Record reconciliation | Resolve conflicting versions; return a field. | Tombstones, version precedence and duplicate handling. | Yellow–blue |
| DATA-04 Historical query | Join tables at a stated logical time; return an aggregate. | Time ranges, missing data and deterministic tie rules. | Orange–brown |
| DATA-05 Units and clocks | Normalise quantities/timestamps; return an integer total. | Rational arithmetic, stated calendars, fixed offsets and exact rounding. | White–green |

### Parsing and encodings

| ID | Task and answer | Meaningful variations | Candidate belts |
|---|---|---|---|
| PARSE-01 Escaped records | Parse records under a supplied grammar; return an aggregate. | Quoted separators, empty fields and embedded newlines. | White–green |
| PARSE-02 Binary frames | Decode supplied hex; return a field or checksum. | Byte order, signedness, bit fields and length prefixes. | Yellow–blue |
| PARSE-03 Nested compression | Interpret bounded repetition; return a character or count. | Nested runs and avoiding full expansion. | Orange–brown |
| PARSE-04 Fragment assembly | Reassemble uniquely ordered fragments; return a compact field. | Overlaps, duplicates and checksums. | Yellow–blue |
| PARSE-05 Expression grammar | Evaluate an expression under declared semantics. | Precedence, associativity, custom operators and bounded integers. | Orange–brown |

### Debugging and behaviour

| ID | Task and answer | Meaningful variations | Candidate belts |
|---|---|---|---|
| DEBUG-01 Repair and evaluate | Correct behaviour to match the specification; return the output for supplied calls. | Boundary, state and mutation bugs beyond current blue templates. | Orange–black |
| DEBUG-02 First divergence | Compare implementations on a supplied stream; return the first divergent step. | Overflow, stale state and off-by-one errors. | Green–brown |
| DEBUG-03 Smallest counterexample | Find the least failing input in a finite domain with an explicit total order. | Exhaustive/symbolic search and interaction bugs. | Green–black |
| DEBUG-04 Patch selection | Select the first candidate satisfying a complete bounded specification. | Interacting edits, explicit candidate order and misleading examples. | Orange–brown |
| DEBUG-05 State leakage | Correct reset/update behaviour; return the final observable value. | Aliasing, caches and multiple calls in a stated order. | Blue–black |

### Graphs and dependencies

| ID | Task and answer | Meaningful variations | Candidate belts |
|---|---|---|---|
| GRAPH-01 Shortest journey | Return exact minimum cost in a bounded graph. | Directed edges, allowed weight ranges and unreachable sentinel. | Yellow–blue |
| GRAPH-02 Dependency order | Return lexicographically first topological order or the defined cycle marker. | Disconnected components, duplicate edges and label ordering. | Orange–blue |
| GRAPH-03 Critical connections | Count vertices/edges whose removal meets a stated connectivity condition. | Directedness and disconnected-input conventions. | Green–brown |
| GRAPH-04 Transport capacity | Return exact maximum flow in a bounded network. | Parallel edges, zero capacity and interacting bottlenecks. | Green–black |
| GRAPH-05 Routes with state | Return minimum steps with keys, switches or limited resources. | Resource-dependent movement and bounded state-space search. | Blue–black |

### Exact finite optimisation

These ask for a fixed optimum established before play, not the best arbitrary
solution submitted by a deadline. Bound sizes so independent reference methods
can establish an exact answer. Approximate results or reference timeouts are
not acceptable published optima.

| ID | Task and answer | Meaningful variations | Candidate belts |
|---|---|---|---|
| OPT-01 Packing value | Return the exact best value under capacity constraints. | Zero/one versus bounded quantities; small multidimensional cases. | Orange–brown |
| OPT-02 Assignment cost | Return exact minimum cost matching workers and jobs. | Forbidden pairs, eligibility and explicit infeasibility handling. | Green–brown |
| OPT-03 Compatible bookings | Return maximum total weight of compatible intervals. | Endpoints, setup gaps and bounded resource counts. | Orange–brown |
| OPT-04 Production plan | Return minimum completion time for a small job set. | Dependencies, machine restrictions and exact bounded search. | Blue–black |
| OPT-05 Cheapest configuration | Return least component cost satisfying finite rules. | Compatibility, capacity and interacting constraints. | Blue–black |

### Deterministic simulations

| ID | Task and answer | Meaningful variations | Candidate belts |
|---|---|---|---|
| SIM-01 Queue discipline | Return a finish time or total wait after simulating arrivals/service. | Explicit ordering for simultaneous events and priority rules. | Yellow–blue |
| SIM-02 State machine | Apply a transition table; return terminal state or count. | Guards and explicit missing-transition behaviour. | White–green |
| SIM-03 Evolving grid | Advance a bounded cellular system; return a count or compact region. | Boundaries, update order and cycle detection. | Orange–brown |
| SIM-04 Retry protocol | Replay a supplied delivery schedule; return final application state. | Duplicates, acknowledgements and bounded retries. | Green–black |
| SIM-05 Inventory process | Apply reservations, expiry and fulfilment; return available quantity. | Rollbacks and precise logical-time ordering. | Yellow–brown |

### Language and rules

Language must communicate precise rules. Generate from an explicit semantic
model and review renderings for ambiguity. Model-based interpretation may help;
there is still a fixed answer and no subjective grading.

| ID | Task and answer | Meaningful variations | Candidate belts |
|---|---|---|---|
| RULE-01 Policy precedence | Apply a supplied policy; return a decision code. | Exceptions, defaults and explicit rule precedence. | Yellow–blue |
| RULE-02 Transformation instructions | Interpret a bounded prose procedure and return its result. | Operation order, branches and translation into reusable tools. | Yellow–brown |
| RULE-03 Alias resolution | Resolve identities under explicit evidence rules; return a label. | Alias graphs, conflicts and stated priority. | White–green |
| RULE-04 Logical consequences | Decide whether a statement follows from finite facts/rules. | Cycles and explicit closed/open-world semantics. | Orange–brown |
| RULE-05 Plan from a brief | Return a canonical shortest action sequence in a finite world. | Constraint extraction; shortest-then-lexicographic ordering. | Blue–black |

### Combined missions

| ID | Task and answer | Meaningful variations | Candidate belts |
|---|---|---|---|
| MIX-01 Migration and query | Apply schema migration, then return a query result. | Compose transforms/joins with explicit null/default rules. | Green–black |
| MIX-02 Repair and reconcile | Diagnose a broken parser, then reconcile its corrected event stream. | Combine debugging, accounting and intermediate validation. | Blue–black |
| MIX-03 Decode and execute | Decode a representation, then return a bounded program's result. | New combinations of known encodings and execution semantics. | Green–black |
| MIX-04 Identify and apply | Identify a unique rule from a finite candidate set, then apply it. | Distinguishing examples; generator checks unique identification. | Orange–brown |
| MIX-05 Incident reconstruction | Use logs and an explicit causal model to identify an earliest fault and resulting state. | Join traces and simulate causes; ensure a unique requested diagnosis. | Blue–black |

## Useful reasons to adapt a fighter

Distinguish four content changes:

1. **Fresh instance:** new data under unchanged rules. A good general tool
   should already handle it; this supplies routine play.
2. **Rule variant:** explicit changes to reversal semantics, eligibility,
   escaping or interval boundaries. Tools must check their assumptions.
3. **New family or composition:** another capability or combination encourages
   better tool-building and selection.
4. **Compatibility change:** a different envelope/answer format is a software
   migration with notice and fixtures, not a surprise puzzle mechanic.

For example, extend a ledger family from deposits/withdrawals to reversals,
then duplicate delivery with explicit IDs, then a mission requiring parser
repair before reconciliation. This creates engineering work beyond bigger inputs.

Keep established families in rotation so good tools retain value. Publish
release capabilities and practice specimens, not forthcoming live instances
or answer-revealing generation state. Freeze a lobby's eligible catalogue and
selection policy before entry. Random selection after entry lock and author/
affiliate exclusions still apply. New revisions affect future lobbies.

Whatever a fighter exposes for such adaptation — a threshold, a model, a
thinking level — can be declared as a setting beside the solver and turned
from the CLI or the cockpit without a code change (docs/api.md, Settings).

## Proposed author package and release procedure

Each package should contain:

- Stable family ID, immutable revision/digest, author, candidate belts,
  answer format, resource bounds and a complete specification of its variants.
- Generator, canonical encoder, reference solution and fixtures. For difficult
  families, use an independently structured check/reference method to reduce
  the chance of publishing an implementation error as the expected answer.
- Training specimens, distinguishing boundary cases and explanations of why
  plausible approaches fail.
- Measured generation/reference-solving costs and script, model and tool-using
  baseline results. Input size or a family name alone does not establish belt.
- Release notes describing capabilities, rule changes and compatibility, with
  training material separate from live secrets.

Proposed lifecycle: draft → deterministic/answer checks → difficulty and cost
review → practice specimens → scheduled activation in a versioned catalogue.
This is internal engineering/content work, not an intermediate external pilot.
Content packs can arrive frequently without changing settlement logic. Exact
editorial cadence remains open.

Preserve old specifications, fixtures and settled evidence. Use the agreed
category/family weights and author limits; submission count must not determine
selection share. A defective revision is quarantined for future rounds and
handled under an explicit invalid-round policy; never rewrite commitments.

House-maintained generators can require normal content/software releases without
a new chain protocol or contract deployment. Separate the public solver interface
from the private content loader. Author-supplied code needs process/resource
isolation; today's trusted-template `exec` helpers are not a sandbox for authors.

Bind family/revision metadata to the published riddle. Today's hash covers
`round_id`, `title`, `statement`, `input` and `answer_format`; it does not cover
arbitrary added fields. Design a versioned metadata envelope and compatibility
transition explicitly. This catalogue does not implement that extension.

## Canonical answers and cost limits

Current formats are `integer`, `string` and `hex`; protocol v0 limits answers
to 512 bytes. Keep initial outputs compact. For a list/tuple encoded as a string,
specify exact serialization and ordering: the normalizer does not understand
arbitrary JSON equivalence. Avoid unspecified rounding, locale, timezone
databases, wall-clock behaviour or implementation-specific code semantics.

Where multiple solutions exist, ask for the unique optimum value or declare a
total tie-breaking order. Never ask for any valid patch/path and secretly accept
only one. An output task establishes the supplied output, not general correctness
of the fighter's software.

The publisher knows the expected answer. Public production generators together
with reproducible seeds can reveal it, so public samples and live-generation
policy need separation. Random selection does not remove this leakage.

Cost includes authoring, independent reference checks, generation and storage,
as well as solving and settlement. Bound expensive search and avoid making raw
hash grinding the default difficulty ladder.

## Proposed first implementation wave

Establish the content interface with representative families, then expand the
catalogue. This is an implementation sequence within the full-product release,
not an external onboarding milestone:

1. DATA-01 and PARSE-01: accessible tasks exposing brittle parsing.
2. DEBUG-01 and SIM-01: reusable debugging and event-processing tools.
3. GRAPH-01 and OPT-03: algorithmic depth with compact exact answers.
4. RULE-01 and MIX-02: interpretation and composition that reward tool selection.

Keep simple existing families as training foundations. Build meaningful variants
and fixtures before multiplying names. The remaining inventory is a continuing
content backlog, not a promise to ship 40 shallow templates at once.

Shipped ahead of this sequence, 2026-09-19: the three Qubic families in
[the riddle pack](riddle-pack.md). They cover PARSE-02 (binary frames, in
the real transaction layout), DATA-01 with SIM-05 (a normalized share
journal with derived destinations and two status modes) and DEBUG-01 with
MIX-02 (a wrong auditor to diagnose, then receipts to reconcile). They were
reviewed (#16) and measured on fresh instances (#17) before any of them is
fought live; the guide records both.
