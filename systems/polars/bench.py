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


# Phase 3b ops. Dimension frames (customers/products) are eager DataFrames passed as lazies in `dims`.
def op06(lf, dims):
    j = lf.join(dims["customers"], on="customer_id", how="inner")
    return agg(j.group_by("segment"), pl.len().cast(I64), CENTS.sum().cast(I64), sum_or_null(C("quantity")))


def op07(lf, dims):
    cust = dims["customers"].filter(C("segment") == "enterprise")
    j = lf.join(cust, on="customer_id", how="inner").join(dims["products"], on="product_id", how="inner")
    return agg(j.group_by("brand"), pl.len().cast(I64), CENTS.sum().cast(I64))


def op08(lf, dims):
    # wrapping uint64 arithmetic: rn * id and the sum both wrap mod 2^64 (polars release build)
    o = lf.sort(["transaction_timestamp", "transaction_id"]).select(
        C("transaction_id").cast(pl.UInt64).alias("id"))
    o = o.with_columns(pl.int_range(1, pl.len() + 1, dtype=pl.UInt64).alias("rn"))
    return o.select(C("id").first().alias("c0"), C("id").last().alias("c1"), (C("rn") * C("id")).sum().alias("c2"))


def op09(lf, dims):
    g = lf.group_by("customer_id").agg(CENTS.sum().cast(I64).alias("total"))
    top = g.sort(["total", "customer_id"], descending=[True, False]).head(100)
    return top.select(pl.int_range(1, pl.len() + 1, dtype=I64).alias("c0"), C("customer_id"), C("total"))


OPS = {
    "OP01": (["quantity", "unit_price", "is_returned"], op01),
    "OP03": (["country", "quantity", "unit_price"], op03),
    "OP04": (["customer_id", "unit_price"], op04),
    "OP05": (["country", "category", "transaction_date", "unit_price"], op05),
    "OP10": (["customer_id", "product_id", "store_id", "transaction_date"], op10),
    "OP19": (["quantity", "country"], op19),
    "OP21": (["unit_price"], op21),
    "OP22": (["transaction_id", "customer_id", "unit_price", "transaction_timestamp", "transaction_date"], op22),
    "OP06": (["customer_id", "quantity", "unit_price"], op06),
    "OP07": (["customer_id", "product_id", "unit_price"], op07),
    "OP08": (["transaction_id", "transaction_timestamp"], op08),
    "OP09": (["customer_id", "unit_price"], op09),
}
NEW = {"OP06", "OP07", "OP08", "OP09"}
DIMS = {"OP06": ["customers"], "OP07": ["customers", "products"]}
DIM_SRC = {"customers": ("dim_customer", ["customer_id", "segment"]),
           "products": ("dim_product", ["product_id", "brand"])}

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
            df = pl.concat([pl.read_csv(f, schema=CSV_SCHEMA, null_values=["\\N"], missing_utf8_is_empty_string=True, has_header=True,
                                        n_threads=args.threads) for f in files])
            res = op15(df.lazy()).collect()
        else:
            res = op15(pl.scan_csv(files, schema=CSV_SCHEMA, null_values=["\\N"], missing_utf8_is_empty_string=True, has_header=True)
                       ).collect(engine="streaming")
        rows, floats = finish(res, op)
        compute_ms = (time.perf_counter() - t0) * 1000
    else:
        cols, fn = OPS[op]
        files = sorted(glob.glob(os.path.join(ddir, "part-*.parquet")))
        if op == "OP08" and args.mode != "materialized":
            sys.exit("OP08 is materialized only")
        dims = {}
        t0 = time.perf_counter()
        for d in DIMS.get(op, []):  # dimension tables always loaded first (counts as load_ms)
            dn, dc = DIM_SRC[d]
            dims[d] = pl.read_parquet(sorted(glob.glob(os.path.join(args.input, dn, label, "part-*.parquet"))),
                                      columns=dc).lazy()
        if args.mode == "materialized":
            df = pl.read_parquet(files, columns=cols)
            load_ms = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            res = (fn(df.lazy(), dims) if op in NEW else fn(df.lazy())).collect()
        else:
            load_ms = (time.perf_counter() - t0) * 1000 if dims else 0.0
            t0 = time.perf_counter()
            lf = pl.scan_parquet(files)
            res = (fn(lf, dims) if op in NEW else fn(lf)).collect(engine="streaming")
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
