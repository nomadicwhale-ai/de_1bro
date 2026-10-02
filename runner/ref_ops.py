"""Pure-Python reference semantics of the Phase 2 operations, computed directly from generator
rows (canonical tuples, see generator.reference.SALES_COLS). Independent of DuckDB: used to
cross-check the oracle and as readable pseudo-code for implementers.
"""
from __future__ import annotations

import math
from collections import defaultdict

from generator.resultdigest import ResultDigest

(TID, CID, PID, STORE, QTY, CENTS, DISC, TAX, COUNTRY, CATEGORY, DATE, TS, RET) = range(13)
MASK = (1 << 64) - 1


def civil_from_days(z: int) -> tuple[int, int, int]:
    """Howard Hinnant's algorithm: days since 1970-01-01 -> (year, month, day)."""
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    return (y + (m <= 2), m, d)


def _digest(rows) -> tuple[str, int]:
    d = ResultDigest()
    for r in rows:
        d.add(r)
    return d.checksum, d.count


def _sum_or_none(total, seen):
    return total if seen else None


def op01(rows):
    n = nq = sq = sp = cr = 0
    mn, mx = None, None
    for r in rows:
        n += 1
        if r[QTY] is not None:
            nq += 1
            sq += r[QTY]
        sp += r[CENTS]
        mn = r[CENTS] if mn is None or r[CENTS] < mn else mn
        mx = r[CENTS] if mx is None or r[CENTS] > mx else mx
        cr += r[RET]
    return _digest([(n, nq, sq if nq else None, sp, mn, mx, cr)]), {}


def _group(rows, keyf):
    g = defaultdict(lambda: [0, 0, False, 0])  # count, sum_qty, seen_qty, sum_cents
    for r in rows:
        a = g[keyf(r)]
        a[0] += 1
        if r[QTY] is not None:
            a[1] += r[QTY]
            a[2] = True
        a[3] += r[CENTS]
    return g


def op03(rows):
    g = _group(rows, lambda r: r[COUNTRY])
    return _digest([(k, a[0], a[1] if a[2] else None, a[3]) for k, a in g.items()]), {}


def op04(rows):
    g = _group(rows, lambda r: r[CID])
    return _digest([(k, a[0], a[3]) for k, a in g.items()]), {}


def op05(rows):
    g = _group(rows, lambda r: (r[COUNTRY], r[CATEGORY], civil_from_days(r[DATE])[0]))
    return _digest([(k[0], k[1], k[2], a[0], a[3]) for k, a in g.items()]), {}


def op10(rows):
    c, p, sd = set(), set(), set()
    for r in rows:
        c.add(r[CID]); p.add(r[PID]); sd.add((r[STORE], r[DATE]))
    return _digest([(len(c), len(p), len(sd))]), {}


def op15(rows):
    s = dict(tid=0, cid=0, pid=0, store=0, qty=0, nq=0, cents=0, disc=0, tax=0, cb=0, nc=0, gb=0,
             days=0, sec=0, frac=0, ret=0)
    n = 0
    for r in rows:
        n += 1
        s["tid"] += r[TID]; s["cid"] += r[CID]; s["pid"] += r[PID]; s["store"] += r[STORE]
        if r[QTY] is None:
            s["nq"] += 1
        else:
            s["qty"] += r[QTY]
        s["cents"] += r[CENTS]
        s["disc"] += math.floor(r[DISC] * 1e6 + 0.5)
        s["tax"] += math.floor(r[TAX] * 1e6 + 0.5)
        if r[COUNTRY] is None:
            s["nc"] += 1
        else:
            s["cb"] += len(r[COUNTRY].encode())
        s["gb"] += len(r[CATEGORY].encode())
        s["days"] += r[DATE]
        s["sec"] += r[TS] // 1_000_000
        s["frac"] += r[TS] % 1_000_000
        s["ret"] += r[RET]
    return _digest([(n, s["tid"], s["cid"], s["pid"], s["store"], s["qty"], s["nq"], s["cents"],
                     s["disc"], s["tax"], s["cb"], s["nc"], s["gb"], s["days"], s["sec"], s["frac"],
                     s["ret"])]), {}


def op19(rows):
    nq = nc = sq = ne = 0
    distinct = set()
    for r in rows:
        nq += r[QTY] is None
        nc += r[COUNTRY] is None
        sq += 1 if r[QTY] is None else r[QTY]
        if r[COUNTRY] is not None:
            distinct.add(r[COUNTRY])
            ne += r[COUNTRY] != ""
    return _digest([(nq, nc, sq, ne, len(distinct))]), {}


def op21(rows):
    exact, naive, ksum, comp = 0, 0.0, 0.0, 0.0
    for r in rows:
        exact += r[CENTS]
        v = r[CENTS] / 100.0
        naive += v
        y = v - comp
        t = ksum + y
        comp = (t - ksum) - y
        ksum = t
    text = f"{exact // 100}.{exact % 100:02d}"
    return _digest([(exact, text)]), {"naive_sum": naive, "kahan_sum": ksum}


def op22(rows):
    a = b = c = ymd = 0
    for r in rows:
        k = r[TID] * 4294967311 + r[CID]
        a += int(float(k)) != k
        f = r[CENTS] / 100.0
        b += int(f * 100.0) != r[CENTS]
        c += (r[TS] // 1000) * 1000 != r[TS]
        y, m, d = civil_from_days(r[DATE])
        ymd += y * 10000 + m * 100 + d
    return _digest([(a, b, c, ymd)]), {}


REF = {"OP01": op01, "OP03": op03, "OP04": op04, "OP05": op05, "OP10": op10, "OP15": op15,
       "OP19": op19, "OP21": op21, "OP22": op22}
