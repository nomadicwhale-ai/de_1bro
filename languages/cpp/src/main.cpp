// Track L C++20 standard-library-only benchmark.
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <dirent.h>
#include "digest.hpp"
#include "ops.hpp"
#include "parse.hpp"
#include "tuned.hpp"

using namespace bench;
using Clock = std::chrono::steady_clock;

static double msSince(Clock::time_point a, Clock::time_point b) {
    return std::chrono::duration<double, std::milli>(b - a).count();
}

static std::string sizeLabel(int64_t rows) {
    if (rows >= 1000000000 && rows % 1000000000 == 0) return std::to_string(rows / 1000000000) + "b";
    if (rows >= 1000000 && rows % 1000000 == 0) return std::to_string(rows / 1000000) + "m";
    if (rows >= 1000 && rows % 1000 == 0) return std::to_string(rows / 1000) + "k";
    return std::to_string(rows);
}

// Sorted part-*.csv files of <root>/<table>/<label>.
static std::vector<std::string> listParts(const std::string& root, const std::string& table, const std::string& label) {
    std::string dir = root + "/" + table + "/" + label;
    std::vector<std::string> files;
    if (DIR* d = opendir(dir.c_str())) {
        while (dirent* e = readdir(d)) {
            std::string n = e->d_name;
            if (n.rfind("part-", 0) == 0 && n.size() > 4 && n.compare(n.size() - 4, 4, ".csv") == 0) files.push_back(dir + "/" + n);
        }
        closedir(d);
    }
    std::sort(files.begin(), files.end());
    return files;
}

int main(int argc, char** argv) {
    std::string op, dataset = "A", mode = "streaming", input = "data", variant = "stdlib";
    int64_t rows = 0;
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        auto val = [&]() -> std::string { return i + 1 < argc ? argv[++i] : ""; };
        if (a == "--op") op = val();
        else if (a == "--dataset") dataset = val();
        else if (a == "--rows") rows = std::atoll(val().c_str());
        else if (a == "--mode") mode = val();
        else if (a == "--input") input = val();
        else if (a == "--variant") variant = val();
        else if (a == "--chunk-rows" || a == "--threads") val();
    }
    try {
        if (dataset != "A") throw std::runtime_error("only dataset A supported");
        if (variant != "stdlib" && variant != "tuned") throw std::runtime_error("bad variant " + variant);
        if (variant == "tuned" && !findTunedOp(op)) throw std::runtime_error("unsupported tuned op " + op);
        std::string label = sizeLabel(rows);
        auto files = listParts(input, "sales_fact", label);
        if (files.empty()) throw std::runtime_error("no CSV chunks for " + label);

        double loadMs = 0, compMs = 0;
        Rows result;
        double fa = 0, fk = 0;
        bool hasFloats = false;
        std::vector<char> buf;

        if (op == "OP15") {
            Op15State st;
            auto t0 = Clock::now();
            for (auto& f : files) { readFile(f, buf); st.chunk(buf); }
            result = {{Val::I(st.rows), Val::I(st.tid), Val::I(st.cid), Val::I(st.pid), Val::I(st.store), Val::I(st.qty),
                       Val::I(st.nq), Val::I(st.cents), Val::I(st.disc), Val::I(st.tax), Val::I(st.cb), Val::I(st.nc),
                       Val::I(st.gb), Val::I(st.days), Val::I(st.sec), Val::I(st.frac), Val::I(st.ret)}};
            compMs = msSince(t0, Clock::now());
        } else {
            const OpDef* def = variant == "tuned" ? findTunedOp(op) : findOp(op);
            if (!def) throw std::runtime_error("unsupported op " + op);
            if (def->matOnly && mode != "materialized") throw std::runtime_error(op + " is materialized only");
            auto agg = def->mk();
            Dims dims;
            if (def->dims) {  // dimension tables are loaded first; time counts as load_ms
                auto t0 = Clock::now();
                for (auto& f : listParts(input, "dim_customer", label)) { readFile(f, buf); dims.loadCustomers(buf); }
                for (auto& f : listParts(input, "dim_product", label)) { readFile(f, buf); dims.loadProducts(buf); }
                loadMs += msSince(t0, Clock::now());
            }
            Batch b;
            if (mode == "streaming") {
                b.init(def->need, 0);
                for (auto& f : files) {
                    auto t0 = Clock::now();
                    readFile(f, buf);
                    b.reset();
                    parseChunk(buf, def->need, b);
                    auto t1 = Clock::now();
                    agg->consume(b, dims);
                    auto t2 = Clock::now();
                    loadMs += msSince(t0, t1);
                    compMs += msSince(t1, t2);
                }
                auto t = Clock::now();
                result = agg->result(b, dims);
                compMs += msSince(t, Clock::now());
            } else if (mode == "materialized") {
                auto t0 = Clock::now();
                b.init(def->need, static_cast<size_t>(rows));
                for (auto& f : files) { readFile(f, buf); parseChunk(buf, def->need, b); }
                std::vector<char>().swap(buf);
                auto t1 = Clock::now();
                loadMs += msSince(t0, t1);
                agg->consume(b, dims);
                result = agg->result(b, dims);
                compMs = msSince(t1, Clock::now());
            } else throw std::runtime_error("bad mode " + mode);
            if (op == "OP21") { agg->floats(fa, fk); hasFloats = true; }
        }

        std::string sum = digest(result);
        std::string fl;
        if (hasFloats) {
            char t[128];
            std::snprintf(t, sizeof t, ",\"floats\":{\"naive_sum\":%.17g,\"kahan_sum\":%.17g}", fa, fk);
            fl = t;
        }
        std::printf("{\"load_ms\":%.3f,\"compute_ms\":%.3f,\"checksum\":\"%s\",\"row_count\":%zu%s,"
                    "\"toolchain\":{\"name\":\"g++\",\"version\":\"%d.%d.%d\",\"flags\":\"-std=c++20 -O3\"}}\n",
                    loadMs, compMs, sum.c_str(), result.size(), fl.c_str(), __GNUC__, __GNUC_MINOR__, __GNUC_PATCHLEVEL__);
        return 0;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "error: %s\n", e.what());
        return 1;
    }
}
