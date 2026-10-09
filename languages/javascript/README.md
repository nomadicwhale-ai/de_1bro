# JavaScript (Node.js, Track L stdlib)

Requires Node.js **22.23.1 or later** (validated with v22.23.1). All 13 operations use only
Node's standard library, one JS execution thread, CSV input, and streaming/materialized modes
(OP08 is materialized-only). Registered as `javascript`.

## Implementation notes

* `bench.mjs` is standalone JavaScript, mechanically stripped from the typed source in
  `languages/typescript/bench.mts` by Node's built-in `stripTypeScriptTypes`. Keeping algorithms identical
  prevents accidental fairness differences; these are two source-language variants of the same V8 runtime,
  **not independent engines**. Build checks the checked-in JavaScript is current; regenerate after edits with
  `node languages/typescript/emit-javascript.mjs` (no npm, compiler, or external runtime packages).
* Read 64 KiB blocks with a UTF-8 `StringDecoder`; build column arrays for needed fields only.
  Streaming honors `--chunk-rows`, even across files, discarding each batch after consumption.
  Materialized retains all needed typed batches before compute. CSV supports doubled quotes, quoted
  empty strings and commas, CRLF and an unterminated final line; the input schema has no multiline strings.
  Dimensions retain a `Map` of IDs to attributes; trailing product JSON fields are skipped.
* `Map`/`Set` implement groups, exact distincts and joins. Inner joins skip unmatched keys.
  Multi-column group keys use JSON tuples to avoid delimiter collisions; Unicode is not normalized.
  OP08 uses `Array.sort` on `(timestamp, id)`; OP09 sorts all customer totals before selecting 100
  (O(G log G), more work/memory than a bounded heap). V8 allocation/GC are part of load/compute.
* Load includes I/O and typed parsing plus dimensions. Compute includes final rows and sorting,
  but excludes digest/JSON. OP15 reports read+parse+summarize as compute, zero load, in both modes.
  OP21 maintains naive and Kahan sums in global row order across batches.
* Node may use background GC/runtime threads, but algorithms create no workers or hidden parallel
  data processing. The identical `--max-old-space-size=8192` flag for JS/TS permits a larger V8 heap;
  it is not preallocated, and the runner still measures process RSS and applies its resource budget.

## BigInt / number caveats

* IDs, money cents, quantities, microsecond timestamps, integer aggregates and digest arithmetic
  use `BigInt`; decimal text is parsed without floats. No ID ever passes through `number`, including
  hash keys and sort comparisons. Aggregates are exact; modulo 2^64 is applied only to OP08's
  positional checksum and the result digest, not to sums. Comparators return -1/0/1, not BigInt differences.
* `number` is IEEE-754 binary64: integers above 2^53-1 are not all exact, and JS bitwise operations
  truncate to 32 bits. We use numbers only for bounded row counts, array indices and Gregorian day/year
  arithmetic, plus the **specified** float computations in OP15/21/22. Dates are computed in UTC with
  integer civil-date formulas, preserving timestamp microseconds (no millisecond-only `Date` conversion).
* OP22 builds `k` with BigInt **before** its deliberate number round trip, and tests decimal truncation
  and timestamp millisecond loss separately. OP21's exact decimal text follows the reference's
  floor-division/remainder format. Float sums are reported separately under the spec tolerance.
* JSON cannot serialize BigInt directly. Integer result rows feed the BigInt-based digest; stdout
  contains only the hex digest, bounded numeric row count/timings, and OP21's numeric floats.

## Validate

From the repo root: `python -m runner build --impl javascript`, then
`python -m runner run --impl javascript --rows 1k,10k,1m --runs 1 --warmup 0 --force`.
Both modes are checked (OP08 streaming is n/a); data and expected results must exist.
Focused regression tests: `python -m pytest tests/test_node_languages.py`.
