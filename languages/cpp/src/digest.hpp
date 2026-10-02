// Result digest (spec/checksum.md): mix64, FNV-1a, order-insensitive sum/xor of row hashes.
#pragma once
#include <cstdint>
#include <cstdio>
#include <string>
#include <string_view>
#include <vector>

namespace bench {

constexpr uint64_t GOLDEN = 0x9E3779B97F4A7C15ULL;
constexpr uint64_t C1 = 0xBF58476D1CE4E5B9ULL;
constexpr uint64_t C2 = 0x94D049BB133111EBULL;
constexpr uint64_t NULL_CANON = 0xA5A5A5A5A5A5A5A5ULL;
constexpr uint64_t FNV_OFF = 0xCBF29CE484222325ULL;
constexpr uint64_t FNV_PRIME = 0x100000001B3ULL;

inline uint64_t mix64(uint64_t z) {
    z ^= z >> 30; z *= C1;
    z ^= z >> 27; z *= C2;
    z ^= z >> 31;
    return z;
}

inline uint64_t fnv1a(std::string_view s) {
    uint64_t h = FNV_OFF;
    for (unsigned char c : s) h = (h ^ c) * FNV_PRIME;
    return h;
}

// One result cell: NULL, int64 or string.
struct Val {
    enum Kind : uint8_t { Null, Int, Str } kind = Null;
    int64_t i = 0;
    std::string s;
    static Val I(int64_t x) { Val v; v.kind = Int; v.i = x; return v; }
    static Val S(std::string_view x) { Val v; v.kind = Str; v.s = std::string(x); return v; }
    static Val N() { return Val{}; }
    uint64_t canon() const {
        switch (kind) {
            case Int: return static_cast<uint64_t>(i);
            case Str: return fnv1a(s);
            default: return NULL_CANON;
        }
    }
};
using Row = std::vector<Val>;

inline std::string digest(const std::vector<Row>& rows) {
    uint64_t sum = 0, x = 0;
    for (const auto& r : rows) {
        uint64_t h = 0;
        for (const auto& v : r) h = mix64(h + v.canon() + GOLDEN);
        sum += h;
        x ^= h;
    }
    char buf[40];
    std::snprintf(buf, sizeof buf, "%016llx%016llx", (unsigned long long)sum, (unsigned long long)x);
    return buf;
}

}  // namespace bench
