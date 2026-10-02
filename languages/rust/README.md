# Rust (std-only) - Track L, variant `stdlib`

Binary `bench` (`cargo build --release --manifest-path languages/rust/Cargo.toml`), registered as `rust`
in `impl.yaml`. No dependencies, no `unsafe`, no `target-cpu=native`. Profile: `opt-level=3`,
`lto="thin"`, `codegen-units=1`, `panic="abort"`. Single-threaded.

## Implementation notes
* Layout: `src/hash.rs` (own mix64, FNV-1a, result digest, Fx-style hasher), `src/csv.rs` (byte-level
  CSV scanning, integer/cents/date/timestamp parsing, columnar `Columns`), `src/ops.rs` (the 9 ops),
  `src/main.rs` (CLI, files, timing, JSON).
* Input: each chunk file is read whole with `std::fs::read` (~113 MB per 1M-row chunk) and scanned as bytes.
  Fields are split by hand (no quoting needed; NULL is exactly `\N`). Fields an op does not need are skipped
  by scanning to the next comma; a const-generic column mask makes this zero-cost per op.
* Parsing: integers, money (`1234.56` -> 123456 cents, no floats), dates (Hinnant `days_from_civil`) and
  timestamps (microseconds, fraction padded to 6 digits) are parsed manually. Only OP15 discount/tax use
  std `str::parse::<f64>`; sums are `floor(x*1e6+0.5)`.
* Modes: both modes parse into the same typed columns (`Vec<i64>`, `Vec<Option<i32>>`, string
  arenas + offsets, ...) and run the same op code. `materialized` loads all files, then computes;
  `streaming` loads one chunk into reused buffers, folds it into the op state, repeats; `load_ms` and
  `compute_ms` are accumulated separately. Raw rows are never retained across chunks.
* OP15 fuses read+parse+summarise (`load_ms` = 0) in both modes (one file buffer alive at a time).
* Hashing: std `HashMap`/`HashSet` with a hand-written FxHash-style `BuildHasher` (multiply/rotate, 8 bytes at a
  time, rotated in `finish`). The default SipHash-1-3 was replaced because it is DoS-resistant but several
  times slower on short keys, and the inputs here are trusted; it is the standard performance-aware choice
  in Rust, and the other languages use their native fast hashes too. Group keys are byte strings
  (`Vec<u8>` looked up by `&[u8]`, allocation only on first sight of a group); OP05 uses a
  length-delimited composite byte key.
* Digest: `mix64`, FNV-1a, row hash, sum/xor all in wrapping `u64` arithmetic. Digesting and JSON output are
  untimed; group maps are the result at the end of `compute_ms`.
* OP21: naive and Kahan sums carry across chunks in row order. OP22 uses `as` casts (round-to-nearest
  i64->f64, truncating f64->i64) and wrapping i64 arithmetic.

## Caveats / known deviations
* String arenas use `u32` offsets, limiting a materialized string column to 4 GiB of bytes (fine up to ~100M rows
  per column of this schema for materialized runs on this machine's memory anyway).
* Money fractional digits beyond two would be truncated (schema is DECIMAL(_,2)).
* Booleans are read from the first byte (`t`); no quoted CSV support.
* Materialized mode includes `Vec` growth only if `--rows` underestimates (columns are pre-reserved).
