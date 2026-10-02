"""Harness self-test implementation (OP00): stream a dataset and return its content digest.

Proves the runner <-> implementation contract end to end (process isolation, JSON line, timing,
checksum comparison against the generator golden/manifest). It is NOT a language benchmark.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from generator import checksum as ck  # noqa: E402
from generator import spec as S  # noqa: E402
from generator.stream import iter_chunks  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--op", required=True)
ap.add_argument("--dataset", default="A")
ap.add_argument("--rows", type=int, required=True)
ap.add_argument("--mode", default="streaming")
ap.add_argument("--chunk-rows", type=int, default=S.DEFAULT_CHUNK_ROWS)
ap.add_argument("--threads", type=int, default=1)
ap.add_argument("--input", default=None)
ap.add_argument("--output-json", action="store_true")
a = ap.parse_args()
assert a.op == "OP00", "selftest only implements OP00"

table = S.DATASET_TABLES[a.dataset]
t0 = time.perf_counter()
merged, rates, rows = None, [], 0
for tbl in iter_chunks(table, a.rows, a.chunk_rows, canonical=True):
    c0 = time.perf_counter()
    merged = ck.merge(merged, ck.digest_table(tbl))
    rows += len(tbl)
    rates.append(len(tbl) / max(time.perf_counter() - c0, 1e-9))
print(json.dumps({"load_ms": 0.0, "compute_ms": (time.perf_counter() - t0) * 1000,
                  "checksum": ck.table_digest(merged), "row_count": rows,
                  "chunk_rows_per_s": [round(r) for r in rates],
                  "toolchain": {"name": "python", "version": sys.version.split()[0], "flags": ""}}))
