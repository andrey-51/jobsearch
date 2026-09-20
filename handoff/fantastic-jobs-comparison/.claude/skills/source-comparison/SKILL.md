---
name: source-comparison
description: Compare the job set returned by the Fantastic Jobs API directly against the set returned by the Apify actor over an aligned window, and report the difference. Use when asked to run the source comparison, diff the two job feeds, or determine whether switching off Apify would change coverage.
---

# Source comparison

Read `CLAUDE.md`, `context/*.md` and `memory/anomalies.md` first. The constraints there
govern; this file is the method.

## Bundled files

- `pipeline.py` — rubric v1.1 scorer. Run it unmodified on both sides.
- `bodies.py` — Notion body builder. Not needed for this study.

## Method

**1. Verify the wrapper hypothesis.**
Check the Apify store listing for actor `s3dtSTZSZWFtAVLn5` and the Fantastic Jobs RapidAPI
docs. Report to Andrey which case you are in before writing comparison code. Evidence is in
`context/fantastic-jobs-api.md`.

**2. Get the credential.**
Ask for `RAPIDAPI_KEY`. Stop if unavailable. Do not work around it.

**3. Correct the parameter mapping.**
The table in `context/fantastic-jobs-api.md` is a guess. Replace it with what the live docs
say. Record what you changed and why.

**4. Pull the direct-API set.**
Window: `date_created` 2026-09-10 to 2026-09-19 inclusive. Same filters. **Paginate to
exhaustion** — the 100-item cap on the Apify side is itself under test. Save the raw JSON.

**5. Join and diff.**
Join to `data/apify_baseline_week.csv` on `id`. Confirm ID parity on a few known rows first;
fall back to `url`, then normalised `organization` + `title`. Produce three sets:
**in both**, **Apify only**, **direct only**.

**6. Score the direct-only set.**
`INTAKE_DATE=<today> python3 pipeline.py <direct_raw.json>` with `pipeline.py` unmodified, so
verdict distributions are comparable.

**7. Pull human labels.**
Read `Human Verdict` from Role Intake (`collection://441379e4-d36a-4d53-b834-57242e0dafb3`),
read-only. Report how many direct-only jobs would have been machine-Strong, with the caveat
from `context/rubric.md` attached. Do not frame extra Strong rows as a benefit.

## The report must answer

- Is the Apify actor a wrapper over Fantastic Jobs? Evidence either way.
- Set sizes over the aligned window: Apify-only, direct-only, both.
- For each **direct-only** job: title, company, industry, `date_created`, and the most likely
  reason Apify missed it (limit truncation, industry exclusion, title filter, time window,
  actor-side dedup).
- For each **Apify-only** job: same treatment.
- Whether any difference traces to a parameter that cannot be expressed on one side.
- Which of the anomalies in `memory/anomalies.md` you were able to settle, and what you found.
- Cost per 100 jobs on each path, if determinable.
- A recommendation: stay on Apify, switch, or run both. Give the tradeoff, then pick one.
- Anything you could not test, and why.

## Output

A markdown report at the repository root of this handoff directory, plus the per-job diff as
CSV next to it in `data/`. Do not write to Notion.
