"""Python Track L joins, sort and top-N, including non-generator edge cases."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from generator import spec as S
from generator.reference import CustomerRef, ProductRef, SalesRef
from languages.python import bench
from runner.ref_ops import REF

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    from generator.cli import main

    root = tmp_path_factory.mktemp("python-bench")
    n = 1000
    assert main(["gen", "--dataset", "A,B,C", "--rows", str(n), "--out", str(root),
                 "--formats", "csv", "--chunk-rows", "127", "--workers", "1"]) == 0
    scale = S.Scale(n)
    sales = SalesRef(S.DEFAULT_SEED, scale)
    customers = CustomerRef(S.DEFAULT_SEED, scale)
    products = ProductRef(S.DEFAULT_SEED, scale)
    rows = [sales.row(i) for i in range(n)]
    dims = {"segment": {r[0]: r[4] for r in (customers.row(i) for i in range(scale.customers))},
            "brand": {r[0]: r[2] for r in (products.row(i) for i in range(scale.products))}}
    return root, rows, dims


@pytest.mark.parametrize("op,mode", [(op, mode) for op in ("OP06", "OP07", "OP08", "OP09")
                                    for mode in ("streaming", "materialized")
                                    if op != "OP08" or mode == "materialized"])
def test_cli_matches_reference(op, mode, generated):
    root, rows, dims = generated
    proc = subprocess.run([sys.executable, "-O", str(ROOT / "languages/python/bench.py"),
                           "--op", op, "--mode", mode, "--rows", "1000", "--input", str(root),
                           "--threads", "1", "--output-json"],
                          capture_output=True, text=True, check=True)
    result = json.loads(proc.stdout)
    (checksum, count), _ = REF[op](rows, dims) if op in ("OP06", "OP07") else REF[op](rows)
    assert result["checksum"] == checksum
    assert result["row_count"] == count
    assert result["load_ms"] > 0
    assert result["compute_ms"] > 0
    assert len(proc.stdout.splitlines()) == 1


def test_join_dimensions_read_all_chunks_and_skip_product_json(generated):
    root, _, dims = generated
    assert bench.load_dims(root, 1000, "OP07") == dims
    assert bench.load_dims(root, 1000, "OP06") == {"segment": dims["segment"]}


def test_op06_null_quantity_and_exact_cents_across_chunks():
    _, step, finish = bench.op06({"segment": {1: "", 2: "é", 3: None}})
    step({"cid": [1, 2, 3, 99], "cents": [101, -201, 300, 999],
          "qty": [None, 0, None, 5]})
    step({"cid": [1, 2], "cents": [102, 202], "qty": [None, -3]})
    rows, floats = finish()
    assert set(rows) == {("", 2, 203, None), ("é", 2, 1, -3), (None, 1, 300, None)}
    assert floats == {}


def test_op07_enterprise_filter_and_inner_joins():
    _, step, finish = bench.op07({"segment": {1: "enterprise", 2: "consumer"},
                                  "brand": {1: "", 2: "品牌", 3: None}})
    step({"cid": [1, 2, 1, 99, 1], "pid": [1, 2, 2, 2, 99],
          "cents": [101, 999, -201, 999, 999]})
    step({"cid": [1, 1], "pid": [2, 3], "cents": [202, 303]})
    rows, _ = finish()
    assert set(rows) == {("", 1, 101), ("品牌", 2, 1), (None, 1, 303)}


def test_op08_microseconds_ties_and_wrapping_sum():
    _, step, finish = bench.op08()
    large = (1 << 63) + 7
    step({"ts_sec": [0, -1, 0, 0, 0], "ts_frac": [1, 999999, 0, 1, 1],
          "tid": [4, 6, 3, large, 2]})
    expected = (6 + 2 * 3 + 3 * 2 + 4 * 4 + 5 * large) & bench.MASK
    assert finish() == ([(6, large, expected)], {})


def test_op08_rejects_streaming_before_loading(tmp_path):
    proc = subprocess.run([sys.executable, str(ROOT / "languages/python/bench.py"),
                           "--op", "OP08", "--mode", "streaming", "--rows", "1000",
                           "--input", str(tmp_path)], capture_output=True, text=True)
    assert proc.returncode != 0
    assert "OP08 is materialized only" in proc.stderr
    assert proc.stdout == ""


def test_op09_ties_at_top100_boundary_and_cross_chunk_totals():
    _, step, finish = bench.op09()
    ids = list(range(105, 0, -1))
    step({"cid": ids, "cents": [100] * len(ids)})
    step({"cid": [105, 1, 2], "cents": [1, -1, -200]})
    rows, _ = finish()
    assert rows == [(1, 105, 101)] + [(cid - 1, cid, 100) for cid in range(3, 102)]


@pytest.mark.parametrize("mode", ["streaming", "materialized"])
def test_dimension_loading_is_timed_before_fact_loading(mode, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(sys, "argv", ["bench", "--op", "OP06", "--mode", mode,
                                     "--rows", "1000", "--input", "unused"])
    monkeypatch.setattr(bench, "chunk_files", lambda *args: ["chunk"])
    ticks = iter(range(20))
    monkeypatch.setattr(bench.time, "perf_counter", lambda: next(ticks))

    def dimensions(*args):
        calls.append("dims")
        return {"segment": {1: "enterprise"}}

    def facts(path, names, acc):
        calls.append("facts")
        acc.update(cid=[1], cents=[100], qty=[None])

    monkeypatch.setattr(bench, "load_dims", dimensions)
    monkeypatch.setattr(bench, "load", facts)
    assert bench.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert calls == ["dims", "facts"]
    assert result["load_ms"] == 2000  # 1000 ms dimensions + 1000 ms facts
    assert result["compute_ms"] == (2000 if mode == "streaming" else 1000)
