# Findings from the Phase 3a timing campaign

Hand-written summary of `report/REPORT.md` (generated from `results/published/phase3a/*.jsonl`: 254 records, all
correct against the oracle; 5 timed runs + 1 warm-up, 3 timed for the Python/SQLite 10M subsets; 45 of 254 cells are
flagged `noisy`). Machine: 4 shared vCPUs. **These are observations about these specific implementations on this one
machine, not statements about the languages in general.** Values are `load + compute` medians.

## Track L (single-threaded, standard library only)
* **Rust vs Go are within ~2x of each other, and neither wins everywhere.** At 10M (materialized): Go is ahead on OP03
  (1.7 s vs 2.5 s), OP05 (3.2 vs 5.1), OP19 and OP21; Rust is ahead on OP10 (3.2 vs 5.3), OP15 (2.5 vs 3.8) and
  marginally OP04/OP22. Much of the gap is the *load* phase (parsing) and each implementation's choices (Go dictionary-
  encodes strings during parsing; Rust uses a hand-written Fx-style hasher) - see the per-language READMEs. Treat
  Rust-vs-Go differences as "these two implementations", not "these two languages".
* **Stdlib CPython is roughly 8-24x slower than Rust/Go** at 1M rows across the nine operations (materialized),
  and uses about 1.5-2.5x their peak memory; at 10M it needs ~30 s just to parse the CSV chunks.
* Parsing dominates the cheap operations: for OP01/OP03/OP04/OP19/OP21 `load` is roughly 85-99% of `load + compute`
  for Rust and Go at 1M (for OP05/OP10 compute is 40-60%). Compute-only ranks therefore differ from end-to-end ranks (the report shows both).

## Track S (data systems)
* **DuckDB is fastest or near-fastest on single-thread streaming for 8 of 9 operations at 10M**, typically 2-6x
  ahead of the Track L programs and ahead of Polars (e.g. OP01 0.45 s vs Polars 1.4 s vs Go 1.8 s). Both engines read
  Parquet (columnar, compressed) while Track L programs parse CSV - the inputs are deliberately the *native* input of each
  track, so this is a pipeline comparison, not a pure engine-vs-language one.
* **CSV parsing (OP15) reverses the picture:** at 10M Rust 2.6 s and Go 3.7 s vs DuckDB 7.9 s and Polars 7.9 s on one thread
  (DuckDB and Polars are comparable at 4 threads: 2.6 s and 2.1 s).
* **Thread scaling (1 -> 4 threads, 10M streaming):** DuckDB OP01 0.45 -> 0.14 s (3.2x), Polars OP01 1.4 -> 0.42 s (3.4x);
  scaling varies by operation: OP04 (high-cardinality group-by) 1.6x (DuckDB) / 2.7x (Polars), OP10 (distinct counts) 4.2x / 4.6x.
* **SQLite** (validation-only): OP01 at 10M takes ~47 s, ~45 s of which is importing the CSV into an in-memory table;
  DuckDB materialized does the same work in 0.7 s.

## What this does not show
No operation above 10M rows; no parallel Track L variants; no joins/sorts/windows/strings (Phase 3b); no Java, C++,
JavaScript/TypeScript, C#, Julia, Swift, Kotlin, Scala, R, PostgreSQL, Spark, pandas or Arrow yet. Rankings from 6
implementations must not be extrapolated to the full list.
