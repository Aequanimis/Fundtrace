# Phase B0+B1 disclosure audit — 161005

## B0 topline experiment

| period | topline=100 | topline=200 | topline=500 | result |
|---|---:|---:|---:|---|
| 2024-06-30 | 100 rows | 10 rows | 10 rows | `TOPLINE_RESPONSE_UNRELIABLE` |
| 2025-12-31 | 100 rows | 10 rows | 10 rows | `TOPLINE_RESPONSE_UNRELIABLE` |

All six HTTP requests succeeded and each selected table was for the requested
period with no duplicate stock codes. `topline=200/500` returned only the first
10 rows, so their first 100 rows cannot be compared to the `topline=100`
response and there is no trustworthy 101+ result. This does **not** confirm
that topline=100 truncates the source; the higher-topline response is not a
reliable formal data source.

## Coverage index

| period | type | rows | holdings | reported equity | coverage | gap | coverage_type |
|---|---|---:|---:|---:|---:|---:|---|
| 2022-03-31 | Q1 | 40 | 0.6745 | 0.9365 | 0.7202 | 0.2620 | PARTIAL |
| 2022-06-30 | INTERIM | 100 | 0.9246 | 0.9397 | 0.9839 | 0.0151 | TOP_N_TRUNCATED |
| 2022-09-30 | Q3 | 35 | 0.6560 | 0.9383 | 0.6991 | 0.2823 | PARTIAL |
| 2022-12-31 | ANNUAL | 100 | 0.9203 | 0.9397 | 0.9794 | 0.0194 | TOP_N_TRUNCATED |
| 2023-03-31 | Q1 | 41 | 0.6391 | 0.9377 | 0.6816 | 0.2986 | PARTIAL |
| 2023-06-30 | INTERIM | 100 | 0.9185 | 0.9387 | 0.9785 | 0.0202 | TOP_N_TRUNCATED |
| 2023-09-30 | Q3 | 41 | 0.6392 | 0.9397 | 0.6802 | 0.3005 | PARTIAL |
| 2023-12-31 | ANNUAL | 100 | 0.9269 | 0.9451 | 0.9807 | 0.0182 | TOP_N_TRUNCATED |
| 2024-03-31 | Q1 | 51 | 0.6714 | 0.9453 | 0.7103 | 0.2739 | PARTIAL |
| 2024-06-30 | INTERIM | 100 | 0.9164 | 0.9440 | 0.9708 | 0.0276 | TOP_N_TRUNCATED |
| 2024-09-30 | Q3 | 43 | 0.6276 | 0.9450 | 0.6641 | 0.3174 | PARTIAL |
| 2024-12-31 | ANNUAL | 100 | 0.9025 | 0.9448 | 0.9552 | 0.0423 | TOP_N_TRUNCATED |
| 2025-03-31 | Q1 | 39 | 0.6713 | 0.9449 | 0.7104 | 0.2736 | PARTIAL |
| 2025-06-30 | INTERIM | 100 | 0.8782 | 0.9441 | 0.9302 | 0.0659 | TOP_N_TRUNCATED |
| 2025-09-30 | Q3 | 26 | 0.5116 | 0.9442 | 0.5418 | 0.4326 | PARTIAL |
| 2025-12-31 | ANNUAL | 100 | 0.8765 | 0.9437 | 0.9288 | 0.0672 | TOP_N_TRUNCATED |
| 2026-03-31 | Q1 | 33 | 0.5663 | 0.9447 | 0.5994 | 0.3784 | PARTIAL |
| 2026-06-30 | INTERIM | 10 | 0.4437 | 0.9433 | 0.4704 | 0.4996 | TOP10 |

- Counts: TOP10=1, PARTIAL=9, TOP_N_TRUNCATED=8, FULL_CONFIRMED=0, UNKNOWN=0.
- All Q1/Q3 records are conservatively `PARTIAL` with `QUARTERLY_PARTIAL` and
  `SOURCE_UNVERIFIED`; three Q1 records also expose local duplicate/missing
  holdings fields and are flagged accordingly.
- `available_date` remains empty and `available_date_status=UNVERIFIED` for
  every record.

## Still unverified / next step

The API's higher-topline behavior and the Q1/Q3 source provenance require
formal report-level verification. Phase B2/B3 can define disclosure dates and
decide how these diagnostics should affect model inputs; Phase B0+B1 does not
change any model path.
