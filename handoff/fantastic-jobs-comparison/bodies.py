#!/usr/bin/env python3
"""Build Notion page bodies for each prepared intake row."""
import json, re, sys
sys.path.insert(0,".")
import pipeline as P   # reuses parsing/scoring; pipeline prints its report to stdout

_SPECIAL = "\\*~`$[]<>{}|^"
def esc(t):
    """Escape Notion-flavored Markdown control characters so feed text renders verbatim."""
    out=[]
    for line in (t or "").splitlines():
        s=""
        for ch in line.rstrip():
            s += ("\\"+ch) if ch in _SPECIAL else ch
        s = re.sub(r"^(\s*)(#{1,6})(\s)", r"\1\\\2\3", s)   # don't hijack as a heading
        out.append(s)
    return "\n".join(out)

def cell(t):
    """Escape for a table cell: same rules, newlines flattened."""
    return esc(" ".join((t or "").split()))

def one_liner(r):
    resp = r.get("ai_core_responsibilities") or ""
    if isinstance(resp, list): resp = " ".join(map(str,resp))
    s = re.split(r"(?<=[.!?])\s+", resp.strip())
    return " ".join(s[:1]) if s else ""

def org_line(r):
    bits=[]
    if r.get("org_linkedin_industry"): bits.append(r["org_linkedin_industry"])
    if r.get("org_linkedin_headcount"): bits.append(f"{r['org_linkedin_headcount']} employees")
    if r.get("org_linkedin_headquarters"): bits.append(f"HQ {r['org_linkedin_headquarters']}")
    if r.get("org_linkedin_founded_date"): bits.append(f"founded {str(r['org_linkedin_founded_date'])[:4]}")
    nm = esc(r.get("organization","")); return (f"**{nm}** — " + esc(", ".join(map(str,bits)))) if bits else f"**{nm}**"

def assessment(p):
    d=p["dims"]; raw=p["raw"]
    L=[]
    L.append("## Assessment")
    L.append("")
    if p["Hard Fail Reason"] != "None":
        L.append(f"**Machine verdict: Noise — hard fail: {p['Hard Fail Reason']}.** "
                 f"Rubric {P.RUBRIC} scoring was skipped, per the hard-fail-first rule. "
                 f"Flagged rather than dropped because this row is on the watchlist.")
        L.append("")
        L.append(f"- Trigger evidence: \"{cell(p['hard_fail_evidence'])[:300]}\"")
        L.append(f"- Title: \"{cell(p['Role'])}\"")
        L.append(f"- Org industry: {cell(p['Org Industry']) or 'n/a'}")
        L.append("")
        L.append(f"**Recommended next action:** confirm the hard fail by eye — a watchlist company "
                 f"is worth a manual look before the rule is trusted. If wrong, set Human Verdict and "
                 f"the disagreement will surface in the Disagreements view.")
        return "\n".join(L)

    L.append(f"**Machine verdict: {p['Machine Verdict']} — Fit Score {p['Fit Score']}/100 (rubric {P.RUBRIC}).**")
    L.append("")
    ranked = sorted(d.items(), key=lambda kv: -(kv[1][0]/kv[1][1]))
    for dim,(pt,mx,ev) in ranked[:2]:
        if ev: L.append(f"- **{cell(dim)} — {pt}/{mx}.** \"{cell(ev)[:280]}\"")
    for dim,(pt,mx,ev) in ranked[-2:]:
        if ev: L.append(f"- **{cell(dim)} — {pt}/{mx} (weakest).** \"{cell(ev)[:280]}\"")
    L.append("")
    L.append(f"_Six dimensions totalling 95 points, rescaled to {p['Fit Score']}/100. "
             f"Comp is not scored in {P.RUBRIC}; disclosed salary: "
             f"{esc(p['Salary']) or 'none'}._")
    L.append("")
    L.append('<table fit-page-width="true" header-row="true">')
    L.append("\t<tr>\n\t\t<td>Dimension</td>\n\t\t<td>Score</td>\n\t\t<td>JD evidence</td>\n\t</tr>")
    for dim,(pt,mx,ev) in d.items():
        L.append(f"\t<tr>\n\t\t<td>{cell(dim)}</td>\n\t\t<td>{pt}/{mx}</td>\n\t\t<td>{cell(ev)[:220]}</td>\n\t</tr>")
    L.append("</table>")
    L.append("")
    if p["Machine Verdict"]=="Strong":
        act = ("Enrich and apply. Promote to the Roles DB, research the hiring manager, "
               "then tailor the CV against the requirements summary above.")
    elif p["Watchlist"]:
        act = ("Watchlist company below the Strong bar — keep warm. Worth a networking approach "
               "even though the role itself scores Partial.")
    else:
        act = "Hold for human review; re-check if a stronger role at the same company appears."
    L.append(f"**Recommended next action:** {act}")
    return "\n".join(L)

def build(p):
    r=p["raw"]
    L=[]
    L.append("## Snapshot")
    L.append("")
    ol=one_liner(r)
    L.append(esc(ol) if ol else f"{cell(p['Role'])} at {cell(p['Company'])}.")
    L.append("")
    L.append(org_line(r))
    L.append("")
    req = r.get("ai_requirements_summary") or ""
    if isinstance(req, list): req=" ".join(map(str,req))
    L.append("## Requirements")
    L.append("")
    L.append(esc(req) if req else "_No requirements summary supplied by the feed._")
    L.append("")
    if p.get("roles_url"):
        L.append("## Cross-DB match")
        L.append("")
        L.append(f"Matches an existing Roles entry on dedup key `{p['Dedup Key']}` — "
                 f"[{p['roles_title']}]({p['roles_url']}). Intake Status set to Promoted. "
                 f"The Roles record was not modified.")
        L.append("")
    if p["Fit Score"] >= 70 or p["Watchlist"]:
        L.append(assessment(p)); L.append("")
    L.append("## Full JD")
    L.append("")
    L.append(esc(r.get("description_text") or ""))
    return "\n".join(L)

prepared = P.prepared
for p in prepared:
    p["body"] = build(p)

json.dump([{k:v for k,v in p.items() if k not in ("raw","dims")} for p in prepared],
          open("towrite.json","w"), indent=1, default=str)

n_assess=sum(1 for p in prepared if p["Fit Score"]>=70 or p["Watchlist"])
sizes=sorted(len(p["body"]) for p in prepared)
print(f"bodies built: {len(prepared)}  with ## Assessment: {n_assess}")
print(f"body chars  : min {sizes[0]} median {sizes[len(sizes)//2]} max {sizes[-1]}")
