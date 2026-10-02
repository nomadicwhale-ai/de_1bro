"""Vectorised (numpy + pyarrow) generator. Must be bit-identical to reference.py.

gen_chunk() returns a pyarrow Table in *canonical* form: money as int64 cents
(`unit_price_cents`, `lifetime_value_cents`), dates as date32, timestamps as
timestamp[us] (UTC). to_output() converts to the published file schema.
"""
from __future__ import annotations

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from . import spec as S
from .reference import stream_key

_U = np.uint64
_GOLDEN, _C1, _C2 = _U(S.GOLDEN), _U(S.C1), _U(S.C2)
_S30, _S27, _S31, _S11 = _U(30), _U(27), _U(31), _U(11)

_VOCAB = {
    "country": pa.array(S.COUNTRY_VOCAB, pa.string()),
    "category": pa.array(S.CATEGORY_VOCAB, pa.string()),
    "countries": pa.array(S.COUNTRIES, pa.string()),
    "categories": pa.array(S.CATEGORIES, pa.string()),
    "segments": pa.array(S.SEGMENTS, pa.string()),
    "events": pa.array(S.EVENT_TYPES, pa.string()),
    "tags": pa.array(S.TAGS, pa.string()),
    "colors": pa.array(S.COLORS, pa.string()),
    "sizes": pa.array(S.SIZES, pa.string()),
    "pads": pa.array(S.PADS, pa.string()),
}
_RATE_BP = np.array(S.COUNTRY_RATE_BP, dtype=np.int64)
_HEX = np.frombuffer(b"0123456789abcdef", dtype=np.uint8)


def _keys(seed: int, table: str, ncols: int) -> list[int]:
    tid = S.TABLE_IDS[table]
    return [stream_key(seed, tid, c) for c in range(ncols)]


def _draw(key: int, idx: np.ndarray) -> np.ndarray:
    with np.errstate(over="ignore"):
        z = idx * _GOLDEN + _U(key)
        z ^= z >> _S30
        z *= _C1
        z ^= z >> _S27
        z *= _C2
        z ^= z >> _S31
    return z


def _u01(x: np.ndarray) -> np.ndarray:
    return (x >> _S11).astype(np.float64) * S.INV53


def _mod(x: np.ndarray, n: int) -> np.ndarray:
    return (x % _U(n)).astype(np.int64)


def _skew(u: np.ndarray, n: int, power: int) -> np.ndarray:
    v = u * u if power == 2 else u * u * u
    idx = np.floor(float(n) * v).astype(np.int64)
    return np.minimum(idx, n - 1)


def _take(vocab: str, idx: np.ndarray, valid: np.ndarray | None = None) -> pa.Array:
    mask = None if valid is None else ~valid
    return _VOCAB[vocab].take(pa.array(idx, type=pa.int64(), mask=mask))


def _str(a: np.ndarray) -> pa.Array:
    return pc.cast(pa.array(a), pa.string())


def _join(*parts, sep: str = "") -> pa.Array:
    return pc.binary_join_element_wise(*parts, sep)


# ---------------------------------------------------------------- sales_fact
def _sales(start: int, n: int, scale: S.Scale, seed: int) -> pa.Table:
    K = _keys(seed, "sales_fact", 20)
    i = np.arange(start, start + n, dtype=np.uint64)
    ii = i.astype(np.int64)
    d = lambda c: _draw(K[c], i)  # noqa: E731
    u = lambda c: _u01(d(c))  # noqa: E731

    customer_id = 1 + _skew(u(0), scale.customers, 3)
    product_id = 1 + _mod(d(1), scale.products)
    store_id = 1 + _mod(d(2), S.N_STORES)
    base_qty = 1 + _mod(d(3), 20)
    price = 99 + np.floor(u(4) * u(5) * u(6) * 999900.0).astype(np.int64)
    dpct = np.where(d(7) % _U(100) < _U(30), 0, _mod(d(8), 51))
    discount = dpct.astype(np.float64) / 100.0
    cidx = _skew(u(9), 40, 2)
    tax = (price * base_qty * _RATE_BP[cidx]).astype(np.float64) / 1000000.0
    gidx = _skew(u(10), S.N_CATEGORIES, 2)
    date = S.SALES_DATE0 + _mod(d(11), S.SALES_DATE_SPAN)
    ts = date * S.US_PER_DAY + _mod(d(12), 86400) * 1_000_000 + _mod(d(13), 1_000_000)
    returned = d(14) % _U(100) < _U(5)
    qty_valid = ~(d(15) % _U(1000) == _U(0))
    cty_valid = ~(d(16) % _U(10000) == _U(0))

    edge = ii % S.EDGE_EVERY == S.EDGE_EVERY - 1
    pat = (ii // S.EDGE_EVERY) % 8
    qty = base_qty.copy()
    for p, v in ((0, S.INT32_MAX), (1, S.INT32_MIN)):
        m = edge & (pat == p)
        qty[m] = v
        qty_valid[m] = True
    for p, v in ((2, 40), (3, 41)):
        m = edge & (pat == p)
        cidx[m] = v
        cty_valid[m] = True
    gidx[edge & (pat == 4)] = 200
    gidx[edge & (pat == 5)] = 201
    m6 = edge & (pat == 6)
    ts[m6] = date[m6] * S.US_PER_DAY + S.US_PER_DAY - 1
    m7 = edge & (pat == 7)
    ts[m7] = date[m7] * S.US_PER_DAY

    return pa.table({
        "transaction_id": pa.array(ii + 1, pa.int64()),
        "customer_id": pa.array(customer_id, pa.int64()),
        "product_id": pa.array(product_id, pa.int64()),
        "store_id": pa.array(store_id.astype(np.int32), pa.int32()),
        "quantity": pa.array(qty.astype(np.int32), pa.int32(), mask=~qty_valid),
        "unit_price_cents": pa.array(price, pa.int64()),
        "discount": pa.array(discount, pa.float64()),
        "tax": pa.array(tax, pa.float64()),
        "country": _take("country", cidx, cty_valid),
        "category": _take("category", gidx),
        "transaction_date": pa.array(date.astype(np.int32), pa.date32()),
        "transaction_timestamp": pa.array(ts, pa.timestamp("us")),
        "is_returned": pa.array(returned, pa.bool_()),
    })


# ------------------------------------------------------------- dim_customer
def _customers(start: int, n: int, scale: S.Scale, seed: int) -> pa.Table:
    K = _keys(seed, "dim_customer", 20)
    i = np.arange(start, start + n, dtype=np.uint64)
    ids = i.astype(np.int64) + 1
    ids_s = _str(ids)
    return pa.table({
        "customer_id": pa.array(ids, pa.int64()),
        "name": _join(pa.scalar("Customer "), ids_s),
        "email": _join(pa.scalar("user"), ids_s, pa.scalar("@example.com")),
        "signup_date": pa.array((S.CUSTOMER_DATE0 + _mod(_draw(K[0], i), S.CUSTOMER_DATE_SPAN))
                                .astype(np.int32), pa.date32()),
        "segment": _take("segments", _mod(_draw(K[1], i), 6)),
        "country": _take("countries", _skew(_u01(_draw(K[2], i)), 40, 2)),
        "lifetime_value_cents": pa.array(_mod(_draw(K[3], i), 100_000_000), pa.int64()),
    })


# -------------------------------------------------------------- dim_product
def _products(start: int, n: int, scale: S.Scale, seed: int) -> pa.Table:
    K = _keys(seed, "dim_product", 20)
    i = np.arange(start, start + n, dtype=np.uint64)
    d = lambda c: _draw(K[c], i)  # noqa: E731
    wvalid = ~(d(2) % _U(10) == _U(0))
    weight = (10 + _mod(d(3), 50000)).astype(np.int32)
    ntags = 1 + _mod(d(4), 4)
    j = np.arange(4, dtype=np.uint64)
    tag_idx = _mod(_draw(K[5], i[:, None] * _U(4) + j[None, :]), 32)
    keep = np.arange(4)[None, :] < ntags[:, None]
    flat = tag_idx[keep]
    offs = np.zeros(n + 1, dtype=np.int32)
    np.cumsum(ntags, out=offs[1:])
    tags = pa.ListArray.from_arrays(pa.array(offs), _take("tags", flat))
    colors = _take("colors", _mod(d(6), 8))
    sizes = _take("sizes", _mod(d(7), 5))
    items = pa.concat_arrays([colors, sizes])
    order = np.empty(2 * n, dtype=np.int64)
    order[0::2] = np.arange(n)
    order[1::2] = np.arange(n) + n
    items = items.take(pa.array(order))
    keys = pa.array(["color", "size"] * n, pa.string())
    attrs = pa.MapArray.from_arrays(pa.array(np.arange(0, 2 * n + 1, 2, dtype=np.int32)),
                                    keys, items)
    brand = _join(pa.scalar("brand_"), pc.utf8_lpad(_str(_mod(d(1), 500)), 3, "0"))
    return pa.table({
        "product_id": pa.array(i.astype(np.int64) + 1, pa.int64()),
        "category": _take("categories", _skew(_u01(d(0)), S.N_CATEGORIES, 2)),
        "brand": brand,
        "weight_grams": pa.array(weight, pa.int32(), mask=~wvalid),
        "tags": tags,
        "attributes": attrs,
    })


# --------------------------------------------------------------- events_log
def _hex16(x: np.ndarray) -> np.ndarray:
    shifts = np.arange(60, -4, -4, dtype=np.uint64)
    return _HEX[((x[:, None] >> shifts[None, :]) & _U(15)).astype(np.uint8)]


def _events(start: int, n: int, scale: S.Scale, seed: int) -> pa.Table:
    K = _keys(seed, "events_log", 16)
    i = np.arange(start, start + n, dtype=np.uint64)
    ii = i.astype(np.int64)
    d = lambda c: _draw(K[c], i)  # noqa: E731
    u = lambda c: _u01(d(c))  # noqa: E731
    dup = (ii > 0) & (d(0) % _U(100) == _U(0))
    den = np.maximum(i, _U(1))
    event_id = np.where(dup, 1 + (d(1) % den).astype(np.int64), ii + 1)
    ts = S.EVENTS_BASE_US + ii * 1000 + _mod(d(2), 60_000_000) - 30_000_000
    user_id = 1 + _mod(d(3), scale.users)
    etype = _take("events", _mod(d(4), 8))
    amount = _mod(d(5), 100000)
    pad = _take("pads", _mod(d(6), 451))
    payload = _join(pa.scalar('{"user":{"id":'), _str(user_id), pa.scalar('},"action":"'),
                    etype, pa.scalar('","amount":'), _str(amount), pa.scalar(',"note":"'),
                    pad, pa.scalar('"}'))
    h = np.concatenate([_hex16(d(7)), _hex16(d(8))], axis=1)
    out = np.full((n, 36), ord("-"), dtype=np.uint8)
    out[:, 0:8], out[:, 9:13], out[:, 14:18] = h[:, 0:8], h[:, 8:12], h[:, 12:16]
    out[:, 19:23], out[:, 24:36] = h[:, 16:20], h[:, 20:32]
    session = pa.Array.from_buffers(pa.binary(36), n, [None, pa.py_buffer(out)]).cast(pa.string())
    x = d(9)
    octets = [_str(((x >> _U(s)) & _U(255)).astype(np.uint8)) for s in (24, 16, 8, 0)]
    ip = _join(*octets, sep=".")
    nbytes = 1 + np.floor(u(10) * u(11) * u(12) * u(13) * 1000000000.0).astype(np.int64)
    return pa.table({
        "event_id": pa.array(event_id, pa.int64()),
        "ts": pa.array(ts, pa.timestamp("us")),
        "user_id": pa.array(user_id, pa.int64()),
        "event_type": etype,
        "payload_json": payload,
        "session_id": session,
        "ip": ip,
        "bytes": pa.array(nbytes, pa.int64()),
    })


# ------------------------------------------------------------- wide_numeric
def _wide(start: int, n: int, scale: S.Scale, seed: int) -> pa.Table:
    K = _keys(seed, "wide_numeric", S.WIDE_FLOATS + S.WIDE_INTS)
    i = np.arange(start, start + n, dtype=np.uint64)
    cols = {"id": pa.array(i.astype(np.int64) + 1, pa.int64())}
    for c in range(S.WIDE_FLOATS):
        cols[f"f{c:03d}"] = pa.array(_u01(_draw(K[c], i)), pa.float64())
    for c in range(S.WIDE_INTS):
        cols[f"i{c:02d}"] = pa.array(_mod(_draw(K[S.WIDE_FLOATS + c], i), S.WIDE_INT_MOD),
                                     pa.int64())
    return pa.table(cols)


_GEN = {
    "sales_fact": _sales,
    "dim_customer": _customers,
    "dim_product": _products,
    "events_log": _events,
    "wide_numeric": _wide,
}


def gen_chunk(table: str, start: int, n: int, scale: S.Scale, seed: int = S.DEFAULT_SEED) -> pa.Table:
    """Rows [start, start+n) of `table` in canonical form."""
    return _GEN[table](start, n, scale, seed)


def _cents_to_decimal(col: pa.ChunkedArray | pa.Array) -> pa.Array:
    if isinstance(col, pa.ChunkedArray):
        col = col.combine_chunks()
    c = col.to_numpy(zero_copy_only=False).astype(np.int64)
    buf = np.empty((len(c), 2), dtype=np.int64)
    buf[:, 0] = c
    buf[:, 1] = c >> 63
    return pa.Array.from_buffers(pa.decimal128(18, 2), len(c), [None, pa.py_buffer(buf)])


def to_output(tbl: pa.Table, price_as: str = "decimal") -> pa.Table:
    """Canonical -> published schema (`unit_price`, `lifetime_value`)."""
    out = tbl
    for src, dst in (("unit_price_cents", "unit_price"), ("lifetime_value_cents", "lifetime_value")):
        if src in out.column_names:
            idx = out.column_names.index(src)
            if price_as == "float64" and src == "unit_price_cents":
                col = pc.divide(pc.cast(out.column(idx), pa.float64()), 100.0)
            elif price_as == "cents" and src == "unit_price_cents":
                col, dst = out.column(idx), src
            else:
                col = _cents_to_decimal(out.column(idx))
            out = out.set_column(idx, dst, col)
    return out
