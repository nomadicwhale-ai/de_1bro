"""Constants and vocabularies of the deterministic dataset specification.

Everything here is mirrored in spec/generator.md. Changing any value changes the
data and MUST bump GENERATOR_VERSION and regenerate spec/golden.json.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 0x5EED1B20
MASK64 = (1 << 64) - 1
GOLDEN = 0x9E3779B97F4A7C15
C1 = 0xBF58476D1CE4E5B9
C2 = 0x94D049BB133111EB
INV53 = 1.0 / 9007199254740992.0  # 2**-53, exact

TABLE_IDS = {
    "sales_fact": 1,
    "dim_customer": 2,
    "dim_product": 3,
    "events_log": 4,
    "wide_numeric": 5,
}
DATASET_TABLES = {
    "A": "sales_fact",
    "B": "dim_customer",
    "C": "dim_product",
    "D": "events_log",
    "E": "wide_numeric",
}

EPOCH = _dt.date(1970, 1, 1)


def days(y: int, m: int, d: int) -> int:
    return (_dt.date(y, m, d) - EPOCH).days


SALES_DATE0 = days(2015, 1, 1)
SALES_DATE_SPAN = days(2025, 12, 31) - SALES_DATE0 + 1  # 4018
CUSTOMER_DATE0 = days(2010, 1, 1)
CUSTOMER_DATE_SPAN = 5000
EVENTS_BASE_US = days(2025, 1, 1) * 86400 * 1_000_000
US_PER_DAY = 86400 * 1_000_000

INT32_MAX = 2147483647
INT32_MIN = -2147483648

COUNTRIES = [
    "United States", "China", "India", "Germany", "United Kingdom", "France", "Japan",
    "Brazil", "Canada", "Italy", "Russia", "South Korea", "Australia", "Spain", "Mexico",
    "Indonesia", "Netherlands", "Saudi Arabia", "Turkey", "Switzerland", "Poland", "Sweden",
    "Belgium", "Argentina", "Norway", "Austria", "Ireland", "Israel", "UAE", "Singapore",
    "Denmark", "Malaysia", "Philippines", "South Africa", "Egypt", "Finland", "Chile",
    "Portugal", "Czechia", "Mongolia",
]
# tax rate in basis points per country (same order)
COUNTRY_RATE_BP = [
    725, 1300, 1800, 1900, 2000, 2000, 1000, 1700, 500, 2200,
    2000, 1000, 1000, 2100, 1600, 1100, 2100, 1500, 2000, 770,
    2300, 2500, 2100, 2100, 2500, 2000, 2300, 1700, 500, 800,
    2500, 600, 1200, 1500, 1400, 2400, 1900, 2300, 2100, 1000,
]
assert len(COUNTRIES) == 40 and len(COUNTRY_RATE_BP) == 40

N_CATEGORIES = 200
CATEGORIES = [f"category_{k:03d}" for k in range(N_CATEGORIES)]

# Edge-case vocabulary appended after the regular vocabularies
EDGE_COUNTRY_EMPTY = ""
EDGE_COUNTRY_UNICODE = "Côte d'Ivoire \U0001F1E8\U0001F1EE"
EDGE_CATEGORY_DECOMPOSED = "Café"
EDGE_CATEGORY_PRECOMPOSED = "Café"
COUNTRY_VOCAB = COUNTRIES + [EDGE_COUNTRY_EMPTY, EDGE_COUNTRY_UNICODE]
CATEGORY_VOCAB = CATEGORIES + [EDGE_CATEGORY_DECOMPOSED, EDGE_CATEGORY_PRECOMPOSED]

SEGMENTS = ["consumer", "corporate", "small_business", "enterprise", "government", "education"]
EVENT_TYPES = ["view", "click", "search", "add_to_cart", "purchase", "refund", "login", "logout"]
TAGS = [f"tag_{k:02d}" for k in range(32)]
COLORS = ["red", "green", "blue", "black", "white", "yellow", "purple", "orange"]
SIZES = ["xs", "s", "m", "l", "xl"]
PAD = "abcdefghij" * 45  # 450 chars
PADS = [PAD[:k] for k in range(451)]

N_STORES = 5000
EDGE_EVERY = 1000  # rows with i % 1000 == 999 are edge-case rows
WIDE_FLOATS = 100
WIDE_INTS = 20
WIDE_INT_MOD = 1_000_000_007

DEFAULT_CHUNK_ROWS = 1_000_000

SIZE_LABELS = {
    "1k": 1_000, "10k": 10_000, "1m": 1_000_000, "10m": 10_000_000,
    "100m": 100_000_000, "1b": 1_000_000_000,
}


def parse_rows(text: str) -> int:
    t = text.strip().lower().replace("_", "").replace(",", "")
    if t in SIZE_LABELS:
        return SIZE_LABELS[t]
    mult = {"k": 10**3, "m": 10**6, "b": 10**9}
    if t and t[-1] in mult:
        return int(float(t[:-1]) * mult[t[-1]])
    return int(t)


def size_label(n: int) -> str:
    for k, v in SIZE_LABELS.items():
        if v == n:
            return k
    return str(n)


@dataclass(frozen=True)
class Scale:
    """Benchmark scale N and the derived dimension sizes (see spec/generator.md)."""

    n: int

    @property
    def customers(self) -> int:
        return min(max(self.n // 10, 1), 50_000_000)

    @property
    def products(self) -> int:
        return min(max(self.n // 100, 10), 1_000_000)

    @property
    def users(self) -> int:
        return max(self.n // 100, 10)

    def rows(self, table: str) -> int:
        return {
            "sales_fact": self.n,
            "dim_customer": self.customers,
            "dim_product": self.products,
            "events_log": self.n,
            "wide_numeric": self.n,
        }[table]
