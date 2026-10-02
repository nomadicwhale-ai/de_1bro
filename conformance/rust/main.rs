// Conformance probe (Rust, built WITHOUT optimisation so overflow checks are on, as in `cargo build` debug).
use std::collections::{BTreeSet, HashMap};
use std::hint::black_box;
use std::mem::size_of;
use std::panic::{catch_unwind, set_hook};

fn kv(k: &str, v: &str) { println!("{}={}", k, v); }
fn fmt17(x: f64) -> String {
    if x.is_nan() { return "nan".into(); }
    if x.is_infinite() { return if x > 0.0 { "inf".into() } else { "-inf".into() }; }
    if x == 0.0 { return "0".into(); }
    let e: i32 = format!("{:.16e}", x).split('e').nth(1).unwrap().parse().unwrap();
    let dec = (16 - e).max(0) as usize;
    let mut s = format!("{:.*}", dec, x);
    if s.contains('.') { while s.ends_with('0') { s.pop(); } if s.ends_with('.') { s.pop(); } }
    s
}
fn probe<F: FnOnce() -> String + std::panic::UnwindSafe>(k: &str, f: F) {
    match catch_unwind(f) { Ok(v) => kv(k, &v), Err(_) => kv(k, "panic") }
}
fn strprobe(prefix: &str, s: &str) {
    kv(&format!("{}_utf8", prefix), &s.len().to_string());
    kv(&format!("{}_utf16", prefix), &s.encode_utf16().count().to_string());
    kv(&format!("{}_scalars", prefix), &s.chars().count().to_string());
}
fn main() {
    set_hook(Box::new(|_| {})); // keep stderr quiet; panics are reported as probe values
    kv("lang", "rust");
    let v = std::process::Command::new("rustc").arg("--version").output()
        .ok().and_then(|o| String::from_utf8(o.stdout).ok()).unwrap_or_else(|| "unknown".into());
    kv("version", v.trim());
    kv("size_int8", &size_of::<i8>().to_string());
    kv("size_int16", &size_of::<i16>().to_string());
    kv("size_int32", &size_of::<i32>().to_string());
    kv("size_int64", &size_of::<i64>().to_string());
    kv("size_uint8", &size_of::<u8>().to_string());
    kv("size_uint16", &size_of::<u16>().to_string());
    kv("size_uint32", &size_of::<u32>().to_string());
    kv("size_uint64", &size_of::<u64>().to_string());
    kv("size_float32", &size_of::<f32>().to_string());
    kv("size_float64", &size_of::<f64>().to_string());
    kv("size_bool", &size_of::<bool>().to_string());
    kv("size_char", &size_of::<char>().to_string());
    kv("char_meaning", "char is a 4-byte Unicode scalar value (never a surrogate); u8 is the byte type");
    probe("int32_max_plus_1", || (black_box(i32::MAX) + 1).to_string());
    probe("int64_max_plus_1", || (black_box(i64::MAX) + 1).to_string());
    probe("uint8_255_plus_1", || (black_box(255u8) + 1).to_string());
    probe("uint32_0_minus_1", || (black_box(0u32) - 1).to_string());
    probe("int_div_m7_2", || (black_box(-7i32) / 2).to_string());
    probe("int_mod_m7_2", || (black_box(-7i32) % 2).to_string());
    probe("int_div_by_zero", || (black_box(1i32) / black_box(0)).to_string());
    probe("f64_0_1_plus_0_2", || fmt17(black_box(0.1f64) + black_box(0.2)));
    probe("f32_16777217_roundtrip", || fmt17((black_box(16777217i32) as f32) as f64));
    probe("f64_2p53_plus_1", || fmt17(black_box(9007199254740992.0f64) + 1.0));
    probe("f64_nan_eq_nan", || { let n = black_box(f64::NAN); (n == n).to_string() });
    probe("f64_1_div_0", || fmt17(black_box(1.0f64) / black_box(0.0)));
    probe("f64_neg1_div_0", || fmt17(black_box(-1.0f64) / black_box(0.0)));
    probe("f64_0_div_0", || fmt17(black_box(0.0f64) / black_box(0.0)));
    probe("i64_2p53p1_via_f64", || ((black_box(9007199254740993i64) as f64) as i64).to_string());
    strprobe("str_e_pre", "\u{00e9}");
    strprobe("str_e_comb", "e\u{0301}");
    strprobe("str_emoji", "\u{1F600}");
    kv("date_epoch_day_2015_01_01", "n/a");
    kv("timestamp_max_precision", "ns");
    probe("empty_array_index0", || { let v: Vec<i32> = black_box(Vec::new()); v[0].to_string() });
    probe("empty_array_max", || { let v: Vec<i32> = black_box(Vec::new()); match v.iter().max() { Some(m) => m.to_string(), None => "none".into() } });
    probe("empty_string_index0", || { let s = black_box(String::new()); s[0..1].to_string() });
    probe("empty_string_split_count", || black_box(String::new()).split(',').count().to_string());
    {
        let mut orders = BTreeSet::new();
        for _ in 0..200 {
            let mut m = HashMap::new();
            m.insert(3, 0); m.insert(1, 0); m.insert(2, 0);
            let o: Vec<String> = m.keys().map(|k| k.to_string()).collect();
            orders.insert(o.join(","));
        }
        if orders.len() > 1 { kv("map_order_3_1_2", "randomized"); } else { kv("map_order_3_1_2", orders.iter().next().unwrap()); }
    }
    kv("decimal_0_1_plus_0_2", "n/a");
    let mut s = 0.0f64;
    for _ in 0..10_000_000 { s += black_box(0.1); }
    kv("f64_sum_10m_0_1", &fmt17(s));
}
