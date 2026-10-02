"""Cross-implementation golden tests: pure-Python reference == vectorised generator."""
import pyarrow as pa
import pytest

from generator import checksum as ck
from generator import fast, spec as S
from generator.reference import make_ref

SEED = S.DEFAULT_SEED
TABLES = list(S.TABLE_IDS)


def rows_of(tbl: pa.Table):
    cols = []
    for name in tbl.column_names:
        c = tbl.column(name)
        if pa.types.is_date32(c.type):
            c = c.cast(pa.int32())
        elif pa.types.is_timestamp(c.type):
            c = c.cast(pa.int64())
        cols.append(c.to_pylist())
    return list(zip(*cols))


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("n", [1_000, 10_000])
def test_rows_identical(table, n):
    scale = S.Scale(n)
    count = min(scale.rows(table), 5000)
    ref, cols = make_ref(table, SEED, scale)
    expected = [ref.row(i) for i in range(count)]
    got = rows_of(fast.gen_chunk(table, 0, count, scale, SEED))
    assert list(fast.gen_chunk(table, 0, 1, scale, SEED).column_names) == cols
    assert got == expected


@pytest.mark.parametrize("table", TABLES)
def test_chunk_boundaries_do_not_matter(table):
    scale = S.Scale(10_000)
    n = min(scale.rows(table), 3000)
    whole = rows_of(fast.gen_chunk(table, 0, n, scale, SEED))
    parts = []
    for start in range(0, n, 777):
        parts += rows_of(fast.gen_chunk(table, start, min(777, n - start), scale, SEED))
    assert parts == whole


@pytest.mark.parametrize("table", TABLES)
def test_digest_matches_reference(table):
    scale = S.Scale(10_000)
    n = min(scale.rows(table), 3000)
    ref, cols = make_ref(table, SEED, scale)
    expected = ck.digest_rows(cols, (ref.row(i) for i in range(n)))
    got = ck.digest_table(fast.gen_chunk(table, 0, n, scale, SEED))
    assert got == expected


def test_seed_changes_data():
    scale = S.Scale(1000)
    a = rows_of(fast.gen_chunk("sales_fact", 0, 50, scale, SEED))
    b = rows_of(fast.gen_chunk("sales_fact", 0, 50, scale, SEED + 1))
    assert a != b


def test_sales_properties():
    scale = S.Scale(100_000)
    t = fast.gen_chunk("sales_fact", 0, 100_000, scale, SEED)
    d = t.to_pydict()
    assert min(d["unit_price_cents"]) >= 99 and max(d["unit_price_cents"]) <= 999_999
    assert 0.0004 < t.column("quantity").null_count / 100_000 < 0.002
    assert max(d["customer_id"]) <= scale.customers and min(d["customer_id"]) >= 1
    assert 0.03 < sum(d["is_returned"]) / 100_000 < 0.07
    # timestamp consistent with date
    import numpy as np
    days = np.array(t.column("transaction_date").cast(pa.int32()).to_numpy())
    us = np.array(t.column("transaction_timestamp").cast(pa.int64()).to_numpy())
    assert (us // S.US_PER_DAY == days).all()
    assert set(S.EDGE_COUNTRY_UNICODE for _ in [0]) & set(d["country"])
    assert "" in d["country"]


def test_output_schema():
    scale = S.Scale(1000)
    out = fast.to_output(fast.gen_chunk("sales_fact", 0, 100, scale))
    assert out.schema.field("unit_price").type == pa.decimal128(18, 2)
    out2 = fast.to_output(fast.gen_chunk("sales_fact", 0, 100, scale), "float64")
    assert out2.schema.field("unit_price").type == pa.float64()
    cents = fast.gen_chunk("sales_fact", 0, 100, scale).column("unit_price_cents").to_pylist()
    from decimal import Decimal
    assert out.column("unit_price").to_pylist() == [Decimal(c) / 100 for c in cents]
