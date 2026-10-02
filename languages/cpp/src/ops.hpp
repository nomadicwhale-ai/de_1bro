// Operation implementations. Each Agg consumes columnar batches and yields result rows.
#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <memory>
#include <unordered_map>
#include <unordered_set>
#include "digest.hpp"
#include "parse.hpp"

namespace bench {

using Rows = std::vector<Row>;

struct Agg {
    virtual ~Agg() = default;
    virtual void consume(const Batch& b, const Dims& d) = 0;
    virtual Rows result(const Batch& b, const Dims& d) = 0;
    virtual void floats(double&, double&) const {}
};

inline Val optI(int64_t v, bool seen) { return seen ? Val::I(v) : Val::N(); }
inline Val dictVal(const Dict& d, int32_t c) { return c < 0 ? Val::N() : Val::S(d.strs[c]); }

// ---- OP01 ----
struct Op01 : Agg {
    int64_t n = 0, nq = 0, sq = 0, sp = 0, mn = 0, mx = 0, cr = 0;
    bool started = false;
    void consume(const Batch& b, const Dims&) override {
        size_t cnt = b.cents.size();
        if (!started && cnt > 0) { mn = mx = b.cents[0]; started = true; }
        const int64_t* cents = b.cents.data();
        const int32_t* qty = b.qty.data();
        const uint8_t *qnull = b.qnull.data(), *ret = b.ret.data();
        int64_t lmn = mn, lmx = mx, lsp = sp, lnq = 0, lsq = 0, lcr = 0;
        for (size_t i = 0; i < cnt; i++) {
            int64_t c = cents[i];
            if (!qnull[i]) { lnq++; lsq += qty[i]; }
            lsp += c;
            if (c < lmn) lmn = c;
            if (c > lmx) lmx = c;
            lcr += ret[i];
        }
        mn = lmn; mx = lmx; sp = lsp;
        n += cnt; nq += lnq; sq += lsq; cr += lcr;
    }
    Rows result(const Batch&, const Dims&) override {
        return {{Val::I(n), Val::I(nq), optI(sq, nq > 0), Val::I(sp),
                 started ? Val::I(mn) : Val::N(), started ? Val::I(mx) : Val::N(), Val::I(cr)}};
    }
};

// ---- OP03 (groups indexed by country dictionary code + 1; slot 0 = NULL) ----
struct Op03 : Agg {
    std::vector<int64_t> cnt, sq, sc;
    std::vector<uint8_t> seenq;
    void consume(const Batch& b, const Dims&) override {
        size_t need = b.countryD.strs.size() + 1;
        if (cnt.size() < need) { cnt.resize(need); sq.resize(need); sc.resize(need); seenq.resize(need); }
        for (size_t i = 0; i < b.cents.size(); i++) {
            size_t g = b.country[i] + 1;
            cnt[g]++;
            sc[g] += b.cents[i];
            if (!b.qnull[i]) { sq[g] += b.qty[i]; seenq[g] = 1; }
        }
    }
    Rows result(const Batch& b, const Dims&) override {
        Rows out;
        for (size_t g = 0; g < cnt.size(); g++) {
            if (!cnt[g]) continue;
            out.push_back({g ? Val::S(b.countryD.strs[g - 1]) : Val::N(), Val::I(cnt[g]), optI(sq[g], seenq[g]), Val::I(sc[g])});
        }
        return out;
    }
};

// ---- OP04: group by customer_id (std::unordered_map, default identity hash for int64) ----
struct Op04 : Agg {
    std::unordered_map<int64_t, int32_t> m;
    std::vector<int64_t> keys, cnt, sum;
    void consume(const Batch& b, const Dims&) override {
        for (size_t i = 0; i < b.cents.size(); i++) {
            auto [it, ins] = m.try_emplace(b.cid[i], static_cast<int32_t>(keys.size()));
            if (ins) { keys.push_back(b.cid[i]); cnt.push_back(0); sum.push_back(0); }
            cnt[it->second]++;
            sum[it->second] += b.cents[i];
        }
    }
    Rows result(const Batch&, const Dims&) override {
        Rows out;
        out.reserve(keys.size());
        for (size_t g = 0; g < keys.size(); g++) out.push_back({Val::I(keys[g]), Val::I(cnt[g]), Val::I(sum[g])});
        return out;
    }
};

// ---- OP05: group by (country, category, year) ----
struct Op05 : Agg {
    // key packed as 3 x 21 bits is unsafe for year; use a 64-bit key: (country+1)<<40 | (category+1)<<24 | (year & 0xFFFFFF)
    std::unordered_map<uint64_t, int32_t> m;
    std::vector<std::array<int32_t, 3>> keys;
    std::vector<int64_t> cnt, sum;
    void consume(const Batch& b, const Dims&) override {
        for (size_t i = 0; i < b.cents.size(); i++) {
            int64_t y, mo, d;
            civilFromDays(b.date[i], y, mo, d);
            uint64_t k = (uint64_t(uint32_t(b.country[i] + 1)) << 40) | (uint64_t(uint32_t(b.category[i] + 1)) << 24) |
                         (uint64_t(y) & 0xFFFFFF);
            auto [it, ins] = m.try_emplace(k, static_cast<int32_t>(keys.size()));
            if (ins) { keys.push_back({b.country[i], b.category[i], int32_t(y)}); cnt.push_back(0); sum.push_back(0); }
            cnt[it->second]++;
            sum[it->second] += b.cents[i];
        }
    }
    Rows result(const Batch& b, const Dims&) override {
        Rows out;
        for (size_t g = 0; g < keys.size(); g++)
            out.push_back({dictVal(b.countryD, keys[g][0]), dictVal(b.categoryD, keys[g][1]), Val::I(keys[g][2]),
                           Val::I(cnt[g]), Val::I(sum[g])});
        return out;
    }
};

// ---- OP06: hash join sales x dim_customer, group by segment (slot 0 = NULL segment) ----
struct Op06 : Agg {
    std::vector<int64_t> cnt, sc, sq;
    std::vector<uint8_t> seenq;
    void consume(const Batch& b, const Dims& d) override {
        size_t need = d.segD.strs.size() + 1;
        if (cnt.size() < need) { cnt.resize(need); sc.resize(need); sq.resize(need); seenq.resize(need); }
        for (size_t i = 0; i < b.cents.size(); i++) {
            auto it = d.custSeg.find(b.cid[i]);
            if (it == d.custSeg.end()) continue;  // inner join
            size_t g = it->second + 1;
            cnt[g]++;
            sc[g] += b.cents[i];
            if (!b.qnull[i]) { sq[g] += b.qty[i]; seenq[g] = 1; }
        }
    }
    Rows result(const Batch&, const Dims& d) override {
        Rows out;
        for (size_t g = 0; g < cnt.size(); g++) {
            if (!cnt[g]) continue;
            out.push_back({g ? Val::S(d.segD.strs[g - 1]) : Val::N(), Val::I(cnt[g]), Val::I(sc[g]), optI(sq[g], seenq[g])});
        }
        return out;
    }
};

// ---- OP07: star join, segment = 'enterprise', group by brand (slot 0 = NULL brand) ----
struct Op07 : Agg {
    std::vector<int64_t> cnt, sc;
    void consume(const Batch& b, const Dims& d) override {
        size_t need = d.brandD.strs.size() + 1;
        if (cnt.size() < need) { cnt.resize(need); sc.resize(need); }
        auto e = d.segD.m.find(std::string_view("enterprise"));
        if (e == d.segD.m.end()) return;
        int32_t ent = e->second;
        for (size_t i = 0; i < b.cents.size(); i++) {
            auto c = d.custSeg.find(b.cid[i]);
            if (c == d.custSeg.end() || c->second != ent) continue;
            auto p = d.prodBrand.find(b.pid[i]);
            if (p == d.prodBrand.end()) continue;
            size_t g = p->second + 1;
            cnt[g]++;
            sc[g] += b.cents[i];
        }
    }
    Rows result(const Batch&, const Dims& d) override {
        Rows out;
        for (size_t g = 0; g < cnt.size(); g++) {
            if (!cnt[g]) continue;
            out.push_back({g ? Val::S(d.brandD.strs[g - 1]) : Val::N(), Val::I(cnt[g]), Val::I(sc[g])});
        }
        return out;
    }
};

// ---- OP08: full sort by (timestamp, id); materialized only ----
struct Op08 : Agg {
    Rows out;
    void consume(const Batch&, const Dims&) override {}
    Rows result(const Batch& b, const Dims&) override {
        struct K { int64_t ts, id; };
        std::vector<K> v(b.ts.size());
        for (size_t i = 0; i < v.size(); i++) v[i] = {b.ts[i], b.tid[i]};
        std::sort(v.begin(), v.end(), [](const K& a, const K& c) { return a.ts != c.ts ? a.ts < c.ts : a.id < c.id; });
        uint64_t pos = 0;
        for (size_t i = 0; i < v.size(); i++) pos += uint64_t(i + 1) * uint64_t(v[i].id);
        return {{Val::I(v.front().id), Val::I(v.back().id), Val::I(static_cast<int64_t>(pos))}};
    }
};

// ---- OP09: top 100 customers by revenue (ties: smaller customer_id) ----
struct Op09 : Op04 {
    Rows result(const Batch&, const Dims&) override {
        std::vector<uint32_t> idx(keys.size());
        for (size_t i = 0; i < idx.size(); i++) idx[i] = static_cast<uint32_t>(i);
        size_t k = std::min<size_t>(100, idx.size());
        auto less = [&](uint32_t a, uint32_t c) { return sum[a] != sum[c] ? sum[a] > sum[c] : keys[a] < keys[c]; };
        std::partial_sort(idx.begin(), idx.begin() + k, idx.end(), less);
        Rows out;
        for (size_t r = 0; r < k; r++) out.push_back({Val::I(int64_t(r + 1)), Val::I(keys[idx[r]]), Val::I(sum[idx[r]])});
        return out;
    }
};

// ---- OP10: exact distinct counts ----
struct Op10 : Agg {
    std::unordered_set<int64_t> c, p;
    std::unordered_set<uint64_t> sd;
    void consume(const Batch& b, const Dims&) override {
        for (size_t i = 0; i < b.cid.size(); i++) {
            c.insert(b.cid[i]);
            p.insert(b.pid[i]);
            sd.insert(uint64_t(uint32_t(b.store[i])) << 32 | uint64_t(uint32_t(b.date[i])));
        }
    }
    Rows result(const Batch&, const Dims&) override {
        return {{Val::I(int64_t(c.size())), Val::I(int64_t(p.size())), Val::I(int64_t(sd.size()))}};
    }
};

// ---- OP19: NULL handling ----
struct Op19 : Agg {
    int64_t nq = 0, nc = 0, sq = 0, ne = 0;
    std::vector<uint8_t> seen, nonEmpty;
    void consume(const Batch& b, const Dims&) override {
        const auto& strs = b.countryD.strs;
        while (seen.size() < strs.size()) { nonEmpty.push_back(!strs[seen.size()].empty()); seen.push_back(0); }
        for (size_t i = 0; i < b.country.size(); i++) {
            if (b.qnull[i]) { nq++; sq++; } else sq += b.qty[i];
            int32_t c = b.country[i];
            if (c < 0) nc++;
            else { seen[c] = 1; ne += nonEmpty[c]; }
        }
    }
    Rows result(const Batch&, const Dims&) override {
        int64_t d = 0;
        for (auto s : seen) d += s;
        return {{Val::I(nq), Val::I(nc), Val::I(sq), Val::I(ne), Val::I(d)}};
    }
};

// ---- OP21: exact decimal sum vs float64 sums ----
struct Op21 : Agg {
    int64_t exact = 0;
    double naive = 0, ksum = 0, comp = 0;
    void consume(const Batch& b, const Dims&) override {
        int64_t e = exact;
        double nv = naive, ks = ksum, cp = comp;
        for (int64_t c : b.cents) {
            e += c;
            double v = static_cast<double>(c) / 100.0;
            nv += v;
            double y = v - cp;
            double t = ks + y;
            cp = (t - ks) - y;
            ks = t;
        }
        exact = e; naive = nv; ksum = ks; comp = cp;
    }
    Rows result(const Batch&, const Dims&) override {
        int64_t q = floorDiv(exact, 100), r = exact - q * 100;
        std::string t = std::to_string(q) + "." + char('0' + r / 10) + char('0' + r % 10);
        return {{Val::I(exact), Val::S(t)}};
    }
    void floats(double& a, double& k) const override { a = naive; k = ksum; }
};

// ---- OP22: lossy conversion counts ----
struct Op22 : Agg {
    int64_t a = 0, bb = 0, c = 0, ymd = 0;
    void consume(const Batch& b, const Dims&) override {
        int64_t la = 0, lb = 0, lc = 0, ly = 0;
        for (size_t i = 0; i < b.cents.size(); i++) {
            uint64_t k = uint64_t(b.tid[i]) * 4294967311ULL + uint64_t(b.cid[i]);  // wrapping int64
            int64_t ks = static_cast<int64_t>(k);
            if (static_cast<int64_t>(static_cast<double>(ks)) != ks) la++;
            double f = static_cast<double>(b.cents[i]) / 100.0;
            if (static_cast<int64_t>(f * 100.0) != b.cents[i]) lb++;
            if ((b.ts[i] / 1000) * 1000 != b.ts[i]) lc++;
            int64_t y, m, d;
            civilFromDays(b.date[i], y, m, d);
            ly += y * 10000 + m * 100 + d;
        }
        a += la; bb += lb; c += lc; ymd += ly;
    }
    Rows result(const Batch&, const Dims&) override {
        return {{Val::I(a), Val::I(bb), Val::I(c), Val::I(ymd)}};
    }
};

struct OpDef {
    uint32_t need;
    std::unique_ptr<Agg> (*mk)();
    bool dims;       // needs dim tables
    bool matOnly;    // materialized only
};

template <class T> std::unique_ptr<Agg> make() { return std::make_unique<T>(); }

inline const OpDef* findOp(const std::string& name) {
    static const std::unordered_map<std::string, OpDef> ops = {
        {"OP01", {bit(cQTY) | bit(cPRICE) | bit(cRET), make<Op01>, false, false}},
        {"OP03", {bit(cQTY) | bit(cPRICE) | bit(cCOUNTRY), make<Op03>, false, false}},
        {"OP04", {bit(cCID) | bit(cPRICE), make<Op04>, false, false}},
        {"OP05", {bit(cCOUNTRY) | bit(cCATEGORY) | bit(cDATE) | bit(cPRICE), make<Op05>, false, false}},
        {"OP06", {bit(cCID) | bit(cQTY) | bit(cPRICE), make<Op06>, true, false}},
        {"OP07", {bit(cCID) | bit(cPID) | bit(cPRICE), make<Op07>, true, false}},
        {"OP08", {bit(cTID) | bit(cTS), make<Op08>, false, true}},
        {"OP09", {bit(cCID) | bit(cPRICE), make<Op09>, false, false}},
        {"OP10", {bit(cCID) | bit(cPID) | bit(cSTORE) | bit(cDATE), make<Op10>, false, false}},
        {"OP19", {bit(cQTY) | bit(cCOUNTRY), make<Op19>, false, false}},
        {"OP21", {bit(cPRICE), make<Op21>, false, false}},
        {"OP22", {bit(cTID) | bit(cCID) | bit(cPRICE) | bit(cDATE) | bit(cTS), make<Op22>, false, false}},
    };
    auto it = ops.find(name);
    return it == ops.end() ? nullptr : &it->second;
}

}  // namespace bench
