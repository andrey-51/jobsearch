"""Write prepared Role Intake rows via the Notion REST API. Resumable."""
import os, re, json, time, sys, urllib.request, urllib.error

TOKEN = os.environ["Notion_KEY"]
DS    = "441379e4-d36a-4d53-b834-57242e0dafb3"   # Role Intake ONLY
VER   = "2025-09-03"
assert DS == "441379e4-d36a-4d53-b834-57242e0dafb3", "refuse to write anywhere else"

def api(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request("https://api.notion.com/v1"+path, data=data, method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Notion-Version": VER,
                 "Content-Type": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt); continue
            return e.code, json.loads(body)
        except Exception:
            time.sleep(2 ** attempt)
    return "ERR", {"message": "retries exhausted"}

# ---------- markdown -> rich_text ----------
TOK = re.compile(r"(\*\*.+?\*\*|_[^_\n]+?_)", re.S)

def rt(text, link=None):
    """Split text into <=2000-char rich_text spans, honouring ** and _ markers."""
    out = []
    for piece in TOK.split(text):
        if not piece: continue
        bold = italic = False
        if piece.startswith("**") and piece.endswith("**") and len(piece) > 4:
            piece, bold = piece[2:-2], True
        elif piece.startswith("_") and piece.endswith("_") and len(piece) > 2:
            piece, italic = piece[1:-1], True
        piece = piece.replace("\\", "")          # body was escaped for the MCP tool
        for i in range(0, len(piece), 1900):
            seg = piece[i:i+1900]
            if not seg: continue
            o = {"type": "text", "text": {"content": seg}}
            if bold or italic:
                o["annotations"] = {"bold": bold, "italic": italic}
            out.append(o)
    return out or [{"type": "text", "text": {"content": ""}}]

def para(text):   return {"object":"block","type":"paragraph","paragraph":{"rich_text":rt(text)}}
def h2(text):     return {"object":"block","type":"heading_2","heading_2":{"rich_text":rt(text)}}
def bullet(text): return {"object":"block","type":"bulleted_list_item","bulleted_list_item":{"rich_text":rt(text)}}

CELL = re.compile(r"<td>(.*?)</td>", re.S)
ROW  = re.compile(r"<tr>(.*?)</tr>", re.S)

def table_block(xml):
    rows = [CELL.findall(r) for r in ROW.findall(xml)]
    rows = [r for r in rows if r]
    if not rows: return None
    w = max(len(r) for r in rows)
    children = []
    for r in rows:
        cells = [rt(c.strip()) for c in r] + [rt("")] * (w - len(r))
        children.append({"object":"block","type":"table_row","table_row":{"cells":cells}})
    return {"object":"block","type":"table","table":{
        "table_width": w, "has_column_header": True, "has_row_header": False,
        "children": children}}

def to_blocks(body):
    blocks, buf = [], []
    def flush():
        if buf:
            txt = "\n".join(buf).strip()
            if txt: blocks.append(para(txt))
            buf.clear()
    i, lines = 0, body.split("\n")
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("<table"):
            flush()
            chunk = []
            while i < len(lines):
                chunk.append(lines[i])
                if "</table>" in lines[i]: break
                i += 1
            tb = table_block("\n".join(chunk))
            if tb: blocks.append(tb)
        elif ln.startswith("## "):
            flush(); blocks.append(h2(ln[3:].strip()))
        elif ln.startswith("- "):
            flush(); blocks.append(bullet(ln[2:].strip()))
        elif ln.strip() == "":
            flush()
        else:
            buf.append(ln)
        i += 1
    flush()
    return blocks

# ---------- properties ----------
def props(r):
    """Role Intake properties. Machine Verdict and Rubric Version were removed from the schema on 2026-10-04."""
    def txt(v): return {"rich_text":[{"type":"text","text":{"content":str(v)[:2000]}}]} if str(v or "") else {"rich_text":[]}
    p = {
        "Role":            {"title":[{"type":"text","text":{"content":r["Role"][:2000]}}]},
        "Company":         txt(r["Company"]),
        "Feed":            {"select":{"name":r["Feed"]}},
        "Source Job ID":   txt(r["Source Job ID"]),
        "Location":        txt(r["Location"]),
        "Work Mode":       {"select":{"name":r["Work Mode"]}},
        "Org Industry":    txt(r["Org Industry"]),
        "Org Headcount":   txt(r["Org Headcount"]),
        "Salary":          txt(r["Salary"]),
        "Experience Level":{"select":{"name":r["Experience Level"]}},
        "Fit Score":       {"number": r["Fit Score"]},
        "Hard Fail Reason":{"select":{"name":r["Hard Fail Reason"]}},
        "Watchlist":       {"checkbox": bool(r["Watchlist"])},
        "Dedup Key":       txt(r["Dedup Key"]),
        "Duplicate":       {"checkbox": False},
        "Intake Status":   {"select":{"name":r["Intake Status"]}},
        "Posted":          {"date":{"start":r["Posted"]}} if r.get("Posted") else {"date":None},
        "Fetched":         {"date":{"start":r["Fetched"]}} if r.get("Fetched") else {"date":None},
    }
    if r.get("Job URL"): p["Job URL"] = {"url": r["Job URL"]}
    if r.get("Triage"):
        p["Triage"] = {"select":{"name":r["Triage"]}}
        p["ATS Score"] = {"number": r["ATS Score"]}
        p["Triage Reason"] = txt(r["Triage Reason"])
    return p

def write_row(r):
    blocks = to_blocks(r["body"])
    st, resp = api("POST", "/pages", {
        "parent": {"type": "data_source_id", "data_source_id": DS},
        "properties": props(r),
        "children": blocks[:100],
    })
    if st != 200:
        return False, f"{st} {resp.get('code')} {str(resp.get('message'))[:200]}", None
    pid = resp["id"]
    for i in range(100, len(blocks), 100):
        st2, resp2 = api("PATCH", f"/blocks/{pid}/children", {"children": blocks[i:i+100]})
        if st2 != 200:
            return False, f"append {st2} {resp2.get('code')} {str(resp2.get('message'))[:200]}", pid
    return True, pid, pid

if __name__ == "__main__":
    # usage: python3 nwrite.py <final_rows.json> <log.txt> <lo> <hi>
    # final_rows.json comes from `intake.py final`: rows with Triage merged in.
    rows = json.load(open(sys.argv[1])); logf = sys.argv[2]
    lo, hi = int(sys.argv[3]), int(sys.argv[4])
    done = set()
    try:
        for l in open(logf):
            if l.strip(): done.add(l.split()[0])
    except FileNotFoundError: pass
    log = open(logf, "a")
    ok = fail = skip = 0
    for r in rows[lo:hi]:
        sid = r["Source Job ID"]
        if sid in done: skip += 1; continue
        good, info, pid = write_row(r)
        if good:
            log.write(f"{sid} {info}\n"); log.flush(); ok += 1
        else:
            # a failed append can leave a partial page: report its id so it can be archived, never retried blindly
            print(f"FAIL {sid} {r['Company'][:28]}: {info} partial_page={pid}", flush=True); fail += 1
            if fail >= 5:
                print("5 failures, stopping", flush=True); break
        time.sleep(0.34)
    print(f"range[{lo}:{hi}] ok={ok} fail={fail} skipped={skip}")
