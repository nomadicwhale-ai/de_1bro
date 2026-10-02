# Python (CPython 3.11, standard library only)

Track L, variant `stdlib`, name `python`. Single file `bench.py`; no third-party packages.
Run through the runner: `python3 -m runner run --impl python --rows 1k,10k,1m --runs 1 --warmup 0 --force`.

## Implementation notes
* Reading: `csv.reader` over the chunk files (sorted names), consumed in batches of 65 536 rows and
  transposed with `zip(*batch)`, so conversion runs column-wise with `map`/comprehensions (C-level loops).
  Only the columns an op needs are converted; other fields are skipped untouched.
* Money: integer cents by `s.replace(".", "")` when the text has exactly two decimals (`s[-3] == "."`),
  with a slower exact fallback for other shapes. No floats.
* Dates/timestamps: no `datetime`. `YYYY-MM-DD` -> days via Hinnant `days_from_civil`, memoised in a dict
  (a few thousand distinct dates); `HH:MM:SS` seconds-of-day memoised; fractional microseconds sliced
  (`s[20:26]`, the generator's fixed 6-digit format is assumed). Year / y-m-d use `civil_from_days`,
  memoised per distinct day (OP05) or applied to per-day counts (OP22).
* Streaming: per chunk file, `load_ms` = read+parse+type conversion into column lists, `compute_ms` =
  the op (group-by dict updates, set unions, loops). Raw rows are dropped after each file.
  Materialized: all needed converted columns for all files are loaded first, then one compute pass.
* OP15 (both modes): read+parse+summarise timed as `compute_ms`, `load_ms` = 0, batch-bounded memory.
* NULL (`\N`) becomes `None`; empty strings stay `""`. Group keys are Python `str` (Unicode code points,
  equal iff UTF-8 bytes equal; no normalisation). Byte lengths use `str.encode`.
* OP21 uses an explicit left-to-right loop for naive and Kahan sums (not `sum()`, whose float behaviour
  changed in 3.12). OP22 uses the exact int/float comparison `float(k) != k` (equivalent to
  `int(float(k)) != k`).
* Digest (mix64, FNV-1a, row hash) is own code in `bench.py`; `generator.resultdigest` is not imported.
  Digest/JSON are outside the timed region.
* `gc.disable()` during the run (no cyclic garbage is created; avoids GC scans of huge containers).

## Known unfairness / caveats
* Interpreter speed: per-row work in pure Python is orders of magnitude slower than compiled languages;
  the batch/`zip(*rows)`/`map` structure is the main mitigation.
* `csv.reader` creates 13 `str` objects per row even for skipped columns (the reader is C but cannot skip).
* Memory: materialized mode keeps Python int/str objects (28+ bytes each), much larger than typed arrays.
* Fraction digits of timestamps and 2-decimal money are assumed to follow the generator's canonical format
  (money has a slow fallback; timestamps do not).
