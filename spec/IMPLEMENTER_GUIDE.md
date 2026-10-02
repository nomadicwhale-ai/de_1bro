# Implementer guide (Track L languages and Track S systems)

Read first: `spec/ops/README.md`, `spec/ops/OPxx.md` (exact semantics + DuckDB oracle SQL),
`spec/checksum.md` ("Result digests"), `generator/resultdigest.py` (reference digest),
`runner/ref_ops.py` (readable pure-Python semantics of every op), `docs/METHODOLOGY.md`.

## Directory and registration
* Track L: `languages/<lang>/`, Track S: `systems/<system>/`. Put everything there (sources, build files,
  `README.md` with an "Implementation notes" section: design choices, deviations, known unfairness).
* Register by writing `languages/<lang>/impl.yaml` (or `systems/<system>/impl.yaml`), a mapping keyed by a
  globally unique name:

```yaml
rust:                              # unique name
  track: L                         # L = language, S = data system
  variant: stdlib                  # stdlib | parallel | ecosystem | native | default
  build: ["cargo", "build", "--release", "--manifest-path", "languages/rust/Cargo.toml"]   # optional, cwd = repo root
  cmd: ["languages/rust/target/release/bench"]                 # cwd = repo root
  toolchain: {name: rustc, version_cmd: ["rustc", "--version"]}
  flags: "--release lto=thin"
  ops: [OP01, OP03, OP04, OP05, OP10, OP15, OP19, OP21, OP22]  # ops this implementation supports
  threads: [1]                     # thread counts to run (Track L stdlib: [1])
  modes: [streaming, materialized]
  input: csv                       # csv | parquet   (OP15 always reads CSV)
  max_rows: 10000000               # optional cap (e.g. SQLite)
```

## CLI contract
```
<cmd> --op OP03 --dataset A --rows 1000000 --mode streaming|materialized \
      --chunk-rows 1000000 --threads 1 --input <data dir> --output-json
```
`--input` is the data root; files are `<input>/sales_fact/<label>/part-NNNNN.{csv,parquet}` where `<label>`
is `1k|10k|1m|10m|100m|1b` for rows = 1000, 10000, 1000000, ... (sorted file names = row order).
Print **one JSON line** on stdout (anything else goes to stderr):
```json
{"load_ms": 12.3, "compute_ms": 45.6, "checksum": "<32 hex>", "row_count": 43,
 "floats": {"naive_sum": 1.5, "kahan_sum": 1.5},        // only ops with floats (OP21)
 "toolchain": {"name": "rustc", "version": "1.97.0", "flags": "--release"},
 "steady_rss_mb": 120.5, "notes": ""}                    // optional
```
Exit code 0 on success, non-zero with a message on stderr otherwise.

## Timing rules
* `materialized`: read **all** needed input into memory first (`load_ms` = read + parse into the language's
  typed in-memory representation, e.g. columnar arrays/vectors/structs), then run the operation
  (`compute_ms`). Peak RSS therefore includes the whole dataset.
* `streaming`: process chunk files one after another with bounded memory; accumulate `load_ms` (file read +
  parse) and `compute_ms` (the operation's own work: hashing, aggregating...) separately across chunks.
  Aggregation state may grow with the number of groups, but raw rows must not be retained.
* OP15 (parse CSV): parsing is the operation. Report `compute_ms` = read+parse+summarise, `load_ms` = 0.
* `compute_ms` ends when the final result rows exist in memory. **Computing the result digest and printing
  JSON are not timed** (same rule for every implementation).
* Use a monotonic clock. Do not sleep, log per row, or use threads when `--threads 1` (and no hidden
  parallelism in engines: set their thread count to `--threads`).
* Track L may skip unneeded CSV fields without converting them (cheap field skipping) but must parse every
  needed field of every row correctly; do not rely on knowing the generator's value distributions.
* Track S: use the engine's native SQL/DataFrame operations (no row loops in the host language); the data
  loading path is the engine's own reader or importer.

## Fairness and quality
Standard library only for Track L variant `stdlib` (no third-party crates/packages; write your own digest
helpers: mix64, FNV-1a, hash maps from the stdlib). Idiomatic but performance-aware code: preallocated
buffers, appropriate collections, avoid accidental O(n^2), avoid per-row allocation where the language makes
that easy. Release/optimised builds; no `-march=native`, no `unsafe`/FFI shortcuts unless essential and
documented. Money is integer cents (parse `1234.56` -> 123456 without floating point). NULL (`\N`) is
distinct from the empty string. Group keys are compared as UTF-8 bytes (no normalisation).

## Validate
```
python3 -m runner build --impl <name>
python3 -m runner run --impl <name> --rows 1k,10k,1m --runs 1 --warmup 0 --force
```
Every (op, mode, threads) must report `OK`; `INCORRECT` means your result differs from the oracle
(`results/expected/`), `SKIPPED` means data/expected result is missing. Debug by comparing against
`runner/ref_ops.py`. Also run 10m once at the end if memory/time allow (`--rows 10m`). Do not commit.
