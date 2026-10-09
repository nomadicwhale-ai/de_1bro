/** Dependency-free lexicographic merge sort of primitive row indexes (no boxed keys). */
final class PrimitiveSort {
    private PrimitiveSort() { }

    static int[] indexes(long[] ts, long[] tid, int n) {
        int[] src = new int[n], dst = new int[n];
        for (int i = 0; i < n; i++) src[i] = i;
        // long widths avoid overflow when doubling near the maximum Java array length.
        for (long width = 1; width < n; width *= 2) {
            for (long start = 0; start < n; start += width * 2) {
                int lo = (int) start, mid = (int) Math.min(start + width, n);
                int hi = (int) Math.min(start + width * 2, n);
                int a = lo, b = mid;
                for (int out = lo; out < hi; out++) {
                    if (a < mid && (b == hi || compare(src[a], src[b], ts, tid) <= 0)) dst[out] = src[a++];
                    else dst[out] = src[b++];
                }
            }
            int[] swap = src; src = dst; dst = swap;
        }
        return src;
    }

    private static int compare(int a, int b, long[] ts, long[] tid) {
        int c = Long.compare(ts[a], ts[b]);
        return c != 0 ? c : Long.compare(tid[a], tid[b]);
    }

    static final class Op08 implements Ops.Agg {
        long first, last, pos;
        public void consume(Csv.Batch b) {
            int[] idx = indexes(b.ts, b.tid, b.n);
            long sum = 0;
            for (int i = 0; i < b.n; i++) sum += (long) (i + 1) * b.tid[idx[i]];
            first = b.tid[idx[0]];
            last = b.tid[idx[b.n - 1]];
            pos = sum; // Java long arithmetic wraps modulo 2^64.
        }
        public Object[][] result(Csv.Batch b) { return new Object[][]{{first, last, pos}}; }
    }
}
