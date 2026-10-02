# Data-type comparison

Comparison of how 13 languages (C++, Rust, Java, C#, Go, Python, JavaScript, TypeScript, Julia, Swift, Kotlin, Scala, R) and three reference systems (PostgreSQL, DuckDB, Arrow/Parquet logical types) represent common data types, with data-engineering-specific risks (conversion, precision, performance).

**Headline caveat: equivalent type names do not imply identical memory layout or behavior.** A Java `char` is a UTF-16 code unit, a C++ `char` is a byte, a Rust `char` is a 4-byte Unicode scalar and a Swift `Character` is a grapheme cluster. A JavaScript `number` is a double (integers exact only to 2^53), a Python `int` is arbitrary precision, R has no native 64-bit integer. Read [equivalence-is-not-identity.md](equivalence-is-not-identity.md) before trusting any cross-language comparison.

## Rebuild

```
python3 docs/data-types/build.py          # validate types.yaml, regenerate markdown
python3 docs/data-types/build.py --check  # validate, exit non-zero if markdown on disk is stale
```

Requirements: Python 3 and PyYAML. Validation fails loudly, listing every missing (concept, language, field) cell. Edit only `types.yaml` (and the hand-written files below); never edit generated files.

## Files

| File | Kind | Content |
|---|---|---|
| `types.yaml` | source of truth | 22 concepts x 16 columns x 9 fields, plus per-language doc sources |
| `build.py` | tool | validator and markdown generator |
| `index.md` | generated | category index, column list, documentation roots, unverified counts |
| `integers.md`, `floating-point-and-decimal.md`, `text-and-binary.md`, `temporal.md`, `nullability-and-errors.md`, `collections.md`, `composite-types.md` | generated | per-concept tables, one row per language |
| `equivalence-is-not-identity.md` | hand-written | runnable examples where equivalent names behave differently |
| `conversion-matrix.md` | hand-written | Dataset A conversions (int64 to float64, decimal, timestamps, dates, widths, parsing, booleans) |
| `conformance-output/` | produced by the conformance suite | actual sizeof/overflow/0.1+0.2 output per language; takes precedence over prose |

## Reading guide

Each concept has a table with one row per language and nine columns:

1. **Type name**: exact spelling, plus the common library type when the standard library has none.
2. **In-memory size**: bytes; for variable-width types, header and per-element overhead.
3. **Width**: fixed or variable.
4. **Null support**: native null, optional wrapper, sentinel, validity bitmap or none.
5. **Primitive / object**: value type, reference type, boxed, heap-allocated.
6. **Typical DE use**: one line on how the type is used in data engineering.
7. **Conversion risks**: overflow, signedness, truncation, locale, timezone, NaN.
8. **Precision limits**: e.g. 2^53 for JS `number`, float digits, decimal scale.
9. **Performance notes**: cache behavior, boxing, GC pressure, allocation.

Conventions:

- A field starting with `unverified:` contains at least one claim that has not been confirmed against primary documentation or by running code. The specific doubtful claim is also tagged inline with `unverified`.
- TypeScript cells that merely repeat JavaScript runtime behavior are copied from JavaScript on purpose (TypeScript compiles to JavaScript and shares its runtime); the cell still names the type-level construct.
- Sizes quote 64-bit platforms (LP64 Linux, CPython, HotSpot with compressed oops) unless stated. Object sizes for managed runtimes vary by version and flags; use the conformance output for exact numbers.
- "Reference columns" (PostgreSQL, DuckDB, Arrow/Parquet) describe the storage-engine view, which is what the benchmark data passes through.
- Where a language has no standard-library equivalent the cell says so and names a common library type; those libraries are outside the stdlib benchmark track.
