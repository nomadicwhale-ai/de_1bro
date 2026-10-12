"""Adversarial container/sort tests independent of the generator's distributions."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_cpp_flat_map_and_aggregates(tmp_path):
    if not shutil.which("g++"):
        pytest.skip("g++ not installed")
    source = tmp_path / "test.cpp"
    source.write_text(r'''
#include <cassert>
#include <limits>
#include "tuned.hpp"
using namespace bench;
int main() {
    FlatMap map;
    assert(map.size() == 0);
    std::vector<uint64_t> keys = {0, UINT64_MAX, uint64_t(INT64_MIN), uint64_t(INT64_MAX)};
    // Force a cluster in the initial table, then many rehashes.
    for (uint64_t k = 1; keys.size() < 4000; k++) if ((mix64(k) & 15) == 0) keys.push_back(k);
    for (size_t i = 0; i < keys.size(); i++) assert(map.getOrAdd(keys[i]) == i);
    for (size_t i = keys.size(); i-- > 0;) assert(map.getOrAdd(keys[i]) == i);
    assert(map.size() == keys.size());
    Batch full;
    for (int i = 0; i < 5000; i++) {
        full.cid.push_back(i % 503 - 251);
        full.pid.push_back(i % 107 - 53);
        full.cents.push_back((i % 5 - 2) * 100); // negative sums and revenue ties
        full.store.push_back(i % 31 - 15);
        full.date.push_back(i % 97 - 48);
    }
    full.cid[0] = INT64_MIN; full.cid[1] = INT64_MAX;
    full.pid[0] = INT64_MIN; full.pid[1] = INT64_MAX;
    full.store[0] = INT32_MIN; full.date[0] = INT32_MIN;
    Dims dims;
    for (const auto* op : {"OP04", "OP09", "OP10"}) {
        Batch chunk;
        auto naive = findOp(op)->mk(), tuned = findTunedOp(op)->mk();
        naive->consume(full, dims);
        // Tuned state must persist across uneven chunks, including an empty one.
        tuned->consume(chunk, dims);
        for (size_t lo = 0; lo < full.cid.size(); lo += 137) {
            size_t hi = std::min(lo + 137, full.cid.size());
            chunk.cid.assign(full.cid.begin() + lo, full.cid.begin() + hi);
            chunk.pid.assign(full.pid.begin() + lo, full.pid.begin() + hi);
            chunk.cents.assign(full.cents.begin() + lo, full.cents.begin() + hi);
            chunk.store.assign(full.store.begin() + lo, full.store.begin() + hi);
            chunk.date.assign(full.date.begin() + lo, full.date.begin() + hi);
            tuned->consume(chunk, dims);
        }
        auto a = naive->result(full, dims), b = tuned->result(full, dims);
        assert(a.size() == b.size());
        assert(digest(a) == digest(b));
    }
}
''')
    binary = tmp_path / "test"
    subprocess.run(["g++", "-std=c++20", "-O2", "-I", str(ROOT / "languages/cpp/src"),
                    str(source), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)


def test_java_primitive_sort(tmp_path):
    if not shutil.which("javac") or not shutil.which("java"):
        pytest.skip("JDK not installed")
    source = tmp_path / "TestPrimitiveSort.java"
    source.write_text(r'''
import java.util.*;
public class TestPrimitiveSort {
    public static void main(String[] args) {
        Random rng = new Random(123);
        for (int n : new int[]{0, 1, 2, 3, 7, 16, 31, 1025, 4097}) {
            for (int pattern = 0; pattern < 5; pattern++) {
                long[] ts = new long[n], id = new long[n];
                for (int i = 0; i < n; i++) {
                    ts[i] = switch (pattern) {
                        case 0 -> rng.nextInt(7) - 3; // tie-breaking
                        case 1 -> i;
                        case 2 -> n - i;
                        case 3 -> Long.MIN_VALUE;
                        default -> rng.nextLong();
                    };
                    id[i] = rng.nextLong();
                }
                if (n > 1) { id[0] = Long.MIN_VALUE; id[1] = Long.MAX_VALUE; }
                Integer[] want = new Integer[n];
                for (int i = 0; i < n; i++) want[i] = i;
                Arrays.sort(want, (a, b) -> {
                    int c = Long.compare(ts[a], ts[b]);
                    return c != 0 ? c : Long.compare(id[a], id[b]);
                });
                int[] got = PrimitiveSort.indexes(ts, id, n);
                for (int i = 0; i < n; i++) if (got[i] != want[i]) throw new AssertionError("order");
                if (n == 0) continue;
                Csv.Batch batch = new Csv.Batch(Csv.bit(Csv.TS) | Csv.bit(Csv.TID), n);
                batch.n = n; batch.ts = ts; batch.tid = id;
                Ops.Agg naive = new Ops.Op08(), tuned = new PrimitiveSort.Op08();
                naive.consume(batch); tuned.consume(batch);
                if (!Arrays.deepEquals(naive.result(batch), tuned.result(batch))) throw new AssertionError("result");
            }
        }
    }
}
''')
    sources = sorted((ROOT / "languages/java/src").glob("*.java"))
    subprocess.run(["javac", "-d", str(tmp_path), *map(str, sources), str(source)], check=True)
    subprocess.run(["java", "-cp", str(tmp_path), "TestPrimitiveSort"], check=True)
