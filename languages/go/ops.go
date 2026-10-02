package main

import (
	"cmp"
	"slices"
)

// Agg consumes columnar batches and finally yields the result rows.
type Agg interface {
	Consume(b *Batch)
	Result(b *Batch) [][]Val
}

type opDef struct {
	need uint32
	mk   func() Agg
}

var ops = map[string]opDef{
	"OP01": {bit(cQTY) | bit(cPRICE) | bit(cRET), func() Agg { return &op01{} }},
	"OP03": {bit(cQTY) | bit(cPRICE) | bit(cCOUNTRY), func() Agg { return &op03{} }},
	"OP04": {bit(cCID) | bit(cPRICE), func() Agg { return &op04{m: map[int64]int32{}} }},
	"OP05": {bit(cCOUNTRY) | bit(cCATEGORY) | bit(cDATE) | bit(cPRICE), func() Agg { return &op05{m: map[[3]int32]int32{}} }},
	"OP10": {bit(cCID) | bit(cPID) | bit(cSTORE) | bit(cDATE), func() Agg {
		return &op10{c: map[int64]struct{}{}, p: map[int64]struct{}{}, sd: map[uint64]struct{}{}}
	}},
	"OP06": {bit(cCID) | bit(cQTY) | bit(cPRICE), func() Agg {
		n := len(dims.segs)
		return &op06{cnt: make([]int64, n), sq: make([]int64, n), sp: make([]int64, n), seenq: make([]bool, n)}
	}},
	"OP07": {bit(cCID) | bit(cPID) | bit(cPRICE), func() Agg {
		n := len(dims.brands)
		ent := map[int64]struct{}{}
		for k, g := range dims.cust {
			if dims.segs[g] == "enterprise" {
				ent[k] = struct{}{}
			}
		}
		return &op07{ent: ent, cnt: make([]int64, n), sp: make([]int64, n)}
	}},
	"OP08": {bit(cTID) | bit(cTS), func() Agg { return &op08{} }},
	"OP09": {bit(cCID) | bit(cPRICE), func() Agg { return &op09{m: map[int64]int32{}} }},
	"OP19": {bit(cQTY) | bit(cCOUNTRY), func() Agg { return &op19{} }},
	"OP21": {bit(cPRICE), func() Agg { return &op21{} }},
	"OP22": {bit(cTID) | bit(cCID) | bit(cPRICE) | bit(cDATE) | bit(cTS), func() Agg { return &op22{} }},
}

func optI(v int64, seen bool) Val {
	if seen {
		return I(v)
	}
	return Null()
}

// ---- OP01 ----
type op01 struct {
	n, nq, sq, sp, mn, mx, cr int64
	started                   bool
}

func (a *op01) Consume(b *Batch) {
	cents, qty, qnull, ret := b.cents, b.qty, b.qnull, b.ret
	n := len(cents)
	qty, qnull, ret = qty[:n], qnull[:n], ret[:n]
	if !a.started && n > 0 {
		a.mn, a.mx, a.started = cents[0], cents[0], true
	}
	mn, mx, sp := a.mn, a.mx, a.sp
	var nq, sq, cr int64
	for i, c := range cents {
		if !qnull[i] {
			nq++
			sq += int64(qty[i])
		}
		sp += c
		if c < mn {
			mn = c
		}
		if c > mx {
			mx = c
		}
		if ret[i] {
			cr++
		}
	}
	a.mn, a.mx, a.sp = mn, mx, sp
	a.n += int64(n)
	a.nq += nq
	a.sq += sq
	a.cr += cr
}

func (a *op01) Result(*Batch) [][]Val {
	var mn, mx Val = Null(), Null()
	if a.started {
		mn, mx = I(a.mn), I(a.mx)
	}
	return [][]Val{{I(a.n), I(a.nq), optI(a.sq, a.nq > 0), I(a.sp), mn, mx, I(a.cr)}}
}

// ---- OP03 (groups indexed by country dictionary code + 1; slot 0 = NULL) ----
type op03 struct {
	cnt, sq, sc []int64
	seenq       []bool
}

func (a *op03) Consume(b *Batch) {
	need := len(b.countryD.strs) + 1
	for len(a.cnt) < need {
		a.cnt = append(a.cnt, 0)
		a.sq = append(a.sq, 0)
		a.sc = append(a.sc, 0)
		a.seenq = append(a.seenq, false)
	}
	n := len(b.cents)
	country, qty, qnull := b.country[:n], b.qty[:n], b.qnull[:n]
	for i, c := range b.cents {
		g := country[i] + 1
		a.cnt[g]++
		a.sc[g] += c
		if !qnull[i] {
			a.sq[g] += int64(qty[i])
			a.seenq[g] = true
		}
	}
}

func (a *op03) Result(b *Batch) [][]Val {
	var out [][]Val
	for g := range a.cnt {
		if a.cnt[g] == 0 {
			continue
		}
		k := Null()
		if g > 0 {
			k = S(b.countryD.strs[g-1])
		}
		out = append(out, []Val{k, I(a.cnt[g]), optI(a.sq[g], a.seenq[g]), I(a.sc[g])})
	}
	return out
}

// ---- OP04 ----
type op04 struct {
	m        map[int64]int32
	keys     []int64
	cnt, sum []int64
}

func (a *op04) Consume(b *Batch) {
	cid := b.cid[:len(b.cents)]
	for i, c := range b.cents {
		k := cid[i]
		g, ok := a.m[k]
		if !ok {
			g = int32(len(a.keys))
			a.m[k] = g
			a.keys = append(a.keys, k)
			a.cnt = append(a.cnt, 0)
			a.sum = append(a.sum, 0)
		}
		a.cnt[g]++
		a.sum[g] += c
	}
}

func (a *op04) Result(*Batch) [][]Val {
	out := make([][]Val, len(a.keys))
	for g, k := range a.keys {
		out[g] = []Val{I(k), I(a.cnt[g]), I(a.sum[g])}
	}
	return out
}

// ---- OP05 ----
type op05 struct {
	m        map[[3]int32]int32
	keys     [][3]int32
	cnt, sum []int64
}

func (a *op05) Consume(b *Batch) {
	n := len(b.cents)
	country, category, date := b.country[:n], b.category[:n], b.date[:n]
	for i, c := range b.cents {
		y, _, _ := civilFromDays(int64(date[i]))
		k := [3]int32{country[i], category[i], int32(y)}
		g, ok := a.m[k]
		if !ok {
			g = int32(len(a.keys))
			a.m[k] = g
			a.keys = append(a.keys, k)
			a.cnt = append(a.cnt, 0)
			a.sum = append(a.sum, 0)
		}
		a.cnt[g]++
		a.sum[g] += c
	}
}

func dictVal(d *Dict, c int32) Val {
	if c < 0 {
		return Null()
	}
	return S(d.strs[c])
}

func (a *op05) Result(b *Batch) [][]Val {
	out := make([][]Val, len(a.keys))
	for g, k := range a.keys {
		out[g] = []Val{dictVal(b.countryD, k[0]), dictVal(b.categoryD, k[1]), I(int64(k[2])), I(a.cnt[g]), I(a.sum[g])}
	}
	return out
}

// ---- OP10 ----
type op10 struct {
	c, p map[int64]struct{}
	sd   map[uint64]struct{}
}

func (a *op10) Consume(b *Batch) {
	n := len(b.cid)
	pid, store, date := b.pid[:n], b.store[:n], b.date[:n]
	for i, c := range b.cid {
		a.c[c] = struct{}{}
		a.p[pid[i]] = struct{}{}
		a.sd[uint64(uint32(store[i]))<<32|uint64(uint32(date[i]))] = struct{}{}
	}
}

func (a *op10) Result(*Batch) [][]Val {
	return [][]Val{{I(int64(len(a.c))), I(int64(len(a.p))), I(int64(len(a.sd)))}}
}

// ---- OP19 ----
type op19 struct {
	nq, nc, sq, ne int64
	seen           []bool
	nonEmpty       []bool
}

func (a *op19) Consume(b *Batch) {
	d := b.countryD
	for len(a.seen) < len(d.strs) {
		a.seen = append(a.seen, false)
		a.nonEmpty = append(a.nonEmpty, len(d.strs[len(a.seen)-1]) > 0)
	}
	n := len(b.country)
	qty, qnull := b.qty[:n], b.qnull[:n]
	for i, c := range b.country {
		if qnull[i] {
			a.nq++
			a.sq++
		} else {
			a.sq += int64(qty[i])
		}
		if c < 0 {
			a.nc++
		} else {
			a.seen[c] = true
			if a.nonEmpty[c] {
				a.ne++
			}
		}
	}
}

func (a *op19) Result(*Batch) [][]Val {
	var d int64
	for _, s := range a.seen {
		if s {
			d++
		}
	}
	return [][]Val{{I(a.nq), I(a.nc), I(a.sq), I(a.ne), I(d)}}
}

// ---- OP21 ----
type op21 struct {
	exact       int64
	naive, ksum float64
	comp        float64
}

func (a *op21) Consume(b *Batch) {
	exact, naive, ksum, comp := a.exact, a.naive, a.ksum, a.comp
	for _, c := range b.cents {
		exact += c
		v := float64(c) / 100.0
		naive += v
		y := v - comp
		t := ksum + y
		comp = (t - ksum) - y
		ksum = t
	}
	a.exact, a.naive, a.ksum, a.comp = exact, naive, ksum, comp
}

func (a *op21) Result(*Batch) [][]Val {
	text := itoa(floorDiv(a.exact, 100)) + "." + pad2(a.exact-floorDiv(a.exact, 100)*100)
	return [][]Val{{I(a.exact), S(text)}}
}

func itoa(v int64) string {
	if v == 0 {
		return "0"
	}
	neg := v < 0
	var buf [24]byte
	i := len(buf)
	u := uint64(v)
	if neg {
		u = -u
	}
	for u > 0 {
		i--
		buf[i] = byte('0' + u%10)
		u /= 10
	}
	if neg {
		i--
		buf[i] = '-'
	}
	return string(buf[i:])
}

func pad2(v int64) string {
	return string([]byte{byte('0' + v/10), byte('0' + v%10)})
}

// ---- OP22 ----
type op22 struct{ a, b, c, ymd int64 }

func (x *op22) Consume(b *Batch) {
	n := len(b.cents)
	tid, cid, ts, date := b.tid[:n], b.cid[:n], b.ts[:n], b.date[:n]
	var a, bb, c, ymd int64
	for i, cents := range b.cents {
		k := tid[i]*4294967311 + cid[i]
		if int64(float64(k)) != k {
			a++
		}
		f := float64(cents) / 100.0
		if int64(float64(f*100.0)) != cents {
			bb++
		}
		if (ts[i]/1000)*1000 != ts[i] {
			c++
		}
		y, m, d := civilFromDays(int64(date[i]))
		ymd += y*10000 + m*100 + d
	}
	x.a += a
	x.b += bb
	x.c += c
	x.ymd += ymd
}

func (x *op22) Result(*Batch) [][]Val {
	return [][]Val{{I(x.a), I(x.b), I(x.c), I(x.ymd)}}
}

// ---- OP06 (customer_id -> segment index via stdlib map; per-segment accumulator slices) ----
type op06 struct {
	cnt, sq, sp []int64
	seenq       []bool
}

func (a *op06) Consume(b *Batch) {
	n := len(b.cents)
	cid, qty, qnull := b.cid[:n], b.qty[:n], b.qnull[:n]
	cust := dims.cust
	for i, c := range b.cents {
		g, ok := cust[cid[i]]
		if !ok {
			continue
		}
		a.cnt[g]++
		a.sp[g] += c
		if !qnull[i] {
			a.sq[g] += int64(qty[i])
			a.seenq[g] = true
		}
	}
}

func (a *op06) Result(*Batch) [][]Val {
	var out [][]Val
	for g, s := range dims.segs {
		if a.cnt[g] > 0 {
			out = append(out, []Val{S(s), I(a.cnt[g]), I(a.sp[g]), optI(a.sq[g], a.seenq[g])})
		}
	}
	return out
}

// ---- OP07 ----
type op07 struct {
	ent     map[int64]struct{}
	cnt, sp []int64
}

func (a *op07) Consume(b *Batch) {
	n := len(b.cents)
	cid, pid := b.cid[:n], b.pid[:n]
	prod := dims.prod
	for i, c := range b.cents {
		if _, ok := a.ent[cid[i]]; !ok {
			continue
		}
		if g, ok := prod[pid[i]]; ok {
			a.cnt[g]++
			a.sp[g] += c
		}
	}
}

func (a *op07) Result(*Batch) [][]Val {
	var out [][]Val
	for g, s := range dims.brands {
		if a.cnt[g] > 0 {
			out = append(out, []Val{S(s), I(a.cnt[g]), I(a.sp[g])})
		}
	}
	return out
}

// ---- OP08 (materialized only; slices.SortFunc = pdqsort on (ts, id) pairs) ----
type op08 struct{ first, last, pos int64 }

type tsID struct{ ts, id int64 }

func (a *op08) Consume(b *Batch) {
	v := make([]tsID, len(b.ts))
	for i, t := range b.ts {
		v[i] = tsID{t, b.tid[i]}
	}
	slices.SortFunc(v, func(x, y tsID) int {
		if c := cmp.Compare(x.ts, y.ts); c != 0 {
			return c
		}
		return cmp.Compare(x.id, y.id)
	})
	if len(v) > 0 {
		a.first, a.last = v[0].id, v[len(v)-1].id
	}
	var s uint64
	for i, e := range v {
		s += uint64(i+1) * uint64(e.id)
	}
	a.pos = int64(s)
}

func (a *op08) Result(*Batch) [][]Val { return [][]Val{{I(a.first), I(a.last), I(a.pos)}} }

// ---- OP09 ----
type op09 struct {
	m    map[int64]int32
	keys []int64
	sum  []int64
}

func (a *op09) Consume(b *Batch) {
	cid := b.cid[:len(b.cents)]
	for i, c := range b.cents {
		k := cid[i]
		g, ok := a.m[k]
		if !ok {
			g = int32(len(a.keys))
			a.m[k] = g
			a.keys = append(a.keys, k)
			a.sum = append(a.sum, 0)
		}
		a.sum[g] += c
	}
}

func (a *op09) Result(*Batch) [][]Val {
	idx := make([]int32, len(a.keys))
	for i := range idx {
		idx[i] = int32(i)
	}
	less := func(x, y int32) int {
		if c := cmp.Compare(a.sum[y], a.sum[x]); c != 0 {
			return c
		}
		return cmp.Compare(a.keys[x], a.keys[y])
	}
	// Full sort of group indices, then take 100 (n groups is small relative to rows).
	slices.SortFunc(idx, less)
	if len(idx) > 100 {
		idx = idx[:100]
	}
	out := make([][]Val, len(idx))
	for r, g := range idx {
		out[r] = []Val{I(int64(r + 1)), I(a.keys[g]), I(a.sum[g])}
	}
	return out
}
