"""KYC / KYB / sanctions-PEP-adverse-media orchestration for the compliance bots.

Uses the kyb/ toolkit scripts (copied from the evercrest-kyb plugin):
  live_screen.py  OFAC SDN + Consolidated, UN, EU, UK official lists (cached for 24 h, versions logged)
  name_match.py   fuzzy name + "2 strong identifiers" rule -> suggested disposition
  bo_calc.py      indirect ownership, UBO threshold (25% / 10%), OFAC 50% Rule
  mrz_check.py    ICAO 9303 check digits
PEP and adverse media have no free authoritative source, so the bots build ready-to-click
searches from the SOP search library (incl. local-language terms) and mark them Analyst to run.

Dispositions are always "suggested". A suggested sanctions True Match => STOP, escalate to the
MLRO, no tip-off.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

HERE = Path(__file__).resolve().parent
KYB = HERE / "kyb"
LIST_FILES = {"ofac": ["SDN.CSV", "ALT.CSV", "ADD.CSV", "CONS_PRIM.CSV", "CONS_ALT.CSV"], "un": ["un_consolidated.xml"],
              "eu": ["eu_fsf.csv"], "uk": ["uk_sanctions_list.csv"]}
CACHE_HOURS = 24


def _run(script: str, *args: str, timeout: int = 900) -> str:
    p = subprocess.run([sys.executable, str(KYB / script), *args], capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"{script}: {p.stderr.strip()[-300:]}")
    return p.stdout


# ───────────────────────── FATF ─────────────────────────
ALIASES = {"bvi": "virgin islands", "british virgin islands": "virgin islands", "north korea": "dprk",
           "democratic people's republic of korea": "dprk", "laos": "lao pdr", "ivory coast": "côte d'ivoire",
           "cote d'ivoire": "côte d'ivoire", "drc": "democratic republic of the congo", "burma": "myanmar"}


def _fatf_lists() -> dict:
    text = (KYB / "fatf-list.md").read_text(encoding="utf-8")
    m = re.search(r"\*\*Last updated:\*\*\s*([^(\n]+)", text)
    updated = m.group(1).strip() if m else "?"
    black = re.search(r"black list\)(.*?)##", text, re.S | re.I)
    grey = re.search(r"grey list\)[^\n]*\n(.*?)(?:\nRemoved|##)", text, re.S | re.I)
    clean = lambda block: [re.sub(r"\s*\(.*?\)", "", l[2:]).strip().lower() for l in block.group(1).splitlines() if l.startswith("- ")] if block else []
    black_l, grey_l = clean(black), clean(grey)
    black_l = ["dprk" if "dprk" in b or "korea" in b else b for b in black_l]
    try:
        age = (dt.date.today() - dt.datetime.strptime(updated, "%d %B %Y").date()).days
    except ValueError:
        age = None
    return {"black": black_l, "grey": grey_l, "updated": updated, "stale": age is None or age > 125}


def fatf(country: str) -> str | None:
    if not country:
        return None
    c = re.sub(r"\s*\(.*?\)", "", country.strip().lower())
    c = ALIASES.get(c, c)
    L = _fatf_lists()
    if c in L["black"]:
        return "black"
    if c in L["grey"]:
        return "grey"
    return None


# ───────────────────────── sanctions (live, cached) ─────────────────────────

def screen(subjects: list[dict], out_dir: Path, cache: Path) -> dict:
    """Screens subjects on OFAC/UN/EU/UK. A list downloaded in the last 24 h is reused from the cache;
    the others are downloaded now (and cached if the download worked)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    subj_file = out_dir / "subjects.json"
    subj_file.write_text(json.dumps({"subjects": subjects}, ensure_ascii=False))
    is_fresh = lambda src: all((cache / f).exists() and time.time() - (cache / f).stat().st_mtime < CACHE_HOURS * 3600
                               for f in LIST_FILES[src][:1])
    fresh = [s for s in LIST_FILES if is_fresh(s)]
    stale = [s for s in LIST_FILES if s not in fresh]
    merged = {"run": "", "min_score": 85, "lists": [], "results": {s["name"]: [] for s in subjects}}
    for group, extra in ((fresh, ["--from-dir", str(cache)]), (stale, [])):
        if not group:
            continue
        run_dir = out_dir / ("cached" if extra else "download")
        _run("live_screen.py", str(subj_file), "--out", str(run_dir), "--sources", ",".join(group), *extra)
        data = json.loads((run_dir / "live_screening.json").read_text(encoding="utf-8"))
        merged["run"], merged["min_score"] = data["run"], data["min_score"]
        for lg in data["lists"]:
            lg["cached"] = bool(extra)
        merged["lists"] += data["lists"]
        for name, hits in data["results"].items():
            merged["results"].setdefault(name, []).extend(hits)
        if not extra:  # cache whatever downloaded fine
            for src in group:
                for f in LIST_FILES[src]:
                    p = run_dir / "lists" / src / f
                    if p.exists() and p.stat().st_size > 0:
                        shutil.copy(p, cache / f)
        shutil.rmtree(run_dir / "lists", ignore_errors=True)
    merged["from_cache"] = bool(fresh)
    return merged


# ───────────────────────── PEP / adverse media searches ─────────────────────────

def _local_terms() -> list[tuple[str, str]]:
    rows = []
    for line in (KYB / "search-strings.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0] not in ("Language", "---") and not cells[0].startswith("-"):
            rows.append((cells[1].lower(), cells[2]))
    return rows


def searches(name: str, country: str = "", entity: bool = False) -> list[dict]:
    """Ready-to-click searches from the SOP library (Analyst to run)."""
    g = lambda q: "https://www.google.com/search?tbm=nws&q=" + quote_plus(q)
    gw = lambda q: "https://www.google.com/search?q=" + quote_plus(q)
    n = f'"{name}"'
    out = [
        {"group": "Adverse media", "label": "Fraud / laundering", "url": g(f'{n} AND (fraud OR scam OR "money laundering" OR embezzlement)')},
        {"group": "Adverse media", "label": "Bribery / corruption / tax", "url": g(f'{n} AND (bribery OR corruption OR kickback OR "tax evasion")')},
        {"group": "Adverse media", "label": "Sanctions / terrorism", "url": g(f'{n} AND (sanction OR OFAC OR terrorist OR "terrorism financing")')},
        {"group": "Adverse media", "label": "Arrest / court", "url": g(f'{n} AND (arrest OR charged OR convicted OR indicted OR lawsuit OR investigation)')},
        {"group": "Adverse media", "label": "Regulator / fines", "url": g(f'{n} AND (regulator OR fine OR penalty OR "cease and desist" OR "license revoked")')},
    ]
    if country:
        for where, terms in _local_terms():
            if country.lower() in where or (country.lower() in ("ph", "phl") and "philippines" in where):
                out.append({"group": "Adverse media", "label": f"Local language ({country})", "url": g(f"{n} AND ({terms})")})
                break
    if not entity:
        out += [{"group": "PEP", "label": "Public office", "url": gw(f'{n} AND (minister OR mayor OR governor OR senator OR congressman OR ambassador OR judge)')},
                {"group": "PEP", "label": "OpenSanctions (PEP + sanctions, lead only)", "url": "https://www.opensanctions.org/search/?q=" + quote_plus(name)}]
    else:
        out += [{"group": "Registry", "label": "OpenCorporates", "url": "https://opencorporates.com/companies?q=" + quote_plus(name)},
                {"group": "Registry", "label": "OpenSanctions", "url": "https://www.opensanctions.org/search/?q=" + quote_plus(name)}]
    out += [{"group": "Lists", "label": "AMLC sanctions / designations (PH)", "url": "https://www.amlc.gov.ph/"},
            {"group": "Lists", "label": "ICIJ Offshore Leaks", "url": "https://offshoreleaks.icij.org/search?q=" + quote_plus(name)},
            {"group": "Lists", "label": "OFAC search (manual)", "url": "https://sanctionssearch.ofac.treas.gov/"}]
    return out


# ───────────────────────── KYC (person) ─────────────────────────

def mrz(lines: list[str], name: str, dob: str, nationality: str) -> dict | None:
    lines = [l.strip().replace(" ", "") for l in lines if l.strip()]
    if not lines:
        return None
    args = []
    for l in lines:
        args += ["--line", l]
    for flag, v in (("--name", name), ("--dob", dob), ("--nationality", nationality)):
        if v:
            args += [flag, v]
    try:
        return json.loads(_run("mrz_check.py", *args, "--json"))
    except Exception as exc:
        return {"error": str(exc)}


def _disposition(results: list) -> tuple[str, list]:
    hits = [h for h in results]
    if any(h["suggested_disposition"].startswith("True Match") for h in hits):
        return "TRUE", hits
    if any(h["suggested_disposition"] == "Inconclusive" for h in hits):
        return "INCONCLUSIVE", hits
    return ("FP" if hits else "NONE"), hits


def decide(screen_res: dict, fatf_hits: list[str], extra_red: list[str], incomplete: list[str]) -> tuple[str, str]:
    """Overall outcome + one-line reason (also says which lists still need the analyst)."""
    outcome, why = _decide(screen_res, fatf_hits, extra_red, incomplete)
    if incomplete and outcome not in ("STOP", "REJECT", "INCOMPLETE"):
        why = why.rstrip(". ") + ". Hindi pa na-screen: " + ", ".join(incomplete) + " (Analyst to run)."
    return outcome, why


def _decide(screen_res: dict, fatf_hits: list[str], extra_red: list[str], incomplete: list[str]) -> tuple[str, str]:
    allhits = [h for hs in screen_res["results"].values() for h in hs] if screen_res else []
    if any(h["suggested_disposition"].startswith("True Match") for h in allhits):
        return "STOP", "Posibleng TRUE MATCH sa sanctions list: STOP, i-escalate sa MLRO agad, walang tip-off."
    if "black" in fatf_hits:
        return "REJECT", "Nasa FATF black list ang bansa."
    if extra_red:
        return "ESCALATE", "; ".join(extra_red)
    if any(h["suggested_disposition"] == "Inconclusive" for h in allhits):
        return "PENDING", "May inconclusive na hit: kailangan ng RFI para sa identifiers."
    if "grey" in fatf_hits:
        return "EDD", "Nasa FATF grey list: Enhanced Due Diligence at 10% UBO threshold."
    if incomplete:
        return "INCOMPLETE", "Hindi natapos ang ilang check: " + ", ".join(incomplete)
    return "CLEAR*", "Walang hit sa mga listahang na-screen. *Tapusin pa ang PEP at adverse media (Analyst to run)."


def kyc_person(d: dict, work: Path, cache: Path) -> dict:
    subj = {"name": d["name"].strip(), "type": "person", "dob": d.get("dob", ""), "nationality": d.get("nationality", ""),
            "address": d.get("address", ""), "id_number": d.get("id_number", ""),
            "aliases": [a.strip() for a in d.get("aliases", "").split(",") if a.strip()]}
    scr = screen([subj], work / "screen", cache)
    fatf_hits = [x for x in (fatf(subj["nationality"]), fatf(d.get("country", ""))) if x]
    m = mrz(d.get("mrz", "").splitlines(), subj["name"], subj["dob"], subj["nationality"])
    red = []
    if m and not m.get("error"):
        if m.get("overall") not in ("Pass", None):
            red.append(f"MRZ check digits: {m.get('overall')} (posibleng peke o tampered na ID)")
        red += [f"MRZ: {f}" for f in m.get("flags", [])]
        red += [f"MRZ vs application: {row[0]} hindi tugma ({row[1]} vs {row[2]})" for row in m.get("application_comparison", [])
                if str(row[3]).startswith("Mismatch")]
    incomplete = [lg["source"] for lg in scr["lists"] if lg["status"] != "ok"]
    outcome, why = decide(scr, fatf_hits, red, incomplete)
    return {"kind": "KYC", "subject": subj, "screen": scr, "fatf": fatf_hits, "mrz": m, "red": red,
            "searches": {subj["name"]: searches(subj["name"], d.get("country") or subj["nationality"])},
            "outcome": outcome, "why": why, "fatf_info": _fatf_lists()}


# ───────────────────────── KYB (business + UBO) ─────────────────────────
ENTITY_RE = re.compile(r"\b(ltd|limited|inc|corp|corporation|llc|co\.|company|holdings?|gmbh|s\.a\.|pte|plc|b\.v\.|bv|trust|foundation|opc|partners)\b", re.I)


def parse_owners(text: str, business: str) -> tuple[list, list, list[str]]:
    """Lines: 'Owner name | % | owns (blank = the business) | country'."""
    parties = {"TARGET": {"id": "TARGET", "name": business, "type": "entity"}}
    ids, holdings, errors = {business.lower(): "TARGET"}, [], []

    def pid(name: str, country: str = "") -> str:
        k = name.lower()
        if k not in ids:
            ids[k] = f"P{len(ids)}"
            parties[ids[k]] = {"id": ids[k], "name": name, "type": "entity" if ENTITY_RE.search(name) else "person",
                               **({"country": country} if country else {})}
        elif country:
            parties[ids[k]].setdefault("country", country)
        return ids[k]

    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        cells = [c.strip() for c in line.split("|")] + ["", "", ""]
        name, pct, owned, country = cells[0], cells[1].rstrip("%").strip(), cells[2], cells[3]
        try:
            p = float(pct)
        except ValueError:
            errors.append(f"Linya {i}: walang malinaw na % ('{line.strip()}')")
            continue
        holdings.append({"owner": pid(name, country), "owned": pid(owned) if owned else "TARGET", "pct": p,
                         "source": "Declared in the KYB form: verify against GIS / share register"})
    return list(parties.values()), holdings, errors


def kyb_business(d: dict, work: Path, cache: Path, docs_info: dict | None = None) -> dict:
    import url_check
    name = d["name"].strip()
    country = d.get("country", "")
    parties, holdings, owner_errors = parse_owners(d.get("owners", ""), name)
    parties[0].update(country=country)
    offshore = ("seychelles", "vanuatu", "curaçao", "curacao", "united arab emirates", "bvi", "british virgin islands",
                "cayman islands", "panama", "belize", "marshall islands")
    countries = [country] + [p.get("country", "") for p in parties[1:]]
    high = any(fatf(c) or c.strip().lower() in offshore for c in countries if c)  # 10% UBO threshold
    directors = [x.strip() for x in d.get("directors", "").splitlines() if x.strip()]
    subjects = [{"name": name, "type": "entity", "country": country, "reg_number": d.get("reg_number", ""),
                 "incorporation_date": d.get("inc_date", ""), "address": d.get("address", "")}]
    seen = {name.lower()}
    for p in parties[1:] + [{"name": x, "type": "person"} for x in directors]:
        if p["name"].lower() not in seen:
            seen.add(p["name"].lower())
            subjects.append({"name": p["name"], "type": p["type"], "country": p.get("country", ""), "nationality": p.get("country", "")})
    scr = screen(subjects, work / "screen", cache)
    true_match = {n.lower() for n, hs in scr["results"].items() if any(h["suggested_disposition"].startswith("True") for h in hs)}
    for p in parties:
        p["sanctioned"] = p["name"].lower() in true_match  # feeds the OFAC 50% Rule
    ubo = None
    if holdings:
        case = {"subject": "TARGET", "high_risk_jurisdiction": high, "parties": parties, "holdings": holdings}
        cf = work / "bo_case.json"
        work.mkdir(parents=True, exist_ok=True)
        cf.write_text(json.dumps(case, ensure_ascii=False))
        try:
            ubo = {"json": json.loads(_run("bo_calc.py", str(cf), "--json")), "md": _run("bo_calc.py", str(cf))}
        except Exception as exc:
            ubo = {"error": str(exc)}
    fatf_hits = [x for x in [fatf(country)] + [fatf(s.get("country", "")) for s in subjects[1:]] if x]
    url = None
    red = []
    if d.get("website"):
        try:
            url = url_check.check(d["website"], name)
            if url["rating"] == "HIGH":
                red.append("HIGH risk ang website: " + "; ".join(f["msg"] for f in url["findings"] if f["level"] == "high")[:200])
        except Exception as exc:
            url = {"error": str(exc)}
    if ubo and ubo.get("json", {}).get("ofac", {}).get("subject_blocked"):
        red.append(f"OFAC 50% Rule: BLOCKED ang negosyo ({ubo['json']['ofac']['subject_aggregate_pct']:.0f}% pag-aari ng sanctioned parties)")
    mrz_checks = []
    if docs_info:  # documents read from the Drive link
        for m in docs_info.get("mrz", []):
            res = mrz(m["lines"], "", "", "")
            mrz_checks.append({"file": m["file"], "result": res})
            if res and not res.get("error") and res.get("overall") not in ("Pass", None):
                red.append(f"MRZ check digits sa {m['file']}: {res.get('overall')} (posibleng peke o tampered na ID)")
    incomplete = [lg["source"] for lg in scr["lists"] if lg["status"] != "ok"] + (["UBO (walang shareholders)"] if not holdings else [])
    if docs_info:
        missing = [c["item"] for c in docs_info["checklist"] if c["status"] != "Received"]
        if missing:
            incomplete.append(f"{len(missing)} missing document(s) (RFI)")
        incomplete += [f"{x} (RFI: renewed copy)" for x in docs_info.get("issues", []) if x.startswith("Expired")]
    outcome, why = decide(scr, fatf_hits, red, incomplete)
    docs = ["SEC Certificate of Incorporation / DTI registration", "Articles and By-Laws", "Latest GIS (General Information Sheet)",
            "BIR Certificate of Registration (Form 2303)", "Mayor's / Business Permit", "Board resolution / Secretary's certificate (authorised signatory)",
            "Valid IDs ng directors at UBOs", "Proof of address ng negosyo", "Share register o stock and transfer book (para sa UBO)"]
    return {"kind": "KYB", "subject": subjects[0], "subjects": subjects, "screen": scr, "fatf": fatf_hits, "ubo": ubo,
            "owner_errors": owner_errors, "high_risk_jurisdiction": high, "url": url, "red": red, "docs": docs,
            "documents": docs_info, "mrz_checks": mrz_checks,
            "searches": {s["name"]: searches(s["name"], s.get("country") or country, s["type"] == "entity") for s in subjects},
            "outcome": outcome, "why": why, "fatf_info": _fatf_lists()}


# ───────────────────────── report ─────────────────────────
COLORS = {"STOP": "#e84a5f", "REJECT": "#e84a5f", "ESCALATE": "#ff8a3d", "PENDING": "#ffb02e", "EDD": "#ffb02e",
          "INCOMPLETE": "#4da3ff", "CLEAR*": "#3ddc84", "HIGH": "#e84a5f", "MEDIUM": "#ffb02e", "LOW": "#3ddc84"}


def render(r: dict) -> str:
    e = html.escape
    sec = []
    if r["kind"] in ("KYC", "KYB"):
        logs = "".join(f"<tr><td>{e(l['source'])}</td><td>{'✅ ' + str(l['records']) + ' records' if l['status'] == 'ok' else '❌ FAILED: Analyst to run'}</td>"
                       f"<td>{e(', '.join(f['obtained'] + ' · sha256 ' + f['sha256'][:12] for f in l['files'] if 'sha256' in f)[:220])}</td></tr>"
                       for l in r["screen"]["lists"])
        res = []
        for name, hits in r["screen"]["results"].items():
            if not hits:
                res.append(f"<li>✅ <b>{e(name)}</b>: walang hit (score ≥ {r['screen']['min_score']:.0f})</li>")
            for h in hits:
                ids = "".join(f"<tr><td>{e(str(a))}</td><td>{e(str(b))}</td><td>{e(str(c))}</td><td>{e(str(x))}</td></tr>" for a, b, c, x in h["identifiers"])
                tm = h["suggested_disposition"].startswith("True")
                res.append(f"<li class='{'tm' if tm else ''}'>{'🛑' if tm else '⚠️'} <b>{e(name)}</b> ↔ {e(h['hit_name'])} "
                           f"<small>({e(h['source'])} #{e(str(h['list_id']))}, {e(h.get('programme', ''))})</small><br>"
                           f"Name score {h['name_score']} · <b>{e(h['suggested_disposition'])}</b>: {e(h['reason'])}"
                           f"<details><summary>Identifiers</summary><table><tr><th>ID</th><th>Subject</th><th>Hit</th><th>Result</th></tr>{ids}</table></details></li>")
        sec.append(f"<h2>Sanctions screening (OFAC · UN · EU · UK)</h2><table><tr><th>List</th><th>Status</th><th>Version</th></tr>{logs}</table>"
                   f"<p class='muted'>Run {e(r['screen']['run'])}{' (lists cached &lt; 24h)' if r['screen'].get('from_cache') else ''}. "
                   "Dispositions are suggestions: ang analyst ang magko-confirm. True Match = 2+ strong identifiers.</p><ul>{''.join(res)}</ul>")
        fi = r["fatf_info"]
        sec.append(f"<h2>FATF</h2><p>{'⚠️ ' + ', '.join(r['fatf']).upper() + ' list' if r['fatf'] else '✅ Wala sa black/grey list'} "
                   f"<small>(FATF lists as of {e(fi['updated'])}; confirm on the live FATF list{'. ⚠️ Baka luma na ang listahan' if fi['stale'] else ''})</small></p>")
    if r.get("mrz"):
        m = r["mrz"]
        sec.append(f"<h2>MRZ check</h2><pre>{e(json.dumps(m, indent=1, ensure_ascii=False)[:2500])}</pre>"
                   "<p class='muted'>Pass = consistent lang, hindi patunay na tunay ang ID.</p>")
    if r["kind"] == "KYB":
        u = r.get("ubo")
        if u and u.get("md"):
            sec.append(f"<h2>Beneficial ownership (UBO) · threshold {'10%' if r['high_risk_jurisdiction'] else '25%'}</h2><pre>{e(u['md'])}</pre>")
        elif u:
            sec.append(f"<h2>Beneficial ownership</h2><p class='err'>{e(u.get('error', ''))}</p>")
        else:
            sec.append("<h2>Beneficial ownership</h2><p class='warn'>Walang shareholders na nailagay: Analyst to run (GIS / share register).</p>")
        if r["owner_errors"]:
            sec.append("<ul>" + "".join(f"<li class='warn'>{e(x)}</li>" for x in r["owner_errors"]) + "</ul>")
        di = r.get("documents")
        if di:
            ck = "".join(f"<li>{'✅' if c['status'] == 'Received' else '❌'} {e(c['item'])}"
                         f"{' <small>(' + e(', '.join(c['files'])) + ')</small>' if c['files'] else ' <b class=warn>Missing: RFI</b>'}</li>"
                         for c in di["checklist"])
            inv = "".join(f"<tr><td>{e(x['name'])}</td><td>{e(x['type'])}</td><td><small>{e(x.get('drive_id') or '-')}</small></td>"
                          f"<td><small>{e(x.get('modified') or '-')}</small></td><td>{e(x.get('note') or ('%d page(s)' % x['pages'] if x['pages'] else ''))}</td></tr>"
                          for x in di["files"])
            iss = "".join(f"<li class='warn'>⚠️ {e(x)}</li>" for x in di.get("issues", []))
            mz = "".join(f"<li>{e(m['file'])}: <b>{e(str((m['result'] or {}).get('overall') or (m['result'] or {}).get('error', '')))}</b></li>"
                         for m in r.get("mrz_checks", []))
            sec.append(f"<h2>📂 Documents from Drive ({len(di['files'])} file(s), via {e(di['via'])})</h2>"
                       + "".join(f"<p class='muted'>{e(n)}</p>" for n in di.get("notes", []))
                       + f"<p class='muted'>Details taken from the documents by {'AI (' + e(di['extracted_by']) + ')' if di['extracted_by'] != 'rules' else 'simple rules (walang AI sa ⚙️: punan ang kulang sa form)'}; typed fields win. Verify bago i-approve.</p>"
                       + f"<h3>Checklist</h3><ul>{ck}</ul>" + (f"<h3>Issues</h3><ul>{iss}</ul>" if iss else "")
                       + (f"<h3>MRZ found in documents</h3><ul>{mz}</ul><p class='muted'>Pass = consistent lang, hindi patunay na tunay ang ID.</p>" if mz else "")
                       + f"<h3>Document inventory</h3><table><tr><th>File</th><th>Detected as</th><th>Drive ID</th><th>Last modified</th><th>Notes</th></tr>{inv}</table>"
                       "<p class='muted'>Review based on the file versions listed above (Drive ID and last-modified time).</p>")
        else:
            sec.append("<h2>Document checklist (KYB)</h2><ul>" + "".join(f"<li>☐ {e(x)}</li>" for x in r["docs"]) + "</ul>")
    if r.get("url"):
        sec.append(render_url(r["url"], embedded=True))
    if r.get("searches"):
        blocks = []
        for name, links in r["searches"].items():
            items = "".join(f"<li><span class='tag'>{e(l['group'])}</span> <a href='{e(l['url'])}' target='_blank'>{e(l['label'])}</a> ☐</li>" for l in links)
            blocks.append(f"<h3>{e(name)}</h3><ul class='links'>{items}</ul>")
        sec.append("<h2>PEP · adverse media · other lists (Analyst to run)</h2><p class='muted'>Walang libreng opisyal na PEP/adverse media database, "
                   "kaya handa na ang mga search mula sa SOP library mo. I-check ang bawat isa at i-record ang resulta.</p>" + "".join(blocks))
    color = COLORS.get(r["outcome"], "#9c96c9")
    title = r["subject"]["name"] if r["kind"] != "URL" else r["url"]
    return _page(f"{r['kind']}: {title}", f"""<div class="card"><h1>🛡️ {e(r['kind'])}: {e(title)}</h1>
<p><span class="lvl" style="background:{color}">{e(r['outcome'])}</span> {e(r['why'])}</p>
{'<p class="stop">🛑 Huwag ipaalam sa customer (no tip-off). I-escalate sa MLRO ngayon.</p>' if r['outcome'] == 'STOP' else ''}
<p class="muted">{dt.datetime.now():%b %d, %Y %I:%M %p} · Bot Office compliance bots</p></div>{''.join(sec)}""")


def render_url(u: dict, embedded: bool = False) -> str:
    e = html.escape
    if u.get("error"):
        return f"<h2>Website</h2><p class='err'>{e(u['error'])}</p>"
    f = u["facts"]
    lvl = {"high": "🔴", "medium": "🟠", "low": "🟡"}
    finds = "".join(f"<li>{lvl[x['level']]} {e(x['msg'])}</li>" for x in u["findings"]) or "<li>✅ Walang nakitang problema</li>"
    pages = "".join(f"<li>{'✅' if v else '❌'} {e(k)}{(' · <a href=' + chr(39) + e(v) + chr(39) + ' target=_blank>link</a>') if v else ''}</li>" for k, v in (f.get("pages") or {}).items())
    who = f.get("whois", {})
    rows = [("Final URL", f.get("final_url", "")), ("HTTPS", "oo" if f.get("https") else "hindi"),
            ("SSL", (f"valid hanggang {f['cert']['expires']} ({f['cert'].get('issuer', '')})" if f.get("cert", {}).get("valid") else f"❌ {f.get('cert', {}).get('error', '')}")),
            ("Domain na-rehistro", f"{who.get('created') or '?'} ({who.get('age_days', '?')} araw) · {who.get('registrar', '')}" if "error" not in who else "Analyst to run"),
            ("Unang Wayback snapshot", f.get("first_archived") or "wala / Analyst to run"), ("Title", f.get("title", "")),
            ("Pangalan ng negosyo", f.get("name_match", "-")), ("Email / phone", ", ".join(f.get("emails", []) + f.get("phones", [])) or "wala")]
    pc = f.get("privacy_check")
    if pc:
        rows.append(("Privacy policy (DPA check)", f"{pc['level']} · kulang: {', '.join(pc['missing']) or 'wala'}"))
    table = "".join(f"<tr><td>{e(a)}</td><td>{e(str(b))}</td></tr>" for a, b in rows)
    analyst = "".join(f"<li>☐ {_linkify(x)}</li>" for x in u["analyst"])
    body = (f"<h2>Website check: {e(u['url'])} <span class='lvl' style='background:{COLORS.get(u['rating'], '#4da3ff')}'>{e(u['rating'])}</span></h2>"
            f"<ul>{finds}</ul><table>{table}</table><h3>Mga page</h3><ul>{pages or '<li>Hindi nabasa ang page</li>'}</ul>"
            f"<h3>Analyst to run</h3><ul>{analyst}</ul>")
    return body if embedded else _page(f"URL: {u['url']}", f"<div class='card'><h1>🌐 URL check</h1></div>{body}")


def _linkify(t: str) -> str:
    return re.sub(r"(https?://\S+)", lambda m: f"<a href='{html.escape(m.group(1))}' target='_blank'>{html.escape(m.group(1))}</a>", html.escape(t))


def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
body{{font:15px/1.5 system-ui,sans-serif;background:#0d0b1a;color:#e9e6ff;max-width:900px;margin:0 auto;padding:22px}}
.card{{background:#17132e;border:1px solid #3a3270;border-radius:14px;padding:16px 20px;margin-bottom:16px}} h1{{font-size:21px;margin:0 0 8px}}
h2{{font-size:14px;letter-spacing:.06em;text-transform:uppercase;color:#9c96c9;margin-top:26px}} h3{{font-size:14px;margin:14px 0 4px}}
.lvl{{display:inline-block;color:#111;font-weight:800;border-radius:99px;padding:3px 12px;margin-right:6px;font-size:13px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td,th{{border-bottom:1px solid #2a2550;padding:6px;text-align:left;vertical-align:top}}
pre{{white-space:pre-wrap;background:#17132e;border-radius:10px;padding:12px;font:12.5px/1.45 ui-monospace,monospace}}
a{{color:#2ee6c9}} .muted{{color:#8d87b8;font-size:13px}} .warn{{color:#ffb86b}} .err{{color:#ff8a8a}}
.stop{{background:#e84a5f33;color:#ffb3bd;border-radius:10px;padding:10px;font-weight:700}} li.tm{{color:#ffb3bd}} li{{margin:6px 0}}
.tag{{font-size:11px;background:#2a2450;border-radius:6px;padding:1px 6px;color:#c4a6ff}} .links{{list-style:none;padding-left:0}}
</style></head><body>{body}<p class="muted">Automated screening support. Hindi ito final na decision: ang analyst/MLRO ang magko-confirm ng lahat ng disposition.</p></body></html>"""
