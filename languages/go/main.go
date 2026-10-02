// Track L Go stdlib-only benchmark implementation.
package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"
)

func sizeLabel(rows int64) string {
	switch {
	case rows >= 1_000_000_000 && rows%1_000_000_000 == 0:
		return fmt.Sprintf("%db", rows/1_000_000_000)
	case rows >= 1_000_000 && rows%1_000_000 == 0:
		return fmt.Sprintf("%dm", rows/1_000_000)
	case rows >= 1000 && rows%1000 == 0:
		return fmt.Sprintf("%dk", rows/1000)
	}
	return fmt.Sprint(rows)
}

func ms(d time.Duration) float64 { return float64(d.Nanoseconds()) / 1e6 }

func fail(err error) {
	fmt.Fprintln(os.Stderr, "error:", err)
	os.Exit(1)
}

func main() {
	op := flag.String("op", "", "operation")
	dataset := flag.String("dataset", "A", "dataset")
	rows := flag.Int64("rows", 0, "rows")
	mode := flag.String("mode", "streaming", "streaming|materialized")
	_ = flag.Int64("chunk-rows", 1000000, "chunk rows (streaming uses the chunk files)")
	threads := flag.Int("threads", 1, "threads (the algorithm is single-goroutine)")
	input := flag.String("input", "data", "data root")
	_ = flag.Bool("output-json", true, "")
	flag.Parse()
	_ = threads
	if *dataset != "A" {
		fail(fmt.Errorf("only dataset A supported"))
	}
	dir := filepath.Join(*input, "sales_fact", sizeLabel(*rows))
	files, err := filepath.Glob(filepath.Join(dir, "part-*.csv"))
	if err != nil || len(files) == 0 {
		fail(fmt.Errorf("no CSV chunks in %s", dir))
	}
	sort.Strings(files)

	var loadD, compD time.Duration
	var result [][]Val
	var floats map[string]float64
	var buf []byte

	if *op == "OP15" {
		var st op15State
		t0 := time.Now()
		for _, f := range files {
			if buf, err = readFile(f, buf); err != nil {
				fail(err)
			}
			if err = st.chunk(buf); err != nil {
				fail(fmt.Errorf("%s: %w", f, err))
			}
		}
		result = [][]Val{{I(st.rows), I(st.tid), I(st.cid), I(st.pid), I(st.store), I(st.qty), I(st.nq),
			I(st.cents), I(st.disc), I(st.tax), I(st.cb), I(st.nc), I(st.gb), I(st.days), I(st.sec),
			I(st.frac), I(st.ret)}}
		compD = time.Since(t0)
	} else {
		def, ok := ops[*op]
		if !ok {
			fail(fmt.Errorf("unsupported op %q", *op))
		}
		agg := def.mk()
		var b *Batch
		switch *mode {
		case "streaming":
			b = newBatch(def.need, 0)
			for _, f := range files {
				t0 := time.Now()
				if buf, err = readFile(f, buf); err != nil {
					fail(err)
				}
				b.reset()
				if err = parseChunk(buf, def.need, b); err != nil {
					fail(fmt.Errorf("%s: %w", f, err))
				}
				t1 := time.Now()
				agg.Consume(b)
				t2 := time.Now()
				loadD += t1.Sub(t0)
				compD += t2.Sub(t1)
			}
			t := time.Now()
			result = agg.Result(b)
			compD += time.Since(t)
		case "materialized":
			t0 := time.Now()
			b = newBatch(def.need, int(*rows))
			for _, f := range files {
				if buf, err = readFile(f, buf); err != nil {
					fail(err)
				}
				if err = parseChunk(buf, def.need, b); err != nil {
					fail(fmt.Errorf("%s: %w", f, err))
				}
			}
			buf = nil
			loadD = time.Since(t0)
			t1 := time.Now()
			agg.Consume(b)
			result = agg.Result(b)
			compD = time.Since(t1)
		default:
			fail(fmt.Errorf("bad mode %q", *mode))
		}
		if a, ok := agg.(*op21); ok {
			floats = map[string]float64{"naive_sum": a.naive, "kahan_sum": a.ksum}
		}
	}

	sum, n := digest(result)
	var fl string
	if floats != nil {
		fl = fmt.Sprintf(`,"floats":{"naive_sum":%s,"kahan_sum":%s}`, ftoa(floats["naive_sum"]), ftoa(floats["kahan_sum"]))
	}
	fmt.Printf(`{"load_ms":%.3f,"compute_ms":%.3f,"checksum":"%s","row_count":%d%s,"toolchain":{"name":"go","version":"%s","flags":"-trimpath"},"notes":"GOMAXPROCS=%d"}`+"\n",
		ms(loadD), ms(compD), sum, n, fl, strings.TrimPrefix(runtime.Version(), "go"), runtime.GOMAXPROCS(0))
}

func ftoa(f float64) string { return fmt.Sprintf("%.17g", f) }
