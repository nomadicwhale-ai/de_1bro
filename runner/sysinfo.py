"""Collect environment metadata recorded in every result record."""
from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path


def _read(p: str) -> str | None:
    try:
        return Path(p).read_text().strip()
    except OSError:
        return None


def cpu_model() -> str:
    txt = _read("/proc/cpuinfo") or ""
    for line in txt.splitlines():
        if line.lower().startswith(("model name", "hardware", "cpu model")):
            return line.split(":", 1)[1].strip()
    return platform.processor() or platform.machine()


def ram_gb() -> float:
    txt = _read("/proc/meminfo") or ""
    for line in txt.splitlines():
        if line.startswith("MemTotal:"):
            return round(int(line.split()[1]) / 1024 / 1024, 2)
    return 0.0


def container_limits() -> str | None:
    parts = []
    mem = _read("/sys/fs/cgroup/memory.max") or _read("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    cpu = _read("/sys/fs/cgroup/cpu.max")
    if mem and mem != "max" and int(mem) < (1 << 50):
        parts.append(f"memory={int(mem) / 2**30:.1f}GiB")
    if cpu and not cpu.startswith("max"):
        parts.append(f"cpu.max={cpu}")
    return ", ".join(parts) or None


def disk_kind(path: Path) -> str | None:
    try:
        dev = os.stat(path).st_dev
        for entry in Path("/sys/dev/block").glob(f"{os.major(dev)}:{os.minor(dev)}"):
            rot = Path(os.path.realpath(entry)).parent / "queue" / "rotational"
            if rot.exists():
                return "hdd" if rot.read_text().strip() == "1" else "ssd/nvme"
    except OSError:
        pass
    return None


def collect(data_dir: Path | None = None, cache: str = "unknown") -> dict:
    return {
        "cpu": cpu_model(),
        "cores": os.cpu_count() or 1,
        "ram_gb": ram_gb(),
        "os": f"{platform.system()} {platform.release()}",
        "kernel": platform.version(),
        "container_limits": container_limits(),
        "disk": disk_kind(data_dir) if data_dir else None,
        "cache": cache,
        "governor": _read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
        "taskset": bool(shutil.which("taskset")),
    }
