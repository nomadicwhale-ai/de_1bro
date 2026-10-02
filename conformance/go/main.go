// Conformance probe (Go, standard library only).
package main

import (
	"fmt"
	"math"
	"runtime"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf16"
	"unicode/utf8"
	"unsafe"
)

func kv(k, v string) { fmt.Printf("%s=%s\n", k, v) }

func fmt17(x float64) string {
	if math.IsNaN(x) {
		return "nan"
	}
	if math.IsInf(x, 1) {
		return "inf"
	}
	if math.IsInf(x, -1) {
		return "-inf"
	}
	return strconv.FormatFloat(x, 'g', 17, 64)
}

func probe(k string, f func() string) {
	defer func() {
		if r := recover(); r != nil {
			kv(k, "panic")
		}
	}()
	kv(k, f())
}

func strprobe(prefix, s string) {
	kv(prefix+"_utf8", strconv.Itoa(len(s)))
	kv(prefix+"_utf16", strconv.Itoa(len(utf16.Encode([]rune(s)))))
	kv(prefix+"_scalars", strconv.Itoa(utf8.RuneCountInString(s)))
}

func main() {
	kv("lang", "go")
	kv("version", runtime.Version())
	var i8 int8
	var i16 int16
	var i32 int32
	var i64 int64
	var u8 uint8
	var u16 uint16
	var u32 uint32
	var u64 uint64
	var f32 float32
	var f64 float64
	var b bool
	var r rune
	kv("size_int8", strconv.Itoa(int(unsafe.Sizeof(i8))))
	kv("size_int16", strconv.Itoa(int(unsafe.Sizeof(i16))))
	kv("size_int32", strconv.Itoa(int(unsafe.Sizeof(i32))))
	kv("size_int64", strconv.Itoa(int(unsafe.Sizeof(i64))))
	kv("size_uint8", strconv.Itoa(int(unsafe.Sizeof(u8))))
	kv("size_uint16", strconv.Itoa(int(unsafe.Sizeof(u16))))
	kv("size_uint32", strconv.Itoa(int(unsafe.Sizeof(u32))))
	kv("size_uint64", strconv.Itoa(int(unsafe.Sizeof(u64))))
	kv("size_float32", strconv.Itoa(int(unsafe.Sizeof(f32))))
	kv("size_float64", strconv.Itoa(int(unsafe.Sizeof(f64))))
	kv("size_bool", strconv.Itoa(int(unsafe.Sizeof(b))))
	kv("size_char", strconv.Itoa(int(unsafe.Sizeof(r))))
	kv("char_meaning", "no char type; rune is an alias of int32 holding a Unicode code point, byte is an alias of uint8")

	probe("int32_max_plus_1", func() string { x := int32(math.MaxInt32); x++; return strconv.Itoa(int(x)) })
	probe("int64_max_plus_1", func() string { x := int64(math.MaxInt64); x++; return strconv.FormatInt(x, 10) })
	probe("uint8_255_plus_1", func() string { x := uint8(255); x++; return strconv.Itoa(int(x)) })
	probe("uint32_0_minus_1", func() string { x := uint32(0); x--; return strconv.FormatUint(uint64(x), 10) })
	n7, two, zero := -7, 2, 0
	probe("int_div_m7_2", func() string { return strconv.Itoa(n7 / two) })
	probe("int_mod_m7_2", func() string { return strconv.Itoa(n7 % two) })
	probe("int_div_by_zero", func() string { return strconv.Itoa(1 / zero) })
	a, bb := 0.1, 0.2
	probe("f64_0_1_plus_0_2", func() string { return fmt17(a + bb) })
	probe("f32_16777217_roundtrip", func() string { i := int32(16777217); return fmt17(float64(float32(i))) })
	probe("f64_2p53_plus_1", func() string { x := float64(1 << 53); return fmt17(x + 1) })
	probe("f64_nan_eq_nan", func() string { n := math.NaN(); return strconv.FormatBool(n == n) })
	fz, fo := 0.0, 1.0
	probe("f64_1_div_0", func() string { return fmt17(fo / fz) })
	probe("f64_neg1_div_0", func() string { return fmt17(-fo / fz) })
	probe("f64_0_div_0", func() string { return fmt17(fz / fz) })
	probe("i64_2p53p1_via_f64", func() string { i := int64(9007199254740993); return strconv.FormatInt(int64(float64(i)), 10) })
	strprobe("str_e_pre", "é")
	strprobe("str_e_comb", "é")
	strprobe("str_emoji", "\U0001F600")
	probe("date_epoch_day_2015_01_01", func() string {
		return strconv.FormatInt(time.Date(2015, 1, 1, 0, 0, 0, 0, time.UTC).Unix()/86400, 10)
	})
	kv("timestamp_max_precision", "ns")
	probe("empty_array_index0", func() string { var s []int; return strconv.Itoa(s[0]) })
	probe("empty_array_max", func() string { var s []int; return strconv.Itoa(slices.Max(s)) })
	probe("empty_string_index0", func() string { s := ""; return strconv.Itoa(int(s[0])) })
	probe("empty_string_split_count", func() string { return strconv.Itoa(len(strings.Split("", ","))) })
	orders := map[string]bool{}
	for i := 0; i < 200; i++ {
		m := map[int]int{}
		m[3], m[1], m[2] = 0, 0, 0
		var ks []string
		for k := range m {
			ks = append(ks, strconv.Itoa(k))
		}
		orders[strings.Join(ks, ",")] = true
	}
	if len(orders) > 1 {
		kv("map_order_3_1_2", "randomized")
	} else {
		var o []string
		for k := range orders {
			o = append(o, k)
		}
		sort.Strings(o)
		kv("map_order_3_1_2", o[0])
	}
	kv("decimal_0_1_plus_0_2", "n/a")
	s := 0.0
	for i := 0; i < 10000000; i++ {
		s += a
	}
	kv("f64_sum_10m_0_1", fmt17(s))
}
