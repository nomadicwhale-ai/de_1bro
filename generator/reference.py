"""Canonical pure-Python reference implementation (slow, obviously correct).

Row functions return plain tuples in *canonical* representation:
decimal money -> int64 cents, date -> int days since 1970-01-01,
timestamp -> int64 microseconds since epoch (UTC), None for null.
"""
from __future__ import annotations

from . import spec as S
from .spec import GOLDEN, INV53, MASK64, C1, C2


def mix64(z: int) -> int:
    z &= MASK64
    z ^= z >> 30
    z = (z * C1) & MASK64
    z ^= z >> 27
    z = (z * C2) & MASK64
    z ^= z >> 31
    return z


def stream_key(seed: int, table_id: int, col: int) -> int:
    return mix64((seed ^ (((table_id << 16) | col) * GOLDEN)) & MASK64)


def rand(key: int, i: int) -> int:
    return mix64((key + i * GOLDEN) & MASK64)


def u01(x: int) -> float:
    return (x >> 11) * INV53


class Ref:
    """Holds stream keys for one (seed, table)."""

    def __init__(self, seed: int, table: str, ncols: int = 20):
        tid = S.TABLE_IDS[table]
        self.k = [stream_key(seed, tid, c) for c in range(ncols)]

    def r(self, col: int, i: int) -> int:
        return rand(self.k[col], i)

    def u(self, col: int, i: int) -> float:
        return u01(rand(self.k[col], i))


def _skew_index(u: float, n: int, power: int) -> int:
    v = u * u if power == 2 else u * u * u
    idx = int(float(n) * v)
    return idx if idx < n else n - 1


# ---------------------------------------------------------------- sales_fact
SALES_COLS = [
    "transaction_id", "customer_id", "product_id", "store_id", "quantity",
    "unit_price_cents", "discount", "tax", "country", "category",
    "transaction_date", "transaction_timestamp", "is_returned",
]


class SalesRef(Ref):
    def __init__(self, seed: int, scale: S.Scale):
        super().__init__(seed, "sales_fact")
        self.m = scale.customers
        self.p = scale.products

    def row(self, i: int) -> tuple:
        r, u = self.r, self.u
        customer_id = 1 + _skew_index(u(0, i), self.m, 3)
        product_id = 1 + r(1, i) % self.p
        store_id = 1 + r(2, i) % S.N_STORES
        base_qty = 1 + r(3, i) % 20
        price_cents = 99 + int(u(4, i) * u(5, i) * u(6, i) * 999900.0)
        dpct = 0 if r(7, i) % 100 < 30 else r(8, i) % 51
        discount = dpct / 100.0
        cidx = _skew_index(u(9, i), 40, 2)
        tax = float(price_cents * base_qty * S.COUNTRY_RATE_BP[cidx]) / 1000000.0
        gidx = _skew_index(u(10, i), S.N_CATEGORIES, 2)
        date = S.SALES_DATE0 + r(11, i) % S.SALES_DATE_SPAN
        ts = date * S.US_PER_DAY + (r(12, i) % 86400) * 1_000_000 + r(13, i) % 1_000_000
        returned = r(14, i) % 100 < 5
        quantity = None if r(15, i) % 1000 == 0 else base_qty
        country_i = None if r(16, i) % 10000 == 0 else cidx
        category_i = gidx
        if i % S.EDGE_EVERY == S.EDGE_EVERY - 1:
            pat = (i // S.EDGE_EVERY) % 8
            if pat == 0:
                quantity = S.INT32_MAX
            elif pat == 1:
                quantity = S.INT32_MIN
            elif pat == 2:
                country_i = 40
            elif pat == 3:
                country_i = 41
            elif pat == 4:
                category_i = 200
            elif pat == 5:
                category_i = 201
            elif pat == 6:
                ts = date * S.US_PER_DAY + S.US_PER_DAY - 1
            else:
                ts = date * S.US_PER_DAY
        country = None if country_i is None else S.COUNTRY_VOCAB[country_i]
        return (i + 1, customer_id, product_id, store_id, quantity, price_cents,
                discount, tax, country, S.CATEGORY_VOCAB[category_i], date, ts, returned)


# ------------------------------------------------------------- dim_customer
CUSTOMER_COLS = ["customer_id", "name", "email", "signup_date", "segment", "country",
                 "lifetime_value_cents"]


class CustomerRef(Ref):
    def __init__(self, seed: int, scale: S.Scale):
        super().__init__(seed, "dim_customer")

    def row(self, i: int) -> tuple:
        cid = i + 1
        return (cid, f"Customer {cid}", f"user{cid}@example.com",
                S.CUSTOMER_DATE0 + self.r(0, i) % S.CUSTOMER_DATE_SPAN,
                S.SEGMENTS[self.r(1, i) % 6],
                S.COUNTRIES[_skew_index(self.u(2, i), 40, 2)],
                self.r(3, i) % 100_000_000)


# -------------------------------------------------------------- dim_product
PRODUCT_COLS = ["product_id", "category", "brand", "weight_grams", "tags", "attributes"]


class ProductRef(Ref):
    def __init__(self, seed: int, scale: S.Scale):
        super().__init__(seed, "dim_product")

    def row(self, i: int) -> tuple:
        r = self.r
        weight = None if r(2, i) % 10 == 0 else 10 + r(3, i) % 50000
        ntags = 1 + r(4, i) % 4
        tags = [S.TAGS[rand(self.k[5], i * 4 + j) % 32] for j in range(ntags)]
        attrs = [("color", S.COLORS[r(6, i) % 8]), ("size", S.SIZES[r(7, i) % 5])]
        return (i + 1, S.CATEGORIES[_skew_index(self.u(0, i), 200, 2)],
                f"brand_{r(1, i) % 500:03d}", weight, tags, attrs)


# --------------------------------------------------------------- events_log
EVENT_COLS = ["event_id", "ts", "user_id", "event_type", "payload_json", "session_id",
              "ip", "bytes"]


class EventsRef(Ref):
    def __init__(self, seed: int, scale: S.Scale):
        super().__init__(seed, "events_log", 16)
        self.users = scale.users

    def row(self, i: int) -> tuple:
        r, u = self.r, self.u
        event_id = 1 + r(1, i) % i if (i > 0 and r(0, i) % 100 == 0) else i + 1
        ts = S.EVENTS_BASE_US + i * 1000 + (r(2, i) % 60_000_000) - 30_000_000
        user_id = 1 + r(3, i) % self.users
        etype = S.EVENT_TYPES[r(4, i) % 8]
        amount = r(5, i) % 100000
        pad = S.PADS[r(6, i) % 451]
        payload = f'{{"user":{{"id":{user_id}}},"action":"{etype}","amount":{amount},"note":"{pad}"}}'
        h = f"{r(7, i):016x}{r(8, i):016x}"
        session = f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
        x = r(9, i)
        ip = f"{(x >> 24) & 255}.{(x >> 16) & 255}.{(x >> 8) & 255}.{x & 255}"
        nbytes = 1 + int(u(10, i) * u(11, i) * u(12, i) * u(13, i) * 1000000000.0)
        return (event_id, ts, user_id, etype, payload, session, ip, nbytes)


# ------------------------------------------------------------- wide_numeric
WIDE_COLS = (["id"] + [f"f{c:03d}" for c in range(S.WIDE_FLOATS)]
             + [f"i{c:02d}" for c in range(S.WIDE_INTS)])


class WideRef(Ref):
    def __init__(self, seed: int, scale: S.Scale):
        super().__init__(seed, "wide_numeric", S.WIDE_FLOATS + S.WIDE_INTS)

    def row(self, i: int) -> tuple:
        fl = tuple(u01(rand(self.k[c], i)) for c in range(S.WIDE_FLOATS))
        it = tuple(rand(self.k[S.WIDE_FLOATS + c], i) % S.WIDE_INT_MOD
                   for c in range(S.WIDE_INTS))
        return (i + 1,) + fl + it


REFS = {
    "sales_fact": (SalesRef, SALES_COLS),
    "dim_customer": (CustomerRef, CUSTOMER_COLS),
    "dim_product": (ProductRef, PRODUCT_COLS),
    "events_log": (EventsRef, EVENT_COLS),
    "wide_numeric": (WideRef, WIDE_COLS),
}


def make_ref(table: str, seed: int, scale: S.Scale):
    cls, cols = REFS[table]
    return cls(seed, scale), cols
