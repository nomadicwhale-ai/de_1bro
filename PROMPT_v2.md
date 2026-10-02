# Prompt: Universal Data Types and 1-Billion-Row Data Engineering Benchmark

## 0. Role and working agreement

You are a senior data/performance engineer building a reproducible, publishable benchmark repository.
Work in **phases** (section 12). After each phase: run its acceptance checks, commit, and report what passed, what failed, and what was skipped. Do not start the next phase until the current one passes.

Priorities, in order:
1. **Correctness**: every result is verified against a reference.
2. **Reproducibility**: anyone can re-run with one command and get the same data and comparable numbers.
3. **Fairness**: the rules in section 5 are enforced, not just documented.
4. **Coverage**: more languages and engines are better, but never at the cost of 1–3.

Never fabricate benchmark numbers. If something was not run, the report must say "not run" and why. Never claim a language is universally fastest; rank per workload and explain why.

## 1. Goal

Compare how programming languages (Track L) and data-processing systems (Track S) handle common data types and large-scale data-engineering operations, using identical deterministic data and identical logical operations.

Deliverables: type-comparison docs, a deterministic data generator, per-language and per-engine implementations, a benchmark runner, machine-readable results, charts, and a written report.

## 2. Scope

### Track L: programming languages (hand-written implementations)
C++, Rust, Java, C#, Go, Python, JavaScript, TypeScript (counted separately; TS compiles to JS and shares the runtime, so report it as a variant of JS), Julia, Swift, Kotlin, Scala, R.

Each language has up to three implementation variants, reported separately:
- **stdlib**: standard library only, single-threaded (the primary, fairest track)
- **idiomatic-parallel**: standard library concurrency, fixed N threads
- **ecosystem**: well-known libraries (e.g. NumPy, data.table, Eigen), clearly labeled, never mixed into the stdlib ranking

### Track S: data systems (never ranked against Track L)
PostgreSQL, DuckDB, SQLite (validation up to 10M rows only), Apache Spark (local mode and, if available, cluster), Polars, pandas, Apache Arrow (C++/PyArrow compute), ClickHouse (if installable), and a JS data library (e.g. Arquero or DuckDB-WASM) if practical.

State plainly in the report that Tracks L and S are different execution environments (query optimizers, vectorization, columnar storage, JIT, I/O layers) and are shown in separate tables.

If a toolchain cannot be installed in the environment, create the implementation anyway with a Dockerfile and mark it `status: "not_run"` with a reason. Do not silently drop it.

## 3. Common data-type comparison (documentation deliverable)

Create `docs/data-types/` containing one markdown file per category plus a generated `index.md`, and a single machine-readable `types.yaml` that the markdown is generated from (single source of truth).

Languages: all Track L languages, plus SQL (PostgreSQL, DuckDB) and Arrow/Parquet logical types as reference columns.

Concepts (each one row group; do not duplicate concepts):
signed integer (8/16/32/64), unsigned integer (8/16/32/64), 32-bit float, 64-bit float, decimal / arbitrary-precision, boolean, character (note: byte vs. UTF-16 code unit vs. Unicode scalar), string (encoding and indexing semantics), date, time, timestamp (with and without timezone, precision), nullable/optional value, fixed-size array, dynamic list/vector, tuple, struct/record, class/object, enumeration, map/dictionary (ordered vs. hash), set, binary/byte array, error/result type.

For every (concept × language) cell document:
| Field | Notes |
|---|---|
| language-specific type name | exact spelling, plus common library alternative if the stdlib has none |
| in-memory size | bytes; for variable-width types, header/overhead and typical per-element overhead |
| width | fixed or variable |
| null support | native null / optional wrapper / sentinel / none |
| primitive vs. object | value type, reference type, boxed, heap-allocated |
| typical data-engineering use | one line |
| conversion risks | overflow, signedness, truncation, locale, timezone, NaN handling |
| precision limits | e.g. 2^53 for JS `number`, float rounding, decimal scale |
| performance notes | cache behavior, boxing, GC pressure, allocation |

Required cross-cutting sections:
- "Equivalent names are not equivalent behavior": at least 8 concrete, runnable examples (e.g. integer overflow: wraps in C++/Go/Java, panics in Rust debug, arbitrary precision in Python; JS `number` loses integers above 2^53; `char` is a byte in C++, UTF-16 unit in Java/C#, Unicode scalar in Rust/Swift; string indexing O(1) bytes vs. O(n) graphemes).
- A **cross-language conversion matrix** for the Dataset A types (int64 → float64 loss, decimal → float, timestamp precision loss, date epoch differences).
- Each risk claim links to or cites the language specification or official docs. Mark any claim not verified as `unverified`.
- A small **conformance test** per language (`conformance/<lang>`) that prints the actual `sizeof`/size, overflow behavior, and 0.1+0.2 result, with the output committed under `docs/data-types/conformance-output/`. Docs must agree with the test output.

## 4. Datasets

### 4.1 Sizes
1,000; 10,000; 1,000,000; 10,000,000; 100,000,000; 1,000,000,000 rows.

### 4.2 Modes
- **Materialized**: the full dataset loaded into memory (or the engine's native storage). Allowed only where it fits in RAM; otherwise record `skipped: insufficient_memory`.
- **Streaming/chunked**: fixed chunk size (default 1,000,000 rows), single pass, bounded memory. All sizes up to 1B must be runnable in this mode.

### 4.3 Determinism contract
- Canonical PRNG: **splitmix64** seeded with `seed = 0x5EED_1B20` (documented constant), with a counter-based design so that **row i can be generated independently** from `(seed, table, column, i)`. This makes chunking, parallelism, and every language's generator produce bit-identical data.
- Reference generator in Python/NumPy-free pure code and a Rust or C++ fast generator; all other languages either read generated files or implement the same function and pass a cross-language **golden test** (first 1,000 rows + checksums of rows 0..10^6 must match exactly).
- Float columns are produced by an integer-to-float mapping defined in the spec (e.g. `(x >> 11) * 2^-53`), not by language-specific `random()` calls.
- Money is stored as **int64 cents** in the canonical data. `unit_price` is also exposed as `decimal(18,2)` and `float64` views; operations must state which view they use, and the float64 view is tested for tolerance (section 7).
- Datasets are written once to Parquet and CSV (and Arrow IPC), partitioned into chunk files, with a manifest (`manifest.json`: schema, row count, seed, generator version, per-chunk row range and xxhash64/sha256).
- Disk guard: before generating, estimate size and refuse with a clear message if free disk is insufficient. Provide `--dry-run` that prints the estimate. Print the size estimate table for all sizes in the docs (uncompressed CSV, Parquet, in-memory per language).

### 4.4 Schemas

**Dataset A: `sales_fact`**
```
transaction_id: int64            # sequential 1..N
customer_id: int64               # Zipf(s=1.1) over dim_customer (skewed)
product_id: int64                # uniform over dim_product
store_id: int32                  # uniform 1..5000
quantity: int32                  # 1..20, with 0.1% nulls
unit_price_cents: int64          # lognormal, 99..999_999; exposed as decimal(18,2) / float64
discount: float64                # 0.0..0.5, 30% exact zeros
tax: float64                     # derived from country rate
country: string                  # ~40 values, skewed
category: string                 # ~200 values
transaction_date: date           # 2015-01-01 .. 2025-12-31
transaction_timestamp: timestamp # microsecond precision, UTC, consistent with transaction_date
is_returned: boolean             # 5% true
```
Include documented null rates (e.g. `quantity` 0.1%, `discount` 0%, `country` 0.01%) and an **intentional edge-case slice** (empty strings, max/min int values, Unicode strings incl. emoji and combining characters, NaN excluded from the main slice, timestamps at date boundaries).

**Dataset B: `dim_customer`** (for joins): `customer_id`, `name`, `email`, `signup_date`, `segment` (enum, 6 values), `country`, `lifetime_value` decimal(18,2). Size = min(N/10, 50M).

**Dataset C: `dim_product`**: `product_id`, `category`, `brand`, `weight_grams` (nullable), `tags` (array of strings, nested), `attributes` (map string→string).

**Dataset D: `events_log`** (strings, JSON, time-series): `event_id`, `ts` (timestamp), `user_id`, `event_type` (enum), `payload_json` (string, 50–500 bytes), `session_id` (UUID string), `ip` (string), `bytes` (int64, heavy-tailed), with out-of-order timestamps and 1% duplicates by `event_id`.

**Dataset E: `wide_numeric`**: 100 float64 + 20 int64 columns, for columnar/SIMD/scan stress. Sizes capped at 100M rows unless disk allows more.

Joins use Dataset A × B × C. Dataset E sizes above 100M are optional.

## 5. Fairness rules (enforced by the runner, documented in `docs/METHODOLOGY.md`)

1. **Same logical operation** = same input data, same output schema and values (within section 7 tolerance). Implementations may use any algorithm that satisfies this, unless the op spec fixes the algorithm (e.g. "hash join").
2. **Idiomatic but not crippled**: use each language's standard approach with performance-aware code (preallocated buffers, appropriate collections, no accidental O(n²), no per-row logging). A short "implementation notes" file per language explains key choices and known tradeoffs. Reviewers can open issues for unfair implementations; log them in `docs/FAIRNESS_ISSUES.md`.
3. **Pinned toolchains**: exact compiler/runtime/library versions in a lockfile or Dockerfile per language; builds in release mode with documented flags (e.g. `-O3 -march=native` is *not* allowed by default because it hurts portability; use `-O3` and report a `native` variant separately if desired; Rust `--release` with `lto="thin"`; Java default JIT flags plus a documented `-Xmx`; Go default; .NET `Release`+ReadyToRun off, TieredPGO on; Python CPython 3.12, no JIT, no Cython/Numba in stdlib variant).
4. **Hardware and environment**: containers pinned to CPU/memory limits; record CPU model, core count, RAM, OS, kernel, container limits, governor, and disk type in every result file. Single-thread track uses `taskset` to pin to one core; parallel track uses fixed N (default 4 and N=physical cores).
5. **Timing boundaries** (reported separately as `load_ms`, `compute_ms`, `total_ms`): `load` includes parse/decode into the language's in-memory representation; `compute` is the operation only; process startup and JIT warmup are reported separately as `startup_ms` and excluded from `compute_ms` after warmup runs.
6. **Run protocol**: 1 discarded warmup run (cold-start measured separately), then ≥ 7 timed runs for sizes ≤ 100M and ≥ 3 for 1B. Report median, min, p95 and IQR. Flag a result as `noisy` if IQR/median > 10%. Randomize execution order of languages across repetitions to reduce thermal/ordering bias; drop page cache between cold runs when permitted and record whether the cache was warm.
7. **Memory measurement**: peak RSS via cgroup `memory.peak` (or `/usr/bin/time -v` max RSS), measured per process; for managed runtimes also record the configured heap limit. Report both peak and steady-state (post-load) memory.
8. **Throughput**: `rows/s` and `MB/s` of input processed, computed from `compute_ms`, not `total_ms`.
9. **No result may be published without passing correctness** (section 7). A failing implementation appears in reports as `INCORRECT` with its diff, not in rankings.
10. **I/O isolation**: the benchmark reads from a local NVMe/tmpfs path; report which. Compute-only ops use in-memory inputs; end-to-end ops include file read/write.

## 6. Operations (the common benchmark suite)

Every operation has an ID, an exact spec in `spec/ops/<id>.md`, a reference implementation (SQL on DuckDB as the oracle; plus a pure-Python reference for ≤ 1M rows), the expected output schema, and a checksum definition.

| ID | Operation | Dataset | Notes |
|---|---|---|---|
| OP01 | Full scan + aggregate: `count`, `sum(quantity)`, `sum(unit_price)`, `min/max` | A | float64 sum uses defined summation order or compensated (Kahan) as spec'd |
| OP02 | Filter + project: `is_returned = false AND discount > 0.1 AND country IN (...)` | A | output count + checksum |
| OP03 | Group-by low cardinality: by `country` (40 keys) | A | sum, avg, count |
| OP04 | Group-by high cardinality: by `customer_id` (~N/10 keys) | A | memory-intensive |
| OP05 | Group-by multi-key: `(country, category, year(transaction_date))` | A | date extraction cost |
| OP06 | Hash join A ⋈ B on `customer_id`, then aggregate by `segment` | A,B | |
| OP07 | Star join A ⋈ B ⋈ C, aggregate by `brand` | A,B,C | |
| OP08 | Sort by `(transaction_timestamp, transaction_id)` | A | materialized only; external sort in streaming for Track S |
| OP09 | Top-N: top 100 customers by revenue | A | |
| OP10 | Distinct count `customer_id` (exact), plus approx (HLL) where supported | A | exact result is the correctness oracle |
| OP11 | Window: running sum per customer ordered by timestamp, last-row check | A | |
| OP12 | Deduplicate `events_log` by `event_id`, keep latest `ts` | D | |
| OP13 | String ops: lowercase, substring, `contains`, regexp extract on `payload_json` | D | Unicode-correct |
| OP14 | JSON field extraction (`$.user.id`) and sum | D | parser cost |
| OP15 | Parse CSV → typed columns | A | with null handling |
| OP16 | Read Parquet → aggregate (if library available) | A | |
| OP17 | Write CSV and Parquet | A | |
| OP18 | Date/time arithmetic: bucket by hour/day, timezone conversion | A,D | |
| OP19 | Null handling: `coalesce`, `count` of nulls, null-propagating sum | A | |
| OP20 | Wide numeric scan: `sum` of 100 columns, column-wise stddev | E | SIMD/memory-bandwidth stress |
| OP21 | Decimal arithmetic: `sum(decimal(18,2))` exactness vs float64 error | A | shows precision differences |
| OP22 | Type-conversion round trip: int64 → float64 → int64, string → int, date → string → date | A | counts of lossy rows |

Track L implements OP01–OP05, OP08–OP11, OP13, OP15, OP17–OP22 (hash join OP06/07 and OP12 also required, using the language's own hash map). Track S implements all applicable ops; unsupported ops are marked `n/a`, not omitted.

Per-op, specify the exact output so results are comparable (e.g. OP03 returns rows sorted by `country` with `sum_quantity: int64`, `avg_unit_price: float64` rounded to 6 decimals).

## 7. Correctness protocol

- **Reference**: DuckDB over the same Parquet is the oracle for all aggregate/relational ops; a pure-Python reference confirms DuckDB on the 1,000 and 10,000-row sets.
- **Integer / string / date outputs must match exactly.**
- **Float outputs**: relative tolerance `1e-9` for sums with a specified summation order; `1e-6` where order differs (documented per op); NaN/Inf handling specified.
- **Order-insensitive checksum** for large result sets: `xor` + `sum` of per-row xxhash64 of the canonical serialization (spec in `spec/checksum.md`), plus row count.
- Each result record includes `checksum`, `row_count`, `expected_checksum`, and `correct: true|false`.
- CI runs the full cross-language correctness matrix at 1K and 10K rows for every implemented language and engine; a language failing correctness at any size is excluded from that op's ranking and flagged.
- Cross-language golden tests for the generator (section 4.3) are part of CI.

## 8. Scalability analysis

- Run all ops for 1K → 1B where feasible (skip with a recorded reason when RAM/disk/time budget would be exceeded; budget configured in `config/budget.yaml`: max wall time per run, max RSS, max disk).
- Report scaling exponent (log-log slope of `compute_ms` vs. rows), speedup of parallel vs. single-thread, and the **row count where materialized mode first fails** per language.
- Report memory per row (`bytes/row`) at 1M and 10M for each language and op.
- Large sizes (100M, 1B) in streaming mode report **sustained throughput** with a time series (rows/s per chunk), to expose GC pauses and throttling.

## 9. Results format (machine-readable, schema-validated)

Append-only JSON Lines at `results/raw/<run_id>.jsonl`; schema at `schema/result.schema.json`; validated in CI.

```json
{
  "run_id": "2026-10-02T12:00:00Z-abc123",
  "track": "L",
  "implementation": "rust",
  "variant": "stdlib",
  "toolchain": {"name": "rustc", "version": "1.XX.X", "flags": "--release lto=thin"},
  "op": "OP03",
  "dataset": "A",
  "rows": 10000000,
  "mode": "streaming",
  "chunk_rows": 1000000,
  "threads": 1,
  "status": "ok",
  "correct": true,
  "checksum": "…", "expected_checksum": "…",
  "startup_ms": 12.1, "load_ms": 840.2, "compute_ms": 311.5, "total_ms": 1163.8,
  "runs": [311.5, 309.0, 315.2],
  "median_ms": 311.5, "min_ms": 309.0, "p95_ms": 315.2, "iqr_pct": 1.4, "noisy": false,
  "rows_per_s": 32102568, "mb_per_s": 2310.4,
  "peak_rss_mb": 412, "steady_rss_mb": 220,
  "env": {"cpu": "…", "cores": 8, "ram_gb": 32, "os": "…", "container_limits": "…", "disk": "nvme", "cache": "warm"},
  "skip_reason": null
}
```
Also emit aggregated `results/summary.csv` and `results/summary.json`. Raw results are immutable; derived artifacts are regenerated by `make report`.

## 10. Ranking and reporting

- **Rank per operation and per size**, separately for: Track L stdlib, Track L parallel, Track L ecosystem, Track S. Show rank, median, ratio to best, memory, and a confidence flag. Use **dense ranking with ties** when medians are within the noise band (IQR overlap).
- No overall "winner". If a composite is shown, label it clearly (e.g. geometric mean of per-op ratios among ops where all listed implementations are correct), with the list of included ops, and never as the headline.
- **Explain differences** for each op in `report/explanations/<op>.md`: concrete mechanisms (GC vs. manual memory, hash-map implementation, SIMD autovectorization, boxing, string encoding cost, JIT warmup, runtime startup, parallel runtime overhead, columnar vs. row layout, vectorized execution, spill-to-disk), supported by profiler evidence (e.g. `perf stat` counters or flame graph) for at least the top and bottom implementation per op, or explicitly marked as hypothesis.
- **Charts** (generated from `results/summary.json` only; reproducible script at `report/make_charts.py`):
  - bar chart per op at fixed size (log scale) with error bars
  - scaling lines (rows vs. time, log-log) per op
  - throughput vs. rows
  - memory vs. rows
  - heatmap: implementation × op (ratio to best)
  - streaming throughput time-series
  - data-type conversion-loss chart
  Charts must be colorblind-safe, have titled axes with units, and a caption stating the environment.
- **Report**: `report/REPORT.md` (and HTML export) with: methodology summary, environment, limitations, per-op tables, per-op explanations, data-type findings, threats to validity (single machine, container effects, implementation skill bias, library version effects, cache effects), and reproduction instructions. State whenever a result is not statistically distinguishable.
- Include a **"Surprising results"** section only when each one has a verified explanation or is labeled unexplained.

## 11. Repository layout and engineering requirements

```
.
├── README.md
├── Makefile                      # make setup | gen | test | bench | report | clean
├── config/{budget.yaml,env.yaml,ops.yaml}
├── docs/{METHODOLOGY.md,FAIRNESS_ISSUES.md,data-types/}
├── spec/{ops/,checksum.md,generator.md}
├── schema/result.schema.json
├── generator/                    # reference + fast generator + golden tests
├── languages/<lang>/{Dockerfile,README.md,src/,tests/}
├── systems/<engine>/{Dockerfile,README.md,sql_or_src/}
├── runner/                       # orchestrates builds, runs, timing, memory, validation
├── conformance/<lang>/
├── results/{raw/,summary.*}
├── report/{REPORT.md,make_charts.py,explanations/,charts/}
└── .github/workflows/ci.yml
```
- Each language/engine is a container (reproducible, pinned) with a **uniform CLI contract**:
  `bench --op OP03 --dataset A --rows 10000000 --mode streaming --chunk-rows 1000000 --threads 1 --input <manifest> --output-json`
  The runner owns timing of the process boundary and memory; the implementation reports its own internal `load_ms`/`compute_ms`. Output is a single JSON line on stdout.
- Runner features: resumable (skips completed run keys), per-run timeout, memory limit, structured logs, `--dry-run`, `--only lang=rust,op=OP03`, deterministic ordering with seeded shuffle, and a `--smoke` profile (1K–10K rows, all implementations, < 10 min total).
- CI: lint/format per language, generator golden tests, correctness matrix at 1K/10K, schema validation of result files, and building every Dockerfile. Large benchmarks are never run in CI.
- Code quality: no benchmark code shares helper libraries across languages that would bias timing; no `unsafe`/FFI shortcuts in the stdlib variant unless documented; tests per implementation; each README documents design choices and known deviations.
- Licenses and attribution for any third-party dataset/library; no network access required during timed runs.

## 12. Phased delivery plan (acceptance criteria per phase)

**Phase 1 – Foundations** (must complete first)
- Repo skeleton, Makefile, config, schemas, methodology doc, runner skeleton.
- Data-type docs for all concepts and languages from `types.yaml`, plus conformance tests for every language whose toolchain is installable.
- Deterministic generator (splitmix64 counter-based), golden tests, manifest, Parquet/CSV writer, disk guard and size-estimate table.
- Acceptance: generator output identical across two independent implementations; `make gen SIZE=1m` works; docs build; schema validates.

**Phase 2 – Vertical slice**
- Languages: Python, Rust, Go; systems: DuckDB, Polars, SQLite.
- Ops: OP01–OP05, OP10, OP15, OP19, OP21, OP22.
- Sizes: 1K–10M; materialized and streaming.
- Acceptance: all outputs correct vs. oracle; results schema valid; first charts and a draft report produced.

**Phase 3 – Breadth**
- Remaining languages and engines (PostgreSQL, Spark, pandas, Arrow, ClickHouse if available, JS libs).
- Remaining ops (OP06–OP09, OP11–OP14, OP16–OP18, OP20).
- Sizes up to 100M.
- Acceptance: full correctness matrix passes at 1K/10K; each skipped combination recorded with reason.

**Phase 4 – Scale and analysis**
- 100M and 1B streaming runs where hardware allows; parallel track; scaling analysis; profiler evidence; full report and explanations.
- Acceptance: `make report` regenerates all tables/charts from `results/` alone; report passes the section 10 checklist.

At the end of each phase, output a status table (language/engine × op × size: `ok | skipped(reason) | failed | not_run`).

## 13. Assumptions to state up front (and ask if they block progress)

Before starting, print assumptions and confirm or proceed with defaults:
- Target hardware and disk budget (default: this machine; record specs; 1B runs only if free disk ≥ 2× estimated Parquet size, otherwise generate on the fly in streaming mode without persisting).
- Which toolchains are installable here; list the ones that are not and how they are handled (Dockerfile + `not_run`).
- Whether native-CPU-flag variants are wanted in addition to portable builds (default: portable only).
- Whether benchmarks should run in-process or via the CLI contract (default: CLI contract).

## 14. Definition of done

- `make setup && make smoke && make report` works from a clean clone.
- Every published number comes from `results/raw/`, passes correctness, and has environment metadata.
- The data-type docs are generated from `types.yaml` and agree with conformance-test output.
- No unsupported claims; every ranking is per workload with explanation or an explicit "unexplained" label.
- Limitations and threats to validity are documented.
