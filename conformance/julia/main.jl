# Conformance probe (Julia, stdlib only). NOT RUN in the authoring environment.
using Printf, Dates
kv(k, v) = println(k, "=", v)
function probe(k, f)
    try
        kv(k, f())
    catch
        kv(k, "exception")
    end
end
function fmt17(x::Real)
    isnan(x) && return "nan"
    isinf(x) && return x > 0 ? "inf" : "-inf"
    return Printf.format(Printf.Format("%.17g"), Float64(x))
end
function strprobe(p, s)
    kv(p * "_utf8", sizeof(s))
    kv(p * "_utf16", length(transcode(UInt16, s)))
    kv(p * "_scalars", length(s))
end
const ZERO = Ref(0); const FZ = Ref(0.0)
kv("lang", "julia")
kv("version", "julia " * string(VERSION))
for (n, T) in (("int8", Int8), ("int16", Int16), ("int32", Int32), ("int64", Int64),
               ("uint8", UInt8), ("uint16", UInt16), ("uint32", UInt32), ("uint64", UInt64),
               ("float32", Float32), ("float64", Float64), ("bool", Bool), ("char", Char))
    kv("size_" * n, sizeof(T))
end
kv("char_meaning", "Char is a 32-bit Unicode code point (scalar value), distinct from UInt8 bytes")
probe("int32_max_plus_1", () -> string(typemax(Int32) + Int32(1)))
probe("int64_max_plus_1", () -> string(typemax(Int64) + Int64(1)))
probe("uint8_255_plus_1", () -> string(UInt8(255) + UInt8(1)))
probe("uint32_0_minus_1", () -> string(UInt32(0) - UInt32(1)))
probe("int_div_m7_2", () -> string(div(-7, 2)))
probe("int_mod_m7_2", () -> string(rem(-7, 2)))
probe("int_div_by_zero", () -> string(div(1, ZERO[])))
probe("f64_0_1_plus_0_2", () -> fmt17(0.1 + 0.2))
probe("f32_16777217_roundtrip", () -> fmt17(Float64(Float32(16777217))))
probe("f64_2p53_plus_1", () -> fmt17(9007199254740992.0 + 1.0))
probe("f64_nan_eq_nan", () -> string(NaN == NaN))
probe("f64_1_div_0", () -> fmt17(1.0 / FZ[]))
probe("f64_neg1_div_0", () -> fmt17(-1.0 / FZ[]))
probe("f64_0_div_0", () -> fmt17(FZ[] / FZ[]))
probe("i64_2p53p1_via_f64", () -> string(unsafe_trunc(Int64, Float64(9007199254740993))))
strprobe("str_e_pre", "é")
strprobe("str_e_comb", "é")
strprobe("str_emoji", "\U0001F600")
probe("date_epoch_day_2015_01_01", () -> string(Dates.value(Date(2015, 1, 1)) - Dates.value(Date(1970, 1, 1))))
kv("timestamp_max_precision", "ms")  # Dates.DateTime has millisecond resolution
probe("empty_array_index0", () -> string(Int[][1]))
probe("empty_array_max", () -> string(maximum(Int[])))
probe("empty_string_index0", () -> string(""[1]))
probe("empty_string_split_count", () -> string(length(split("", ","))))
probe("map_order_3_1_2", () -> begin
    d = Dict{Int,Int}(); d[3] = 0; d[1] = 0; d[2] = 0
    join(keys(d), ",")
end)
kv("decimal_0_1_plus_0_2", "n/a")  # Base has Rational/BigFloat only; no decimal type
probe("f64_sum_10m_0_1", () -> begin
    s = 0.0; a = 0.1
    for _ in 1:10_000_000; s += a; end
    fmt17(s)
end)
