// Conformance probe (Java, standard library only).
import java.math.BigDecimal;
import java.math.MathContext;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.LocalDate;
import java.util.*;
import java.util.concurrent.Callable;

public class Main {
    static void kv(String k, String v) { System.out.println(k + "=" + v); }

    static String fmt17(double x) {
        if (Double.isNaN(x)) return "nan";
        if (Double.isInfinite(x)) return x > 0 ? "inf" : "-inf";
        if (x == 0) return "0";
        return new BigDecimal(x).round(new MathContext(17)).stripTrailingZeros().toPlainString();
    }

    static void probe(String k, Callable<String> f) {
        try { kv(k, f.call()); } catch (Throwable t) { kv(k, "exception"); }
    }

    static void strprobe(String prefix, String s) {
        kv(prefix + "_utf8", String.valueOf(s.getBytes(StandardCharsets.UTF_8).length));
        kv(prefix + "_utf16", String.valueOf(s.length()));
        kv(prefix + "_scalars", String.valueOf(s.codePointCount(0, s.length())));
    }

    static volatile int zeroI = 0;
    static volatile double zeroD = 0.0, oneD = 1.0;

    public static void main(String[] args) {
        kv("lang", "java");
        kv("version", System.getProperty("java.version"));
        kv("size_int8", String.valueOf(Byte.BYTES));
        kv("size_int16", String.valueOf(Short.BYTES));
        kv("size_int32", String.valueOf(Integer.BYTES));
        kv("size_int64", String.valueOf(Long.BYTES));
        kv("size_uint8", "n/a");
        kv("size_uint16", "n/a");
        kv("size_uint32", "n/a");
        kv("size_uint64", "n/a");
        kv("size_float32", String.valueOf(Float.BYTES));
        kv("size_float64", String.valueOf(Double.BYTES));
        kv("size_bool", "n/a");
        kv("size_char", String.valueOf(Character.BYTES));
        kv("char_meaning", "char is an unsigned 16-bit UTF-16 code unit (a supplementary code point needs two chars)");
        probe("int32_max_plus_1", () -> { int x = Integer.MAX_VALUE; x++; return String.valueOf(x); });
        probe("int64_max_plus_1", () -> { long x = Long.MAX_VALUE; x++; return String.valueOf(x); });
        kv("uint8_255_plus_1", "n/a");
        kv("uint32_0_minus_1", "n/a");
        probe("int_div_m7_2", () -> { int a = -7, b = 2; return String.valueOf(a / b); });
        probe("int_mod_m7_2", () -> { int a = -7, b = 2; return String.valueOf(a % b); });
        probe("int_div_by_zero", () -> String.valueOf(1 / zeroI));
        probe("f64_0_1_plus_0_2", () -> { double a = 0.1, b = 0.2; return fmt17(a + b); });
        probe("f32_16777217_roundtrip", () -> { int i = 16777217; return fmt17((double) (float) i); });
        probe("f64_2p53_plus_1", () -> { double x = 9007199254740992.0; return fmt17(x + 1.0); });
        probe("f64_nan_eq_nan", () -> { double n = Double.NaN; return String.valueOf(n == n); });
        probe("f64_1_div_0", () -> fmt17(oneD / zeroD));
        probe("f64_neg1_div_0", () -> fmt17(-oneD / zeroD));
        probe("f64_0_div_0", () -> fmt17(zeroD / zeroD));
        probe("i64_2p53p1_via_f64", () -> { long i = 9007199254740993L; return String.valueOf((long) (double) i); });
        strprobe("str_e_pre", "é");
        strprobe("str_e_comb", "é");
        strprobe("str_emoji", "😀");
        probe("date_epoch_day_2015_01_01", () -> String.valueOf(LocalDate.of(2015, 1, 1).toEpochDay()));
        probe("timestamp_max_precision", () -> { Instant.now(); return "ns"; }); // java.time.Instant holds nanoseconds
        probe("empty_array_index0", () -> { int[] a = new int[0]; return String.valueOf(a[0]); });
        probe("empty_array_max", () -> { int[] a = new int[0]; OptionalInt m = Arrays.stream(a).max(); return m.isPresent() ? String.valueOf(m.getAsInt()) : "empty_optional"; });
        probe("empty_string_index0", () -> String.valueOf((int) "".charAt(0)));
        probe("empty_string_split_count", () -> String.valueOf("".split(",").length));
        probe("map_order_3_1_2", () -> {
            Map<Integer, Integer> m = new HashMap<>();
            m.put(3, 0); m.put(1, 0); m.put(2, 0);
            StringBuilder sb = new StringBuilder();
            for (int k : m.keySet()) { if (sb.length() > 0) sb.append(','); sb.append(k); }
            return sb.toString();
        });
        probe("decimal_0_1_plus_0_2", () -> new BigDecimal("0.1").add(new BigDecimal("0.2")).toPlainString());
        probe("f64_sum_10m_0_1", () -> { double s = 0.0, a = 0.1; for (int i = 0; i < 10000000; i++) s += a; return fmt17(s); });
    }
}
