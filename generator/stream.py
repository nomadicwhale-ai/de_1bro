"""Streaming API: iterate chunks of any table without touching disk.

    from generator.stream import iter_chunks
    for tbl in iter_chunks("sales_fact", n=10_000_000, chunk_rows=1_000_000):
        ...   # pyarrow.Table in the published schema (decimal price by default)
"""
from __future__ import annotations

from typing import Iterator

import pyarrow as pa

from . import fast, spec as S

WIDE_MAX_CHUNK = 250_000


def effective_chunk_rows(table: str, chunk_rows: int) -> int:
    return min(chunk_rows, WIDE_MAX_CHUNK) if table == "wide_numeric" else chunk_rows


def chunk_ranges(rows: int, chunk_rows: int) -> list[tuple[int, int]]:
    return [(s, min(chunk_rows, rows - s)) for s in range(0, rows, chunk_rows)]


def iter_chunks(table: str, n: int, chunk_rows: int = S.DEFAULT_CHUNK_ROWS,
                seed: int = S.DEFAULT_SEED, canonical: bool = False,
                price_as: str = "decimal", start_chunk: int = 0, stop_chunk: int | None = None
                ) -> Iterator[pa.Table]:
    scale = S.Scale(n)
    cr = effective_chunk_rows(table, chunk_rows)
    for idx, (start, cnt) in enumerate(chunk_ranges(scale.rows(table), cr)):
        if idx < start_chunk or (stop_chunk is not None and idx >= stop_chunk):
            continue
        tbl = fast.gen_chunk(table, start, cnt, scale, seed)
        yield tbl if canonical else fast.to_output(tbl, price_as)
