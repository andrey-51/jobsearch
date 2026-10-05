---
name: application-job-intake
description: Run an Apify Fantastic Jobs run (actor s3dtSTZSZWFtAVLn5) into Andrey's Notion Role Intake database. Fetch the run, score it with the v1.1 rubric, dedupe against live and deleted rows, dry-run for approval, ATS-screen every new row against the CV, then write the pages with Triage filled in and verify. Use whenever Andrey gives an Apify run id or dataset, says "add run X", "intake this run", "load the batch", "write roles from runID", "/application-job-intake" followed by a run id, asks to backfill or consolidate a run into Role Intake, or asks to triage or re-screen Role Intake rows whose Triage is empty. Never writes to Roles, Outreach or Companies; for moving Reviewed intake rows into Roles use application-role-intake instead.
---

# Apify run to Role Intake

This skill turns one Apify run into screened Role Intake rows. It writes only to Role Intake. It never applies to anything.
Promoting rows into the Roles tracker is a different skill (application-role-intake), and nothing here touches Roles.

## Where things live

| Item | Location |
|---|---|
| Role Intake data source (the only write target) | `collection://441379e4-d36a-4d53-b834-57242e0dafb3` |
| Roles (read-only, never write) | `collection://29ca5e5b-5444-4136-ae62-7af42e552cbf` |
| Apify actor | Fantastic Jobs `s3dtSTZSZWFtAVLn5`, pay per event (about $0.012 per job plus $0.01 start) |
| Helper | `scripts/intake.py` (fetch, prepare, live-sql, dedup, batches, final, show, verify, ledger-add) |
| Scoring and page bodies | `scripts/pipeline.py` (rubric v1.1), `scripts/bodies.py` |
| Direct REST writer | `scripts/nwrite.py` (needs a working `Notion_KEY`) |
| Write ledger | `data/ledger.csv`: every job id ever written. It is the only record of rows Andrey deleted, so commit it after every run |
| Roles cross-check | `data/roles.tsv` (Company, Role, URL), a snapshot of Roles used to mark Cross-DB matches |
| Screen brief | `references/screen_brief.md` |
| Connector writer brief | `references/writer_brief.md` |

## Ground rules

These come from Andrey's standing instructions and from mistakes in earlier runs.

- **Dry run first, then wait.** Fetch, score and dedupe, report, and write nothing until Andrey approves the write.
  The approval covers that batch only.
- **Role Intake only.** Never create or modify anything in Roles, Outreach or Companies, even when a row matches one.
- **Secrets.** `APIFY_TOKEN` and `Notion_KEY` come from the environment. Never print them or write them into a file, page,
  log, commit or URL shown to the user. Use a generic User-Agent; never put Andrey's name or email in a header.
- **Respect deletions.** A job Andrey deleted from Role Intake stays deleted: neither the same posting nor the same role
  (same dedup key) comes back. The ledger is how deletions are detected (ledger rows that are no longer live).
- **No duplicates.** Andrey's rule since 2026-10-04: skip any row whose posting or dedup key is already live, and in-batch
  duplicates. Report what was skipped; do not write it with a Duplicate flag.
- **No Assessment section.** Pages carry Snapshot, Requirements and Full JD only (Assessments were removed on 2026-09-28).
- **Check the schema before writing.** Fetch the data source and drop any property it no longer has. Machine Verdict and
  Rubric Version were removed on 2026-10-04; `intake.py show` and `nwrite.py` already leave them out. If a new property
  appears, leave it empty.
- **Keep Andrey's fields alone.** Human Verdict and Noise Reason are his. Never set or change them.

## Procedure

Use a work directory outside the repo (the session scratchpad, or `./intake_work`) and pass it as `--dir` every time.
Below, `I` means `python3 <skill>/scripts/intake.py --dir <work dir>`.

### 1. Fetch and score

```
I fetch <run>
I prepare <run> --date <today YYYY-MM-DD>
```

`fetch` prints status, cost, the date_created spread and the actor input. Note the timeRange and the number of
excluded industries. `prepare` prints machine verdicts and hard fails. It lists every "Management track" and
"Wrong location/US leak" hard fail with its evidence line. Read those: the rules misfire on phrases like "team of
Account Executives", "headquartered in California" or US salary bands inside UK postings. A misfired row scores 0,
but the ATS screen still judges it properly.

### 2. Dedupe against Notion

```
I live-sql <run>
```

This prints read-only queries: query 1 with job ids inline, then one or more key queries with a PARAMS line.
Run each through `mcp__Notion__notion-query-data-sources` with data_source_urls
`["collection://441379e4-d36a-4d53-b834-57242e0dafb3"]`. Pass the PARAMS list as `params`. Do not inline the keys:
they contain quotes, dashes and pipes that break the call. Paste each returned `live` string as its own line into
`<work dir>/live_<run>.txt`, then:

```
I dedup <run> --live <work dir>/live_<run>.txt
```

The output groups rows as new, same role as a live row, same role as a deleted row, posting already live, posting
deleted by user and in-batch duplicate. Only "new" rows go forward.

### 3. Dry-run report, then stop

Report in a short table: run size and cost, the dedup split, the skipped matches by company, the top machine-Strong
new rows, hard-fail misfires spotted in step 1, and anything odd (very old Posted dates, schema changes, a dead token).
Ask whether to write and screen. Wait for the answer.

### 4. ATS screen (after approval)

```
I batches <run> --size 26
```

Copy the CV text to `<work dir>/cv.txt`. The source is the CV Andrey attached or the project knowledge; ask if neither is
available. Then spawn one subagent per batch in parallel (about 25 to 50 rows each). Give each the paths to
`references/screen_brief.md`, `cv.txt`, its batch file, and its output file `screen/verdicts_<run>_<n>.txt`.
Without subagents, screen the batches yourself in order.

When the verdicts are back, check them before trusting them:
- Read every Pursue reason and every reason that cites a figure or employer. Confirm each claim against `cv.txt` and fix
  any that are invented. Earlier runs invented "KPMG co-sell" and "NRR 110 to 120 percent".
- For every Skip whose reason is a language, and every Pursue with a language flag, read the language sentence in the
  full JD (`run_<run>.json`). "Advantage" or "not a requirement" means it is not a gap.

Then merge:

```
I final <run>
```

This fails if any row lacks a verdict, and warns when a score falls outside its verdict's band.

### 5. Write

Test the token first: GET `https://api.notion.com/v1/data_sources/441379e4-d36a-4d53-b834-57242e0dafb3` with `Notion_KEY`.

- **Token works (fast path).** Write the rows with
  `cd <work dir> && python3 <skill>/scripts/nwrite.py final_<run>.json wrote_<run>.txt 0 <n>`.
  For large batches, run four ranges in parallel. The log makes it resumable. If a write fails after the page was
  created (partial_page in the output), archive that page rather than retrying blindly.
- **Token fails (401 since 2026-09-28, connector path).** Split the rows into ranges of about 12 and spawn one writer
  subagent per range, briefed with `references/writer_brief.md`, the intake.py path, the work dir, the run id, the range
  and a log file. Writers copy bodies with a JSON dump, not by retyping.

### 6. Verify

Query the result through the connector:

```sql
SELECT (SELECT count(*) FROM "collection://441379e4-d36a-4d53-b834-57242e0dafb3") AS total,
       (SELECT count(*) FROM (SELECT "Source Job ID" FROM "collection://441379e4-d36a-4d53-b834-57242e0dafb3"
         WHERE "Source Job ID" IS NOT NULL GROUP BY "Source Job ID" HAVING count(*)>1)) AS dup_sids,
       (SELECT group_concat("Source Job ID" || ':' || coalesce("Triage",'') || ':' || coalesce("ATS Score",''), '|')
         FROM "collection://441379e4-d36a-4d53-b834-57242e0dafb3" WHERE "date:Fetched:start" = '<today>') AS new_rows
```

Save `new_rows` to `<work dir>/got_<run>.txt` and run `I verify <run> --got <work dir>/got_<run>.txt`.
Expect `total` to equal the previous count plus the rows written, and `dup_sids` = 0. Fetch one written page and check it
has no Assessment section and its body is intact.

### 7. Record and report

```
I ledger-add <run>
```

Commit `data/ledger.csv`, so the next session can still tell which rows Andrey deleted. Then report:

| Section | Content |
|---|---|
| Result | Rows written, new database total, verification outcome |
| Weakest point first | Misfired hard fails among Pursue rows; screen reasons corrected; anything not verified |
| Screen split | Pursue / Borderline / Skip counts |
| Pursue table | Role, company, ATS score, machine Fit Score (mark 0s caused by misfires) |
| Skip themes | Required languages, public sector, junior seats, agencies and so on |
| Housekeeping | Token state, schema changes, empty rows noticed |

## Other jobs this skill covers

- **Re-screen rows with empty Triage.** Query `WHERE "Triage" IS NULL` for the job id, Human Verdict and page url. Build
  batches from the stored run files: `batches` needs `towrite_<run>.json`, so write a small list for those ids. Screen them,
  then set only Triage, ATS Score and Triage Reason with `mcp__Notion__notion-update-page` (command
  `update_properties`). Rows Andrey has already labelled double as a blind accuracy check: report screen versus Human
  Verdict as a small confusion table.
- **Backfill runs** (timeRange 6m): same steps. `timeRange` filters on date_created, not date_posted, so old postings
  come back. Keep them; Andrey filters later.
- **Refresh `data/roles.tsv`** when Roles has changed a lot: read Company, Role Title and the page url from Roles with a SQL
  query (read-only) and rewrite the file. It only drives the Cross-DB match note on pages.

## Known issues (as of 2026-10-05)

- `pipeline.py` hard-fail rules: "Management track" fires on body text such as "team of Account Executives" and "people
  management skills". "Wrong location/US leak" fires on US headquarters lines, US legal boilerplate and US salary bands in
  UK postings. In the last two runs this put four Pursue rows at Fit Score 0. A fix (title-only management check; ignore
  boilerplate and roles with a UK location) has been proposed and is not applied yet. Until then, rank by Triage, not
  Fit Score.
- The machine scorer reads "insurance" in benefits text as an FSI signal.
- Connector writes can normalise long dashed lines and non-breaking spaces in job text. This is cosmetic.
- The screen's main blind spot: Andrey sometimes rates AI and data companies Strong even when they ask for a vertical he
  hasn't sold into. On the Partial pool, two of three such roles were screened Skip. Mention Skip rows from those companies
  rather than burying them.
