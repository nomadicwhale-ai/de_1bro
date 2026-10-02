"""Oracle: computes expected results with DuckDB over the generated Parquet files.

    python -m runner.oracle --rows 1k,10k,1m [--op OP01,OP03]   # writes results/expected/<op>_A_<rows>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb

from common import env
from generator import spec as S
from generator.resultdigest import ResultDigest
from .ops import OPS


def parquet_glob(data_dir: Path, rows: int) -> str:
    return str(data_dir / "sales_fact" / S.size_label(rows) / "part-*.parquet")


def compute(op_id: str, data_dir: Path, rows: int, threads: int = 4) -> dict:
    o = OPS[op_id]
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads}")
    con.execute(f"CREATE VIEW sales AS SELECT * FROM read_parquet('{parquet_glob(data_dir, rows)}')")
    for view, table in (("customers", "dim_customer"), ("products", "dim_product")):
        if table in o.get("tables", []):
            g = str(data_dir / table / S.size_label(rows) / "part-*.parquet")
            con.execute(f"CREATE VIEW {view} AS SELECT * FROM read_parquet('{g}')")
    res = con.execute(o["sql"]).fetchall()
    ncols = len(o["columns"])
    floats = o.get("floats", [])
    d = ResultDigest()
    float_vals: dict[str, float] = {}
    for row in res:
        d.add(row[:ncols])
        for k, name in enumerate(floats):
            float_vals[name] = float(row[ncols + k])
    man = json.loads((data_dir / "sales_fact" / S.size_label(rows) / "manifest.json").read_text())
    return {"op": op_id, "dataset": "A", "rows": rows, "checksum": d.checksum, "row_count": d.count,
            "floats": float_vals, "rtol": 1e-9, "source": "duckdb", "duckdb_version": duckdb.__version__,
            "data_table_digest": man.get("table_digest"), "generator_version": man["generator_version"]}


def expected_path(op: str, rows: int) -> Path:
    return env.ROOT / "results" / "expected" / f"{op}_A_{rows}.json"


def main(argv=None) -> int:
    env.load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default="1k,10k")
    ap.add_argument("--op", default=",".join(OPS))
    ap.add_argument("--data", default=str(env.get_path("DATA_DIR", "./data")))
    a = ap.parse_args(argv)
    for n in (S.parse_rows(x) for x in a.rows.split(",")):
        for op in a.op.split(","):
            r = compute(op, Path(a.data), n)
            p = expected_path(op, n)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(r, indent=1))
            print(f"{op} N={S.size_label(n)}: rows={r['row_count']} checksum={r['checksum'][:16]}… floats={r['floats']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
