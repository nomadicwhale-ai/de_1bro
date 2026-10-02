# Methodology

Status: Phases 1-2 complete (see docs/STATUS.md). Rules marked **[enforced]** are checked by code; the rest are
protocol that Phase 2+ implementations and the runner follow.

## Tracks
* **Track L** – hand-written programs per language; variants `stdlib` (single-threaded, primary),
  `parallel` (stdlib concurrency, fixed N threads), `ecosystem` (named libraries, ranked separately).
* **Track S** – data systems (DuckDB, PostgreSQL, Spark, Polars, pandas, Arrow, ClickHouse, SQLite ≤10M).
* Tracks are **never ranked against each other**: different optimisers, vectorisation, storage and I/O layers.

## Data **[enforced]**
Deterministic, counter-based generator (`spec/generator.md`); the pure-Python reference and the
vectorised generator are compared on every test run, and `spec/golden.json` pins expected digests for
other languages. Manifests record seed, generator version, per-chunk sha256 and content digests
(`python -m generator verify`).

## Implementation contract **[enforced by runner/run.py]**
```
<cmd> --op OPxx --dataset A --rows N --mode streaming|materialized --chunk-rows C --threads T \
      --input <data dir> --output-json
stdout (last JSON line): {"load_ms", "compute_ms", "checksum", "row_count",
                          optional "steady_rss_mb", "chunk_rows_per_s", "toolchain", "notes"}
```
Registered in `config/implementations.yaml`. Each timed run is a fresh OS process; the first run per
configuration is a discarded warm-up (`WARMUP_RUNS`), then `TIMED_RUNS` (7; 3 at 1B). Peak RSS is the
child's own `ru_maxrss` from `wait4` (not cumulative). Single-thread runs are pinned with `taskset`
(`SINGLE_THREAD_CPU`). Implementation order is shuffled with a fixed seed (`SHUFFLE_SEED`).

## Timing boundaries
`startup_ms` = process wall time minus load minus compute; `load_ms` = parse/decode into the language's
representation; `compute_ms` = the operation only (reported, ranked and used for rows/s). I/O is isolated:
compute-only ops use in-memory input; end-to-end ops (OP15–17) include file I/O and are labelled.

## Statistics **[enforced]**
Median, min, p95 and IQR/median per configuration (`runner/stats.py`); `noisy = IQR% > 10`.
Rankings use dense ranks with ties when medians fall within the noise band.

## Correctness **[enforced]**
A record is `status: ok` only if its checksum **and** row count match the expected value for that
(op, dataset, rows). Otherwise `incorrect` and it is excluded from rankings. Missing oracle ⇒ `skipped`
(never silently "ok"). Oracle: DuckDB over the same Parquet (Phase 2); in Phase 1 the harness op `OP00`
(digest of the generated table) is checked against `spec/golden.json` / the dataset manifest. Phase 2 ops are checked against `results/expected/` (DuckDB oracle, cross-checked by `runner/ref_ops.py`).
Float outputs: relative tolerance 1e-9 with a specified summation order, 1e-6 otherwise (per-op spec).

## Fairness rules
1. Same logical operation = same input, same output schema/values; algorithms free unless the op spec fixes one.
2. Idiomatic but not crippled (preallocation, proper collections, no accidental O(n²)); choices documented per language;
   disputes go in `docs/FAIRNESS_ISSUES.md`.
3. Pinned toolchains (Dockerfile/lockfile) and release builds; no `-march=native` in the primary track.
4. Hardware, container limits, governor, disk and cache state are recorded in every record.
5. Streaming is required up to 1B rows; materialized only where the estimated in-memory size fits `max_rss_gb`
   (`config/budget.yaml`); skipped combinations are recorded with a reason.

## Resource guards **[enforced]**
`generator gen` estimates output size from a measured sample and refuses (exit 2) if it exceeds free disk or
`MAX_DISK_GB`; `--dry-run` only prints the estimate; `--sink null` generates and digests on the fly without writing
(1B rows streams in ~2 minutes on 4 cores for dataset A).

## Threats to validity (to be extended with results)
Single machine and container effects; implementation-skill bias; library version effects; page-cache state;
the benchmark generator is Python-implemented (data is read from files or re-generated bit-identically by each language).
