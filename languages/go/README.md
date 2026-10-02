# Go (Track L, variant `stdlib`)

Registered as `go` in `impl.yaml`. Go 1.24, standard library only (`go.mod` has no dependencies).
Build: `go build -C languages/go -trimpath -o bin/bench .` (output `languages/go/bin/bench`, git-ignored).

## Implementation notes
* **Single goroutine, default GOMAXPROCS.** The algorithm never starts goroutines. `GOMAXPROCS` is left at the
  Go default so the garbage collector can use its background workers, as an ordinary Go program would. When the
  runner pins the process to one CPU (`taskset`, `SINGLE_THREAD_CPU`), Go sees the affinity mask and
  GOMAXPROCS becomes 1 automatically, so GC then shares that core (this is what the runner measures). The value
  used is echoed in the JSON `notes` field.
* **Own primitives**: `mix64`, FNV-1a, row hash/digest (`digest.go`), CSV field splitting over `[]byte`
  (`bytes.IndexByte` per field, no `encoding/csv`), integer, cents (no floating point), date
  (Hinnant days_from_civil / civil_from_days) and `YYYY-MM-DD HH:MM:SS[.ffffff]` timestamp parsers.
  `strconv.ParseFloat` is used only for `discount`/`tax` in OP15; `floor(x*1e6+0.5)` uses an explicit
  `float64()` conversion so no architecture can fuse the multiply-add.
* **I/O**: each chunk file is read whole with `os.Open` + `io.ReadFull` into a reused buffer (one chunk, ~100 MB
  per 1M rows, is the streaming memory bound; the buffer is dropped before compute in materialized mode).
* **Columnar batch**: needed columns only (others are skipped without conversion, scanning stops after the last
  needed field of a row). `country`/`category` are dictionary-encoded into int32 codes using a stdlib
  `map[string]int32` (lookups with `m[string(b)]` do not allocate); NULL = code -1. The dictionary is built in
  the load/parse phase, so OP03 (array indexed by code) and OP19 (distinct = seen bitmap over codes) have a very
  cheap compute phase while parse carries the hashing cost. Group-by on `customer_id` uses `map[int64]int32`
  into dense accumulator slices; OP05 uses `map[[3]int32]int32`; OP10 uses `map[int64]struct{}` and a packed
  `uint64` (store, date) key.
* **Modes**: streaming parses one chunk file into a reused batch, aggregates, repeats (rows are not retained;
  aggregation state, dictionaries and group maps persist). Materialized parses every file into one batch
  preallocated for `--rows`, then runs the operation once. Both modes share the same parse and aggregation code.
* **OP15** fuses parse and summarise per row (all 13 columns converted) and reports `load_ms = 0` in both modes.
* `compute_ms` includes building the result rows (e.g. strings for group keys) but not the digest or JSON output.
* No `unsafe`, no cgo, no assembly. Build flags: `-trimpath` only (default optimisation).

## Known limitations / unfairness
* CSV parsing assumes no quoted fields (the generator never emits quotes, commas or newlines inside values);
  `\r\n` line ends are tolerated. Non-nullable columns that contain `\N` are rejected with an error.
* The Go GC runs concurrently with the work; on a pinned single CPU its cost is included in the timings.
* Dictionary encoding of strings (also done by several other Track L implementations in spirit) favours OP03/OP19
  compute time relative to implementations that hash raw bytes per row; the cost moves into `load_ms`.
