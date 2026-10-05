#!/usr/bin/env python3
"""Apify run -> Role Intake helper. Every subcommand works inside one work directory (--dir).

  fetch    <run>                     download dataset, run metadata and actor input; print a summary
  prepare  <run> --date YYYY-MM-DD   score (pipeline.py) and build page bodies (bodies.py)
  live-sql <run>                     print the SQL that fetches only the live rows this batch could collide with
  dedup    <run> --live FILE         split the batch against live Role Intake rows and the ledger
  batches  <run> [--size N]          write screening batch files for the ATS screen
  final    <run>                     merge screen verdicts into the rows to write; validate them
  show     <run> <i> <j>             print connector-ready properties and body for rows i..j-1
  verify   <run> --got FILE          compare what Notion holds with what was intended
  ledger-add <run>                   record the written rows in data/ledger.csv

Secrets come from the environment (APIFY_TOKEN, Notion_KEY) and are never printed or written.
"""
import argparse, collections, csv, json, os, re, shutil, subprocess, sys, urllib.request

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
        if r["Hard Fail Reason"] in ("Management track", "Wrong location/US leak"):
            # these two rules misfire often; show the evidence so a human can judge
            ev = str(r.get("hard_fail_evidence", ""))[:150]
            print(f"  CHECK {r['Hard Fail Reason']}: {r['Company'][:24]} | {r['Role'][:40]} | {ev}")


# ---------------------------------------------------------------- dedup
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
    ledger = read_ledger()
    rel = {s: r for s, r in ledger.items() if s in sids or r["dedup_key"] in keys}
    return rows, sids | set(rel), keys, rel


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


def cmd_dedup(a):
    live = read_live(a.live)
    _, _, _, ledger = relevant(a)
    deleted = {s: r for s, r in ledger.items() if s not in live}
    live_keys = set(live.values()) - {""}
    deleted_keys = {r["dedup_key"] for r in deleted.values()} - live_keys
    rows = json.load(open(path(a, f"towrite_all_{a.run}.json")))
    cat = collections.defaultdict(list)
    seen = set()
    for r in rows:
        s, k = r["Source Job ID"], r["Dedup Key"]
        if s in live: c = "posting already live"
        elif s in deleted: c = "posting deleted by user"
        elif k in deleted_keys: c = "same role as a deleted row"
        elif k in live_keys: c = "same role as a live row"
        elif r.get("Duplicate") or k in seen: c = "in-batch duplicate"
        else: c = "new"
        if c == "new":
            seen.add(k)
        cat[c].append(r)
    new = sorted(cat["new"], key=lambda r: (-r["Fit Score"], r["Company"]))
    json.dump(new, open(path(a, f"towrite_{a.run}.json"), "w"), ensure_ascii=False)
    json.dump({c: [r["Source Job ID"] for r in v] for c, v in cat.items()}, open(path(a, f"dedup_{a.run}.json"), "w"))
    print(f"live rows that touch this batch {len(live)} | ledger rows that touch it {len(ledger)} | of those deleted by user {len(deleted)}")
    for c in ["new", "same role as a live row", "same role as a deleted row", "posting already live",
              "posting deleted by user", "in-batch duplicate"]:
        v = cat.get(c, [])
        print(f"{c:28s} {len(v):4d} {dict(collections.Counter(r['Machine Verdict'] for r in v))}")
    for c in ["same role as a deleted row", "same role as a live row"]:
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


def cmd_batches(a):
    raw = {str(x["id"]): x for x in json.load(open(path(a, f"run_{a.run}.json")))}
    rows = json.load(open(path(a, f"towrite_{a.run}.json")))
    os.makedirs(path(a, "screen"), exist_ok=True)
    mp, out = [], []
    for i, r in enumerate(rows):
        k = f"K{i:03d}"
        x = raw[r["Source Job ID"]]
        d = re.sub(r"\s+", " ", x.get("description_text") or "")
        mp.append({"k": k, "sid": r["Source Job ID"]})
        out.append(f"### {k} | {x.get('title')} | {x.get('organization')} | {x.get('org_linkedin_industry')} | "
                   f"hc {x.get('org_linkedin_headcount')} | {'; '.join(x.get('locations_derived') or [])} | "
                   f"{x.get('ai_work_arrangement')} | exp {x.get('ai_experience_level')}\n"
                   f"REQ: {x.get('ai_requirements_summary') or ''}\n"
                   f"SKILLS: {', '.join((x.get('ai_key_skills') or [])[:12])}\n"
                   f"FLAGS (regex scan of full JD): {flags(d) or 'none'}\n"
                   f"JD: {d[:2400]}\n\n")
    json.dump(mp, open(path(a, f"map_{a.run}.json"), "w"))
    n = 0
    for b in range(0, len(out), a.size):
        open(path(a, f"screen/batch_{a.run}_{n}.txt"), "w").write("".join(out[b:b + a.size]))
        print(f"screen/batch_{a.run}_{n}.txt  {mp[b]['k']}..{mp[min(b + a.size, len(mp)) - 1]['k']}")
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
                v[p[0]] = (p[2], int(p[1]), p[3])
    return v


def cmd_final(a):
    rows = json.load(open(path(a, f"towrite_{a.run}.json")))
    mp = {m["sid"]: m["k"] for m in json.load(open(path(a, f"map_{a.run}.json")))}
    v = load_verdicts(a)
    missing = [k for k in mp.values() if k not in v]
    if missing:
        sys.exit(f"no verdict for {missing}")
    for r in rows:
        vd, sc, why = v[mp[r["Source Job ID"]]]
        if vd == "Pursue" and sc < 75 or vd == "Skip" and sc >= 60:
            print(f"WARN score/verdict mismatch {mp[r['Source Job ID']]} {vd} {sc}")
        r["Triage"], r["ATS Score"], r["Triage Reason"] = vd, sc, why[:2000]
    json.dump(rows, open(path(a, f"final_{a.run}.json"), "w"), ensure_ascii=False)
    print(f"final rows {len(rows)} {dict(collections.Counter(r['Triage'] for r in rows))}")
    for r in sorted(rows, key=lambda r: -r["ATS Score"]):
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
    """--got holds the SQL group_concat of "sid:Triage:ATS Score" joined by '|'."""
    got = {}
    for x in open(a.got).read().strip().split("|"):
        p = x.split(":")
        if len(p) >= 3:
            got[p[0]] = (p[1], p[2].split(".")[0])
    rows = json.load(open(path(a, f"final_{a.run}.json")))
    want = {r["Source Job ID"]: (r["Triage"], str(r["ATS Score"])) for r in rows}
    missing = sorted(set(want) - set(got))
    extra = sorted(set(got) - set(want))
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
            w.writerow(["sid", "dedup_key", "company", "role", "run", "written"])
        for r in new:
            w.writerow([r["Source Job ID"], r["Dedup Key"], r["Company"], r["Role"], a.run, r["Fetched"]])
    print(f"ledger +{len(new)} rows -> {len(ledger) + len(new)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.environ.get("INTAKE_DIR", "./intake_work"))
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name in ["fetch", "final", "ledger-add", "live-sql"]:
        sp.add_parser(name).add_argument("run")
    p = sp.add_parser("prepare"); p.add_argument("run"); p.add_argument("--date", required=True)
    p = sp.add_parser("dedup"); p.add_argument("run"); p.add_argument("--live", required=True)
    p = sp.add_parser("batches"); p.add_argument("run"); p.add_argument("--size", type=int, default=26)
    p = sp.add_parser("show"); p.add_argument("run"); p.add_argument("i", type=int); p.add_argument("j", type=int)
    p = sp.add_parser("verify"); p.add_argument("run"); p.add_argument("--got", required=True)
    a = ap.parse_args()
    {"fetch": cmd_fetch, "prepare": cmd_prepare, "dedup": cmd_dedup, "batches": cmd_batches,
     "final": cmd_final, "live-sql": cmd_live_sql, "show": cmd_show, "verify": cmd_verify, "ledger-add": cmd_ledger_add}[a.cmd](a)


if __name__ == "__main__":
    main()
