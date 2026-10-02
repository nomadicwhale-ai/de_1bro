# Status (end of Phase 2)

Last updated after merging Phase 1+2 into `main` (PR #1).

## Phase summary

| Phase | Scope | State |
|---|---|---|
| 1 Foundations | repo skeleton, `.env.example`, deterministic generator (1k-1B, streaming), golden tests, manifests, disk guard, result schema, runner, data-type docs, conformance probes | **done** |
| 2 Vertical slice | Python/Rust/Go + DuckDB/Polars/SQLite, ops OP01,03,04,05,10,15,19,21,22; DuckDB oracle + pure-Python cross-check; result digests | **done, correctness-validated** (no timing campaign yet) |
| 3 Breadth | remaining languages/engines/ops, real timing campaign, first report | next (see `docs/PLAN.md`) |
| 4 Scale + analysis | 100M/1B runs, parallel track, profiler evidence, charts, final report | planned |

## What exists and is verified

* **Generator** - `python -m generator gen|estimate|verify|golden`. Pure-Python reference == vectorised generator on
  every table (tests + `spec/golden.json`). 1B rows of `sales_fact` digest in ~100 s on 4 cores (`--sink null`).
* **Oracle** - `runner/oracle.py` (DuckDB SQL from `runner/ops.py`) == independent pure-Python semantics
  (`runner/ref_ops.py`) at 1k and 10k rows (`tests/test_oracle.py`). Expected results committed for
  1k, 10k, 1m, 10m in `results/expected/`.
* **Runner** - process-isolated runs, per-process peak RSS (`wait4`), warm-up + timed runs, median/p95/IQR,
  resumable, schema-validated JSONL.
* **Docs** - 22 data-type concepts x 16 columns (`docs/data-types/`, 78 fields still marked `unverified`),
  conformance probes for 13 languages (7 executed).

## Correctness matrix (runner, single run, correctness only - NOT benchmark timings)

| implementation | track | ops | modes | threads | 1k / 10k / 1m | 10m |
|---|---|---|---|---|---|---|
| python (stdlib) | L | 9 | streaming, materialized | 1 | all OK | OP01, OP10, OP22 only |
| rust (std only) | L | 9 | streaming, materialized | 1 | all OK | all OK |
| go (stdlib) | L | 9 | streaming, materialized | 1 | all OK | all OK |
| duckdb | S | 9 | streaming, materialized | 1, 4 | all OK | all OK |
| polars | S | 9 | streaming, materialized | 1, 4 | all OK | all OK |
| sqlite | S | 9 | materialized | 1 | all OK | OP01, 04, 19, 21, 22 only |

Totals: 408/408 records OK at 1k-1m; 119/119 OK at 10m; 0 incorrect, 0 failed, 0 schema problems.
Ops: OP01 scan-aggregate, OP03 group-by (low card.), OP04 group-by (high card.), OP05 group-by (3 keys),
OP10 distinct counts, OP15 CSV parse, OP19 null handling, OP21 decimal vs float sums, OP22 conversion round trips.

## Known caveats (do not publish rankings before these are addressed)

1. **No timing campaign yet.** Numbers seen so far came from single runs on a machine shared with other jobs.
2. **Not every combination was run at 10m** (python and sqlite subsets above); nothing has run above 10m.
3. **Not-installed toolchains:** C#, Julia, Swift, Kotlin, Scala, R (conformance sources + Dockerfiles exist, untested);
   no Java/C++/JS benchmark implementations yet. PostgreSQL, Spark, pandas, Arrow, ClickHouse not started.
4. **Engine semantics worth a fairness note:** Polars rewrites `x / 100.0` as multiplication (driver works around it);
   Polars has no Kahan sum and SQLite's `sum()` is already compensated (OP21 floats compared with rtol 1e-9);
   DuckDB/Polars streaming modes ignore `--chunk-rows` and scan all files in one query.
5. **Track L load/compute split differs by design** (e.g. Go dictionary-encodes strings during load, making OP03
   compute tiny). Compare `load_ms + compute_ms` too, never `compute_ms` alone, before drawing conclusions.
6. Size estimates in `docs/dataset-sizes.md` run 10-30% high; 1B Parquet (~28-35 GB) does not fit this container's disk -
   use `--sink null` for 1B here.
7. Result digests are verified only against the DuckDB oracle + pure-Python at <=10k rows; 100k-10M rely on DuckDB alone.

## Reproduce

```bash
cp .env.example .env && make setup && make test
for n in 1k 10k 1m 10m; do make gen SIZE=$n DATASETS=A; done
python -m runner.oracle --rows 1k,10k,1m,10m
python -m runner build && python -m runner run --rows 1k,10k,1m --runs 1 --warmup 0 --force
```
