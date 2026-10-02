//! The nine operations. Each op consumes typed columns (one chunk in streaming mode, all rows in
//! materialized mode) into its own state; `digest` turns the final state into result rows (untimed).
use crate::csv::*;
use crate::hash::*;

pub trait Op {
    fn consume(&mut self, c: &Columns);
    /// Feed result rows to the digest; returns float results.
    fn digest(&self, d: &mut Digest) -> Vec<(&'static str, f64)>;
}

#[derive(Default, Clone, Copy)]
pub struct Agg {
    count: i64,
    sq: i64,
    seen: bool,
    sp: i64,
}

impl Agg {
    #[inline(always)]
    fn add(&mut self, q: Option<i32>, cents: i64) {
        self.count += 1;
        if let Some(q) = q {
            self.sq += q as i64;
            self.seen = true;
        }
        self.sp = self.sp.wrapping_add(cents);
    }
    fn sq_v(&self) -> V<'static> {
        if self.seen { V::I(self.sq) } else { V::Null }
    }
}

// ---------------------------------------------------------------- OP01
pub const OP01_MASK: u32 = C_QTY | C_PRICE | C_RET;
#[derive(Default)]
pub struct Op01 {
    n: i64,
    nq: i64,
    sq: i64,
    sp: i64,
    mn: i64,
    mx: i64,
    ret: i64,
}
impl Op for Op01 {
    fn consume(&mut self, c: &Columns) {
        if self.n == 0 && c.n > 0 {
            self.mn = i64::MAX;
            self.mx = i64::MIN;
        }
        for i in 0..c.n {
            if let Some(q) = c.qty[i] {
                self.nq += 1;
                self.sq += q as i64;
            }
            let p = c.cents[i];
            self.sp = self.sp.wrapping_add(p);
            if p < self.mn { self.mn = p; }
            if p > self.mx { self.mx = p; }
            self.ret += c.ret[i] as i64;
        }
        self.n += c.n as i64;
    }
    fn digest(&self, d: &mut Digest) -> Vec<(&'static str, f64)> {
        let (mn, mx) = if self.n > 0 { (V::I(self.mn), V::I(self.mx)) } else { (V::Null, V::Null) };
        let sq = if self.nq > 0 { V::I(self.sq) } else { V::Null };
        d.add(&[V::I(self.n), V::I(self.nq), sq, V::I(self.sp), mn, mx, V::I(self.ret)]);
        vec![]
    }
}

// ---------------------------------------------------------------- OP03
pub const OP03_MASK: u32 = C_COUNTRY | C_QTY | C_PRICE;
#[derive(Default)]
pub struct Op03 {
    map: FxMap<Vec<u8>, Agg>,
    null: Agg,
}
impl Op for Op03 {
    fn consume(&mut self, c: &Columns) {
        for i in 0..c.n {
            match c.country_at(i) {
                None => self.null.add(c.qty[i], c.cents[i]),
                Some(k) => {
                    if let Some(a) = self.map.get_mut(k) {
                        a.add(c.qty[i], c.cents[i]);
                    } else {
                        let mut a = Agg::default();
                        a.add(c.qty[i], c.cents[i]);
                        self.map.insert(k.to_vec(), a);
                    }
                }
            }
        }
    }
    fn digest(&self, d: &mut Digest) -> Vec<(&'static str, f64)> {
        if self.null.count > 0 {
            let a = &self.null;
            d.add(&[V::Null, V::I(a.count), a.sq_v(), V::I(a.sp)]);
        }
        for (k, a) in &self.map {
            d.add(&[V::S(k), V::I(a.count), a.sq_v(), V::I(a.sp)]);
        }
        vec![]
    }
}

// ---------------------------------------------------------------- OP04
pub const OP04_MASK: u32 = C_CID | C_PRICE;
#[derive(Default)]
pub struct Op04 {
    map: FxMap<i64, (i64, i64)>,
}
impl Op for Op04 {
    fn consume(&mut self, c: &Columns) {
        for i in 0..c.n {
            let e = self.map.entry(c.cid[i]).or_insert((0, 0));
            e.0 += 1;
            e.1 = e.1.wrapping_add(c.cents[i]);
        }
    }
    fn digest(&self, d: &mut Digest) -> Vec<(&'static str, f64)> {
        for (k, a) in &self.map {
            d.add(&[V::I(*k), V::I(a.0), V::I(a.1)]);
        }
        vec![]
    }
}

// ---------------------------------------------------------------- OP05
pub const OP05_MASK: u32 = C_COUNTRY | C_CATEGORY | C_DATE | C_PRICE;
#[derive(Default)]
pub struct Op05 {
    map: FxMap<Vec<u8>, (Option<Vec<u8>>, Vec<u8>, i64, Agg)>,
    key: Vec<u8>,
}
impl Op for Op05 {
    fn consume(&mut self, c: &Columns) {
        for i in 0..c.n {
            let year = civil_from_days(c.date[i] as i64).0;
            let country = c.country_at(i);
            let cat = c.category_at(i);
            self.key.clear();
            self.key.extend_from_slice(&year.to_le_bytes());
            match country {
                None => {
                    self.key.push(0);
                    self.key.extend_from_slice(&0u32.to_le_bytes());
                }
                Some(s) => {
                    self.key.push(1);
                    self.key.extend_from_slice(&(s.len() as u32).to_le_bytes());
                    self.key.extend_from_slice(s);
                }
            }
            self.key.extend_from_slice(cat);
            if let Some(e) = self.map.get_mut(self.key.as_slice()) {
                e.3.add(None, c.cents[i]);
            } else {
                let mut a = Agg::default();
                a.add(None, c.cents[i]);
                self.map.insert(self.key.clone(), (country.map(|s| s.to_vec()), cat.to_vec(), year, a));
            }
        }
    }
    fn digest(&self, d: &mut Digest) -> Vec<(&'static str, f64)> {
        for (country, cat, year, a) in self.map.values() {
            let cv = match country {
                None => V::Null,
                Some(s) => V::S(s),
            };
            d.add(&[cv, V::S(cat), V::I(*year), V::I(a.count), V::I(a.sp)]);
        }
        vec![]
    }
}

// ---------------------------------------------------------------- OP10
pub const OP10_MASK: u32 = C_CID | C_PID | C_STORE | C_DATE;
#[derive(Default)]
pub struct Op10 {
    cust: FxSet<i64>,
    prod: FxSet<i64>,
    sd: FxSet<u64>,
}
impl Op for Op10 {
    fn consume(&mut self, c: &Columns) {
        for i in 0..c.n {
            self.cust.insert(c.cid[i]);
            self.prod.insert(c.pid[i]);
            self.sd.insert(((c.store[i] as u32 as u64) << 32) | c.date[i] as u32 as u64);
        }
    }
    fn digest(&self, d: &mut Digest) -> Vec<(&'static str, f64)> {
        d.add(&[V::I(self.cust.len() as i64), V::I(self.prod.len() as i64), V::I(self.sd.len() as i64)]);
        vec![]
    }
}

// ---------------------------------------------------------------- OP19
pub const OP19_MASK: u32 = C_QTY | C_COUNTRY;
#[derive(Default)]
pub struct Op19 {
    nq: i64,
    nc: i64,
    sq1: i64,
    ne: i64,
    distinct: FxSet<Vec<u8>>,
}
impl Op for Op19 {
    fn consume(&mut self, c: &Columns) {
        for i in 0..c.n {
            match c.qty[i] {
                None => {
                    self.nq += 1;
                    self.sq1 += 1;
                }
                Some(q) => self.sq1 += q as i64,
            }
            match c.country_at(i) {
                None => self.nc += 1,
                Some(s) => {
                    if !s.is_empty() {
                        self.ne += 1;
                    }
                    if !self.distinct.contains(s) {
                        self.distinct.insert(s.to_vec());
                    }
                }
            }
        }
    }
    fn digest(&self, d: &mut Digest) -> Vec<(&'static str, f64)> {
        d.add(&[V::I(self.nq), V::I(self.nc), V::I(self.sq1), V::I(self.ne), V::I(self.distinct.len() as i64)]);
        vec![]
    }
}

// ---------------------------------------------------------------- OP21
pub const OP21_MASK: u32 = C_PRICE;
#[derive(Default)]
pub struct Op21 {
    exact: i64,
    naive: f64,
    ksum: f64,
    comp: f64,
}
impl Op for Op21 {
    fn consume(&mut self, c: &Columns) {
        for &cents in &c.cents[..c.n] {
            self.exact = self.exact.wrapping_add(cents);
            let v = cents as f64 / 100.0;
            self.naive += v;
            let y = v - self.comp;
            let t = self.ksum + y;
            self.comp = (t - self.ksum) - y;
            self.ksum = t;
        }
    }
    fn digest(&self, d: &mut Digest) -> Vec<(&'static str, f64)> {
        let text = format!("{}.{:02}", self.exact.div_euclid(100), self.exact.rem_euclid(100));
        d.add(&[V::I(self.exact), V::S(text.as_bytes())]);
        vec![("naive_sum", self.naive), ("kahan_sum", self.ksum)]
    }
}

// ---------------------------------------------------------------- OP22
pub const OP22_MASK: u32 = C_TID | C_CID | C_PRICE | C_TS | C_DATE;
#[derive(Default)]
pub struct Op22 {
    a: i64,
    b: i64,
    c: i64,
    ymd: i64,
}
impl Op for Op22 {
    fn consume(&mut self, c: &Columns) {
        for i in 0..c.n {
            let k = c.tid[i].wrapping_mul(4294967311).wrapping_add(c.cid[i]);
            if (k as f64) as i64 != k {
                self.a += 1;
            }
            let cents = c.cents[i];
            let f = cents as f64 / 100.0;
            if (f * 100.0).trunc() as i64 != cents {
                self.b += 1;
            }
            let us = c.ts[i];
            if us.div_euclid(1000) * 1000 != us {
                self.c += 1;
            }
            let (y, m, d) = civil_from_days(c.date[i] as i64);
            self.ymd += y * 10000 + m * 100 + d;
        }
    }
    fn digest(&self, d: &mut Digest) -> Vec<(&'static str, f64)> {
        d.add(&[V::I(self.a), V::I(self.b), V::I(self.c), V::I(self.ymd)]);
        vec![]
    }
}

// ---------------------------------------------------------------- OP15 (fused parse + summarise)
#[derive(Default)]
pub struct Op15 {
    rows: i64,
    tid: i64,
    cid: i64,
    pid: i64,
    store: i64,
    qty: i64,
    nq: i64,
    cents: i64,
    disc: i64,
    tax: i64,
    cb: i64,
    nc: i64,
    gb: i64,
    days: i64,
    sec: i64,
    frac: i64,
    ret: i64,
}

fn parse_f64(f: &[u8]) -> f64 {
    std::str::from_utf8(f).ok().and_then(|s| s.parse::<f64>().ok()).unwrap_or(0.0)
}

impl Op15 {
    /// Parse every column of every row in `buf` and fold into the summaries.
    pub fn parse(&mut self, buf: &[u8]) {
        let n = buf.len();
        let mut p = after_header(buf);
        while p < n {
            if buf[p] == b'\n' || buf[p] == b'\r' {
                p += 1;
                continue;
            }
            self.tid = self.tid.wrapping_add(read_int(buf, &mut p).unwrap_or(0));
            self.cid = self.cid.wrapping_add(read_int(buf, &mut p).unwrap_or(0));
            self.pid = self.pid.wrapping_add(read_int(buf, &mut p).unwrap_or(0));
            self.store = self.store.wrapping_add(read_int(buf, &mut p).unwrap_or(0));
            match read_int(buf, &mut p) {
                Some(q) => self.qty = self.qty.wrapping_add(q),
                None => self.nq += 1,
            }
            self.cents = self.cents.wrapping_add(read_cents(buf, &mut p));
            let f = field(buf, &mut p);
            if !is_null(f) {
                self.disc = self.disc.wrapping_add((parse_f64(f) * 1e6 + 0.5).floor() as i64);
            }
            let f = field(buf, &mut p);
            if !is_null(f) {
                self.tax = self.tax.wrapping_add((parse_f64(f) * 1e6 + 0.5).floor() as i64);
            }
            let f = field(buf, &mut p);
            if is_null(f) { self.nc += 1; } else { self.cb += f.len() as i64; }
            let f = field(buf, &mut p);
            if !is_null(f) { self.gb += f.len() as i64; }
            self.days += read_date(buf, &mut p);
            let us = read_ts(buf, &mut p);
            self.sec += us.div_euclid(1_000_000);
            self.frac += us.rem_euclid(1_000_000);
            self.ret += (buf[p] == b't') as i64;
            p = end_row(buf, p);
            self.rows += 1;
        }
    }
    pub fn digest(&self, d: &mut Digest) {
        d.add(&[
            V::I(self.rows), V::I(self.tid), V::I(self.cid), V::I(self.pid), V::I(self.store),
            V::I(self.qty), V::I(self.nq), V::I(self.cents), V::I(self.disc), V::I(self.tax),
            V::I(self.cb), V::I(self.nc), V::I(self.gb), V::I(self.days), V::I(self.sec),
            V::I(self.frac), V::I(self.ret),
        ]);
    }
}
