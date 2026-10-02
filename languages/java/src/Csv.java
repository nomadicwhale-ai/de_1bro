import java.io.IOException;
import java.io.RandomAccessFile;
import java.util.Arrays;

/** Byte-level CSV parsing from byte[] into columnar batches. No String.split, no regex, no quote handling. */
final class Csv {
    static final int TID = 0, CID = 1, PID = 2, STORE = 3, QTY = 4, PRICE = 5, DISC = 6, TAX = 7, COUNTRY = 8,
            CATEGORY = 9, DATE = 10, TS = 11, RET = 12, NCOLS = 13;

    static int bit(int c) { return 1 << c; }

    static final class Bad extends RuntimeException {
        Bad(String m) { super(m); }
    }

    /** Reused file buffer (one chunk). */
    static byte[] buf = new byte[1 << 20];
    static int len;

    static void readFile(String path) throws IOException {
        try (RandomAccessFile f = new RandomAccessFile(path, "r")) {
            long sz = f.length();
            if (sz > Integer.MAX_VALUE - 16) throw new IOException("file too large: " + path);
            if (buf.length < sz) buf = new byte[(int) sz];
            f.readFully(buf, 0, (int) sz);
            len = (int) sz;
        }
    }

    /** Byte-string dictionary with FNV-1a hashing over the raw bytes (open addressing). */
    static final class Dict {
        byte[][] strs = new byte[64][];
        int n;
        private int[] tab = new int[256]; // code + 1
        private int[] hs = new int[64];
        private int mask = 255;

        int code(byte[] b, int s, int e) {
            long h = Digest.FNV_OFF;
            for (int i = s; i < e; i++) h = (h ^ (b[i] & 0xFF)) * Digest.FNV_PRIME;
            int hh = (int) (h ^ (h >>> 32));
            int i = hh & mask;
            while (true) {
                int v = tab[i];
                if (v == 0) break;
                byte[] k = strs[v - 1];
                if (hs[v - 1] == hh && k.length == e - s && Arrays.equals(k, 0, k.length, b, s, e)) return v - 1;
                i = (i + 1) & mask;
            }
            if (n == strs.length) {
                strs = Arrays.copyOf(strs, n * 2);
                hs = Arrays.copyOf(hs, n * 2);
            }
            strs[n] = Arrays.copyOfRange(b, s, e);
            hs[n] = hh;
            tab[i] = ++n;
            if (n * 2 > mask) {
                int c = (mask + 1) << 1;
                int[] nt = new int[c];
                int m = c - 1;
                for (int j = 0; j < n; j++) {
                    int p = hs[j] & m;
                    while (nt[p] != 0) p = (p + 1) & m;
                    nt[p] = j + 1;
                }
                tab = nt;
                mask = m;
            }
            return n - 1;
        }
    }

    /** Columnar block of parsed rows; only the columns in `need` are allocated/filled. */
    static final class Batch {
        int n, cap;
        final int need;
        long[] tid, cid, pid, cents, ts;
        int[] store, qty, country, category, date; // qty NULL = Integer.MIN_VALUE sentinel avoided: see qnull
        boolean[] qnull, ret;
        final Dict countryD = new Dict(), categoryD = new Dict();

        Batch(int need, int cap) {
            this.need = need;
            alloc(cap);
        }

        private void alloc(int c) {
            cap = c;
            if ((need & bit(TID)) != 0) tid = tid == null ? new long[c] : Arrays.copyOf(tid, c);
            if ((need & bit(CID)) != 0) cid = cid == null ? new long[c] : Arrays.copyOf(cid, c);
            if ((need & bit(PID)) != 0) pid = pid == null ? new long[c] : Arrays.copyOf(pid, c);
            if ((need & bit(STORE)) != 0) store = store == null ? new int[c] : Arrays.copyOf(store, c);
            if ((need & bit(QTY)) != 0) {
                qty = qty == null ? new int[c] : Arrays.copyOf(qty, c);
                qnull = qnull == null ? new boolean[c] : Arrays.copyOf(qnull, c);
            }
            if ((need & bit(PRICE)) != 0) cents = cents == null ? new long[c] : Arrays.copyOf(cents, c);
            if ((need & bit(COUNTRY)) != 0) country = country == null ? new int[c] : Arrays.copyOf(country, c);
            if ((need & bit(CATEGORY)) != 0) category = category == null ? new int[c] : Arrays.copyOf(category, c);
            if ((need & bit(DATE)) != 0) date = date == null ? new int[c] : Arrays.copyOf(date, c);
            if ((need & bit(TS)) != 0) ts = ts == null ? new long[c] : Arrays.copyOf(ts, c);
            if ((need & bit(RET)) != 0) ret = ret == null ? new boolean[c] : Arrays.copyOf(ret, c);
        }

        void grow() { alloc(Math.max(1024, cap * 2)); }

        /** Drop rows, keep buffers and dictionaries (streaming). */
        void reset() { n = 0; }
    }

    // ---------- field parsers over [s,e) ----------

    static boolean isNull(byte[] b, int s, int e) { return e - s == 2 && b[s] == '\\' && b[s + 1] == 'N'; }

    static long parseInt(byte[] b, int s, int e) {
        int i = s;
        boolean neg = false;
        if (i < e && (b[i] == '-' || b[i] == '+')) { neg = b[i] == '-'; i++; }
        if (i >= e) throw new Bad("bad int");
        long v = 0;
        for (; i < e; i++) {
            int d = b[i] - '0';
            if (d < 0 || d > 9) throw new Bad("bad int");
            v = v * 10 + d;
        }
        return neg ? -v : v;
    }

    /** Decimal text -> int64 cents without floating point (extra decimals truncated). */
    static long parseCents(byte[] b, int s, int e) {
        int i = s;
        boolean neg = false;
        if (i < e && (b[i] == '-' || b[i] == '+')) { neg = b[i] == '-'; i++; }
        if (i >= e) throw new Bad("bad decimal");
        long ip = 0;
        int nd = 0;
        for (; i < e && b[i] != '.'; i++) {
            int d = b[i] - '0';
            if (d < 0 || d > 9) throw new Bad("bad decimal");
            ip = ip * 10 + d;
            nd++;
        }
        long frac = 0;
        int fd = 0;
        if (i < e) {
            for (i++; i < e; i++) {
                int d = b[i] - '0';
                if (d < 0 || d > 9) throw new Bad("bad decimal");
                if (fd < 2) { frac = frac * 10 + d; fd++; }
                nd++;
            }
        }
        if (nd == 0) throw new Bad("bad decimal");
        for (; fd < 2; fd++) frac *= 10;
        long v = ip * 100 + frac;
        return neg ? -v : v;
    }

    static long daysFromCivil(long y, long m, long d) {
        if (m <= 2) y--;
        long era = Math.floorDiv(y, 400L);
        long yoe = y - era * 400;
        long mp = m > 2 ? m - 3 : m + 9;
        long doy = (153 * mp + 2) / 5 + d - 1;
        long doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
        return era * 146097 + doe - 719468;
    }

    /** Hinnant civil_from_days; returns the year only. */
    static long yearFromDays(long z) {
        z += 719468;
        long era = Math.floorDiv(z, 146097L);
        long doe = z - era * 146097;
        long yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
        long y = yoe + era * 400;
        long doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
        long mp = (5 * doy + 2) / 153;
        return mp < 10 ? y : y + 1;
    }

    /** Full civil_from_days; returns y*10000 + m*100 + d. */
    static long yyyymmdd(long z) {
        z += 719468;
        long era = Math.floorDiv(z, 146097L);
        long doe = z - era * 146097;
        long yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
        long y = yoe + era * 400;
        long doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
        long mp = (5 * doy + 2) / 153;
        long d = doy - (153 * mp + 2) / 5 + 1;
        long m = mp < 10 ? mp + 3 : mp - 9;
        if (m <= 2) y++;
        return y * 10000 + m * 100 + d;
    }

    /** YYYY-MM-DD -> days since epoch. */
    static long parseDate(byte[] b, int s, int e) {
        long[] parts = new long[3]; // tiny, escape-analysed by the JIT
        int p = 0, nd = 0;
        long v = 0;
        boolean neg = false;
        for (int i = s; i < e; i++) {
            int c = b[i];
            if (c == '-' && i == s) { neg = true; continue; }
            if (c == '-') {
                if (nd == 0 || p >= 2) throw new Bad("bad date");
                parts[p++] = v;
                v = 0;
                nd = 0;
                continue;
            }
            int d = c - '0';
            if (d < 0 || d > 9) throw new Bad("bad date");
            v = v * 10 + d;
            nd++;
        }
        if (p != 2 || nd == 0) throw new Bad("bad date");
        parts[2] = v;
        if (neg) parts[0] = -parts[0];
        return daysFromCivil(parts[0], parts[1], parts[2]);
    }

    private static int two(byte[] b, int i) {
        int x = b[i] - '0', y = b[i + 1] - '0';
        if (x < 0 || x > 9 || y < 0 || y > 9) throw new Bad("bad time");
        return x * 10 + y;
    }

    /** "YYYY-MM-DD HH:MM:SS[.ffffff]" -> microseconds since epoch. */
    static long parseTS(byte[] b, int s, int e) {
        int sp = s;
        while (sp < e && b[sp] != ' ' && b[sp] != 'T') sp++;
        if (sp >= e) throw new Bad("bad timestamp");
        long days = parseDate(b, s, sp);
        int t = sp + 1;
        if (e - t < 8 || b[t + 2] != ':' || b[t + 5] != ':') throw new Bad("bad timestamp");
        long h = two(b, t), mi = two(b, t + 3), sec = two(b, t + 6);
        long frac = 0;
        if (e - t > 8) {
            if (b[t + 8] != '.') throw new Bad("bad timestamp");
            int n = 0;
            for (int i = t + 9; i < e; i++) {
                int d = b[i] - '0';
                if (d < 0 || d > 9) throw new Bad("bad timestamp");
                if (n < 6) { frac = frac * 10 + d; n++; }
            }
            for (; n < 6; n++) frac *= 10;
        }
        return (days * 86400 + h * 3600 + mi * 60 + sec) * 1000000 + frac;
    }

    static int skipLine(byte[] b, int p, int len) {
        while (p < len && b[p] != '\n') p++;
        return p < len ? p + 1 : p;
    }

    static boolean startsWith(byte[] b, int len, String pre) {
        if (len < pre.length()) return false;
        for (int i = 0; i < pre.length(); i++) if (b[i] != pre.charAt(i)) return false;
        return true;
    }

    /** Parses buf[0,len) (one sales_fact chunk), appending the needed columns of every row to bt. */
    static void parseChunk(byte[] b, int len, Batch bt) {
        final int need = bt.need;
        int last = 0;
        for (int c = 0; c < NCOLS; c++) if ((need & bit(c)) != 0) last = c;
        int p = startsWith(b, len, "transaction_id") ? skipLine(b, 0, len) : 0;
        while (p < len) {
            int c0 = b[p];
            if (c0 == '\n') { p++; continue; }
            if (c0 == '\r' && p + 1 < len && b[p + 1] == '\n') { p += 2; continue; }
            if (bt.n == bt.cap) bt.grow();
            final int n = bt.n;
            for (int f = 0; f <= last; f++) {
                final int s = p;
                int e;
                if (f == NCOLS - 1) {
                    while (p < len && b[p] != '\n') p++;
                    e = p;
                    if (e > s && b[e - 1] == '\r') e--;
                } else {
                    byte c;
                    while (p < len && (c = b[p]) != ',') {
                        if (c == '\n') throw new Bad("short row");
                        p++;
                    }
                    if (p >= len) throw new Bad("short row");
                    e = p++;
                }
                if ((need & (1 << f)) == 0) continue;
                switch (f) {
                    case TID -> bt.tid[n] = parseInt(b, s, e);
                    case CID -> bt.cid[n] = parseInt(b, s, e);
                    case PID -> bt.pid[n] = parseInt(b, s, e);
                    case STORE -> bt.store[n] = (int) parseInt(b, s, e);
                    case QTY -> {
                        if (isNull(b, s, e)) { bt.qty[n] = 0; bt.qnull[n] = true; }
                        else { bt.qty[n] = (int) parseInt(b, s, e); bt.qnull[n] = false; }
                    }
                    case PRICE -> bt.cents[n] = parseCents(b, s, e);
                    case COUNTRY -> bt.country[n] = isNull(b, s, e) ? -1 : bt.countryD.code(b, s, e);
                    case CATEGORY -> bt.category[n] = isNull(b, s, e) ? -1 : bt.categoryD.code(b, s, e);
                    case DATE -> bt.date[n] = (int) parseDate(b, s, e);
                    case TS -> bt.ts[n] = parseTS(b, s, e);
                    case RET -> bt.ret[n] = e > s && b[s] == 't';
                    default -> { }
                }
            }
            if (last < NCOLS - 1) while (p < len && b[p] != '\n') p++;
            if (p < len) p++;
            bt.n = n + 1;
        }
    }

    // ---------- OP15: parse every column and summarise ----------

    static final class Op15 {
        long rows, tid, cid, pid, store, qty, nq, cents, disc, tax, cb, nc, gb, days, sec, frac, ret;
        private final int[] fs = new int[NCOLS], fe = new int[NCOLS];

        static long floorE6(double x) {
            double y = x * 1e6 + 0.5; // Java float arithmetic is strict IEEE: no fused multiply-add
            return (long) Math.floor(y);
        }

        private static double parseDouble(byte[] b, int s, int e) {
            try {
                return Double.parseDouble(new String(b, s, e - s, java.nio.charset.StandardCharsets.ISO_8859_1));
            } catch (NumberFormatException x) {
                throw new Bad("bad float");
            }
        }

        void chunk(byte[] b, int len) {
            int p = startsWith(b, len, "transaction_id") ? skipLine(b, 0, len) : 0;
            while (p < len) {
                int c0 = b[p];
                if (c0 == '\n') { p++; continue; }
                if (c0 == '\r' && p + 1 < len && b[p + 1] == '\n') { p += 2; continue; }
                for (int f = 0; f < NCOLS; f++) {
                    fs[f] = p;
                    if (f == NCOLS - 1) {
                        while (p < len && b[p] != '\n') p++;
                        int e = p;
                        if (e > fs[f] && b[e - 1] == '\r') e--;
                        fe[f] = e;
                    } else {
                        byte c;
                        while (p < len && (c = b[p]) != ',') {
                            if (c == '\n') throw new Bad("short row");
                            p++;
                        }
                        if (p >= len) throw new Bad("short row");
                        fe[f] = p++;
                    }
                }
                if (p < len) p++;
                rows++;
                tid += parseInt(b, fs[TID], fe[TID]);
                cid += parseInt(b, fs[CID], fe[CID]);
                pid += parseInt(b, fs[PID], fe[PID]);
                store += parseInt(b, fs[STORE], fe[STORE]);
                if (isNull(b, fs[QTY], fe[QTY])) nq++; else qty += parseInt(b, fs[QTY], fe[QTY]);
                cents += parseCents(b, fs[PRICE], fe[PRICE]);
                disc += floorE6(parseDouble(b, fs[DISC], fe[DISC]));
                tax += floorE6(parseDouble(b, fs[TAX], fe[TAX]));
                if (isNull(b, fs[COUNTRY], fe[COUNTRY])) nc++; else cb += fe[COUNTRY] - fs[COUNTRY];
                if (!isNull(b, fs[CATEGORY], fe[CATEGORY])) gb += fe[CATEGORY] - fs[CATEGORY];
                days += parseDate(b, fs[DATE], fe[DATE]);
                long us = parseTS(b, fs[TS], fe[TS]);
                long q = Math.floorDiv(us, 1000000L);
                sec += q;
                frac += us - q * 1000000L;
                if (fe[RET] > fs[RET] && b[fs[RET]] == 't') ret++;
            }
        }
    }
}
