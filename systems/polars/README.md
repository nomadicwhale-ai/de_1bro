# Polars (Track S)

Driver: `systems/polars/bench.py` (python `polars` 1.44.x), registered as `polars` in `impl.yaml`
(variant default, threads 1 and 4, modes streaming and materialized, Parquet input; OP15 reads CSV).

## Implementation notes
* Threads: `POLARS_MAX_THREADS=<--threads>` is set before `import polars` (also `n_threads` for `read_csv`).
* `materialized`: `pl.read_parquet(files, columns=<needed columns only>)` is `load_ms`; then the op is run as
  lazy expressions over `df.lazy()` and collected with the default in-memory engine (`compute_ms`).
* `streaming`: `pl.scan_parquet(files).<op>.collect(engine="streaming")`, `load_ms = 0` (read is fused into
  the query; projection pushdown selects columns). `--chunk-rows` is ignored (the engine chunks itself).
* `compute_ms` includes collect plus `DataFrame.rows()` (result to python tuples). Digest/JSON are untimed.
* Money: `(unit_price * 100).cast(Int64)` on the Decimal(18,2) column is exact decimal arithmetic (checked
  against Python `Decimal`); no floats involved. Year/month/day via `dt.year()/month()/day()`.
* NULL-aware sums (`sum_quantity` NULL when all NULL) use `when(count>0).then(sum)`; small ints are cast to
  Int64 before summing (polars would otherwise overflow Int32 sums in some paths).
* OP15: `pl.read_csv` (per chunk file, concatenated) / `pl.scan_csv(...).collect(engine="streaming")` with an
  explicit schema, `null_values=["\N"]`, `missing_utf8_is_empty_string=True` (an empty unquoted field is the
  empty string, not NULL), date/timestamp read as strings and parsed with exact formats
  (`%Y-%m-%d`, `%Y-%m-%d %H:%M:%S%.f`, `strict=True`), then summary expressions. Whole read+parse+summary is
  `compute_ms`, `load_ms = 0`. Both modes use the same logic (eager vs streaming engine).

## Known caveats / unfairness
* **Scalar division is not IEEE in polars**: `x / 100.0` is rewritten as `x * 0.01`, giving different
  results (e.g. OP22 `lossy_decimal_float64` 16 instead of 69). The driver divides by a data-derived
  vector column `(cents*0+100).cast(Float64)` to get exact IEEE division.
* OP21 `naive_sum`: polars f64 `sum` (SIMD/pairwise, parallel when threads > 1), compared with rtol 1e-9.
  `kahan_sum`: no compensated-sum expression exists in polars; the value reported is the exact int64 cents
  total divided by 100.0 (one scalar python division of the engine result), which is the correctly rounded
  value a compensated sum approximates. Not a true Kahan loop.
* OP15 with 1 thread is slow (~5 s per 1M rows), dominated by timestamp string parsing.
* `streaming` is the new streaming engine; some ops may fall back to in-memory internally.
