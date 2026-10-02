# Deterministic data generator specification (v1.0.0)

Every implementation (the Python reference, the vectorised generator, and any language that
re-implements it) MUST produce **bit-identical** data. `spec/golden.json` holds the expected
digests; `tests/test_generator.py` and `python -m generator golden` enforce it.

## 1. Primitives (all arithmetic is unsigned 64-bit, wrapping)

```
GOLDEN = 0x9E3779B97F4A7C15     C1 = 0xBF58476D1CE4E5B9     C2 = 0x94D049BB133111EB
mix64(z):  z ^= z >> 30;  z *= C1;  z ^= z >> 27;  z *= C2;  z ^= z >> 31;  return z
key(seed, table_id, col) = mix64(seed XOR (((table_id << 16) | col) * GOLDEN))
rand(key, i)             = mix64(key + i * GOLDEN)          # counter-based: row i is independent
u01(x)                   = (x >> 11) * 2^-53                 # exact double in [0, 1)
```
`mix64` is the splitmix64 finaliser. `seed` defaults to `0x5EED1B20` (`BENCH_SEED`).
Table ids: sales_fact=1, dim_customer=2, dim_product=3, events_log=4, wide_numeric=5.
`col` selects an independent random stream; the column table below lists the stream numbers.

Only IEEE-754 `+ - * /`, int→double conversion and truncation are used. **No libm
(`exp`, `log`, `pow`) is used anywhere**, so all languages agree bit-for-bit.

Helpers: `rand % n` is the uniform integer in `[0, n)`. `skew(u, n, p)` = `min(n-1, trunc(double(n) * v))`
with `v = u*u` (p=2) or `v = (u*u)*u` (p=3) — a power-law-style skew, evaluated left to right.

## 2. Scale

`N` is the benchmark scale (1k … 1b). Derived: `customers = min(max(N/10,1), 50M)`,
`products = min(max(N/100,10), 1M)`, `users = max(N/100,10)`. Rows: sales_fact=N, dim_customer=customers,
dim_product=products, events_log=N, wide_numeric=N (capped at 100M unless `--allow-large-wide`).
Row index `i` is 0-based; chunking never changes the data.

## 3. Canonical value representation

money = int64 **cents**; date = int32 days since 1970-01-01; timestamp = int64 microseconds since
epoch (UTC, no zone); NULL = absent. Published files expose `unit_price` / `lifetime_value` as
`decimal(18,2)` (or float64 / cents via `--price-as`).

## 4. sales_fact (stream numbers in brackets)

| column | rule |
|---|---|
| transaction_id | `i + 1` |
| customer_id | `1 + skew(u01(rand[0]), customers, 3)` |
| product_id | `1 + rand[1] % products` |
| store_id (int32) | `1 + rand[2] % 5000` |
| base_qty | `1 + rand[3] % 20` |
| unit_price_cents | `99 + trunc(u01[4] * u01[5] * u01[6] * 999900.0)` (left-assoc) → 99..999 998 |
| discount | `d = 0 if rand[7] % 100 < 30 else rand[8] % 51`; `discount = d / 100.0` |
| country idx | `skew(u01[9], 40, 2)` into the 40-entry list in `generator/spec.py` |
| tax | `double(price_cents * base_qty * rate_bp[country idx]) / 1000000.0` (int64 product, uses base_qty) |
| category idx | `skew(u01[10], 200, 2)` → `category_000..199` |
| transaction_date | `days(2015-01-01) + rand[11] % 4018` |
| transaction_timestamp | `date * 86400e6 + (rand[12] % 86400) * 1e6 + rand[13] % 1e6` |
| is_returned | `rand[14] % 100 < 5` |
| quantity (int32, nullable) | NULL if `rand[15] % 1000 == 0`, else base_qty |
| country (nullable) | NULL if `rand[16] % 10000 == 0` |

**Edge-case slice**: rows with `i % 1000 == 999` apply pattern `p = (i / 1000) % 8` *after* the rules above
(edges override NULLs): 0 quantity=INT32_MAX; 1 quantity=INT32_MIN; 2 country=""; 3 country=`Côte d'Ivoire 🇨🇮`;
4 category=`Café` (decomposed); 5 category=`Café` (precomposed); 6 timestamp = end of its date
(`23:59:59.999999`); 7 timestamp = start of its date. At N=1000 only pattern 0 appears; all eight need N≥8000.

## 5. Dimension and other tables

* **dim_customer** (`customer_id=i+1`): name=`Customer {id}`, email=`user{id}@example.com`,
  signup_date=`days(2010-01-01) + rand[0] % 5000`, segment=`SEGMENTS[rand[1] % 6]`,
  country=`COUNTRIES[skew(u01[2],40,2)]`, lifetime_value_cents=`rand[3] % 100000000`.
* **dim_product** (`product_id=i+1`): category=`category_{skew(u01[0],200,2):03d}`, brand=`brand_{rand[1] % 500:03d}`,
  weight_grams (int32, NULL if `rand[2] % 10 == 0`)=`10 + rand[3] % 50000`, tags (list<string>) = `1 + rand[4] % 4` entries
  `TAGS[rand(key[5], i*4 + j) % 32]`, attributes (map) = `{color: COLORS[rand[6]%8], size: SIZES[rand[7]%5]}`.
* **events_log**: event_id = `1 + rand[1] % i` if `i>0 and rand[0] % 100 == 0` (≈1 % duplicate ids) else `i+1`;
  ts = `2025-01-01 + i*1000µs + rand[2] % 60e6 − 30e6` (out of order); user_id=`1 + rand[3] % users`;
  event_type=`EVENT_TYPES[rand[4] % 8]`; payload_json=`{"user":{"id":U},"action":"T","amount":A,"note":"P"}`
  with `A = rand[5] % 100000`, `P` = first `rand[6] % 451` chars of `abcdefghij`×45; session_id = UUID-shaped hex of
  `rand[7]`,`rand[8]` (`8-4-4-4-12`, lowercase, no version bits); ip = four bytes of `rand[9]` bits 24..0;
  bytes=`1 + trunc(u01[10]*u01[11]*u01[12]*u01[13] * 1e9)`.
* **wide_numeric**: `id=i+1`; `f000..f099 = u01(rand[c])`; `i00..i19 = rand[100+c] % 1000000007`.

Vocabularies (country list and tax rates, segments, event types, tags, colours, sizes) live in
`generator/spec.py` and are normative.

## 6. Files

`data/<table>/<size>/part-NNNNN.{parquet,csv,arrow}` + `manifest.json` (+ per-chunk `.meta.json` for resume).
CSV: header row, `\N` for NULL (so NULL ≠ empty string), timestamps `YYYY-MM-DD HH:MM:SS.ffffff`,
nested columns as compact JSON. Parquet: zstd, one row group per chunk. The manifest records schema,
seed, generator version, per-chunk row range, sha256 of every file and the column digests (spec/checksum.md).
