mod csv;
mod hash;
mod ops;

use csv::{parse_chunk, Columns};
use hash::Digest;
use ops::*;
use std::path::PathBuf;
use std::time::Instant;

struct Args {
    op: String,
    rows: u64,
    materialized: bool,
    chunk_rows: usize,
    input: PathBuf,
}

fn parse_args() -> Result<Args, String> {
    let mut a = Args { op: String::new(), rows: 0, materialized: false, chunk_rows: 1_000_000, input: PathBuf::new() };
    let mut it = std::env::args().skip(1);
    while let Some(k) = it.next() {
        match k.as_str() {
            "--output-json" => {}
            _ => {
                let v = it.next().ok_or(format!("missing value for {k}"))?;
                match k.as_str() {
                    "--op" => a.op = v,
                    "--dataset" | "--threads" => {}
                    "--rows" => a.rows = v.parse().map_err(|_| "bad --rows")?,
                    "--mode" => a.materialized = v == "materialized",
                    "--chunk-rows" => a.chunk_rows = v.parse().map_err(|_| "bad --chunk-rows")?,
                    "--input" => a.input = PathBuf::from(v),
                    _ => return Err(format!("unknown arg {k}")),
                }
            }
        }
    }
    Ok(a)
}

fn label(rows: u64) -> String {
    match rows {
        1_000 => "1k".into(),
        10_000 => "10k".into(),
        1_000_000 => "1m".into(),
        10_000_000 => "10m".into(),
        100_000_000 => "100m".into(),
        1_000_000_000 => "1b".into(),
        n => n.to_string(),
    }
}

fn ms(t: std::time::Duration) -> f64 {
    t.as_secs_f64() * 1000.0
}

/// Returns (load_ms, compute_ms).
fn drive<const M: u32, O: Op>(files: &[PathBuf], a: &Args, op: &mut O) -> Result<(f64, f64), String> {
    let (mut load, mut comp) = (0.0, 0.0);
    let mut cols = Columns::default();
    let rd = |f: &PathBuf| std::fs::read(f).map_err(|e| format!("{}: {e}", f.display()));
    if a.materialized {
        let t = Instant::now();
        cols.reserve(M, a.rows as usize);
        for f in files {
            let buf = rd(f)?;
            parse_chunk::<M>(&buf, &mut cols);
        }
        load += ms(t.elapsed());
        let t = Instant::now();
        op.consume(&cols);
        comp += ms(t.elapsed());
    } else {
        cols.reserve(M, a.chunk_rows);
        for f in files {
            let t = Instant::now();
            let buf = rd(f)?;
            cols.clear();
            parse_chunk::<M>(&buf, &mut cols);
            load += ms(t.elapsed());
            drop(buf);
            let t = Instant::now();
            op.consume(&cols);
            comp += ms(t.elapsed());
        }
    }
    Ok((load, comp))
}

fn finish<O: Op>(files: &[PathBuf], a: &Args, mut op: O, m: u32) -> Result<(f64, f64, Digest, Vec<(&'static str, f64)>), String> {
    macro_rules! go {
        ($($mask:ident),*) => {
            match m {
                $( x if x == $mask => drive::<{ $mask }, O>(files, a, &mut op)?, )*
                _ => unreachable!(),
            }
        };
    }
    let (l, c) = go!(OP01_MASK, OP03_MASK, OP04_MASK, OP05_MASK, OP10_MASK, OP19_MASK, OP21_MASK, OP22_MASK);
    let mut d = Digest::default();
    let fl = op.digest(&mut d);
    Ok((l, c, d, fl))
}

fn run(a: &Args) -> Result<String, String> {
    let dir = a.input.join("sales_fact").join(label(a.rows));
    let mut files: Vec<PathBuf> = std::fs::read_dir(&dir)
        .map_err(|e| format!("{}: {e}", dir.display()))?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().map_or(false, |x| x == "csv"))
        .collect();
    files.sort();
    if files.is_empty() {
        return Err(format!("no csv files in {}", dir.display()));
    }
    let (load, comp, digest, floats) = match a.op.as_str() {
        "OP01" => finish(&files, a, Op01::default(), OP01_MASK)?,
        "OP03" => finish(&files, a, Op03::default(), OP03_MASK)?,
        "OP04" => finish(&files, a, Op04::default(), OP04_MASK)?,
        "OP05" => finish(&files, a, Op05::default(), OP05_MASK)?,
        "OP10" => finish(&files, a, Op10::default(), OP10_MASK)?,
        "OP19" => finish(&files, a, Op19::default(), OP19_MASK)?,
        "OP21" => finish(&files, a, Op21::default(), OP21_MASK)?,
        "OP22" => finish(&files, a, Op22::default(), OP22_MASK)?,
        "OP15" => {
            // Parsing is the operation: compute_ms = read + parse + summarise, load_ms = 0.
            let mut op = Op15::default();
            let t = Instant::now();
            for f in &files {
                let buf = std::fs::read(f).map_err(|e| format!("{}: {e}", f.display()))?;
                op.parse(&buf);
            }
            let c = ms(t.elapsed());
            let mut d = Digest::default();
            op.digest(&mut d);
            (0.0, c, d, vec![])
        }
        o => return Err(format!("unsupported op {o}")),
    };
    let ver = std::process::Command::new("rustc")
        .arg("--version")
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .and_then(|s| s.split_whitespace().nth(1).map(|v| v.to_string()))
        .unwrap_or_else(|| "unknown".into());
    let mut js = format!(
        "{{\"load_ms\": {:.3}, \"compute_ms\": {:.3}, \"checksum\": \"{}\", \"row_count\": {}",
        load, comp, digest.checksum(), digest.count
    );
    if !floats.is_empty() {
        let f: Vec<String> = floats.iter().map(|(k, v)| format!("\"{k}\": {v:?}")).collect();
        js.push_str(&format!(", \"floats\": {{{}}}", f.join(", ")));
    }
    js.push_str(&format!(
        ", \"toolchain\": {{\"name\": \"rustc\", \"version\": \"{ver}\", \"flags\": \"--release opt-level=3 lto=thin\"}}, \"notes\": \"\"}}"
    ));
    Ok(js)
}

fn main() {
    let a = match parse_args() {
        Ok(a) => a,
        Err(e) => {
            eprintln!("error: {e}");
            std::process::exit(2);
        }
    };
    match run(&a) {
        Ok(js) => println!("{js}"),
        Err(e) => {
            eprintln!("error: {e}");
            std::process::exit(1);
        }
    }
}
