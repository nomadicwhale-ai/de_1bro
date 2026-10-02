//! Dimension tables (dim_customer, dim_product): only the leading fields are read, the rest of the
//! line (quoted JSON in dim_product) is ignored without quote handling.
use crate::csv::*;
use crate::hash::*;
use std::path::Path;

#[derive(Default)]
pub struct Dims {
    pub cust: FxMap<i64, u32>, // customer_id -> index into segs
    pub segs: Vec<Vec<u8>>,
    pub prod: FxMap<i64, u32>, // product_id -> index into brands
    pub brands: Vec<Vec<u8>>,
}

fn read_table(dir: &Path) -> Result<Vec<u8>, String> {
    let mut files: Vec<_> = std::fs::read_dir(dir)
        .map_err(|e| format!("{}: {e}", dir.display()))?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().map_or(false, |x| x == "csv"))
        .collect();
    files.sort();
    let mut all = Vec::new();
    for f in files {
        let b = std::fs::read(&f).map_err(|e| format!("{}: {e}", f.display()))?;
        let h = after_header(&b);
        all.extend_from_slice(&b[h..]);
        if all.last().map_or(false, |&c| c != b'\n') {
            all.push(b'\n');
        }
    }
    Ok(all)
}

fn intern(map: &mut FxMap<Vec<u8>, u32>, list: &mut Vec<Vec<u8>>, s: &[u8]) -> u32 {
    if let Some(&g) = map.get(s) {
        return g;
    }
    let g = list.len() as u32;
    list.push(s.to_vec());
    map.insert(s.to_vec(), g);
    g
}

impl Dims {
    /// customer_id,name,email,signup_date,segment,...
    pub fn load_customers(&mut self, dir: &Path) -> Result<(), String> {
        let buf = read_table(dir)?;
        let mut dict = FxMap::default();
        let mut p = 0;
        while p < buf.len() {
            if buf[p] == b'\n' || buf[p] == b'\r' {
                p += 1;
                continue;
            }
            let id = read_int(&buf, &mut p).ok_or("NULL customer_id")?;
            skip(&buf, &mut p);
            skip(&buf, &mut p);
            skip(&buf, &mut p);
            let seg = field(&buf, &mut p);
            let g = intern(&mut dict, &mut self.segs, seg);
            self.cust.insert(id, g);
            p = end_row(&buf, p);
        }
        Ok(())
    }
    /// product_id,category,brand,... (remaining quoted JSON fields ignored)
    pub fn load_products(&mut self, dir: &Path) -> Result<(), String> {
        let buf = read_table(dir)?;
        let mut dict = FxMap::default();
        let mut p = 0;
        while p < buf.len() {
            if buf[p] == b'\n' || buf[p] == b'\r' {
                p += 1;
                continue;
            }
            let id = read_int(&buf, &mut p).ok_or("NULL product_id")?;
            skip(&buf, &mut p);
            let brand = field(&buf, &mut p);
            let g = intern(&mut dict, &mut self.brands, brand);
            self.prod.insert(id, g);
            p = end_row(&buf, p);
        }
        Ok(())
    }
}
