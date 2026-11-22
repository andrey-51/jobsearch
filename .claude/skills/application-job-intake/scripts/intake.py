#!/usr/bin/env python3
"""Apify run -> Role Intake helper. Every subcommand works inside one work directory (--dir).

  fetch    <run>                     download dataset, run metadata and actor input; print a summary
  prepare  <run> --date YYYY-MM-DD   score (pipeline.py) and build page bodies (bodies.py)
  live-sql <run>                     print the SQL that fetches only the live rows this batch could collide with
  live-rest <run>                    read all live rows' job ids and dedup keys over the REST API (needs Notion_KEY)
  dedup    <run> --live FILE         split the batch against live Role Intake rows and the ledger
  batches  <run> [--size N]          write screening batch files for the ATS screen
  final    <run>                     merge screen verdicts into the rows to write; validate them
  show     <run> <i> <j>             print connector-ready properties and body for rows i..j-1
  verify   <run> --got FILE          compare what Notion holds with what was intended
  ledger-add <run>                   record the written rows in data/ledger.csv

Secrets come from the environment (APIFY_TOKEN, Notion_KEY) and are never printed or written.
"""
import argparse, collections, csv, hashlib, json, os, re, shutil, subprocess, sys, urllib.error, urllib.request

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(SKILL, "scripts")
LEDGER = os.path.join(SKILL, "data", "ledger.csv")
ROLES_TSV = os.path.join(SKILL, "data", "roles.tsv")
UA = "Mozilla/5.0 (compatible; intake-bot)"   # generic on purpose: never a name or email


def path(a, name):
    os.makedirs(a.dir, exist_ok=True)
    return os.path.join(a.dir, name)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


# ---------------------------------------------------------------- fetch
def cmd_fetch(a):
    tok = os.environ["APIFY_TOKEN"]
    base = f"https://api.apify.com/v2/actor-runs/{a.run}"
    try:
        meta = get(f"{base}?token={tok}")["data"]
    except urllib.error.HTTPError as e:
        # Andrey sometimes pastes the dataset id instead of the run id (2026-11-22): resolve it to its run.
        if e.code != 404:
            raise
        run = get(f"https://api.apify.com/v2/datasets/{a.run}?token={tok}")["data"]["actRunId"]
        print(f"{a.run} is a dataset id; it belongs to run {run}. Use {run} for every later step.")
        a.run, base = run, f"https://api.apify.com/v2/actor-runs/{run}"
        meta = get(f"{base}?token={tok}")["data"]
    items = get(f"{base}/dataset/items?format=json&clean=true&token={tok}")
    inp = get(f"https://api.apify.com/v2/key-value-stores/{meta['defaultKeyValueStoreId']}/records/INPUT?token={tok}")
    json.dump(items, open(path(a, f"run_{a.run}.json"), "w"))
    json.dump(meta, open(path(a, f"meta_{a.run}.json"), "w"))
    json.dump(inp, open(path(a, f"input_{a.run}.json"), "w"))
    print(f"status {meta['status']} | started {meta['startedAt'][:19]} | cost ${meta.get('usageTotalUsd')} | actor {meta.get('actId')}")
    print(f"items {len(items)} | unique ids {len({str(x['id']) for x in items})}")
    print("date_created:", dict(sorted(collections.Counter((x.get('date_created') or '')[:10] for x in items).items())))
    short = {k: (v if not isinstance(v, list) or len(v) < 6 else f"[{len(v)} items]") for k, v in inp.items()}
    print("input:", short)


# ---------------------------------------------------------------- prepare
def strip_assessment(body):
    i = body.find("## Assessment")
    if i < 0:
        return body
    j = body.find("\n## ", i + 5)
    return body[:i] + (body[j + 1:] if j >= 0 else "")


def cmd_prepare(a):
    env = dict(os.environ, INTAKE_DATE=a.date, ROLES_TSV=ROLES_TSV)
    src = os.path.abspath(path(a, f"run_{a.run}.json"))
    for script, out, dst in [("pipeline.py", "prepared.json", f"prepared_{a.run}.json"),
                             ("bodies.py", "towrite.json", f"towrite_all_{a.run}.json")]:
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, script), src],
                           cwd=a.dir, env=env, capture_output=True, text=True)
        open(path(a, f"{script}.{a.run}.log"), "w").write(r.stdout + r.stderr)
        if r.returncode != 0:
            sys.exit(f"{script} failed; see {script}.{a.run}.log")
        shutil.move(path(a, out), path(a, dst))
    rows = json.load(open(path(a, f"towrite_all_{a.run}.json")))
    for r in rows:
        r["body"] = strip_assessment(r["body"])
    json.dump(rows, open(path(a, f"towrite_all_{a.run}.json"), "w"), ensure_ascii=False)
    print(f"prepared {len(rows)} rows")
    print("machine verdicts:", dict(collections.Counter(r["Machine Verdict"] for r in rows)))
    print("hard fails:", dict(collections.Counter(r["Hard Fail Reason"] for r in rows)))
    for r in rows:
        if r["Hard Fail Reason"] in ("Management track", "Wrong location/US leak", "FTC/contract"):
            # these two rules misfire often; show the evidence so a human can judge
            ev = str(r.get("hard_fail_evidence", ""))[:150]
            print(f"  CHECK {r['Hard Fail Reason']}: {r['Company'][:24]} | {r['Role'][:40]} | {ev}")


# ---------------------------------------------------------------- dedup
# jd_hash was added on 2026-11-01; older rows leave it empty (DictReader gives None).
LEDGER_COLS = ["sid", "dedup_key", "company", "role", "run", "written", "jd_hash"]


def read_ledger():
    if not os.path.exists(LEDGER):
        return {}
    return {row["sid"]: row for row in csv.DictReader(open(LEDGER))}


def read_live(f):
    """Live file = the 'live' strings returned by the live-sql queries, pasted one per line
    (rows joined by '^^', fields by '~~'). Duplicates across queries are fine."""
    raw = "^^".join(l.strip() for l in open(f) if l.strip())
    live = {}
    for chunk in raw.split("^^"):
        if not chunk.strip():
            continue
        sid, _, key = chunk.partition("~~")
        if sid.strip():
            live[sid.strip()] = key.strip()
    return live


def relevant(a):
    """Batch sids and keys, plus ledger rows sharing either: the only rows dedup needs to know about."""
    rows = json.load(open(path(a, f"towrite_all_{a.run}.json")))
    sids = {r["Source Job ID"] for r in rows}
    keys = {r["Dedup Key"] for r in rows}
    jds = {jd_hash(r) for r in rows} - {None}
    ledger = read_ledger()
    rel = {s: r for s, r in ledger.items() if s in sids or r["dedup_key"] in keys or r.get("jd_hash") in jds}
    return rows, sids | set(rel), keys, rel


def cmd_live_rest(a):
    """Read every live Role Intake row's Source Job ID and Dedup Key through the Notion REST API (read-only) and write
    them as live_<run>.txt for dedup. Needs a working Notion_KEY; used for big runs where live-sql would need many
    connector calls (2026-11-22: 1,000 rows)."""
    tok = os.environ["Notion_KEY"]
    ds = "441379e4-d36a-4d53-b834-57242e0dafb3"
    txt = lambda p: "".join(t.get("plain_text", "") for t in (p or {}).get("rich_text", []))
    out, cursor = [], None
    while True:
        body = {"page_size": 100, **({"start_cursor": cursor} if cursor else {})}
        req = urllib.request.Request(f"https://api.notion.com/v1/data_sources/{ds}/query", data=json.dumps(body).encode(),
                                     method="POST", headers={"Authorization": f"Bearer {tok}", "Notion-Version": "2025-09-03",
                                                             "Content-Type": "application/json", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            res = json.loads(r.read().decode())
        for pg in res["results"]:
            pr = pg["properties"]
            sid = txt(pr.get("Source Job ID"))
            if sid:
                out.append(f"{sid}~~{txt(pr.get('Dedup Key'))}")
        if not res.get("has_more"):
            break
        cursor = res["next_cursor"]
    open(path(a, f"live_{a.run}.txt"), "w").write("^^".join(out) + "\n")
    print(f"live rows with a job id: {len(out)} -> live_{a.run}.txt")


def cmd_live_sql(a):
    """Two read-only queries. Job ids are digits, so they go inline. Dedup keys carry quotes, dashes and
    pipes, so they go as bound parameters (the connector accepts at most 100 per call)."""
    _, sids, keys, _ = relevant(a)
    ds = '"collection://441379e4-d36a-4d53-b834-57242e0dafb3"'
    sel = f"SELECT group_concat(\"Source Job ID\" || '~~' || coalesce(\"Dedup Key\",''), '^^') AS live FROM {ds} WHERE "
    ids = sorted(s for s in sids if s.isdigit())
    print("### QUERY 1 (job ids, no params)")
    print(sel + "\"Source Job ID\" IN (" + ",".join(f"'{s}'" for s in ids) + ")")
    keys = sorted(keys)
    for n, b in enumerate(range(0, len(keys), 100), start=2):
        chunk = keys[b:b + 100]
        print(f"### QUERY {n} (dedup keys, pass PARAMS as the params array)")
        print(sel + "\"Dedup Key\" IN (" + ",".join("?" * len(chunk)) + ")")
        print("PARAMS " + json.dumps(chunk, ensure_ascii=False))


def jd_hash(r):
    """Fingerprint of the job description text, so the same posting under another title or job board
    (seen 2026-10-26: Rithum vs "Rithum LinkedIn Board", Build Technologies AE vs Senior AE) counts as a duplicate."""
    jd = r["body"].split("## Full JD", 1)[-1]
    jd = re.sub(r"\s+", " ", jd).strip()
    return hashlib.md5(jd.encode()).hexdigest() if len(jd) > 200 else None


# Loose role key: company without legal suffixes and title as a set of words, so the same role under another company
# spelling or word order matches (2026-11-22: LinkedIn "Aircall" vs job board "Aircall.io, Inc.", "Enterprise Account
# Executive" vs "Account Executive, Enterprise").
CO_STOP = r"\b(io|inc|ltd|limited|llc|plc|group|gmbh|corp|corporation|co|technologies|software|ai|uk|the)\b"


def loose_key(k):
    co, _, ti = k.partition("|")
    core = re.sub(r"[^a-z0-9]", "", re.sub(CO_STOP, "", co))
    words = frozenset(w for w in re.findall(r"[a-z0-9&]+", re.sub(r"copy of|\(copy\)", "", ti)) if w not in ("and", "the", "of"))
    return (core, words) if core and words else None


def cmd_dedup(a):
    live = read_live(a.live)
    _, _, _, ledger = relevant(a)
    deleted = {s: r for s, r in ledger.items() if s not in live}
    live_keys = set(live.values()) - {""}
    deleted_keys = {r["dedup_key"] for r in deleted.values()} - live_keys
    # Same job description as a row written in an earlier run, under another title or board (2026-11-01: Build
    # Technologies "Account Executive" came back a week after its "Senior Account Executive" twin was written).
    live_jd = {r.get("jd_hash") for s, r in ledger.items() if s in live} - {None, ""}
    deleted_jd = {r.get("jd_hash") for r in deleted.values()} - live_jd - {None, ""}
    live_loose = {loose_key(k) for k in live_keys} - {None}
    rows = json.load(open(path(a, f"towrite_all_{a.run}.json")))
    cat = collections.defaultdict(list)
    seen, seen_jd, seen_loose = set(), set(), set()
    # Highest machine score first, then the shorter company name ("Rithum" over "Rithum LinkedIn Board"),
    # so when two copies collide the better one is kept.
    for r in sorted(rows, key=lambda r: (-r["Fit Score"], len(r["Company"]))):
        s, k, j, lk = r["Source Job ID"], r["Dedup Key"], jd_hash(r), loose_key(r["Dedup Key"])
        if s in live: c = "posting already live"
        elif s in deleted: c = "posting deleted by user"
        elif k in deleted_keys: c = "same role as a deleted row"
        elif k in live_keys: c = "same role as a live row"
        elif j and j in deleted_jd: c = "same JD as a deleted row"
        elif j and j in live_jd: c = "same JD as a live row"
        elif lk and lk in live_loose: c = "same role as a live row (other spelling)"
        elif r.get("Duplicate") or k in seen: c = "in-batch duplicate"
        elif j and j in seen_jd: c = "in-batch duplicate (same JD, other title or board)"
        elif lk and lk in seen_loose: c = "in-batch duplicate (other spelling)"
        else: c = "new"
        if c == "new":
            seen.add(k)
            if j:
                seen_jd.add(j)
            if lk:
                seen_loose.add(lk)
        cat[c].append(r)
    new = sorted(cat["new"], key=lambda r: (-r["Fit Score"], r["Company"]))
    json.dump(new, open(path(a, f"towrite_{a.run}.json"), "w"), ensure_ascii=False)
    json.dump({c: [r["Source Job ID"] for r in v] for c, v in cat.items()}, open(path(a, f"dedup_{a.run}.json"), "w"))
    print(f"live rows that touch this batch {len(live)} | ledger rows that touch it {len(ledger)} | of those deleted by user {len(deleted)}")
    for c in ["new", "same role as a live row", "same role as a live row (other spelling)", "same role as a deleted row",
              "same JD as a live row", "same JD as a deleted row", "posting already live", "posting deleted by user",
              "in-batch duplicate", "in-batch duplicate (same JD, other title or board)", "in-batch duplicate (other spelling)"]:
        v = cat.get(c, [])
        print(f"{c:28s} {len(v):4d} {dict(collections.Counter(r['Machine Verdict'] for r in v))}")
    for c in ["same role as a deleted row", "same role as a live row", "same role as a live row (other spelling)",
              "same JD as a deleted row", "same JD as a live row"]:
        for r in cat.get(c, []):
            print(f"   {c[:24]:24s} | {r['Fit Score']:>3} | {r['Company'][:26]:26s} | {r['Role'][:55]}")
    print("new, machine Strong:")
    for r in new:
        if r["Machine Verdict"] == "Strong":
            print(f"   {r['Fit Score']:>3} | {r['Company'][:26]:26s} | {r['Role'][:60]}")


# ---------------------------------------------------------------- screening batches
LANGS = "German|French|Dutch|Spanish|Italian|Portuguese|Swedish|Danish|Norwegian|Finnish|Nordic|Arabic|Polish|Hebrew|Japanese|Mandarin|Russian|Czech|Hungarian"
LANG_RE = rf"\b({LANGS})\b[^.]{{0,40}}\b(speak|speaking|fluen|native|proficien|language)|\b(fluen\w*|native|speaking)\b[^.]{{0,30}}\b({LANGS})\b"


def flags(d):
    f = [m.group(0)[:70] for m in re.finditer(LANG_RE, d, re.I)]
    f += [m.group(0) for m in re.finditer(r"\b(SC clearance|DV clearance|security clearance|SC cleared|DV cleared|eligible for SC)\b", d, re.I)]
    f += [m.group(0) for m in re.finditer(r"\b(public sector|central government|education sector|healthcare|NHS|defen[cs]e)\b", d, re.I)]
    return "; ".join(dict.fromkeys(f))[:300]


def rule_keys(a):
    """Rows already decided as Skip by the language/public/security rule, listed before screening in
    screen/verdicts_<run>_rules.txt as "Kxxx|-|Skip|TAG reason". They are left out of the screening batches."""
    f = path(a, f"screen/verdicts_{a.run}_rules.txt")
    return {l.split("|", 1)[0] for l in open(f) if l.strip()} if os.path.exists(f) else set()


def cmd_batches(a):
    raw = {str(x["id"]): x for x in json.load(open(path(a, f"run_{a.run}.json")))}
    rows = json.load(open(path(a, f"towrite_{a.run}.json")))
    os.makedirs(path(a, "screen"), exist_ok=True)
    pre = rule_keys(a)
    mp, out, ks = [], [], []
    for i, r in enumerate(rows):
        k = f"K{i:03d}"
        x = raw[r["Source Job ID"]]
        d = re.sub(r"\s+", " ", x.get("description_text") or "")
        mp.append({"k": k, "sid": r["Source Job ID"]})
        if k in pre:
            continue
        ks.append(k)
        out.append(f"### {k} | {x.get('title')} | {x.get('organization')} | {x.get('org_linkedin_industry')} | "
                   f"hc {x.get('org_linkedin_headcount')} | {'; '.join(x.get('locations_derived') or [])} | "
                   f"{x.get('ai_work_arrangement')} | exp {x.get('ai_experience_level')}\n"
                   f"REQ: {x.get('ai_requirements_summary') or ''}\n"
                   f"SKILLS: {', '.join((x.get('ai_key_skills') or [])[:12])}\n"
                   f"FLAGS (regex scan of full JD): {flags(d) or 'none'}\n"
                   f"JD: {d[:2400]}\n\n")
    json.dump(mp, open(path(a, f"map_{a.run}.json"), "w"))
    if pre:
        print(f"left out {len(pre)} rule Skips: {sorted(pre)}")
    n = 0
    for b in range(0, len(out), a.size):
        open(path(a, f"screen/batch_{a.run}_{n}.txt"), "w").write("".join(out[b:b + a.size]))
        print(f"screen/batch_{a.run}_{n}.txt  {len(out[b:b + a.size])} rows  {ks[b]}..{ks[min(b + a.size, len(ks)) - 1]}")
        n += 1


# ---------------------------------------------------------------- merge verdicts
def load_verdicts(a):
    v = {}
    d = path(a, "screen")
    for f in sorted(os.listdir(d)):
        if f.startswith(f"verdicts_{a.run}_") and f.endswith(".txt"):
            for line in open(os.path.join(d, f)):
                if not line.strip():
                    continue
                p = line.rstrip("\n").split("|", 3)
                if len(p) != 4 or p[2] not in ("Pursue", "Borderline", "Skip"):
                    sys.exit(f"bad verdict line in {f}: {line[:80]}")
                if p[0] in v:
                    sys.exit(f"duplicate verdict key {p[0]}")
                v[p[0]] = (p[2], None if p[1] == "-" else int(p[1]), p[3])
    return v


# Andrey's rule (2026-10-12): roles that require another language, or that sell into public sector, defence,
# security or cyber, are always Skip, and the reason starts with a tag so they can be filtered in Notion.
# "PUBLIC/DEFENCE:" was the tag before security was added; it is still recognised on old reasons.
PDS = "PUBLIC/DEFENCE/SECURITY:"
TAGS = ("LANGUAGE:", PDS, "PUBLIC/DEFENCE:")
TITLE_LANG = re.compile(rf"\b({LANGS}|Italian|Bilingual|Multilingual)\b|speaking", re.I)
TITLE_PUBLIC = re.compile(r"public sector|\bgovernment\b|central gov|local gov|\bdefen[cs]e\b|blue light|\bNHS\b|"
                          r"\bMoD\b|ministry|\bfederal\b|law enforcement|\bpolice\b|\bsecurity\b|cyber|\bIAM\b|\bidentity\b|\bSOC\b", re.I)
SECURITY_INDUSTRY = re.compile(r"computer and network security|security and investigations", re.I)  # physical security added 2026-11-22


def hard_skip(k, r, vd, sc, why):
    """Apply the language and public/defence/security rule. The screener tags most rows; a title or security-vendor
    industry match is forced here in case it missed one. JD-only signals stay with the screener, because boilerplate
    mentions are common."""
    tag = next((t for t in TAGS if why.startswith(t)), None)
    if not tag:
        title = r["Role"]
        if TITLE_LANG.search(title):
            tag, why = "LANGUAGE:", f"LANGUAGE: title names a language requirement ({title}). {why}"
        elif TITLE_PUBLIC.search(title):
            tag, why = PDS, f"{PDS} title names a public sector, defence or security patch ({title}). {why}"
        elif SECURITY_INDUSTRY.search(r.get("Org Industry") or ""):
            tag, why = PDS, f"{PDS} company is a security vendor ({r['Org Industry']}). {why}"
        if tag:
            print(f"FORCED {k} {tag} {r['Company'][:24]} | {title[:50]} (screen said {vd} {sc})")
    if tag and (vd != "Skip" or (sc or 0) > 55):
        vd, sc = "Skip", None if sc is None else min(sc, 55)
    return vd, sc, why


def cmd_final(a):
    rows = json.load(open(path(a, f"towrite_{a.run}.json")))
    mp = {m["sid"]: m["k"] for m in json.load(open(path(a, f"map_{a.run}.json")))}
    v = load_verdicts(a)
    missing = [k for k in mp.values() if k not in v]
    if missing:
        sys.exit(f"no verdict for {missing}")
    for r in rows:
        k = mp[r["Source Job ID"]]
        vd, sc, why = v[k]
        if sc is None and vd != "Skip":
            sys.exit(f"{k}: an unscreened row (score '-') must be a rule Skip")
        vd, sc, why = hard_skip(k, r, vd, sc, why)
        if sc is not None and (vd == "Pursue" and sc < 75 or vd == "Skip" and sc >= 60):
            print(f"WARN score/verdict mismatch {k} {vd} {sc}")
        r["Triage"], r["ATS Score"], r["Triage Reason"] = vd, sc, why[:2000]
        if r["Intake Status"] == "New" and (sc is None or vd == "Skip" and a.skip_status):
            # rule Skips decided before screening always; screened Skips with --skip-status (Andrey, 2026-11-09)
            r["Intake Status"] = "Skipped"
    json.dump(rows, open(path(a, f"final_{a.run}.json"), "w"), ensure_ascii=False)
    print(f"final rows {len(rows)} {dict(collections.Counter(r['Triage'] for r in rows))} "
          f"| Intake Status {dict(collections.Counter(r['Intake Status'] for r in rows))}")
    for r in sorted(rows, key=lambda r: -(r["ATS Score"] or 0)):
        if r["Triage"] == "Pursue":
            print(f"   ATS {r['ATS Score']} | fit {r['Fit Score']:>3} | {r['Company'][:26]:26s} | {r['Role'][:55]}")


# ---------------------------------------------------------------- show (connector payloads)
def cmd_show(a):
    rows = json.load(open(path(a, f"final_{a.run}.json")))
    for i in range(a.i, min(a.j, len(rows))):
        r = rows[i]
        props = {"Role": r["Role"], "Company": r["Company"], "Feed": r["Feed"], "Job URL": r["Job URL"],
                 "Source Job ID": r["Source Job ID"], "Location": r["Location"], "Work Mode": r["Work Mode"],
                 "date:Posted:start": r["Posted"], "date:Fetched:start": r["Fetched"],
                 "Org Industry": r["Org Industry"], "Org Headcount": r["Org Headcount"], "Salary": r["Salary"],
                 "Experience Level": r["Experience Level"], "Fit Score": r["Fit Score"],
                 "Hard Fail Reason": r["Hard Fail Reason"],
                 "Watchlist": "__YES__" if r["Watchlist"] else "__NO__",
                 "Dedup Key": r["Dedup Key"], "Duplicate": "__NO__", "Intake Status": r["Intake Status"],
                 "Triage": r["Triage"], "ATS Score": r["ATS Score"], "Triage Reason": r["Triage Reason"]}
        if not r.get("Posted"):
            props.pop("date:Posted:start")
        print(f"=============== ROW {i} ===============")
        print(json.dumps(props, ensure_ascii=False, indent=1))
        print("--------------- BODY ---------------")
        print(r["body"])
        print("--------------- ENDBODY ---------------")


# ---------------------------------------------------------------- verify + ledger
def cmd_verify(a):
    """--got holds the SQL group_concat of "sid:Triage:ATS Score:Intake Status" joined by '|'
    (the older three-field form without Intake Status is still accepted)."""
    got = {}
    for x in open(a.got).read().strip().split("|"):
        p = x.split(":")
        if len(p) >= 3:
            got[p[0]] = (p[1], p[2].split(".")[0]) + ((p[3],) if len(p) >= 4 else ())
    rows = json.load(open(path(a, f"final_{a.run}.json")))
    want = {r["Source Job ID"]: (r["Triage"], "" if r["ATS Score"] is None else str(r["ATS Score"]), r["Intake Status"])
            for r in rows}
    want = {s: w[:len(got[s])] if s in got else w for s, w in want.items()}
    missing = sorted(set(want) - set(got))
    # Rows another run wrote on the same Fetched date are in the ledger already; only unknown rows are unexpected.
    others = {s for s, r in read_ledger().items() if r["run"] != a.run}
    extra = sorted(set(got) - set(want) - others)
    bad = sorted(s for s in want if s in got and got[s] != want[s])
    print(f"intended {len(want)} | found {len(got)} | missing {missing or 'none'} | unexpected {extra or 'none'} | mismatched {bad or 'none'}")
    sys.exit(1 if missing or bad else 0)


def cmd_ledger_add(a):
    rows = json.load(open(path(a, f"final_{a.run}.json")))
    ledger = read_ledger()
    new = [r for r in rows if r["Source Job ID"] not in ledger]
    exists = os.path.exists(LEDGER)
    with open(LEDGER, "a", newline="") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(LEDGER_COLS)
        for r in new:
            w.writerow([r["Source Job ID"], r["Dedup Key"], r["Company"], r["Role"], a.run, r["Fetched"], jd_hash(r) or ""])
    print(f"ledger +{len(new)} rows -> {len(ledger) + len(new)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.environ.get("INTAKE_DIR", "./intake_work"))
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name in ["fetch", "ledger-add", "live-sql", "live-rest"]:
        sp.add_parser(name).add_argument("run")
    p = sp.add_parser("final"); p.add_argument("run")
    p.add_argument("--skip-status", action="store_true", help="also set Intake Status = Skipped on screened Skips")
    p = sp.add_parser("prepare"); p.add_argument("run"); p.add_argument("--date", required=True)
    p = sp.add_parser("dedup"); p.add_argument("run"); p.add_argument("--live", required=True)
    p = sp.add_parser("batches"); p.add_argument("run"); p.add_argument("--size", type=int, default=26)
    p = sp.add_parser("show"); p.add_argument("run"); p.add_argument("i", type=int); p.add_argument("j", type=int)
    p = sp.add_parser("verify"); p.add_argument("run"); p.add_argument("--got", required=True)
    a = ap.parse_args()
    {"fetch": cmd_fetch, "prepare": cmd_prepare, "dedup": cmd_dedup, "batches": cmd_batches,
     "final": cmd_final, "live-sql": cmd_live_sql, "live-rest": cmd_live_rest, "show": cmd_show, "verify": cmd_verify, "ledger-add": cmd_ledger_add}[a.cmd](a)


if __name__ == "__main__":
    main()
