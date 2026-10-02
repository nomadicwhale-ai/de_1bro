// Conformance probe (C++20, g++). Prints key=value lines.
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <exception>
#include <limits>
#include <map>
#include <ranges>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>
#include <algorithm>

static void kv(const char* k, const std::string& v) { std::printf("%s=%s\n", k, v.c_str()); }
static std::string fmt17(double x) {
    if (std::isnan(x)) return "nan";
    if (std::isinf(x)) return x > 0 ? "inf" : "-inf";
    char b[64]; std::snprintf(b, sizeof b, "%.17g", x); return b;
}
static void strprobe(const std::string& prefix, const std::string& s) {
    long scalars = 0, u16 = 0;
    for (unsigned char c : s) {
        if ((c & 0xC0) != 0x80) { scalars++; u16 += (c >= 0xF0) ? 2 : 1; }
    }
    kv((prefix + "_utf8").c_str(), std::to_string(s.size()));
    kv((prefix + "_utf16").c_str(), std::to_string(u16));
    kv((prefix + "_scalars").c_str(), std::to_string(scalars));
}
template <class F> static void probe(const char* k, F f) {
    try { kv(k, f()); } catch (const std::exception&) { kv(k, "exception"); } catch (...) { kv(k, "exception"); }
}

int main() {
    kv("lang", "cpp");
    kv("version", std::string("g++ ") + __VERSION__ + " std=c++" + std::to_string(__cplusplus));
    kv("size_int8", std::to_string(sizeof(int8_t)));
    kv("size_int16", std::to_string(sizeof(int16_t)));
    kv("size_int32", std::to_string(sizeof(int32_t)));
    kv("size_int64", std::to_string(sizeof(int64_t)));
    kv("size_uint8", std::to_string(sizeof(uint8_t)));
    kv("size_uint16", std::to_string(sizeof(uint16_t)));
    kv("size_uint32", std::to_string(sizeof(uint32_t)));
    kv("size_uint64", std::to_string(sizeof(uint64_t)));
    kv("size_float32", std::to_string(sizeof(float)));
    kv("size_float64", std::to_string(sizeof(double)));
    kv("size_bool", std::to_string(sizeof(bool)));
    kv("size_char", std::to_string(sizeof(char)));
    kv("char_meaning", "char is a 1-byte integer code unit of implementation-defined signedness, not a Unicode character (char8_t/char16_t/char32_t exist separately)");
    kv("int32_max_plus_1", "undefined_behavior");
    kv("int64_max_plus_1", "undefined_behavior");
    { volatile uint8_t a = 255; uint8_t r = static_cast<uint8_t>(a + 1); kv("uint8_255_plus_1", std::to_string(r)); }
    { volatile uint32_t a = 0; uint32_t r = a - 1u; kv("uint32_0_minus_1", std::to_string(r)); }
    { volatile int a = -7, b = 2; kv("int_div_m7_2", std::to_string(a / b)); kv("int_mod_m7_2", std::to_string(a % b)); }
    kv("int_div_by_zero", "undefined_behavior");
    { volatile double a = 0.1, b = 0.2; kv("f64_0_1_plus_0_2", fmt17(a + b)); }
    { volatile int32_t i = 16777217; volatile float f = static_cast<float>(i); kv("f32_16777217_roundtrip", fmt17(f)); }
    { volatile double a = 9007199254740992.0; kv("f64_2p53_plus_1", fmt17(a + 1.0)); }
    { volatile double n = std::numeric_limits<double>::quiet_NaN(); kv("f64_nan_eq_nan", (n == n) ? "true" : "false"); }
    { volatile double z = 0.0, o = 1.0; kv("f64_1_div_0", fmt17(o / z)); kv("f64_neg1_div_0", fmt17(-o / z)); kv("f64_0_div_0", fmt17(z / z)); }
    { volatile int64_t i = 9007199254740993LL; volatile double d = static_cast<double>(i); int64_t r = static_cast<int64_t>(d); kv("i64_2p53p1_via_f64", std::to_string(r)); }
    strprobe("str_e_pre", "\xC3\xA9");
    strprobe("str_e_comb", "e\xCC\x81");
    strprobe("str_emoji", "\xF0\x9F\x98\x80");
    {
        using namespace std::chrono;
        auto d = sys_days{year{2015} / January / 1}.time_since_epoch().count();
        kv("date_epoch_day_2015_01_01", std::to_string(d));
        using P = system_clock::period;
        std::string p = (P::den == 1000000000) ? "ns" : (P::den == 1000000) ? "us" : (P::den == 1000) ? "ms" : "other";
        kv("timestamp_max_precision", p);
    }
    probe("empty_array_index0", []() -> std::string { std::vector<int> v; return std::to_string(v.at(0)); }); // at() throws; operator[] would be UB
    probe("empty_array_max", []() -> std::string { std::vector<int> v; auto it = std::max_element(v.begin(), v.end()); return it == v.end() ? "end_iterator" : "value"; });
    probe("empty_string_index0", []() -> std::string { std::string s; return s[0] == '\0' ? "NUL_char(operator[] at size() is defined)" : "other"; });
    probe("empty_string_split_count", []() -> std::string {
        std::string s; size_t n = 0; for (auto part : s | std::views::split(',')) { (void)part; n++; } return std::to_string(n); });
    {
        std::unordered_map<int, int> m; m[3] = 0; m[1] = 0; m[2] = 0;
        std::string o; for (auto& [k, v] : m) { if (!o.empty()) o += ","; o += std::to_string(k); (void)v; }
        kv("map_order_3_1_2", o);
    }
    kv("decimal_0_1_plus_0_2", "n/a");
    { volatile double s = 0.0; for (int i = 0; i < 10000000; i++) s = s + 0.1; kv("f64_sum_10m_0_1", fmt17(s)); }
    return 0;
}
