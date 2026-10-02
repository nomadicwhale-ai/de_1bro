/**
 * Open-addressing (linear probing) long -> dense int index map. getOrAdd assigns indices 0,1,2.. in insertion
 * order; keys are kept in dkeys[]. Also used as a plain long set (size()).
 */
final class LMap {
    private long[] tk;
    private int[] tv; // index + 1, 0 = empty
    private int mask, size;
    long[] dkeys = new long[16];

    LMap() { this(1 << 12); }

    LMap(int cap) {
        int c = 16;
        while (c < cap) c <<= 1;
        tk = new long[c];
        tv = new int[c];
        mask = c - 1;
    }

    int size() { return size; }

    int get(long key) {
        int i = (int) Digest.mix64(key) & mask;
        while (true) {
            int v = tv[i];
            if (v == 0) return -1;
            if (tk[i] == key) return v - 1;
            i = (i + 1) & mask;
        }
    }

    int getOrAdd(long key) {
        int i = (int) Digest.mix64(key) & mask;
        while (true) {
            int v = tv[i];
            if (v == 0) break;
            if (tk[i] == key) return v - 1;
            i = (i + 1) & mask;
        }
        if (size == dkeys.length) dkeys = java.util.Arrays.copyOf(dkeys, size * 2);
        dkeys[size] = key;
        tk[i] = key;
        tv[i] = ++size;
        if (size * 2 > mask) grow();
        return size - 1;
    }

    private void grow() {
        int c = (mask + 1) << 1;
        long[] nk = new long[c];
        int[] nv = new int[c];
        int m = c - 1;
        for (int j = 0; j <= mask; j++) {
            int v = tv[j];
            if (v == 0) continue;
            int i = (int) Digest.mix64(tk[j]) & m;
            while (nv[i] != 0) i = (i + 1) & m;
            nk[i] = tk[j];
            nv[i] = v;
        }
        tk = nk;
        tv = nv;
        mask = m;
    }
}
