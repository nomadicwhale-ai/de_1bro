# SQLite (Track S, variant default)

Driver: `bench.py` (python3 stdlib `sqlite3`, SQLite 3.45.1 here). Registered as `sqlite` in `impl.yaml`
(materialized only, 1 thread, CSV input, `max_rows` 10M, validation scale only).

## Implementation notes
* **Database**: `:memory:` (no temp file, so no disk I/O in the timings); `journal_mode=OFF`, `synchronous=OFF`.
  The `sqlite3` CLI is not installed, so the import path is `csv.reader` + `executemany` in a single transaction.
* **load_ms** = CSV chunk files -> `sales` table. The import necessarily runs a Python per-row conversion
  (the stdlib has no bulk CSV importer): money text -> integer cents without floats (`1234.56` -> 123456),
  timestamp -> integer microseconds, date -> integer days since epoch (memoised per distinct date string),
  `\N` -> NULL, `true/false` -> 1/0, discount/tax -> REAL via `float()` (needed for `floor(x*1e6+0.5)` to match
  the oracle bit for bit). This conversion cost dominates load_ms and is a host-language loop; it is
  the importer, not query work. Queries themselves contain no Python row loops.
* **compute_ms** = one SQL statement + `fetchall()`. Digest/JSON are untimed.
* **OP15**: import + summary query reported as one `compute_ms`, `load_ms` = 0.
* **Year/month/day (OP05, OP22)**: pure SQL Hinnant `civil_from_days` arithmetic in nested subqueries. It is
  evaluated once per DISTINCT `date_days` (a few thousand values) in a `MATERIALIZED` CTE and joined back to the
  fact rows (evaluating it per row through SQLite's subquery flattening was ~10x slower). Still all SQL.
* **OP22**: int64->float64->int64 via `CAST(CAST(k AS REAL) AS INTEGER)`; `trunc(f*100.0)` via `CAST(.. AS INTEGER)`.
* **OP21**: `exact_sum_cents`/decimal text in SQL (`printf('%02d')`). Both `naive_sum` and `kahan_sum` are SQLite
  `sum(cents/100.0)`. SQLite >= 3.43 implements Kahan-Babuska compensated summation inside `sum()` for floats, so
  `kahan_sum` is a genuine compensated sum for that reason; `naive_sum` is *not* truly naive on 3.43+ (SQLite offers
  no plain float sum). Both are within rtol 1e-9 of the oracle. On SQLite < 3.43 both would be naive.
* Streaming mode is not supported (the whole table is held in memory); runs above 10M rows are capped via `max_rows`.

## Known unfairness
Per-row Python parsing makes load_ms much slower than a native importer (DuckDB/CLI `.import`). Each invocation
re-imports the data (one process per op), so every op pays the full load.
