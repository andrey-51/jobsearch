# Anomalies and findings

Things that will mislead you if you do not know them. The first two change the query window.

## 1. `timeRange: "24h"` did not produce a 24-hour window on the 09-17 runs

Both `mbxBWQqaJiWjbFFfC` and `EHR7huYa7StCS0dKE` ran on 2026-09-17 and returned records with
`date_created` reaching back to 2026-09-10 — a full week.

```
mbx (ran 09-17): 09-10:15  09-11:16  09-12:3  09-13:1  09-14:12  09-15:28  09-16:23  09-17:2
EHR (ran 09-17): 09-10:12  09-11:16  09-12:6  09-13:1  09-14:15  09-15:22  09-16:16  09-17:11
OQq (ran 09-18): 09-17:11  09-18:9
uOi (ran 09-19): 09-18:3   09-19:7
```

The 09-18 and 09-19 runs behaved as expected. Two candidate explanations:

- `timeRange` was set differently on those two runs, or
- the actor widens the window when a narrow one underfills `limit: 100`

**Determine which.** If it is the second, Andrey's daily "24h" runs are silently back-filling,
and the direct API may not do the same. This is one of the more useful things the study can
settle.

## 2. `timeRange` filters on `date_created`, not `date_posted`

The `EHR` set contains postings with `date_posted` as old as **2026-04-13** — jobs posted
months ago that were newly added to the database.

Confirm the same semantics on the direct API and align windows on `date_created`. Getting this
wrong will manufacture a difference that does not exist.

## 3. Two same-day runs overlapped by only 80 of ~100

`mbx` (100 items) and `EHR` (99 items) both ran on 2026-09-17 with nominally the same filters
and share only 80 records. Either the inputs differed, or the result set is not deterministic
at the `limit: 100` boundary. If the latter, a single 100-capped call does not reliably
represent the corpus, which matters for how you design the direct-API pull.

## 4. Twenty jobs were returned but never ingested

All 20 are `mbx`-only (`scored=no` in the baseline CSV). They were fetched and then dropped
before scoring. Explaining why is in scope for the report.

## 5. Known data defects in the source

- **Zero-valued salary placeholders.** Planview's JSON-LD carried
  `{value: 0, minValue: 0, maxValue: 0, currency: USD}`, which a naive formatter renders as
  `$0 / year`. `pipeline.py` was patched on 2026-09-19 to treat a zero MonetaryAmount as
  undisclosed. If you write your own parsing, do the same.
- **Duplicate requisitions under different IDs.** Intapp posted the same job text under three
  requisition numbers (R2025345, R2025352, R2025353) with two different titles. NAVEX posted
  "Account Director - Enterprise" and "Enterprise Account Director" as separate requisitions
  with 95.5% identical descriptions. Exact-ID matching will treat these as distinct; the
  `dedup_key` column will catch some but not the word-order variants.

## 6. Calibration state

59 rows in Role Intake carry a `Human Verdict`. All 59 are Noise. Zero acceptances. 19 of
those 59 were machine-Strong. See `context/rubric.md` for what this means for your report.
