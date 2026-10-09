import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/** Track L Java 21 stdlib-only benchmark implementation. */
public final class Bench {
    static String sizeLabel(long rows) {
        if (rows >= 1_000_000_000L && rows % 1_000_000_000L == 0) return (rows / 1_000_000_000L) + "b";
        if (rows >= 1_000_000L && rows % 1_000_000L == 0) return (rows / 1_000_000L) + "m";
        if (rows >= 1000 && rows % 1000 == 0) return (rows / 1000) + "k";
        return Long.toString(rows);
    }

    static void fail(String msg) {
        System.err.println("error: " + msg);
        System.exit(1);
    }

    static double ms(long ns) { return ns / 1e6; }

    public static void main(String[] args) throws Exception {
        String op = "", dataset = "A", mode = "streaming", input = "data", variant = "stdlib";
        long rows = 0;
        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--op" -> op = args[++i];
                case "--dataset" -> dataset = args[++i];
                case "--rows" -> rows = Long.parseLong(args[++i]);
                case "--mode" -> mode = args[++i];
                case "--input" -> input = args[++i];
                case "--variant" -> variant = args[++i];
                case "--chunk-rows", "--threads" -> i++;
                default -> { }
            }
        }
        if (!dataset.equals("A")) fail("only dataset A supported");
        if (!variant.equals("stdlib") && !variant.equals("tuned")) fail("bad variant " + variant);
        if (variant.equals("tuned") && !op.equals("OP08")) fail("unsupported tuned op " + op);
        String label = sizeLabel(rows);
        List<String> files = new ArrayList<>();
        try (var st = Files.list(Path.of(input, "sales_fact", label))) {
            st.filter(p -> p.getFileName().toString().startsWith("part-") && p.getFileName().toString().endsWith(".csv"))
                    .map(Path::toString).sorted().forEach(files::add);
        } catch (java.io.IOException e) {
            fail("no CSV chunks in " + input + "/sales_fact/" + label);
        }
        if (files.isEmpty()) fail("no CSV chunks");

        long loadNs = 0, compNs = 0;
        Object[][] result;
        double[] floats = null;

        if (op.equals("OP15")) {
            Csv.Op15 st = new Csv.Op15();
            long t0 = System.nanoTime();
            for (String f : files) {
                Csv.readFile(f);
                st.chunk(Csv.buf, Csv.len);
            }
            result = new Object[][]{{st.rows, st.tid, st.cid, st.pid, st.store, st.qty, st.nq, st.cents, st.disc, st.tax,
                    st.cb, st.nc, st.gb, st.days, st.sec, st.frac, st.ret}};
            compNs = System.nanoTime() - t0;
        } else {
            Ops.Def def = Ops.OPS.get(op);
            if (def == null) { fail("unsupported op " + op); return; }
            Ops.Agg agg = variant.equals("tuned") ? new PrimitiveSort.Op08() : def.mk().get();
            Csv.Batch b;
            if (mode.equals("streaming")) {
                if (op.equals("OP08")) { fail("OP08 is materialized only"); return; }
                long t0 = System.nanoTime();
                agg.load(input, label);
                loadNs += System.nanoTime() - t0;
                b = new Csv.Batch(def.need(), 1 << 16);
                for (String f : files) {
                    long a = System.nanoTime();
                    Csv.readFile(f);
                    b.reset();
                    Csv.parseChunk(Csv.buf, Csv.len, b);
                    long m = System.nanoTime();
                    agg.consume(b);
                    long z = System.nanoTime();
                    loadNs += m - a;
                    compNs += z - m;
                }
                long t = System.nanoTime();
                result = agg.result(b);
                compNs += System.nanoTime() - t;
            } else if (mode.equals("materialized")) {
                long t0 = System.nanoTime();
                agg.load(input, label);
                b = new Csv.Batch(def.need(), (int) Math.max(rows, 1024));
                for (String f : files) {
                    Csv.readFile(f);
                    Csv.parseChunk(Csv.buf, Csv.len, b);
                }
                Csv.buf = new byte[0]; // drop the file buffer before compute
                loadNs = System.nanoTime() - t0;
                long t1 = System.nanoTime();
                agg.consume(b);
                result = agg.result(b);
                compNs = System.nanoTime() - t1;
            } else {
                fail("bad mode " + mode);
                return;
            }
            if (agg instanceof Ops.Op21 a) floats = new double[]{a.naive, a.ksum};
        }

        String sum = Digest.digest(result);
        String fl = floats == null ? "" : ",\"floats\":{\"naive_sum\":" + floats[0] + ",\"kahan_sum\":" + floats[1] + "}";
        System.out.println(String.format("{\"load_ms\":%.3f,\"compute_ms\":%.3f,\"checksum\":\"%s\",\"row_count\":%d%s,"
                        + "\"toolchain\":{\"name\":\"java\",\"version\":\"%s\",\"flags\":\"-Xmx6g -XX:+UseSerialGC\"},\"notes\":\"\"}",
                ms(loadNs), ms(compNs), sum, result.length, fl, System.getProperty("java.version")));
    }
}
