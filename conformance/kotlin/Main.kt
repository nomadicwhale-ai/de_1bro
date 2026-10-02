// Conformance probe (Kotlin/JVM, stdlib + JDK). NOT RUN in the authoring environment.
import java.math.BigDecimal
import java.math.MathContext
import java.time.LocalDate

fun kv(k: String, v: Any) = println("$k=$v")
fun fmt17(x: Double): String {
    if (x.isNaN()) return "nan"
    if (x.isInfinite()) return if (x > 0) "inf" else "-inf"
    if (x == 0.0) return "0"
    return BigDecimal(x).round(MathContext(17)).stripTrailingZeros().toPlainString()
}
fun probe(k: String, f: () -> String) = try { kv(k, f()) } catch (e: Throwable) { kv(k, "exception") }
fun strprobe(p: String, s: String) {
    kv(p + "_utf8", s.toByteArray(Charsets.UTF_8).size)
    kv(p + "_utf16", s.length)
    kv(p + "_scalars", s.codePointCount(0, s.length))
}
@Volatile var zeroI = 0
@Volatile var zeroD = 0.0
@Volatile var oneD = 1.0

fun main() {
    kv("lang", "kotlin")
    kv("version", "Kotlin " + KotlinVersion.CURRENT + " on JVM " + System.getProperty("java.version"))
    kv("size_int8", Byte.SIZE_BYTES); kv("size_int16", Short.SIZE_BYTES)
    kv("size_int32", Int.SIZE_BYTES); kv("size_int64", Long.SIZE_BYTES)
    kv("size_uint8", UByte.SIZE_BYTES); kv("size_uint16", UShort.SIZE_BYTES)
    kv("size_uint32", UInt.SIZE_BYTES); kv("size_uint64", ULong.SIZE_BYTES)
    kv("size_float32", Float.SIZE_BYTES); kv("size_float64", Double.SIZE_BYTES)
    kv("size_bool", "n/a"); kv("size_char", Char.SIZE_BYTES)
    kv("char_meaning", "Char is a 16-bit UTF-16 code unit (same as Java char)")
    probe("int32_max_plus_1") { var x = Int.MAX_VALUE; x++; x.toString() }
    probe("int64_max_plus_1") { var x = Long.MAX_VALUE; x++; x.toString() }
    probe("uint8_255_plus_1") { var x: UByte = 255u; x++; x.toString() }
    probe("uint32_0_minus_1") { var x: UInt = 0u; x--; x.toString() }
    probe("int_div_m7_2") { val a = -7; val b = 2; (a / b).toString() }
    probe("int_mod_m7_2") { val a = -7; val b = 2; (a % b).toString() }
    probe("int_div_by_zero") { (1 / zeroI).toString() }
    probe("f64_0_1_plus_0_2") { val a = 0.1; val b = 0.2; fmt17(a + b) }
    probe("f32_16777217_roundtrip") { val i = 16777217; fmt17(i.toFloat().toDouble()) }
    probe("f64_2p53_plus_1") { val x = 9007199254740992.0; fmt17(x + 1.0) }
    probe("f64_nan_eq_nan") { val n = Double.NaN; (n == n).toString() }
    probe("f64_1_div_0") { fmt17(oneD / zeroD) }
    probe("f64_neg1_div_0") { fmt17(-oneD / zeroD) }
    probe("f64_0_div_0") { fmt17(zeroD / zeroD) }
    probe("i64_2p53p1_via_f64") { val i = 9007199254740993L; i.toDouble().toLong().toString() }
    strprobe("str_e_pre", "é")
    strprobe("str_e_comb", "é")
    strprobe("str_emoji", "😀")
    probe("date_epoch_day_2015_01_01") { LocalDate.of(2015, 1, 1).toEpochDay().toString() }
    kv("timestamp_max_precision", "ns")  // java.time.Instant
    probe("empty_array_index0") { val a = IntArray(0); a[0].toString() }
    probe("empty_array_max") { IntArray(0).maxOrNull()?.toString() ?: "none" }
    probe("empty_string_index0") { "".get(0).code.toString() }
    probe("empty_string_split_count") { "".split(",").size.toString() }
    probe("map_order_3_1_2") { val m = HashMap<Int, Int>(); m[3] = 0; m[1] = 0; m[2] = 0; m.keys.joinToString(",") }
    probe("decimal_0_1_plus_0_2") { BigDecimal("0.1").add(BigDecimal("0.2")).toPlainString() }
    probe("f64_sum_10m_0_1") { var s = 0.0; val a = 0.1; for (i in 0 until 10_000_000) s += a; fmt17(s) }
}
