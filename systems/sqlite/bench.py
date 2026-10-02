#!/usr/bin/env python3
"""Track S driver: SQLite (python stdlib sqlite3), materialized mode, validation scale only.

load_ms    = CSV chunk files -> in-memory `sales` table (csv.reader + executemany, one transaction)
compute_ms = the op's SQL query + fetchall.  OP15: import + summary query as one compute_ms, load_ms = 0.
"""
import argparse, csv, json, sqlite3, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

LABELS = {1000: "1k", 10000: "10k", 1000000: "1m", 10000000: "10m", 100000000: "100m", 1000000000: "1b"}

SCHEMA = """CREATE TABLE sales(transaction_id INTEGER, customer_id INTEGER, product_id INTEGER, store_id INTEGER,
 quantity INTEGER, cents INTEGER, discount REAL, tax REAL, country TEXT, category TEXT,
 date_days INTEGER, ts_us INTEGER, is_returned INTEGER)"""
INSERT = "INSERT INTO sales VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"


def days_from_civil(y, m, d):
    y -= m <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def make_rows(files):
    """Yield typed tuples. Money parsed from decimal text without floats; NULL for \\N."""
    daycache = {}
    for f in files:
        with open(f, newline="", encoding="utf-8") as fh:
            rd = csv.reader(fh)
            next(rd)  # header
            for r in rd:
                p = r[5]
                a, _, b = p.partition(".")
                if a[:1] == "-":
                    cents = -(int(a[1:] or 0) * 100 + int((b + "00")[:2]))
                else:
                    cents = int(a) * 100 + int((b + "00")[:2])
                ds = r[10]
                dd = daycache.get(ds)
                if dd is None:
                    dd = daycache[ds] = days_from_civil(int(ds[:4]), int(ds[5:7]), int(ds[8:10]))
                t = r[11]
                fr = t[20:]
                us = (dd * 86400 + int(t[11:13]) * 3600 + int(t[14:16]) * 60 + int(t[17:19])) * 1000000 \
                    + (int((fr + "000000")[:6]) if fr else 0)
                q = r[4]
                c = r[8]
                yield (int(r[0]), int(r[1]), int(r[2]), int(r[3]),
                       None if q == "\\N" else int(q), cents, float(r[6]), float(r[7]),
                       None if c == "\\N" else c, r[9], dd, us, 1 if r[12] == "true" else 0)


def import_csv(con, files):
    con.execute(SCHEMA)
    con.execute("BEGIN")
    con.executemany(INSERT, make_rows(files))
    con.execute("COMMIT")


# Hinnant civil_from_days in pure SQL, evaluated once per DISTINCT date_days value (few thousand) and
# joined back to the fact rows; yields columns date_days, year, month, day.
YMD_SQL = """
SELECT date_days, y + (m <= 2) AS year, m AS month, dd AS day FROM (
 SELECT *, CASE WHEN mp < 10 THEN mp + 3 ELSE mp - 9 END AS m, doy - (153*mp + 2)/5 + 1 AS dd FROM (
  SELECT *, (5*doy + 2)/153 AS mp FROM (
   SELECT *, doe - (365*yoe + yoe/4 - yoe/100) AS doy, yoe + era*400 AS y FROM (
    SELECT *, (doe - doe/1460 + doe/36524 - doe/146096)/365 AS yoe FROM (
     SELECT *, z - era*146097 AS doe FROM (
      SELECT *, (z - CASE WHEN z < 0 THEN 146096 ELSE 0 END)/146097 AS era FROM (
       SELECT *, date_days + 719468 AS z FROM (SELECT DISTINCT date_days FROM sales))))))))"""

Q = {
 "OP01": "SELECT count(*), count(quantity), sum(quantity), sum(cents), min(cents), max(cents), "
         "count(*) FILTER (WHERE is_returned) FROM sales",
 "OP03": "SELECT country, count(*), sum(quantity), sum(cents) FROM sales GROUP BY country",
 "OP04": "SELECT customer_id, count(*), sum(cents) FROM sales GROUP BY customer_id",
 "OP05": f"WITH y AS MATERIALIZED ({YMD_SQL}) SELECT country, category, y.year, count(*), sum(cents) FROM sales JOIN y USING (date_days) "
         "GROUP BY country, category, y.year",
 "OP10": "SELECT (SELECT count(DISTINCT customer_id) FROM sales), (SELECT count(DISTINCT product_id) FROM sales), "
         "(SELECT count(*) FROM (SELECT DISTINCT store_id, date_days FROM sales))",
 "OP15": "SELECT count(*), sum(transaction_id), sum(customer_id), sum(product_id), sum(store_id), sum(quantity), "
         "count(*) FILTER (WHERE quantity IS NULL), sum(cents), "
         "sum(CAST(floor(discount*1e6+0.5) AS INTEGER)), sum(CAST(floor(tax*1e6+0.5) AS INTEGER)), "
         "sum(length(CAST(country AS BLOB))), count(*) FILTER (WHERE country IS NULL), "
         "sum(length(CAST(category AS BLOB))), sum(date_days), "
         "sum((ts_us - ((ts_us % 1000000) + 1000000) % 1000000) / 1000000), "
         "sum(((ts_us % 1000000) + 1000000) % 1000000), count(*) FILTER (WHERE is_returned) FROM sales",
 "OP19": "SELECT count(*) FILTER (WHERE quantity IS NULL), count(*) FILTER (WHERE country IS NULL), "
         "sum(coalesce(quantity, 1)), count(*) FILTER (WHERE country IS NOT NULL AND country <> ''), "
         "count(DISTINCT country) FROM sales",
 # exact sum + formatted decimal; floats: sum() and (>=3.43) Kahan-Babuska sum()
 "OP21": "SELECT s, CAST(s/100 AS TEXT) || '.' || printf('%02d', s % 100), f1, f2 FROM "
         "(SELECT sum(cents) AS s, sum(cents/100.0) AS f1, sum(cents/100.0) AS f2 FROM sales)",
 "OP22": f"WITH y AS MATERIALIZED ({YMD_SQL}) "
         "SELECT count(*) FILTER (WHERE CAST(CAST(transaction_id*4294967311 + customer_id AS REAL) AS INTEGER) "
         "<> transaction_id*4294967311 + customer_id), "
         "count(*) FILTER (WHERE CAST((cents/100.0)*100.0 AS INTEGER) <> cents), "
         "count(*) FILTER (WHERE (ts_us/1000)*1000 <> ts_us), "
         f"sum(y.year*10000 + y.month*100 + y.day) FROM sales JOIN y USING (date_days)",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--op", required=True)
    ap.add_argument("--dataset", default="A")
    ap.add_argument("--rows", type=int, required=True)
    ap.add_argument("--mode", default="materialized")
    ap.add_argument("--chunk-rows", type=int, default=0)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output-json", action="store_true")
    a = ap.parse_args()
    if a.mode != "materialized":
        sys.exit("sqlite: only materialized mode is supported")
    if a.op not in Q:
        sys.exit(f"sqlite: unsupported op {a.op}")
    files = sorted((Path(a.input) / "sales_fact" / LABELS[a.rows]).glob("part-*.csv"))
    if not files:
        sys.exit("sqlite: no csv chunk files found")

    con = sqlite3.connect(":memory:", isolation_level=None)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    clock = time.perf_counter
    if a.op == "OP15":
        t0 = clock()
        import_csv(con, files)
        res = con.execute(Q["OP15"]).fetchall()
        compute_ms, load_ms = (clock() - t0) * 1000, 0.0
    else:
        t0 = clock()
        import_csv(con, files)
        load_ms = (clock() - t0) * 1000
        t0 = clock()
        res = con.execute(Q[a.op]).fetchall()
        compute_ms = (clock() - t0) * 1000

    from generator.resultdigest import digest_rows
    floats = {}
    if a.op == "OP21":
        r = res[0]
        floats = {"naive_sum": float(r[2]), "kahan_sum": float(r[3])}
        res = [(r[0], r[1])]
    checksum, n = digest_rows(res)
    ver = sqlite3.sqlite_version
    out = {"load_ms": load_ms, "compute_ms": compute_ms, "checksum": checksum, "row_count": n,
           "toolchain": {"name": "sqlite", "version": ver, "flags": "in-memory csv.reader+executemany"},
           "notes": "in-memory db"}
    if floats:
        out["floats"] = floats
    print(json.dumps(out))


if __name__ == "__main__":
    main()
