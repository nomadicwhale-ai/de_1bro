"""OP15 must preserve empty strings and NULLs across Polars CSV API versions."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from generator.cli import main as generate

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def csv_data(tmp_path_factory):
    out = tmp_path_factory.mktemp("polars-csv")
    assert generate(["gen", "--dataset", "A", "--rows", "1k", "--out", str(out),
                     "--workers", "1", "--formats", "csv"]) == 0
    return out


@pytest.mark.parametrize("mode", ["streaming", "materialized"])
@pytest.mark.parametrize("threads", [1, 4])
def test_op15_csv_correctness(csv_data, mode, threads):
    expected = json.loads((ROOT / "results/expected/OP15_A_1000.json").read_text())
    result = subprocess.run(
        [sys.executable, str(ROOT / "systems/polars/bench.py"), "--op", "OP15",
         "--rows", "1000", "--mode", mode, "--threads", str(threads),
         "--input", str(csv_data), "--output-json"],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    assert actual["checksum"] == expected["checksum"]
    assert actual["row_count"] == expected["row_count"]
