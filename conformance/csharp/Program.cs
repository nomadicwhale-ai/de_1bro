// Conformance probe (C# / .NET 8, BCL only). NOT RUN in the authoring environment.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Numerics;
using System.Text;

static class P
{
    static void Kv(string k, object v) => Console.WriteLine($"{k}={v}");
    static string Fmt17(double x)
    {
        if (double.IsNaN(x)) return "nan";
        if (double.IsPositiveInfinity(x)) return "inf";
        if (double.IsNegativeInfinity(x)) return "-inf";
        var s = x.ToString("G17", CultureInfo.InvariantCulture);
        if (s.Contains('E')) s = decimal.Parse(s, NumberStyles.Float, CultureInfo.InvariantCulture).ToString(CultureInfo.InvariantCulture);
        return s;
    }
    static void Probe(string k, Func<string> f)
    {
        try { Kv(k, f()); } catch (Exception) { Kv(k, "exception"); }
    }
    static void StrProbe(string p, string s)
    {
        Kv(p + "_utf8", Encoding.UTF8.GetByteCount(s));
        Kv(p + "_utf16", s.Length);
        Kv(p + "_scalars", s.EnumerateRunes().Count());
    }
    static int zeroI = 0; static double zeroD = 0.0, oneD = 1.0;
    static void Main()
    {
        Kv("lang", "csharp");
        Kv("version", ".NET " + Environment.Version);
        Kv("size_int8", sizeof(sbyte)); Kv("size_int16", sizeof(short)); Kv("size_int32", sizeof(int)); Kv("size_int64", sizeof(long));
        Kv("size_uint8", sizeof(byte)); Kv("size_uint16", sizeof(ushort)); Kv("size_uint32", sizeof(uint)); Kv("size_uint64", sizeof(ulong));
        Kv("size_float32", sizeof(float)); Kv("size_float64", sizeof(double)); Kv("size_bool", sizeof(bool)); Kv("size_char", sizeof(char));
        Kv("char_meaning", "char is a 16-bit UTF-16 code unit");
        // default context is unchecked: wraps
        Probe("int32_max_plus_1", () => { int x = int.MaxValue; unchecked { x++; } return x.ToString(); });
        Probe("int64_max_plus_1", () => { long x = long.MaxValue; unchecked { x++; } return x.ToString(); });
        Probe("uint8_255_plus_1", () => { byte x = 255; unchecked { x++; } return x.ToString(); });
        Probe("uint32_0_minus_1", () => { uint x = 0; unchecked { x--; } return x.ToString(); });
        Probe("int_div_m7_2", () => { int a = -7, b = 2; return (a / b).ToString(); });
        Probe("int_mod_m7_2", () => { int a = -7, b = 2; return (a % b).ToString(); });
        Probe("int_div_by_zero", () => (1 / zeroI).ToString());
        Probe("f64_0_1_plus_0_2", () => { double a = 0.1, b = 0.2; return Fmt17(a + b); });
        Probe("f32_16777217_roundtrip", () => { int i = 16777217; return Fmt17((double)(float)i); });
        Probe("f64_2p53_plus_1", () => { double x = 9007199254740992.0; return Fmt17(x + 1.0); });
        Probe("f64_nan_eq_nan", () => { double n = double.NaN; return (n == n) ? "true" : "false"; });
        Probe("f64_1_div_0", () => Fmt17(oneD / zeroD));
        Probe("f64_neg1_div_0", () => Fmt17(-oneD / zeroD));
        Probe("f64_0_div_0", () => Fmt17(zeroD / zeroD));
        Probe("i64_2p53p1_via_f64", () => { long i = 9007199254740993L; return ((long)(double)i).ToString(); });
        StrProbe("str_e_pre", "é");
        StrProbe("str_e_comb", "é");
        StrProbe("str_emoji", "\U0001F600");
        Probe("date_epoch_day_2015_01_01", () => (new DateOnly(2015, 1, 1).DayNumber - new DateOnly(1970, 1, 1).DayNumber).ToString());
        Kv("timestamp_max_precision", "100ns"); // DateTime/DateTimeOffset ticks = 100 ns
        Probe("empty_array_index0", () => { var a = new int[0]; return a[0].ToString(); });
        Probe("empty_array_max", () => new int[0].Max().ToString());
        Probe("empty_string_index0", () => ((int)""[0]).ToString());
        Probe("empty_string_split_count", () => "".Split(',').Length.ToString());
        Probe("map_order_3_1_2", () => { var m = new Dictionary<int, int>(); m[3] = 0; m[1] = 0; m[2] = 0; return string.Join(",", m.Keys); });
        Probe("decimal_0_1_plus_0_2", () => (0.1m + 0.2m).ToString(CultureInfo.InvariantCulture));
        Probe("f64_sum_10m_0_1", () => { double s = 0, a = 0.1; for (int i = 0; i < 10000000; i++) s += a; return Fmt17(s); });
    }
}
