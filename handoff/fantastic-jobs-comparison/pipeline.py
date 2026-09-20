#!/usr/bin/env python3
"""Role Intake backfill: parse -> dedup -> score. Rubric v1.0."""
import json, re, sys, os, collections, datetime

RUBRIC = "v1.1"
TODAY = os.environ.get("INTAKE_DATE", "2026-09-17")
SRC = sys.argv[1] if len(sys.argv) > 1 else "run_EHR.json"

rows = json.load(open(SRC))

# ---------------------------------------------------------------- normalize
SUFFIXES = ["inc","ltd","limited","llc","gmbh","bv","plc","group","holdings",
            "corp","corporation","co","sa","ag","nv","ab","oy","as","srl","spa","pty"]

def norm_company(s):
    s = (s or "").lower()
    s = s.replace("&"," and ")
    s = re.sub(r"[^\w\s]", " ", s)          # strip punctuation (b.v. -> b v)
    toks = [t for t in s.split() if t]
    # strip suffix tokens from the tail, repeatedly
    while toks and toks[-1] in SUFFIXES:
        toks.pop()
    return " ".join(toks)

def norm_title(s):
    s = (s or "").lower()
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def dedup_key(company, title):
    return f"{norm_company(company)}|{norm_title(title)}"

# ---------------------------------------------------------------- field map
WORK_MODE = {"Remote OK":"Remote","Remote Solely":"Remote","Hybrid":"Hybrid","On-site":"On-site"}
EXP_OK = {"0-2","2-5","5-10","10+"}

def loc_string(r):
    locs = r.get("locations_derived") or []
    if isinstance(locs, str): locs = [locs]
    return "; ".join(dict.fromkeys(x for x in locs if x))

def _money(cur, lo, hi, one, unit):
    def _z(v):
        # A zero-valued MonetaryAmount is an ATS placeholder, not a disclosed salary.
        try: return None if float(v) == 0 else v
        except (TypeError, ValueError): return v
    lo, hi, one = _z(lo), _z(hi), _z(one)
    sym = {"GBP":"\u00a3","USD":"$","EUR":"\u20ac"}.get((cur or "").upper(), ((cur+" ") if cur else ""))
    def fmt(v):
        try: return f"{int(float(v)):,}"
        except Exception: return str(v)
    if lo is not None and hi is not None and str(lo) != str(hi): s = f"{sym}{fmt(lo)}-{fmt(hi)}"
    elif one is not None:                                        s = f"{sym}{fmt(one)}"
    elif lo is not None:                                         s = f"{sym}{fmt(lo)}+"
    elif hi is not None:                                         s = f"up to {sym}{fmt(hi)}"
    else: return ""
    return (s + (f" / {unit.lower()}" if unit else "")).strip()

def _from_jsonld(sal):
    """Unwrap a schema.org MonetaryAmount dict (possibly nested in a list)."""
    if isinstance(sal, list):
        for x in sal:
            got = _from_jsonld(x)
            if got: return got
        return ""
    if not isinstance(sal, dict): return ""
    cur = sal.get("currency") or sal.get("salaryCurrency") or ""
    v = sal.get("value", sal)
    if isinstance(v, list): v = v[0] if v else {}
    if not isinstance(v, dict): v = {}
    return _money(cur, v.get("minValue"), v.get("maxValue"),
                  v.get("value"), v.get("unitText") or sal.get("unitText") or "")

def salary_string(r):
    sal = r.get("salary")
    if isinstance(sal, (dict, list)):
        got = _from_jsonld(sal)
        if got: return got
    elif sal:
        return str(sal).strip()
    return _money(r.get("ai_salary_currency"), r.get("ai_salary_min_value"),
                  r.get("ai_salary_max_value"), r.get("ai_salary_value"),
                  r.get("ai_salary_unit_text") or "")

def gbp_base(r):
    """Best-guess annual GBP base from the ai_salary_* fields; None if unknown."""
    cur = (r.get("ai_salary_currency") or "").upper()
    unit = (r.get("ai_salary_unit_text") or "").upper()
    vals = [v for v in (r.get("ai_salary_min_value"), r.get("ai_salary_value")) if v is not None]
    if not vals: return None
    try: v = float(vals[0])
    except Exception: return None
    if unit and "YEAR" not in unit: return None
    if cur == "GBP": return v
    if cur == "USD": return v * 0.78
    if cur == "EUR": return v * 0.85
    return None

# ---------------------------------------------------------------- text blobs
def blobs(r):
    desc = (r.get("description_text") or "")
    resp = (r.get("ai_core_responsibilities") or "")
    req  = (r.get("ai_requirements_summary") or "")
    if isinstance(resp, list): resp = " ".join(map(str, resp))
    if isinstance(req, list):  req  = " ".join(map(str, req))
    return desc, resp, req

_RX={}
def has(text, phrase):
    """Word-boundary containment: 'ad sales' must not match 'lead sales campaigns'."""
    rx=_RX.get(phrase)
    if rx is None:
        rx=_RX[phrase]=re.compile(r"(?<![\w])"+re.escape(phrase).replace(r"\ ",r"\s+")+r"(?![\w])")
    return bool(rx.search(text))

def any_has(text, words):
    return any(has(text,w) for w in words)

def sent_with(text, *needles):
    """Return the first sentence in text containing any needle (for evidence quotes)."""
    for s in re.split(r"(?<=[.!?])\s+|\n+", text):
        low = s.lower()
        if any(has(low,n) for n in needles) and 25 < len(s) < 320:
            return " ".join(s.split())
    return ""

# ---------------------------------------------------------------- hard fails
INSURANCE_BROKERS = ["wtw","willis towers watson","aon","marsh","gallagher","ajg","howden",
                     "lockton","brown and brown","alliant","nfp","ardonagh","pib","jensten"]
AGENCY_ORGS = ["wpp","publicis","omnicom","dentsu","havas","interpublic","ipg mediabrands",
               "wpp media","groupm","mediacom","mission group","ogilvy","vmly","wunderman"]
AGENCY_WORDS = ["advertising agency","media agency","pr agency","public relations",
                "creative agency","marketing agency","integrated agency","brand agency"]
AD_SALES = ["ad sales","advertising sales","media sales","sell advertising","ad revenue",
            "programmatic advertising","sponsorship sales","ad inventory"]
STAFFING_WORDS = ["recruitment","staffing","staffing and recruiting","talent acquisition firm",
                  "executive search","recruiting agency","headhunt"]
JUNIOR_WORDS = ["junior","intern","graduate","entry level","trainee","apprentice","placement"]
MGMT_WORDS = ["manage a team of","lead a team of","direct reports","people management",
              "hire and develop","manage the team","manage and mentor","managing and mentoring",
              "coach and develop the team","build and lead a team","managing a team",
              "leading a team of","team of account executives","your team of",
              "manage a team","lead and develop a team","people leadership",
              "coach and manage the team","line manage","performance manage"]
MGMT_TITLES = ["engineering manager","solution engineering manager","solutions engineering manager",
               "head of sales","sales team leader","team leader","team lead","people manager"]
FTC_WORDS = ["fixed term","fixed-term","ftc","maternity cover","parental cover",
             "12 month contract","12-month contract","6 month contract","6-month contract",
             "maternity leave cover","secondment"]
US_STATES = ["alabama","alaska","arizona","arkansas","california","colorado","connecticut",
 "delaware","florida","georgia","hawaii","idaho","illinois","indiana","iowa","kansas",
 "kentucky","louisiana","maine","maryland","massachusetts","michigan","minnesota",
 "mississippi","missouri","montana","nebraska","nevada","new hampshire","new jersey",
 "new mexico","new york","north carolina","north dakota","ohio","oklahoma","oregon",
 "pennsylvania","rhode island","south carolina","south dakota","tennessee","texas","utah",
 "vermont","virginia","washington","west virginia","wisconsin","wyoming",
 "united states","u.s.","usa","401(k)","401k"]

def hard_fail(r):
    title = (r.get("title") or "")
    tl = title.lower()
    org = (r.get("organization") or "")
    ol = org.lower()
    ind = (r.get("org_linkedin_industry") or "")
    il = ind.lower()
    desc, resp, req = blobs(r)
    dl, rl = desc.lower(), resp.lower()
    orgdesc = (r.get("org_linkedin_description") or "").lower()
    locs = r.get("locations_derived") or []

    # 1. insurance broking
    if ("insurance" in il and any(w in (ol+" "+orgdesc) for w in ["brok","broking"])) \
       or any(b == norm_company(org) or b in ol.split() or ol.startswith(b) for b in INSURANCE_BROKERS) \
       or "insurance brokers" in il:
        return "Insurance broker", sent_with(desc,"insurance","broking","broker") or ind
    # 2. agency / PR / media
    if any(w in il for w in ["advertising services","public relations","marketing services"]) \
       or any_has(orgdesc, AGENCY_WORDS) or any(a in ol for a in AGENCY_ORGS):
        return "Agency/PR", sent_with(orgdesc or desc, *AGENCY_WORDS) or ind
    # 3. ad sales role
    if any_has(tl, ["ad sales","advertising sales","media sales"]) or any_has(dl, AD_SALES):
        return "Ad sales", sent_with(desc, *AD_SALES) or title
    # 4. staffing / recruiting poster
    if r.get("org_linkedin_recruitment_agency_derived") is True \
       or "staffing and recruiting" in il \
       or any(w in ol for w in ["recruitment","recruiting","staffing","talent partners"]):
        return "Staffing poster", f"industry={ind}; recruitment_agency_derived={r.get('org_linkedin_recruitment_agency_derived')}"
    # 5. too junior by title
    if any(re.search(rf"\b{w}\b", tl) for w in JUNIOR_WORDS):
        return "Too junior", title
    # 6. people-management scope in responsibilities
    if any_has(tl, MGMT_TITLES):
        return "Management track", f"title indicates people-management scope: '{title}'"
    if any_has(rl, MGMT_WORDS) or any_has(dl, MGMT_WORDS):
        return "Management track", sent_with(resp + " " + desc, *MGMT_WORDS)
    # 7. FTC / fixed-term / maternity cover
    emp = r.get("ai_employment_type") or ""
    if isinstance(emp, list): emp = " ".join(map(str, emp))
    if any_has(dl, FTC_WORDS) or emp.upper() in ("CONTRACTOR","TEMPORARY"):
        return "FTC/contract", sent_with(desc, *FTC_WORDS) or emp
    # 8. US-role location leak
    bare_uk = bool(locs) and all((x or "").strip().lower() == "united kingdom" for x in locs)
    if bare_uk and any(re.search(rf"\b{re.escape(w)}\b", dl) for w in US_STATES):
        hit = next(w for w in US_STATES if re.search(rf"\b{re.escape(w)}\b", dl))
        return "Wrong location/US leak", sent_with(desc, hit) or f"US reference: {hit}"
    return None, ""

# ---------------------------------------------------------------- rubric v1.0
CLOSING_TITLES = ["account executive","account director","account manager","client director",
                  "client partner","sales director","sales executive","enterprise sales",
                  "strategic sales","business development director","global account",
                  "named account","sales specialist","commercial director","regional sales"]
OWNERSHIP = ["full sales cycle","end-to-end sales","end to end","own the entire","own the full",
             "close new business","closing","net new","new logo","land and expand","quota",
             "book of business","own a territory","own the relationship","drive revenue",
             "pipeline generation","prospect to close","complex sales cycles","multi-threaded"]
NON_IC = ["solutions engineer","sales engineer","solution engineering","solutions engineering",
          "customer success","account coordinator","sales development representative","sdr","bdr",
          "pre-sales","presales","marketing manager","product manager","consultant",
          "implementation","solutions architect","solution architect","partner manager",
          "channel manager","renewals","support engineer","technical account manager"]
SENIOR_WORDS = ["senior","principal","strategic","global","enterprise","major","director",
                "lead","head of","vp","vice president","staff","sr."]
BIG_DEAL = ["seven-figure","seven figure","six-figure","six figure","multi-million","$1m","£1m",
            "fortune 500","ftse","global 2000","c-level","c-suite","cxo","board level",
            "executive stakeholders","large enterprise","complex enterprise","£1m+","multi-year"]
SMB_WORDS = ["mid-market","midmarket","smb","small and medium","commercial segment","velocity sales",
             "transactional sales","high volume","inside sales"]
DOMAIN = ["data platform","data infrastructure","machine learning","artificial intelligence","ai","llm","large language model","genai","generative ai","cloud","saas","analytics",
          "data warehouse","observability","devops","api","kubernetes","data governance","mlops",
          "software platform","enterprise software","cybersecurity","cyber security","data science",
          "etl","lakehouse","vector database","automation platform","integration platform"]
DOMAIN_IND = ["software development","it services","information technology","data infrastructure",
              "computer and network security","technology, information and internet",
              "computer software","internet publishing","information services"]
FSI = ["financial services","banking","banks","capital markets","investment bank","fintech",
       "payments","wealth management","asset management","insurance","fsi","regulated industries",
       "hedge fund","trading","risk and compliance","aml","kyc","basel","mifid","dora"]
UK_GOOD = ["london","england","united kingdom","scotland","wales","northern ireland","uk"]

WATCHLIST = {"snowflake":"Snowflake","databricks":"Databricks","anthropic":"Anthropic",
             "openai":"OpenAI","mistral":"Mistral","mistral ai":"Mistral","nvidia":"NVIDIA",
             "servicenow":"ServiceNow","finastra":"Finastra","dataiku":"Dataiku",
             "collibra":"Collibra","quantexa":"Quantexa","aws":"AWS","amazon":"AWS",
             "amazon web services":"AWS"}

def count_hits(text, words):
    return sum(1 for w in words if has(text, w))

def score(r):
    """Return (total, {dim: (points, max, evidence)})."""
    title = r.get("title") or ""
    tl = title.lower()
    desc, resp, req = blobs(r)
    dl = desc.lower(); rl = resp.lower(); ql = req.lower()
    allt = f" {dl} {rl} {ql} "
    ind = (r.get("org_linkedin_industry") or "").lower()
    d = {}

    # 1. Sales motion: IC closing / strategic ownership (25)
    is_closing = any_has(tl, CLOSING_TITLES)
    is_non_ic  = any_has(tl, NON_IC)
    own_hits   = count_hits(allt, OWNERSHIP)
    if is_non_ic:
        p = 6
    elif is_closing and own_hits >= 4: p = 25
    elif is_closing and own_hits >= 2: p = 21
    elif is_closing and own_hits >= 1: p = 17
    elif is_closing:                   p = 13
    elif own_hits >= 3:                p = 12
    elif own_hits >= 1:                p = 8
    else:                              p = 3
    d["Sales motion (IC closing / strategic ownership)"] = (
        p, 25, sent_with(resp or desc, *OWNERSHIP) or title)

    # 2. Seniority and deal profile (20)
    exp = r.get("ai_experience_level") or ""
    sen_hits = count_hits(tl, SENIOR_WORDS)
    big = count_hits(allt, BIG_DEAL)
    smb = count_hits(allt + " " + tl, SMB_WORDS)
    p = 0
    p += {"10+":9, "5-10":7, "2-5":3, "0-2":0}.get(exp, 3)
    p += min(sen_hits, 2) * 2.5           # up to 5
    p += min(big, 3) * 2                  # up to 6
    p -= min(smb, 2) * 3                  # up to -6
    p = max(0, min(20, p))
    d["Seniority and deal profile"] = (
        round(p,1), 20, sent_with(desc, *BIG_DEAL) or f"experience level {exp}; title '{title}'")

    # 3. Domain: data / AI / cloud SaaS (20)
    dom = count_hits(allt, DOMAIN)
    ind_ok = any(w in ind for w in DOMAIN_IND)
    p = min(14, dom * 2.5) + (6 if ind_ok else 0)
    p = max(0, min(20, p))
    d["Domain (data / AI / cloud SaaS)"] = (
        round(p,1), 20, sent_with(desc, *DOMAIN) or f"industry: {r.get('org_linkedin_industry')}")

    # 4. FSI vertical alignment (10)
    fsi = count_hits(allt, FSI)
    p = min(10, fsi * 2.5)
    d["FSI vertical alignment"] = (round(p,1), 10, sent_with(desc, *FSI) or "no FSI signal in JD")

    # 5. Company quality (10)
    hc = r.get("org_linkedin_headcount")
    try: hc = int(hc)
    except Exception: hc = None
    foll = r.get("org_linkedin_followers")
    try: foll = int(foll)
    except Exception: foll = None
    inv = r.get("org_crunchbase_total_investment")
    p = 0
    if hc is not None:
        p += 5 if hc >= 1000 else 4 if hc >= 250 else 3 if hc >= 50 else 2
    if foll is not None:
        p += 3 if foll >= 100000 else 2 if foll >= 20000 else 1
    if inv: p += 2
    if norm_company(r.get("organization")) in WATCHLIST: p = 10
    p = max(0, min(10, p))
    d["Company quality"] = (round(p,1), 10,
        f"headcount {r.get('org_linkedin_headcount')}, LinkedIn followers {foll}, industry {r.get('org_linkedin_industry')}")

    # 6. Location and UK eligibility (10)
    loc = loc_string(r).lower()
    ctry = [c.lower() for c in (r.get("countries_derived") or [])]
    wm = WORK_MODE.get(r.get("ai_work_arrangement") or "", "Unknown")
    p = 0
    if has(loc, "london"): p = 10
    elif any_has(loc, UK_GOOD) or "united kingdom" in ctry: p = 8
    else: p = 2
    if wm == "On-site" and not has(loc, "london"): p -= 2
    p = max(0, min(10, p))
    d["Location and UK eligibility"] = (p, 10, f"{loc_string(r)} ({wm})")

    # Comp dimension removed in v1.1 (81% non-disclosure made it noise).
    # The six remaining dimensions sum to 95; rescale to 100 so the 70/55
    # thresholds keep their intended meaning. Comp is still recorded in the
    # Salary property and reported below as context, it just does not score.
    raw_total = sum(v[0] for v in d.values())
    total = round(raw_total * 100.0 / 95.0)
    return total, d

def verdict(sc):
    return "Strong" if sc >= 70 else "Partial" if sc >= 55 else "Noise"

# ---------------------------------------------------------------- build rows
prepared = []
for r in rows:
    title = (r.get("title") or "").strip()
    org   = (r.get("organization") or "").strip()
    hf, hf_ev = hard_fail(r)
    if hf:
        sc, dims, mv = 0, {}, "Noise"
    else:
        sc, dims = score(r)
        mv = verdict(sc)
    nc = norm_company(org)
    prepared.append({
        "source_id": r.get("id"),
        "Role": title, "Company": org,
        "Feed": "ATS",
        "Job URL": r.get("url") or r.get("apply_url") or "",
        "Source Job ID": str(r.get("id") or ""),
        "Location": loc_string(r),
        "Work Mode": WORK_MODE.get(r.get("ai_work_arrangement") or "", "Unknown"),
        "Posted": (r.get("date_posted") or "")[:10] or None,
        "Fetched": TODAY,
        "Org Industry": r.get("org_linkedin_industry") or "",
        "Org Headcount": str(r.get("org_linkedin_headcount") or r.get("org_linkedin_size") or ""),
        "Salary": salary_string(r),
        "Experience Level": (r.get("ai_experience_level") if r.get("ai_experience_level") in EXP_OK else "Unknown"),
        "Machine Verdict": mv,
        "Fit Score": sc,
        "Hard Fail Reason": hf or "None",
        "hard_fail_evidence": hf_ev,
        "Watchlist": nc in WATCHLIST,
        "Dedup Key": dedup_key(org, title),
        "Duplicate": False,
        "Rubric Version": RUBRIC,
        "Intake Status": "New",
        "dims": dims,
        "raw": r,
    })

# ---------------------------------------------------------------- in-batch dedup
bykey = collections.OrderedDict()
for p in prepared:
    bykey.setdefault(p["Dedup Key"], []).append(p)

dupe_groups = []
for k, grp in bykey.items():
    if len(grp) > 1:
        keeper = grp[0]
        locs = []
        for g in grp:
            for piece in (g["Location"] or "").split(";"):
                piece = piece.strip()
                if piece and piece not in locs: locs.append(piece)
        keeper["Location"] = "; ".join(locs)
        for g in grp[1:]:
            g["Duplicate"] = True
        dupe_groups.append((k, grp))

# ---------------------------------------------------------------- cross-DB
roles = []
for line in open("roles.tsv"):
    parts = line.rstrip("\n").split("\t")
    if len(parts) < 3: continue
    comp, rtitle, url = parts[0], parts[1], parts[2]
    roles.append({"company": comp, "title": rtitle, "url": url,
                  "key": dedup_key(comp, rtitle),
                  "ncomp": norm_company(comp), "ntitle": norm_title(rtitle)})

exact_matches, near_matches = [], []
for p in prepared:
    hit = next((x for x in roles if x["key"] == p["Dedup Key"]), None)
    if hit:
        p["Intake Status"] = "Promoted"
        p["roles_url"] = hit["url"]; p["roles_title"] = hit["title"]; p["roles_company"] = hit["company"]
        exact_matches.append((p, hit))
        continue
    nc = norm_company(p["Company"])
    if not nc: continue
    for x in roles:
        same_co = x["ncomp"] == nc or (nc and (nc in x["ntitle"]))
        if not same_co: continue
        a = set(norm_title(p["Role"]).split()); b = set(x["ntitle"].split())
        if a and len(a & b) / len(a) >= 0.6:
            near_matches.append((p, x)); break

# ---------------------------------------------------------------- report
out = []
W = out.append
n = len(prepared)
dupes = sum(1 for p in prepared if p["Duplicate"])
W(f"SOURCE FILE            : {SRC}")
W(f"ROWS PARSED            : {n}")
W(f"DUPLICATE ROWS FLAGGED : {dupes}  (in {len(dupe_groups)} groups; keepers not flagged)")
W(f"UNIQUE DEDUP KEYS      : {len(bykey)}")
W("")
vc = collections.Counter(p["Machine Verdict"] for p in prepared)
W("VERDICT DISTRIBUTION")
for v in ("Strong","Partial","Noise"):
    W(f"  {v:<8} {vc.get(v,0):>3}  ({vc.get(v,0)*100//n}%)")
W("")
hfc = collections.Counter(p["Hard Fail Reason"] for p in prepared if p["Hard Fail Reason"] != "None")
W(f"HARD FAILS             : {sum(hfc.values())}")
for k, v in hfc.most_common(): W(f"  {k:<26} {v}")
W("")
W("SCORE HISTOGRAM (10-pt buckets)")
hist = collections.Counter(min(90, (p["Fit Score"]//10)*10) for p in prepared)
for b in range(0, 100, 10):
    c = hist.get(b, 0)
    W(f"  {b:>3}-{b+9:<3} {c:>3} {'#'*c}")
scores = sorted(p["Fit Score"] for p in prepared)
nz = [s for s in scores if s > 0]
W(f"  min {scores[0]}  median {scores[n//2]}  max {scores[-1]}"
  f"   | excluding hard-fails: min {nz[0] if nz else '-'} median {nz[len(nz)//2] if nz else '-'}")
W("COMP DISCLOSURE (context only - not scored in v1.1)")
_disc = [p for p in prepared if p["Salary"]]
W(f"  rows with any salary data: {len(_disc)}/{n}")
for _p in _disc[:12]:
    W(f"    {_p['Company'][:22]:<22} {_p['Role'][:44]:<44} {_p['Salary']}")
W("")
wl = [p for p in prepared if p["Watchlist"]]
W(f"WATCHLIST HITS         : {len(wl)}")
for p in wl:
    W(f"  {p['Company']:<22} {p['Role'][:58]:<58} {p['Fit Score']:>3} {p['Machine Verdict']}")
W("")
W(f"CROSS-DB EXACT MATCHES (-> Intake Status 'Promoted'): {len(exact_matches)}")
for p, h in exact_matches:
    W(f"  {p['Company']} | {p['Role']}  ->  {h['url']}")
W(f"CROSS-DB NEAR MATCHES  (same company, >=60% title token overlap; NOT promoted): {len(near_matches)}")
for p, h in near_matches:
    W(f"  intake: {p['Company']:<20} {p['Role'][:46]:<46}")
    W(f"    roles: {h['company']:<20} {h['title'][:70]}")
W("")
W("IN-BATCH DUPLICATE GROUPS")
for k, grp in dupe_groups:
    W(f"  key: {k}")
    for i, g in enumerate(grp):
        W(f"    [{'KEEP' if i==0 else 'DUP '}] {g['Location']}  ({g['source_id']})")
W("")
W("="*100)
W("5 SAMPLE SCORED ROWS")
W("="*100)
ranked = sorted([p for p in prepared if p["Hard Fail Reason"]=="None"], key=lambda x:-x["Fit Score"])
samples = ranked[:2] + ranked[len(ranked)//2:len(ranked)//2+1] + ranked[-1:]
samples += [p for p in prepared if p["Hard Fail Reason"]!="None"][:1]
for p in samples[:5]:
    W("")
    W(f"{p['Role']} — {p['Company']}")
    W(f"  {p['Location']} | {p['Work Mode']} | exp {p['Experience Level']} | posted {p['Posted']} | {p['Org Industry']}")
    W(f"  Salary: {p['Salary'] or '(not disclosed)'}")
    W(f"  FIT {p['Fit Score']}  ->  {p['Machine Verdict']}   Hard fail: {p['Hard Fail Reason']}"
      + (f"  [{p['hard_fail_evidence'][:90]}]" if p['Hard Fail Reason']!="None" else ""))
    W(f"  Watchlist: {p['Watchlist']} | Dedup key: {p['Dedup Key']}")
    for dim,(pt,mx,ev) in p["dims"].items():
        W(f"    {pt:>5}/{mx:<3} {dim:<46} {ev[:88]}")
print("\n".join(out))

json.dump([{k:v for k,v in p.items() if k!="raw"} for p in prepared],
          open("prepared.json","w"), indent=1, default=str)
