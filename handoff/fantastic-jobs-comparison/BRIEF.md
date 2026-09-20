# Handoff: Fantastic Jobs direct API vs Apify — coverage comparison

You are a code agent. Your job is a **read-only comparison study**. You are not extending the
ingestion pipeline and you are not adding rows to anything.

## Objective

Andrey ingests UK enterprise-sales job postings into a Notion "Role Intake" database via an
Apify actor. He wants to know whether calling the **Fantastic Jobs API directly** would have
surfaced a materially different set of jobs over the last week, and if so, which jobs the
Apify path missed or added.

Deliverable: a written comparison plus a per-job diff table. No writes to Notion.

## Hard constraints — do not violate

1. **Write nothing to Notion.** Not to Role Intake, not to Roles, not to Outreach, not to any
   page. You may *read* Role Intake (`collection://441379e4-d36a-4d53-b834-57242e0dafb3`) to
   pull the `Human Verdict` column. Reads only.
2. **Never write an API token or key into a file, a commit, a log, or a Notion page.** Read
   credentials from environment variables only. `APIFY_TOKEN` is already in the environment.
3. Do not re-run the Apify actor. The four runs below are completed, immutable executions and
   the data is already captured in this directory. Re-running costs money and proves nothing.
4. Report what you actually observe. If a query returns nothing, say so; do not reconstruct a
   plausible-looking result set.

## BLOCKER you will hit immediately

**There is no Fantastic Jobs / RapidAPI credential in this environment.** I checked: the only
tokens present are `APIFY_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN` and Claude/gcloud internals.

Fantastic Jobs' "Active Jobs DB" is distributed through RapidAPI and needs an
`X-RapidAPI-Key`. Before doing anything else, confirm with Andrey that he has a subscription
and get the key supplied as an environment variable (suggest `RAPIDAPI_KEY`). If he does not
have one, stop and tell him — most of this brief is not executable without it. Note that a
free RapidAPI tier may cap results or strip fields, which would confound the comparison; if
he is on a free tier, say so explicitly in your report rather than treating truncated results
as evidence of narrower coverage.

Do not attempt to work around the missing key by scraping, by using an unofficial mirror, or
by inferring results.

## The thing you should check first, before writing any comparison code

**The Apify actor almost certainly *is* Fantastic Jobs.** Every record in the captured runs
carries the Active Jobs DB schema — `ai_experience_level`, `ai_work_arrangement`,
`ai_requirements_summary`, `org_linkedin_headcount`, `org_linkedin_industry`,
`locations_derived`, `regions_derived`, `source_type`. The Apify input field names
(`liIndustryExclusionFilter`, `aiExperienceLevelFilter`, `titleSearch` with `:*` prefix
syntax) are camelCase restatements of that API's query parameters. The Apify actor ID is
`s3dtSTZSZWFtAVLn5`.

If that holds, this is **not** a comparison of two job corpora. It is a comparison of a
wrapper against the thing it wraps, and any difference you find will come from parameter
translation, result limits, pagination, or dedup inside the actor — not from one source
knowing about jobs the other does not. That is still a worthwhile finding, and it changes what
the report should be about. **Verify this first** (check the actor's Apify store page and the
Fantastic Jobs RapidAPI docs) and tell Andrey in your first message which case you are in,
because it determines whether the rest of the study is about coverage or about plumbing.

## What the Apify side actually did

Four completed runs, all from Andrey's account, all with the input in `apify_input.json`
(modulo `timeRange`, see the anomaly below):

| Run ID | Ran on | Items | `date_created` span of results |
|---|---|---|---|
| `mbxBWQqaJiWjbFFfC` | 2026-09-17 | 100 | 2026-09-10 .. 2026-09-17 |
| `EHR7huYa7StCS0dKE` | 2026-09-17 | 99 | 2026-09-10 .. 2026-09-17 |
| `OQqri0wrnB1gqoFmy` | 2026-09-18 | 20 | 2026-09-17 .. 2026-09-18 |
| `uOioaGBo3ulYMUng2` | 2026-09-19 | 10 | 2026-09-18 .. 2026-09-19 |

149 unique job IDs across all four. `mbx` and `EHR` overlap by 80; the other pairs overlap by
zero. Of the 149, **129 were scored and written to Notion** and 20 (all `mbx`-only) never
entered the pipeline.

Raw datasets are re-fetchable without re-running the actor:

```
curl -sS "https://api.apify.com/v2/actor-runs/<RUN_ID>/dataset/items?format=json&clean=true&token=$APIFY_TOKEN"
```

### Two anomalies worth testing against the direct API

**1. `timeRange: "24h"` did not produce a 24-hour window on the 09-17 runs.** Both `mbx` and
`EHR` ran on 2026-09-17 and returned records created as far back as 2026-09-10 — a full week.
The 09-18 and 09-19 runs returned 1-2 days each, as expected. Either `timeRange` was set
differently on those two runs, or the actor widens the window when a narrow one underfills the
`limit: 100`. Determine which. If it is the latter, Andrey's daily "24h" runs are silently
back-filling, and the direct API may behave differently.

**2. `timeRange` filters on `date_created`, not `date_posted`.** The `EHR` set contains
postings with `date_posted` back to 2026-04-13 — old jobs newly added to the database.
Confirm the same semantics hold on the direct API, and use `date_created` for window
alignment. Getting this wrong will produce a fake difference.

## Comparison window

Use **`date_created` from 2026-09-10 to 2026-09-19 inclusive** (10 days). This is the real
span of Apify coverage, not the nominal 24h. Query the direct API for the same window with the
same filters, paginating to exhaustion rather than stopping at 100.

## Parameter mapping — treat as a hypothesis, verify against live docs

Do not trust this table. Read the Fantastic Jobs RapidAPI documentation and correct it. It is
here to save you a first pass, not to be copied.

| Apify input | Likely direct-API equivalent | Verify |
|---|---|---|
| `titleSearch` (array, `:*` prefix wildcards) | `title_filter` — may need a single OR-joined string with quoted phrases; `:*` is Postgres full-text prefix syntax | how arrays are joined; whether `:*` passes through |
| `titleExclusionSearch` | `title_exclude_filter` or a `NOT` clause in `title_filter` | whether a separate param exists at all |
| `locationSearch` | `location_filter` | array vs OR-joined string |
| `aiExperienceLevelFilter: ["5-10","10+"]` | `ai_experience_level_filter` | exact value spellings |
| `liIndustryExclusionFilter` (36 industries) | `li_industry_filter` with negation, or `organization_exclude` | **most likely to differ** — if the direct API has no exclusion parameter, you must apply the 36-industry exclusion client-side, and you must then also apply it to the Apify set for a fair comparison |
| `timeRange: "24h"` | `date_filter` / `date_created` lower bound, ISO 8601 | which date field it binds to |
| `includeCompanyDetails: true` | `include_ai` / `description_type` / org-enrichment flag | whether `org_linkedin_*` fields require a higher tier |
| `limit: 100` | `limit` + `offset` | max page size; whether pagination is offset or cursor |
| `removeAgency: false` | `org_linkedin_recruitment_agency_derived` filter | — |

The 36-industry exclusion list is the single most likely source of a spurious difference. If
you cannot reproduce it server-side, filter both sides client-side on
`org_linkedin_industry` and say that you did.

## Files in this directory

- `apify_input.json` — the exact Apify actor input Andrey uses
- `apify_baseline_week.csv` — **the baseline**: all 149 unique jobs, one row each, with
  `apify_runs` (which runs returned it), `date_posted`, `date_created`, `source_ats`,
  `org_industry`, `org_headcount`, `locations_derived`, `url`, and for the 129 that were
  scored: `fit_score`, `machine_verdict`, `hard_fail_reason`, `dedup_key`
- `pipeline.py` — the scoring pipeline (rubric v1.1). Run as
  `INTAKE_DATE=YYYY-MM-DD python3 pipeline.py <raw_run.json>` → writes `prepared.json`.
  Six dimensions summing 95, rescaled ×100/95; ≥70 Strong, 55-69 Partial, <55 Noise; hard
  fails bypass scoring entirely (score 0, verdict Noise). **Do not modify it.** Score the
  direct-API pull with this exact file so the two sides are comparable.
- `bodies.py` — page-body builder. You will not need it; included for completeness.

## Method

1. Verify the wrapper hypothesis. Report which case you are in before proceeding.
2. Get the RapidAPI key from Andrey. Stop if unavailable.
3. Reproduce the filter set against the direct API for `date_created` 2026-09-10..2026-09-19,
   paginating to exhaustion. Save the raw JSON.
4. Join to `apify_baseline_week.csv` on the job `id`. Fantastic Jobs IDs should match exactly
   since the Apify records carry the same `id` field — confirm this on a few known rows before
   relying on it. If IDs do not match, fall back to `url`, then to
   normalised `organization` + `title`.
5. Produce the diff: **in both**, **Apify only**, **direct only**.
6. Score the direct-only set with the unmodified `pipeline.py` so the verdict distributions
   are comparable.
7. Read `Human Verdict` from Role Intake (read-only) and report how many direct-only jobs would
   have been machine-Strong. Context: Andrey has labelled 59 rows and **every one of the 19
   machine-Strong rows he reviewed came back Noise**, so machine-Strong is currently an
   unvalidated signal. Do not present "the direct API found N more Strong roles" as a benefit.
   Count them, and say plainly that the label is not yet worth anything.

## What the report must answer

- Is the Apify actor a wrapper over Fantastic Jobs? Evidence either way.
- Set sizes: Apify-only, direct-only, both, over the aligned window.
- For each **direct-only** job: title, company, industry, `date_created`, and the most likely
  reason Apify missed it (limit truncation, industry exclusion, title filter, time window,
  actor-side dedup).
- For each **Apify-only** job, same treatment.
- Whether any difference is attributable to a parameter that cannot be expressed on one side.
- Cost per 100 jobs on each path, if determinable.
- A recommendation: stay on Apify, switch, or run both. Give the tradeoff, then pick one.
- Anything you could not test, and why.

## Style notes for the final write-up

Andrey wants the weakest part of an argument first, no opening praise, no closing reassurance,
and no invented flaws. If the two paths turn out to be equivalent, say that in the first line
rather than padding the report to justify the exercise. Avoid em-dashes.
