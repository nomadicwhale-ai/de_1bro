// Hand-written byte-level CSV parsing into columnar batches.
#pragma once
#include <charconv>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace bench {

enum Col { cTID, cCID, cPID, cSTORE, cQTY, cPRICE, cDISC, cTAX, cCOUNTRY, cCATEGORY, cDATE, cTS, cRET, nCols };
constexpr uint32_t bit(int c) { return 1u << c; }

[[noreturn]] inline void bad() { throw std::runtime_error("malformed CSV field"); }

// ---- string dictionary (std::unordered_map with transparent lookup: no allocation on hit) ----
struct SvHash {
    using is_transparent = void;
    size_t operator()(std::string_view s) const { return std::hash<std::string_view>{}(s); }
};
struct SvEq {
    using is_transparent = void;
    bool operator()(std::string_view a, std::string_view b) const { return a == b; }
};
struct Dict {
    std::unordered_map<std::string, int32_t, SvHash, SvEq> m;
    std::vector<std::string> strs;
    int32_t code(std::string_view b) {
        auto it = m.find(b);
        if (it != m.end()) return it->second;
        int32_t c = static_cast<int32_t>(strs.size());
        strs.emplace_back(b);
        m.emplace(strs.back(), c);
        return c;
    }
};

// Columnar block; only columns in `need` are filled.
struct Batch {
    size_t n = 0;
    std::vector<int64_t> tid, cid, pid, cents, ts;
    std::vector<int32_t> store, qty, country, category, date;
    std::vector<uint8_t> qnull, ret;
    Dict countryD, categoryD;

    void init(uint32_t need, size_t cap) {
        auto rs = [&](auto& v, int c) { if (need & bit(c)) v.reserve(cap); };
        rs(tid, cTID); rs(cid, cCID); rs(pid, cPID); rs(store, cSTORE); rs(qty, cQTY); rs(qnull, cQTY);
        rs(cents, cPRICE); rs(country, cCOUNTRY); rs(category, cCATEGORY); rs(date, cDATE); rs(ts, cTS); rs(ret, cRET);
    }
    void reset() {
        n = 0;
        tid.clear(); cid.clear(); pid.clear(); cents.clear(); ts.clear();
        store.clear(); qty.clear(); country.clear(); category.clear(); date.clear();
        qnull.clear(); ret.clear();
    }
};

// ---- file reading ----
inline void readFile(const std::string& path, std::vector<char>& buf) {
    FILE* f = std::fopen(path.c_str(), "rb");
    if (!f) throw std::runtime_error("cannot open " + path);
    std::fseek(f, 0, SEEK_END);
    long sz = std::ftell(f);
    std::fseek(f, 0, SEEK_SET);
    if (buf.size() < static_cast<size_t>(sz)) buf.resize(sz);
    size_t got = std::fread(buf.data(), 1, sz, f);
    std::fclose(f);
    if (got != static_cast<size_t>(sz)) throw std::runtime_error("short read " + path);
    buf.resize(sz);  // size == file size (capacity is kept)
}

// ---- field parsers ----
inline bool isNull(std::string_view f) { return f.size() == 2 && f[0] == '\\' && f[1] == 'N'; }

inline int64_t parseInt(std::string_view f) {
    size_t i = 0;
    bool neg = false;
    if (!f.empty() && (f[0] == '-' || f[0] == '+')) { neg = f[0] == '-'; i = 1; }
    if (i >= f.size()) bad();
    uint64_t v = 0;
    for (; i < f.size(); i++) {
        unsigned d = static_cast<unsigned char>(f[i]) - '0';
        if (d > 9) bad();
        v = v * 10 + d;
    }
    return neg ? -static_cast<int64_t>(v) : static_cast<int64_t>(v);
}

// "1234.56" -> 123456 without floating point; digits beyond 2 decimals are truncated.
inline int64_t parseCents(std::string_view f) {
    size_t i = 0;
    bool neg = false;
    if (!f.empty() && (f[0] == '-' || f[0] == '+')) { neg = f[0] == '-'; i = 1; }
    if (i >= f.size()) bad();
    int64_t ip = 0, frac = 0;
    int nd = 0, fd = 0;
    for (; i < f.size() && f[i] != '.'; i++) {
        unsigned d = static_cast<unsigned char>(f[i]) - '0';
        if (d > 9) bad();
        ip = ip * 10 + d; nd++;
    }
    if (i < f.size()) {
        for (i++; i < f.size(); i++) {
            unsigned d = static_cast<unsigned char>(f[i]) - '0';
            if (d > 9) bad();
            if (fd < 2) { frac = frac * 10 + d; fd++; }
            nd++;
        }
    }
    if (nd == 0) bad();
    for (; fd < 2; fd++) frac *= 10;
    int64_t v = ip * 100 + frac;
    return neg ? -v : v;
}

inline int64_t floorDiv(int64_t a, int64_t b) {
    int64_t q = a / b;
    if ((a % b != 0) && ((a < 0) != (b < 0))) q--;
    return q;
}

inline int64_t daysFromCivil(int64_t y, int64_t m, int64_t d) {
    if (m <= 2) y--;
    int64_t era = floorDiv(y, 400);
    int64_t yoe = y - era * 400;
    int64_t mp = m > 2 ? m - 3 : m + 9;
    int64_t doy = (153 * mp + 2) / 5 + d - 1;
    int64_t doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return era * 146097 + doe - 719468;
}

// Hinnant's civil_from_days.
inline void civilFromDays(int64_t z, int64_t& y, int64_t& m, int64_t& d) {
    z += 719468;
    int64_t era = floorDiv(z, 146097);
    int64_t doe = z - era * 146097;
    int64_t yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    y = yoe + era * 400;
    int64_t doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    int64_t mp = (5 * doy + 2) / 153;
    d = doy - (153 * mp + 2) / 5 + 1;
    m = mp < 10 ? mp + 3 : mp - 9;
    if (m <= 2) y++;
}

inline int64_t parseDate(std::string_view f) {
    int64_t parts[3] = {0, 0, 0};
    int p = 0, nd = 0;
    int64_t v = 0;
    bool neg = false;
    for (size_t i = 0; i < f.size(); i++) {
        char c = f[i];
        if (c == '-' && i == 0) { neg = true; continue; }
        if (c == '-') {
            if (nd == 0 || p >= 2) bad();
            parts[p++] = v; v = 0; nd = 0;
            continue;
        }
        unsigned d = static_cast<unsigned char>(c) - '0';
        if (d > 9) bad();
        v = v * 10 + d; nd++;
    }
    if (p != 2 || nd == 0) bad();
    parts[2] = v;
    if (neg) parts[0] = -parts[0];
    return daysFromCivil(parts[0], parts[1], parts[2]);
}

inline int64_t two(const char* p) {
    unsigned a = static_cast<unsigned char>(p[0]) - '0', b = static_cast<unsigned char>(p[1]) - '0';
    if (a > 9 || b > 9) bad();
    return a * 10 + b;
}

// "YYYY-MM-DD HH:MM:SS[.ffffff]" -> microseconds since epoch.
inline int64_t parseTS(std::string_view f) {
    size_t sp = f.find(' ');
    if (sp == std::string_view::npos) sp = f.find('T');
    if (sp == std::string_view::npos) bad();
    int64_t days = parseDate(f.substr(0, sp));
    std::string_view t = f.substr(sp + 1);
    if (t.size() < 8 || t[2] != ':' || t[5] != ':') bad();
    int64_t h = two(t.data()), mi = two(t.data() + 3), s = two(t.data() + 6);
    int64_t frac = 0;
    if (t.size() > 8) {
        if (t[8] != '.') bad();
        int n = 0;
        for (size_t i = 9; i < t.size(); i++) {
            unsigned d = static_cast<unsigned char>(t[i]) - '0';
            if (d > 9) bad();
            if (n < 6) { frac = frac * 10 + d; n++; }
        }
        for (; n < 6; n++) frac *= 10;
    }
    return (days * 86400 + h * 3600 + mi * 60 + s) * 1000000 + frac;
}

// ---- line iteration ----
// Returns next line (no \n / \r); advances p. Returns false at end.
inline bool nextLine(const char*& p, const char* end, std::string_view& line) {
    if (p >= end) return false;
    const char* nl = static_cast<const char*>(std::memchr(p, '\n', end - p));
    const char* e = nl ? nl : end;
    const char* le = e;
    if (le > p && le[-1] == '\r') le--;
    line = std::string_view(p, le - p);
    p = nl ? nl + 1 : end;
    return true;
}

// Split off the next comma-terminated field from `line`.
inline std::string_view takeField(std::string_view& line) {
    const char* c = static_cast<const char*>(std::memchr(line.data(), ',', line.size()));
    if (!c) bad();
    std::string_view f(line.data(), c - line.data());
    line.remove_prefix(f.size() + 1);
    return f;
}

inline void skipHeader(const char*& p, const char* end, std::string_view first) {
    if (static_cast<size_t>(end - p) >= first.size() && std::memcmp(p, first.data(), first.size()) == 0) {
        std::string_view l;
        nextLine(p, end, l);
    }
}

// Append the needed columns of every row of buf to b.
inline void parseChunk(const std::vector<char>& buf, uint32_t need, Batch& b) {
    int last = 0;
    for (int c = 0; c < nCols; c++) if (need & bit(c)) last = c;
    const char* p = buf.data();
    const char* end = p + buf.size();
    skipHeader(p, end, "transaction_id");
    std::string_view line;
    size_t n = 0;
    while (nextLine(p, end, line)) {
        if (line.empty()) continue;
        for (int f = 0; f <= last; f++) {
            std::string_view fld;
            if (f == nCols - 1) fld = line; else fld = takeField(line);
            if (!(need & bit(f))) continue;
            switch (f) {
                case cTID: b.tid.push_back(parseInt(fld)); break;
                case cCID: b.cid.push_back(parseInt(fld)); break;
                case cPID: b.pid.push_back(parseInt(fld)); break;
                case cSTORE: b.store.push_back(static_cast<int32_t>(parseInt(fld))); break;
                case cQTY:
                    if (isNull(fld)) { b.qty.push_back(0); b.qnull.push_back(1); }
                    else { b.qty.push_back(static_cast<int32_t>(parseInt(fld))); b.qnull.push_back(0); }
                    break;
                case cPRICE: b.cents.push_back(parseCents(fld)); break;
                case cCOUNTRY: b.country.push_back(isNull(fld) ? -1 : b.countryD.code(fld)); break;
                case cCATEGORY: b.category.push_back(isNull(fld) ? -1 : b.categoryD.code(fld)); break;
                case cDATE: b.date.push_back(static_cast<int32_t>(parseDate(fld))); break;
                case cTS: b.ts.push_back(parseTS(fld)); break;
                case cRET: b.ret.push_back(!fld.empty() && fld[0] == 't'); break;
                default: break;
            }
        }
        n++;
    }
    b.n += n;
}

// ---- OP15: parse every column and summarise ----
inline int64_t floorE6(double x) {
    volatile double t = x * 1e6;  // volatile: forbid FMA contraction of x*1e6+0.5
    double y = t + 0.5;
    int64_t f = static_cast<int64_t>(y);
    if (static_cast<double>(f) > y) f--;
    return f;
}

struct Op15State {
    int64_t rows = 0, tid = 0, cid = 0, pid = 0, store = 0, qty = 0, nq = 0, cents = 0, disc = 0, tax = 0;
    int64_t cb = 0, nc = 0, gb = 0, days = 0, sec = 0, frac = 0, ret = 0;

    static double toD(std::string_view s) {
        double d;
        auto r = std::from_chars(s.data(), s.data() + s.size(), d);
        if (r.ec != std::errc() || r.ptr != s.data() + s.size()) bad();
        return d;
    }
    void chunk(const std::vector<char>& buf) {
        const char* p = buf.data();
        const char* end = p + buf.size();
        skipHeader(p, end, "transaction_id");
        std::string_view line;
        while (nextLine(p, end, line)) {
            if (line.empty()) continue;
            std::string_view fl[nCols];
            for (int f = 0; f < nCols - 1; f++) fl[f] = takeField(line);
            fl[nCols - 1] = line;
            rows++;
            tid += parseInt(fl[cTID]);
            cid += parseInt(fl[cCID]);
            pid += parseInt(fl[cPID]);
            store += parseInt(fl[cSTORE]);
            if (isNull(fl[cQTY])) nq++; else qty += parseInt(fl[cQTY]);
            cents += parseCents(fl[cPRICE]);
            disc += floorE6(toD(fl[cDISC]));
            tax += floorE6(toD(fl[cTAX]));
            if (isNull(fl[cCOUNTRY])) nc++; else cb += static_cast<int64_t>(fl[cCOUNTRY].size());
            if (!isNull(fl[cCATEGORY])) gb += static_cast<int64_t>(fl[cCATEGORY].size());
            days += parseDate(fl[cDATE]);
            int64_t us = parseTS(fl[cTS]);
            sec += floorDiv(us, 1000000);
            frac += us - floorDiv(us, 1000000) * 1000000;
            if (!fl[cRET].empty() && fl[cRET][0] == 't') ret++;
        }
    }
};

// ---- dimension tables (OP06/OP07) ----
// dim_customer: customer_id -> segment code; dim_product: product_id -> brand code (-1 = NULL).
// Only the leading unquoted fields are read; the rest of each line is ignored.
struct Dims {
    std::unordered_map<int64_t, int32_t> custSeg, prodBrand;
    Dict segD, brandD;

    void loadCustomers(const std::vector<char>& buf) {
        const char* p = buf.data();
        const char* end = p + buf.size();
        skipHeader(p, end, "customer_id");
        std::string_view line;
        while (nextLine(p, end, line)) {
            if (line.empty()) continue;
            int64_t id = parseInt(takeField(line));
            for (int i = 0; i < 3; i++) takeField(line);  // name, email, signup_date
            std::string_view seg = takeField(line);
            custSeg[id] = isNull(seg) ? -1 : segD.code(seg);
        }
    }
    void loadProducts(const std::vector<char>& buf) {
        const char* p = buf.data();
        const char* end = p + buf.size();
        skipHeader(p, end, "product_id");
        std::string_view line;
        while (nextLine(p, end, line)) {
            if (line.empty()) continue;
            int64_t id = parseInt(takeField(line));
            takeField(line);  // category
            std::string_view brand = takeField(line);
            prodBrand[id] = isNull(brand) ? -1 : brandD.code(brand);
        }
    }
};

}  // namespace bench
