# Universal Data Types and 1-Billion-Row Data Engineering Benchmark

A reproducible benchmark that compares how programming languages (Track L) and data systems (Track S)
handle common data types and large-scale data-engineering operations on identical deterministic data.
There is no overall winner: results are ranked per workload and explained. See `PROMPT_v2.md` for the full
specification and `docs/METHODOLOGY.md` for the rules.

## Status

| Phase | Scope | State |
|---|---|---|
| 1 Foundations | repo skeleton, `.env`, deterministic generator (1k–1B rows, streaming), golden tests, manifests, disk guard, result schema, runner, data-type docs, conformance probes | **done** |
| 2 Vertical slice | Python/Rust/Go + DuckDB/Polars/SQLite, ops OP01,03,04,05,10,15,19,21,22, DuckDB oracle | **done** (correctness-validated; no timing campaign yet) |
| 3 Breadth | first timing campaign + report, remaining ops, languages/engines | next |
| 4 Scale + analysis | 100M/1B runs, parallel track, charts, report | planned |

Details: [`docs/STATUS.md`](docs/STATUS.md) (verified matrix + caveats) and [`docs/PLAN.md`](docs/PLAN.md) (what comes next).

## Quick start

```bash
cp .env.example .env          # adjust seed, paths, budget, DB connections
make setup                    # pip install -r requirements.txt
make test                     # reference == vectorised generator; golden digests
make gen SIZE=1m              # all five tables -> data/<table>/1m/part-*.{parquet,csv} + manifest.json
make verify                   # sha256 + content-digest check of everything under data/
make gen-dry SIZE=1b          # estimate size, check disk guard, write nothing
make stream SIZE=1b DATASETS=A   # generate + digest 1B rows on the fly (no files)
make smoke                    # runner smoke profile, results validated against schema/result.schema.json
python -m runner.oracle --rows 1k,10k    # expected results (DuckDB) for the Phase 2 ops
python -m runner build && python -m runner run --rows 1k,10k --runs 1 --warmup 0 --force   # all implementations
```

## Datasets (`spec/generator.md`)

| id | table | rows for scale N | notes |
|---|---|---|---|
| A | `sales_fact` | N | 13 columns, nulls, skew, edge-case rows every 1000th row |
| B | `dim_customer` | min(N/10, 50M) | join dimension |
| C | `dim_product` | clamp(N/100, 10, 1M) | nested list + map columns |
| D | `events_log` | N | strings, JSON, UUIDs, out-of-order timestamps, 1% duplicate ids |
| E | `wide_numeric` | N (≤100M) | 100 float64 + 20 int64 columns |

Scales: 1k, 10k, 1m, 10m, 100m, 1b (or any integer). Row `i` depends only on `(seed, table, column, i)`, so
chunks, workers and other languages produce identical data. Python API: `generator.stream.iter_chunks(...)`.
Measured sizes: `docs/dataset-sizes.md`.

## Configuration (`.env`)

All settings live in `.env.example` (seed, `DATA_DIR`, chunking, workers, formats, compression, price type,
resource budget, run protocol, PostgreSQL/ClickHouse/Spark/DuckDB settings). Real environment variables override
the file; `common/env.py` is a dependency-free loader.

## Layout

```
generator/   deterministic generator (reference.py, fast.py), checksum, writers, CLI
spec/        generator.md, checksum.md, golden.json (expected digests)
schema/      result.schema.json
config/      budget.yaml, ops.yaml, implementations.yaml
runner/      process-isolated runner, stats, sysinfo, op registry (ops.py), DuckDB oracle, pure-Python ref ops
languages/   Track L implementations (python, rust, go) - each with impl.yaml + README notes
systems/     Track S implementations (duckdb, polars, sqlite)
docs/        METHODOLOGY.md, dataset-sizes.md, data-types/
conformance/ per-language probes of integer/float/string/time semantics
tests/       golden + cross-implementation tests
```
