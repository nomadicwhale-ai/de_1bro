#!/usr/bin/env python3
"""Track S driver: DuckDB (python package). See systems/duckdb/README.md."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402
from generator.resultdigest import ResultDigest  # noqa: E402

LABELS = {1000: "1k", 10000: "10k", 1000000: "1m", 10000000: "10m", 100000000: "100m",
          1000000000: "1b"}
CENTS = "(unit_price * 100)::BIGINT"

# op -> (needed columns, SQL over table/view `sales`, number of digested columns, float names)
OPS = {
    "OP01": (["quantity", "unit_price", "is_returned"],
             f"""SELECT count(*), count(quantity), sum(quantity)::BIGINT, sum({CENTS})::BIGINT,
                 min({CENTS}), max({CENTS}), count(*) FILTER (WHERE is_returned) FROM sales""", 7, []),
    "OP03": (["country", "quantity", "unit_price"],
             f"""SELECT country, count(*), sum(quantity)::BIGINT, sum({CENTS})::BIGINT
                 FROM sales GROUP BY country""", 4, []),
    "OP04": (["customer_id", "unit_price"],
             f"SELECT customer_id, count(*), sum({CENTS})::BIGINT FROM sales GROUP BY customer_id", 3, []),
    "OP05": (["country", "category", "transaction_date", "unit_price"],
             f"""SELECT country, category, year(transaction_date)::BIGINT, count(*),
                 sum({CENTS})::BIGINT FROM sales GROUP BY 1, 2, 3""", 5, []),
    "OP10": (["customer_id", "product_id", "store_id", "transaction_date"],
             """SELECT (SELECT count(DISTINCT customer_id) FROM sales),
                       (SELECT count(DISTINCT product_id) FROM sales),
                       (SELECT count(*) FROM (SELECT DISTINCT store_id, transaction_date FROM sales))""",
             3, []),
    "OP19": (["quantity", "country"],
             """SELECT count(*) FILTER (WHERE quantity IS NULL), count(*) FILTER (WHERE country IS NULL),
                sum(coalesce(quantity, 1))::BIGINT,
                count(*) FILTER (WHERE country IS NOT NULL AND country <> ''),
                count(DISTINCT country) FROM sales""", 5, []),
    "OP21": (["unit_price"],
             f"""SELECT sum({CENTS})::BIGINT,
                 (sum({CENTS}) // 100)::VARCHAR || '.' || lpad((sum({CENTS}) % 100)::VARCHAR, 2, '0'),
                 sum(({CENTS})::DOUBLE / 100.0), fsum(({CENTS})::DOUBLE / 100.0) FROM sales""",
             2, ["naive_sum", "kahan_sum"]),
    "OP22": (["transaction_id", "customer_id", "unit_price", "transaction_timestamp", "transaction_date"],
             f"""SELECT
                count(*) FILTER (WHERE (transaction_id * 4294967311 + customer_id)::DOUBLE::BIGINT
                                 <> transaction_id * 4294967311 + customer_id),
                count(*) FILTER (WHERE trunc((({CENTS})::DOUBLE / 100.0) * 100.0)::BIGINT <> {CENTS}),
                count(*) FILTER (WHERE (epoch_us(transaction_timestamp) // 1000) * 1000
                                 <> epoch_us(transaction_timestamp)),
                sum(year(transaction_date) * 10000 + month(transaction_date) * 100
                    + day(transaction_date))::BIGINT FROM sales""", 4, []),
    "OP15": ([],
             f"""SELECT count(*), sum(transaction_id)::BIGINT, sum(customer_id)::BIGINT,
                 sum(product_id)::BIGINT, sum(store_id)::BIGINT, sum(quantity)::BIGINT,
                 count(*) FILTER (WHERE quantity IS NULL),
                 sum({CENTS})::BIGINT, sum(floor(discount * 1e6 + 0.5)::BIGINT)::BIGINT,
                 sum(floor(tax * 1e6 + 0.5)::BIGINT)::BIGINT, sum(strlen(country))::BIGINT,
                 count(*) FILTER (WHERE country IS NULL), sum(strlen(category))::BIGINT,
                 sum(epoch(transaction_date)::BIGINT // 86400)::BIGINT,
                 sum(epoch_us(transaction_timestamp) // 1000000)::BIGINT,
                 sum(epoch_us(transaction_timestamp) % 1000000)::BIGINT,
                 count(*) FILTER (WHERE is_returned) FROM sales""", 17, []),
}

# Phase 3b ops: (sales columns, dims needed, SQL over sales/customers/products, ncols).  SQL written here (not the oracle's).
SC = "(s.unit_price * 100)::BIGINT"
OPS.update({
    "OP06": (["customer_id", "quantity", "unit_price"], ["customers"],
             f"""SELECT c.segment, count(*), sum({SC})::BIGINT, sum(s.quantity)::BIGINT
                 FROM sales s JOIN customers c ON s.customer_id = c.customer_id GROUP BY c.segment""", 4, []),
    "OP07": (["customer_id", "product_id", "unit_price"], ["customers", "products"],
             f"""SELECT p.brand, count(*), sum({SC})::BIGINT FROM sales s
                 JOIN customers c ON s.customer_id = c.customer_id
                 JOIN products p ON s.product_id = p.product_id
                 WHERE c.segment = 'enterprise' GROUP BY p.brand""", 3, []),
    # rn * id summed in HUGEINT (128-bit, cannot overflow for N <= 1e9), reduced mod 2^64 at the end.
    "OP08": (["transaction_id", "transaction_timestamp"], [],
             """WITH o AS (SELECT transaction_id, row_number() OVER (ORDER BY transaction_timestamp, transaction_id) AS rn
                           FROM sales)
                SELECT arg_min(transaction_id, rn), arg_max(transaction_id, rn),
                       (sum(rn::HUGEINT * transaction_id::HUGEINT) % 18446744073709551616::HUGEINT)::HUGEINT FROM o""", 3, []),
    "OP09": (["customer_id", "unit_price"], [],
             f"""SELECT row_number() OVER (ORDER BY total DESC, customer_id), customer_id, total FROM
                 (SELECT customer_id, sum({CENTS})::BIGINT AS total FROM sales GROUP BY customer_id
                  ORDER BY total DESC, customer_id LIMIT 100)""", 3, []),
})
DIM_SRC = {"customers": ("dim_customer", "customer_id, segment"), "products": ("dim_product", "product_id, brand")}

CSV_TYPES = ("{'transaction_id':'BIGINT','customer_id':'BIGINT','product_id':'BIGINT',"
             "'store_id':'INTEGER','quantity':'INTEGER','unit_price':'DECIMAL(18,2)',"
             "'discount':'DOUBLE','tax':'DOUBLE','country':'VARCHAR','category':'VARCHAR',"
             "'transaction_date':'DATE','transaction_timestamp':'TIMESTAMP','is_returned':'BOOLEAN'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--op", required=True)
    ap.add_argument("--dataset", default="A")
    ap.add_argument("--rows", type=int, required=True)
    ap.add_argument("--mode", choices=["streaming", "materialized"], required=True)
    ap.add_argument("--chunk-rows", type=int, default=1000000)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output-json", action="store_true")
    a = ap.parse_args()

    spec = OPS[a.op]
    if len(spec) == 5:
        cols, dims, sql, ncols, float_names = spec
    else:
        (cols, sql, ncols, float_names), dims = spec, []
    if a.op == "OP08" and a.mode != "materialized":
        sys.exit("OP08 is materialized only")
    label = LABELS[a.rows]
    ddir = Path(a.input) / "sales_fact" / label

    con = duckdb.connect()  # in-memory
    con.execute(f"PRAGMA threads={int(a.threads)}")
    con.execute(f"PRAGMA memory_limit='{os.environ.get('DUCKDB_MEMORY_LIMIT', '8GB')}'")
    tmp = os.environ.get("DUCKDB_TEMP_DIR")
    if tmp:
        os.makedirs(tmp, exist_ok=True)
        con.execute(f"PRAGMA temp_directory='{tmp}'")
    con.execute("PRAGMA enable_progress_bar=false")

    load_ms = 0.0
    if a.op == "OP15":
        csv = str(ddir / "part-*.csv").replace("'", "''")
        src = (f"read_csv('{csv}', header=true, columns={CSV_TYPES}, nullstr='\\N', "
               f"timestampformat='%Y-%m-%d %H:%M:%S.%f', dateformat='%Y-%m-%d', delim=',', quote='\"')")
        run_sql = sql.replace("FROM sales", f"FROM {src}")
        t0 = time.perf_counter()
        res = con.execute(run_sql).fetchall()
        compute_ms = (time.perf_counter() - t0) * 1000
    else:
        pq = str(ddir / "part-*.parquet").replace("'", "''")
        t0 = time.perf_counter()
        for d in dims:  # small dimension tables are always loaded first (counts as load_ms)
            dname, dcols = DIM_SRC[d]
            dp = str(Path(a.input) / dname / label / "part-*.parquet").replace("'", "''")
            con.execute(f"CREATE TABLE {d} AS SELECT {dcols} FROM read_parquet('{dp}')")
        if a.mode == "materialized":
            con.execute(f"CREATE TABLE sales AS SELECT {', '.join(cols)} FROM read_parquet('{pq}')")
            run_sql = sql
        elif dims:
            con.execute(f"CREATE VIEW sales AS SELECT {', '.join(cols)} FROM read_parquet('{pq}')")
            run_sql = sql
        else:
            run_sql = sql.replace("FROM sales", f"FROM read_parquet('{pq}')")
        load_ms = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        res = con.execute(run_sql).fetchall()
        compute_ms = (time.perf_counter() - t0) * 1000

    d = ResultDigest()
    floats = {}
    for row in res:
        d.add(row[:ncols])
        for k, name in enumerate(float_names):
            floats[name] = float(row[ncols + k])
    out = {"load_ms": load_ms, "compute_ms": compute_ms, "checksum": d.checksum,
           "row_count": d.count, "toolchain": {"name": "duckdb", "version": duckdb.__version__,
                                                "flags": f"threads={a.threads}"}}
    if float_names:
        out["floats"] = floats
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
