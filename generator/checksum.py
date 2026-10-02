"""Order-insensitive per-column digests (spec/checksum.md).

Per column: sum over rows (mod 2**64) of a canonical 64-bit value, plus null count.
  ints/bool/date(days)/timestamp(us)/cents -> two's-complement uint64
  float64 -> raw IEEE-754 bits
  string -> xxh64(utf8, seed 0)
  list<string> -> xxh64 of "\\x1f".join(items); map -> xxh64 of "\\x1f".join(k=v)
  null -> contributes 0 and increments `nulls`
Digests of chunks add column-wise, so any chunking yields the same table digest.
"""
from __future__ import annotations

import struct

import numpy as np
import pyarrow as pa
import xxhash

from .spec import MASK64

_h = xxhash.xxh64_intdigest


def _hash_str(s: str) -> int:
    return _h(s.encode("utf-8"))


def _canon(v) -> int:
    """Pure-python canonical value of a non-null reference value."""
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v & MASK64
    if isinstance(v, float):
        return struct.unpack("<Q", struct.pack("<d", v))[0]
    if isinstance(v, str):
        return _hash_str(v)
    if isinstance(v, list):
        if v and isinstance(v[0], tuple):
            return _hash_str("\x1f".join(f"{k}={x}" for k, x in v))
        return _hash_str("\x1f".join(v))
    raise TypeError(type(v))


def digest_rows(cols: list[str], rows) -> dict:
    """Digest of reference rows (iterable of tuples)."""
    sums = [0] * len(cols)
    nulls = [0] * len(cols)
    for row in rows:
        for c, v in enumerate(row):
            if v is None:
                nulls[c] += 1
            else:
                sums[c] = (sums[c] + _canon(v)) & MASK64
    return {c: [sums[k], nulls[k]] for k, c in enumerate(cols)}


def _col_digest(col: pa.ChunkedArray | pa.Array) -> list[int]:
    if isinstance(col, pa.ChunkedArray):
        col = col.combine_chunks() if col.num_chunks else pa.array([], col.type)
    t = col.type
    nulls = col.null_count
    if pa.types.is_string(t):
        enc = col.dictionary_encode()
        hashes = np.fromiter((_hash_str(s) for s in enc.dictionary.to_pylist()),
                             dtype=np.uint64, count=len(enc.dictionary))
        idx = enc.indices.drop_null().to_numpy(zero_copy_only=False)
        s = int(hashes[idx].sum(dtype=np.uint64)) if len(idx) else 0
        return [s, nulls]
    if pa.types.is_list(t):
        vals = [None if v is None else _hash_str("\x1f".join(v)) for v in col.to_pylist()]
    elif pa.types.is_map(t):
        vals = [None if v is None else _hash_str("\x1f".join(f"{k}={x}" for k, x in v))
                for v in col.to_pylist()]
    else:
        if pa.types.is_date32(t):
            col = col.cast(pa.int32())
        elif pa.types.is_timestamp(t):
            col = col.cast(pa.int64())
        if pa.types.is_boolean(t):
            arr = col.fill_null(False).to_numpy(zero_copy_only=False).astype(np.int64)
        elif pa.types.is_floating(t):
            arr = col.fill_null(0.0).to_numpy(zero_copy_only=False).astype(np.float64).view(np.int64)
        else:
            arr = col.fill_null(0).to_numpy(zero_copy_only=False).astype(np.int64)
        return [int(arr.view(np.uint64).sum(dtype=np.uint64)), nulls]
    s = 0
    for v in vals:
        if v is not None:
            s = (s + v) & MASK64
    return [s, nulls]


def digest_table(tbl: pa.Table) -> dict:
    """Digest of a canonical-form Arrow table (generator.fast.gen_chunk)."""
    return {name: _col_digest(tbl.column(name)) for name in tbl.column_names}


def merge(a: dict | None, b: dict) -> dict:
    if a is None:
        return {k: list(v) for k, v in b.items()}
    return {k: [(a[k][0] + v[0]) & MASK64, a[k][1] + v[1]] for k, v in b.items()}


def to_json(d: dict) -> dict:
    return {k: {"sum": f"{v[0]:016x}", "nulls": v[1]} for k, v in d.items()}


def from_json(d: dict) -> dict:
    return {k: [int(v["sum"], 16), v["nulls"]] for k, v in d.items()}


def table_digest(d: dict) -> str:
    """Single 64-bit fingerprint of a column-digest dict (schema order matters)."""
    s = "|".join(f"{k}={v[0]:016x}:{v[1]}" for k, v in d.items())
    return f"{_hash_str(s):016x}"
