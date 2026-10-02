"""Benchmark runner: orchestrates implementations through the CLI contract.

    python -m runner run --impl selftest --op OP00 --rows 1k,10k --runs 3
    python -m runner run --smoke                 # tiny sizes, every runnable implementation
    python -m runner validate results/raw/*.jsonl
    python -m runner list

Each run is a separate OS process (clean memory, honest peak RSS via wait4). The first run per
configuration is a discarded warm-up. Results are appended to results/raw/<run_id>.jsonl and
validated against schema/result.schema.json. Completed (impl, op, rows, mode, threads) keys are
skipped on re-run (resumable).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from common import env
from generator import spec as S
from . import stats, sysinfo

ROOT = env.ROOT
SCHEMA = json.loads((ROOT / "schema" / "result.schema.json").read_text())


# ------------------------------------------------------------------ registry / config
def load_impls() -> dict:
    return yaml.safe_load((ROOT / "config" / "implementations.yaml").read_text())


def load_budget() -> dict:
    b = yaml.safe_load((ROOT / "config" / "budget.yaml").read_text())
    b["max_rss_gb"] = env.get_float("MAX_RSS_GB", b["max_rss_gb"])
    b["max_wall_seconds_per_run"] = env.get_int("RUN_TIMEOUT_SEC", b["max_wall_seconds_per_run"])
    return b


def toolchain_version(impl: dict) -> str:
    cmd = impl.get("toolchain", {}).get("version_cmd")
    if not cmd or not shutil.which(cmd[0]):
        return "unknown"
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return (out.stdout or out.stderr).strip().splitlines()[0]
    except Exception:
        return "unknown"


# ------------------------------------------------------------------ expected checksums
def expected_checksum(op: str, dataset: str, rows: int, data_dir: Path) -> dict | None:
    f = ROOT / "results" / "expected" / f"{op}_{dataset}_{rows}.json"
    if f.exists():
        return json.loads(f.read_text())
    if op == "OP00":  # harness self-test: digest of the generated table itself
        table = S.DATASET_TABLES[dataset]
        man = data_dir / table / S.size_label(rows) / "manifest.json"
        if man.exists():
            m = json.loads(man.read_text())
            if m.get("table_digest"):
                return {"checksum": m["table_digest"], "row_count": m["rows"], "source": "manifest"}
        golden = json.loads((ROOT / "spec" / "golden.json").read_text())
        for c in golden["cases"]:
            if c["table"] == table and c["scale_n"] == rows and c["rows"] == S.Scale(rows).rows(table):
                return {"checksum": c["table_digest"], "row_count": c["rows"], "source": "golden"}
    return None


# ------------------------------------------------------------------ process execution
def run_with_rss(cmd: list[str], timeout: int, pin_cpu: int | None) -> dict:
    """Like run_once but measures this child's peak RSS using wait4 (per-process, not cumulative)."""
    import resource  # noqa: F401  (Linux/macOS)
    full = list(cmd)
    if pin_cpu is not None and shutil.which("taskset"):
        full = ["taskset", "-c", str(pin_cpu)] + full
    t0 = time.perf_counter()
    with subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT) as p:
        import threading
        bufs = {}

        def drain(name, f):
            bufs[name] = f.read()

        th = [threading.Thread(target=drain, args=(n, f), daemon=True)
              for n, f in (("out", p.stdout), ("err", p.stderr))]
        [t.start() for t in th]
        timed_out = False
        status = None
        while True:
            pid, st, ru = os.wait4(p.pid, os.WNOHANG)
            if pid:
                status, rusage = st, ru
                break
            if time.perf_counter() - t0 > timeout:
                p.kill()
                timed_out = True
                _, status, rusage = os.wait4(p.pid, 0)
                break
            time.sleep(0.005)
        [t.join() for t in th]
        p.returncode = 0  # reaped manually; avoid Popen waitpid error
    wall = (time.perf_counter() - t0) * 1000
    rc = os.waitstatus_to_exitcode(status) if status is not None else -1
    return {"timeout": timed_out, "wall_ms": wall, "peak_rss_mb": rusage.ru_maxrss / 1024.0,
            "returncode": rc, "stdout": bufs.get("out", b"").decode(errors="replace"),
            "stderr": bufs.get("err", b"").decode(errors="replace")}


def parse_json_line(stdout: str) -> dict | None:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                return None
    return None


# ------------------------------------------------------------------ one configuration
def run_config(name: str, impl: dict, op: str, dataset: str, rows: int, mode: str, threads: int,
               chunk_rows: int, data_dir: Path, budget: dict, envinfo: dict, run_id: str,
               timed_runs: int, warmup: int) -> dict:
    base = {
        "run_id": run_id, "track": impl["track"], "implementation": name,
        "variant": impl.get("variant", "default"), "op": op, "dataset": dataset, "rows": rows,
        "mode": mode, "chunk_rows": chunk_rows if mode == "streaming" else None,
        "threads": threads, "env": dict(envinfo),
    }
    ver = toolchain_version(impl)
    base["toolchain"] = {"name": impl.get("toolchain", {}).get("name", name), "version": ver,
                         "flags": impl.get("flags", "")}
    if impl.get("status") == "not_run":
        return {**base, "status": "not_run", "skip_reason": impl.get("reason", "toolchain not installed")}
    if op not in impl.get("ops", []):
        return {**base, "status": "n/a", "skip_reason": f"{name} does not implement {op}"}
    exp = expected_checksum(op, dataset, rows, data_dir)
    if exp is None:
        return {**base, "status": "skipped", "skip_reason": "no oracle result for this op/size yet"}

    cmd = list(impl["cmd"]) + ["--op", op, "--dataset", dataset, "--rows", str(rows), "--mode", mode,
                              "--chunk-rows", str(chunk_rows), "--threads", str(threads),
                              "--input", str(data_dir), "--output-json"]
    pin = env.get_int("SINGLE_THREAD_CPU", 0) if threads == 1 else None
    runs, rss, last, total_ms = [], [], None, []
    for k in range(warmup + timed_runs):
        r = run_with_rss(cmd, budget["max_wall_seconds_per_run"], pin)
        if r["timeout"]:
            return {**base, "status": "timeout", "skip_reason": f"exceeded {budget['max_wall_seconds_per_run']}s"}
        res = parse_json_line(r["stdout"])
        if r["returncode"] != 0 or res is None:
            return {**base, "status": "failed", "skip_reason": None,
                    "notes": f"rc={r['returncode']} stderr={r['stderr'][-500:]!r}"}
        if k < warmup:
            continue
        runs.append(float(res["compute_ms"]))
        rss.append(r["peak_rss_mb"])
        total_ms.append(r["wall_ms"])
        last = res
    s = stats.summarize(runs, budget["noisy_iqr_pct"])
    correct = last["checksum"] == exp["checksum"] and last.get("row_count") == exp["row_count"]
    compute_s = max(s["median_ms"], 1e-6) / 1000.0
    rec = {
        **base, "status": "ok" if correct else "incorrect", "correct": correct,
        "checksum": last["checksum"], "expected_checksum": exp["checksum"],
        "row_count": last.get("row_count"), "startup_ms": max(min(total_ms) - last.get("load_ms", 0)
                                                              - last["compute_ms"], 0.0),
        "load_ms": last.get("load_ms"), "compute_ms": last["compute_ms"],
        "total_ms": min(total_ms), "runs": runs, **s, "rows_per_s": rows / compute_s,
        "mb_per_s": None, "peak_rss_mb": max(x for x in rss if x is not None),
        "steady_rss_mb": last.get("steady_rss_mb"), "notes": last.get("notes"),
        "chunk_rows_per_s": last.get("chunk_rows_per_s", []),
        "oracle": exp.get("source", "expected-file"),
    }
    if last.get("toolchain"):
        rec["toolchain"] = {**rec["toolchain"], **last["toolchain"]}
    return rec


# ------------------------------------------------------------------ CLI
def validate_records(paths: list[Path]) -> int:
    import jsonschema
    v = jsonschema.Draft202012Validator(SCHEMA)
    bad = n = 0
    for p in paths:
        for ln, line in enumerate(p.read_text().splitlines(), 1):
            if not line.strip():
                continue
            n += 1
            errs = list(v.iter_errors(json.loads(line)))
            for e in errs:
                bad += 1
                print(f"{p}:{ln}: {'/'.join(map(str, e.absolute_path))}: {e.message}")
    print(f"validated {n} records, {bad} problems")
    return 1 if bad else 0


def done_keys(out_dir: Path) -> set:
    keys = set()
    for p in out_dir.glob("*.jsonl"):
        for line in p.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("status") in ("ok", "incorrect", "n/a", "not_run"):
                    keys.add((r["implementation"], r["variant"], r["op"], r["dataset"], r["rows"], r["mode"], r["threads"]))
    return keys


def cmd_run(a) -> int:
    impls = load_impls()
    budget = load_budget()
    names = a.impl.split(",") if a.impl else list(impls)
    ops = a.op.split(",") if a.op else None
    sizes = [S.parse_rows("1k"), S.parse_rows("10k")] if a.smoke else \
        [S.parse_rows(x) for x in a.rows.split(",")]
    data_dir = env.get_path("DATA_DIR", "./data")
    out_dir = env.get_path("RESULTS_DIR", "./results") / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    envinfo = sysinfo.collect(data_dir)
    plan = []
    for name in names:
        impl = impls[name]
        for op in (ops or impl.get("ops", [])):
            for rows in sizes:
                for mode in impl.get("modes", ["streaming"]):
                    for threads in impl.get("threads", [1]):
                        plan.append((name, impl, op, a.dataset, rows, mode, threads))
    random.Random(env.get_int("SHUFFLE_SEED", 42)).shuffle(plan)
    skip = done_keys(out_dir) if not a.force else set()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    out_file = out_dir / f"{run_id}.jsonl"
    print(f"run {run_id}: {len(plan)} configurations -> {out_file}")
    if a.dry_run:
        for p in plan:
            print("  ", p[0], p[2], p[4], p[5], f"threads={p[6]}")
        return 0
    bad = 0
    for name, impl, op, ds, rows, mode, threads in plan:
        key = (name, impl.get("variant", "default"), op, ds, rows, mode, threads)
        if key in skip:
            print(f"  skip (already done) {key}")
            continue
        timed = a.runs or (env.get_int("TIMED_RUNS_1B", 3) if rows >= 10**9 else env.get_int("TIMED_RUNS", 7))
        rec = run_config(name, impl, op, ds, rows, mode, threads, a.chunk_rows, data_dir, budget,
                         envinfo, run_id, timed, a.warmup if a.warmup is not None else env.get_int("WARMUP_RUNS", 1))
        with open(out_file, "a") as f:
            f.write(json.dumps(rec) + "\n")
        flag = "OK " if rec["status"] == "ok" else rec["status"].upper()
        extra = f"median={rec['median_ms']:.1f}ms rss={rec['peak_rss_mb']:.0f}MB" if rec["status"] in ("ok", "incorrect") else (rec.get("skip_reason") or rec.get("notes") or "")
        print(f"  {flag:<9} {name} {op} N={S.size_label(rows)} {mode} t={threads} {extra}")
        bad += rec["status"] in ("incorrect", "failed", "timeout")
    rc = validate_records([out_file]) if out_file.exists() else 0
    return 1 if (bad or rc) else 0


def main(argv=None) -> int:
    env.load_dotenv()
    p = argparse.ArgumentParser(prog="python -m runner")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--impl", help="comma list (default: all registered)")
    r.add_argument("--op")
    r.add_argument("--rows", default="1k,10k")
    r.add_argument("--dataset", default="A")
    r.add_argument("--chunk-rows", type=int, default=env.get_int("CHUNK_ROWS", S.DEFAULT_CHUNK_ROWS))
    r.add_argument("--runs", type=int, help="timed runs (default from .env)")
    r.add_argument("--warmup", type=int)
    r.add_argument("--smoke", action="store_true", help="1k+10k rows, one run each, all implementations")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--force", action="store_true", help="re-run even if results exist")
    r.set_defaults(fn=cmd_run)
    v = sub.add_parser("validate")
    v.add_argument("files", nargs="+", type=Path)
    v.set_defaults(fn=lambda a: validate_records(a.files))
    l = sub.add_parser("list")
    l.set_defaults(fn=lambda a: [print(f"{k:<12} track={v['track']} variant={v.get('variant')} ops={v.get('ops')}")
                                 for k, v in load_impls().items()] and 0)
    a = p.parse_args(argv)
    if getattr(a, "smoke", False) and a.runs is None:
        a.runs, a.warmup = 1, 0
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
