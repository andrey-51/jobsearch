# Direct API findings — 2026-09-20

Partial run against `https://data.fantastic.jobs/v1/active-ats`. Four things settled, the
overlap comparison itself not completed. Quota exhausted mid-run (see the last section).

## 1. The Apify actor is first-party, not a third-party wrapper

Settled. From `GET https://api.apify.com/v2/acts/s3dtSTZSZWFtAVLn5`:

- Apify username: **`fantastic-jobs`**
- Actor name: `career-site-job-listing-api`
- Description ends: *"Powered by Fantastic.jobs"*

Same vendor, same corpus, two distribution channels. The study is about channel differences,
not coverage differences. No job exists on one side that the other has never heard of.

## 2. Auth and endpoint

- Host `data.fantastic.jobs` is reachable. `active-jobs-db.p.rapidapi.com` and `apify.com`
  are blocked by this environment's egress policy.
- `Authorization: Bearer <key>`. `x-api-key` and bare-token schemes are rejected.
- `/v1/active-ats` is the only endpoint found. These all 404: `active-ats-full`,
  `-pro`, `-premium`, `-expired`, `-meta`, `-enriched`, `/v1/jobs`, `/v1/organizations`,
  `/v1/usage`, `/v1/account`, `/v1/me`, `/v1/plan`. No OpenAPI spec is served.

## 3. The direct response is missing the fields the rubric depends on

**52 fields vs the Apify actor's 71.** Absent from every direct response:

```
description_text                      <- the entire JD
org_linkedin_industry                 <- the 36-industry exclusion depends on this
org_linkedin_headcount                <- Company quality dimension
org_linkedin_followers                <- Company quality dimension
org_linkedin_name / _size / _type / _website / _description / _slogan /
  _specialties / _locations / _headquarters / _founded_date / _id /
  _recruitment_agency_derived
org_crunchbase_categories / _total_investment
org_logo_permalink
```

No parameter turns them on. All of these were rejected as unknown query parameters:
`include_company_details`, `company_details`, `include_org`, `include_ai`, `include_linkedin`,
`description_type`, `include_description`, `with_description`, `full_description`, `fields`,
`expand`.

The Apify actor exposes these as `includeCompanyDetails` and `descriptionType`, and they work
there. Either they are gated to a higher plan tier on the REST API, or the REST tier in use
does not carry them at all. **Determine which before concluding the REST API cannot do this.**

Consequence as things stand: the direct API cannot reproduce Andrey's search. The 36-industry
exclusion cannot be applied server-side or client-side, because the industry field is not
returned. `pipeline.py` also cannot score a direct-API pull, since scoring reads
`description_text`, `org_linkedin_headcount` and `org_linkedin_followers`.

## 4. Parameter surface

Accepted on `/v1/active-ats` (14): `time_frame`, `limit`, `offset`, `id`, `title`, `location`,
`description`, `organization`, `domain`, `date_posted_gte`, `has_salary`, `ai_language`,
`ai_work_arrangement`, `ai_experience_level`.

`time_frame` is required, one of `1h`, `24h`, `7d`, `6m`. `limit` caps at 1000 per page.
The API returns "Did you mean" suggestions for near-miss names, which is the cheapest way to
discover the rest.

**No exclusion parameters exist.** No `title_exclude`, no `location_exclusion`, no
`li_industry_filter`, no `remove_agency`, no `ats` filter. The Apify actor has all of these
(`titleExclusionSearch`, `locationExclusionSearch`, `liIndustryExclusionFilter`, `removeAgency`,
`atsExclusionFilter`, plus `organizationSearch`, `domainFilter`, `aiTaxonomiesFilter`,
`liOrganizationEmployeesGte/Lte`, `liOrganizationSizeFilter` — 38 params in total, retrieved
from `GET /v2/actor-builds/mt08IK4O8mwAQ77GI`).

## 5. Repeated parameters AND together, they do not OR

Measured on `time_frame=7d&location=United Kingdom`:

| title params | rows |
|---|---|
| 1 (`Account Executive`) | 148 |
| 2 (`Account Executive`, `Account Director`) | 148 |
| 7 (Andrey's full list) | 25 |

Passing the seven title patterns as repeated params narrowed the result to 25 rather than
unioning them. **Any comparison built on repeated params is invalid.** The OR syntax was not
established before quota ran out; `title=A OR B` returns 200 but the semantics were not
verified against a known-answer set.

## 6. Job IDs match exactly across both channels

Confirmed. 19 of the 25 rows from the (invalid) AND query matched Apify baseline IDs exactly,
e.g. `2371345520` Planview, `2371358876`/`2371358879` Intapp, `2368664691` AlphaSense.
**Join on `id`, no fallback needed.**

Six rows in that set were not in the Apify baseline: Lumivero, Gartner (Conference Sales),
Sama, Aon Corporation, Okta (Auth0), Harmoney. Two of those (Gartner, Aon) are in industries
Andrey excludes, which is consistent with the direct API having no industry exclusion. This is
suggestive only — the query was invalid, so treat it as a hint about where differences will
show up, not as a result.

## 7. Quota model, and how it got exhausted

**The meter counts jobs returned, not API calls:**

```
403 — "API Key has exceeded the allowed limit for \"jobs\" meter."
```

No `X-RateLimit-*` or quota headers are returned, so there is no warning before the wall.

Five diagnostic calls issued with `limit=1000` to measure result-set sizes consumed roughly
5,000 jobs and exhausted the allowance. That was a methodology error: the count of rows is what
those calls were measuring, so a large limit was the only way to get the number, but the plan's
meter should have been checked first and the sizing done against a cheaper signal.

**Before resuming:** find out the plan's job allowance and reset period, and budget the pull.
The real comparison needs roughly one full pass over the window, so size that against the
remaining allowance rather than probing.
