package main

import (
	"bytes"
	"errors"
	"io"
	"os"
	"strconv"
)

// Column indices of sales_fact.
const (
	cTID = iota
	cCID
	cPID
	cSTORE
	cQTY
	cPRICE
	cDISC
	cTAX
	cCOUNTRY
	cCATEGORY
	cDATE
	cTS
	cRET
	nCols
)

func bit(c int) uint32 { return 1 << uint(c) }

var errBad = errors.New("malformed CSV field")

// Dict is a string dictionary (stdlib map keyed by string; lookups with string(b) do not allocate).
type Dict struct {
	m    map[string]int32
	strs []string
}

func newDict() *Dict { return &Dict{m: make(map[string]int32)} }

func (d *Dict) code(b []byte) int32 {
	if c, ok := d.m[string(b)]; ok {
		return c
	}
	s := string(b)
	c := int32(len(d.strs))
	d.m[s] = c
	d.strs = append(d.strs, s)
	return c
}

// Batch is a columnar block of parsed rows. Only the columns in `need` are filled.
type Batch struct {
	n         int
	tid, cid  []int64
	pid       []int64
	store     []int32
	qty       []int32
	qnull     []bool
	cents     []int64
	country   []int32 // dictionary code, -1 = NULL
	category  []int32
	date      []int32
	ts        []int64
	ret       []bool
	countryD  *Dict
	categoryD *Dict
}

func newBatch(need uint32, capRows int) *Batch {
	b := &Batch{countryD: newDict(), categoryD: newDict()}
	if need&bit(cTID) != 0 {
		b.tid = make([]int64, 0, capRows)
	}
	if need&bit(cCID) != 0 {
		b.cid = make([]int64, 0, capRows)
	}
	if need&bit(cPID) != 0 {
		b.pid = make([]int64, 0, capRows)
	}
	if need&bit(cSTORE) != 0 {
		b.store = make([]int32, 0, capRows)
	}
	if need&bit(cQTY) != 0 {
		b.qty = make([]int32, 0, capRows)
		b.qnull = make([]bool, 0, capRows)
	}
	if need&bit(cPRICE) != 0 {
		b.cents = make([]int64, 0, capRows)
	}
	if need&bit(cCOUNTRY) != 0 {
		b.country = make([]int32, 0, capRows)
	}
	if need&bit(cCATEGORY) != 0 {
		b.category = make([]int32, 0, capRows)
	}
	if need&bit(cDATE) != 0 {
		b.date = make([]int32, 0, capRows)
	}
	if need&bit(cTS) != 0 {
		b.ts = make([]int64, 0, capRows)
	}
	if need&bit(cRET) != 0 {
		b.ret = make([]bool, 0, capRows)
	}
	return b
}

// reset drops the rows but keeps buffers and dictionaries (streaming mode).
func (b *Batch) reset() {
	b.n = 0
	b.tid, b.cid, b.pid = b.tid[:0], b.cid[:0], b.pid[:0]
	b.store, b.qty, b.qnull = b.store[:0], b.qty[:0], b.qnull[:0]
	b.cents = b.cents[:0]
	b.country, b.category = b.country[:0], b.category[:0]
	b.date, b.ts, b.ret = b.date[:0], b.ts[:0], b.ret[:0]
}

// ---------- low level readers ----------

// readFile reads a whole file into buf (reused when large enough).
func readFile(path string, buf []byte) ([]byte, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return nil, err
	}
	sz := int(st.Size())
	if cap(buf) < sz {
		buf = make([]byte, sz)
	}
	buf = buf[:sz]
	if _, err := io.ReadFull(f, buf); err != nil {
		return nil, err
	}
	return buf, nil
}

func isNull(f []byte) bool { return len(f) == 2 && f[0] == '\\' && f[1] == 'N' }

func parseInt(f []byte) (int64, bool) {
	i := 0
	neg := false
	if len(f) > 0 && (f[0] == '-' || f[0] == '+') {
		neg = f[0] == '-'
		i = 1
	}
	if i >= len(f) {
		return 0, false
	}
	var v int64
	for ; i < len(f); i++ {
		d := f[i] - '0'
		if d > 9 {
			return 0, false
		}
		v = v*10 + int64(d)
	}
	if neg {
		v = -v
	}
	return v, true
}

// parseCents converts decimal text ("1234.56") to int64 cents without floating point
// (digits beyond the second decimal are truncated toward zero).
func parseCents(f []byte) (int64, bool) {
	i := 0
	neg := false
	if len(f) > 0 && (f[0] == '-' || f[0] == '+') {
		neg = f[0] == '-'
		i = 1
	}
	if i >= len(f) {
		return 0, false
	}
	var ip int64
	nd := 0
	for ; i < len(f) && f[i] != '.'; i++ {
		d := f[i] - '0'
		if d > 9 {
			return 0, false
		}
		ip = ip*10 + int64(d)
		nd++
	}
	var frac int64
	fd := 0
	if i < len(f) { // at '.'
		i++
		for ; i < len(f); i++ {
			d := f[i] - '0'
			if d > 9 {
				return 0, false
			}
			if fd < 2 {
				frac = frac*10 + int64(d)
				fd++
			}
			nd++
		}
	}
	if nd == 0 {
		return 0, false
	}
	for ; fd < 2; fd++ {
		frac *= 10
	}
	v := ip*100 + frac
	if neg {
		v = -v
	}
	return v, true
}

func floorDiv(a, b int64) int64 {
	q := a / b
	if (a%b != 0) && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}

func daysFromCivil(y, m, d int64) int64 {
	if m <= 2 {
		y--
	}
	era := floorDiv(y, 400)
	yoe := y - era*400
	var mp int64
	if m > 2 {
		mp = m - 3
	} else {
		mp = m + 9
	}
	doy := (153*mp+2)/5 + d - 1
	doe := yoe*365 + yoe/4 - yoe/100 + doy
	return era*146097 + doe - 719468
}

// civilFromDays is Hinnant's algorithm.
func civilFromDays(z int64) (y, m, d int64) {
	z += 719468
	era := floorDiv(z, 146097)
	doe := z - era*146097
	yoe := (doe - doe/1460 + doe/36524 - doe/146096) / 365
	y = yoe + era*400
	doy := doe - (365*yoe + yoe/4 - yoe/100)
	mp := (5*doy + 2) / 153
	d = doy - (153*mp+2)/5 + 1
	if mp < 10 {
		m = mp + 3
	} else {
		m = mp - 9
	}
	if m <= 2 {
		y++
	}
	return
}

// parseDate parses YYYY-MM-DD into days since epoch.
func parseDate(f []byte) (int64, bool) {
	var parts [3]int64
	p := 0
	var v int64
	nd := 0
	neg := false
	for i := 0; i < len(f); i++ {
		c := f[i]
		if c == '-' && nd == 0 && p == 0 && i == 0 {
			neg = true
			continue
		}
		if c == '-' {
			if nd == 0 || p >= 2 {
				return 0, false
			}
			parts[p] = v
			p++
			v, nd = 0, 0
			continue
		}
		d := c - '0'
		if d > 9 {
			return 0, false
		}
		v = v*10 + int64(d)
		nd++
	}
	if p != 2 || nd == 0 {
		return 0, false
	}
	parts[2] = v
	if neg {
		parts[0] = -parts[0]
	}
	return daysFromCivil(parts[0], parts[1], parts[2]), true
}

func two(f []byte) (int64, bool) {
	if len(f) < 2 {
		return 0, false
	}
	a, b := f[0]-'0', f[1]-'0'
	if a > 9 || b > 9 {
		return 0, false
	}
	return int64(a)*10 + int64(b), true
}

// parseTS parses "YYYY-MM-DD HH:MM:SS[.ffffff]" into microseconds since epoch.
func parseTS(f []byte) (int64, bool) {
	sp := bytes.IndexByte(f, ' ')
	if sp < 0 {
		sp = bytes.IndexByte(f, 'T')
		if sp < 0 {
			return 0, false
		}
	}
	days, ok := parseDate(f[:sp])
	if !ok {
		return 0, false
	}
	t := f[sp+1:]
	if len(t) < 8 || t[2] != ':' || t[5] != ':' {
		return 0, false
	}
	h, ok1 := two(t[0:])
	mi, ok2 := two(t[3:])
	s, ok3 := two(t[6:])
	if !ok1 || !ok2 || !ok3 {
		return 0, false
	}
	var frac int64
	if len(t) > 8 {
		if t[8] != '.' {
			return 0, false
		}
		n := 0
		for _, c := range t[9:] {
			d := c - '0'
			if d > 9 {
				return 0, false
			}
			if n < 6 {
				frac = frac*10 + int64(d)
				n++
			}
		}
		for ; n < 6; n++ {
			frac *= 10
		}
	}
	return ((days*86400+h*3600+mi*60+s)*1000000 + frac), true
}

// nextLine returns the next line (without \n or \r) and the rest of the buffer.
func nextLine(buf []byte) (line, rest []byte) {
	i := bytes.IndexByte(buf, '\n')
	if i < 0 {
		line, rest = buf, nil
	} else {
		line, rest = buf[:i], buf[i+1:]
	}
	if n := len(line); n > 0 && line[n-1] == '\r' {
		line = line[:n-1]
	}
	return
}

func skipHeader(buf []byte) []byte {
	if bytes.HasPrefix(buf, []byte("transaction_id")) {
		_, rest := nextLine(buf)
		return rest
	}
	return buf
}

// parseChunk appends the needed columns of every row of buf to b.
func parseChunk(buf []byte, need uint32, b *Batch) error {
	last := 0
	for c := 0; c < nCols; c++ {
		if need&bit(c) != 0 {
			last = c
		}
	}
	buf = skipHeader(buf)
	n := 0
	for len(buf) > 0 {
		var line []byte
		line, buf = nextLine(buf)
		if len(line) == 0 {
			continue
		}
		for f := 0; f <= last; f++ {
			var fld []byte
			if f == nCols-1 {
				fld = line
			} else {
				i := bytes.IndexByte(line, ',')
				if i < 0 {
					return errBad
				}
				fld, line = line[:i], line[i+1:]
			}
			if need&bit(f) == 0 {
				continue
			}
			switch f {
			case cTID:
				v, ok := parseInt(fld)
				if !ok {
					return errBad
				}
				b.tid = append(b.tid, v)
			case cCID:
				v, ok := parseInt(fld)
				if !ok {
					return errBad
				}
				b.cid = append(b.cid, v)
			case cPID:
				v, ok := parseInt(fld)
				if !ok {
					return errBad
				}
				b.pid = append(b.pid, v)
			case cSTORE:
				v, ok := parseInt(fld)
				if !ok {
					return errBad
				}
				b.store = append(b.store, int32(v))
			case cQTY:
				if isNull(fld) {
					b.qty = append(b.qty, 0)
					b.qnull = append(b.qnull, true)
				} else {
					v, ok := parseInt(fld)
					if !ok {
						return errBad
					}
					b.qty = append(b.qty, int32(v))
					b.qnull = append(b.qnull, false)
				}
			case cPRICE:
				v, ok := parseCents(fld)
				if !ok {
					return errBad
				}
				b.cents = append(b.cents, v)
			case cCOUNTRY:
				if isNull(fld) {
					b.country = append(b.country, -1)
				} else {
					b.country = append(b.country, b.countryD.code(fld))
				}
			case cCATEGORY:
				if isNull(fld) {
					b.category = append(b.category, -1)
				} else {
					b.category = append(b.category, b.categoryD.code(fld))
				}
			case cDATE:
				v, ok := parseDate(fld)
				if !ok {
					return errBad
				}
				b.date = append(b.date, int32(v))
			case cTS:
				v, ok := parseTS(fld)
				if !ok {
					return errBad
				}
				b.ts = append(b.ts, v)
			case cRET:
				b.ret = append(b.ret, len(fld) > 0 && fld[0] == 't')
			}
		}
		n++
	}
	b.n += n
	return nil
}

// ---------- OP15: parse every column and summarise ----------

type op15State struct {
	rows, tid, cid, pid, store, qty, nq, cents, disc, tax int64
	cb, nc, gb, days, sec, frac, ret                      int64
}

func (s *op15State) chunk(buf []byte) error {
	buf = skipHeader(buf)
	for len(buf) > 0 {
		var line []byte
		line, buf = nextLine(buf)
		if len(line) == 0 {
			continue
		}
		var fl [nCols][]byte
		for f := 0; f < nCols-1; f++ {
			i := bytes.IndexByte(line, ',')
			if i < 0 {
				return errBad
			}
			fl[f], line = line[:i], line[i+1:]
		}
		fl[nCols-1] = line
		s.rows++
		var ok bool
		var v int64
		if v, ok = parseInt(fl[cTID]); !ok {
			return errBad
		}
		s.tid += v
		if v, ok = parseInt(fl[cCID]); !ok {
			return errBad
		}
		s.cid += v
		if v, ok = parseInt(fl[cPID]); !ok {
			return errBad
		}
		s.pid += v
		if v, ok = parseInt(fl[cSTORE]); !ok {
			return errBad
		}
		s.store += v
		if isNull(fl[cQTY]) {
			s.nq++
		} else {
			if v, ok = parseInt(fl[cQTY]); !ok {
				return errBad
			}
			s.qty += v
		}
		if v, ok = parseCents(fl[cPRICE]); !ok {
			return errBad
		}
		s.cents += v
		d, err := strconv.ParseFloat(string(fl[cDISC]), 64)
		if err != nil {
			return errBad
		}
		s.disc += floorE6(d)
		t, err := strconv.ParseFloat(string(fl[cTAX]), 64)
		if err != nil {
			return errBad
		}
		s.tax += floorE6(t)
		if isNull(fl[cCOUNTRY]) {
			s.nc++
		} else {
			s.cb += int64(len(fl[cCOUNTRY]))
		}
		if !isNull(fl[cCATEGORY]) {
			s.gb += int64(len(fl[cCATEGORY]))
		}
		if v, ok = parseDate(fl[cDATE]); !ok {
			return errBad
		}
		s.days += v
		if v, ok = parseTS(fl[cTS]); !ok {
			return errBad
		}
		s.sec += floorDiv(v, 1000000)
		s.frac += v - floorDiv(v, 1000000)*1000000
		if len(fl[cRET]) > 0 && fl[cRET][0] == 't' {
			s.ret++
		}
	}
	return nil
}

func floorE6(x float64) int64 {
	// explicit float64() conversion forbids fused multiply-add on any architecture
	y := float64(x*1e6) + 0.5
	f := int64(y)
	if float64(f) > y {
		f--
	}
	return f
}
