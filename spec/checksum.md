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

## Result digests (benchmark operations)

Row-paired and standard-library friendly (only splitmix `mix64` and FNV-1a are needed); implemented in
`generator/resultdigest.py`. Result values are int64, string or NULL - **floats are never digested**.

```
canon(NULL)   = 0xA5A5A5A5A5A5A5A5
canon(int)    = value as uint64 (two's complement)       canon(bool) = 0 | 1
canon(string) = FNV-1a-64 of the UTF-8 bytes  (offset 0xCBF29CE484222325, prime 0x100000001B3)
row_hash      = h = 0; for each column v in declared order: h = mix64(h + canon(v) + GOLDEN)   (mod 2^64)
checksum      = hex16(sum of row_hash mod 2^64) + hex16(xor of row_hash)      (32 hex chars)
row_count     = number of result rows
```
mix64 and GOLDEN are those of spec/generator.md. Group-by results contribute one row per group; the order
of rows is irrelevant. Float results (e.g. OP21 `naive_sum`) are reported in the JSON line under `floats`
and compared with relative tolerance 1e-9.
