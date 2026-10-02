"""File writers (Parquet / CSV / Arrow IPC) and the output->canonical reader."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

CSV_NULL = "\\N"
FORMATS = ("parquet", "csv", "arrow")


def _nested_to_json(tbl: pa.Table) -> pa.Table:
    for name in tbl.column_names:
        t = tbl.schema.field(name).type
        if pa.types.is_list(t):
            vals = [None if v is None else json.dumps(v, separators=(",", ":"))
                    for v in tbl.column(name).to_pylist()]
        elif pa.types.is_map(t):
            vals = [None if v is None else json.dumps(dict(v), separators=(",", ":"))
                    for v in tbl.column(name).to_pylist()]
        else:
            continue
        tbl = tbl.set_column(tbl.column_names.index(name), name, pa.array(vals, pa.string()))
    return tbl


def write_parquet(tbl: pa.Table, path: Path, compression: str = "zstd") -> None:
    comp = None if compression in ("none", "") else compression
    pq.write_table(tbl, path, compression=comp, row_group_size=max(len(tbl), 1),
                   use_dictionary=True, write_statistics=True)


def write_arrow(tbl: pa.Table, path: Path) -> None:
    with pa.OSFile(str(path), "wb") as sink, pa.ipc.new_file(sink, tbl.schema) as w:
        w.write_table(tbl)


def write_csv(tbl: pa.Table, path: Path) -> None:
    import duckdb

    tbl = _nested_to_json(tbl)
    con = duckdb.connect()
    con.register("t", tbl)
    con.execute(f"COPY t TO '{path}' (FORMAT CSV, HEADER, NULLSTR '{CSV_NULL}', TIMESTAMPFORMAT '%Y-%m-%d %H:%M:%S.%f')")
    con.close()


def write_table(tbl: pa.Table, base: Path, fmt: str, compression: str = "zstd") -> Path:
    """Atomically write `tbl` as `<base>.<fmt>`; returns the final path."""
    final = base.with_suffix("." + fmt)
    tmp = final.with_name(final.name + ".tmp")
    {"parquet": lambda: write_parquet(tbl, tmp, compression),
     "csv": lambda: write_csv(tbl, tmp),
     "arrow": lambda: write_arrow(tbl, tmp)}[fmt]()
    os.replace(tmp, final)
    return final


def sha256_file(path: Path, bufsize: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(bufsize):
            h.update(block)
    return h.hexdigest()


def from_output(tbl: pa.Table) -> pa.Table:
    """Published schema -> canonical (inverse of fast.to_output); used by `verify`."""
    out = tbl
    for dst, src in (("unit_price", "unit_price_cents"), ("lifetime_value", "lifetime_value_cents")):
        if dst in out.column_names:
            idx = out.column_names.index(dst)
            col = out.column(idx)
            if pa.types.is_decimal(col.type):
                arr = col.combine_chunks()
                lo = np.frombuffer(arr.buffers()[1], dtype=np.int64)[arr.offset * 2:(arr.offset + len(arr)) * 2:2]
                new = pa.array(lo.copy(), pa.int64())
            elif pa.types.is_floating(col.type):
                new = pa.array(np.rint(col.to_numpy() * 100.0).astype(np.int64))
            else:
                new = col
            out = out.set_column(idx, src, new)
    return out
