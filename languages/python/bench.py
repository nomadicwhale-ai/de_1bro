#!/usr/bin/env python3
"""Track L / Python stdlib-only benchmark (CPython 3.11). See README.md in this directory."""
import argparse
import csv
import gc
import heapq
import json
import math
import os
import platform
import sys
import time
from collections import Counter, defaultdict
from itertools import islice

NA = "\\N"
MASK = (1 << 64) - 1
GOLDEN = 0x9E3779B97F4A7C15
C1 = 0xBF58476D1CE4E5B9
C2 = 0x94D049BB133111EB
NULL_CANON = 0xA5A5A5A5A5A5A5A5
FNV_OFF = 0xCBF29CE484222325
FNV_PRIME = 0x100000001B3
BATCH = 65536
LABELS = {1000: "1k", 10000: "10k", 1000000: "1m", 10000000: "10m", 100000000: "100m",
          1000000000: "1b"}

# ---------------------------------------------------------------- digest (own code)


def mix64(z):
    z &= MASK
    z ^= z >> 30
    z = (z * C1) & MASK
    z ^= z >> 27
    z = (z * C2) & MASK
    z ^= z >> 31
    return z


def fnv1a64(data):
    h = FNV_OFF
    for b in data:
        h = ((h ^ b) * FNV_PRIME) & MASK
    return h


_fnv_cache = {}


def canon(v):
    if v is None:
        return NULL_CANON
    if isinstance(v, str):
        h = _fnv_cache.get(v)
        if h is None:
            h = _fnv_cache[v] = fnv1a64(v.encode("utf-8"))
        return h
    return v & MASK  # int / bool


def digest(rows):
    s = x = n = 0
    for row in rows:
        h = 0
        for v in row:
            h = mix64(h + canon(v) + GOLDEN)
        s = (s + h) & MASK
        x ^= h
        n += 1
    return "%016x%016x" % (s, x), n


# ---------------------------------------------------------------- date / time helpers


def days_from_civil(y, m, d):
    if m <= 2:
        y -= 1
    era = y // 400
    yoe = y - era * 400
    doy = (153 * (m - 3 if m > 2 else m + 9) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(z):
    z += 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    return (y + (m <= 2), m, d)


class DayCache(dict):
    """'YYYY-MM-DD' -> days since epoch, memoised (a few thousand distinct dates)."""

    def __missing__(self, s):
        v = days_from_civil(int(s[:4]), int(s[5:7]), int(s[8:10]))
        self[s] = v
        return v


class SecCache(dict):
    """'HH:MM:SS' -> seconds of day."""

    def __missing__(self, s):
        v = int(s[:2]) * 3600 + int(s[3:5]) * 60 + int(s[6:8])
        self[s] = v
        return v


class YearCache(dict):
    """days -> civil year (Hinnant civil_from_days)."""

    def __missing__(self, z):
        v = civil_from_days(z)[0]
        self[z] = v
        return v


DAYS = DayCache()
SECS = SecCache()
YEARS = YearCache()


def _cents_slow(s):
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    a, _, b = s.partition(".")
    b = (b + "00")[:2]
    v = int(a or "0") * 100 + int(b)
    return -v if neg else v


# ---------------------------------------------------------------- column converters
# each takes a tuple of raw strings (one batch of one column) and returns a list (or tuple of lists)


def c_int(t):
    return list(map(int, t))


def c_qty(t):
    return [None if x == NA else int(x) for x in t]


def c_str(t):
    return [None if x == NA else x for x in t]


def c_raw(t):
    return t


def c_cents(t):
    return [int(s.replace(".", "")) if s[-3:-2] == "." else _cents_slow(s) for s in t]


def c_days(t):
    d = DAYS
    return [d[s] for s in t]


def c_ts(t):
    d = DAYS
    sc = SECS
    return ([d[s[:10]] * 86400 + sc[s[11:19]] for s in t], [int(s[20:26]) for s in t])


def c_bool(t):
    return [x == "true" for x in t]


COLS = {  # name -> (index, converter)
    "tid": (0, c_int), "cid": (1, c_int), "pid": (2, c_int), "store": (3, c_int),
    "qty": (4, c_qty), "cents": (5, c_cents), "disc": (6, c_raw), "tax": (7, c_raw),
    "country": (8, c_str), "category": (9, c_raw), "days": (10, c_days), "ts": (11, c_ts),
    "ret": (12, c_bool),
}


def chunk_files(root, rows, table="sales_fact"):
    d = os.path.join(root, table, LABELS[rows])
    return [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.startswith("part-") and f.endswith(".csv")]


def read_batches(path):
    """Yield transposed batches (tuple of 13 column tuples of str)."""
    with open(path, "r", encoding="utf-8", newline="") as f:
        r = csv.reader(f)
        next(r)
        while True:
            b = list(islice(r, BATCH))
            if not b:
                break
            yield list(zip(*b))


def load(path, names, acc):
    spec = [(n,) + COLS[n] for n in names]
    for t in read_batches(path):
        for n, i, conv in spec:
            v = conv(t[i])
            if n == "ts":
                acc["ts_sec"].extend(v[0])
                acc["ts_frac"].extend(v[1])
            else:
                acc[n].extend(v)


def load_dims(root, rows, op):
    """Read small join dimensions before the fact table; callers time this as loading."""
    segments = {}
    for path in chunk_files(root, rows, "dim_customer"):
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            next(reader)
            for row in reader:
                segments[int(row[0])] = None if row[4] == NA else row[4]
    dims = {"segment": segments}
    if op == "OP07":
        brands = {}
        for path in chunk_files(root, rows, "dim_product"):
            with open(path, "r", encoding="utf-8", newline="") as f:
                next(f)
                for line in f:
                    # Only these unquoted fields are needed; the remainder is quoted JSON.
                    product_id, _, brand, _ = line.split(",", 3)
                    brands[int(product_id)] = None if brand == NA else brand
        dims["brand"] = brands
    return dims


def new_acc(names):
    acc = {n: [] for n in names if n != "ts"}
    if "ts" in names:
        acc["ts_sec"] = []
        acc["ts_frac"] = []
    return acc


# ---------------------------------------------------------------- ops: (cols, init, step, finish)


def op01():
    st = {"n": 0, "nq": 0, "sq": 0, "sp": 0, "mn": None, "mx": None, "cr": 0}

    def step(a):
        c = a["cents"]
        if not c:
            return
        q = [x for x in a["qty"] if x is not None]
        st["n"] += len(c)
        st["nq"] += len(q)
        st["sq"] += sum(q)
        st["sp"] += sum(c)
        lo, hi = min(c), max(c)
        st["mn"] = lo if st["mn"] is None or lo < st["mn"] else st["mn"]
        st["mx"] = hi if st["mx"] is None or hi > st["mx"] else st["mx"]
        st["cr"] += sum(a["ret"])

    def fin():
        return [(st["n"], st["nq"], st["sq"] if st["nq"] else None, st["sp"], st["mn"], st["mx"],
                 st["cr"])], {}
    return ["qty", "cents", "ret"], step, fin


def op03():
    cnt, qs, qn, cs = Counter(), defaultdict(int), defaultdict(int), defaultdict(int)

    def step(a):
        co = a["country"]
        cnt.update(co)
        for k, q, p in zip(co, a["qty"], a["cents"]):
            cs[k] += p
            if q is not None:
                qs[k] += q
                qn[k] += 1

    def fin():
        return [(k, n, qs[k] if qn[k] else None, cs[k]) for k, n in cnt.items()], {}
    return ["country", "qty", "cents"], step, fin


def op04():
    cnt, cs = Counter(), defaultdict(int)

    def step(a):
        cid = a["cid"]
        cnt.update(cid)
        for k, p in zip(cid, a["cents"]):
            cs[k] += p

    def fin():
        return [(k, n, cs[k]) for k, n in cnt.items()], {}
    return ["cid", "cents"], step, fin


def op05():
    cnt, cs = Counter(), defaultdict(int)

    def step(a):
        y = YEARS
        keys = list(zip(a["country"], a["category"], [y[d] for d in a["days"]]))
        cnt.update(keys)
        for k, p in zip(keys, a["cents"]):
            cs[k] += p

    def fin():
        return [(k[0], k[1], k[2], n, cs[k]) for k, n in cnt.items()], {}
    return ["country", "category", "days", "cents"], step, fin


def op06(dims):
    segments = dims["segment"]
    groups = {}

    def step(a):
        for cid, cents, qty in zip(a["cid"], a["cents"], a["qty"]):
            if cid not in segments:
                continue
            key = segments[cid]
            group = groups.get(key)
            if group is None:
                group = groups[key] = [0, 0, 0, False]
            group[0] += 1
            group[1] += cents
            if qty is not None:
                group[2] += qty
                group[3] = True

    def fin():
        return [(key, g[0], g[1], g[2] if g[3] else None) for key, g in groups.items()], {}
    return ["cid", "cents", "qty"], step, fin


def op07(dims):
    segments, brands = dims["segment"], dims["brand"]
    groups = {}

    def step(a):
        for cid, pid, cents in zip(a["cid"], a["pid"], a["cents"]):
            if segments.get(cid) != "enterprise" or pid not in brands:
                continue
            key = brands[pid]
            group = groups.get(key)
            if group is None:
                group = groups[key] = [0, 0]
            group[0] += 1
            group[1] += cents

    def fin():
        return [(key, g[0], g[1]) for key, g in groups.items()], {}
    return ["cid", "pid", "cents"], step, fin


def op08():
    result = []

    def step(a):
        # Lexicographic seconds/fraction order is the exact microsecond timestamp order.
        order = sorted(zip(a["ts_sec"], a["ts_frac"], a["tid"]))
        positional_sum = sum(rank * row[2] for rank, row in enumerate(order, 1)) & MASK
        result.append((order[0][2], order[-1][2], positional_sum))

    def fin():
        return result, {}
    return ["ts", "tid"], step, fin


def op09():
    totals = defaultdict(int)

    def step(a):
        for cid, cents in zip(a["cid"], a["cents"]):
            totals[cid] += cents

    def fin():
        top = heapq.nsmallest(100, totals.items(), key=lambda item: (-item[1], item[0]))
        return [(rank, cid, cents) for rank, (cid, cents) in enumerate(top, 1)], {}
    return ["cid", "cents"], step, fin


def op10():
    c, p, sd = set(), set(), set()

    def step(a):
        c.update(a["cid"])
        p.update(a["pid"])
        sd.update(zip(a["store"], a["days"]))

    def fin():
        return [(len(c), len(p), len(sd))], {}
    return ["cid", "pid", "store", "days"], step, fin


def op19():
    st = {"nq": 0, "nc": 0, "sq": 0, "ne": 0}
    dist = set()

    def step(a):
        q = a["qty"]
        co = a["country"]
        nq = q.count(None)
        st["nq"] += nq
        st["sq"] += sum(x for x in q if x is not None) + nq
        nc = co.count(None)
        st["nc"] += nc
        st["ne"] += len(co) - nc - co.count("")
        dist.update(co)

    def fin():
        dist.discard(None)
        return [(st["nq"], st["nc"], st["sq"], st["ne"], len(dist))], {}
    return ["qty", "country"], step, fin


def op21():
    st = {"exact": 0, "naive": 0.0, "ks": 0.0, "comp": 0.0}

    def step(a):
        c = a["cents"]
        st["exact"] += sum(c)
        naive, ks, comp = st["naive"], st["ks"], st["comp"]
        for x in c:
            v = x / 100.0
            naive += v
            y = v - comp
            t = ks + y
            comp = (t - ks) - y
            ks = t
        st["naive"], st["ks"], st["comp"] = naive, ks, comp

    def fin():
        e = st["exact"]
        return [(e, "%d.%02d" % (e // 100, e % 100))], {"naive_sum": st["naive"], "kahan_sum": st["ks"]}
    return ["cents"], step, fin


def op22():
    st = {"a": 0, "b": 0, "c": 0}
    dayc = Counter()

    def step(a):
        la = lb = 0
        for t, c, x in zip(a["tid"], a["cid"], a["cents"]):
            k = t * 4294967311 + c
            if float(k) != k:  # exact int/float comparison == int(float(k)) != k
                la += 1
            if int(x / 100.0 * 100.0) != x:
                lb += 1
        st["a"] += la
        st["b"] += lb
        st["c"] += sum(1 for f in a["ts_frac"] if f % 1000)
        dayc.update(a["days"])

    def fin():
        ymd = 0
        for z, n in dayc.items():
            y, m, d = civil_from_days(z)
            ymd += n * (y * 10000 + m * 100 + d)
        return [(st["a"], st["b"], st["c"], ymd)], {}
    return ["tid", "cid", "cents", "ts", "days"], step, fin


OPS = {"OP01": op01, "OP03": op03, "OP04": op04, "OP05": op05, "OP06": op06, "OP07": op07,
       "OP08": op08, "OP09": op09, "OP10": op10, "OP19": op19, "OP21": op21, "OP22": op22}


# ---------------------------------------------------------------- OP15 (parse everything)


def run_op15(files):
    s = dict.fromkeys("rows tid cid pid store qty nq cents disc tax cb nc gb days sec frac ret".split(), 0)
    floor = math.floor
    for path in files:
        for t in read_batches(path):
            s["rows"] += len(t[0])
            s["tid"] += sum(map(int, t[0]))
            s["cid"] += sum(map(int, t[1]))
            s["pid"] += sum(map(int, t[2]))
            s["store"] += sum(map(int, t[3]))
            q = [x for x in t[4] if x != NA]
            s["nq"] += len(t[4]) - len(q)
            s["qty"] += sum(map(int, q))
            s["cents"] += sum(c_cents(t[5]))
            s["disc"] += sum([floor(float(x) * 1e6 + 0.5) for x in t[6]])
            s["tax"] += sum([floor(float(x) * 1e6 + 0.5) for x in t[7]])
            co = [x for x in t[8] if x != NA]
            s["nc"] += len(t[8]) - len(co)
            s["cb"] += sum(map(len, map(str.encode, co)))
            s["gb"] += sum(map(len, map(str.encode, t[9])))
            s["days"] += sum(c_days(t[10]))
            sec, frac = c_ts(t[11])
            s["sec"] += sum(sec)
            s["frac"] += sum(frac)
            s["ret"] += t[12].count("true")
    return [(s["rows"], s["tid"], s["cid"], s["pid"], s["store"], s["qty"], s["nq"], s["cents"],
             s["disc"], s["tax"], s["cb"], s["nc"], s["gb"], s["days"], s["sec"], s["frac"],
             s["ret"])], {}


# ---------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--op", required=True)
    ap.add_argument("--dataset", default="A")
    ap.add_argument("--rows", type=int, required=True)
    ap.add_argument("--mode", default="streaming")
    ap.add_argument("--chunk-rows", type=int, default=0)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output-json", action="store_true")
    a = ap.parse_args()
    if a.op == "OP08" and a.mode != "materialized":
        ap.error("OP08 is materialized only")
    files = chunk_files(a.input, a.rows)
    gc.disable()
    pc = time.perf_counter
    load_ms = compute_ms = 0.0
    if a.op == "OP15":
        t0 = pc()
        rows, floats = run_op15(files)
        compute_ms = (pc() - t0) * 1000
    elif a.op in OPS:
        if a.op in ("OP06", "OP07"):
            t0 = pc()
            dims = load_dims(a.input, a.rows, a.op)
            load_ms = (pc() - t0) * 1000
            names, step, fin = OPS[a.op](dims)
        else:
            names, step, fin = OPS[a.op]()
        if a.mode == "materialized":
            acc = new_acc(names)
            t0 = pc()
            for f in files:
                load(f, names, acc)
            load_ms += (pc() - t0) * 1000
            t0 = pc()
            step(acc)
            rows, floats = fin()
            compute_ms = (pc() - t0) * 1000
        else:
            for f in files:
                acc = new_acc(names)
                t0 = pc()
                load(f, names, acc)
                t1 = pc()
                step(acc)
                t2 = pc()
                load_ms += (t1 - t0) * 1000
                compute_ms += (t2 - t1) * 1000
                del acc
            t0 = pc()
            rows, floats = fin()
            compute_ms += (pc() - t0) * 1000
    else:
        sys.stderr.write("unsupported op %s\n" % a.op)
        return 2
    cs, n = digest(rows)
    out = {"load_ms": load_ms, "compute_ms": compute_ms, "checksum": cs, "row_count": n,
           "toolchain": {"name": "cpython", "version": platform.python_version(), "flags": "-O"}}
    if floats:
        out["floats"] = floats
    try:
        import resource
        out["steady_rss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    except Exception:
        pass
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
