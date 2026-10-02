import java.nio.charset.StandardCharsets;

/** Result digest of spec/checksum.md: splitmix mix64 + FNV-1a, order-insensitive over rows. Cells: Long, String, byte[] or null. */
final class Digest {
    static final long GOLDEN = 0x9E3779B97F4A7C15L, C1 = 0xBF58476D1CE4E5B9L, C2 = 0x94D049BB133111EBL;
    static final long NULL_CANON = 0xA5A5A5A5A5A5A5A5L, FNV_OFF = 0xCBF29CE484222325L, FNV_PRIME = 0x100000001B3L;

    static long mix64(long z) {
        z ^= z >>> 30;
        z *= C1;
        z ^= z >>> 27;
        z *= C2;
        z ^= z >>> 31;
        return z;
    }

    static long fnv1a(byte[] b) {
        long h = FNV_OFF;
        for (byte x : b) h = (h ^ (x & 0xFF)) * FNV_PRIME;
        return h;
    }

    static long canon(Object v) {
        if (v == null) return NULL_CANON;
        if (v instanceof Long l) return l;
        if (v instanceof byte[] b) return fnv1a(b);
        return fnv1a(((String) v).getBytes(StandardCharsets.UTF_8));
    }

    /** @return {checksum hex, row count} */
    static String digest(Object[][] rows) {
        long sum = 0, xor = 0;
        for (Object[] r : rows) {
            long h = 0;
            for (Object v : r) h = mix64(h + canon(v) + GOLDEN);
            sum += h;
            xor ^= h;
        }
        return String.format("%016x%016x", sum, xor);
    }
}
