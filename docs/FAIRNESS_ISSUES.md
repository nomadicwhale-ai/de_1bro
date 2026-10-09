# Fairness issues

**Correctness checks do not make performance comparisons fair.** Track L and Track S remain separate; the issues below must accompany any published ranking. See [Methodology](METHODOLOGY.md) and [Plan](PLAN.md).

## Open issues

**These are documented limitations, not changes to benchmark semantics.** Follow-up implementation work remains in the roadmap; this register does not approve new variants or timing campaigns.

| ID | Issue and evidence | Reporting mitigation / follow-up | State |
|---|---|---|---|
| F01 | Implementation choices affect results: C++ uses `std::unordered_map` with allocation-heavy nodes; Java OP08 sorts boxed indices. See `languages/cpp/README.md`, `languages/java/README.md`. | Keep the stdlib baseline; label tuned/ecosystem variants separately (roadmap item 3), never silently replace results. | Open |
| F02 | Load/compute boundaries differ: Go dictionary-encodes strings during load; DuckDB/Polars streaming fuses reading into query execution. See implementation READMEs and `report/FINDINGS.md`. | Compare `load_ms + compute_ms` as well as compute; disclose importer/representation choices, never interpret compute-only rankings as end-to-end speed. | Open |
| F03 | DuckDB/Polars streaming ignores `--chunk-rows`; Polars operations may fall back to in-memory. Track L streams explicit chunks; SQLite is materialized-only. See `systems/*/README.md`. | Report modes and peak RSS, not a claim of identical bounded-memory behavior; document unsupported combinations. | Open |
| F04 | OP21 engine sums are not identical algorithms: Polars reports exact cents divided by 100 as its compensated value; SQLite >=3.43 compensates even its nominal naive sum. Polars also requires an OP22 division workaround. See `systems/polars/README.md`, `systems/sqlite/README.md`. | Retain exact integer checksums and specified float tolerance; disclose engine behavior, avoid ranking these outputs as equivalent Kahan implementations. | Open |
| F05 | SQLite imports via per-row Python `csv` + `executemany`; native importers and Track L field-skipping have different costs. See `systems/sqlite/README.md`, `spec/IMPLEMENTER_GUIDE.md`. | Include load time and identify the importer; do not attribute host-language import cost solely to SQLite SQL execution. | Open |
| F06 | Java uses a fresh JVM per run, so JIT warm-up is paid again despite discarded runner warm-ups. See `languages/java/README.md`. | Treat these as fresh-process results, not steady-state JVM throughput; disclose the process model. | Open |
| F07 | Published results combine campaigns and contain noisy cells; Python/SQLite 10M coverage is partial, and no implementation has been validated above 10M. See `report/FINDINGS.md`, `docs/STATUS.md`, `docs/PLAN.md`. | Rerun together on a quieter machine with >=7 timed runs before publication-grade ranking; distinguish missing coverage from poor performance. | Open |
| F08 | Python dependencies use minimum versions and CI Rust follows stable; toolchain/library versions and hardware can change. See `requirements.txt`, `.github/workflows/ci.yml`, result environment/toolchain metadata. | Record actual versions/environment with results; CI proves correctness on its environment, not pinned performance reproducibility. | Open |

## Trust coverage

**Independent validation now reaches 100k, not the larger timing scales.** `tests/test_oracle.py` compares all 13 operations against pure Python at 1k/10k/100k and self-checks committed OP06-OP09 expected files at those scales; 1M/10M remain DuckDB-only oracle results.

- CI builds every registered implementation on a clean checkout and runs smoke plus forced 1k/10k correctness; unexpected skips fail the job.
- Correctness CI is not a benchmark campaign and does not resolve F01-F08.

## Recording a dispute

**A fairness claim needs evidence and an explicit reporting consequence.** Add a stable issue ID, affected operation/implementation, reproduction or source link, mitigation and state; retain resolved entries with the resolving PR or result evidence.
