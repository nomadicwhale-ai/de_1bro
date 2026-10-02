# Plan (revised after the Phase 3b slice)

Rule order is unchanged: **correctness > reproducibility > fairness > coverage.** Every item below is sized so it
ends in a merged, verified increment; later items can be dropped without invalidating earlier ones.

## 1. Where we are

| Area | Done | Evidence |
|---|---|---|
| Data | deterministic generator, 5 tables, 1k-1B (streaming), manifests, golden digests | `spec/generator.md`, `spec/golden.json`, tests |
| Oracle | 13 ops: OP01,03,04,05,06,07,08,09,10,15,19,21,22; DuckDB == pure-Python at 1k/10k; expected results to 10M | `runner/ops.py`, `runner/ref_ops.py`, `results/expected/` |
| Track L | python, rust, go, java, cpp (stdlib only) | `languages/*` (python lacks OP06-09) |
| Track S | duckdb, polars, sqlite | `systems/*` |
| Results | 804 correct timing records (1M/10M) | `results/published/`, `report/REPORT.md`, `report/FINDINGS.md` |
| Docs | data-type tables (78 `unverified` fields), conformance probes (7/13 languages run) | `docs/data-types/`, `conformance/` |

## 2. Prioritised roadmap

Effort: S = a few hundred lines / ~1 agent task, M = 2-3 agent tasks, L = open-ended. "Cost" is relative (S << L).

| # | Item | Effort | Value | Acceptance criteria |
|---|---|---|---|---|
| 1 | **Trust fixes (do first)**: extend the pure-Python vs DuckDB cross-check to 100k rows; add OP06-09 expected-result self-check at 100k; add a CI job that builds all implementations and runs `runner run --smoke` + 1k/10k correctness; create `docs/FAIRNESS_ISSUES.md` | S | high | CI green on a clean clone; cross-check test passes at 100k |
| 2 | **Python OP06-09** (stdlib) so Track L is uniform across the 13 ops | S | medium | OK at 1k/10k/1m; impl.yaml updated |
| 3 | **Flat-hash-map variants for C++ (OP04/09/10)** and primitive sort for Java OP08, as *labelled variants* next to the current implementations (variant `ecosystem`/`tuned`), so the report separates "naive stdlib" from "tuned stdlib" | S | high (removes the main fairness caveat) | both variants correct; report shows both |
| 4 | **JavaScript (node) and TypeScript** std-only implementations, all 13 ops (BigInt/number caveats documented) | M | high (language coverage) | OK at 1k/10k/1m; 10m subset |
| 5 | **Remaining ops**: OP02 filter, OP18 date/time, OP20 wide scan (needs dataset E), OP11 window, then OP12-14 (dataset D), OP16/17 I/O | M-L | high | spec + oracle + reference + >=4 implementations each |
| 6 | **More systems**: pandas, PyArrow compute (cheap, pip), then PostgreSQL (server install), Spark local (JVM + pyspark), ClickHouse (if installable) | M-L | medium-high | same contract; `status: not_run` + reason where infeasible |
| 7 | **Parallel Track L variants** (fixed 4 threads) for rust/go/java/cpp on OP01/03/04/10 | M | medium | correctness at 1 and 4 threads; scaling table |
| 8 | **Scale**: 100M for all fast implementations (Parquet/CSV on disk, ~11 GB CSV); 1B streaming where feasible (generate-on-the-fly harness or a larger disk); scaling exponents, bytes/row | L | high for the "1B rows" goal | expected results to 100M (DuckDB); documented skips for combinations that exceed budget |
| 9 | **Languages without local toolchains** (C#, Julia, Swift, Kotlin, Scala, R): run from their Dockerfiles in an environment that has them; otherwise stay `not_run` | L | medium | one language at a time, same contract |
| 10 | **Explanations & evidence**: `perf stat` counters / flame graphs for the top and bottom implementation per op; `report/explanations/<op>.md`; resolve `unverified` data-type fields | L | high for "explain why results differ" | each op page cites measured evidence or says "hypothesis" |

Suggested order under a tight budget: **1 -> 2 -> 3 -> 4**, then 5 (OP02/OP18 first), then 8 at 100M. Items 1-3 are cheap and
make the existing results more defensible; item 4 adds the most visible coverage per unit cost.

## 3. Known limitations to fix or keep documenting

* Report mixes two campaigns (earlier Rust/Go/Python numbers vs later Java/C++); rerun everything together before any
  publication-grade ranking (`make bench` + `make report`). 104 of 446 cells are flagged noisy; use a quieter machine
  and >= 7 runs for final numbers.
* Python and SQLite are only validated on a subset of operations at 10M; nothing runs above 10M.
* DuckDB/Polars streaming ignore `--chunk-rows` and scan all files in one query; Track L streaming is true chunked.
* `compute_ms` vs `load_ms` splits are implementation-defined; rank by `load + compute` (as the report does).
* `std::unordered_map` (C++) and boxed-index sort (Java) are deliberately idiomatic-stdlib; item 3 adds tuned variants.
* Size estimates in `docs/dataset-sizes.md` run 10-30% high; 1B Parquet (~35 GB) does not fit this container's disk.
* 78 data-type fields remain `unverified`; conformance output wins when it disagrees.

## 4. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Implementation-skill bias dominates results | per-language READMEs, `FAIRNESS_ISSUES.md`, tuned variants labelled separately |
| Oracle bug (found once: OP15 double sums) | pure-Python cross-check at larger sizes; exact integer sums only; never hash floats |
| Noisy shared machine | pin single-thread runs, shuffle order, >= 7 runs, flag `noisy`, rerun noisy cells |
| Scope creep | each roadmap item ends in a merged PR with docs updated |
| Budget | work through sub-agents with tight scopes and short reports; avoid repeated full campaigns |

## 5. How to continue (handoff)

1. Read `spec/IMPLEMENTER_GUIDE.md` (CLI/JSON contract, timing rules, Phase 3b addendum) and `docs/METHODOLOGY.md`.
2. New op: add to `runner/ops.py` (spec + oracle SQL), `runner/ref_ops.py` (pure Python), run `python -m runner specs`,
   `python -m runner.oracle --rows 1k,10k,1m,10m --op OPxx`, `pytest tests`.
3. New implementation: `languages/<lang>/` or `systems/<system>/` with `impl.yaml` (fragment auto-registered), README notes;
   validate with `python -m runner run --impl <name> --rows 1k,10k,1m --runs 1 --warmup 0 --force`.
4. Timing run: `python -m runner run --impl <names> --rows 1m,10m --runs 5 --warmup 1` on an idle machine, copy
   `results/raw/*.jsonl` to `results/published/<phase>/`, then `make report` and update `report/FINDINGS.md`
   (re-check every number against the data before merging).
5. Keep `docs/STATUS.md` and this plan current in the same PR.
