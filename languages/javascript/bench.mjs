// Generated from languages/typescript/bench.mts; run node languages/typescript/emit-javascript.mjs.
import { openSync, readSync, closeSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { StringDecoder } from 'node:string_decoder';
import { performance } from 'node:perf_hooks';









const NEEDS                           = {
    OP01: [4, 5, 12], OP03: [4, 5, 8], OP04: [1, 5], OP05: [5, 8, 9, 10],
    OP06: [1, 4, 5], OP07: [1, 2, 5], OP08: [0, 11], OP09: [1, 5],
    OP10: [1, 2, 3, 10], OP15: Array.from({ length: 13 }, (_, i) => i),
    OP19: [4, 8], OP21: [5], OP22: [0, 1, 5, 10, 11],
};
const MASK = (1n << 64n) - 1n;

export function floorDiv(a        , b        )         {
    const q = a / b;
    return a % b < 0n ? q - 1n : q;
}

export function cents(text        )         {
    const m = /^([+-]?)(\d+)(?:\.(\d{1,2}))?$/.exec(text);
    if (!m) throw new Error(`invalid decimal: ${text}`);
    const value = BigInt(m[2]) * 100n + BigInt((m[3] ?? '').padEnd(2, '0'));
    return m[1] === '-' ? -value : value;
}

function dateParts(text        )           {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
    if (!m) throw new Error(`invalid date: ${text}`);
    return [Number(m[1]), Number(m[2]), Number(m[3])];
}

function daysFromCivil(y        , m        , d        )         {
    y -= m <= 2 ? 1 : 0;
    const era = Math.floor(y / 400), yoe = y - era * 400;
    const doy = Math.floor((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5) + d - 1;
    return era * 146097 + yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy - 719468;
}

export function civilFromDays(days        )           {
    const z = days + 719468, era = Math.floor(z / 146097), doe = z - era * 146097;
    const yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365);
    const y = yoe + era * 400, doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
    const mp = Math.floor((5 * doy + 2) / 153), d = doy - Math.floor((153 * mp + 2) / 5) + 1;
    const m = mp + (mp < 10 ? 3 : -9);
    return [y + (m <= 2 ? 1 : 0), m, d];
}

export function timestamp(text        )         {
    const m = /^(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?$/.exec(text);
    if (!m) throw new Error(`invalid timestamp: ${text}`);
    const [y, month, d] = dateParts(m[1]);
    const seconds = Number(m[2]) * 3600 + Number(m[3]) * 60 + Number(m[4]);
    return BigInt(daysFromCivil(y, month, d)) * 86400000000n + BigInt(seconds) * 1000000n
        + BigInt((m[5] ?? '').padEnd(6, '0'));
}

// Schema strings have no embedded newlines. Read only dimension fields before quoted JSON.
export function csvFields(line        , limit = Infinity)                    {
    if (!line.includes('"')) return line.split(',').slice(0, limit).map(s => s === '\\N' ? null : s);
    const fields                    = [];
    let i = 0;
    while (i <= line.length && fields.length < limit) {
        const quoted = line[i] === '"';
        let value = '';
        if (quoted) {
            i++;
            let closed = false;
            while (i < line.length) {
                if (line[i] !== '"') value += line[i++];
                else if (line[i + 1] === '"') { value += '"'; i += 2; }
                else { i++; closed = true; break; }
            }
            if (!closed || (i < line.length && line[i] !== ',')) throw new Error('malformed CSV quoting');
        } else {
            const start = i;
            while (i < line.length && line[i] !== ',') i++;
            value = line.slice(start, i);
        }
        fields.push(!quoted && value === '\\N' ? null : value);
        if (i === line.length) break;
        i++;
    }
    return fields;
}

function* lines(path        )                    {
    const fd = openSync(path, 'r'), bytes = Buffer.allocUnsafe(1 << 16), decoder = new StringDecoder('utf8');
    let carry = '', header = true;
    try {
        for (;;) {
            const n = readSync(fd, bytes, 0, bytes.length, null);
            carry += n ? decoder.write(bytes.subarray(0, n)) : decoder.end();
            let start = 0, end        ;
            while ((end = carry.indexOf('\n', start)) !== -1) {
                const line = carry.slice(start, end).replace(/\r$/, '');
                start = end + 1;
                if (header) header = false;
                else if (line.length) yield line;
            }
            carry = carry.slice(start);
            if (!n) break;
        }
        if (!header && carry.length) yield carry.replace(/\r$/, '');
    } finally { closeSync(fd); }
}

function files(root        , table        , label        )           {
    const dir = join(root, table, label);
    const names = readdirSync(dir).filter(f => /^part-.*\.csv$/.test(f)).sort();
    if (!names.length) throw new Error(`no CSV chunks in ${dir}`);
    return names.map(f => join(dir, f));
}

function batch()        {
    return { n: 0, tid: [], cid: [], pid: [], store: [], qty: [], cents: [], discount: [], tax: [],
        country: [], category: [], days: [], ts: [], returned: [] };
}

function append(b       , line        , need          )       {
    const f = csvFields(line);
    if (f.length !== 13) throw new Error('sales row must have 13 fields');
    for (const col of need) {
        const s = f[col];
        if (s === null && col !== 4 && col !== 8 && col !== 9) throw new Error(`NULL in required field ${col}`);
        switch (col) {
            case 0: b.tid.push(BigInt(s )); break;
            case 1: b.cid.push(BigInt(s )); break;
            case 2: b.pid.push(BigInt(s )); break;
            case 3: b.store.push(BigInt(s )); break;
            case 4: b.qty.push(s === null ? null : BigInt(s)); break;
            case 5: b.cents.push(cents(s )); break;
            case 6: b.discount.push(Number(s)); break;
            case 7: b.tax.push(Number(s)); break;
            case 8: b.country.push(s); break;
            case 9: b.category.push(s); break;
            case 10: { const [y, m, d] = dateParts(s ); b.days.push(daysFromCivil(y, m, d)); break; }
            case 11: b.ts.push(timestamp(s )); break;
            case 12:
                if (s !== 'true' && s !== 'false') throw new Error('invalid boolean');
                b.returned.push(s === 'true'); break;
        }
    }
    b.n++;
}

function* batches(paths          , need          , chunkRows        )                   {
    let b = batch();
    for (const path of paths) for (const line of lines(path)) {
        append(b, line, need);
        if (b.n === chunkRows) { yield b; b = batch(); }
    }
    if (b.n) yield b;
}

function dimensions(root        , table        , label        , col        )                             {
    const dim = new Map                       ();
    for (const path of files(root, table, label)) for (const line of lines(path)) {
        const f = csvFields(line, col + 1);
        if (f.length !== col + 1 || f[0] === null) throw new Error('short dimension row');
        dim.set(BigInt(f[0]), f[col]);
    }
    return dim;
}

export function digest(rows          )                                          {
    function mix(z        )         {
        z = ((z ^ (z >> 30n)) * 0xBF58476D1CE4E5B9n) & MASK;
        z = ((z ^ (z >> 27n)) * 0x94D049BB133111EBn) & MASK;
        return z ^ (z >> 31n);
    }
    let sum = 0n, xor = 0n;
    for (const row of rows) {
        let h = 0n;
        for (const v of row) {
            let canon        ;
            if (v === null) canon = 0xA5A5A5A5A5A5A5A5n;
            else if (typeof v === 'string') {
                canon = 0xCBF29CE484222325n;
                for (const byte of Buffer.from(v, 'utf8')) canon = ((canon ^ BigInt(byte)) * 0x100000001B3n) & MASK;
            } else {
                if (typeof v === 'number' && !Number.isSafeInteger(v)) throw new Error('unsafe integer result');
                canon = BigInt(v) & MASK;
            }
            h = mix((h + canon + 0x9E3779B97F4A7C15n) & MASK);
        }
        sum = (sum + h) & MASK; xor ^= h;
    }
    return { checksum: sum.toString(16).padStart(16, '0') + xor.toString(16).padStart(16, '0'), row_count: rows.length };
}

class Operation {
    groups = new Map                               ();
    customers = new Map                       ();
    products = new Map                       ();
    distinctC = new Set        (); distinctP = new Set        (); distinctSD = new Set        ();
    countries = new Set        ();
    sums = Array        (17).fill(0n);
    count = 0; qtyCount = 0; min                = null; max                = null;
    naive = 0; kahan = 0; compensation = 0;
    sorted                                = [];
    op        ;

    constructor(op        ) { this.op = op; }

    group(id                        , key        , price        , qty                = null)       {
        let g = this.groups.get(id);
        if (!g) {
            g = { key, count: 0, cents: 0n, qty: 0n, hasQty: false };
            this.groups.set(id, g);
        }
        g.count++; g.cents += price;
        if (qty !== null) { g.qty += qty; g.hasQty = true; }
    }

    consume(b       )       {
        const s = this.sums;
        for (let i = 0; i < b.n; i++) {
            const price = b.cents[i], qty = b.qty[i], country = b.country[i];
            switch (this.op) {
                case 'OP01':
                    this.count++; s[0] += price;
                    if (qty !== null) { this.qtyCount++; s[1] += qty; }
                    if (this.min === null || price < this.min) this.min = price;
                    if (this.max === null || price > this.max) this.max = price;
                    if (b.returned[i]) s[2]++;
                    break;
                case 'OP03': this.group(country, [country], price, qty); break;
                case 'OP04': case 'OP09': this.group(b.cid[i], [b.cid[i]], price); break;
                case 'OP05': {
                    const key = [country, b.category[i], civilFromDays(b.days[i])[0]];
                    this.group(JSON.stringify(key), key, price); break;
                }
                case 'OP06':
                    if (this.customers.has(b.cid[i])) {
                        const key = this.customers.get(b.cid[i]) ;
                        this.group(key, [key], price, qty);
                    }
                    break;
                case 'OP07':
                    if (this.customers.get(b.cid[i]) === 'enterprise' && this.products.has(b.pid[i])) {
                        const key = this.products.get(b.pid[i]) ;
                        this.group(key, [key], price);
                    }
                    break;
                case 'OP08': this.sorted.push({ tid: b.tid[i], ts: b.ts[i] }); break;
                case 'OP10':
                    this.distinctC.add(b.cid[i]); this.distinctP.add(b.pid[i]);
                    this.distinctSD.add(`${b.store[i]}/${b.days[i]}`); break;
                case 'OP15': {
                    s[0]++; s[1] += b.tid[i]; s[2] += b.cid[i]; s[3] += b.pid[i]; s[4] += b.store[i];
                    if (qty === null) s[6]++; else s[5] += qty;
                    s[7] += price; s[8] += BigInt(Math.floor(b.discount[i] * 1e6 + 0.5));
                    s[9] += BigInt(Math.floor(b.tax[i] * 1e6 + 0.5));
                    if (country === null) s[11]++; else s[10] += BigInt(Buffer.byteLength(country, 'utf8'));
                    if (b.category[i] !== null) s[12] += BigInt(Buffer.byteLength(b.category[i] , 'utf8'));
                    s[13] += BigInt(b.days[i]);
                    const sec = floorDiv(b.ts[i], 1000000n);
                    s[14] += sec; s[15] += b.ts[i] - sec * 1000000n;
                    if (b.returned[i]) s[16]++;
                    break;
                }
                case 'OP19':
                    if (qty === null) { s[0]++; s[2]++; } else s[2] += qty;
                    if (country === null) s[1]++;
                    else { this.countries.add(country); if (country !== '') s[3]++; }
                    break;
                case 'OP21': {
                    s[0] += price;
                    const value = Number(price) / 100.0;
                    this.naive += value;
                    const y = value - this.compensation, t = this.kahan + y;
                    this.compensation = (t - this.kahan) - y; this.kahan = t;
                    break;
                }
                case 'OP22': {
                    const k = b.tid[i] * 4294967311n + b.cid[i];
                    if (BigInt(Number(k)) !== k) s[0]++;
                    if (BigInt(Math.trunc((Number(price) / 100.0) * 100.0)) !== price) s[1]++;
                    if (floorDiv(b.ts[i], 1000n) * 1000n !== b.ts[i]) s[2]++;
                    const [y, m, d] = civilFromDays(b.days[i]);
                    s[3] += BigInt(y * 10000 + m * 100 + d); break;
                }
            }
        }
    }

    result()           {
        const s = this.sums;
        switch (this.op) {
            case 'OP01': return [[this.count, this.qtyCount, this.qtyCount ? s[1] : null, s[0], this.min, this.max, s[2]]];
            case 'OP03': return Array.from(this.groups.values(), g => [...g.key, g.count, g.hasQty ? g.qty : null, g.cents]);
            case 'OP04': case 'OP05': case 'OP07': return Array.from(this.groups.values(), g => [...g.key, g.count, g.cents]);
            case 'OP06': return Array.from(this.groups.values(), g => [...g.key, g.count, g.cents, g.hasQty ? g.qty : null]);
            case 'OP08': {
                this.sorted.sort((a, b) => compare(a.ts, b.ts) || compare(a.tid, b.tid));
                let pos = 0n;
                for (let i = 0; i < this.sorted.length; i++) pos = (pos + BigInt(i + 1) * this.sorted[i].tid) & MASK;
                return [[this.sorted[0]?.tid ?? null, this.sorted.at(-1)?.tid ?? null, pos]];
            }
            case 'OP09': {
                // Standard Array.sort over group totals; no generated-value assumptions.
                const top = Array.from(this.groups.values()).sort((a, b) => compare(b.cents, a.cents)
                    || compare(a.key[0]          , b.key[0]          )).slice(0, 100);
                return top.map((g, i) => [i + 1, g.key[0], g.cents]);
            }
            case 'OP10': return [[this.distinctC.size, this.distinctP.size, this.distinctSD.size]];
            case 'OP15': return [s];
            case 'OP19': return [[s[0], s[1], s[2], s[3], this.countries.size]];
            case 'OP21': {
                const whole = floorDiv(s[0], 100n), frac = s[0] - whole * 100n;
                return [[s[0], `${whole}.${frac.toString().padStart(2, '0')}`]];
            }
            case 'OP22': return [s.slice(0, 4)];
            default: throw new Error(`unsupported operation: ${this.op}`);
        }
    }
}

function compare(a        , b        )         { return a < b ? -1 : a > b ? 1 : 0; }

export function main(args          )       {
    const opts                         = {};
    for (let i = 0; i < args.length; i++) {
        if (args[i] === '--output-json') continue;
        if (!args[i].startsWith('--') || i + 1 >= args.length) throw new Error('expected --key value');
        opts[args[i].slice(2)] = args[++i];
    }
    const op = opts.op, mode = opts.mode ?? 'streaming', rows = Number(opts.rows);
    const labels                         = { 1000: '1k', 10000: '10k', 1000000: '1m', 10000000: '10m', 100000000: '100m', 1000000000: '1b' };
    const label = labels[rows], root = opts.input ?? 'data', chunkRows = Number(opts['chunk-rows'] ?? 1000000);
    if (!NEEDS[op]) throw new Error(`unsupported operation: ${op}`);
    if ((opts.dataset ?? 'A') !== 'A') throw new Error('only dataset A supported');
    if (!label || !Number.isSafeInteger(chunkRows) || chunkRows <= 0) throw new Error('invalid rows or chunk-rows');
    if (Number(opts.threads ?? 1) !== 1) throw new Error('stdlib implementations require --threads 1');
    if (!['streaming', 'materialized'].includes(mode)) throw new Error('invalid mode');
    if (op === 'OP08' && mode !== 'materialized') throw new Error('OP08 is materialized only');
    const state = new Operation(op), paths = files(root, 'sales_fact', label);
    let load = 0, compute = 0;
    let t = performance.now();
    if (op === 'OP06' || op === 'OP07') state.customers = dimensions(root, 'dim_customer', label, 4);
    if (op === 'OP07') state.products = dimensions(root, 'dim_product', label, 2);
    load += performance.now() - t;
    let result          ;
    if (op === 'OP15') {
        // Parsing is the operation, regardless of the requested mode; no raw rows retained.
        t = performance.now();
        for (const b of batches(paths, NEEDS[op], chunkRows)) state.consume(b);
        result = state.result(); compute = performance.now() - t; load = 0;
    } else {
        if (mode === 'materialized') {
            t = performance.now();
            const all = Array.from(batches(paths, NEEDS[op], chunkRows));
            load += performance.now() - t;
            t = performance.now();
            for (const b of all) state.consume(b);
            result = state.result(); compute += performance.now() - t;
        } else {
            const iterator = batches(paths, NEEDS[op], chunkRows);
            for (;;) {
                t = performance.now(); const next = iterator.next(); load += performance.now() - t;
                if (next.done) break;
                t = performance.now(); state.consume(next.value); compute += performance.now() - t;
            }
            t = performance.now(); result = state.result(); compute += performance.now() - t;
        }
    }
    const floats = op === 'OP21' ? { naive_sum: state.naive, kahan_sum: state.kahan } : undefined;
    // Digest, serialization and stdout are outside all timing boundaries.
    console.log(JSON.stringify({ load_ms: load, compute_ms: compute, ...digest(result), floats,
        toolchain: { name: 'node', version: process.version, flags: process.execArgv.join(' ') },
        notes: 'Single-threaded Node/V8; exact integers use BigInt; OP15 includes read+parse+summarise.' }));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
    try { main(process.argv.slice(2)); }
    catch (error) { console.error(error instanceof Error ? error.message : String(error)); process.exitCode = 1; }
}
