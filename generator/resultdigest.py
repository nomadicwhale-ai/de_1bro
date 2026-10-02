"""Result digest for benchmark operations (spec/checksum.md, "Result digests").

Unlike the dataset digest this one is *row-paired*: every result row is hashed from all of its
non-float columns, then rows are combined order-insensitively. It only needs mix64 and FNV-1a, so
any language can implement it with the standard library. Float columns are never hashed; they are
reported separately and compared with a relative tolerance.
"""
from __future__ import annotations

from .reference import mix64
from .spec import GOLDEN, MASK64

NULL_CANON = 0xA5A5A5A5A5A5A5A5
FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x100000001B3


def fnv1a64(data: bytes) -> int:
    h = FNV_OFFSET
    for b in data:
        h = ((h ^ b) * FNV_PRIME) & MASK64
    return h


def canon(v) -> int:
    if v is None:
        return NULL_CANON
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v & MASK64
    if isinstance(v, str):
        return fnv1a64(v.encode("utf-8"))
    raise TypeError(f"unsupported result value {type(v)}: floats are not digested")


def row_hash(values) -> int:
    h = 0
    for v in values:
        h = mix64((h + canon(v) + GOLDEN) & MASK64)
    return h


class ResultDigest:
    def __init__(self):
        self.count = 0
        self.sum = 0
        self.xor = 0

    def add(self, values) -> None:
        h = row_hash(values)
        self.count += 1
        self.sum = (self.sum + h) & MASK64
        self.xor ^= h

    def merge(self, other: "ResultDigest") -> None:
        self.count += other.count
        self.sum = (self.sum + other.sum) & MASK64
        self.xor ^= other.xor

    @property
    def checksum(self) -> str:
        return f"{self.sum:016x}{self.xor:016x}"


def digest_rows(rows) -> tuple[str, int]:
    d = ResultDigest()
    for r in rows:
        d.add(r)
    return d.checksum, d.count
