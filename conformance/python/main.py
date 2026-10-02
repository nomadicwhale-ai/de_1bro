"""Conformance probe (Python 3, standard library only)."""
import datetime
import decimal
import platform
import struct

out = []


def kv(k, v):
    out.append(f"{k}={v}")


def probe(k, f):
    try:
        kv(k, f())
    except Exception:
        kv(k, "exception")


def fmt17(x):
    if x != x:
        return "nan"
    if x == float("inf"):
        return "inf"
    if x == float("-inf"):
        return "-inf"
    return "%.17g" % x


def strprobe(p, s):
    kv(p + "_utf8", len(s.encode("utf-8")))
    kv(p + "_utf16", len(s.encode("utf-16-le")) // 2)
    kv(p + "_scalars", len(s))


kv("lang", "python")
kv("version", "CPython " + platform.python_version())
for n in ("int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64"):
    kv("size_" + n, "n/a")  # int is arbitrary precision; no fixed-width scalar types
kv("size_float32", "n/a")
kv("size_float64", struct.calcsize("d"))  # float is a C double
kv("size_bool", "n/a")
kv("size_char", "n/a")
kv("char_meaning", "no char type; a character is a str of length 1 (one Unicode code point)")
probe("int32_max_plus_1", lambda: str(2147483647 + 1))
probe("int64_max_plus_1", lambda: str(9223372036854775807 + 1))
probe("uint8_255_plus_1", lambda: str(255 + 1))
probe("uint32_0_minus_1", lambda: str(0 - 1))
probe("int_div_m7_2", lambda: str(-7 // 2))
probe("int_mod_m7_2", lambda: str(-7 % 2))
zero = 0
probe("int_div_by_zero", lambda: str(1 // zero))
a, b = 0.1, 0.2
probe("f64_0_1_plus_0_2", lambda: fmt17(a + b))
probe("f32_16777217_roundtrip", lambda: fmt17(struct.unpack("f", struct.pack("f", 16777217.0))[0]))
probe("f64_2p53_plus_1", lambda: fmt17(9007199254740992.0 + 1.0))
probe("f64_nan_eq_nan", lambda: str(float("nan") == float("nan")).lower())
fz, fo = 0.0, 1.0
probe("f64_1_div_0", lambda: fmt17(fo / fz))
probe("f64_neg1_div_0", lambda: fmt17(-fo / fz))
probe("f64_0_div_0", lambda: fmt17(fz / fz))
probe("i64_2p53p1_via_f64", lambda: str(int(float(9007199254740993))))
strprobe("str_e_pre", "é")
strprobe("str_e_comb", "é")
strprobe("str_emoji", "\U0001F600")
probe("date_epoch_day_2015_01_01", lambda: str((datetime.date(2015, 1, 1) - datetime.date(1970, 1, 1)).days))
kv("timestamp_max_precision", "us")
probe("empty_array_index0", lambda: str([][0]))
probe("empty_array_max", lambda: str(max([])))
probe("empty_string_index0", lambda: str(""[0]))
probe("empty_string_split_count", lambda: str(len("".split(","))))


def mapord():
    m = {}
    m[3] = 0
    m[1] = 0
    m[2] = 0
    return ",".join(str(k) for k in m)


probe("map_order_3_1_2", mapord)
probe("decimal_0_1_plus_0_2", lambda: str(decimal.Decimal("0.1") + decimal.Decimal("0.2")))


def total():
    s = 0.0
    for _ in range(10_000_000):
        s += 0.1
    return fmt17(s)


probe("f64_sum_10m_0_1", total)
print("\n".join(out))
