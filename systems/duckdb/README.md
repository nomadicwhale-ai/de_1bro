# DuckDB (Track S, variant default)

Driver: `bench.py` (python `duckdb` package, in-memory database). Registered as `duckdb` in `impl.yaml`.

## Implementation notes
* Own SQL per op (derived from the spec/oracle queries, not importing `runner/oracle.py`). The digest uses
  `generator.resultdigest` (untimed).
* Settings: `PRAGMA threads = --threads`; `PRAGMA memory_limit` from `DUCKDB_MEMORY_LIMIT` (default `8GB`);
  `PRAGMA temp_directory` from `DUCKDB_TEMP_DIR` when set.
* `compute_ms` = `execute()` + `fetchall()` of the result rows. Digest and JSON are not timed.
* `materialized`: `CREATE TABLE sales AS SELECT <columns the op needs> FROM read_parquet('part-*.parquet')`
  is `load_ms`; the op SQL over that table is `compute_ms`. Peak RSS contains the loaded columns.
* `streaming`: the op SQL runs directly over `read_parquet('part-*.parquet')`; no table is created,
  `load_ms = 0` (parquet scan is part of `compute_ms`; DuckDB streams row groups, it is not literally
  chunk-file-at-a-time like Track L).
* OP15: `read_csv` over `part-*.csv` with explicit column types, `nullstr='\N'`, fixed
  `timestampformat='%Y-%m-%d %H:%M:%S.%f'`, then the OP15 summary SQL. Whole read+parse+summary is
  `compute_ms`, `load_ms = 0`, identical in both modes.
* OP21: `naive_sum` = plain `sum(cents::DOUBLE/100.0)`, `kahan_sum` = `fsum(...)`. With threads > 1 the
  naive sum is not strictly left-to-right (spec allows rtol 1e-9).
* Known unfairness: process start-up and `import duckdb` are outside `compute_ms`; DuckDB is a vectorised
  multi-threaded engine so `threads=4` is genuine parallelism; `--chunk-rows` is ignored.
* OP15 `sum_discount_e6`/`sum_tax_e6`: the floored values are cast to BIGINT before summing (exact).
  The oracle SQL sums them as DOUBLE, which is inexact above 2^53 (~9e15; happens at 10m rows for tax)
  and thread-order dependent, so an oracle for 10m+ generated that way may not be reproducible.

Phase 3b (OP06-OP09): joins/sort/top-N in DuckDB SQL over Parquet; dim_customer/dim_product (id + segment/brand) are loaded as tables first (load_ms) in both modes; streaming joins read sales via a view over `read_parquet`. OP08 (materialized only) uses `row_number()` over (timestamp, id) and sums `rn*id` in HUGEINT, reduced mod 2^64. OP09 is group-by + ORDER BY/LIMIT 100 + `row_number()`.
