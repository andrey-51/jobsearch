# The Fantastic Jobs side

## Credential gap — read this first

**There is no Fantastic Jobs / RapidAPI credential in this environment.** The only tokens
present are `APIFY_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN` and Claude/gcloud internals.

Fantastic Jobs' "Active Jobs DB" is distributed through RapidAPI and needs an
`X-RapidAPI-Key`. Get it from Andrey as `RAPIDAPI_KEY` before doing anything else.

If he is on a **free RapidAPI tier**, results may be capped or fields stripped. That would
confound the comparison. Say so explicitly in the report rather than treating truncated
results as evidence of narrower coverage.

## The wrapper hypothesis

**The Apify actor is almost certainly Fantastic Jobs itself.** Evidence:

1. Every record in the captured runs carries the Active Jobs DB schema: `ai_experience_level`,
   `ai_work_arrangement`, `ai_requirements_summary`, `ai_key_skills`, `org_linkedin_headcount`,
   `org_linkedin_industry`, `org_linkedin_followers`, `locations_derived`, `regions_derived`,
   `countries_derived`, `source_type`.
2. The Apify input field names are camelCase restatements of that API's query parameters:
   `liIndustryExclusionFilter`, `aiExperienceLevelFilter`, `aiVisaSponsorshipFilter`,
   `populateAiRemoteLocationDerived`.
3. `titleSearch` accepts `:*` prefix wildcards, which is Postgres full-text search syntax
   passed through rather than reimplemented.

**If this holds**, the study is not comparing two job corpora. It is comparing a wrapper
against the thing it wraps, and any difference will come from parameter translation, result
limits, pagination, or dedup inside the actor. That is still worth knowing, and it changes
what the report should be about.

Verify by checking the actor's Apify store listing and the Fantastic Jobs RapidAPI docs. Tell
Andrey which case you are in **before** writing comparison code.

## Parameter mapping — a hypothesis, not a spec

**Do not trust this table.** It was written without access to the live documentation. Read the
RapidAPI docs and correct it. It exists to save you a first pass.

| Apify input | Likely direct-API equivalent | What to verify |
|---|---|---|
| `titleSearch` (array, `:*` wildcards) | `title_filter` — may need a single OR-joined string with quoted phrases | how arrays are joined; whether `:*` passes through |
| `titleExclusionSearch` | `title_exclude_filter`, or a `NOT` clause inside `title_filter` | whether a separate parameter exists at all |
| `locationSearch` | `location_filter` | array vs OR-joined string |
| `aiExperienceLevelFilter: ["5-10","10+"]` | `ai_experience_level_filter` | exact value spellings |
| `liIndustryExclusionFilter` (37 industries) | `li_industry_filter` with negation, or `organization_exclude` | **most likely to differ** |
| `timeRange: "24h"` | `date_filter` / a `date_created` lower bound, ISO 8601 | which date field it binds to |
| `includeCompanyDetails: true` | `include_ai` / `description_type` / an org-enrichment flag | whether `org_linkedin_*` needs a higher tier |
| `limit: 100` | `limit` + `offset` | max page size; offset vs cursor pagination |
| `removeAgency: false` | `org_linkedin_recruitment_agency_derived` filter | — |

**The industry exclusion list is the single most likely source of a spurious difference.**
If you cannot reproduce it server-side, filter both sides client-side on
`org_linkedin_industry` and state that you did.

## Query window

Use **`date_created` from 2026-09-10 to 2026-09-19 inclusive** (10 days). This is the real
span of Apify coverage, not the nominal 24h. See `memory/anomalies.md` for why.

Paginate to exhaustion. Do not stop at 100 — the Apify side was capped at 100 and that cap is
itself one of the things under test.

## Joining to the baseline

Join on the job `id`. Fantastic Jobs IDs should match the Apify records exactly since the
records carry the same `id` field. **Confirm this on a few known rows before relying on it.**
Fallback order: `url`, then normalised `organization` + `title`.
