# Scoring rubric v1.1

`pipeline.py` scores a raw Apify/Fantastic Jobs dataset. **Do not modify it.** Score the
direct-API pull with this exact file so the two sides are comparable.

```bash
INTAKE_DATE=2026-09-20 python3 pipeline.py <raw_run.json>   # writes prepared.json
```

## How it scores

Six dimensions summing to 95 points, rescaled by ×100/95:

| Dimension | Max |
|---|---|
| Sales motion (IC closing / strategic ownership) | 25 |
| Seniority and deal profile | 20 |
| Domain (data / AI / cloud SaaS) | 20 |
| FSI vertical alignment | 10 |
| Company quality | 10 |
| Location and UK eligibility | 10 |

Thresholds: **≥70 Strong**, **55-69 Partial**, **<55 Noise**.

Hard fails bypass scoring entirely and land as score 0, verdict Noise. Current hard-fail
reasons in use: Insurance broker, Staffing poster, Agency/PR, Management track, Wrong
location/US leak.

Dedup key is `norm_company(company)|norm_title(title)` — lowercased, punctuation stripped,
company suffixes removed.

## The verdict column is not yet trustworthy

Andrey has hand-labelled 59 rows in Role Intake. **Every one of the 19 machine-Strong rows he
reviewed came back Noise**, including the top scorer at 87/100.

Consequences for your report:

- Do **not** present "the direct API surfaced N more Strong roles" as a benefit. Count them,
  and say plainly that the label carries no demonstrated signal yet.
- Use the verdict distribution as a *shape* comparison between the two sources, not as a
  quality measure of either.
- The 59 labels are all rejections. There are zero acceptances, so no classifier can currently
  be fitted. Do not attempt to fit one.

Two known weaknesses if you need to explain score behaviour:

- Dimension 6 (Location and UK eligibility) has stdev 0.98 with 74 of 100 rows at full marks.
  It functions as a flat +9.6 and mostly measures whether "London" appears in the location
  string.
- No dimension separates the rows Andrey rejected from the rows he left unlabelled. Total gap
  is +0.6 out of 100.

## Body builder

`bodies.py` turns scored rows into Notion page bodies. **You will not need it** — this study
writes nothing to Notion. It is bundled only so `pipeline.py` has its usual companion and the
scoring output can be inspected in the same form Andrey sees.
