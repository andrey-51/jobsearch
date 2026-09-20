# Fantastic Jobs vs Apify — coverage comparison

This is a **read-only comparison study**. You are not extending an ingestion pipeline and you
are not adding rows to anything.

## Objective

Andrey ingests UK enterprise-sales job postings into a Notion "Role Intake" database via an
Apify actor. Determine whether calling the **Fantastic Jobs API directly** would have surfaced
a materially different set of jobs over 2026-09-10 to 2026-09-19, and if so, which jobs each
path missed.

Deliverable: a written comparison plus a per-job diff table.

## Hard constraints

1. **Write nothing to Notion.** Not Role Intake, not Roles, not Outreach, not any page. You may
   *read* Role Intake (`collection://441379e4-d36a-4d53-b834-57242e0dafb3`) to pull the
   `Human Verdict` column. Reads only.
2. **Never write an API token or key into a file, a commit, a log, or a Notion page.** Read
   credentials from environment variables only. `APIFY_TOKEN` is already in the environment.
3. **Do not re-run the Apify actor.** The four runs are completed, immutable executions.
   Re-running costs money and returns identical data.
4. **Do not modify `pipeline.py`.** Both sides must be scored by the same unmodified code.
5. Report what you observe. If a query returns nothing, say so. Do not reconstruct a
   plausible-looking result set.

## Two gating steps, in this order, before any comparison code

**1. Verify the wrapper hypothesis.** The Apify actor is very likely Fantastic Jobs itself. See
`context/fantastic-jobs-api.md` for the evidence. If it holds, this is a wrapper-vs-wrapped
study, not a coverage study, and that changes what the report is about. Tell Andrey which case
you are in before proceeding.

**2. Confirm the credential.** There is **no Fantastic Jobs / RapidAPI key in this
environment**. Ask Andrey to supply one as `RAPIDAPI_KEY`. If he does not have a subscription,
stop and say so; most of this study is not executable without it. Do not work around a missing
key by scraping or by inferring results.

## Layout

| Path | What it holds |
|---|---|
| `context/apify-actor.md` | The four runs, the exact actor input, how to re-fetch the datasets |
| `context/fantastic-jobs-api.md` | Wrapper evidence, credential gap, unverified parameter mapping |
| `context/rubric.md` | How scoring works, and why the verdict column is not yet trustworthy |
| `memory/anomalies.md` | Findings that will mislead you if you do not know them |
| `data/apify_baseline_week.csv` | **The baseline**: 149 unique jobs, one row each |
| `data/apify_input.json` | The exact Apify actor input in use |
| `.claude/skills/source-comparison/SKILL.md` | The method to follow |
| `.claude/skills/source-comparison/pipeline.py` | Rubric v1.1 scorer. Do not modify |

Read `memory/anomalies.md` before designing the comparison. Two of the entries there change the
query window.

## Write-up style

Weakest part of the argument first. No opening praise, no closing reassurance, no invented
flaws. If the two paths turn out to be equivalent, say that in the first line rather than
padding the report to justify the exercise. Avoid em-dashes.
