//! Hand-written CSV field scanning over a byte buffer and typed columnar storage.
//! No quoting support is needed (generator emits none); NULL is the exact two-byte field `\N`.

pub const C_TID: u32 = 1 << 0;
pub const C_CID: u32 = 1 << 1;
pub const C_PID: u32 = 1 << 2;
pub const C_STORE: u32 = 1 << 3;
pub const C_QTY: u32 = 1 << 4;
pub const C_PRICE: u32 = 1 << 5;
pub const C_COUNTRY: u32 = 1 << 8;
pub const C_CATEGORY: u32 = 1 << 9;
pub const C_DATE: u32 = 1 << 10;
pub const C_TS: u32 = 1 << 11;
pub const C_RET: u32 = 1 << 12;

pub const NULL_LEN: u32 = u32::MAX;

/// Columnar typed representation; only the columns in the mask are filled.
#[derive(Default)]
pub struct Columns {
    pub n: usize,
    pub tid: Vec<i64>,
    pub cid: Vec<i64>,
    pub pid: Vec<i64>,
    pub store: Vec<i32>,
    pub qty: Vec<Option<i32>>,
    pub cents: Vec<i64>,
    pub country: Vec<(u32, u32)>, // (offset into country_arena, len); len == NULL_LEN means NULL
    pub country_arena: Vec<u8>,
    pub category: Vec<(u32, u32)>,
    pub category_arena: Vec<u8>,
    pub date: Vec<i32>, // days since epoch
    pub ts: Vec<i64>,   // microseconds since epoch
    pub ret: Vec<bool>,
}

impl Columns {
    pub fn clear(&mut self) {
        self.n = 0;
        self.tid.clear();
        self.cid.clear();
        self.pid.clear();
        self.store.clear();
        self.qty.clear();
        self.cents.clear();
        self.country.clear();
        self.country_arena.clear();
        self.category.clear();
        self.category_arena.clear();
        self.date.clear();
        self.ts.clear();
        self.ret.clear();
    }
    pub fn reserve(&mut self, mask: u32, rows: usize) {
        if mask & C_TID != 0 { self.tid.reserve(rows); }
        if mask & C_CID != 0 { self.cid.reserve(rows); }
        if mask & C_PID != 0 { self.pid.reserve(rows); }
        if mask & C_STORE != 0 { self.store.reserve(rows); }
        if mask & C_QTY != 0 { self.qty.reserve(rows); }
        if mask & C_PRICE != 0 { self.cents.reserve(rows); }
        if mask & C_COUNTRY != 0 { self.country.reserve(rows); self.country_arena.reserve(rows * 8); }
        if mask & C_CATEGORY != 0 { self.category.reserve(rows); self.category_arena.reserve(rows * 12); }
        if mask & C_DATE != 0 { self.date.reserve(rows); }
        if mask & C_TS != 0 { self.ts.reserve(rows); }
        if mask & C_RET != 0 { self.ret.reserve(rows); }
    }
    #[inline]
    pub fn country_at(&self, i: usize) -> Option<&[u8]> {
        let (o, l) = self.country[i];
        if l == NULL_LEN { None } else { Some(&self.country_arena[o as usize..(o + l) as usize]) }
    }
    #[inline]
    pub fn category_at(&self, i: usize) -> &[u8] {
        let (o, l) = self.category[i];
        &self.category_arena[o as usize..(o + l) as usize]
    }
}

/// Parse an integer field (or `\N`), consuming the trailing delimiter.
#[inline(always)]
pub fn read_int(buf: &[u8], p: &mut usize) -> Option<i64> {
    if buf[*p] == b'\\' {
        *p += 3;
        return None;
    }
    let neg = buf[*p] == b'-';
    if neg {
        *p += 1;
    }
    let mut v: i64 = 0;
    loop {
        let d = buf[*p].wrapping_sub(b'0');
        if d > 9 {
            break;
        }
        v = v.wrapping_mul(10).wrapping_add(d as i64);
        *p += 1;
    }
    *p += 1;
    Some(if neg { v.wrapping_neg() } else { v })
}

/// Digits only (no delimiter consumed).
#[inline(always)]
fn num(buf: &[u8], p: &mut usize) -> i64 {
    let mut v: i64 = 0;
    loop {
        let d = buf[*p].wrapping_sub(b'0');
        if d > 9 {
            return v;
        }
        v = v * 10 + d as i64;
        *p += 1;
    }
}

/// Decimal text -> integer cents without floating point; consumes the delimiter.
/// Fractional digits beyond two are truncated (the schema is DECIMAL(_,2)).
#[inline(always)]
pub fn read_cents(buf: &[u8], p: &mut usize) -> i64 {
    let neg = buf[*p] == b'-';
    if neg {
        *p += 1;
    }
    let ip = num(buf, p);
    let mut frac = 0i64;
    let mut cnt = 0;
    if buf[*p] == b'.' {
        *p += 1;
        loop {
            let d = buf[*p].wrapping_sub(b'0');
            if d > 9 {
                break;
            }
            if cnt < 2 {
                frac = frac * 10 + d as i64;
                cnt += 1;
            }
            *p += 1;
        }
    }
    while cnt < 2 {
        frac *= 10;
        cnt += 1;
    }
    *p += 1;
    let c = ip * 100 + frac;
    if neg { -c } else { c }
}

/// Hinnant days_from_civil.
#[inline(always)]
pub fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let mp = (m + 9) % 12;
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

/// Hinnant civil_from_days -> (year, month, day).
#[inline(always)]
pub fn civil_from_days(z: i64) -> (i64, i64, i64) {
    let z = z + 719468;
    let era = z.div_euclid(146097);
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (if m <= 2 { y + 1 } else { y }, m, d)
}

/// `YYYY-MM-DD`; leaves p after the date (on the delimiter / space).
#[inline(always)]
fn date_part(buf: &[u8], p: &mut usize) -> i64 {
    let y = num(buf, p);
    *p += 1;
    let m = num(buf, p);
    *p += 1;
    let d = num(buf, p);
    days_from_civil(y, m, d)
}

#[inline(always)]
pub fn read_date(buf: &[u8], p: &mut usize) -> i64 {
    let d = date_part(buf, p);
    *p += 1;
    d
}

/// `YYYY-MM-DD HH:MM:SS[.ffffff]` -> microseconds since epoch.
#[inline(always)]
pub fn read_ts(buf: &[u8], p: &mut usize) -> i64 {
    let days = date_part(buf, p);
    *p += 1;
    let h = num(buf, p);
    *p += 1;
    let mi = num(buf, p);
    *p += 1;
    let s = num(buf, p);
    let mut frac = 0i64;
    if buf[*p] == b'.' {
        *p += 1;
        let mut cnt = 0;
        loop {
            let d = buf[*p].wrapping_sub(b'0');
            if d > 9 {
                break;
            }
            if cnt < 6 {
                frac = frac * 10 + d as i64;
                cnt += 1;
            }
            *p += 1;
        }
        while cnt < 6 {
            frac *= 10;
            cnt += 1;
        }
    }
    *p += 1;
    days * 86_400_000_000 + (h * 3600 + mi * 60 + s) * 1_000_000 + frac
}

/// Skip a field, consuming the delimiter.
#[inline(always)]
pub fn skip(buf: &[u8], p: &mut usize) {
    while buf[*p] != b',' {
        *p += 1;
    }
    *p += 1;
}

/// Return the field bytes (exclusive of delimiter) and consume the delimiter.
#[inline(always)]
pub fn field<'a>(buf: &'a [u8], p: &mut usize) -> &'a [u8] {
    let s = *p;
    let mut q = s;
    while buf[q] != b',' {
        q += 1;
    }
    *p = q + 1;
    &buf[s..q]
}

#[inline(always)]
pub fn is_null(f: &[u8]) -> bool {
    f.len() == 2 && f[0] == b'\\' && f[1] == b'N'
}

/// Position of the first data row (after the header line).
pub fn after_header(buf: &[u8]) -> usize {
    match buf.iter().position(|&b| b == b'\n') {
        Some(i) => i + 1,
        None => buf.len(),
    }
}

/// Finish a row: consume the rest of the line (after the last field start `p`).
#[inline(always)]
pub fn end_row(buf: &[u8], p: usize) -> usize {
    let mut q = p;
    while q < buf.len() && buf[q] != b'\n' {
        q += 1;
    }
    q + 1
}

/// Parse all rows of one chunk, appending the columns selected by M.
pub fn parse_chunk<const M: u32>(buf: &[u8], c: &mut Columns) {
    let n = buf.len();
    let mut p = after_header(buf);
    let mut rows = 0usize;
    while p < n {
        if buf[p] == b'\n' || buf[p] == b'\r' {
            p += 1;
            continue;
        }
        // 0 transaction_id
        if M & C_TID != 0 { c.tid.push(read_int(buf, &mut p).unwrap_or(0)); } else { skip(buf, &mut p); }
        // 1 customer_id
        if M & C_CID != 0 { c.cid.push(read_int(buf, &mut p).unwrap_or(0)); } else { skip(buf, &mut p); }
        // 2 product_id
        if M & C_PID != 0 { c.pid.push(read_int(buf, &mut p).unwrap_or(0)); } else { skip(buf, &mut p); }
        // 3 store_id
        if M & C_STORE != 0 { c.store.push(read_int(buf, &mut p).unwrap_or(0) as i32); } else { skip(buf, &mut p); }
        // 4 quantity
        if M & C_QTY != 0 { c.qty.push(read_int(buf, &mut p).map(|v| v as i32)); } else { skip(buf, &mut p); }
        // 5 unit_price
        if M & C_PRICE != 0 { c.cents.push(read_cents(buf, &mut p)); } else { skip(buf, &mut p); }
        // 6 discount, 7 tax
        skip(buf, &mut p);
        skip(buf, &mut p);
        // 8 country
        if M & C_COUNTRY != 0 {
            let f = field(buf, &mut p);
            if is_null(f) {
                c.country.push((0, NULL_LEN));
            } else {
                c.country.push((c.country_arena.len() as u32, f.len() as u32));
                c.country_arena.extend_from_slice(f);
            }
        } else {
            skip(buf, &mut p);
        }
        // 9 category
        if M & C_CATEGORY != 0 {
            let f = field(buf, &mut p);
            c.category.push((c.category_arena.len() as u32, f.len() as u32));
            c.category_arena.extend_from_slice(f);
        } else {
            skip(buf, &mut p);
        }
        // 10 date
        if M & C_DATE != 0 { c.date.push(read_date(buf, &mut p) as i32); } else { skip(buf, &mut p); }
        // 11 timestamp
        if M & C_TS != 0 { c.ts.push(read_ts(buf, &mut p)); } else { skip(buf, &mut p); }
        // 12 is_returned
        if M & C_RET != 0 { c.ret.push(buf[p] == b't'); }
        p = end_row(buf, p);
        rows += 1;
    }
    c.n += rows;
}
