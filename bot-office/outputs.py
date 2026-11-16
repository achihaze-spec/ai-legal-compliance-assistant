"""Save each compliance case to a Google Drive folder.

Uses the folder that "Google Drive for desktop" syncs on the Mac (e.g.
~/Library/CloudStorage/GoogleDrive-you@gmail.com/My Drive/<folder>), so no API key or
login is needed: files written there upload to Drive by themselves.

One subfolder per case, named "dd.mm.yy_Merchant name", holding:
  <dd.mm.yy_Name>_<KIND>.docx  readable report (opens in Drive / Google Docs)
  <dd.mm.yy_Name>_<KIND>.html  full report with clickable searches
  <dd.mm.yy_Name>_<KIND>.json  raw results (audit trail)
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import veo  # settings store


def _safe(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", name).strip()
    return re.sub(r"\s+", " ", name)[:80] or "Unnamed"


def drive_root() -> Path | None:
    p = veo.load().get("drive_folder", "").strip()
    if not p:
        return None
    root = Path(p).expanduser()
    return root if root.is_dir() else None


def detect() -> list[str]:
    """Candidate folders inside Google Drive for desktop (My Drive and Shared drives, 2 levels)."""
    found = []
    for base in sorted(Path.home().glob("Library/CloudStorage/GoogleDrive-*")) + [Path.home() / "Google Drive"]:
        for top in ("My Drive", "Shared drives", ""):
            d = base / top if top else base
            if not d.is_dir():
                continue
            for child in sorted(d.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    found.append(str(child))
                    if top == "Shared drives":
                        found += [str(g) for g in sorted(child.iterdir()) if g.is_dir() and not g.name.startswith(".")][:30]
    return found[:200]


def case_folder(merchant: str, when: dt.date | None = None) -> Path | None:
    root = drive_root()
    if not root:
        return None
    folder = root / f"{(when or dt.date.today()):%d.%m.%y}_{_safe(merchant)}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def save_case(merchant: str, kind: str, result: dict, html: str, extra_files: list | None = None) -> Path | None:
    """Writes docx + html + json for one case. Returns the folder, or None if no Drive folder is set."""
    folder = case_folder(merchant)
    if not folder:
        return None
    stem = f"{folder.name}_{kind}"  # the date's dots are not an extension, so build names as strings
    (folder / f"{stem}.html").write_text(html, encoding="utf-8")
    (folder / f"{stem}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    try:
        _docx(result, kind, merchant, folder / f"{stem}.docx")
    except Exception as exc:  # the html/json are still there
        (folder / "docx_error.txt").write_text(str(exc))
    for item in extra_files or []:  # Path, or (Path, name to save as)
        src, dest_name = item if isinstance(item, tuple) else (item, item.name)
        if Path(src).exists():
            (folder / _safe(dest_name)).write_bytes(Path(src).read_bytes())
    return folder


# ───────────────────────── Word report ─────────────────────────

def _docx(r: dict, kind: str, merchant: str, out: Path) -> None:
    from docx import Document
    from docx.shared import Pt, RGBColor

    doc = Document()
    doc.styles["Normal"].font.name = "Arial"
    doc.styles["Normal"].font.size = Pt(10)
    doc.add_heading(f"{kind}: {merchant}", 0)
    p = doc.add_paragraph()
    run = p.add_run(f"Outcome: {r.get('outcome') or r.get('rating', '')}")
    run.bold = True
    red = (r.get("outcome") in ("STOP", "REJECT", "ESCALATE")) or r.get("rating") == "HIGH"
    run.font.color.rgb = RGBColor(0xC0, 0x1F, 0x3A) if red else RGBColor(0x1F, 0x7A, 0x4D)
    if r.get("why"):
        doc.add_paragraph(r["why"])
    if r.get("outcome") == "STOP":
        doc.add_paragraph("STOP. Escalate to the MLRO now. Do not tip off the customer.").runs[0].bold = True
    doc.add_paragraph(f"Prepared {dt.datetime.now():%d %b %Y %H:%M} by the Bot Office compliance bots. "
                      "Suggested dispositions only: the analyst / MLRO confirms.")

    def table(headers, rows):
        t = doc.add_table(rows=1, cols=len(headers))
        t.style = "Light Grid Accent 1"
        for i, h in enumerate(headers):
            t.rows[0].cells[i].text = str(h)
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = str(v)

    if "screen" in r:
        s = r["screen"]
        doc.add_heading("Sanctions screening (OFAC, UN, EU, UK)", 1)
        table(["List", "Status", "Records", "Version / SHA-256"],
              [[l["source"], "OK" if l["status"] == "ok" else "FAILED: Analyst to run", l.get("records", 0),
                "; ".join(f"{f.get('obtained', '')} {f.get('sha256', '')[:16]}" for f in l["files"] if f.get("sha256"))[:120]]
               for l in s["lists"]])
        doc.add_paragraph(f"Run {s.get('run', '')}. Name threshold {s.get('min_score', 85)}.")
        rows = []
        for name, hits in s["results"].items():
            if not hits:
                rows.append([name, "-", "-", "No hit"])
            for h in hits:
                rows.append([name, f"{h['hit_name']} ({h['source']} #{h['list_id']})", h["name_score"],
                             f"{h['suggested_disposition']}: {h['reason']}"])
        table(["Subject", "Hit", "Score", "Suggested disposition"], rows)
    if r.get("fatf") is not None and "fatf_info" in r:
        doc.add_heading("FATF", 1)
        doc.add_paragraph((", ".join(r["fatf"]).upper() + " list" if r["fatf"] else "Not on the black or grey list")
                          + f" (FATF lists as of {r['fatf_info']['updated']}; confirm on the live FATF list).")
    for label, key in (("Missing items", "missing"), ("Red flags in the document", "flags"), ("Key obligations", "obligations")):
        if r.get(key):
            doc.add_heading(label, 1)
            for x in r[key]:
                doc.add_paragraph(str(x), style="List Bullet")
    if r.get("red"):
        doc.add_heading("Red flags", 1)
        for x in r["red"]:
            doc.add_paragraph(x, style="List Bullet")
    if r.get("mrz") and not r["mrz"].get("error"):
        m = r["mrz"]
        doc.add_heading("MRZ check", 1)
        doc.add_paragraph(f"Format {m.get('format')}: {m.get('overall')}. A pass shows consistency only, not authenticity.")
        if m.get("checks"):
            table(["Field", "Given", "Calculated", "Result"], [[c["field"], c["given"], c["calculated"], c["result"]] for c in m["checks"]])
    u = r.get("ubo")
    if u and u.get("json"):
        j = u["json"]
        doc.add_heading(f"Beneficial ownership (threshold {j.get('threshold')}%)", 1)
        table(["Name", "Type", "Direct", "Indirect", "Total", "UBO"],
              [[x["name"], x["type"], f"{x['direct_pct']:.2f}%", f"{x['indirect_pct']:.2f}%", f"{x['total_pct']:.2f}%", "Yes" if x["ubo"] else "No"]
               for x in j["rows"]])
        for x in j["rows"]:
            for w in x["working"]:
                doc.add_paragraph(w, style="List Bullet")
        o = j.get("ofac", {})
        doc.add_paragraph(f"OFAC 50% Rule: {'BLOCKED' if o.get('subject_blocked') else 'not blocked'} "
                          f"({o.get('subject_aggregate_pct', 0):.0f}% held by sanctioned parties on the inputs given).")
        doc.add_paragraph("Percentages were declared in the KYB form: verify against the GIS / share register.")
    di = r.get("documents")
    if di:
        doc.add_heading(f"Documents from Drive ({len(di['files'])} files, via {di['via']})", 1)
        for n in di.get("notes", []):
            doc.add_paragraph(n)
        table(["Checklist item", "Status", "File(s)"], [[c["item"], c["status"] if c["status"] == "Received" else "Missing: RFI",
                                                          ", ".join(c["files"])] for c in di["checklist"]])
        for x in di.get("issues", []):
            doc.add_paragraph(x, style="List Bullet")
        for m in r.get("mrz_checks", []):
            doc.add_paragraph(f"MRZ in {m['file']}: {(m['result'] or {}).get('overall') or (m['result'] or {}).get('error', '')}", style="List Bullet")
        doc.add_heading("Document inventory", 2)
        table(["File", "Detected as", "Drive ID", "Last modified", "Notes"],
              [[x["name"], x["type"], x.get("drive_id") or "-", x.get("modified") or "-", x.get("note", "")] for x in di["files"]])
        doc.add_paragraph("Review based on the file versions listed above (Drive ID and last-modified time).")
    elif r.get("docs"):
        doc.add_heading("Document checklist", 1)
        for x in r["docs"]:
            doc.add_paragraph(f"☐ {x}")
    url = r.get("url") if kind != "URL" else r
    if url and url.get("facts"):
        doc.add_heading(f"Website: {url['url']} ({url['rating']})", 1)
        for f in url["findings"]:
            doc.add_paragraph(f"[{f['level'].upper()}] {f['msg']}", style="List Bullet")
        f = url["facts"]
        who = f.get("whois", {})
        table(["Check", "Result"], [["Final URL", f.get("final_url", "")], ["HTTPS", "yes" if f.get("https") else "no"],
                                    ["Domain registered", f"{who.get('created', '?')} ({who.get('age_days', '?')} days)" if "error" not in who else "Analyst to run"],
                                    ["First archived", f.get("first_archived") or "none / Analyst to run"],
                                    ["Business name on site", f.get("name_match", "-")]])
        for a in url.get("analyst", []):
            doc.add_paragraph(f"☐ {a}")
    if r.get("searches"):
        doc.add_heading("PEP, adverse media and other lists (Analyst to run)", 1)
        for name, links in r["searches"].items():
            doc.add_paragraph(name).runs[0].bold = True
            for l in links:
                doc.add_paragraph(f"☐ [{l['group']}] {l['label']}: {l['url']}", style="List Bullet")
    doc.save(out)
