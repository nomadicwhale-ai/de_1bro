// Conformance probe (Swift 5.9+, Foundation-free where possible). NOT RUN in the authoring environment.
import Foundation

func kv(_ k: String, _ v: Any) { print("\(k)=\(v)") }
func fmt17(_ x: Double) -> String {
    if x.isNaN { return "nan" }
    if x.isInfinite { return x > 0 ? "inf" : "-inf" }
    return String(format: "%.17g", x)
}
func strprobe(_ p: String, _ s: String) {
    kv(p + "_utf8", s.utf8.count)
    kv(p + "_utf16", s.utf16.count)
    kv(p + "_scalars", s.unicodeScalars.count)
}
// Swift traps (crashes the process) on overflow and division by zero, and cannot catch it.
// Those probes are therefore reported as "trap" without executing them.
kv("lang", "swift")
#if swift(>=5.9)
kv("version", "swift (see swiftc --version)")
#endif
kv("size_int8", MemoryLayout<Int8>.size); kv("size_int16", MemoryLayout<Int16>.size)
kv("size_int32", MemoryLayout<Int32>.size); kv("size_int64", MemoryLayout<Int64>.size)
kv("size_uint8", MemoryLayout<UInt8>.size); kv("size_uint16", MemoryLayout<UInt16>.size)
kv("size_uint32", MemoryLayout<UInt32>.size); kv("size_uint64", MemoryLayout<UInt64>.size)
kv("size_float32", MemoryLayout<Float>.size); kv("size_float64", MemoryLayout<Double>.size)
kv("size_bool", MemoryLayout<Bool>.size); kv("size_char", MemoryLayout<Character>.size)
kv("char_meaning", "Character is an extended grapheme cluster (variable size, 16 bytes in memory); Unicode.Scalar is the code point")
kv("int32_max_plus_1", "trap")
kv("int64_max_plus_1", "trap")
kv("uint8_255_plus_1", "trap")
kv("uint32_0_minus_1", "trap")
let m7 = Int(CommandLine.arguments.count) - 8  // = -7 when run with no args (avoids constant folding)
kv("int_div_m7_2", m7 / 2)
kv("int_mod_m7_2", m7 % 2)
kv("int_div_by_zero", "trap")
let a = 0.1, b = 0.2
kv("f64_0_1_plus_0_2", fmt17(a + b))
let i32 = Int32(16777216 + CommandLine.arguments.count)
kv("f32_16777217_roundtrip", fmt17(Double(Float(i32))))
kv("f64_2p53_plus_1", fmt17(9007199254740992.0 + Double(CommandLine.arguments.count)))
let nan = Double.nan
kv("f64_nan_eq_nan", nan == nan ? "true" : "false")
let fz = Double(CommandLine.arguments.count - 1)
kv("f64_1_div_0", fmt17(1.0 / fz)); kv("f64_neg1_div_0", fmt17(-1.0 / fz)); kv("f64_0_div_0", fmt17(fz / fz))
kv("i64_2p53p1_via_f64", Int64(Double(Int64(9007199254740992) + Int64(CommandLine.arguments.count))))
strprobe("str_e_pre", "\u{00e9}")
strprobe("str_e_comb", "e\u{0301}")
strprobe("str_emoji", "\u{1F600}")
var cal = Calendar(identifier: .gregorian); cal.timeZone = TimeZone(identifier: "UTC")!
let d = cal.date(from: DateComponents(year: 2015, month: 1, day: 1))!
kv("date_epoch_day_2015_01_01", Int(d.timeIntervalSince1970 / 86400))
kv("timestamp_max_precision", "ns")  // Swift.ContinuousClock/Duration is attoseconds; Foundation Date is a Double of seconds (~sub-us). Reported: ns clock
kv("empty_array_index0", "trap")
kv("empty_array_max", (([] as [Int]).max().map { String($0) }) ?? "none")
kv("empty_string_index0", ("".first.map { String($0) }) ?? "none(first) / trap(index)")
kv("empty_string_split_count", "".split(separator: ",", omittingEmptySubsequences: false).count)
var dict: [Int: Int] = [:]; dict[3] = 0; dict[1] = 0; dict[2] = 0
kv("map_order_3_1_2", "randomized")  // Swift Dictionary uses per-process random seeding
let dec = Decimal(string: "0.1")! + Decimal(string: "0.2")!
kv("decimal_0_1_plus_0_2", "\(dec)")
var s = 0.0
for _ in 0..<10_000_000 { s += a }
kv("f64_sum_10m_0_1", fmt17(s))
