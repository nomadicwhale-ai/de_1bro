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

---

# Phase 3b additions (Java, C++, joins/sort/top-N)

Data: `results/published/phase3b/` (java and cpp on all 13 ops at 1M/10M; OP06-OP09 for rust, go, duckdb, polars, sqlite).
Whole report now covers 446 records (104 flagged `noisy`), all correct against the oracle. Rust/Go/Python numbers for
OP01-OP05, OP10, OP15, OP19, OP21, OP22 come from the earlier Phase 3a campaign (same idle machine, different time).
Same caveat as above: these describe these implementations, not the languages.

## Track L at 10M rows, materialized, load + compute (4 stdlib-only implementations)
* **C++ is fastest or within ~5% of fastest on 12 of 13 operations**, e.g. OP01 1.4 s (Go 1.8, Rust 1.9, Java 3.0),
  OP06 hash join 1.9 s (Go 2.6, Rust 3.0, Java 3.6), OP08 full sort 3.0 s (Rust 3.2, Go 4.1, Java 12.0).
* **The exception is OP10 (distinct counts): C++ is the slowest at 8.5 s vs Rust 3.2 s.** The C++ version uses
  `std::unordered_map`/`unordered_set`, whose libstdc++ hash for integers is the identity function and which allocates a
  node per element; Rust/Go/Java use flat or custom maps. This is an implementation choice that the README documents,
  not a statement about C++ - a flat hash map would likely close the gap.
* **Java is the slowest Track L implementation on most operations** (typically 1.4-2.3x C++), and 4x slower on OP08 because
  the standard-library comparator sort works on boxed indexes (a primitive sort cannot carry the 2-key order). Each run is a
  fresh JVM, so JIT warm-up and GC are inside the timing; the effect is largest at small sizes.
* Rust is slowest of the compiled three on OP05 (5.1 s vs C++ 2.9 s, Go 3.2 s) - a composite-key hashing choice, see its README.

## Track S vs Track L (different inputs: Parquet vs CSV, so a pipeline comparison)
* DuckDB or Polars is the fastest implementation on 12 of 13 operations at 10M (Polars wins OP07, OP08, OP19); OP15 is the exception.
* **CSV parse (OP15) is again the reverse:** C++ 2.3 s, Rust 2.5 s, Go 3.8 s, Java 4.7 s vs DuckDB 8.0 s and Polars 8.5 s
  (single thread).
* New operations in Track S: OP06 join DuckDB 1.4 s / Polars 2.4 s; OP08 sort Polars 1.6 s / DuckDB 2.5 s;
  OP09 top-100 DuckDB 1.2 s / Polars 2.1 s. SQLite at 10M takes 55-62 s per operation (load + compute), almost all of it CSV import.

## Still not covered
OP02, OP11-OP14, OP16-OP18, OP20; JavaScript/TypeScript, C#, Julia, Swift, Kotlin, Scala, R; PostgreSQL, pandas, Arrow, Spark,
ClickHouse; nothing above 10M rows; no parallel Track L variants.
