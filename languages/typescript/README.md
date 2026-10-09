# TypeScript (Node.js, Track L stdlib)

Registered as `typescript`: all 13 operations, one JS execution thread, streaming/materialized
CSV input (OP08 materialized-only). Requires Node.js **22.23.1 or later**, validated with v22.23.1.

## Implementation notes

* `bench.mts` is the typed implementation: explicit input batches, result cells, group state,
  typed `Map`/`Set` keys and generator signatures. Node's built-in `--experimental-strip-types`
  erases annotations at process startup; no TypeScript compiler, npm packages or external runtime
  libraries are needed. Only erasable TypeScript is used (no enums/namespaces).
* The build command checks parsing/syntax, **not static type checking**. Node does not enforce TypeScript
  types at runtime. Compiler-based checking has not been run in this environment (no `tsc` installed).
  Experimental-feature warnings may appear on stderr; stdout is exactly one JSON result line.
* The checked-in JavaScript counterpart is generated from this source using
  `node languages/typescript/emit-javascript.mjs`; its build/test verifies it is current.
  Type erasure happens outside measured load/compute (startup), so JS and TS run the same V8 algorithms.
  Do not interpret their timings as independent engine performance or publish rankings from one-run checks.
* Algorithms, timing, CSV handling and known unfairness are identical to the
  [JavaScript implementation notes](../javascript/README.md#implementation-notes): column batches,
  streaming bounded by `--chunk-rows`, materialized load before compute, stdlib maps/sets/sort,
  OP09 sorts all group totals, OP15 includes parsing, and digests are untimed.

## BigInt / number caveats

IDs, integer cents/aggregates and microsecond timestamps use `bigint`, never `number` for keys or
ordering. Numbers are used for bounded counts/indices, civil days/years and the specified floating
operations. `number` loses integer precision beyond 2^53-1; bitwise number operators are only 32-bit.
OP22 constructs its integer with BigInt before the deliberate float round trip; OP21 uses exact cents
alongside ordered naive/Kahan sums. Digest arithmetic wraps at 64 bits; aggregate arithmetic does not.
BigInt is not directly JSON-serializable, so results are digested before emitting numeric timings/counts
and float outputs. See the [full caveats](../javascript/README.md#bigint--number-caveats).

## Validate

From the repo root: `python -m runner build --impl typescript`, then
`python -m runner run --impl typescript --rows 1k,10k,1m --runs 1 --warmup 0 --force`.
Focused regression tests: `python -m pytest tests/test_node_languages.py`.
