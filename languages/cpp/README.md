# C++20 (stdlib only) - Track L

Build: `g++ -std=c++20 -O3 -DNDEBUG` (no `-march=native`). Sources: `src/` (single translation unit:
`main.cpp` + header files `digest.hpp`, `parse.hpp`, `ops.hpp`), binary `bin/bench`.

## Implementation notes
* Parsing: each chunk file is read whole into a reusable `std::vector<char>`; rows are split with `memchr`
  and fields are `string_view`s parsed by hand (ints, money -> cents without floating point, dates via
  Hinnant's algorithms, timestamps). Unneeded trailing columns are not visited; unneeded middle fields are
  skipped without conversion. No iostream, regex, `stod`. OP15 parses doubles with `std::from_chars`.
* Columns are `std::vector`s (struct of arrays); strings (country/category/segment/brand) are
  dictionary-encoded; group keys therefore compare as bytes via the dictionary.
* Hash maps: `std::unordered_map` / `std::unordered_set` (node-based, libstdc++). Note libstdc++'s default
  `std::hash<int64_t>` is the identity function (bucket = key mod prime), no mixing. No custom map was written.
  This is slower than flat/open-addressing maps (Rust/Go) for OP04/OP09/OP10 - intentional "idiomatic stdlib".
* Streaming: per-chunk batch reused, dictionaries/aggregates persist. Materialized: all rows loaded
  (reserved by `--rows`), then one consume pass. OP08 (materialized only) sorts a `vector<{ts,id}>` with
  `std::sort`; positional sum uses wrapping uint64.
* Joins (OP06/OP07): dimension tables loaded first (counted in `load_ms`) into `unordered_map<id, code>`;
  dim_customer reads fields 0 and 4, dim_product fields 0-2 (quoted tail ignored).
* OP22 uses wrapping unsigned multiply for `tid*4294967311+cid`; `floorE6` goes through a `volatile` to
  forbid FMA contraction. Digest (mix64, FNV-1a) is own code, not timed.
* Single-threaded; `--threads`/`--chunk-rows` accepted and ignored.
