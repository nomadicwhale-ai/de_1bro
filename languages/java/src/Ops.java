import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;

import static java.lang.Math.floorDiv;

/** The benchmark operations. Each Agg consumes columnar batches and finally yields the result rows. */
final class Ops {
    interface Agg {
        /** Load dimension tables (timed as load_ms). */
        default void load(String root, String label) throws IOException { }
        void consume(Csv.Batch b);
        Object[][] result(Csv.Batch b);
    }

    record Def(int need, java.util.function.Supplier<Agg> mk) { }

    static int bit(int c) { return Csv.bit(c); }

    static final Map<String, Def> OPS = new LinkedHashMap<>();
    static {
        OPS.put("OP01", new Def(bit(Csv.QTY) | bit(Csv.PRICE) | bit(Csv.RET), Op01::new));
        OPS.put("OP03", new Def(bit(Csv.QTY) | bit(Csv.PRICE) | bit(Csv.COUNTRY), Op03::new));
        OPS.put("OP04", new Def(bit(Csv.CID) | bit(Csv.PRICE), Op04::new));
        OPS.put("OP05", new Def(bit(Csv.COUNTRY) | bit(Csv.CATEGORY) | bit(Csv.DATE) | bit(Csv.PRICE), Op05::new));
        OPS.put("OP06", new Def(bit(Csv.CID) | bit(Csv.PRICE) | bit(Csv.QTY), Op06::new));
        OPS.put("OP07", new Def(bit(Csv.CID) | bit(Csv.PID) | bit(Csv.PRICE), Op07::new));
        OPS.put("OP08", new Def(bit(Csv.TID) | bit(Csv.TS), Op08::new));
        OPS.put("OP09", new Def(bit(Csv.CID) | bit(Csv.PRICE), Op09::new));
        OPS.put("OP10", new Def(bit(Csv.CID) | bit(Csv.PID) | bit(Csv.STORE) | bit(Csv.DATE), Op10::new));
        OPS.put("OP19", new Def(bit(Csv.QTY) | bit(Csv.COUNTRY), Op19::new));
        OPS.put("OP21", new Def(bit(Csv.PRICE), Op21::new));
        OPS.put("OP22", new Def(bit(Csv.TID) | bit(Csv.CID) | bit(Csv.PRICE) | bit(Csv.DATE) | bit(Csv.TS), Op22::new));
    }

    static Object optI(long v, boolean seen) { return seen ? (Object) v : null; }

    static Object dictVal(Csv.Dict d, int c) { return c < 0 ? null : d.strs[c]; }

    static long[] grow(long[] a, int n) { return n < a.length ? a : Arrays.copyOf(a, a.length * 2); }

    // ---- OP01 ----
    static final class Op01 implements Agg {
        long n, nq, sq, sp, mn, mx, cr;
        boolean started;

        public void consume(Csv.Batch b) {
            int n = b.n;
            long[] cents = b.cents;
            int[] qty = b.qty;
            boolean[] qnull = b.qnull, ret = b.ret;
            if (!started && n > 0) { mn = mx = cents[0]; started = true; }
            long mn = this.mn, mx = this.mx, sp = this.sp, nq = 0, sq = 0, cr = 0;
            for (int i = 0; i < n; i++) {
                long c = cents[i];
                if (!qnull[i]) { nq++; sq += qty[i]; }
                sp += c;
                if (c < mn) mn = c;
                if (c > mx) mx = c;
                if (ret[i]) cr++;
            }
            this.mn = mn; this.mx = mx; this.sp = sp;
            this.n += n; this.nq += nq; this.sq += sq; this.cr += cr;
        }

        public Object[][] result(Csv.Batch b) {
            return new Object[][]{{n, nq, optI(sq, nq > 0), sp, started ? (Object) mn : null, started ? (Object) mx : null, cr}};
        }
    }

    // ---- OP03 (slot = country code + 1; slot 0 = NULL) ----
    static final class Op03 implements Agg {
        long[] cnt = new long[0], sq = new long[0], sc = new long[0];
        boolean[] seenq = new boolean[0];

        public void consume(Csv.Batch b) {
            int need = b.countryD.n + 1;
            if (cnt.length < need) {
                cnt = Arrays.copyOf(cnt, need); sq = Arrays.copyOf(sq, need);
                sc = Arrays.copyOf(sc, need); seenq = Arrays.copyOf(seenq, need);
            }
            int n = b.n;
            long[] cents = b.cents;
            int[] country = b.country, qty = b.qty;
            boolean[] qnull = b.qnull;
            for (int i = 0; i < n; i++) {
                int g = country[i] + 1;
                cnt[g]++;
                sc[g] += cents[i];
                if (!qnull[i]) { sq[g] += qty[i]; seenq[g] = true; }
            }
        }

        public Object[][] result(Csv.Batch b) {
            List<Object[]> out = new ArrayList<>();
            for (int g = 0; g < cnt.length; g++) {
                if (cnt[g] == 0) continue;
                out.add(new Object[]{g > 0 ? b.countryD.strs[g - 1] : null, cnt[g], optI(sq[g], seenq[g]), sc[g]});
            }
            return out.toArray(new Object[0][]);
        }
    }

    // ---- OP04 ----
    static final class Op04 implements Agg {
        final LMap m = new LMap();
        long[] cnt = new long[1024], sum = new long[1024];

        public void consume(Csv.Batch b) {
            int n = b.n;
            long[] cid = b.cid, cents = b.cents;
            for (int i = 0; i < n; i++) {
                int g = m.getOrAdd(cid[i]);
                if (g >= cnt.length) { cnt = Arrays.copyOf(cnt, g * 2); sum = Arrays.copyOf(sum, g * 2); }
                cnt[g]++;
                sum[g] += cents[i];
            }
        }

        public Object[][] result(Csv.Batch b) {
            Object[][] out = new Object[m.size()][];
            for (int g = 0; g < out.length; g++) out[g] = new Object[]{m.dkeys[g], cnt[g], sum[g]};
            return out;
        }
    }

    // ---- OP05: key packed as (country+1) << 42 | (category+1) << 21 | (year + 2^20) ----
    static final class Op05 implements Agg {
        final LMap m = new LMap();
        long[] cnt = new long[256], sum = new long[256];

        public void consume(Csv.Batch b) {
            int n = b.n;
            long[] cents = b.cents;
            int[] country = b.country, category = b.category, date = b.date;
            for (int i = 0; i < n; i++) {
                long y = Csv.yearFromDays(date[i]);
                long k = ((long) (country[i] + 1) << 42) | ((long) (category[i] + 1) << 21) | (y + (1L << 20));
                int g = m.getOrAdd(k);
                if (g >= cnt.length) { cnt = Arrays.copyOf(cnt, g * 2); sum = Arrays.copyOf(sum, g * 2); }
                cnt[g]++;
                sum[g] += cents[i];
            }
        }

        public Object[][] result(Csv.Batch b) {
            Object[][] out = new Object[m.size()][];
            for (int g = 0; g < out.length; g++) {
                long k = m.dkeys[g];
                int co = (int) (k >>> 42) - 1, ca = (int) ((k >>> 21) & ((1 << 21) - 1)) - 1;
                long y = (k & ((1 << 21) - 1)) - (1L << 20);
                out[g] = new Object[]{dictVal(b.countryD, co), dictVal(b.categoryD, ca), y, cnt[g], sum[g]};
            }
            return out;
        }
    }

    // ---- dimension loading (first fields only; trailing quoted JSON fields are ignored) ----
    static final class Dim {
        final LMap ids = new LMap();
        int[] code = new int[1024]; // per dense id index: dictionary code of the attribute (-1 = NULL)
        final Csv.Dict dict = new Csv.Dict();

        Dim(String root, String table, String label, int attrField, String headerPrefix) throws IOException {
            List<Path> files = new ArrayList<>();
            try (var st = Files.list(Path.of(root, table, label))) {
                st.filter(p -> p.getFileName().toString().startsWith("part-") && p.getFileName().toString().endsWith(".csv"))
                        .sorted().forEach(files::add);
            }
            if (files.isEmpty()) throw new IOException("no CSV chunks for " + table);
            for (Path f : files) {
                Csv.readFile(f.toString());
                byte[] b = Csv.buf;
                int len = Csv.len, p = Csv.startsWith(b, len, headerPrefix) ? Csv.skipLine(b, 0, len) : 0;
                while (p < len) {
                    if (b[p] == '\n') { p++; continue; }
                    if (b[p] == '\r' && p + 1 < len && b[p + 1] == '\n') { p += 2; continue; }
                    long id = 0;
                    int c = -1;
                    for (int fl = 0; fl <= attrField; fl++) {
                        int s = p;
                        while (p < len && b[p] != ',' && b[p] != '\n') p++;
                        if (p >= len || b[p] != ',') throw new Csv.Bad("short dim row");
                        int e = p++;
                        if (fl == 0) id = Csv.parseInt(b, s, e);
                        else if (fl == attrField) {
                            // the attribute is followed by a comma in both dim tables
                            c = Csv.isNull(b, s, e) ? -1 : dict.code(b, s, e);
                        }
                    }
                    while (p < len && b[p] != '\n') p++;
                    if (p < len) p++;
                    int g = ids.getOrAdd(id);
                    if (g >= code.length) code = Arrays.copyOf(code, g * 2);
                    code[g] = c;
                }
            }
        }
    }

    // ---- OP06: hash join sales x dim_customer, group by segment (slot = code + 1) ----
    static final class Op06 implements Agg {
        Dim cust;
        long[] cnt, sum, sq;
        boolean[] seenq;

        public void load(String root, String label) throws IOException {
            cust = new Dim(root, "dim_customer", label, 4, "customer_id");
            int k = cust.dict.n + 1;
            cnt = new long[k]; sum = new long[k]; sq = new long[k]; seenq = new boolean[k];
        }

        public void consume(Csv.Batch b) {
            int n = b.n;
            long[] cid = b.cid, cents = b.cents;
            int[] qty = b.qty;
            boolean[] qnull = b.qnull;
            for (int i = 0; i < n; i++) {
                int ci = cust.ids.get(cid[i]);
                if (ci < 0) continue; // inner join
                int g = cust.code[ci] + 1;
                cnt[g]++;
                sum[g] += cents[i];
                if (!qnull[i]) { sq[g] += qty[i]; seenq[g] = true; }
            }
        }

        public Object[][] result(Csv.Batch b) {
            List<Object[]> out = new ArrayList<>();
            for (int g = 0; g < cnt.length; g++) {
                if (cnt[g] == 0) continue;
                out.add(new Object[]{g > 0 ? cust.dict.strs[g - 1] : null, cnt[g], sum[g], optI(sq[g], seenq[g])});
            }
            return out.toArray(new Object[0][]);
        }
    }

    // ---- OP07: star join, filter segment = 'enterprise', group by brand (slot = code + 1) ----
    static final class Op07 implements Agg {
        Dim cust, prod;
        int ent;
        long[] cnt, sum;

        public void load(String root, String label) throws IOException {
            cust = new Dim(root, "dim_customer", label, 4, "customer_id");
            prod = new Dim(root, "dim_product", label, 2, "product_id");
            byte[] e = "enterprise".getBytes(StandardCharsets.UTF_8);
            ent = cust.dict.code(e, 0, e.length);
            int k = prod.dict.n + 1;
            cnt = new long[k]; sum = new long[k];
        }

        public void consume(Csv.Batch b) {
            int n = b.n;
            long[] cid = b.cid, pid = b.pid, cents = b.cents;
            for (int i = 0; i < n; i++) {
                int ci = cust.ids.get(cid[i]);
                if (ci < 0 || cust.code[ci] != ent) continue;
                int pi = prod.ids.get(pid[i]);
                if (pi < 0) continue;
                int g = prod.code[pi] + 1;
                cnt[g]++;
                sum[g] += cents[i];
            }
        }

        public Object[][] result(Csv.Batch b) {
            List<Object[]> out = new ArrayList<>();
            for (int g = 0; g < cnt.length; g++) {
                if (cnt[g] == 0) continue;
                out.add(new Object[]{g > 0 ? prod.dict.strs[g - 1] : null, cnt[g], sum[g]});
            }
            return out.toArray(new Object[0][]);
        }
    }

    // ---- OP08: full sort by (ts, tid) with the standard library sort (Arrays.sort + Comparator on boxed indices) ----
    static final class Op08 implements Agg {
        long first, last, pos;

        public void consume(Csv.Batch b) {
            int n = b.n;
            final long[] ts = b.ts, tid = b.tid;
            Integer[] idx = new Integer[n];
            for (int i = 0; i < n; i++) idx[i] = i;
            Arrays.sort(idx, (x, y) -> {
                int c = Long.compare(ts[x], ts[y]);
                return c != 0 ? c : Long.compare(tid[x], tid[y]);
            });
            long s = 0;
            for (int i = 0; i < n; i++) s += (long) (i + 1) * tid[idx[i]];
            pos = s;
            first = tid[idx[0]];
            last = tid[idx[n - 1]];
        }

        public Object[][] result(Csv.Batch b) { return new Object[][]{{first, last, pos}}; }
    }

    // ---- OP09: top 100 customers by revenue (ties: smaller customer_id) ----
    static final class Op09 implements Agg {
        final LMap m = new LMap();
        long[] sum = new long[1024];

        public void consume(Csv.Batch b) {
            int n = b.n;
            long[] cid = b.cid, cents = b.cents;
            for (int i = 0; i < n; i++) {
                int g = m.getOrAdd(cid[i]);
                if (g >= sum.length) sum = Arrays.copyOf(sum, g * 2);
                sum[g] += cents[i];
            }
        }

        public Object[][] result(Csv.Batch b) {
            // heap keeps the 100 best; its head is the worst of them (smallest sum, then largest id)
            final long[] s = sum;
            final long[] k = m.dkeys;
            PriorityQueue<Integer> pq = new PriorityQueue<>(101, (x, y) -> {
                int c = Long.compare(s[x], s[y]);
                return c != 0 ? c : Long.compare(k[y], k[x]);
            });
            int g = m.size();
            for (int i = 0; i < g; i++) {
                if (pq.size() < 100) pq.add(i);
                else {
                    int w = pq.peek();
                    if (s[i] > s[w] || (s[i] == s[w] && k[i] < k[w])) { pq.poll(); pq.add(i); }
                }
            }
            Integer[] top = pq.toArray(new Integer[0]);
            Arrays.sort(top, (x, y) -> {
                int c = Long.compare(s[y], s[x]);
                return c != 0 ? c : Long.compare(k[x], k[y]);
            });
            Object[][] out = new Object[top.length][];
            for (int r = 0; r < top.length; r++) out[r] = new Object[]{(long) (r + 1), k[top[r]], s[top[r]]};
            return out;
        }
    }

    // ---- OP10 ----
    static final class Op10 implements Agg {
        final LMap c = new LMap(), p = new LMap(), sd = new LMap();

        public void consume(Csv.Batch b) {
            int n = b.n;
            long[] cid = b.cid, pid = b.pid;
            int[] store = b.store, date = b.date;
            for (int i = 0; i < n; i++) {
                c.getOrAdd(cid[i]);
                p.getOrAdd(pid[i]);
                sd.getOrAdd(((long) store[i] << 32) | (date[i] & 0xFFFFFFFFL));
            }
        }

        public Object[][] result(Csv.Batch b) {
            return new Object[][]{{(long) c.size(), (long) p.size(), (long) sd.size()}};
        }
    }

    // ---- OP19 ----
    static final class Op19 implements Agg {
        long nq, nc, sq, ne;
        boolean[] seen = new boolean[0], nonEmpty = new boolean[0];

        public void consume(Csv.Batch b) {
            Csv.Dict d = b.countryD;
            if (seen.length < d.n) {
                int old = seen.length;
                seen = Arrays.copyOf(seen, d.n);
                nonEmpty = Arrays.copyOf(nonEmpty, d.n);
                for (int i = old; i < d.n; i++) nonEmpty[i] = d.strs[i].length > 0;
            }
            int n = b.n;
            int[] country = b.country, qty = b.qty;
            boolean[] qnull = b.qnull;
            for (int i = 0; i < n; i++) {
                int c = country[i];
                if (qnull[i]) { nq++; sq++; } else sq += qty[i];
                if (c < 0) nc++;
                else {
                    seen[c] = true;
                    if (nonEmpty[c]) ne++;
                }
            }
        }

        public Object[][] result(Csv.Batch b) {
            long d = 0;
            for (boolean s : seen) if (s) d++;
            return new Object[][]{{nq, nc, sq, ne, d}};
        }
    }

    // ---- OP21 ----
    static final class Op21 implements Agg {
        long exact;
        double naive, ksum, comp;

        public void consume(Csv.Batch b) {
            long exact = this.exact;
            double naive = this.naive, ksum = this.ksum, comp = this.comp;
            long[] cents = b.cents;
            for (int i = 0, n = b.n; i < n; i++) {
                long c = cents[i];
                exact += c;
                double v = (double) c / 100.0;
                naive += v;
                double y = v - comp;
                double t = ksum + y;
                comp = (t - ksum) - y;
                ksum = t;
            }
            this.exact = exact; this.naive = naive; this.ksum = ksum; this.comp = comp;
        }

        public Object[][] result(Csv.Batch b) {
            long q = floorDiv(exact, 100L), r = exact - q * 100;
            String text = q + "." + (char) ('0' + r / 10) + (char) ('0' + r % 10);
            return new Object[][]{{exact, text}};
        }
    }

    // ---- OP22 ----
    static final class Op22 implements Agg {
        long a, bb, c, ymd;

        public void consume(Csv.Batch b) {
            long[] tid = b.tid, cid = b.cid, cents = b.cents, ts = b.ts;
            int[] date = b.date;
            long a = 0, bb = 0, c = 0, ymd = 0;
            for (int i = 0, n = b.n; i < n; i++) {
                long k = tid[i] * 4294967311L + cid[i];
                if ((long) (double) k != k) a++;
                double f = (double) cents[i] / 100.0;
                if ((long) (f * 100.0) != cents[i]) bb++;
                if ((ts[i] / 1000) * 1000 != ts[i]) c++;
                ymd += Csv.yyyymmdd(date[i]);
            }
            this.a += a; this.bb += bb; this.c += c; this.ymd += ymd;
        }

        public Object[][] result(Csv.Batch b) { return new Object[][]{{a, bb, c, ymd}}; }
    }
}
