// Conformance probe (Scala 3, stdlib + JDK). NOT RUN in the authoring environment.
import java.math.{BigDecimal => JBD, MathContext}
import java.time.LocalDate

object Main:
  def kv(k: String, v: Any): Unit = println(s"$k=$v")
  def fmt17(x: Double): String =
    if x.isNaN then "nan"
    else if x.isInfinite then (if x > 0 then "inf" else "-inf")
    else if x == 0.0 then "0"
    else JBD(x).round(MathContext(17)).stripTrailingZeros.toPlainString
  def probe(k: String)(f: => String): Unit =
    try kv(k, f) catch case _: Throwable => kv(k, "exception")
  def strprobe(p: String, s: String): Unit =
    kv(p + "_utf8", s.getBytes("UTF-8").length)
    kv(p + "_utf16", s.length)
    kv(p + "_scalars", s.codePointCount(0, s.length))
  @volatile var zeroI = 0
  @volatile var zeroD = 0.0
  @volatile var oneD = 1.0

  def main(args: Array[String]): Unit =
    kv("lang", "scala")
    kv("version", "Scala " + scala.util.Properties.versionNumberString + " on JVM " + System.getProperty("java.version"))
    kv("size_int8", java.lang.Byte.BYTES); kv("size_int16", java.lang.Short.BYTES)
    kv("size_int32", java.lang.Integer.BYTES); kv("size_int64", java.lang.Long.BYTES)
    for n <- List("uint8", "uint16", "uint32", "uint64") do kv("size_" + n, "n/a")
    kv("size_float32", java.lang.Float.BYTES); kv("size_float64", java.lang.Double.BYTES)
    kv("size_bool", "n/a"); kv("size_char", java.lang.Character.BYTES)
    kv("char_meaning", "Char is an unsigned 16-bit UTF-16 code unit (JVM char)")
    probe("int32_max_plus_1") { var x = Int.MaxValue; x += 1; x.toString }
    probe("int64_max_plus_1") { var x = Long.MaxValue; x += 1; x.toString }
    kv("uint8_255_plus_1", "n/a")
    kv("uint32_0_minus_1", "n/a")
    probe("int_div_m7_2") { val a = -7; val b = 2; (a / b).toString }
    probe("int_mod_m7_2") { val a = -7; val b = 2; (a % b).toString }
    probe("int_div_by_zero") { (1 / zeroI).toString }
    probe("f64_0_1_plus_0_2") { val a = 0.1; val b = 0.2; fmt17(a + b) }
    probe("f32_16777217_roundtrip") { val i = 16777217; fmt17(i.toFloat.toDouble) }
    probe("f64_2p53_plus_1") { val x = 9007199254740992.0; fmt17(x + 1.0) }
    probe("f64_nan_eq_nan") { val n = Double.NaN; (n == n).toString }
    probe("f64_1_div_0") { fmt17(oneD / zeroD) }
    probe("f64_neg1_div_0") { fmt17(-oneD / zeroD) }
    probe("f64_0_div_0") { fmt17(zeroD / zeroD) }
    probe("i64_2p53p1_via_f64") { val i = 9007199254740993L; i.toDouble.toLong.toString }
    strprobe("str_e_pre", "é")
    strprobe("str_e_comb", "é")
    strprobe("str_emoji", "😀")
    probe("date_epoch_day_2015_01_01") { LocalDate.of(2015, 1, 1).toEpochDay.toString }
    kv("timestamp_max_precision", "ns")
    probe("empty_array_index0") { val a = new Array[Int](0); a(0).toString }
    probe("empty_array_max") { Array.empty[Int].maxOption.map(_.toString).getOrElse("none") }
    probe("empty_string_index0") { "".charAt(0).toInt.toString }
    probe("empty_string_split_count") { "".split(",", -1).length.toString }
    probe("map_order_3_1_2") {
      val m = scala.collection.immutable.HashMap(3 -> 0, 1 -> 0, 2 -> 0)
      m.keys.mkString(",")
    }
    probe("decimal_0_1_plus_0_2") { (BigDecimal("0.1") + BigDecimal("0.2")).toString }
    probe("f64_sum_10m_0_1") { var s = 0.0; val a = 0.1; var i = 0; while i < 10000000 do { s += a; i += 1 }; fmt17(s) }
