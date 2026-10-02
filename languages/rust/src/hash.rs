//! Own implementations of mix64, FNV-1a, the result digest and a fast (non-SipHash) BuildHasher.
use std::hash::{BuildHasherDefault, Hasher};

pub const GOLDEN: u64 = 0x9E37_79B9_7F4A_7C15;
const C1: u64 = 0xBF58_476D_1CE4_E5B9;
const C2: u64 = 0x94D0_49BB_1331_11EB;
const NULL_CANON: u64 = 0xA5A5_A5A5_A5A5_A5A5;

#[inline]
pub fn mix64(mut z: u64) -> u64 {
    z ^= z >> 30;
    z = z.wrapping_mul(C1);
    z ^= z >> 27;
    z = z.wrapping_mul(C2);
    z ^ (z >> 31)
}

#[inline]
pub fn fnv1a(b: &[u8]) -> u64 {
    let mut h: u64 = 0xCBF2_9CE4_8422_2325;
    for &x in b {
        h = (h ^ x as u64).wrapping_mul(0x0000_0100_0000_01B3);
    }
    h
}

/// Result value (ints, strings, NULL). Floats are never digested.
pub enum V<'a> {
    Null,
    I(i64),
    S(&'a [u8]),
}

#[derive(Default)]
pub struct Digest {
    pub count: u64,
    sum: u64,
    xor: u64,
}

impl Digest {
    pub fn add(&mut self, row: &[V]) {
        let mut h = 0u64;
        for v in row {
            let c = match v {
                V::Null => NULL_CANON,
                V::I(i) => *i as u64,
                V::S(s) => fnv1a(s),
            };
            h = mix64(h.wrapping_add(c).wrapping_add(GOLDEN));
        }
        self.count += 1;
        self.sum = self.sum.wrapping_add(h);
        self.xor ^= h;
    }
    pub fn checksum(&self) -> String {
        format!("{:016x}{:016x}", self.sum, self.xor)
    }
}

/// FxHash-style hasher (multiply/rotate), replacing std's default SipHash-1-3.
/// SipHash is DoS-resistant but several times slower on short keys; benchmark inputs are trusted.
/// `finish` rotates so that hashbrown's low-bit bucket index uses the well-mixed high product bits.
#[derive(Default, Clone, Copy)]
pub struct Fx(u64);

const K: u64 = 0x517C_C1B7_2722_0A95;

impl Fx {
    #[inline]
    fn add(&mut self, x: u64) {
        self.0 = (self.0.rotate_left(5) ^ x).wrapping_mul(K);
    }
}

impl Hasher for Fx {
    #[inline]
    fn write(&mut self, bytes: &[u8]) {
        let mut it = bytes.chunks_exact(8);
        for c in &mut it {
            self.add(u64::from_le_bytes([c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7]]));
        }
        let r = it.remainder();
        if !r.is_empty() {
            let mut t = [0u8; 8];
            t[..r.len()].copy_from_slice(r);
            self.add(u64::from_le_bytes(t));
        }
    }
    #[inline]
    fn write_u64(&mut self, i: u64) {
        self.add(i);
    }
    #[inline]
    fn write_usize(&mut self, i: usize) {
        self.add(i as u64);
    }
    #[inline]
    fn finish(&self) -> u64 {
        self.0.rotate_left(26)
    }
}

pub type FxBuild = BuildHasherDefault<Fx>;
pub type FxMap<K, V> = std::collections::HashMap<K, V, FxBuild>;
pub type FxSet<K> = std::collections::HashSet<K, FxBuild>;
