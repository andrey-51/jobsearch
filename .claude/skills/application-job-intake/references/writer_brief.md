# Connector writer brief (for writer subagents)

Use this only when the Notion REST token fails and pages go through the Notion connector.

You are given: the skill's `scripts/intake.py` path, a work directory, a run id, a row range and a log file.

For each row index i in your range:
1. Run `python3 <intake.py> --dir <work dir> show <run> i i+1`. It prints a properties JSON, then the page body
   between `--------------- BODY ---------------` and `--------------- ENDBODY ---------------`.
2. Call `mcp__Notion__notion-create-pages` (load with ToolSearch "select:mcp__Notion__notion-create-pages") with:
   - parent: {"type": "data_source_id", "data_source_id": "441379e4-d36a-4d53-b834-57242e0dafb3"}
   - allow_async: false
   - pages: [ { "properties": <the printed JSON exactly>, "content": <the body exactly> } ]
   One page per call. The body is long; copy it exactly. The most reliable way is to dump the body as a JSON
   string with a one-line Python command and pass that, rather than retyping it, because bodies contain
   non-breaking spaces, escaped `\$` `\*` `\|` and runs of blank lines.
3. Append `i|<Source Job ID>|<page url>` to your log file.

Rules:
- Create pages only in data source 441379e4-d36a-4d53-b834-57242e0dafb3 (Role Intake). Never write to any other
  database or page and never update or delete a page.
- If a create call errors or times out, check before retrying whether the page already exists:
  `mcp__Notion__notion-query-data-sources` with data_source_urls ["collection://441379e4-d36a-4d53-b834-57242e0dafb3"]
  and `SELECT url FROM "collection://441379e4-d36a-4d53-b834-57242e0dafb3" WHERE "Source Job ID" = ?` with params [sid].
  Retry only if no row comes back; a blind retry creates a duplicate page.
- Do not print or use any tokens or environment variables.

Final reply: pages created, any failures, and any body you could not copy exactly.
