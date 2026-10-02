# Operation specifications (Phase 2)

Generated from `runner/ops.py` (`python -m runner specs`); do not edit by hand. Each file defines the
exact result schema; the oracle is the DuckDB SQL shown in the file, cross-checked against the pure-Python
semantics in `runner/ref_ops.py` (tests/test_oracle.py).

Common rules
* Input rows are the dataset-A files for the requested scale N (`data/sales_fact/<size>/part-*.{csv,parquet}`).
  Track L reads the CSV chunks (stdlib parsers only; skipping unneeded fields is allowed but every row of
  every needed column must be parsed). Track S reads Parquet (or imports the CSV where the system has no
  Parquet reader, e.g. SQLite).
* Money is exact: decimal text `1234.56` -> int64 cents. CSV NULL marker is `\N`; NULL is never the same as `""`.
* Results are digested with the **result digest** (spec/checksum.md); float results are reported separately.
* Streaming mode: process chunk files one at a time with bounded memory, accumulating `load_ms`
  (parse/read) and `compute_ms` (operation) separately. Materialized mode: load everything first
  (`load_ms`), then run the operation (`compute_ms`). OP15 is the exception: parsing *is* the operation.
