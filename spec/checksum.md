# Order-insensitive digests

Used for generator golden tests, dataset manifests and (with the same rules) operation results.

Per column: `sum` = Σ over rows of the canonical 64-bit value, mod 2^64, plus `nulls` = number of NULLs.

| type | canonical 64-bit value |
|---|---|
| int8..int64, bool | two's-complement of the value widened to int64, as uint64 (bool: 0/1) |
| date | days since epoch, same rule |
| timestamp | microseconds since epoch, same rule |
| money | int64 cents |
| float64 | the raw IEEE-754 bits |
| string | `XXH64(utf8 bytes, seed=0)` |
| list<string> | XXH64 of the items joined with `\x1f` |
| map<string,string> | XXH64 of `k=v` pairs joined with `\x1f` |
| NULL | contributes 0 |

`table_digest` = XXH64 of the text `col=<sum as 16 hex>:<nulls>|col=...` in schema order.
Digests of disjoint row ranges add column-wise, so chunking never matters. A digest covers *content*,
not row order; row-level equality is covered by the golden tests (first rows compared exactly).

Operation results (benchmarks) use the same machinery over the result rows with float columns first
rounded as specified in `spec/ops/<id>.md` (to be added in Phase 2).
