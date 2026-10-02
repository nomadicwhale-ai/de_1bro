// Conformance probe (TypeScript). Same logic as ../javascript/main.js; compiled with tsc, run with node.
declare const process: any;

const out: string[] = [];
const kv = (k: string, v: any) => out.push(`${k}=${v}`);
const probe = (k: string, f: () => string) => { try { kv(k, f()); } catch (e) { kv(k, 'exception'); } };
const fmt17 = (x: number) => {
  if (Number.isNaN(x)) return 'nan';
  if (x === Infinity) return 'inf';
  if (x === -Infinity) return '-inf';
  let s = x.toPrecision(17);
  if (s.includes('.') && !s.includes('e')) s = s.replace(/0+$/, '').replace(/\.$/, '');
  return s;
};
const strprobe = (p: string, s: string) => {
  kv(`${p}_utf8`, new TextEncoder().encode(s).length);
  kv(`${p}_utf16`, s.length);
  kv(`${p}_scalars`, [...s].length);
};
kv('lang', 'typescript');
kv('version', 'node ' + process.version + ' tsc ' + (process.env.TSC_VERSION || 'unknown'));
kv('size_int8', Int8Array.BYTES_PER_ELEMENT);
kv('size_int16', Int16Array.BYTES_PER_ELEMENT);
kv('size_int32', Int32Array.BYTES_PER_ELEMENT);
kv('size_int64', BigInt64Array.BYTES_PER_ELEMENT);
kv('size_uint8', Uint8Array.BYTES_PER_ELEMENT);
kv('size_uint16', Uint16Array.BYTES_PER_ELEMENT);
kv('size_uint32', Uint32Array.BYTES_PER_ELEMENT);
kv('size_uint64', BigUint64Array.BYTES_PER_ELEMENT);
kv('size_float32', Float32Array.BYTES_PER_ELEMENT);
kv('size_float64', Float64Array.BYTES_PER_ELEMENT);
kv('size_bool', 'n/a');
kv('size_char', 'n/a');
kv('char_meaning', 'no char type; a string is a sequence of UTF-16 code units; sizes above are typed-array element sizes, plain number is a float64');
probe('int32_max_plus_1', () => String(2147483647 + 1));            // Number: no int32 overflow
probe('int64_max_plus_1', () => String(9223372036854775807n + 1n)); // BigInt: arbitrary precision
probe('uint8_255_plus_1', () => String(255 + 1));
probe('uint32_0_minus_1', () => String(0 - 1));
probe('int_div_m7_2', () => String(-7 / 2));
probe('int_mod_m7_2', () => String(-7 % 2));
probe('int_div_by_zero', () => fmt17(1 / 0));
probe('f64_0_1_plus_0_2', () => fmt17(0.1 + 0.2));
probe('f32_16777217_roundtrip', () => fmt17(Math.fround(16777217)));
probe('f64_2p53_plus_1', () => fmt17(9007199254740992 + 1));
probe('f64_nan_eq_nan', () => { const n = parseFloat('NaN'); return String(n === n); });
probe('f64_1_div_0', () => fmt17(1 / 0));
probe('f64_neg1_div_0', () => fmt17(-1 / 0));
probe('f64_0_div_0', () => fmt17(0 / 0));
probe('i64_2p53p1_via_f64', () => String(BigInt(Number(9007199254740993n))));
strprobe('str_e_pre', 'é');
strprobe('str_e_comb', 'é');
strprobe('str_emoji', '\u{1F600}');
probe('date_epoch_day_2015_01_01', () => String(Date.UTC(2015, 0, 1) / 86400000));
kv('timestamp_max_precision', 'ms');
probe('empty_array_index0', () => String([][0]));
probe('empty_array_max', () => fmt17(Math.max(...[])));
probe('empty_string_index0', () => String(''[0]));
probe('empty_string_split_count', () => String(''.split(',').length));
probe('map_order_3_1_2', () => { const m = new Map(); m.set(3, 0); m.set(1, 0); m.set(2, 0); return [...m.keys()].join(','); });
kv('decimal_0_1_plus_0_2', 'n/a');
probe('f64_sum_10m_0_1', () => { let s = 0; for (let i = 0; i < 10000000; i++) s += 0.1; return fmt17(s); });
console.log(out.join('\n'));
