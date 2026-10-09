# Java (Track L, variants `stdlib` and `tuned`)

Registered as `java` in `impl.yaml`. Java 21, JDK only (no jars). Build: `javac -d languages/java/build languages/java/src/*.java`
(output is git-ignored). Run: `java -Xmx6g -XX:+UseSerialGC -cp languages/java/build Bench ...`.
All 13 ops (OP01 OP03-OP10 OP15 OP19 OP21 OP22), modes streaming + materialized (OP08 materialized only), threads 1.

## Implementation notes
* **JIT/startup are included.** Every measurement is a fresh JVM process, so interpreter warm-up and C1/C2 compilation
  happen inside the timed `load_ms`/`compute_ms` (no in-process warm-up). Small sizes (1k, 10k) are dominated by JIT warm-up;
  tight loops (OP15, the parse) get faster as the run proceeds. JVM start itself (~40 ms) is outside the timers.
* **GC: `-XX:+UseSerialGC -Xmx6g`.** Serial (single-threaded, stop-the-world) GC so no concurrent GC threads use other
  cores, which keeps the single-thread comparison fair; the default G1 would use background workers. The heap is capped
  at 6 GB. JIT compiler threads still run in the background (not controllable without `-Xint`, which would be unfair).
* **Own primitives**: `mix64`, FNV-1a, the row/result digest (`Digest.java`), an open-addressing `long -> dense int` map
  (`LMap.java`, linear probing, also used as a long set), byte-string dictionary with FNV-1a over raw bytes (`Csv.Dict`),
  and hand-written CSV scanning over `byte[]` (no `String.split`, no regex, no `BufferedReader`/`Scanner`); integer, cents
  (no floating point), date (Hinnant) and timestamp parsers. `Double.parseDouble` is used only for `discount`/`tax` in OP15
  (`floor(x*1e6+0.5)`; Java arithmetic is strict IEEE so there is no FMA).
* **I/O**: each chunk file is read whole (`RandomAccessFile.readFully`) into a reused `byte[]` (about one chunk of memory
  in streaming mode; dropped before compute in materialized mode).
* **Columnar batch**: primitive arrays (`long[]`, `int[]`, `boolean[]`) for the needed columns only; other fields are skipped
  without conversion and scanning stops after the last needed field. `country`/`category` are dictionary-encoded to int codes
  during parse (NULL = -1), so OP03/OP19 have a cheap compute phase and the hashing cost lands in `load_ms`.
* **Group-by / distinct**: `LMap` (primitive, no boxing) for OP04/OP09 (customer_id), OP10 (customer, product, packed
  store/date), and OP05 (country code, category code, year packed into one long). OP09 keeps the top 100 with a bounded
  `PriorityQueue`.
* **Joins (OP06/OP07)**: dimension tables are loaded first (counted in `load_ms`), reading only the leading fields
  (id, segment / brand) and ignoring the quoted JSON tail; probes use `LMap` id -> row, with attribute dictionary codes.
* **OP08**: standard library sort: `Arrays.sort(Integer[], Comparator)` (TimSort) on boxed row indexes comparing
  `(ts, transaction_id)`; the baseline uses boxed indices to carry the two keys. It is slow (about 3 s at 1m, about 19 s at 10m)
  and allocation heavy; this is the idiomatic stdlib result, left as is. Position sum uses wrapping `long` arithmetic.
* **Modes**: streaming parses one chunk into a reused batch, aggregates, repeats; materialized parses all chunks into one
  batch preallocated for `--rows`, then aggregates once. Same parse/aggregation code in both.
* **OP15** fuses parse and summarise per row (all 13 columns converted), `load_ms = 0`.
* `compute_ms` includes building the result rows but not the digest or JSON output.

## Tuned variant
* `java-tuned`, variant `tuned`, supports only OP08, materialized mode, one thread. Same parser, JVM flags,
  timing boundaries and result digest as `java`; `--variant tuned` selects it (runner adds it).
* `PrimitiveSort.java` performs a bottom-up merge sort on two primitive `int[]` index buffers, comparing
  the original full signed `long` timestamp then transaction id. No boxed indices, key packing, precision
  loss, assumptions about generator ranges, libraries or parallelism. Auxiliary indexes use 8 bytes/row.
* Allocating buffers, sorting, wrapping positional sum and result creation are timed as `compute_ms`;
  digest and JSON are outside timing. The original `Ops.Op08` boxed-index stdlib sort is unchanged.
* Report tables/charts/ranks keep `stdlib` and `tuned` separate. Acceptance validation at 1k/10k/1m is
  pending a JDK in the author environment. Reproduce: `python -m runner run --impl java,java-tuned --rows 1k,10k,1m --runs 1 --warmup 0 --force`.

## Known limitations / unfairness
* CSV parsing assumes no quoted fields in sales_fact/dim_customer (generator never emits them); `\r\n` is tolerated.
  Non-nullable columns containing `\N` are rejected.
* `java -version` prints a `Picked up JAVA_TOOL_OPTIONS` line on stderr in some sandboxes; the registered `version_cmd`
  filters it out.
* Results are per fresh process, so JIT warm-up is part of every number (see above).
