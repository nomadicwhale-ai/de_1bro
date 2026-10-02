"""DuckDB oracle == independent pure-Python semantics, on 1k and 10k rows."""
import math
from pathlib import Path

import pytest

from generator import spec as S
from generator.reference import SalesRef
from runner import oracle
from runner.ops import OPS
from runner.ref_ops import NEEDS_DIMS, REF, civil_from_days

DATA = Path(__file__).resolve().parent.parent / "data"


def test_civil_from_days():
    import datetime as dt
    for days in (-1, 0, 16436, 19000, 20453, 11000, 2932896):
        d = dt.date(1970, 1, 1) + dt.timedelta(days=days)
        assert civil_from_days(days) == (d.year, d.month, d.day)


@pytest.fixture(scope="module", params=[1000, 10000])
def sized(request, tmp_path_factory):
    n = request.param
    out = tmp_path_factory.mktemp("data")
    from generator.cli import main
    assert main(["gen", "--dataset", "A,B,C", "--rows", str(n), "--out", str(out), "--workers", "1",
                 "--formats", "parquet"]) == 0
    ref = SalesRef(S.DEFAULT_SEED, S.Scale(n))
    rows = [ref.row(i) for i in range(n)]
    from generator.reference import CustomerRef, ProductRef
    cref, pref = CustomerRef(S.DEFAULT_SEED, S.Scale(n)), ProductRef(S.DEFAULT_SEED, S.Scale(n))
    dims = {"segment": {r[0]: r[4] for r in (cref.row(i) for i in range(S.Scale(n).customers))},
            "brand": {r[0]: r[2] for r in (pref.row(i) for i in range(S.Scale(n).products))}}
    return n, out, rows, dims


@pytest.mark.parametrize("op", list(OPS))
def test_oracle_matches_reference(op, sized):
    n, out, rows, dims = sized
    exp = oracle.compute(op, out, n)
    (checksum, count), floats = REF[op](rows, dims) if op in NEEDS_DIMS else REF[op](rows)
    assert exp["row_count"] == count
    assert exp["checksum"] == checksum
    for k, v in floats.items():
        assert math.isclose(exp["floats"][k], v, rel_tol=1e-9)
