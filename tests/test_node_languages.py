"""Node JS/TS regressions: exact integers, CSV edges, joins and batch/file boundaries."""
import csv
import datetime as dt
import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from generator.resultdigest import digest_rows
from runner.ref_ops import NEEDS_DIMS, REF

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
IMPLEMENTATIONS = ["languages/javascript/bench.mjs", "languages/typescript/bench.mts"]


def node(cmd, **kwargs):
    return subprocess.run([NODE, "--experimental-strip-types", *cmd], cwd=ROOT,
                          text=True, capture_output=True, timeout=60, **kwargs)


@pytest.fixture(scope="module", autouse=True)
def supported_node():
    if NODE:
        major, minor = map(int, node(["--version"]).stdout.strip().lstrip("v").split(".")[:2])
        if (major, minor) < (22, 23):
            pytest.skip("requires Node.js >=22.23.1 with built-in TypeScript stripping")


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    out = tmp_path_factory.mktemp("node-csv")
    rows = []
    for i in range(125):
        # Adjacent keys beyond binary64's exact range, negative/zero money, NULL vs empty,
        # composed/decomposed Unicode, all-NULL groups, and ties in both sorts.
        cid = 9007199254740993 + i
        country = [None, "", "Café", "Café", 'x,"y"', "Côte d'Ivoire 🇨🇮"][i % 6]
        if i == 17:
            country = "é🇨🇮" * 10000  # A UTF-8 string spanning multiple 64 KiB read blocks.
        days = [-1, 0, 16436, 20453][i % 4]
        price = [-101, 0, 1, 29, 9007199254740993][i % 5]
        ts = days * 86400000000 + (i % 3) * 1234567
        rows.append((i + 1, cid, i % 3 + 1, i % 4, None if i % 6 == 0 else i % 9,
                     price, 0.005, 0.1234565, country, ["Café", "Café"][i % 2], days, ts, i % 2))
    dims = {"segment": {r[1]: "enterprise" if i % 3 == 0 else (None if i % 3 == 1 else "")
                         for i, r in enumerate(rows)}, "brand": {1: 'b,"quoted"', 2: None, 3: ""}}

    def money(c):
        sign = "-" if c < 0 else ""
        return f"{sign}{abs(c) // 100}.{abs(c) % 100:02d}"

    def write(table, part, header, data, ending="\r\n"):
        path = out / table / "1k" / f"part-{part:05d}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            w = csv.writer(f, lineterminator=ending)
            w.writerow(header)
            w.writerows(data)
        # Exercise final lines without terminators.
        path.write_bytes(path.read_bytes().rstrip(b"\r\n"))

    for part, chunk in enumerate((rows[:63], rows[63:])):
        formatted = []
        for r in chunk:
            timestamp = dt.datetime(1970, 1, 1) + dt.timedelta(microseconds=r[11])
            formatted.append([*r[:4], "\\N" if r[4] is None else r[4], money(r[5]), r[6], r[7],
                              "\\N" if r[8] is None else r[8], r[9],
                              (dt.date(1970, 1, 1) + dt.timedelta(days=r[10])).isoformat(),
                              timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"), "true" if r[12] else "false"])
        write("sales_fact", part, [f"col{i}" for i in range(13)], formatted)
    # Deliberately unmatched sale and product exercise inner rather than left joins.
    customers = [[cid, "n", "e", "1970-01-01", "\\N" if seg is None else seg, "US", "1.00"]
                 for cid, seg in dims["segment"].items() if cid != rows[-1][1]]
    write("dim_customer", 0, ["customer_id", "name", "email", "signup_date", "segment", "country", "lifetime_value"], customers)
    write("dim_product", 0, ["product_id", "category", "brand", "weight_grams", "tags", "attributes"],
          [[pid, "c", "\\N" if brand is None else brand, 1, '["x,y"]', '{"x":"y"}']
           for pid, brand in dims["brand"].items() if pid != 3])
    return out, rows, dims


@pytest.mark.parametrize("implementation", IMPLEMENTATIONS)
@pytest.mark.parametrize("mode", ["streaming", "materialized"])
@pytest.mark.parametrize("op", list(REF))
def test_semantics(implementation, mode, op, sample):
    if op == "OP08" and mode == "streaming":
        pytest.skip("OP08 is materialized-only")
    out, rows, dims = sample
    result = node([implementation, "--op", op, "--dataset", "A", "--rows", "1000", "--mode", mode,
                   "--chunk-rows", "7", "--threads", "1", "--input", str(out), "--output-json"])
    assert result.returncode == 0, result.stderr
    assert len(result.stdout.splitlines()) == 1
    got = json.loads(result.stdout)
    source = rows
    if op in NEEDS_DIMS:
        source = [r for r in rows if r[1] != rows[-1][1] and (op != "OP07" or r[2] != 3)]
        (checksum, count), floats = REF[op](source, dims)
    else:
        (checksum, count), floats = REF[op](source)
    assert (got["checksum"], got["row_count"]) == (checksum, count)
    assert got["load_ms"] >= 0 and got["compute_ms"] >= 0
    if op == "OP15":
        assert got["load_ms"] == 0
    for key, value in floats.items():
        assert math.isclose(got["floats"][key], value, rel_tol=1e-9)


@pytest.mark.parametrize("implementation", IMPLEMENTATIONS)
def test_sort_uint64_wrap_and_microseconds(implementation, tmp_path):
    path = tmp_path / "sales_fact" / "1k" / "part-00000.csv"
    path.parent.mkdir(parents=True)
    ids = [2**63 - 1, 2**63 - 2, 2**53 + 1]
    timestamps = [253402300799999999, 253402300799999999, 253402300799999998]
    rows = [(tid, 0, 0, 0, None, 0, 0, 0, None, "", 0, ts, False)
            for tid, ts in zip(ids, timestamps)]
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"col{i}" for i in range(13)])
        for tid, ts in zip(ids, timestamps):
            w.writerow([tid, 0, 0, 0, "\\N", "0.00", 0, 0, "\\N", "", "9999-12-31",
                        f"9999-12-31 23:59:59.{ts % 1000000:06d}", "false"])
    result = node([implementation, "--op", "OP08", "--rows", "1000", "--mode", "materialized",
                   "--chunk-rows", "1", "--input", str(tmp_path)])
    assert result.returncode == 0, result.stderr
    got = json.loads(result.stdout)
    (checksum, count), _ = REF["OP08"](rows)
    assert (got["checksum"], got["row_count"]) == (checksum, count)


def test_javascript_matches_typed_source():
    result = node(["languages/typescript/emit-javascript.mjs", "--check"])
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("implementation", IMPLEMENTATIONS)
def test_helpers(implementation):
    rows = [[None, "", "Café", "Café", -1, 2**64 - 1, 9007199254740993]]
    expected, count = digest_rows(rows)
    script = f'''
        import assert from 'node:assert/strict';
        import {{ cents, timestamp, floorDiv, civilFromDays, csvFields, digest }} from './{implementation}';
        assert.equal(cents('-0.01'), -1n);
        assert.equal(cents('90071992547409.93'), 9007199254740993n);
        assert.equal(timestamp('1969-12-31 23:59:59.999999'), -1n);
        assert.equal(timestamp('9999-12-31 23:59:59.999999'), 253402300799999999n);
        assert.equal(floorDiv(-1n, 1000000n), -1n);
        assert.deepEqual(civilFromDays(-1), [1969, 12, 31]);
        assert.deepEqual(csvFields('\\\\N,"","\\\\N","x,""y"""'), [null, '', '\\\\N', 'x,"y"']);
        assert.throws(() => csvFields('"unterminated'));
        assert.throws(() => cents('1.234'));
        assert.throws(() => digest([[9007199254740992]]));
        console.log(JSON.stringify(digest([[null, '', 'Café', 'Café', -1n, 18446744073709551615n, 9007199254740993n]])));
    '''
    result = node(["--input-type=module", "-e", script])
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"checksum": expected, "row_count": count}


@pytest.mark.parametrize("implementation", IMPLEMENTATIONS)
@pytest.mark.parametrize("args, message", [
    (["--op", "OP08", "--mode", "streaming"], "materialized only"),
    (["--op", "OP01", "--threads", "2"], "threads 1"),
    (["--op", "OP01", "--chunk-rows", "0"], "invalid rows or chunk-rows"),
    (["--op", "OP99"], "unsupported operation"),
])
def test_invalid_cli(implementation, args, message):
    result = node([implementation, "--rows", "1000", *args])
    assert result.returncode != 0
    assert result.stdout == ""
    assert message in result.stderr
