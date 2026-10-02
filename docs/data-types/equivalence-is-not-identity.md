# Equivalent names are not equivalent behavior

Two languages can both offer a type called `int`, `string` or `timestamp` and still disagree on size, overflow, indexing, rounding, null handling and ordering. Each example below is small, runnable, and states the output observed on the machine used to write this page.

Observed with: CPython 3.11.15, Node.js 22.22.0, Go 1.24.7, rustc 1.97.0, OpenJDK 21.0.11, g++ 13.3.0 on Linux x86-64. Languages whose toolchain was not available here (C#, Swift, Julia, Kotlin, Scala, R, SQL engines) are described from documentation and every such claim is marked `unverified` (meaning: not executed by the author, cited to docs only). Re-run any snippet to confirm on your own toolchain; see [conformance-output/](conformance-output/) for the conformance suite output.

Documentation roots used throughout: [cppreference](https://en.cppreference.com/), [Rust reference](https://doc.rust-lang.org/reference/), [JLS](https://docs.oracle.com/javase/specs/), [.NET docs](https://learn.microsoft.com/dotnet/), [Go spec](https://go.dev/ref/spec), [Python docs](https://docs.python.org/3/), [MDN](https://developer.mozilla.org/), [Julia docs](https://docs.julialang.org/), [Swift docs](https://docs.swift.org/), [Kotlin docs](https://kotlinlang.org/docs/), [Scala docs](https://docs.scala-lang.org/), [R manuals](https://cran.r-project.org/manuals.html), [PostgreSQL docs](https://www.postgresql.org/docs/), [DuckDB docs](https://duckdb.org/docs/), [Arrow docs](https://arrow.apache.org/docs/).

## 1. Integer overflow: wrap, trap, UB or grow

Add 1 to the largest 32-bit signed integer.

| Language | Behavior | Observed |
|---|---|---|
| Java | wraps (JLS 15.18.2); `Math.addExact` throws | `-2147483648`; `integer overflow` |
| Go | wraps by definition (spec: Arithmetic operators) | `-2147483648`; `uint8(255)+1` is `0` |
| Rust | panics in debug builds, wraps in release; explicit `checked_`/`wrapping_` methods | debug: panic `attempt to add with overflow`; release (`rustc -O`): wraps to `-2147483648`; `checked_add` gives `None` |
| C++ | signed overflow is undefined behavior; unsigned wraps | `uint32_t` max + 1 is `0`; signed needs `__builtin_add_overflow` or a pre-check |
| Python | `int` never overflows | `2**31 + 1` is `2147483649`; `2**63 + 1` is `9223372036854775809` |
| JavaScript | `number` is a double; bitwise ops coerce to int32 | `(2**31)\|0` is `-2147483648`; `2147483647+1` is `2147483648` (no wrap) |
| C# | unchecked by default (wraps); `checked` throws `OverflowException` | `unverified` (not run) |
| Swift | traps at runtime; `&+` wraps | `unverified` (not run) |
| PostgreSQL / DuckDB | raise an out-of-range error | `unverified` (not run) |

```java
int x = Integer.MAX_VALUE; x++;                 // -2147483648
Math.addExact(Integer.MAX_VALUE, 1);            // ArithmeticException: integer overflow
```
```rust
let x: i32 = i32::MAX;
println!("{:?} {:?} {}", x.checked_add(1), x.overflowing_add(1), x.wrapping_add(1));
// None (-2147483648, true) -2147483648
```
```go
var x int32 = math.MaxInt32; x++ // -2147483648
```
```cpp
int r; bool o = __builtin_add_overflow(INT_MAX, 1, &r);  // o == 1; plain INT_MAX+1 is UB
```

Why it matters: an aggregation such as `sum(quantity)` can silently wrap in Java/Go/C#, panic in Rust debug, be undefined in C++, or fail loudly in SQL. Benchmarks must state the accumulator width.

## 2. JavaScript `number` is a double: integers are exact only to 2^53

```js
console.log(2**53, 2**53 + 1, 9007199254740993, 9007199254740993n, Number.MAX_SAFE_INTEGER);
// 9007199254740992 9007199254740992 9007199254740992 9007199254740993n 9007199254740991
```
```python
float(2**53 + 1)   # 9007199254740992.0 (the +1 is lost on conversion)
```
```java
long big = (1L << 53) + 1; (long)(double)big   // 9007199254740992
```

Any int64 id above 2^53 round-trips incorrectly through a JS `number` or any float64 (see [conversion-matrix.md](conversion-matrix.md)). Use `BigInt`, strings, or two 32-bit halves. Source: [MDN Number.MAX_SAFE_INTEGER](https://developer.mozilla.org/docs/Web/JavaScript/Reference/Global_Objects/Number/MAX_SAFE_INTEGER).

## 3. What a "character" is

| Language | Type | Meaning |
|---|---|---|
| C++ | `char` | one byte (`sizeof` is 1); `wchar_t` is 4 here (2 on Windows) |
| Java / C# / Kotlin / Scala / JS | `char` (JS: string unit) | one UTF-16 code unit |
| Rust | `char` | 4-byte Unicode scalar value |
| Go | `rune` (`int32`) | Unicode code point; `byte` is `uint8` |
| Swift | `Character` | extended grapheme cluster (`unverified`: not run) |
| Julia | `Char` | 32-bit code point (`unverified`: not run) |
| Python | none | a `str` of length 1 (one code point) |

## 4. String length and indexing for `"😀"` and for `e` + combining accent

```python
s = "😀"; len(s), len(s.encode())            # (1, 4)  code points, UTF-8 bytes
len("é"), len("é"), "é" == "é"   # (2, 1, False)
```
```js
"😀".length, [..."😀"].length, "é".length                 // 2 1 2  (UTF-16 units, code points, units)
"é" === "é", "é".normalize() === "é"    // false true
```
```java
String s = "😀";
s.length() + " " + s.codePointCount(0, s.length()) + " " + s.getBytes(UTF_8).length   // 2 1 4
```
```go
s := "😀"; len(s), utf8.RuneCountInString(s)   // 4 1   (bytes, runes)
```
```rust
let s = "😀"; (s.len(), s.chars().count());          // (4, 1)
let t = "e\u{301}"; (t.len(), t.chars().count());    // (3, 2)
```
```cpp
std::string s = "\xF0\x9F\x98\x80"; s.size();       // 4 (bytes; no Unicode awareness)
```

The same visible text has length 1, 2, 3 or 4 depending on the language and unit. Indexing is O(1) per unit in all of the above, but in Swift `count` is O(n) in grapheme clusters and there is no integer subscript (`unverified`: not run; see [Swift docs](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/stringsandcharacters/)). Canonical equivalence (`é` vs `e` + U+0301) is not applied by default anywhere in this list except Swift `==`.

## 5. `0.1 + 0.2`

```python
0.1 + 0.2            # 0.30000000000000004
```
Observed `0.30000000000000004` and `== 0.3` false in Python, JavaScript, Java, Rust, C++ (with non-constant operands). Go is a trap: with variables `a, b := 0.1, 0.2` the sum is `0.30000000000000004` and `a+b == 0.3` is `false`, but the constant expression `0.1 + 0.2 == 0.3` is evaluated with exact arbitrary-precision constants at compile time and is `true` ([Go spec: Constant expressions](https://go.dev/ref/spec#Constant_expressions)). R prints `0.3` by default (7 significant digits) while `0.1 + 0.2 == 0.3` is `FALSE` (`unverified`: not run; `isTRUE(all.equal(...))` is the idiom).

## 6. float32 rounding

```python
import struct
struct.unpack('f', struct.pack('f', 16777217.0))[0]   # 16777216.0   (2^24 + 1 not representable)
struct.unpack('f', struct.pack('f', 0.1))[0]          # 0.10000000149011612
```
```java
(float)16777217 + " " + (double)0.1f      // 1.6777216E7 0.10000000149011612
```
```rust
16777217_i32 as f32   // 16777216
```
```js
Math.fround(16777217)   // 16777216
Math.fround(0.1)        // 0.10000000149011612
```

Integers are exact in float32 only up to 2^24, and `0.1f` widened to double shows its true value. R and Python have no float32 scalar, so a Parquet `FLOAT` column read into them is widened and the artifact becomes visible.

## 7. Integer division and modulo of negatives

| Expression `-7 / 2`, `-7 % 2` | Result | Rounding |
|---|---|---|
| C++, Java, Go, Rust, JS (`%`) | `-3`, `-1` | truncate toward zero; remainder takes the sign of the dividend |
| Python (`//`, `%`) | `-4`, `1` | floor; remainder takes the sign of the divisor |
| Rust `div_euclid` / `rem_euclid` | `-4`, `1` | Euclidean |
| Java `Math.floorDiv` / `floorMod` | `-4`, `1` | floor |
| JavaScript `/` | `-3.5` | `/` is always floating point; `Math.trunc(-7/2)` is `-3` |
| R (`%/%`, `%%`) | `-4`, `1` | floor (`unverified`: not run) |
| Julia (`÷`, `%`, `mod`) | `-3`, `-1`; `mod(-7,2)` is `1` | truncating `÷`/`%` (`unverified`: not run) |
| PostgreSQL (`/`, `%`) | `-3`, `-1` | truncate (`unverified`: not run) |
| DuckDB (`/` on integers) | `-3.5` (returns DOUBLE) | `//` is integer division (`unverified`: not run) |

A hash-bucket function `hash % n` with a negative hash yields a negative index in C++/Java/Go/Rust/JS but not in Python. Use `rem_euclid`, `Math.floorMod`, or an unsigned hash.

## 8. Timestamp precision and timezone

A Parquet/Arrow microsecond timestamp such as `1700000000123456` (2023-11-14 22:13:20.123456 UTC):

```python
import datetime
datetime.datetime.fromtimestamp(1700000000.123456, datetime.timezone.utc).isoformat()
# '2023-11-14T22:13:20.123456+00:00'   (microsecond precision, aware UTC)
```
```js
new Date(1700000000123.456).getTime()   // 1700000000123   (milliseconds; .456 is lost)
```
```java
Instant.ofEpochSecond(1700000000L, 123456789).toString()   // 2023-11-14T22:13:20.123456789Z  (nanoseconds)
```

JS `Date` is millisecond-only; Java `Instant` is nanosecond; Python `datetime` is microsecond; .NET `DateTime` ticks are 100 ns; PostgreSQL stores microseconds (no nanoseconds). A timestamp "without timezone" (Arrow `timestamp[us]`, PostgreSQL `timestamp`) is a wall-clock reading; a timestamp "with timezone" (Arrow `timestamp[us, tz]`, PostgreSQL `timestamptz`) is a UTC instant and does not store the zone name. Parsing a naive string with the wrong assumption shifts every value by the offset. A date-only JS string is parsed as UTC while a date-time without offset is parsed as local time:

```js
new Date('2024-01-05').toISOString()   // 2024-01-05T00:00:00.000Z
```

## 9. `null` is not `NaN` (and neither equals itself)

```python
float('nan') == float('nan'), None == None     # (False, True)
```
```js
NaN === NaN, Object.is(NaN, NaN), null == undefined, typeof null   // false true true 'object'
```
```go
n := math.NaN(); n == n     // false
```
```java
Double.NaN == Double.NaN                               // false
Double.valueOf(Double.NaN).equals(Double.NaN)           // true (equals uses bit comparison)
```

SQL `NULL = NULL` is `NULL` (not true), PostgreSQL and DuckDB sort `NaN` as larger than all numbers and treat `NaN = NaN` as true (`unverified`: not run; see [PostgreSQL float types](https://www.postgresql.org/docs/current/datatype-numeric.html#DATATYPE-FLOAT)). R distinguishes `NA_real_` from `NaN` (`is.na` is true for both, `is.nan` only for `NaN`). pandas converts an int column with a missing value to float64 unless a nullable dtype is used. Missing is not an invalid number; keep them apart in aggregates (`avg` skips NULL but propagates NaN).

## 10. Decimal vs float money sums

```python
import decimal, math
sum([0.1]*10)                              # 0.9999999999999999  (CPython 3.11)
math.fsum([0.1]*10)                        # 1.0
sum([decimal.Decimal('0.1')]*10)           # Decimal('1.0')
decimal.Decimal(0.1)                       # Decimal('0.1000000000000000055511151231257827021181583404541015625')
```
```java
new BigDecimal(0.1)                        // 0.1000000000000000055511151231257827021181583404541015625
BigDecimal.valueOf(0.1).multiply(BigDecimal.TEN)   // 1.0
new BigDecimal("2.0").equals(new BigDecimal("2.00"))      // false (scale differs)
new BigDecimal("2.0").compareTo(new BigDecimal("2.00"))   // 0
```
Note: CPython 3.12 changed the builtin `sum()` of floats to use compensated summation, so `sum([0.1]*10)` may print `1.0` there (`unverified`: not run on 3.12). Summation order matters for float64 generally, which is why the benchmark fixes the order or uses Kahan summation and carries money as int64 cents. Decimal types differ too: C# `decimal` is 28-29 digits, `java.math.BigDecimal` is unbounded, PostgreSQL `numeric` is up to 131072 digits, JS has no native decimal.

## 11. Map and set iteration order

```python
list({"b": 1, "a": 2, "10": 3})            # ['b', 'a', '10']  (insertion order, guaranteed since 3.7)
```
```js
Object.keys({b:1, a:2, "10":3, "2":4})                         // [ '2', '10', 'b', 'a' ]  (integer-like keys first)
[...new Map([["b",1],["a",2],["10",3]]).keys()]                // [ 'b', 'a', '10' ]
```
```go
m := map[string]int{"a":1,"b":2,"c":3,"d":4,"e":5}
for k := range m { fmt.Print(k) }   // order differs between runs: observed "abcde abcde eabcd"
```
```rust
let m: HashMap<_,_> = [("a",1),("b",2),("c",3),("d",4),("e",5)].into(); m.keys()   // observed ["b","e","a","c","d"]; random per process
```
```java
new HashMap<>() keys of banana, apple, cherry, 10, 2   // observed [banana, apple, cherry, 2, 10]; unspecified, version dependent
```

Never rely on iteration order of a hash map for output that is checksummed; sort first. Swift's `Dictionary` order changes between processes (`unverified`: not run; see [Swift Dictionary](https://developer.apple.com/documentation/swift/dictionary)).

## 12. Unsigned and signed mixing, and narrowing

```cpp
-1 < 1u            // 0 (false!): -1 converts to 4294967295
```
```java
byte b = (byte)200;  b + " " + (b & 0xFF)   // -56 200   (Java byte is signed)
```
```rust
300_i32 as u8, -1_i32 as u32                 // 44, 4294967295 (silent truncation / reinterpretation)
(1e20_f64) as i32, f64::NAN as i32           // 2147483647, 0 (float->int casts saturate; NaN gives 0)
```
```go
var u uint8 = 255; u++   // 0
var i64 int64 = math.MaxInt64; i64++   // -9223372036854775808
```

Java has no unsigned primitives (use `Integer.toUnsignedLong`, `Long.compareUnsigned`); R has no 64-bit integer at all; PostgreSQL has no unsigned integers. A Parquet `UINT64` therefore needs an explicit mapping in many of the benchmark languages.

## 13. Sizes that differ from what the name suggests

Observed with g++ 13.3 on Linux x86-64 (`sizeof`): `int` 4, `long` 8, `wchar_t` 4, `long double` 16, `bool` 1, `std::string` 32. Rust: `size_of::<Option<u32>>()` is 8, `Option<Box<u32>>` is 8 (niche optimization), `char` is 4. On Windows `long` is 4 and `wchar_t` is 2. Python `int` objects start at 28 bytes (CPython) versus 8 for a numpy `int64` element. See the cell tables in [integers.md](integers.md) and [text-and-binary.md](text-and-binary.md), and [conformance-output/](conformance-output/) for the authoritative per-language numbers.

## Takeaways for the benchmark

1. State the exact type of every accumulator, key and timestamp in each implementation; "int" is not a specification.
2. Compare checksums, not printed values, and define summation order and rounding in the op spec.
3. Treat any conversion across languages (int64 to JS, decimal to float, microsecond to millisecond) as a lossy boundary; see [conversion-matrix.md](conversion-matrix.md).
