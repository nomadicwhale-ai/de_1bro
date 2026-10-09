# Status (Phase 3b slice complete)

Last updated after roadmap items 1 (trust fixes), 2 (Python stdlib OP06-OP09) and 4 (JavaScript/TypeScript).
No new timing campaign; Java, C++ and earlier OP06-OP09 support came in PRs #1-#3.

## Phase summary

| Phase | Scope | State |
|---|---|---|
| 1 Foundations | repo skeleton, `.env.example`, deterministic generator (1k-1B, streaming), golden tests, manifests, disk guard, result schema, runner, data-type docs, conformance probes | **done** |
| 2 Vertical slice | Python/Rust/Go + DuckDB/Polars/SQLite, ops OP01,03,04,05,10,15,19,21,22; DuckDB oracle + pure-Python cross-check; result digests | **done, correctness-validated** (no timing campaign yet) |
| 3a First results | timing campaign (5 runs + warm-up) for the 6 implementations at 1M/10M, generated report + charts | **done** - `report/REPORT.md`, `report/FINDINGS.md`, `results/published/phase3a/` |
| 3b/3c Breadth | joins/sort/top-N (OP06-09) for all implementations, Java + C++ on all 13 ops | **slice done** - 8 implementations, 13 ops; `results/published/phase3b/` |
| Roadmap item 2 | Python stdlib OP06-OP09; all Track L languages support all 13 registered ops | **done, correctness-validated at 1k/10k/1m** |
| Roadmap item 4 | JavaScript + TypeScript (Node.js), stdlib, all 13 ops | **implemented, correctness-validated** at 1k/10k/1m; OP01/06/22 at 10m |
| 3c+ remaining breadth | OP02, OP11-14, OP16-18, OP20; C#, Julia, Swift, Kotlin, Scala, R; PostgreSQL, pandas, Arrow, Spark | next - prioritised in `docs/PLAN.md` (items 1-4 first) |
| 4 Scale + analysis | 100M/1B runs, parallel track, profiler evidence, charts, final report | planned |

## What exists and is verified

* **Generator** - `python -m generator gen|estimate|verify|golden`. Pure-Python reference == vectorised generator on
  every table (tests + `spec/golden.json`). 1B rows of `sales_fact` digest in ~100 s on 4 cores (`--sink null`).
* **Oracle** - `runner/oracle.py` (DuckDB SQL from `runner/ops.py`) == independent pure-Python semantics
  (`runner/ref_ops.py`) at 1k, 10k and 100k rows (`tests/test_oracle.py`, all 13 ops). Expected results committed for
  1k, 10k, 1m, 10m in `results/expected/`, plus OP06-OP09 at 100k; those four ops' expected files are
  self-checked against both evaluators at 1k/10k/100k.
* **Runner** - process-isolated runs, per-process peak RSS (`wait4`), warm-up + timed runs, median/p95/IQR,
  resumable, schema-validated JSONL.
* **CI** - a clean-clone `implementations` job provisions Python, Rust, Go, Java and C++, builds all registered
  implementations, generates/verifies 1k/10k inputs, runs smoke plus forced correctness and rejects unexpected skips.
  CPU affinity is selected from the runner's allowed CPUs. `generator` runs the full tests, including the 100k checks.
* **Python coverage** - item 1 removed premature OP06-OP09 registration; item 2 implements and re-registers
  these operations after validation, bringing the stdlib driver to all 13 registered operations.
* **Fairness** - `docs/FAIRNESS_ISSUES.md` tracks current caveats, evidence and reporting mitigations.
* **Docs** - 22 data-type concepts x 16 columns (`docs/data-types/`, 78 fields still marked `unverified`),
  conformance probes for 13 languages (7 executed).

## Correctness matrix (runner, single run, correctness only - NOT benchmark timings)

**Roadmap item 2:** Python now supports all 13 operations. The full acceptance run at 1k/10k/1m produced
75 OK records and 3 n/a records (OP08 streaming is undefined), with no incorrect, failed or skipped records.
OP06/OP07/OP09 passed in both modes; OP08 passed materialized. The new operations have not been run at 10m.
Reproduce with `python -m runner run --impl python --rows 1k,10k,1m --runs 1 --warmup 0 --force`.

Phase 3b added `java` and `cpp` (track L, stdlib, all 13 ops, both modes except OP08 materialized-only) and OP06-OP09 for
rust, go, duckdb, polars, sqlite. Validation at 1k/10k/1m: 624 + 12 records OK, 0 incorrect; timing campaigns: 804 OK records in total
for Phase 3b (see `results/published/`). The table below is the Phase 2 snapshot (ops 01,03,04,05,10,15,19,21,22).

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

### Roadmap item 4: JavaScript / TypeScript

* `javascript` and `typescript`: Track L `stdlib`, all 13 ops, one execution thread; streaming and materialized
  (OP08 materialized-only). **150 OK records** at 1k/10k/1m, six expected OP08-streaming n/a; **12 OK** at
  10m (OP01, OP06, OP22, both modes), zero incorrect/failed/schema problems. Node.js v22.23.1.
* Typed TypeScript source and mechanically generated standalone JavaScript run the same V8 algorithms;
  Node's built-in type stripping needs no npm dependencies. BigInt preserves IDs, cents, integer sums and
  microseconds. Number/BigInt, GC, top-N sort and timing caveats: `languages/{javascript,typescript}/README.md`.
* These are one-run correctness checks, **not a timing campaign**; no new rankings/results were published.
  Reproduce: `python -m runner run --impl javascript,typescript --rows 1k,10k,1m --runs 1 --warmup 0 --force`;
  subset: add `--rows 10m --op OP01,OP06,OP22` instead. Focused regressions: `tests/test_node_languages.py`.

## Known caveats (do not publish rankings before these are addressed)

1. **Timing campaign is small:** 5 timed runs on one 4-vCPU machine (45 of 254 cells flagged noisy); 10M for Python/SQLite covers a subset of operations.
2. **Not every combination was run at 10m** (python and sqlite subsets above); nothing has run above 10m.
3. **Not-installed toolchains:** C#, Julia, Swift, Kotlin, Scala, R (conformance sources + Dockerfiles exist, untested);
   JS/TS now validated (roadmap item 4); Java/C++ were added in Phase 3b. PostgreSQL, Spark, pandas, Arrow, ClickHouse not started.
4. **Engine semantics worth a fairness note:** Polars rewrites `x / 100.0` as multiplication (driver works around it);
   Polars has no Kahan sum and SQLite's `sum()` is already compensated (OP21 floats compared with rtol 1e-9);
   DuckDB/Polars streaming modes ignore `--chunk-rows` and scan all files in one query.
5. **Track L load/compute split differs by design** (e.g. Go dictionary-encodes strings during load, making OP03
   compute tiny). Compare `load_ms + compute_ms` too, never `compute_ms` alone, before drawing conclusions.
6. Size estimates in `docs/dataset-sizes.md` run 10-30% high; 1B Parquet (~28-35 GB) does not fit this container's disk -
   use `--sink null` for 1B here.
7. Oracle/result digests are independently cross-checked through 100k; 1M/10M still rely on DuckDB alone.
   Clean-clone CI checks correctness, not performance or fairness; tracked caveats remain in `docs/FAIRNESS_ISSUES.md`.

## Reproduce

```bash
cp .env.example .env && make setup && make test
for n in 1k 10k 1m 10m; do make gen SIZE=$n DATASETS=A; done
python -m runner.oracle --rows 1k,10k,1m,10m
python -m runner build && python -m runner run --rows 1k,10k,1m --runs 1 --warmup 0 --force
```
