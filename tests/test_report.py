"""Report retains labelled variants and never mixes their ranks."""
import json

from report.make_charts import load, main
from runner.run import load_impls, validate_records


def record(name, variant, ms):
    return {"implementation": name, "variant": variant, "track": "L", "op": "OP08",
            "rows": 1000, "mode": "materialized", "threads": 1, "status": "ok",
            "median_ms": ms, "load_ms": 0, "peak_rss_mb": 12,
            "env": {"cpu": "test", "cores": 1, "ram_gb": 1, "os": "test"}}


def test_report_separates_variants(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir()
    # Same implementation name deliberately tests variant as part of record identity.
    baseline = record("java", "stdlib", 100)
    baseline["env"] = {"cpu": "Xeon baseline", "cores": 4, "ram_gb": 15.72, "os": "old OS"}
    tuned = record("java", "tuned", 1)
    tuned["env"] = {"cpu": "tuned VM", "cores": 6, "ram_gb": 328.76, "os": "new OS"}
    records = [baseline, tuned, record("library", "ecosystem", 0.5),
               {**record("bad", "tuned", 0.1), "status": "incorrect"}]
    (raw / "records.jsonl").write_text("\n".join(map(json.dumps, records)))
    assert len(load(raw)) == 3
    main(["--raw", str(raw), "--out", str(out)])
    text = (out / "REPORT.md").read_text()
    assert "variant `stdlib`" in text and "variant `tuned`" in text and "variant `ecosystem`" in text
    assert text.count("**#1**") == 3  # fastest tuned/library entries cannot demote the baseline
    assert "Xeon baseline | 4 | 15.72 | old OS" in text
    assert "tuned VM | 6 | 328.76 | new OS" in text
    baseline_id = next(line.split("|")[1].strip() for line in text.splitlines() if "| Xeon baseline |" in line)
    tuned_id = next(line.split("|")[1].strip() for line in text.splitlines() if "| tuned VM |" in line)
    assert f"variant `stdlib`)\n\nEnvironment: **{baseline_id}**" in text
    assert f"variant `tuned`)\n\nEnvironment: **{tuned_id}**" in text
    assert f"<sub>{baseline_id}; load" in text and f"<sub>{tuned_id}; load" in text
    assert "bad" not in text
    for chart in ("L_1k_bars.png", "L_tuned_1k_bars.png", "L_ecosystem_1k_bars.png"):
        assert (out / "charts" / chart).is_file()


def test_tuned_registration_and_schema(tmp_path):
    impls = load_impls()
    assert impls["cpp"]["variant"] == impls["java"]["variant"] == "stdlib"
    assert impls["cpp-tuned"]["ops"] == ["OP04", "OP09", "OP10"]
    assert impls["java-tuned"]["ops"] == ["OP08"]
    assert impls["java-tuned"]["modes"] == ["materialized"]
    for name in ("cpp-tuned", "java-tuned"):
        assert impls[name]["variant"] == "tuned"
    rec = {**record("java-tuned", "tuned", 1), "run_id": "test", "dataset": "A",
           "correct": True, "checksum": "0" * 32, "expected_checksum": "0" * 32,
           "compute_ms": 1, "runs": [1]}
    path = tmp_path / "result.jsonl"
    path.write_text(json.dumps(rec) + "\n")
    assert validate_records([path]) == 0
