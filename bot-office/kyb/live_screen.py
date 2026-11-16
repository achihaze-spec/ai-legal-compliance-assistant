#!/usr/bin/env python3
"""Live checks: screen names against the free official sanctions lists.

Sources (official publishers only):
  OFAC  SDN and Consolidated (non-SDN) lists, US Treasury Sanctions List Service
  UN    Security Council Consolidated List (XML)
  EU    Consolidated Financial Sanctions List (FSF CSV)
  UK    UK Sanctions List (FCDO CSV)

Every download is logged with URL, UTC time, size and SHA-256 so the review can prove which
list version was used. If a download is blocked or fails, that source is reported as
"Analyst to run". If the analyst has saved the official files (for example in the merchant
Drive folder), use --from-dir to screen against those files instead of downloading.

Input JSON: {"subjects": [{"name": "...", "type": "person|entity", "dob": "...",
             "nationality": "...", "country": "...", "aliases": [...]}, ...]}

Usage:
  python3 live_screen.py subjects.json --out results_dir [--sources ofac,un,eu,uk]
                         [--from-dir saved_lists_dir] [--min-score 85]
Outputs results_dir/live_screening.md, results_dir/live_screening.json, results_dir/lists/*
"""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(__file__))
from kyb_common import fold, name_score, md_table  # noqa: E402
from name_match import assess  # noqa: E402

SOURCES = {
    "ofac": {
        "label": "OFAC SDN + Consolidated (non-SDN)",
        "files": {
            "SDN.CSV": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV",
            "ALT.CSV": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/ALT.CSV",
            "ADD.CSV": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/ADD.CSV",
            "CONS_PRIM.CSV": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/CONS_PRIM.CSV",
            "CONS_ALT.CSV": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/CONS_ALT.CSV",
        },
        "required": ["SDN.CSV"],
    },
    "un": {
        "label": "UN Security Council Consolidated List",
        "files": {"un_consolidated.xml": "https://scsanctions.un.org/resources/xml/en/consolidated.xml"},
        "required": ["un_consolidated.xml"],
    },
    "eu": {
        "label": "EU Consolidated Financial Sanctions List",
        "files": {"eu_fsf.csv": "https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw"},
        "required": ["eu_fsf.csv"],
    },
    "uk": {
        "label": "UK Sanctions List (FCDO)",
        "files": {"uk_sanctions_list.csv": "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv"},
        "required": ["uk_sanctions_list.csv"],
    },
}


def now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def fetch(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "BotOffice-KYB-screening/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as fh:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            fh.write(chunk)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def nul(v):
    v = (v or "").strip()
    return "" if v in ("-0-", "-0- ") else v


# ---------- parsers: each returns list of records ----------
# record = {"source", "list_id", "name", "aliases", "type", "dob", "nationality", "country", "programme"}

def parse_ofac(d):
    recs = {}
    remark_dob = re.compile(r"DOB ([^;]+?)(?:;|$)", re.I)
    remark_nat = re.compile(r"(?:nationality|citizen) ([^;]+?)(?:;|$)", re.I)
    for prim, alt, label in (("SDN.CSV", "ALT.CSV", "OFAC SDN"), ("CONS_PRIM.CSV", "CONS_ALT.CSV", "OFAC Consolidated")):
        p = os.path.join(d, prim)
        if not os.path.exists(p):
            continue
        for row in csv.reader(io.StringIO(read_text(p))):
            if len(row) < 12 or not row[0].strip().isdigit():
                continue
            ent, name, typ, prog, remarks = row[0].strip(), nul(row[1]), nul(row[2]).lower(), nul(row[3]), nul(row[11])
            dob = remark_dob.search(remarks)
            nat = remark_nat.findall(remarks)
            recs[(label, ent)] = {"source": label, "list_id": ent, "name": name, "aliases": [],
                                  "type": "person" if typ == "individual" else "entity",
                                  "dob": dob.group(1).strip() if dob else "", "nationality": [n.strip() for n in nat],
                                  "country": "", "programme": prog}
        a = os.path.join(d, alt)
        if os.path.exists(a):
            for row in csv.reader(io.StringIO(read_text(a))):
                if len(row) >= 4 and (label, row[0].strip()) in recs:
                    recs[(label, row[0].strip())]["aliases"].append(nul(row[3]))
    add = os.path.join(d, "ADD.CSV")
    if os.path.exists(add):
        for row in csv.reader(io.StringIO(read_text(add))):
            if len(row) >= 6 and ("OFAC SDN", row[0].strip()) in recs:
                r = recs[("OFAC SDN", row[0].strip())]
                r["country"] = r["country"] or nul(row[5])
    return list(recs.values())


def parse_un(d):
    p = os.path.join(d, "un_consolidated.xml")
    root = ET.fromstring(read_text(p).encode("utf-8"))
    out = []

    def txt(el, tag):
        x = el.find(tag)
        return (x.text or "").strip() if x is not None and x.text else ""

    for ind in root.iter("INDIVIDUAL"):
        name = " ".join(filter(None, [txt(ind, t) for t in ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME")]))
        aliases = [txt(a, "ALIAS_NAME") for a in ind.iter("INDIVIDUAL_ALIAS") if txt(a, "ALIAS_NAME")]
        dobs = []
        for b in ind.iter("INDIVIDUAL_DATE_OF_BIRTH"):
            dobs.append(txt(b, "DATE") or txt(b, "YEAR") or
                        (f"{txt(b, 'FROM_YEAR')} {txt(b, 'TO_YEAR')}".strip()))
        nats = [v.text.strip() for n in ind.iter("NATIONALITY") for v in n.iter("VALUE") if v.text]
        out.append({"source": "UN", "list_id": txt(ind, "REFERENCE_NUMBER") or txt(ind, "DATAID"), "name": name,
                    "aliases": aliases, "type": "person", "dob": next((x for x in dobs if x), ""),
                    "nationality": nats, "country": "", "programme": txt(ind, "UN_LIST_TYPE")})
    for ent in root.iter("ENTITY"):
        aliases = [txt(a, "ALIAS_NAME") for a in ent.iter("ENTITY_ALIAS") if txt(a, "ALIAS_NAME")]
        countries = [txt(a, "COUNTRY") for a in ent.iter("ENTITY_ADDRESS") if txt(a, "COUNTRY")]
        out.append({"source": "UN", "list_id": txt(ent, "REFERENCE_NUMBER") or txt(ent, "DATAID"),
                    "name": txt(ent, "FIRST_NAME"), "aliases": aliases, "type": "entity", "dob": "",
                    "nationality": [], "country": countries[0] if countries else "", "programme": txt(ent, "UN_LIST_TYPE")})
    return out


def _col(header, *needles):
    for i, h in enumerate(header):
        hl = h.lower()
        if all(n in hl for n in needles):
            return i
    return None


def parse_eu(d):
    text = read_text(os.path.join(d, "eu_fsf.csv"))
    delim = ";" if text[:2000].count(";") > text[:2000].count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    hi = next(i for i, r in enumerate(rows) if any("logicalid" in c.lower() for c in r))
    h = rows[hi]
    c_id = _col(h, "entity_logicalid") or _col(h, "logicalid")
    c_name = _col(h, "namealias_wholename") or _col(h, "wholename")
    c_type = _col(h, "subjecttype_classificationcode") or _col(h, "subjecttype")
    c_dob = _col(h, "birthdate_birthdate") or _col(h, "birthdate")
    c_nat = _col(h, "citizenship_countrydescription") or _col(h, "citizenship")
    c_ctry = _col(h, "address_countrydescription")
    c_prog = _col(h, "regulation_programme") or _col(h, "programme")
    recs = {}
    for r in rows[hi + 1:]:
        if c_id is None or len(r) <= c_id or not r[c_id].strip():
            continue
        key = r[c_id].strip()
        g = lambda c: r[c].strip() if c is not None and c < len(r) else ""  # noqa: E731
        rec = recs.setdefault(key, {"source": "EU", "list_id": key, "name": "", "aliases": [], "type": "",
                                    "dob": "", "nationality": [], "country": "", "programme": ""})
        nm = g(c_name)
        if nm:
            if not rec["name"]:
                rec["name"] = nm
            elif nm not in rec["aliases"] and nm != rec["name"]:
                rec["aliases"].append(nm)
        t = g(c_type).lower()
        if t:
            rec["type"] = "person" if t.startswith("p") else "entity"
        rec["dob"] = rec["dob"] or g(c_dob)
        if g(c_nat) and g(c_nat) not in rec["nationality"]:
            rec["nationality"].append(g(c_nat))
        rec["country"] = rec["country"] or g(c_ctry)
        rec["programme"] = rec["programme"] or g(c_prog)
    return [r for r in recs.values() if r["name"]]


def parse_uk(d):
    rows = list(csv.reader(io.StringIO(read_text(os.path.join(d, "uk_sanctions_list.csv")))))
    hi = next(i for i, r in enumerate(rows) if any("unique id" in c.lower() for c in r))
    h = rows[hi]
    c_id = _col(h, "unique id")
    name_cols = [(_col(h, f"name {i}"), i) for i in (1, 2, 3, 4, 5, 6)]
    c_type = _col(h, "designation type") or _col(h, "entity type") or _col(h, "individual, entity")
    c_ntype = _col(h, "name type")
    c_dob = _col(h, "d.o.b") or _col(h, "birth")
    c_nat = _col(h, "nationalit")
    c_ctry = _col(h, "address country") or _col(h, "country")
    c_regime = _col(h, "regime")
    recs = {}
    for r in rows[hi + 1:]:
        if c_id is None or len(r) <= c_id or not r[c_id].strip():
            continue
        g = lambda c: r[c].strip() if c is not None and c < len(r) else ""  # noqa: E731
        parts = [g(c) for c, i in name_cols if i != 6] + [g(c) for c, i in name_cols if i == 6]
        nm = " ".join(p for p in parts if p)
        key = g(c_id)
        rec = recs.setdefault(key, {"source": "UK", "list_id": key, "name": "", "aliases": [], "type": "",
                                    "dob": "", "nationality": [], "country": "", "programme": g(c_regime)})
        primary = "primary" in g(c_ntype).lower() if c_ntype is not None else not rec["name"]
        if nm:
            if primary and not rec["name"]:
                rec["name"] = nm
            elif nm != rec["name"] and nm not in rec["aliases"]:
                rec["aliases"].append(nm)
        t = g(c_type).lower()
        if t:
            rec["type"] = "person" if "individual" in t else "entity"
        rec["dob"] = rec["dob"] or g(c_dob)
        if g(c_nat):
            rec["nationality"] += [x.strip() for x in re.split(r"[;,]|\(\d\)", g(c_nat)) if x.strip()]
        rec["country"] = rec["country"] or g(c_ctry)
    for rec in recs.values():
        if not rec["name"] and rec["aliases"]:
            rec["name"] = rec["aliases"].pop(0)
    return [r for r in recs.values() if r["name"]]


PARSERS = {"ofac": parse_ofac, "un": parse_un, "eu": parse_eu, "uk": parse_uk}


def prepare(source, list_dir, from_dir):
    meta = SOURCES[source]
    sdir = os.path.join(list_dir, source)
    os.makedirs(sdir, exist_ok=True)
    log = {"source": meta["label"], "status": "ok", "files": [], "records": 0, "note": ""}
    for fname, url in meta["files"].items():
        dest = os.path.join(sdir, fname)
        entry = {"file": fname, "url": url}
        try:
            if from_dir:
                src = os.path.join(from_dir, fname)
                if not os.path.exists(src):
                    raise FileNotFoundError(f"{fname} not in {from_dir}")
                with open(src, "rb") as a, open(dest, "wb") as b:
                    b.write(a.read())
                entry["obtained"] = f"analyst-saved file, copied {now()}"
            else:
                fetch(url, dest)
                entry["obtained"] = f"downloaded {now()}"
            entry["bytes"] = os.path.getsize(dest)
            entry["sha256"] = sha256(dest)
        except Exception as e:  # noqa: BLE001
            entry["error"] = f"{type(e).__name__}: {e}"
            if fname in meta["required"]:
                log["status"] = "failed"
        log["files"].append(entry)
    if log["status"] == "ok":
        try:
            recs = PARSERS[source](sdir)
            log["records"] = len(recs)
            if not recs:
                log["status"], log["note"] = "failed", "File parsed to 0 records; format may have changed."
            return log, recs
        except Exception as e:  # noqa: BLE001
            log["status"], log["note"] = "failed", f"Parse error {type(e).__name__}: {e}"
    return log, []


def index(records):
    idx = {}
    for i, r in enumerate(records):
        for n in [r["name"]] + r["aliases"]:
            for tok in fold(n).split():
                if len(tok) >= 3:
                    idx.setdefault(tok[:4], set()).add(i)
    return idx


def screen(subject, records, idx, min_score):
    entity = subject.get("type") == "entity"
    names = [subject["name"]] + subject.get("aliases", [])
    cand = set()
    for n in names:
        for tok in fold(n).split():
            if len(tok) >= 3:
                cand |= idx.get(tok[:4], set())
    hits = []
    for i in cand:
        r = records[i]
        if r["type"] and r["type"] != ("entity" if entity else "person"):
            continue
        best, best_name = 0, r["name"]
        for rn in [r["name"]] + r["aliases"]:
            for sn in names:
                s = name_score(sn, rn, entity)
                if s > best:
                    best, best_name = s, rn
        if best >= min_score:
            hit = {"source": r["source"], "list_id": r["list_id"], "hit_name": best_name,
                   "dob": r["dob"], "nationality": r["nationality"] or r["country"], "country": r["country"],
                   "programme": r["programme"]}
            a = assess(subject, hit)
            a["programme"] = r["programme"]
            hits.append(a)
    hits.sort(key=lambda h: -h["name_score"])
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("subjects")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sources", default="ofac,un,eu,uk")
    ap.add_argument("--from-dir", help="folder with analyst-saved official list files (same file names)")
    ap.add_argument("--min-score", type=float, default=85)
    a = ap.parse_args()
    with open(a.subjects, encoding="utf-8") as fh:
        subjects = json.load(fh)["subjects"]
    os.makedirs(a.out, exist_ok=True)
    list_dir = os.path.join(a.out, "lists")
    logs, results = [], {s["name"]: [] for s in subjects}
    for src in [s.strip() for s in a.sources.split(",") if s.strip()]:
        log, recs = prepare(src, list_dir, a.from_dir)
        logs.append(log)
        if not recs:
            continue
        idx = index(recs)
        for s in subjects:
            results[s["name"]] += screen(s, recs, idx, a.min_score)

    md = ["## Live sanctions screening", f"Run: {now()}. Name threshold {a.min_score}. Official lists only.", "",
          "### List versions used"]
    rows = []
    for lg in logs:
        if lg["status"] == "ok":
            for f in lg["files"]:
                if "sha256" in f:
                    rows.append([lg["source"], f["file"], f["obtained"], f["bytes"], f["sha256"][:16] + "...", lg["records"]])
        else:
            errs = "; ".join(f.get("error", "") for f in lg["files"] if f.get("error")) or lg["note"]
            rows.append([lg["source"], "-", "FAILED: Analyst to run", "-", errs[:120], 0])
    md.append(md_table(["Source", "File", "Obtained", "Bytes", "SHA-256", "Records"], rows))
    md += ["", "### Results"]
    for s in subjects:
        hits = results[s["name"]]
        ran = [lg["source"] for lg in logs if lg["status"] == "ok"]
        if not hits:
            md.append(f"- **{s['name']}**: no hit at {a.min_score}+ on {', '.join(ran) or 'no source'}.")
            continue
        md += [f"- **{s['name']}**: {len(hits)} potential hit(s).", ""]
        md.append(md_table(["Source", "List ID", "Hit", "Programme", "Name score", "Strong IDs", "Suggested", "Reason"],
                           [[h["source"], h["list_id"], h["hit_name"], h.get("programme", ""), h["name_score"],
                             ", ".join(h["strong_matched"]) or "-", h["suggested_disposition"], h["reason"]] for h in hits]))
        for h in hits:
            md += ["", f"Identifiers for {h['source']} {h['list_id']}:",
                   md_table(["Identifier", "Subject", "Hit", "Result"], h["identifiers"])]
    failed = [lg["source"] for lg in logs if lg["status"] != "ok"]
    if failed:
        md += ["", "Not screened (Analyst to run): " + ", ".join(failed) + "."]
    md.append("\nNot covered by live mode: PEP, adverse media, AMLC and other local lists, OpenSanctions. These stay Analyst to run.")
    with open(os.path.join(a.out, "live_screening.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))
    with open(os.path.join(a.out, "live_screening.json"), "w", encoding="utf-8") as fh:
        json.dump({"run": now(), "min_score": a.min_score, "lists": logs, "results": results}, fh, indent=2)
    print("\n".join(md))


if __name__ == "__main__":
    main()
