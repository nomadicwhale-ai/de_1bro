"""Tiny dependency-free .env loader + typed getters.

Precedence: real environment > .env file > default. `.env` lives at the repo root
(copy .env.example). Supports comments, quotes, `export` prefix and ${VAR} expansion.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_loaded = False


def _expand(value: str, env: dict) -> str:
    return _VAR.sub(lambda m: env.get(m.group(1)) or (m.group(2) or ""), value)


def load_dotenv(path: Path | None = None, override: bool = False) -> dict:
    """Load KEY=VALUE pairs into os.environ (existing variables win unless override)."""
    global _loaded
    path = path or ROOT / ".env"
    values: dict[str, str] = {}
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if val[:1] in "\"'" and val[-1:] == val[:1] and len(val) >= 2:
                quote, val = val[0], val[1:-1]
            else:
                quote = ""
                val = re.sub(r"\s+#.*$", "", val)
            merged = {**values, **os.environ}
            values[key] = val if quote == "'" else _expand(val, merged)
    for k, v in values.items():
        if override or k not in os.environ:
            os.environ[k] = v
    _loaded = True
    return values


def _ensure():
    if not _loaded:
        load_dotenv()


def get(key: str, default: str | None = None) -> str | None:
    _ensure()
    v = os.environ.get(key)
    return default if v is None or v == "" else v


def get_int(key: str, default: int) -> int:
    v = get(key)
    if v is None:
        return default
    return int(v, 0) if v.lower().startswith(("0x", "0b", "0o")) else int(float(v))


def get_float(key: str, default: float) -> float:
    v = get(key)
    return default if v is None else float(v)


def get_bool(key: str, default: bool) -> bool:
    v = get(key)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


def get_path(key: str, default: str) -> Path:
    p = Path(get(key, default)).expanduser()
    return p if p.is_absolute() else ROOT / p
