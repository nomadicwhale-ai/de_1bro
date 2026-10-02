#!/usr/bin/env python3
"""Track S driver: Polars. See systems/polars/README.md for semantics and notes."""
import argparse
import glob
import json
import os
import sys
import time

ap = argparse.ArgumentParser()
ap.add_argument("--op", required=True)
ap.add_argument("--dataset", default="A")
ap.add_argument("--rows", type=int, required=True)
ap.add_argument("--mode", choices=["streaming", "materialized"], required=True)
ap.add_argument("--chunk-rows", type=int, default=0)
ap.add_argument("--threads", type=int, default=1)
ap.add_argument("--input", required=True)
ap.add_argument("--output-json", action="store_true")
args = ap.parse_args()

os.environ["POLARS_MAX_THREADS"] = str(args.threads)  # must precede the polars import
import polars as pl  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from generator.resultdigest import digest_rows  # noqa: E402

LABELS = {1000: "1k", 10000: "10k", 1000000: "1m", 10000000: "10m", 100000000: "100m", 1000000000: "1b"}
label = LABELS[args.rows]
ddir = os.path.join(args.input, "sales_fact", label)

C = pl.col
CENTS = (C("unit_price") * 100).cast(pl.Int64)  # decimal(18,2) * 100 -> exact decimal -> Int64 (no float)
I64 = pl.Int64
# Vector-valued 100.0 (derived from the data so the optimizer cannot treat it as a scalar literal):
# polars turns `x / <scalar literal>` into `x * (1/lit)`, which is NOT IEEE division (e.g. 130886/100.0
# != 130886 * 0.01). Dividing by a column gives the exact IEEE result required by OP21/OP22.
H100 = (CENTS * 0 + 100).cast(pl.Float64)


def sel(lf, *exprs):
    """select with unique positional output names (result columns are positional)."""
    return lf.select([e.alias(f"c{i}") for i, e in enumerate(exprs)])


def agg(g, *exprs):
    return g.agg([e.alias(f"a{i}") for i, e in enumerate(exprs)])


def sum_or_null(c):
    """sum skipping NULLs; NULL (not 0) when every value is NULL."""
    return pl.when(c.count() > 0).then(c.cast(I64).sum()).otherwise(None)


# op -> (needed parquet columns, function LazyFrame -> LazyFrame of result)
def op01(lf):
    return sel(
        lf, pl.len().cast(I64), C("quantity").count().cast(I64), sum_or_null(C("quantity")),
        CENTS.sum().cast(I64), CENTS.min(), CENTS.max(), C("is_returned").sum().cast(I64))


def op03(lf):
    return agg(lf.group_by("country"),
        pl.len().cast(I64), sum_or_null(C("quantity")), CENTS.sum().cast(I64))


def op04(lf):
    return agg(lf.group_by("customer_id"), pl.len().cast(I64), CENTS.sum().cast(I64))


def op05(lf):
    return agg(lf.group_by("country", "category", C("transaction_date").dt.year().cast(I64).alias("year")),
        pl.len().cast(I64), CENTS.sum().cast(I64))


def op10(lf):
    return sel(
        lf, C("customer_id").drop_nulls().n_unique().cast(I64),
        C("product_id").drop_nulls().n_unique().cast(I64),
        pl.struct("store_id", "transaction_date").n_unique().cast(I64))


def op19(lf):
    return sel(
        lf, C("quantity").is_null().sum().cast(I64), C("country").is_null().sum().cast(I64),
        C("quantity").fill_null(1).cast(I64).sum(),
        (C("country").is_not_null() & (C("country") != "")).sum().cast(I64),
        C("country").drop_nulls().n_unique().cast(I64))


def op21(lf):
    v = CENTS.cast(pl.Float64) / H100
    # naive_sum: plain f64 sum (polars may use pairwise/SIMD; rtol 1e-9 applies).
    # kahan_sum: exact int64 cents total / 100.0 (the correctly rounded value a compensated sum approximates).
    return sel(lf, CENTS.sum().cast(I64), v.sum(), CENTS.sum().cast(pl.Float64))


def op22(lf):
    k = C("transaction_id") * 4294967311 + C("customer_id")
    f = CENTS.cast(pl.Float64) / H100
    us = C("transaction_timestamp").dt.timestamp("us")
    d = C("transaction_date").dt
    return sel(
        lf, (k.cast(pl.Float64).cast(I64) != k).sum().cast(I64),
        ((f * 100.0).cast(I64) != CENTS).sum().cast(I64),  # float->int cast truncates toward zero
        (((us // 1000) * 1000) != us).sum().cast(I64),
        (d.year().cast(I64) * 10000 + d.month().cast(I64) * 100 + d.day().cast(I64)).sum().cast(I64))


OPS = {
    "OP01": (["quantity", "unit_price", "is_returned"], op01),
    "OP03": (["country", "quantity", "unit_price"], op03),
    "OP04": (["customer_id", "unit_price"], op04),
    "OP05": (["country", "category", "transaction_date", "unit_price"], op05),
    "OP10": (["customer_id", "product_id", "store_id", "transaction_date"], op10),
    "OP19": (["quantity", "country"], op19),
    "OP21": (["unit_price"], op21),
    "OP22": (["transaction_id", "customer_id", "unit_price", "transaction_timestamp", "transaction_date"], op22),
}

CSV_SCHEMA = {
    "transaction_id": pl.Int64, "customer_id": pl.Int64, "product_id": pl.Int64, "store_id": pl.Int64,
    "quantity": pl.Int64, "unit_price": pl.Decimal(18, 2), "discount": pl.Float64, "tax": pl.Float64,
    "country": pl.String, "category": pl.String, "transaction_date": pl.String,
    "transaction_timestamp": pl.String, "is_returned": pl.Boolean,
}


def op15(lf):
    d = lf.with_columns(
        C("transaction_date").str.to_date("%Y-%m-%d", strict=True).alias("dt"),
        C("transaction_timestamp").str.to_datetime("%Y-%m-%d %H:%M:%S%.f", time_unit="us", strict=True).alias("ts"))
    us = C("ts").dt.timestamp("us")
    return sel(
        d, pl.len().cast(I64), C("transaction_id").sum().cast(I64), C("customer_id").sum().cast(I64),
        C("product_id").sum().cast(I64), C("store_id").sum().cast(I64), sum_or_null(C("quantity")).fill_null(0),
        C("quantity").is_null().sum().cast(I64), CENTS.sum().cast(I64),
        (C("discount") * 1e6 + 0.5).floor().cast(I64).sum().cast(I64),
        (C("tax") * 1e6 + 0.5).floor().cast(I64).sum().cast(I64),
        C("country").str.len_bytes().sum().cast(I64), C("country").is_null().sum().cast(I64),
        C("category").str.len_bytes().sum().cast(I64),
        C("dt").dt.epoch("d").cast(I64).sum().cast(I64),
        (us // 1_000_000).sum().cast(I64), (us % 1_000_000).sum().cast(I64),
        C("is_returned").sum().cast(I64))


def finish(df, op):
    """Result frame -> list of python tuples (part of compute_ms)."""
    rows = df.rows()
    if op == "OP21":
        e, naive, cents_f = rows[0]
        kahan = cents_f / 100.0  # one scalar division of the exact total
        return [(e, f"{e // 100}.{e % 100:02d}")], {"naive_sum": naive, "kahan_sum": kahan}
    return rows, {}


def main():
    op = args.op
    load_ms = 0.0
    if op == "OP15":
        files = sorted(glob.glob(os.path.join(ddir, "part-*.csv")))
        t0 = time.perf_counter()
        if args.mode == "materialized":
            df = pl.concat([pl.read_csv(f, schema=CSV_SCHEMA, null_values=["\\N"], has_header=True,
                                        n_threads=args.threads) for f in files])
            res = op15(df.lazy()).collect()
        else:
            res = op15(pl.scan_csv(files, schema=CSV_SCHEMA, null_values=["\\N"], has_header=True)
                       ).collect(engine="streaming")
        rows, floats = finish(res, op)
        compute_ms = (time.perf_counter() - t0) * 1000
    else:
        cols, fn = OPS[op]
        files = sorted(glob.glob(os.path.join(ddir, "part-*.parquet")))
        if args.mode == "materialized":
            t0 = time.perf_counter()
            df = pl.read_parquet(files, columns=cols)
            load_ms = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            res = fn(df.lazy()).collect()
        else:
            t0 = time.perf_counter()
            res = fn(pl.scan_parquet(files)).collect(engine="streaming")
        rows, floats = finish(res, op)
        compute_ms = (time.perf_counter() - t0) * 1000
    checksum, count = digest_rows(rows)
    out = {"load_ms": load_ms, "compute_ms": compute_ms, "checksum": checksum, "row_count": count,
           "toolchain": {"name": "polars", "version": pl.__version__, "flags": f"POLARS_MAX_THREADS={args.threads}"},
           "notes": ""}
    if floats:
        out["floats"] = floats
    print(json.dumps(out))


main()
