"""Phase 2 operation registry: single source of truth for specs (spec/ops/*.md) and the oracle.

Every op reads dataset A (`sales_fact`) and returns result rows made of *integer / string / NULL*
columns (digested, exact) plus optional named float results (compared with relative tolerance).
`sql` is run by DuckDB over the Parquet files (`FROM sales`) and is the oracle; the same results
are re-derived in pure Python (tests/test_oracle.py) for 1k/10k rows as an independent check.
"""
from __future__ import annotations

CENTS = "(unit_price * 100)::BIGINT"
# Table `sales` exposes the dataset columns; unit_price is decimal(18,2).

OPS: dict[str, dict] = {
    "OP01": {
        "name": "scan_aggregate",
        "title": "Full scan + aggregate",
        "columns": ["count_rows", "count_quantity", "sum_quantity", "sum_price_cents",
                    "min_price_cents", "max_price_cents", "count_returned"],
        "group": False,
        "text": ("One pass over all rows. `count_quantity`/`sum_quantity` skip NULL quantity "
                 "(sum is NULL if every quantity is NULL). Money is summed as int64 cents "
                 "(`unit_price * 100`)."),
        "sql": f"""SELECT count(*), count(quantity), sum(quantity)::BIGINT, sum({CENTS})::BIGINT,
                   min({CENTS}), max({CENTS}), count(*) FILTER (WHERE is_returned) FROM sales""",
    },
    "OP03": {
        "name": "groupby_low_cardinality",
        "title": "Group by country (low cardinality, ~43 groups)",
        "columns": ["country", "count_rows", "sum_quantity", "sum_price_cents"],
        "group": True,
        "text": ("Group by `country`; NULL country is its own group; the empty-string and Unicode edge "
                 "countries are ordinary keys (compare bytes, no normalisation). `sum_quantity` skips "
                 "NULL quantity (NULL if all NULL)."),
        "sql": f"""SELECT country, count(*), sum(quantity)::BIGINT, sum({CENTS})::BIGINT
                   FROM sales GROUP BY country""",
    },
    "OP04": {
        "name": "groupby_high_cardinality",
        "title": "Group by customer_id (high cardinality, ~N/10 groups)",
        "columns": ["customer_id", "count_rows", "sum_price_cents"],
        "group": True,
        "text": "Group by `customer_id` (skewed keys, up to N/10 groups). Memory-intensive.",
        "sql": f"SELECT customer_id, count(*), sum({CENTS})::BIGINT FROM sales GROUP BY customer_id",
    },
    "OP05": {
        "name": "groupby_multi_key",
        "title": "Group by (country, category, year(transaction_date))",
        "columns": ["country", "category", "year", "count_rows", "sum_price_cents"],
        "group": True,
        "text": ("Three-part key; `year` is the proleptic-Gregorian civil year of the date (days since "
                 "1970-01-01 converted with Hinnant's civil_from_days). NULL country is a key value."),
        "sql": f"""SELECT country, category, year(transaction_date)::BIGINT, count(*),
                   sum({CENTS})::BIGINT FROM sales GROUP BY 1, 2, 3""",
    },
    "OP10": {
        "name": "distinct_count",
        "title": "Exact distinct counts",
        "columns": ["distinct_customers", "distinct_products", "distinct_store_days"],
        "group": False,
        "text": ("Exact `count(DISTINCT customer_id)`, `count(DISTINCT product_id)` and the number of "
                 "distinct `(store_id, transaction_date)` pairs. No approximate sketches."),
        "sql": """SELECT (SELECT count(DISTINCT customer_id) FROM sales),
                         (SELECT count(DISTINCT product_id) FROM sales),
                         (SELECT count(*) FROM (SELECT DISTINCT store_id, transaction_date FROM sales))""",
    },
    "OP15": {
        "name": "parse_csv",
        "title": "Parse CSV into typed values and summarise every column",
        "columns": ["rows", "sum_transaction_id", "sum_customer_id", "sum_product_id", "sum_store_id",
                    "sum_quantity", "nulls_quantity", "sum_price_cents", "sum_discount_e6",
                    "sum_tax_e6", "sum_country_bytes", "nulls_country", "sum_category_bytes",
                    "sum_date_days", "sum_ts_seconds", "sum_ts_micros_frac", "count_returned"],
        "group": False,
        "csv_input": True,
        "text": ("Input is the CSV chunk files (not Parquet). Parse ALL 13 columns of every row into typed "
                 "values; the parse is the benchmarked work, so `compute_ms` covers read+parse+summarise "
                 "(report `load_ms` = 0). Summaries: ids/store/quantity summed (NULLs skipped); "
                 "`sum_price_cents` of decimal text -> cents; `sum_discount_e6`/`sum_tax_e6` = sum of "
                 "`floor(x * 1e6 + 0.5)`; `sum_*_bytes` = total UTF-8 byte length (NULL skipped); "
                 "`sum_date_days` days since epoch; timestamp split into `sum_ts_seconds` = sum of "
                 "`us div 1_000_000` and `sum_ts_micros_frac` = sum of `us mod 1_000_000`; "
                 "`count_returned` = rows with is_returned = true. CSV NULL marker is `\\N`."),
        "sql": f"""SELECT count(*), sum(transaction_id)::BIGINT, sum(customer_id)::BIGINT, sum(product_id)::BIGINT,
                   sum(store_id)::BIGINT, sum(quantity)::BIGINT, count(*) FILTER (WHERE quantity IS NULL),
                   sum({CENTS})::BIGINT, sum(floor(discount * 1e6 + 0.5))::BIGINT,
                   sum(floor(tax * 1e6 + 0.5))::BIGINT, sum(strlen(country))::BIGINT,
                   count(*) FILTER (WHERE country IS NULL), sum(strlen(category))::BIGINT,
                   sum(epoch(transaction_date)::BIGINT // 86400)::BIGINT,
                   sum(epoch_us(transaction_timestamp) // 1000000)::BIGINT,
                   sum(epoch_us(transaction_timestamp) % 1000000)::BIGINT,
                   count(*) FILTER (WHERE is_returned) FROM sales""",
    },
    "OP19": {
        "name": "null_handling",
        "title": "NULL handling",
        "columns": ["null_quantity", "null_country", "sum_quantity_or_1", "count_country_nonempty",
                    "distinct_country"],
        "group": False,
        "text": ("`null_*` count NULLs; `sum_quantity_or_1` = sum of `coalesce(quantity, 1)`; "
                 "`count_country_nonempty` = rows with country not NULL and not the empty string; "
                 "`distinct_country` = number of distinct non-NULL countries (the empty string counts)."),
        "sql": """SELECT count(*) FILTER (WHERE quantity IS NULL), count(*) FILTER (WHERE country IS NULL),
                  sum(coalesce(quantity, 1))::BIGINT,
                  count(*) FILTER (WHERE country IS NOT NULL AND country <> ''),
                  count(DISTINCT country) FROM sales""",
    },
    "OP21": {
        "name": "decimal_arithmetic",
        "title": "Exact decimal sum vs float64 sums",
        "columns": ["exact_sum_cents", "exact_sum_decimal"],
        "floats": ["naive_sum", "kahan_sum"],
        "group": False,
        "text": ("`exact_sum_cents` = int64 sum of cents; `exact_sum_decimal` = that value formatted as "
                 "`<int>.<2-digit>` (e.g. `123456.07`). Floats: with `v = cents / 100.0` (IEEE division), "
                 "`naive_sum` = left-to-right sum of v in row order; `kahan_sum` = Kahan-compensated sum "
                 "of v in row order. Float results are compared with rtol 1e-9; engines that sum in "
                 "parallel are allowed to differ within that tolerance."),
        "sql": f"""SELECT sum({CENTS})::BIGINT,
                   (sum({CENTS}) // 100)::VARCHAR || '.' || lpad((sum({CENTS}) % 100)::VARCHAR, 2, '0'),
                   sum(({CENTS})::DOUBLE / 100.0), fsum(({CENTS})::DOUBLE / 100.0) FROM sales""",
    },
    "OP22": {
        "name": "type_conversion_roundtrip",
        "title": "Type-conversion round trips (counts of lossy rows)",
        "columns": ["lossy_int64_float64", "lossy_decimal_float64", "lossy_ts_millis", "sum_yyyymmdd"],
        "group": False,
        "text": ("With `k = transaction_id * 4294967311 + customer_id` (int64): count rows where "
                 "`int64(float64(k)) != k` (round-to-nearest conversion). `lossy_decimal_float64`: with "
                 "`f = cents / 100.0`, count rows where `trunc(f * 100.0) != cents`. `lossy_ts_millis`: "
                 "count rows where `(us div 1000) * 1000 != us`. `sum_yyyymmdd`: sum over rows of "
                 "`year*10000 + month*100 + day` of the date (civil_from_days)."),
        "sql": f"""SELECT
          count(*) FILTER (WHERE (transaction_id * 4294967311 + customer_id)::DOUBLE::BIGINT
                           <> transaction_id * 4294967311 + customer_id),
          count(*) FILTER (WHERE trunc((({CENTS})::DOUBLE / 100.0) * 100.0)::BIGINT <> {CENTS}),
          count(*) FILTER (WHERE (epoch_us(transaction_timestamp) // 1000) * 1000
                           <> epoch_us(transaction_timestamp)),
          sum(year(transaction_date) * 10000 + month(transaction_date) * 100 + day(transaction_date))::BIGINT
          FROM sales""",
    },
}


def spec_markdown(op_id: str) -> str:
    o = OPS[op_id]
    cols = ", ".join(f"`{c}`" for c in o["columns"])
    floats = o.get("floats")
    input_kind = "CSV chunk files" if o.get("csv_input") else "dataset A (CSV chunks for Track L, Parquet for Track S)"
    lines = [
        f"# {op_id} - {o['title']}", "",
        f"Dataset: A (`sales_fact`). Input: {input_kind}. Registry name: `{o['name']}`.", "",
        o["text"], "",
        "## Result", "",
        f"Result rows (digested, exact): columns {cols}"
        + (" - one row per group." if o["group"] else " - exactly one row."),
    ]
    if floats:
        lines += ["", "Float results (not digested, rtol 1e-9): " + ", ".join(f"`{f}`" for f in floats) + "."]
    lines += ["", "Report `checksum` and `row_count` via the result digest (spec/checksum.md, "
              "\"Result digests\"); `floats` as a JSON object. NULL values are digested as NULL, not as 0.",
              "", "## Oracle", "", "DuckDB over the generated Parquet files:", "", "```sql",
              o["sql"].strip().replace("sales", "sales"), "```", ""]
    return "\n".join(lines)
