# Plan (updated after Phase 2)

Priorities (unchanged): correctness > reproducibility > fairness > coverage. Work is ordered so every step
produces a publishable, verified increment; later items can be dropped without invalidating earlier ones.

## Phase 3a - first real results (highest value, cheapest)
1. Timing campaign for the Phase 2 implementations: 1 warm-up + 7 timed runs at 1m and 10m (3 at larger sizes),
   quiet machine, fixed seed shuffle. Output `results/raw/*.jsonl` (commit a curated copy under `results/published/`).
2. `report/make_charts.py` + `report/REPORT.md` v0: per-op tables (dense ranks with noise-band ties), bar charts, the
   load/compute split, memory per row, caveats from `docs/STATUS.md`. Rankings per op, per mode, per thread count;
   Track L and Track S in separate tables.
3. Extend oracle cross-check to 100k rows (pure Python vs DuckDB) and run 100m for the compiled/engine implementations.

## Phase 3b - breadth of operations (dataset A, then B/C/D/E)
OP02 filter, OP06/07 joins (needs `dim_customer`, `dim_product`), OP08 sort, OP09 top-N, OP11 window, OP12 dedup (D),
OP13 strings (D), OP14 JSON (D), OP16 Parquet read, OP17 write, OP18 date/time, OP20 wide scan (E).
Each op: entry in `runner/ops.py` (spec + oracle SQL) -> pure-Python semantics in `runner/ref_ops.py` -> implementations.

## Phase 3c - breadth of implementations (install toolchains first; otherwise Dockerfile + `not_run`)
1. Java, C++ (installed here) and JavaScript/TypeScript (node installed): std-only, same contract.
2. Systems: PostgreSQL (psql client present, server needed), pandas, PyArrow compute, Spark local (needs JVM + pyspark).
3. Toolchains not installed (C#, Julia, Swift, Kotlin, Scala, R): run from their Dockerfiles when available.
4. Parallel variants (fixed N threads) for Rust/Go/Java/C++ once single-thread numbers are stable.

## Phase 4 - scale and analysis
100m materialized/streaming where RAM allows; 1B streaming (generate on the fly or on a larger disk); scaling
exponents, bytes/row, GC/throttling time series, `perf stat`/flame-graph evidence for top/bottom implementation per
op, per-op explanation pages, final report and threats-to-validity.

## Housekeeping backlog
* Resolve the 78 `unverified` data-type fields as toolchains become available (conformance output wins on conflict).
* `docs/FAIRNESS_ISSUES.md` (not yet created) for implementation disputes; keep `docs/STATUS.md` current per phase.
* CI: add a smoke job running `python -m runner run --smoke` plus the Phase 2 implementations at 1k/10k.
* Consider spec-level chunk reading for DuckDB/Polars streaming so `--chunk-rows` is honoured.

## Budget note
Compute-heavy items (timing campaign, 100m+, Spark/PostgreSQL setup) are the expensive ones; implementation work is
parallelised through sub-agents. If budget is tight, stop after Phase 3a: it already yields a verified, reproducible,
honestly-caveated report for 6 implementations x 9 operations.
