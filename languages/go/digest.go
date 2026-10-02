package main

import "fmt"

const (
	golden   uint64 = 0x9E3779B97F4A7C15
	c1       uint64 = 0xBF58476D1CE4E5B9
	c2       uint64 = 0x94D049BB133111EB
	nullCan  uint64 = 0xA5A5A5A5A5A5A5A5
	fnvOff   uint64 = 0xCBF29CE484222325
	fnvPrime uint64 = 0x100000001B3
)

func mix64(z uint64) uint64 {
	z ^= z >> 30
	z *= c1
	z ^= z >> 27
	z *= c2
	z ^= z >> 31
	return z
}

func fnv1a(s string) uint64 {
	h := fnvOff
	for i := 0; i < len(s); i++ {
		h = (h ^ uint64(s[i])) * fnvPrime
	}
	return h
}

// Val is one result cell: int64, string or NULL.
type Val struct {
	kind uint8 // 0 null, 1 int, 2 string
	i    int64
	s    string
}

func I(x int64) Val  { return Val{kind: 1, i: x} }
func S(s string) Val { return Val{kind: 2, s: s} }
func Null() Val      { return Val{} }
func (v Val) canon() uint64 {
	switch v.kind {
	case 1:
		return uint64(v.i)
	case 2:
		return fnv1a(v.s)
	}
	return nullCan
}

// digest implements the order-insensitive result digest of spec/checksum.md.
func digest(rows [][]Val) (string, int) {
	var sum, xor uint64
	for _, r := range rows {
		var h uint64
		for _, v := range r {
			h = mix64(h + v.canon() + golden)
		}
		sum += h
		xor ^= h
	}
	return fmt.Sprintf("%016x%016x", sum, xor), len(rows)
}
