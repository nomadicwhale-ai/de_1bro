"""Command line: python -m generator {gen,estimate,verify,golden} ...  (see --help)."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from common import env
from . import checksum as ck
from . import fast, spec as S, writers
from .stream import chunk_ranges, effective_chunk_rows

DEFAULT_FORMATS = "parquet,csv"
WIDE_ROW_CAP = 100_000_000


def _seed(text: str | None) -> int:
    v = text if text is not None else env.get("BENCH_SEED", hex(S.DEFAULT_SEED))
    return int(v, 0)


def _tables(arg: str) -> list[str]:
    if arg.lower() == "all":
        return list(S.DATASET_TABLES.values())
    out = []
    for tok in arg.replace(" ", "").split(","):
        for ch in (tok if tok.isalpha() and len(tok) <= 5 and tok.isupper() else [tok]):
            if ch in S.DATASET_TABLES:
                out.append(S.DATASET_TABLES[ch])
            elif ch in S.TABLE_IDS:
                out.append(ch)
            else:
                sys.exit(f"unknown dataset/table '{ch}' (use A-E, names, or 'all')")
    return list(dict.fromkeys(out))


def _human(b: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024 or unit == "TB":
            return f"{b:.1f} {unit}" if unit != "B" else f"{int(b)} B"
        b /= 1024
    return ""


# --------------------------------------------------------------------- estimate
def measure_bytes_per_row(table: str, formats: list[str], compression: str, price_as: str,
                          sample_rows: int = 100_000) -> dict:
    """Generate a real sample, write it in each format and measure bytes/row."""
    scale = S.Scale(max(sample_rows * 10, 1000))
    n = min(scale.rows(table), 20_000 if table == "wide_numeric" else sample_rows)
    tbl = fast.to_output(fast.gen_chunk(table, 0, n, scale), price_as)
    res = {"arrow_memory": tbl.nbytes / n}
    with tempfile.TemporaryDirectory(dir=env.get("TMPDIR")) as td:
        for fmt in formats:
            p = writers.write_table(tbl, Path(td) / "s", fmt, compression)
            res[fmt] = p.stat().st_size / n
    return res


def estimate_total(tables: list[str], n: int, formats: list[str], compression: str,
                   price_as: str) -> tuple[int, list[dict]]:
    scale = S.Scale(n)
    total, rows_out = 0, []
    for t in tables:
        rows = effective_rows(t, n, scale)
        bpr = measure_bytes_per_row(t, formats, compression, price_as)
        size = {f: bpr[f] * rows for f in formats}
        total += sum(size.values())
        rows_out.append({"table": t, "rows": rows, "bytes_per_row": bpr, "size": size,
                         "memory": bpr["arrow_memory"] * rows})
    return int(total), rows_out


def effective_rows(table: str, n: int, scale: S.Scale | None = None, allow_large_wide: bool = False) -> int:
    scale = scale or S.Scale(n)
    rows = scale.rows(table)
    if table == "wide_numeric" and not allow_large_wide:
        rows = min(rows, WIDE_ROW_CAP)
    return rows


def cmd_estimate(a) -> int:
    formats = a.formats.split(",")
    tables = _tables(a.dataset)
    sizes = [S.parse_rows(x) for x in a.rows.split(",")] if a.rows else list(S.SIZE_LABELS.values())
    lines = ["# Dataset size estimates", "",
             "Measured by generating and writing a real sample of each table, then extrapolating "
             f"bytes/row linearly (compression: `{a.compression}`, price as `{a.price_as}`). "
             "Estimates are conservative: measured on a 100k-row sample, so compressed formats usually come out 10-30% larger than the real 1M-row chunk files. `wide_numeric` is capped at 100M rows "
             "unless `--allow-large-wide`.", ""]
    bpr_cache = {t: measure_bytes_per_row(t, formats, a.compression, a.price_as) for t in tables}
    lines += ["## Bytes per row (measured)", "",
              "| table | arrow in-memory | " + " | ".join(formats) + " |",
              "|---|---|" + "---|" * len(formats)]
    for t in tables:
        b = bpr_cache[t]
        lines.append(f"| {t} | {b['arrow_memory']:.1f} | " + " | ".join(f"{b[f]:.1f}" for f in formats) + " |")
    lines += ["", "## Projected sizes per scale N", ""]
    lines += ["| N | table | rows | arrow in-memory | " + " | ".join(formats) + " |",
              "|---|---|---|---|" + "---|" * len(formats)]
    for n in sizes:
        sc = S.Scale(n)
        for t in tables:
            rows = effective_rows(t, n, sc, a.allow_large_wide)
            b = bpr_cache[t]
            lines.append(f"| {S.size_label(n)} | {t} | {rows:,} | {_human(b['arrow_memory'] * rows)} | "
                         + " | ".join(_human(b[f] * rows) for f in formats) + " |")
    text = "\n".join(lines) + "\n"
    print(text)
    if a.markdown:
        Path(a.markdown).parent.mkdir(parents=True, exist_ok=True)
        Path(a.markdown).write_text(text, encoding="utf-8")
        print(f"wrote {a.markdown}")
    return 0


# --------------------------------------------------------------------- gen
def _chunk_job(job: dict) -> dict:
    table, idx, start, cnt = job["table"], job["index"], job["start"], job["rows"]
    out_dir = Path(job["out_dir"])
    base = out_dir / f"part-{idx:05d}"
    meta_path = out_dir / f"part-{idx:05d}.meta.json"
    formats = job["formats"]
    if job["sink"] == "files" and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if all((out_dir / m["path"]).exists() for m in meta["files"].values()) and \
                set(meta["files"]) >= set(formats) and meta["seed"] == job["seed"]:
            meta["resumed"] = True
            return meta
    t0 = time.perf_counter()
    scale = S.Scale(job["n"])
    canon = fast.gen_chunk(table, start, cnt, scale, job["seed"])
    gen_s = time.perf_counter() - t0
    digest = ck.digest_table(canon) if job["checksum"] == "full" else None
    files = {}
    if job["sink"] == "files":
        tbl = fast.to_output(canon, job["price_as"])
        for fmt in formats:
            p = writers.write_table(tbl, base, fmt, job["compression"])
            files[fmt] = {"path": p.name, "bytes": p.stat().st_size,
                          "sha256": writers.sha256_file(p) if job["file_hash"] else None}
    meta = {"index": idx, "start": start, "rows": cnt, "seed": job["seed"], "files": files,
            "digest": ck.to_json(digest) if digest else None,
            "gen_seconds": round(gen_s, 4), "total_seconds": round(time.perf_counter() - t0, 4)}
    if job["sink"] == "files":
        meta_path.write_text(json.dumps(meta))
    return meta


def cmd_gen(a) -> int:
    seed = _seed(a.seed)
    formats = [f for f in a.formats.split(",") if f]
    for f in formats:
        if f not in writers.FORMATS:
            sys.exit(f"unknown format {f}")
    n = S.parse_rows(a.rows)
    out_root = Path(a.out)
    tables = _tables(a.dataset)
    sink = "null" if a.sink == "null" else "files"
    scale = S.Scale(n)

    if sink == "files":
        total, per = estimate_total(tables, n, formats, a.compression, a.price_as)
        for t in per:
            t["rows"] = effective_rows(t["table"], n, scale, a.allow_large_wide)
        total = int(sum(sum(bpr["bytes_per_row"][f] for f in formats) * bpr["rows"] for bpr in per))
        out_root.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(out_root).free
        cap = env.get_float("MAX_DISK_GB", 0) * 1e9 if env.get("MAX_DISK_GB") else free
        budget = min(free, cap)
        print(f"estimated output: {_human(total)} | free disk: {_human(free)} | budget: {_human(budget)}")
        for t in per:
            print(f"  {t['table']:<14} {t['rows']:>13,} rows  " +
                  "  ".join(f"{f}={_human(t['size'][f])}" for f in formats))
        if total * 1.1 > budget and not a.force:
            print("REFUSING: estimated size exceeds the disk budget. Use a smaller --rows, set "
                  "MAX_DISK_GB, --sink null (generate on the fly), or --force.", file=sys.stderr)
            return 2
        if a.dry_run:
            print("dry run: nothing written")
            return 0
    elif a.dry_run:
        print("dry run: sink=null, nothing to write")
        return 0

    for table in tables:
        rows = effective_rows(table, n, scale, a.allow_large_wide)
        cr = effective_chunk_rows(table, a.chunk_rows)
        ranges = chunk_ranges(rows, cr)
        out_dir = out_root / table / S.size_label(n)
        if sink == "files":
            out_dir.mkdir(parents=True, exist_ok=True)
        jobs = [dict(table=table, index=i, start=s, rows=c, n=n, seed=seed, out_dir=str(out_dir),
                     formats=formats, compression=a.compression, price_as=a.price_as,
                     checksum=a.checksum, sink=sink, file_hash=not a.no_file_hash)
                for i, (s, c) in enumerate(ranges)]
        t0 = time.perf_counter()
        metas = []
        if a.workers <= 1:
            for j in jobs:
                metas.append(_chunk_job(j))
                _progress(table, len(metas), len(jobs), rows, t0)
        else:
            with ProcessPoolExecutor(max_workers=a.workers) as ex:
                for m in ex.map(_chunk_job, jobs):
                    metas.append(m)
                    _progress(table, len(metas), len(jobs), rows, t0)
        el = time.perf_counter() - t0
        print(f"\n{table}: {rows:,} rows in {el:.1f}s ({rows / max(el, 1e-9):,.0f} rows/s)")
        merged = None
        if a.checksum == "full":
            for m in metas:
                merged = ck.merge(merged, ck.from_json(m["digest"]))
        manifest = {
            "dataset": next(k for k, v in S.DATASET_TABLES.items() if v == table),
            "table": table, "scale_n": n, "rows": rows, "seed": f"0x{seed:X}",
            "generator_version": S.GENERATOR_VERSION, "price_as": a.price_as,
            "chunk_rows": cr, "formats": formats, "compression": a.compression,
            "schema": [f"{f.name}:{f.type}" for f in
                       fast.to_output(fast.gen_chunk(table, 0, 1, scale, seed), a.price_as).schema],
            "csv_null": writers.CSV_NULL,
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "column_digests": ck.to_json(merged) if merged else None,
            "table_digest": ck.table_digest(merged) if merged else None,
            "chunks": [{k: m[k] for k in ("index", "start", "rows", "files", "digest")} for m in metas],
        }
        if sink == "files":
            (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
            print(f"manifest: {out_dir / 'manifest.json'}  table_digest={manifest['table_digest']}")
        else:
            print(f"sink=null table_digest={manifest['table_digest']}")
    return 0


_last_progress = [0.0]


def _progress(table, done, total, rows, t0):
    now = time.perf_counter()
    if done != total and now - _last_progress[0] < 1.0:
        return
    _last_progress[0] = now
    end = "\r" if sys.stdout.isatty() else "\n"
    sys.stdout.write(f"  {table}: chunk {done}/{total}  {now - t0:6.1f}s{end}")
    sys.stdout.flush()


# --------------------------------------------------------------------- verify
def cmd_verify(a) -> int:
    ok = True
    for mpath in sorted(Path(a.dir).rglob("manifest.json")) if Path(a.dir).is_dir() else [Path(a.dir)]:
        m = json.loads(mpath.read_text())
        base = mpath.parent
        merged = None
        bad = 0
        for ch in m["chunks"]:
            for fmt, f in ch["files"].items():
                p = base / f["path"]
                if not p.exists():
                    print(f"MISSING {p}"); bad += 1; continue
                if f.get("sha256") and writers.sha256_file(p) != f["sha256"]:
                    print(f"SHA256 MISMATCH {p}"); bad += 1
            if "parquet" in ch["files"] and m["column_digests"] is not None:
                tbl = writers.from_output(pq.read_table(base / ch["files"]["parquet"]["path"]))
                d = ck.digest_table(tbl)
                if ck.to_json(d) != ch["digest"]:
                    print(f"DIGEST MISMATCH chunk {ch['index']} in {mpath}"); bad += 1
                merged = ck.merge(merged, d)
        if merged is not None and bad == 0 and ck.table_digest(merged) != m["table_digest"]:
            print(f"TABLE DIGEST MISMATCH {mpath}"); bad += 1
        print(f"{'OK  ' if bad == 0 else 'FAIL'} {mpath} ({m['rows']:,} rows, {len(m['chunks'])} chunks)")
        ok &= bad == 0
    return 0 if ok else 1


# --------------------------------------------------------------------- golden
def _ref_digest_and_head(table: str, n: int, rows: int, seed: int):
    from .reference import make_ref
    scale = S.Scale(n)
    ref, cols = make_ref(table, seed, scale)
    d = ck.digest_rows(cols, (ref.row(i) for i in range(rows)))
    head = [[_jsonable(v) for v in ref.row(i)] for i in range(3)]
    return cols, d, head


def _jsonable(v):
    return f"f64:{ck._canon(v):016x}" if isinstance(v, float) else v


def cmd_golden(a) -> int:
    seed = S.DEFAULT_SEED
    out = {"generator_version": S.GENERATOR_VERSION, "seed": f"0x{seed:X}",
           "note": "Produced by the pure-Python reference. Floats in `head` are shown as f64:<16-hex IEEE-754 bits>.",
           "cases": []}
    for n, limit in ((1000, None), (10_000, None), (1_000_000, a.rows)):
        scale = S.Scale(n)
        for t in S.TABLE_IDS:
            rows = scale.rows(t) if limit is None else min(scale.rows(t), limit)
            t0 = time.perf_counter()
            cols, d, head = _ref_digest_and_head(t, n, rows, seed)
            got = ck.digest_table(fast.gen_chunk(t, 0, rows, scale, seed))
            assert got == d, f"fast != reference for {t} n={n}"
            out["cases"].append({"scale_n": n, "table": t, "rows": rows, "columns": cols,
                                 "column_digests": ck.to_json(d), "table_digest": ck.table_digest(d),
                                 "head": head})
            print(f"golden {t} N={n} rows={rows}: ok ({time.perf_counter() - t0:.1f}s)")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1))
    print(f"wrote {a.out}")
    return 0


def main(argv=None) -> int:
    env.load_dotenv()
    p = argparse.ArgumentParser(prog="python -m generator", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--dataset", default="A", help="A-E, table names, comma list, or 'all' (default A)")
        sp.add_argument("--formats", default=env.get("GEN_FORMATS", DEFAULT_FORMATS))
        sp.add_argument("--compression", default=env.get("PARQUET_COMPRESSION", "zstd"))
        sp.add_argument("--price-as", default=env.get("PRICE_AS", "decimal"),
                        choices=["decimal", "float64", "cents"])
        sp.add_argument("--allow-large-wide", action="store_true",
                        help="allow wide_numeric above 100M rows")

    g = sub.add_parser("gen", help="generate dataset files (or stream with --sink null)")
    common(g)
    g.add_argument("--rows", required=True, help="scale N: 1k,10k,1m,10m,100m,1b or an integer")
    g.add_argument("--seed", default=None)
    g.add_argument("--out", default=str(env.get_path("DATA_DIR", "./data")))
    g.add_argument("--chunk-rows", type=int, default=env.get_int("CHUNK_ROWS", S.DEFAULT_CHUNK_ROWS))
    g.add_argument("--workers", type=int, default=env.get_int("GEN_WORKERS", 4))
    g.add_argument("--checksum", choices=["full", "none"], default=env.get("GEN_CHECKSUM", "full"))
    g.add_argument("--sink", choices=["files", "null"], default="files",
                   help="null = generate+digest on the fly without writing (streaming throughput test)")
    g.add_argument("--no-file-hash", action="store_true", help="skip sha256 of written files")
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--force", action="store_true", help="ignore the disk guard")
    g.set_defaults(fn=cmd_gen)

    e = sub.add_parser("estimate", help="measure bytes/row and print projected sizes")
    common(e)
    e.add_argument("--rows", default=None, help="comma list; default all six sizes")
    e.add_argument("--markdown", default=None, help="write the report to this file")
    e.set_defaults(fn=cmd_estimate, dataset="all")

    v = sub.add_parser("verify", help="re-check files against manifest(s)")
    v.add_argument("dir")
    v.set_defaults(fn=cmd_verify)

    gl = sub.add_parser("golden", help="(re)generate spec/golden.json with the reference implementation")
    gl.add_argument("--rows", type=int, default=100_000)
    gl.add_argument("--out", default=str(env.ROOT / "spec" / "golden.json"))
    gl.set_defaults(fn=cmd_golden)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
