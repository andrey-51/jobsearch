# Fantastic Jobs direct API vs Apify: coverage comparison

Study date 2026-09-20. Window: `date_created` 2026-09-10 to 2026-09-19 inclusive.
Baseline: `data/apify_baseline_week.csv` (149 unique jobs). Per-job diff: `data/coverage_diff.csv`.

## The weakest part of this report, first

**The headline question is not answered, because no direct-API pull was made.** The comparison
this study was commissioned to run requires calling Fantastic Jobs directly, and this
environment's egress policy refuses `CONNECT` to every host that would serve it:

```
rapidapi.com                   blocked (gateway 403 to CONNECT)
active-jobs-db.p.rapidapi.com  blocked
api.fantastic.jobs             blocked
fantastic.jobs                 blocked
api.apify.com                  reachable
```

This is a policy denial at the proxy, not a missing credential and not a TLS fault. A
key-shaped credential is present in the environment, but under the name `RapidAPI`, not
`RAPIDAPI_KEY` as the handoff specifies. It is 46 characters, is not the Apify token, and does
not carry RapidAPI's usual `msh` prefix. It could not be tested against anything, so whether it
is a valid Active Jobs DB key remains unknown. Nothing was scraped and no result set was
reconstructed.

So the three set sizes the brief asks for, Apify-only, direct-only, and both, are **not
measured**. Everything below about the direct API is inference from the actor's identity and its
published input schema. Everything below about the Apify side is measured.

## Which case we are in: wrapper, confirmed, and stronger than the hypothesis

Not a coverage study. Not even a third-party wrapper study.

Apify actor `s3dtSTZSZWFtAVLn5` is published by the Apify account **`fantastic-jobs`**, titled
"Career Site Job Listing API", described as "Powered by Fantastic.jobs". Its build's input
schema is titled **"Fantastic Jobs ATS API"**. It is Fantastic Jobs' own first-party actor over
their own Active Jobs DB.

The corpus is therefore identical by construction. There is no second source. Any difference
between the two paths can only come from parameter translation, limits, pagination or actor-side
dedup, and the parameter surface argues against even that: the actor exposes 38 inputs that are
camelCase restatements of the API's own query parameters, including a `liIndustryExclusionFilter`
that takes LinkedIn industry names with "same exact, case-sensitive matching as LinkedIn
Industries". The 26-industry exclusion the handoff flagged as "the single most likely source of a
spurious difference" is expressible on the actor side natively, and the `:*` prefix syntax is
documented in the schema rather than reimplemented.

Two corrections to the handoff's description while we are here:

- The exclusion list has **26 industries, not 36**.
- `limit` is documented as **minimum 10, maximum 5,000**, default 10. The 100 in Andrey's input
  is his own choice, not a ceiling the actor imposes. The "100-item cap that is itself under
  test" is not a property of the Apify path.

I did not correct the parameter-mapping table against the live RapidAPI documentation, because
that documentation is behind the same blocked host. The actor's input schema is the nearest
available substitute and is reproduced in effect above.

## Anomaly 1: settled. The actor does not back-fill.

The stored `INPUT` records of all four runs are readable from Apify without re-running anything.
They are not the input in `data/apify_input.json`:

| Run | `timeRange` | `limit` | `liIndustryExclusionFilter` | Items |
|---|---|---|---|---|
| `mbx` (09-17 08:47Z) | **7d** | 100 | **absent** | 100 |
| `EHR` (09-17 13:52Z) | **7d** | **500** | present (26) | 99 |
| `OQq` (09-18 15:08Z) | 24h | 100 | present (26) | 20 |
| `uOi` (09-19 19:10Z) | 24h | 100 | present (26) | 10 |

The 09-17 runs returned a week because they **asked for a week**. Of the two candidate
explanations in `memory/anomalies.md`, the first is correct and the second is false: the actor
does not widen a narrow window to fill `limit`. Andrey's daily "24h" runs are honest 24-hour
windows and are not silently back-filling.

This also means `data/apify_input.json` does not describe any of the four runs. Two of them
differ from it in three fields.

## Anomaly 3: settled. The two 09-17 runs were never comparable.

`mbx` and `EHR` did not run "nominally the same filters". `mbx` had **no industry exclusion at
all** and a `limit` of 100; `EHR` had the 26-industry exclusion and a `limit` of 500. Their
80-record overlap needs no appeal to non-determinism. The 20 `mbx`-only records decompose
exactly, with nothing left over:

| Cause | Count |
|---|---|
| Industry excluded by `EHR`'s filter, which `mbx` did not apply | 14 |
| `date_created` fell before `EHR`'s window opened, 5 hours later | 6 |
| Unexplained | **0** |

The second group is the sliding-window effect: `mbx` ran at 08:47Z so its 7-day window opened at
09-10T08:47Z; `EHR` ran at 13:52Z so its window opened at 09-10T13:52Z. Six jobs created on
09-10 between those times were inside one window and outside the other.

The `EHR`-only 19 are `mbx` truncating at its `limit` of 100. `EHR` asked for 500 and got 99, so
99 is the true size of the filtered 7-day corpus, not a truncation.

**The result set is not shown to be non-deterministic at the `limit: 100` boundary.** That
concern can be retired for now. A single 100-capped call was not the problem.

## Anomaly 4: settled. The 20 were never meant to be ingested.

`EHR ∪ OQq ∪ uOi` is exactly the 129 rows marked `scored=yes`, id for id. The 20 dropped rows are
precisely the `mbx`-only set. `mbx` was an exploratory run, made without the industry filter and
five hours before the run that was actually ingested, and its extra rows simply never entered the
pipeline. Nothing dropped them mid-flight.

Scoring those 20 with unmodified `pipeline.py` (`INTAKE_DATE=2026-09-20`, md5
`d860a72e15f883af6e713e8106707204` before and after) gives 4 Strong, 3 Partial, 13 Noise, with 9
hard fails.

The split by cause matters more than the totals:

- Of the **14 industry-excluded** jobs, **8 hard-fail the rubric on their own** (5 Agency/PR, 3
  Insurance broker), and none of the remaining 6 clears 57. The 26-industry exclusion is close to
  redundant with the rubric's own hard fails over this week. It cost nothing.
- Of the **6 window-slide** jobs, **4 are machine-Strong**: IFS at 77, Stripe at 75, Experian at
  73, a second IFS at 73. The remaining two are Google at 59 and Bitwarden, the set's only
  Wrong location/US leak hard fail. The top scorer in the whole never-ingested set is a window
  artefact, not an industry artefact.

So the filter Andrey configured deliberately cost him nothing this week. The run timing he did
not configure cost him four Strong roles.

## The finding the study was not looking for: 10% of the window was never queried

Reconstructing coverage from the ingested runs' actual start times and window lengths:

```
covered  2026-09-10 13:52:15 -> 2026-09-17 13:52:15   (EHR, 7d)
covered  2026-09-17 15:08:59 -> 2026-09-18 15:08:59   (OQq, 24h)
covered  2026-09-18 19:10:22 -> 2026-09-19 19:10:22   (uOi, 24h)
```

Against the nominal 10-day window that leaves **exactly 24 hours unqueried, 10% of the span**:

| Unqueried band | Duration | Recoverable? |
|---|---|---|
| 09-10 00:00 → 09-10 13:52 | 13h52m | Partly. `mbx` covered most of it but was not ingested |
| 09-17 13:52 → 09-17 15:09 | 1h17m | **No.** Permanently missed |
| 09-18 15:09 → 09-18 19:10 | 4h01m | **No.** Permanently missed |
| 09-19 19:10 → 09-20 00:00 | 4h50m | Yes, if the next run happens within 24h |

The two interior bands, 5h18m, are unrecoverable: a 24-hour window run later never reaches back
past its own opening. The cause is that the runs are manual and irregular, at 08:47, 13:52,
15:08 and 19:10 on successive days. The actor's own schema says it plainly: "We strongly
recommend running the Actor at the same time every hour/day/week to ensure that you get all jobs
without duplicates."

**How many jobs are in those two bands is exactly what the blocked direct API would have told
us.** It is the one number this study most wanted and cannot supply.

## Ingestion losses: 10 scored rows never reached Role Intake

Role Intake holds 119 rows. 129 were scored. Every Role Intake row joins to the baseline, so
nothing is there that should not be.

- **8** are `dedup_key` collisions where a sibling with the same key was written instead. The
  worst is Check Point's "Major Account Manager, Public Sector", posted under three requisition
  IDs, where the row that survived scored **55** and the two dropped both scored **59**. Dedup
  keeps the first-seen row, not the best-scoring one.
- **1** extra sibling was written anyway and flagged `Duplicate`, rather than dropped. Intapp's
  "Enterprise Account Executive - Legal" appears twice. So dedup drops in 8 cases and flags in 1,
  which is inconsistent.
- **2 are unexplained and both are machine-Strong**: Siteimprove "Account Executive" at **79**
  and Behavox "Strategic Account Manager 3" at **71**. Both have unique dedup keys, no sibling in
  Role Intake, and no hard fail. They were scored and then lost. This is a real defect and it is
  separate from everything else in this report.

The anomalies file's prediction about NAVEX holds only halfway. "Account Director - Enterprise"
and "Enterprise Account Director" are both in Role Intake as separate rows, and their
`dedup_key`s do differ (`navex|account director - enterprise` versus
`navex|enterprise account director`), so the key did not collide as predicted. But the second row
carries a `Duplicate` flag anyway. `pipeline.py` sets that flag only for same-key siblings, so
its origin here is not explained by anything in this handoff. Worth a look, since it means the
`Duplicate` column is not a pure function of `dedup_key`.

## Calibration state has changed since `context/rubric.md` was written

`context/rubric.md` says 59 labels, all Noise, zero acceptances, no classifier fittable. Reading
Role Intake today gives **73 labels, and 9 of them are not Noise**:

| Machine | Human Noise | Human Partial | Human Strong | Unlabelled |
|---|---|---|---|---|
| Strong | 20 | 5 | 1 | 10 |
| Partial | 25 | 1 | 0 | 29 |
| Noise | 19 | 2 | 0 | 7 |

Among reviewed rows, 6 of 26 machine-Strong are not Noise (23%), against 1 of 26 machine-Partial
(3.8%). That is the first sign of the Strong band carrying signal. It is 6 events, the confidence
interval is wide, and machine-Noise at 2 of 21 (9.5%) sits above machine-Partial, which it should
not if the score were monotone. The rubric caveat still stands and I am not presenting any count
of Strong roles as a benefit. But "zero acceptances, no classifier can currently be fitted" is
out of date and the file should be corrected.

## Cost

**Apify path, measured.** Andrey is on the **FREE** plan: $5 of monthly usage credit, hard capped,
cycle ending 2026-09-29. The actor charges per dataset item, $0.012 at FREE tier, plus $0.01 per
actor start.

| Run | Items | Charged |
|---|---|---|
| `mbx` | 100 | $1.210 |
| `EHR` | 99 | $1.198 |
| `OQq` | 20 | $0.250 |
| `uOi` | 10 | $0.130 |
| **Total** | 229 | **$2.788** |

**Cost per 100 jobs on Apify: $1.21.** One week of this consumed 56% of the monthly allowance,
and 229 items were charged to obtain 149 unique jobs, so 35% of the spend went on the `mbx`/`EHR`
overlap.

Current usage is **$4.04 of $5** with nine days left in the cycle. Two consequences, both
already visible in the run records:

1. Apify caps each run to the remaining credit. The `maxItems` the platform set on the four runs
   was 376, 225, 115 and 93, falling as credit depleted, and none of these was set by Andrey. The
   next run will be capped near **79 items** regardless of the `limit: 100` in the input. Within
   about five days the cap reaches zero and runs return nothing.
2. Tiered pricing does not help at this volume: SILVER is $0.006/job and GOLD $0.004, but both
   sit behind paid Apify plans.

**Direct path: not determinable.** Fantastic Jobs' RapidAPI pricing is behind the blocked host. I
will not put a number on it. The relevant comparison is that the $0.012/job Andrey pays includes
Apify's 20% platform margin, so the direct price is bounded above by it, but by how much is
unmeasured.

One unrelated hazard found in the same place: FREE-tier **dataset retention is 7 days**. The
`mbx` and `EHR` datasets from 09-17 expire around 09-24. They were re-fetched intact for this
study; after that date the raw JSON is gone and only the committed CSV survives.

## Recommendation

**Fix the cadence first. Do not switch sources yet.**

The tradeoff as it actually stands:

- *Stay on Apify.* Zero migration work, and the corpus is identical because the actor is
  first-party. But $0.012/job on a $5 cap does not fund this: the free tier is exhausted in about
  five days, and the run cap is already degrading silently.
- *Switch to the direct API.* Removes Apify's 20% margin and the per-run start fee, and removes
  the credit-derived `maxItems` cap. But the price is unverified, the credential is untested, and
  the migration cannot be validated from this environment at all.
- *Run both.* Pays twice for one corpus. There is no coverage argument for it, because there is
  only one corpus.

I would **stay on Apify and change the configuration**, for one reason: not one of the losses
this study found is attributable to the source. Four Strong roles were lost to irregular run
times, two to an ingestion bug, and eight to dedup keeping the first row rather than the best
one. Switching to the direct API fixes none of those and would have produced the same 149 jobs.

Concretely, in priority order:

1. **Schedule the run.** Same time daily, `timeRange: 24h`. Apify's scheduler is available on
   FREE. This closes the 5h18m of permanently missed window and is the only change here that
   recovers Strong roles.
2. **Find the two lost rows.** Siteimprove 2362176766 and Behavox 2372233676 scored 79 and 71,
   passed dedup, and never arrived. Until that is understood, the ingest count cannot be trusted.
3. **Resolve the credit cap within nine days**, by upgrading, by moving to the direct API, or by
   accepting a gap. Doing nothing means runs quietly returning fewer rows and then none, which
   looks exactly like a coverage drop and is not one.
4. **Make dedup keep the highest-scoring row**, not the first seen. Check Point cost 4 points of
   fit score for no reason.
5. **Correct `data/apify_input.json`** to match a run that was actually made, and fix the two
   documentation errors: 26 industries not 36, and `limit` max 5,000 not 100.

Re-run this comparison properly once a RapidAPI key can be reached. It is a half-day of work with
network access and it would settle the one open question: how many jobs sit in the two unqueried
bands.

## What could not be tested, and why

| Item | Status |
|---|---|
| Direct-API pull over the aligned window | **Blocked.** Egress policy denies all RapidAPI and Fantastic Jobs hosts |
| Set sizes: Apify-only, direct-only, both | **Not measured.** Requires the above |
| Per-job reason each path missed a job | Done for the Apify path only. There is no direct-only set |
| Validity of the `RapidAPI` credential | **Untested.** Nothing to test it against |
| Live RapidAPI parameter documentation | **Blocked.** Substituted the actor's published input schema |
| Whether `timeRange` binds `date_created` on the direct API | **Untested.** Confirmed on the Apify side: `EHR` contains `date_posted` back to 2026-04-13, so anomaly 2 holds there |
| ID parity between the two paths | **Untested.** Would need both sides |
| Direct-API cost per 100 jobs | **Not determinable.** Pricing page is behind the blocked host |
| How many jobs fall in the two unqueried bands | **Blocked.** This is the study's most valuable missing number |
| Zero-salary placeholder handling | Not re-tested. No zero-valued `MonetaryAmount` appears in the 20 rescored rows |

## Method notes

- Nothing was written to Notion. Role Intake was read only, via SQL over
  `collection://441379e4-d36a-4d53-b834-57242e0dafb3`.
- The actor was not re-run. All four datasets and their stored `INPUT` records were re-fetched
  from completed runs via the Apify REST API.
- `pipeline.py` was not modified; md5 `d860a72e15f883af6e713e8106707204` is unchanged. It requires
  a `roles.tsv` cross-reference that is not in this handoff, so it was run against an **empty**
  `roles.tsv`. That suppresses the `Intake Status: Promoted` assignment only, which happens after
  scoring; fit scores, verdicts and hard fails are unaffected.
- No credential value appears in this report, in `data/coverage_diff.csv`, or in any commit.
