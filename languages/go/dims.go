package main

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"sort"
	"strconv"
)

// Dims holds the small dimension tables. Only the leading CSV fields are read; the rest of each
// line (quoted JSON in dim_product) is ignored without quote handling.
type Dims struct {
	cust   map[int64]int32 // customer_id -> segment index
	segs   []string
	prod   map[int64]int32 // product_id -> brand index
	brands []string
}

var dims = &Dims{}

func readTable(dir string, fn func(line []byte) error) error {
	files, err := filepath.Glob(filepath.Join(dir, "part-*.csv"))
	if err != nil || len(files) == 0 {
		return errors.New("no CSV chunks in " + dir)
	}
	sort.Strings(files)
	for _, f := range files {
		buf, err := os.ReadFile(f)
		if err != nil {
			return err
		}
		_, buf = nextLine(buf) // header
		for len(buf) > 0 {
			var line []byte
			line, buf = nextLine(buf)
			if len(line) == 0 {
				continue
			}
			if err := fn(line); err != nil {
				return err
			}
		}
	}
	return nil
}

// fields splits the first len(out) comma-separated fields of line (the remainder is ignored).
func fields(line []byte, out [][]byte) bool {
	for i := range out {
		j := bytes.IndexByte(line, ',')
		if j < 0 {
			if i == len(out)-1 {
				out[i] = line
				return true
			}
			return false
		}
		out[i], line = line[:j], line[j+1:]
	}
	return true
}

func intern(m map[string]int32, list *[]string, b []byte) int32 {
	if c, ok := m[string(b)]; ok {
		return c
	}
	s := string(b)
	c := int32(len(*list))
	m[s] = c
	*list = append(*list, s)
	return c
}

// loadCustomers: customer_id,name,email,signup_date,segment,...
func (d *Dims) loadCustomers(dir string) error {
	d.cust = map[int64]int32{}
	dict := map[string]int32{}
	var f [5][]byte
	return readTable(dir, func(line []byte) error {
		if !fields(line, f[:]) {
			return errBad
		}
		id, err := strconv.ParseInt(string(f[0]), 10, 64)
		if err != nil {
			return err
		}
		d.cust[id] = intern(dict, &d.segs, f[4])
		return nil
	})
}

// loadProducts: product_id,category,brand,... (rest ignored)
func (d *Dims) loadProducts(dir string) error {
	d.prod = map[int64]int32{}
	dict := map[string]int32{}
	var f [3][]byte
	return readTable(dir, func(line []byte) error {
		if !fields(line, f[:]) {
			return errBad
		}
		id, err := strconv.ParseInt(string(f[0]), 10, 64)
		if err != nil {
			return err
		}
		d.prod[id] = intern(dict, &d.brands, f[2])
		return nil
	})
}
