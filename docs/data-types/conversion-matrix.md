# Cross-language conversion matrix (Dataset A)

This page covers the conversions the benchmark hits when moving `sales_fact` (Dataset A, see `PROMPT_v2.md` section 4.4) between Parquet/CSV/Arrow and each language. Dataset A types: `int64` (transaction_id, customer_id, product_id, unit_price_cents), `int32` (store_id, quantity, nullable), `float64` (discount, tax), `string` (country, category), `date`, `timestamp` (microsecond, UTC), `boolean`, plus the `decimal(18,2)` and `float64` views of `unit_price`.

Evidence labels: **observed** means the snippet was run by the author on CPython 3.11.15, Node 22.22.0, Go 1.24.7, rustc 1.97.0, OpenJDK 21.0.11 or g++ 13.3.0 (Linux x86-64). **docs** means taken from the official documentation (root URLs listed at the end). `unverified` means neither: confirm before relying on it. Type details per language live in the generated tables ([index.md](index.md)).

## 0. Summary matrix

Legend: OK = lossless; LOSS = silently lossy; ERR = raises/traps; NONE = no native type (library needed).

| Language | int64 to float64 | decimal(18,2) to float64 | timestamp us to ms / native | date epoch (day 0) | int32/int64 width and sign | string to number | boolean |
|---|---|---|---|---|---|---|---|
| C++ | LOSS above 2^53 (round to nearest) | NONE native decimal; LOSS | `chrono` any duration; us exact in `time_point<..., microseconds>` | `sys_days` 1970-01-01 | narrowing casts truncate; signed overflow UB | `strtod` locale-dependent, `from_chars` not | nonzero is true |
| Rust | LOSS (`as f64` rounds) | NONE std; `rust_decimal`; LOSS | chrono ns; us exact | chrono NaiveDate 0001-01-01 internal, API converts | `as` truncates; `try_from` errors | `parse` locale-independent, strict | only "true"/"false" |
| Java | LOSS | `BigDecimal` OK; to double LOSS | `Instant` ns exact; `java.util.Date` ms LOSS | `LocalDate.toEpochDay` 1970-01-01 | `(int)` truncates; no unsigned | `parseDouble` locale-independent, lenient | `parseBoolean` any non-"true" is false |
| C# | LOSS (`unverified`) | `decimal` OK (28-29 digits); to double LOSS (`unverified`) | `DateTime` 100 ns ticks; us exact | `DateOnly.DayNumber` from 0001-01-01 | unchecked wraps (`unverified`) | `double.Parse` culture-sensitive | `bool.Parse` accepts "True"/"False" case-insensitively (`unverified`) |
| Go | LOSS | NONE std; LOSS | `time.Time` ns; us exact | `Unix()` 1970; zero Time is year 1 | wraps; conversions truncate | `ParseFloat` locale-independent | `ParseBool` accepts 1,t,T,TRUE,true,True,0,f,F,FALSE,false,False |
| Python | LOSS (`float(int)`) | `Decimal` OK; `float()` LOSS | `datetime` us exact; ns LOSS | `date.toordinal` day 1 = 0001-01-01 | `int` unbounded; numpy wraps | `float()` locale-independent, accepts `_`, whitespace, `nan` | `bool("False")` is True |
| JavaScript | `number` LOSS above 2^53; `BigInt` OK | NONE; LOSS | `Date` ms LOSS | ms since 1970 | `number` only; bitwise ops int32 | `Number()` locale-independent; `Number('')` is 0 | `Boolean('false')` is true |
| TypeScript | same as JS (type system does not help) | same as JS | same as JS | same as JS | same as JS | same as JS | same as JS |
| Julia | LOSS (`unverified`) | NONE in Base; `FixedDecimal` package | `DateTime` ms LOSS (`unverified`) | `Dates.value` rata die (`unverified`) | wraps (`unverified`) | `parse` strict, locale-independent (`unverified`) | `parse(Bool, ...)` only "true"/"false" (`unverified`) |
| Swift | LOSS; `Double(exactly:)` is nil (`unverified`) | `Decimal` 38 digits (`unverified`) | `Date` Double seconds since 2001 (`unverified`) | reference epoch 2001-01-01 (`unverified`) | overflow traps (`unverified`) | `Double("1,5")` is nil (`unverified`) | `Bool("true")` only exact |
| Kotlin | LOSS (JVM) | `BigDecimal` | `Instant` ns; `java.util.Date` ms | `LocalDate.toEpochDay` | like Java | `toDouble()` throws, `toDoubleOrNull()` null | `toBoolean()` any non-"true" false (`unverified`) |
| Scala | LOSS (JVM) | `BigDecimal` | `Instant` ns | `LocalDate.toEpochDay` | like Java | `toDouble` throws, `toDoubleOption` | `toBoolean` throws on others (`unverified`) |
| R | integer is 32-bit; `bit64` or double: LOSS above 2^53 (`unverified`) | NONE; double LOSS | `POSIXct` double seconds: us borderline (`unverified`) | `Date` days since 1970-01-01 | no int64; int32 overflow gives NA | `as.numeric` NA with warning | `as.logical("T")` TRUE; logical is 4 bytes |
| PostgreSQL | bigint to double precision LOSS | numeric OK; to float8 LOSS | `timestamptz` us exact; no ns | internal 2000-01-01; `date` is a type | integer overflow errors | cast is locale-independent (`to_number` is locale-aware) | accepts 't','yes','on','1' |
| DuckDB | BIGINT to DOUBLE LOSS | DECIMAL(18,2) OK (int64 internally) | TIMESTAMP us exact; `TIMESTAMP_MS` LOSS | DATE int32 days since 1970-01-01 | overflow errors | `CAST` strict; `TRY_CAST` gives NULL | `CAST('t' AS BOOLEAN)` accepted (`unverified`) |
| Arrow/Parquet | int64 OK; engine cast to float64 LOSS | decimal128(18,2) OK | `timestamp[us]` OK; unit casts truncate | date32 days since 1970-01-01 | Parquet INT32/INT64 with annotations | n/a (format) | bit-packed |

## 1. int64 to float64 (loss above 2^53)

float64 has a 53-bit significand: every integer with magnitude up to 2^53 (9,007,199,254,740,992) is exact; above that, only even numbers (then multiples of 4, and so on) are representable. `transaction_id`, `customer_id`, `product_id` are small in the benchmark (up to 1e9), but `unit_price_cents * quantity` sums and the edge-case slice (max/min int64) cross the line.

```python
float(2**53 + 1)            # 9007199254740992.0      (observed)
float(2**63 - 1)            # 9.223372036854776e+18   (observed)
int(float(2**63 - 1))       # 9223372036854775808     (observed: now out of int64 range)
```
```js
Number(9007199254740993n)      // 9007199254740992 (observed)
9007199254740993               // literal parses to 9007199254740992 (observed)
```
```go
float64(int64(math.MaxInt64))  // 9.223372036854776e+18 (observed)
```
```java
(double)Long.MAX_VALUE; (long)(double)Long.MAX_VALUE   // 9.223372036854776E18, 9223372036854775807 (observed: saturating cast)
```
```rust
i64::MAX as f64               // 9223372036854775808.0 exactly; Display prints 9223372036854776000 (observed)
(i64::MAX as f64) as i64      // 9223372036854775807 (observed: float->int saturates)
```

Per-language notes:

| Language | Native conversion | Behavior |
|---|---|---|
| C++ | `static_cast<double>(i)` | rounds to nearest; `(double)INT64_MAX` is 9223372036854775808 (observed); double to int64 out of range is UB |
| Rust | `i as f64`, `f64::from(i32)` | rounds to nearest; `From<i64> for f64` does not exist (lossy), only `From<i32>`; float to int `as` saturates |
| Java | `(double) l` | rounds to nearest even; `(long) d` saturates, NaN gives 0 |
| C# | `(double) l` | rounds to nearest (`unverified`); `checked` does not catch precision loss |
| Go | `float64(i)` | rounds to nearest (observed value above); float to int out of range is implementation-defined |
| Python | `float(i)` | rounds to nearest; raises `OverflowError` only above about 1.8e308 |
| JS | `Number(bigint)`; `number` literals | rounds; `BigInt(1.5)` throws RangeError; `Number.isSafeInteger(n)` guards |
| Julia | `Float64(i)` | rounds (`unverified`); `Float64` constructor on integers may throw `InexactError` in some APIs (`unverified`) |
| Swift | `Double(i)`; `Double(exactly: i)` | `Double(i)` rounds; `exactly` returns nil on loss (`unverified`) |
| R | `as.numeric(x)` | integer64 via `bit64::as.double` loses above 2^53 (`unverified`); base R has no int64 |
| SQL | `CAST(x AS double precision)` | rounds; PostgreSQL and DuckDB both lossy (`unverified`) |
| Arrow | `pc.cast(arr, pa.float64())` | safe cast raises `ArrowInvalid` when precision is lost (default `safe=True`; `unverified` for all versions) |

Rule for the benchmark: aggregates over int64 columns use int64 accumulators (or 128-bit/decimal where overflow is possible); the float64 view is verified with a tolerance (PROMPT section 7).

## 2. decimal(18,2) to float64

`decimal(18,2)` holds up to 16 digits before the point; float64 holds about 15.95 significant digits. Values with 16 or more significant digits are altered, and even short values such as `0.10` have no exact binary form.

```python
from decimal import Decimal
float(Decimal('9999999999999999.99'))    # 1e+16               (observed: loses the cents)
float(Decimal('12345678901234567.89'))   # 1.2345678901234568e+16 (observed)
Decimal(float(Decimal('0.10')))          # 0.1000000000000000055511151231257827021181583404541015625 (observed)
```

| Language | Exact decimal option | Notes |
|---|---|---|
| C++ | none in std; Boost.Multiprecision, or int64 cents | scale tracking is manual |
| Rust | `rust_decimal` (96-bit mantissa), `bigdecimal`; or `i64` cents | `unverified` crate limits |
| Java / Kotlin / Scala | `java.math.BigDecimal`, `scala.math.BigDecimal` | construct from `String` or `BigDecimal.valueOf(double)`, never `new BigDecimal(0.1)` (observed: `0.1000000000000000055511151231257827021181583404541015625`) |
| C# | `decimal` (28-29 digits) | `(decimal)double` rounds to 15 significant digits (`unverified`) |
| Go | `shopspring/decimal` or `math/big` | none in stdlib |
| Python | `decimal.Decimal` | `Decimal(0.1)` captures binary noise (observed); use string constructor |
| JS / TS | `decimal.js`, `big.js`, or integer cents in `BigInt` | no native type |
| Julia | `FixedPointDecimals.FixedDecimal{Int64,2}` package | `unverified` |
| Swift | `Foundation.Decimal` | `unverified` |
| R | none; `gmp`, `Rmpfr`, or integer cents | DBI/arrow typically return double |
| PostgreSQL | `numeric(18,2)` | exact, variable width |
| DuckDB | `DECIMAL(18,2)` | stored as int64 internally; exact |
| Arrow/Parquet | `decimal128(18,2)`; Parquet `DECIMAL` on INT64 | exact |

The canonical data stores money as int64 cents; the decimal view must equal `cents / 100` exactly and the float64 view must be compared within tolerance.

## 3. timestamp (microsecond, UTC) to millisecond and to native types

Example value 1700000000123456 microseconds since the Unix epoch (2023-11-14T22:13:20.123456Z).

| Language | Native type | Resolution | us survives? | Observed / notes |
|---|---|---|---|---|
| C++ | `chrono::time_point<system_clock, microseconds>` | duration-defined | yes | docs; `system_clock` default is ns on libstdc++ |
| Rust | chrono `DateTime<Utc>`, `SystemTime` | ns | yes | `unverified` for crate versions |
| Java | `Instant` | ns | yes | `Instant.ofEpochSecond(1700000000L, 123456789)` prints `2023-11-14T22:13:20.123456789Z` (observed); `java.util.Date` and `Timestamp.getTime()` keep ms |
| C# | `DateTime` / `DateTimeOffset` | 100 ns ticks | yes | docs |
| Go | `time.Time` | ns | yes | `time.UnixMicro` available; `UnixNano` overflows int64 outside 1678..2262 |
| Python | `datetime` | us | yes | `fromtimestamp(1700000000.123456, utc)` gives `2023-11-14T22:13:20.123456+00:00` (observed); float seconds can mis-round the last us at large magnitude, prefer `timedelta(microseconds=...)` |
| JavaScript | `Date` | **ms** | **no** | `new Date(1700000000123456/1000).toISOString()` gives `2023-11-14T22:13:20.123Z` (observed: 456 us dropped). Keep us as `BigInt` or a `number` of microseconds (exact below 2^53 us, i.e. until year 2255) |
| Julia | `Dates.DateTime` | ms | no | `unverified`; keep Int64 micros |
| Swift | `Date` (Double seconds since 2001-01-01) | about 0.2 us at present | borderline | `unverified` |
| R | `POSIXct` (Double seconds since 1970) | about 1 us at present | borderline | `unverified`; `options(digits.secs=6)` only affects printing |
| PostgreSQL | `timestamptz` | us | yes | cannot store ns |
| DuckDB | `TIMESTAMP` / `TIMESTAMPTZ` | us | yes | `TIMESTAMP_MS` truncates |
| Arrow/Parquet | `timestamp[us]`, `TIMESTAMP(MICROS)` | us | yes | a safe cast to ms raises on loss (`safe=True` default); `safe=False` truncates |

Truncation direction: converting microseconds to milliseconds with integer division rounds toward zero in C++/Java/Go/Rust (`/`) and JS (`Math.trunc`), but toward negative infinity in Python (`//`) and `Math.floorDiv`. For timestamps before 1970 the two differ by 1 ms (for example -1 us is 0 ms truncated and -1 ms floored). Pick one rule (floor) and state it in the op spec.

Timezone: `transaction_timestamp` is UTC. Arrow `timestamp[us]` without a tz and `timestamp[us, UTC]` look alike but differ in meaning (local wall clock vs UTC instant); PostgreSQL `timestamp` ignores offsets in input; `timestamptz` renders in the session `TimeZone`. Benchmarks must pin the session zone to UTC.

## 4. date epoch differences

`transaction_date` is a calendar date (2015-01-01 to 2025-12-31). Day counts for 1970-01-01 in various systems:

| System | Day 0 / reference | Value for 1970-01-01 | Evidence |
|---|---|---|---|
| Parquet `DATE`, Arrow `date32`, DuckDB `DATE`, Java `LocalDate.toEpochDay`, R `Date` | 1970-01-01 | 0 | observed (Java `toEpochDay`: `0`); docs for others |
| Python `date.toordinal()` | 0001-01-01 is ordinal 1 | 719163 | observed |
| .NET `DateOnly.DayNumber` | 0001-01-01 is 0 | 719162 | derived from the ordinal (docs); `unverified` as run |
| Julia `Dates.value(Date)` | rata die, 0001-01-01 is 1 | 719163 | derived (`unverified`) |
| PostgreSQL internal date | 2000-01-01 | -10957 | derived from calendar (observed: `(1970-01-01 - 2000-01-01).days` is `-10957`); external API shows calendar dates |
| Swift / Foundation `Date` | 2001-01-01 00:00:00 UTC (seconds) | -978307200 s | docs (`unverified` as run) |
| Excel serial | 1899-12-30 (1900 system) | 25569 | docs (well known; `unverified` as run) |
| SAS | 1960-01-01 | -3653 | derived (`unverified`) |
| JavaScript `Date` | 1970-01-01T00:00:00Z in ms | 0 ms | docs |
| Go `time.Time` zero value | 0001-01-01 UTC | n/a (`Unix()` is -62135596800) | docs (`unverified` as run) |

Pitfalls: (a) reading `date32` as `datetime64[ns]` fails outside 1677-09-21..2262-04-11 (pandas); (b) JDBC `java.sql.Date` is a millisecond instant that shifts by timezone; (c) JS `new Date('2024-01-05')` is UTC midnight and displays as the previous day in negative-offset zones (observed ISO output `2024-01-05T00:00:00.000Z`); (d) mixing ordinal and epoch days is an off-by-719163 error; (e) year range: Python `date` 1..9999, PostgreSQL 4713 BC.. 5874897 AD, DuckDB up to year 5881580.

## 5. int32 and int64 sign and width mismatches

Dataset A columns: `store_id` and `quantity` are `int32` (quantity nullable, 0.1% nulls); ids and cents are `int64`.

```go
var i64 int64 = 1<<40 + 5; int32(i64)         // 5   (observed: silent truncation)
var u uint64 = math.MaxUint64; int64(u)       // -1  (observed)
```
```rust
(1_i64<<40) as i32                              // 0 (observed)
i32::try_from(1_i64<<40)                        // Err(TryFromIntError(PosOverflow)) (observed)
u64::MAX as i64                                 // -1 (observed)
```
```java
long l = (1L<<40)+5; (int) l                    // 5 (observed)
```
```cpp
int64_t l=(1LL<<40)+5; (int)l                   // 5 (observed, implementation-defined before C++20, modular since)
(long long)UINT64_MAX                           // -1 (observed)
```

| Language | int32 holds | int64 holds | Sign/width pitfalls |
|---|---|---|---|
| C++ | `int32_t` | `int64_t` | `long` is 4 or 8 bytes by platform; signed overflow UB; mixed signed/unsigned comparison converts to unsigned (observed `-1 < 1u` is false) |
| Rust | `i32` | `i64` | `as` truncates silently; use `try_from`; no implicit widening between signed and unsigned |
| Java | `int` | `long` | no unsigned; `(int)` truncates; `int * int` overflows before widening to long (`(long) a * b` is required) |
| C# | `int` | `long` | `uint`/`ulong` not CLS-compliant; unchecked by default (`unverified`) |
| Go | `int32` | `int64` | `int` is platform-sized; wraps (observed `MaxInt64+1` is `-9223372036854775808`) |
| Python | `int` | `int` | no widths; numpy `int32` columns overflow silently; pandas turns int columns with nulls into float64 |
| JS | `number` (int32 via `\|0`) | BigInt or lost | `quantity` fits; ids above 2^53 do not |
| Julia | `Int32` | `Int64` (`Int`) | `Int` is platform word size (`unverified`); literals default to `Int` |
| Swift | `Int32` | `Int64` / `Int` | traps on overflow (`unverified`); no implicit conversions |
| Kotlin / Scala | `Int` | `Long` | `Int * Int` overflows before widening; `Long` literal needs `L` |
| R | `integer` | none: `double` or `bit64::integer64` | NA is INT_MIN; int overflow gives NA with warning; `sum(integer)` is computed in 64-bit but returned as integer or NA (`unverified`) |
| PostgreSQL | `integer` | `bigint` | `sum(integer)` returns bigint; `sum(bigint)` returns numeric |
| DuckDB | `INTEGER` | `BIGINT` | `sum(INTEGER)` returns HUGEINT; casts out of range error |
| Arrow/Parquet | `int32` / INT32 | `int64` / INT64 | 8/16-bit and unsigned types are INT32/INT64 plus annotations |

Benchmark-specific: `sum(quantity)` over 1e9 rows reaches about 1e10, which exceeds int32; every implementation must accumulate in int64. `quantity` nulls must be skipped, not treated as 0 or INT_MIN.

## 6. string to number parsing: locale and leniency

Observed (A = accepted, value shown; E = rejected):

| Input | Python `float` | JS `Number` | Go `ParseFloat` | Rust `parse::<f64>` | Java `parseDouble` | C `strtod` (C locale) |
|---|---|---|---|---|---|---|
| `1,5` | E | NaN | E | E | E | 1 (stops at `,`) |
| `1_000` | 1000.0 | NaN | 1000 | E | E | 1 (stops at `_`) |
| ` 12 ` / ` 12` | 12.0 | 12 | E (` 12`) | E (` 12`) | 12.0 | 12 |
| `nan` / `inf` | nan / inf | NaN / NaN (`Number('inf')`) | NaN / +Inf | NaN / inf | `NaN`/`Infinity` only (`nan` is E) | nan / inf |
| `12abc` | E | NaN (`parseFloat` gives 12) | E | E | E (`12d` gives 12.0) | 12 (partial) |
| empty string | E | **0** | E | E | E | 0 |

Take-aways: (1) `Number('')` is 0 in JS; (2) C `strtod`, C++ `std::stod` and C# `double.Parse` honor the current locale (a German locale reads `1,5` as 1.5), so call `setlocale(LC_ALL, "C")` / `std::from_chars` / `CultureInfo.InvariantCulture` (docs: [cppreference strtod](https://en.cppreference.com/w/c/string/byte/strtof), [.NET numeric parsing](https://learn.microsoft.com/dotnet/standard/base-types/parsing-numeric)); (3) Python accepts underscores and Unicode digits (`float('１２')` is `12.0`, observed), Go accepted `1_000` in our run, Java accepts a trailing `d`/`f`; (4) R `as.numeric("1,5")` gives `NA` with a warning (`unverified`); (5) integer parse overflow: Go `ParseInt` returns the clamped max and an error (observed), Rust returns `PosOverflow` (observed), Java throws `NumberFormatException` (observed), Python never overflows. CSV ingestion of `unit_price` must therefore use an explicit invariant-locale parser and reject, not coerce, malformed input.

## 7. Boolean representation

| System | Storage | Text parsing | Notes |
|---|---|---|---|
| C++ | `bool` 1 byte (observed `sizeof(bool)` is 1) | nonzero integer is true (observed `(int)(bool)2` is 1) | `vector<bool>` is bit-packed |
| Rust | `bool` 1 byte | `"true"`/`"false"` only; `"True"`, `"1"`, `"yes"` are errors (observed) | |
| Java | `boolean`; 1 byte in arrays | `parseBoolean`: true only for case-insensitive `"true"`; `"yes"`, `"1"` are false without error (observed) | silent false on bad input |
| Go | `bool` 1 byte | `ParseBool` accepts `1, t, T, TRUE, true, True, 0, f, F, FALSE, false, False`; `yes` is an error (observed `t`, `TRUE`, `0`, `False`) | |
| Python | `bool` subclass of int | `bool("False")` is True (non-empty string) | `True + True == 2` (observed) |
| JavaScript | `boolean` | `Boolean('false')` is true; truthiness rules | no parser |
| R | `logical` 4 bytes with NA | `as.logical` accepts "T", "TRUE", "true", "True", "F", ...; others NA (`unverified`) | |
| PostgreSQL | 1 byte | accepts `t, true, y, yes, on, 1` and negatives (`unverified` as run) | |
| DuckDB | 1 byte in vectors | casts from VARCHAR accept `true/false/t/f` variants (`unverified`) | |
| Arrow / Parquet | 1 bit per value, bit-packed | n/a | unpack cost into 1-byte bool languages |
| CSV (Dataset A) | text | the generator writes a fixed spelling (define it in the generator spec) | every reader must parse that exact spelling |

## 8. Nulls (quantity has 0.1% nulls)

| Language | Representation used for nullable `int32` | Pitfall |
|---|---|---|
| C++ | `std::optional<int32_t>` or value + validity bitmap | optional doubles the size for 4-byte ints |
| Rust | `Option<i32>` | 8 bytes per value |
| Java / Kotlin / Scala | `Integer` / `Int?` / `Option[Int]`, or `int[]` + `BitSet` | boxing cost; unboxing null throws |
| C# | `int?` | 8 bytes |
| Go | `sql.NullInt32`, `*int32`, or value + `[]bool` | JSON/zero-value ambiguity |
| Python | `None`, pandas nullable `Int32`, or numpy masked array | default pandas converts to float64 NaN |
| JavaScript | `null` in arrays, or `Int32Array` + mask | typed arrays cannot hold null |
| Julia | `Union{Int32,Missing}` | slower than plain vectors |
| Swift | `Int32?` | 5 bytes (stride 8) |
| R | `NA_integer_` (INT_MIN sentinel) | INT_MIN cannot be a data value |
| SQL / Arrow | NULL / validity bitmap | bitmap is 1 bit per value |

## Sources and verification status

Language specifications and docs: [C++ (cppreference)](https://en.cppreference.com/), [Rust reference](https://doc.rust-lang.org/reference/), [Java (JLS and API)](https://docs.oracle.com/javase/specs/), [.NET](https://learn.microsoft.com/dotnet/), [Go spec](https://go.dev/ref/spec) and [strconv](https://pkg.go.dev/strconv), [Python](https://docs.python.org/3/), [MDN](https://developer.mozilla.org/), [Julia](https://docs.julialang.org/), [Swift](https://docs.swift.org/), [Kotlin](https://kotlinlang.org/docs/), [Scala](https://docs.scala-lang.org/), [R manuals](https://cran.r-project.org/manuals.html), [PostgreSQL](https://www.postgresql.org/docs/), [DuckDB](https://duckdb.org/docs/), [Arrow](https://arrow.apache.org/docs/) and [Parquet types](https://parquet.apache.org/docs/file-format/types/). Rows for C#, Julia, Swift, Kotlin, Scala, R, PostgreSQL, DuckDB and Arrow were not executed here and are marked `unverified` where the claim comes from memory of those docs rather than a quoted passage. When the conformance suite output in [conformance-output/](conformance-output/) disagrees with this page, the conformance output wins and this page should be fixed.
