# Dataset size estimates

Measured by generating and writing a real sample of each table, then extrapolating bytes/row linearly (compression: `zstd`, price as `decimal`). Estimates are conservative: measured on a 100k-row sample, so compressed formats usually come out 10-30% larger than the real 1M-row chunk files. `wide_numeric` is capped at 100M rows unless `--allow-large-wide`.

## Bytes per row (measured)

| table | arrow in-memory | parquet | csv |
|---|---|---|---|
| sales_fact | 104.6 | 37.0 | 110.0 |
| dim_customer | 97.2 | 15.2 | 83.7 |
| dim_product | 106.2 | 11.6 | 104.2 |
| events_log | 391.2 | 61.5 | 409.6 |
| wide_numeric | 968.0 | 1057.6 | 2130.1 |

## Projected sizes per scale N

| N | table | rows | arrow in-memory | parquet | csv |
|---|---|---|---|---|---|
| 1k | sales_fact | 1,000 | 102.2 KB | 36.1 KB | 107.4 KB |
| 1k | dim_customer | 100 | 9.5 KB | 1.5 KB | 8.2 KB |
| 1k | dim_product | 10 | 1.0 KB | 116 B | 1.0 KB |
| 1k | events_log | 1,000 | 382.1 KB | 60.0 KB | 400.0 KB |
| 1k | wide_numeric | 1,000 | 945.3 KB | 1.0 MB | 2.0 MB |
| 10k | sales_fact | 10,000 | 1021.7 KB | 361.5 KB | 1.0 MB |
| 10k | dim_customer | 1,000 | 94.9 KB | 14.9 KB | 81.7 KB |
| 10k | dim_product | 100 | 10.4 KB | 1.1 KB | 10.2 KB |
| 10k | events_log | 10,000 | 3.7 MB | 600.2 KB | 3.9 MB |
| 10k | wide_numeric | 10,000 | 9.2 MB | 10.1 MB | 20.3 MB |
| 1m | sales_fact | 1,000,000 | 99.8 MB | 35.3 MB | 104.9 MB |
| 1m | dim_customer | 100,000 | 9.3 MB | 1.5 MB | 8.0 MB |
| 1m | dim_product | 10,000 | 1.0 MB | 113.5 KB | 1017.9 KB |
| 1m | events_log | 1,000,000 | 373.1 MB | 58.6 MB | 390.7 MB |
| 1m | wide_numeric | 1,000,000 | 923.2 MB | 1008.6 MB | 2.0 GB |
| 10m | sales_fact | 10,000,000 | 997.8 MB | 353.0 MB | 1.0 GB |
| 10m | dim_customer | 1,000,000 | 92.7 MB | 14.5 MB | 79.8 MB |
| 10m | dim_product | 100,000 | 10.1 MB | 1.1 MB | 9.9 MB |
| 10m | events_log | 10,000,000 | 3.6 GB | 586.1 MB | 3.8 GB |
| 10m | wide_numeric | 10,000,000 | 9.0 GB | 9.9 GB | 19.8 GB |
| 100m | sales_fact | 100,000,000 | 9.7 GB | 3.4 GB | 10.2 GB |
| 100m | dim_customer | 10,000,000 | 926.7 MB | 145.1 MB | 798.2 MB |
| 100m | dim_product | 1,000,000 | 101.2 MB | 11.1 MB | 99.4 MB |
| 100m | events_log | 100,000,000 | 36.4 GB | 5.7 GB | 38.2 GB |
| 100m | wide_numeric | 100,000,000 | 90.2 GB | 98.5 GB | 198.4 GB |
| 1b | sales_fact | 1,000,000,000 | 97.4 GB | 34.5 GB | 102.4 GB |
| 1b | dim_customer | 50,000,000 | 4.5 GB | 725.7 MB | 3.9 GB |
| 1b | dim_product | 1,000,000 | 101.2 MB | 11.1 MB | 99.4 MB |
| 1b | events_log | 1,000,000,000 | 364.4 GB | 57.2 GB | 381.5 GB |
| 1b | wide_numeric | 100,000,000 | 90.2 GB | 98.5 GB | 198.4 GB |
