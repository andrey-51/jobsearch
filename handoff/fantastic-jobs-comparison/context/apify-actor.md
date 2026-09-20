# The Apify side

Actor ID `s3dtSTZSZWFtAVLn5`, run from Andrey's Apify account via the web console.

## The four runs

All used the input in `data/apify_input.json`, modulo `timeRange` (see
`memory/anomalies.md`, entry 1).

| Run ID | Ran on | Items | `date_created` span of results |
|---|---|---|---|
| `mbxBWQqaJiWjbFFfC` | 2026-09-17 | 100 | 2026-09-10 .. 2026-09-17 |
| `EHR7huYa7StCS0dKE` | 2026-09-17 | 99 | 2026-09-10 .. 2026-09-17 |
| `OQqri0wrnB1gqoFmy` | 2026-09-18 | 20 | 2026-09-17 .. 2026-09-18 |
| `uOioaGBo3ulYMUng2` | 2026-09-19 | 10 | 2026-09-18 .. 2026-09-19 |

**149 unique job IDs** across all four. `mbx` and `EHR` overlap by 80 records; every other
pair overlaps by zero.

Of the 149:
- **129 were scored and written to Notion** (`scored=yes` in the baseline CSV)
- **20 were never ingested** — all `mbx`-only. Worth explaining in the report.

## Re-fetching the raw datasets

The raw JSON is not committed. Fetch it without re-running the actor:

```bash
curl -sS "https://api.apify.com/v2/actor-runs/<RUN_ID>/dataset/items?format=json&clean=true&token=$APIFY_TOKEN"
```

Roughly 2.8 MB across the four runs. If Apify has expired the datasets on Andrey's plan, say
so rather than proceeding with a partial baseline; the CSV still carries the fields the
comparison needs.

## Record schema

Each record has 71 fields. The ones that matter here:

- `id` — the join key against the baseline CSV
- `date_created` — when the record entered the database. **This is what `timeRange` filters on**
- `date_posted` — when the employer posted it. Can be months older than `date_created`
- `title`, `organization`, `url`, `source` (ATS: greenhouse, workday, ashby, icims, ...)
- `org_linkedin_industry`, `org_linkedin_headcount`, `org_linkedin_followers`
- `locations_derived`, `regions_derived`, `countries_derived`
- `ai_experience_level`, `ai_work_arrangement`, `ai_requirements_summary`, `ai_key_skills`
- `description_text` — the full JD
- `salary` — schema.org MonetaryAmount, sometimes a zero-valued placeholder

ATS source distribution across the 149: greenhouse 34, workday 30, ashby 20, icims 9,
smartrecruiters 8, oraclecloud 7, teamtailor 7, workable 7, remainder spread thin.

## The actor input

`data/apify_input.json`, reproduced here in summary:

- `titleSearch`: Enterprise Account Executive, Strategic Account:*, Major Account:*,
  Global Account:*, Named Account:*, Account Director, Account Executive
- `titleExclusionSearch`: SDR, BDR, Business Development Representative, Sales Development,
  Intern, Graduate, VP, Vice President
- `locationSearch`: London England United Kingdom; United Kingdom
- `aiExperienceLevelFilter`: 5-10, 10+
- `liIndustryExclusionFilter`: 36 industries (agencies, recruiting, retail, manufacturing,
  healthcare, education, government, financial services, IT consulting, and others)
- `limit`: 100
- `timeRange`: 24h
- `includeCompanyDetails`: true

The `:*` suffix in `titleSearch` is Postgres full-text prefix-match syntax, which is a strong
hint about what the underlying API is doing with these strings.
