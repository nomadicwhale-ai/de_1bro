"""spec/golden.json (produced by the pure-Python reference) must match the vectorised generator."""
import json
from pathlib import Path

import pytest

from generator import checksum as ck
from generator import fast, spec as S

GOLDEN = json.loads((Path(__file__).resolve().parent.parent / "spec" / "golden.json").read_text())


def test_version_and_seed():
    assert GOLDEN["generator_version"] == S.GENERATOR_VERSION
    assert int(GOLDEN["seed"], 16) == S.DEFAULT_SEED


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=lambda c: f"{c['table']}-N{c['scale_n']}")
def test_case(case):
    scale = S.Scale(case["scale_n"])
    tbl = fast.gen_chunk(case["table"], 0, case["rows"], scale, S.DEFAULT_SEED)
    d = ck.digest_table(tbl)
    assert ck.to_json(d) == case["column_digests"]
    assert ck.table_digest(d) == case["table_digest"]
