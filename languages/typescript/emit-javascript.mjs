// Node's built-in type stripper: no npm packages or TypeScript compiler required.
import { readFileSync, writeFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';

const source = new URL('./bench.mts', import.meta.url);
const target = new URL('../javascript/bench.mjs', import.meta.url);
const generated = '// Generated from languages/typescript/bench.mts; run node languages/typescript/emit-javascript.mjs.\n'
    + stripTypeScriptTypes(readFileSync(source, 'utf8'), { mode: 'strip' })
        .split('\n').map(line => line.trimEnd()).join('\n');
if (process.argv.includes('--check')) {
    if (readFileSync(target, 'utf8') !== generated) {
        console.error('JavaScript source is stale: run node languages/typescript/emit-javascript.mjs');
        process.exitCode = 1;
    }
} else {
    writeFileSync(target, generated);
}
