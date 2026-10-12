// Dependency-free tuned containers; the stdlib operations in ops.hpp are unchanged.
#pragma once
#include "ops.hpp"

namespace bench {

// uint64 -> dense index, linear probing at <= 50% occupancy. Separate occupancy
// (index + 1) permits every key bit pattern, including zero and signed extrema.
class FlatMap {
    std::vector<uint64_t> keys = std::vector<uint64_t>(16);
    std::vector<size_t> slots = std::vector<size_t>(16);
    size_t count = 0;

    size_t slot(uint64_t key) const {
        size_t i = mix64(key) & (slots.size() - 1);
        while (slots[i] && keys[i] != key) i = (i + 1) & (slots.size() - 1);
        return i;
    }

    void grow() {
        auto oldKeys = std::move(keys);
        auto oldSlots = std::move(slots);
        keys.resize(oldKeys.size() * 2);
        slots.assign(oldSlots.size() * 2, 0);
        for (size_t j = 0; j < oldSlots.size(); j++) {
            if (!oldSlots[j]) continue;
            size_t i = slot(oldKeys[j]);
            keys[i] = oldKeys[j];
            slots[i] = oldSlots[j];
        }
    }

public:
    size_t size() const { return count; }
    size_t getOrAdd(uint64_t key) {
        size_t i = slot(key);
        if (slots[i]) return slots[i] - 1;
        if (count == slots.size() / 2) { grow(); i = slot(key); }
        keys[i] = key;
        slots[i] = ++count;
        return count - 1;
    }
};

// Keep the original result formation / top-N logic; replace only its map probes.
template <class Base> struct FlatCustomers : Base {
    FlatMap flat;
    void consume(const Batch& b, const Dims&) override {
        for (size_t i = 0; i < b.cents.size(); i++) {
            size_t g = flat.getOrAdd(static_cast<uint64_t>(b.cid[i]));
            if (g == this->keys.size()) {
                this->keys.push_back(b.cid[i]); this->cnt.push_back(0); this->sum.push_back(0);
            }
            this->cnt[g]++;
            this->sum[g] += b.cents[i];
        }
    }
};

struct FlatDistinct : Agg {
    FlatMap c, p, sd;
    void consume(const Batch& b, const Dims&) override {
        for (size_t i = 0; i < b.cid.size(); i++) {
            c.getOrAdd(static_cast<uint64_t>(b.cid[i]));
            p.getOrAdd(static_cast<uint64_t>(b.pid[i]));
            sd.getOrAdd(uint64_t(uint32_t(b.store[i])) << 32 | uint64_t(uint32_t(b.date[i])));
        }
    }
    Rows result(const Batch&, const Dims&) override {
        return {{Val::I(int64_t(c.size())), Val::I(int64_t(p.size())), Val::I(int64_t(sd.size()))}};
    }
};

inline const OpDef* findTunedOp(const std::string& name) {
    static const std::unordered_map<std::string, OpDef> ops = {
        {"OP04", {bit(cCID) | bit(cPRICE), make<FlatCustomers<Op04>>, false, false}},
        {"OP09", {bit(cCID) | bit(cPRICE), make<FlatCustomers<Op09>>, false, false}},
        {"OP10", {bit(cCID) | bit(cPID) | bit(cSTORE) | bit(cDATE), make<FlatDistinct>, false, false}},
    };
    auto it = ops.find(name);
    return it == ops.end() ? nullptr : &it->second;
}

}  // namespace bench
