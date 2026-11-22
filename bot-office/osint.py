"""Taks, OSINT Researcher: research anything from lawful, publicly available sources.

Types (auto-detected or chosen): person, company, website, crypto, username, country, topic (anything), competitor.
Each run builds an intelligence report:
  - a research plan (objective, sources, Boolean search strings),
  - automated public checks: sanctions lists (OFAC/UN/EU/UK, incl. OFAC-listed crypto addresses), FATF, website/domain
    (DNS, SSL, RDAP age, Wayback), GDELT news mentions, Wikipedia, blockchain explorers, username presence,
  - optional web research by Claude (web search tool, with citations) when Claude is the AI provider,
  - findings with source, confidence and fact / allegation labels, information gaps and an evidence log.
Public information only. People research needs a stated, lawful purpose (Data Privacy Act); no home addresses, family
details or private data. Findings are intelligence, not decisions: the compliance team decides.
"""
from __future__ import annotations

import datetime as dt
import html as htmlmod
import json
import re
from pathlib import Path
from urllib.parse import quote, quote_plus

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
TYPES = {"person": "Person profile", "company": "Corporate profile", "website": "Website / domain", "crypto": "Crypto wallet",
         "username": "Username / social account", "country": "Country risk", "topic": "Topic research (anything)",
         "competitor": "Competitor / market intelligence"}
PURPOSES = ["KYC / KYB due diligence", "AML / sanctions / PEP review", "Fraud investigation", "Vendor due diligence",
            "Brand / impersonation check", "Competitor / market research", "Content research", "General research"]
COUNTRIES = ["philippines", "singapore", "malaysia", "indonesia", "thailand", "vietnam", "china", "hong kong", "japan", "korea",
             "india", "united states", "usa", "united kingdom", "uk", "australia", "canada", "uae", "united arab emirates",
             "russia", "iran", "north korea", "myanmar", "cambodia", "laos", "seychelles", "cayman islands", "panama",
             "british virgin islands", "bvi", "curacao", "malta", "cyprus", "nigeria", "south africa", "brazil", "mexico",
             "germany", "france", "netherlands", "switzerland", "turkey", "israel", "saudi arabia", "qatar", "pakistan"]
ENTITY = re.compile(r"\b(inc|corp|corporation|ltd|limited|llc|co\.|company|holdings?|opc|gmbh|pte|plc|bv|trading|enterprises?|group|foundation)\b", re.I)


def detect(q: str) -> str:
    s = q.strip()
    if re.fullmatch(r"(0x[a-fA-F0-9]{40}|(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,62}|T[1-9A-HJ-NP-Za-km-z]{33})", s):
        return "crypto"
    if re.match(r"^https?://", s) or re.fullmatch(r"[\w-]+(\.[\w-]+)+(/\S*)?", s):
        return "website"
    if s.startswith("@") and " " not in s:
        return "username"
    if s.lower() in COUNTRIES:
        return "country"
    if ENTITY.search(s):
        return "company"
    if re.fullmatch(r"[A-ZÑ][a-zñ'.-]+( [A-ZÑ][a-zñ'.-]+){1,4}", s):
        return "person"
    return "topic"


def _get(url, params=None, timeout=20):
    import requests
    return requests.get(url, params=params, timeout=timeout, headers={"User-Agent": UA})


# ───────────────────────── public sources ─────────────────────────

def news(query: str, n: int = 15) -> dict:
    """GDELT 2.0 DOC API: worldwide news mentions (free, no key)."""
    try:
        r = _get("https://api.gdeltproject.org/api/v2/doc/doc",
                 {"query": f'"{query}"', "mode": "artlist", "format": "json", "maxrecords": n, "sort": "datedesc", "timespan": "5y"}, 30)
        arts = (r.json() or {}).get("articles", []) if r.ok and r.text.strip().startswith("{") else []
        return {"ok": True, "items": [{"title": a.get("title", ""), "url": a.get("url", ""), "source": a.get("domain", ""),
                                       "date": (a.get("seendate") or "")[:8], "lang": a.get("language", "")} for a in arts]}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "items": []}


def wikipedia(query: str) -> dict:
    try:
        s = _get("https://en.wikipedia.org/w/api.php", {"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 3}).json()
        hits = s.get("query", {}).get("search", [])
        if not hits:
            return {"ok": True, "found": False}
        title = hits[0]["title"]
        sm = _get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title.replace(' ', '_'))}").json()
        return {"ok": True, "found": True, "title": title, "extract": sm.get("extract", ""),
                "url": sm.get("content_urls", {}).get("desktop", {}).get("page", f"https://en.wikipedia.org/wiki/{quote(title)}"),
                "others": [h["title"] for h in hits[1:]]}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


def sanctioned_wallet(addr: str, cache: Path) -> list[str]:
    """OFAC lists crypto addresses in SDN remarks ('Digital Currency Address - XBT …')."""
    hits = []
    for f in cache.rglob("*.CSV"):
        try:
            for line in f.read_text(encoding="latin-1", errors="ignore").splitlines():
                if addr.lower() in line.lower():
                    hits.append(f"{f.name}: {line[:220]}")
        except OSError:
            continue
    return hits[:5]


def wallet(addr: str) -> dict:
    try:
        if addr.startswith("0x"):
            j = _get(f"https://api.blockchair.com/ethereum/dashboards/address/{addr}").json()
            a = (j.get("data") or {}).get(addr.lower(), {}).get("address", {})
            return {"ok": True, "chain": "Ethereum", "balance": a.get("balance"), "tx_count": a.get("transaction_count"),
                    "first_seen": a.get("first_seen_receiving"), "last_seen": a.get("last_seen_spending") or a.get("last_seen_receiving")}
        if addr.startswith("T"):
            return {"ok": True, "chain": "Tron", "note": "Tingnan sa Tronscan (link sa ibaba)"}
        j = _get(f"https://blockstream.info/api/address/{addr}").json()
        cs = j.get("chain_stats", {})
        return {"ok": True, "chain": "Bitcoin", "tx_count": cs.get("tx_count"), "received_sats": cs.get("funded_txo_sum"),
                "balance_sats": (cs.get("funded_txo_sum") or 0) - (cs.get("spent_txo_sum") or 0)}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


HANDLE_SITES = {"Instagram": "https://www.instagram.com/{}/", "TikTok": "https://www.tiktok.com/@{}", "Facebook": "https://www.facebook.com/{}",
                "X / Twitter": "https://x.com/{}", "YouTube": "https://www.youtube.com/@{}", "Threads": "https://www.threads.net/@{}",
                "GitHub": "https://github.com/{}", "Reddit": "https://www.reddit.com/user/{}", "Pinterest": "https://www.pinterest.com/{}/",
                "LinkedIn (company)": "https://www.linkedin.com/company/{}", "Telegram": "https://t.me/{}", "Shopee shop": "https://shopee.ph/{}"}


def handles(user: str) -> list[dict]:
    """Possible accounts: HTTP status only (many sites hide 404s), so every hit must be checked by hand. Checked in parallel."""
    from concurrent.futures import ThreadPoolExecutor

    def one(item):
        site, tpl = item
        url = tpl.format(quote(user))
        try:
            r = _get(url, timeout=10)
            status = "possible" if r.status_code == 200 else "not found" if r.status_code == 404 else f"HTTP {r.status_code}"
        except Exception as exc:
            status = f"unreachable ({type(exc).__name__})"
        return {"site": site, "url": url, "status": status}

    with ThreadPoolExecutor(max_workers=6) as ex:
        return list(ex.map(one, HANDLE_SITES.items()))


def boolean_queries(q: str, kind: str, country: str = "") -> list[str]:
    n = f'"{q}"'
    c = f' "{country}"' if country else ""
    base = {
        "person": [f'{n}{c} (fraud OR scam OR estafa OR arrested OR charged OR convicted)', f'{n} (director OR owner OR founder OR CEO)',
                   f'{n} (site:linkedin.com OR site:facebook.com)', f'{n} (sanction OR PEP OR politician OR mayor OR congressman OR official)',
                   f'{n} (kaso OR inaresto OR nanloko OR modus)'],
        "company": [f'{n}{c} (fraud OR scam OR investigation OR lawsuit OR "cease and desist" OR advisory)', f'{n} (SEC OR "business registration" OR DTI)',
                    f'{n} (owner OR director OR "beneficial owner" OR shareholder)', f'{n} (reviews OR complaints OR "not legit")',
                    f'{n} (site:sec.gov.ph OR site:bsp.gov.ph OR site:dti.gov.ph)'],
        "website": [f'"{q}" (scam OR phishing OR fake OR "not legit")', f'site:{q}', f'"{q}" reviews'],
        "crypto": [f'"{q}"', f'"{q}" (scam OR hack OR ransomware OR sanction)'],
        "username": [f'"{q.lstrip("@")}"', f'"@{q.lstrip("@")}" (scam OR fake OR impersonation)'],
        "country": [f'"{q}" (sanctions OR "grey list" OR FATF) 2026', f'"{q}" (money laundering OR corruption) report'],
        "competitor": [f'{n} (pricing OR price)', f'{n} (reviews OR complaints)', f'{n} (launch OR partnership OR acquisition)', f'{n} competitors'],
    }
    return base.get(kind, [n, f'{n} (report OR study OR statistics) 2026', f'{n} site:gov.ph', f'{n} (filetype:pdf)'])


LINKS = {
    "company": [("OpenCorporates", "https://opencorporates.com/companies?q={q}"), ("SEC PH (Company search)", "https://secexpress.ph/"),
                ("SEC PH advisories", "https://www.google.com/search?q={q}+site%3Asec.gov.ph"), ("BSP advisories", "https://www.google.com/search?q={q}+site%3Absp.gov.ph"),
                ("OpenSanctions", "https://www.opensanctions.org/search/?q={q}"), ("ICIJ Offshore Leaks", "https://offshoreleaks.icij.org/search?q={q}"),
                ("LinkedIn", "https://www.google.com/search?q={q}+site%3Alinkedin.com")],
    "person": [("OpenSanctions (PEP & sanctions)", "https://www.opensanctions.org/search/?q={q}"), ("ICIJ Offshore Leaks", "https://offshoreleaks.icij.org/search?q={q}"),
               ("OpenCorporates officers", "https://opencorporates.com/officers?q={q}"), ("LinkedIn", "https://www.google.com/search?q={q}+site%3Alinkedin.com"),
               ("Supreme Court e-Library", "https://www.google.com/search?q={q}+site%3Aelibrary.judiciary.gov.ph")],
    "website": [("urlscan.io", "https://urlscan.io/search/#{q}"), ("VirusTotal", "https://www.virustotal.com/gui/domain/{q}"),
                ("Wayback Machine", "https://web.archive.org/web/*/{q}"), ("DNSdumpster", "https://dnsdumpster.com/"),
                ("crt.sh certificates", "https://crt.sh/?q={q}"), ("ScamAdviser", "https://www.scamadviser.com/check-website/{q}")],
    "crypto": [("Etherscan", "https://etherscan.io/address/{q}"), ("Blockchair", "https://blockchair.com/search?q={q}"),
               ("Blockchain.com", "https://www.blockchain.com/explorer/search?search={q}"), ("Arkham", "https://intel.arkm.com/explorer/address/{q}"),
               ("Tronscan", "https://tronscan.org/#/address/{q}"), ("OFAC search", "https://sanctionssearch.ofac.treas.gov/")],
    "country": [("FATF high-risk lists", "https://www.fatf-gafi.org/en/countries/black-and-grey-lists.html"), ("Basel AML Index", "https://index.baselgovernance.org/"),
                ("TI Corruption Perceptions Index", "https://www.transparency.org/en/cpi"), ("OFAC programs", "https://ofac.treasury.gov/sanctions-programs-and-country-information")],
}


# ───────────────────────── Claude web research ─────────────────────────

RESEARCH_SYSTEM = ("You are Taks, an OSINT researcher for a Philippine fintech compliance team (and for general research). Research the request "
                   "using lawful, publicly available sources only. For every finding: say what the source says, cite it, label it FACT (official "
                   "record or multiple credible sources) or ALLEGATION (reported, unproven), and give a confidence (High / Medium / Low). "
                   "Separate facts, allegations and your assumptions. Name information gaps. For private individuals, do not collect home addresses, "
                   "family details, health or other sensitive personal data. Be concise and organised with headings: Summary, Key findings, "
                   "Risk indicators (if any), Information gaps, Suggested next steps.")


def claude_web(question: str, kind: str, purpose: str) -> dict | None:
    """Web research with Claude's server-side web search tool. Returns {text, sources} or None."""
    import ai
    if ai.provider() != "claude" or not ai.available():
        return None
    client = ai._get_client()
    if client is None:
        return None
    messages = [{"role": "user", "content": f"Research type: {TYPES.get(kind, kind)}. Purpose: {purpose}. Today: {dt.date.today()}.\n\n{question}"}]
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 10}]
    try:
        for _ in range(4):   # the server pauses long searches: continue the turn
            with client.messages.stream(model=ai.MODEL, max_tokens=12000, system=RESEARCH_SYSTEM, tools=tools,
                                        thinking={"type": "adaptive"}, messages=messages) as stream:
                msg = stream.get_final_message()
            if msg.stop_reason != "pause_turn":
                break
            messages.append({"role": "assistant", "content": msg.content})
        text, sources = [], {}
        for b in msg.content:
            if getattr(b, "type", "") == "text":
                text.append(b.text)
                for c in getattr(b, "citations", None) or []:
                    url = getattr(c, "url", None)
                    if url:
                        sources[url] = getattr(c, "title", "") or url
        return {"text": "".join(text).strip(), "sources": [{"url": u, "title": t} for u, t in sources.items()]}
    except Exception as exc:
        return {"text": "", "sources": [], "error": f"{type(exc).__name__}: {str(exc)[:200]}"}


# ───────────────────────── the research run ─────────────────────────

def run(q: str, kind: str, country: str, purpose: str, notes: str, work: Path, cache: Path, web: bool) -> dict:
    import kyc
    q = q.strip()
    kind = kind if kind in TYPES else detect(q)
    ev, findings, gaps, red = [], [], [], []
    now = lambda: dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    def log(source, what, url=""):
        ev.append({"time": now(), "source": source, "what": what, "url": url})

    def find(text, source, url="", label="FACT", conf="Medium"):
        findings.append({"text": text, "source": source, "url": url, "label": label, "confidence": conf})

    subj = q.lstrip("@")
    res = {"query": q, "kind": kind, "kind_label": TYPES[kind], "country": country, "purpose": purpose, "notes": notes,
           "started": now(), "plan": {}, "checks": {}}
    res["plan"] = {"objective": f"{TYPES[kind]}: {q}" + (f" ({country})" if country else "") + f" · purpose: {purpose}",
                   "queries": boolean_queries(subj, kind, country),
                   "links": [{"label": l, "url": u.format(q=quote_plus(subj))} for l, u in LINKS.get(kind, [])]}

    if kind in ("person", "company"):
        sub = {"name": subj, "type": "entity" if kind == "company" else "person", "country": country, "nationality": country}
        scr = kyc.screen([sub], work / "screen", cache)
        hits = scr["results"].get(subj, [])
        res["checks"]["sanctions"] = {"lists": [(l["source"], l["status"]) for l in scr["lists"]], "hits": hits}
        log("Sanctions lists (OFAC/UN/EU/UK)", f"{len(hits)} potential hit(s)")
        for h in hits:
            tm = h["suggested_disposition"].startswith("True")
            find(f"Sanctions list {h['source']}: {h['hit_name']} (score {h['name_score']}), suggested {h['suggested_disposition']}",
                 h["source"], "", "FACT" if tm else "POSSIBLE MATCH", "High" if tm else "Low")
            if tm:
                red.append(f"Possible sanctions TRUE MATCH ({h['source']}): STOP, escalate to the MLRO, no tip-off")
        failed = [l["source"] for l in scr["lists"] if l["status"] != "ok"]
        if failed:
            gaps.append("Hindi na-screen: " + ", ".join(failed))
        res["checks"]["pep_media_links"] = kyc.searches(subj, country, kind == "company")
        if country and kyc.fatf(country):
            red.append(f"{country}: FATF {kyc.fatf(country)} list")
    if kind == "country":
        f = kyc.fatf(q)
        res["checks"]["fatf"] = f or "not listed"
        find(f"FATF: {('on the ' + f + ' list') if f else 'not on the black or grey list'} (as of {kyc._fatf_lists()['updated']})", "FATF list in the toolkit",
             "https://www.fatf-gafi.org/en/countries/black-and-grey-lists.html", "FACT", "High")
        if f:
            red.append(f"FATF {f} list")
    if kind == "website":
        import url_check
        u = url_check.check(q, notes)
        res["checks"]["website"] = u
        log("Website checks (DNS, SSL, RDAP, Wayback, page)", f"rating {u['rating']}", u["url"])
        for x in u["findings"]:
            find(x["msg"], "Website checks", u["url"], "FACT", "High" if x["level"] == "high" else "Medium")
        if u["rating"] == "HIGH":
            red.append("Website rated HIGH risk")
    if kind == "crypto":
        hits = sanctioned_wallet(q, cache)
        res["checks"]["ofac_wallet"] = hits
        log("OFAC SDN digital currency addresses", f"{len(hits)} match(es)")
        if hits:
            red.append("Wallet address appears in the OFAC SDN list: STOP, escalate to the MLRO")
            for h in hits:
                find(h, "OFAC SDN list", "https://sanctionssearch.ofac.treas.gov/", "FACT", "High")
        elif not list(cache.rglob("*.CSV")):
            gaps.append("Walang naka-download na OFAC list pa: magpatakbo muna ng isang KYC/KYB check")
        w = wallet(q)
        res["checks"]["wallet"] = w
        log(f"{w.get('chain', 'Blockchain')} explorer", json.dumps({k: v for k, v in w.items() if k not in ('ok',)})[:200])
        if w.get("ok") and w.get("tx_count") is not None:
            find(f"{w['chain']}: {w.get('tx_count')} transaction(s)" + (f", first seen {w.get('first_seen')}" if w.get("first_seen") else ""),
                 f"{w['chain']} explorer", "", "FACT", "High")
        elif not w.get("ok"):
            gaps.append("Hindi naabot ang blockchain explorer: buksan ang mga link")
    if kind == "username":
        hs = handles(subj)
        res["checks"]["handles"] = hs
        log("Username presence check", f"{sum(h['status'] == 'possible' for h in hs)} possible account(s)")
        for h in hs:
            if h["status"] == "possible":
                find(f"Possible {h['site']} account: {h['url']}", h["site"], h["url"], "UNVERIFIED", "Low")
        gaps.append("Ang 'possible' ay galing sa HTTP status lang: buksan at i-verify ang bawat account (pangalan, bio, petsa, posts)")

    if kind != "crypto":
        nw = news(subj)
        res["checks"]["news"] = nw
        log("GDELT news search (5 years)", f"{len(nw['items'])} article(s)" if nw["ok"] else f"failed ({nw.get('error')})")
        if not nw["ok"]:
            gaps.append("Hindi naabot ang GDELT news: gamitin ang Boolean searches sa Google News")
        neg = re.compile(r"scam|fraud|estafa|arrest|charged|convict|launder|sanction|raid|swindl|illegal|investigat|kaso|modus|ponzi|hack", re.I)
        for a in nw["items"]:
            if neg.search(a["title"]):
                find(f"Adverse media: “{a['title']}” ({a['source']}, {a['date']})", a["source"], a["url"], "ALLEGATION", "Low")
        wk = wikipedia(subj)
        res["checks"]["wikipedia"] = wk
        log("Wikipedia", wk.get("title", "no page") if wk.get("ok") else f"failed ({wk.get('error')})", wk.get("url", ""))
        if not wk.get("ok"):
            gaps.append("Hindi naabot ang Wikipedia")
        if wk.get("found"):
            find(f"Wikipedia: {wk['extract'][:400]}", "Wikipedia", wk["url"], "FACT" if kind in ("country", "topic", "competitor") else "UNVERIFIED", "Medium")

    if web:
        cw = claude_web(f"{q}\n{('Country: ' + country) if country else ''}\n{('Notes: ' + notes) if notes else ''}", kind, purpose)
        if cw is None:
            gaps.append("Web research ni Claude: kailangan ng Claude bilang AI provider sa ⚙️ (Ollama ay walang web search)")
        elif cw.get("error"):
            gaps.append(f"Web research error: {cw['error']}")
        else:
            res["checks"]["claude_web"] = cw
            log("Claude web research (web search tool)", f"{len(cw['sources'])} source(s) cited")
    if kind in ("person", "company"):
        gaps.append("PEP at adverse media: tapusin ang mga search link (walang libreng opisyal na PEP database)")
    if kind == "person" and not country:
        gaps.append("Walang bansa: mas maraming false positive sa pangalan")
    res.update(findings=findings, red=red, gaps=gaps, evidence=ev, finished=now())
    n_alleg = sum(f["label"] == "ALLEGATION" for f in findings)
    incomplete = any(g.startswith("Hindi na-screen") for g in gaps)
    res["outcome"] = "ESCALATE" if red else "INCOMPLETE" if incomplete else ("REVIEW" if n_alleg or any(f["label"] == "POSSIBLE MATCH" for f in findings) else "NO RED FLAGS FOUND*")
    res["why"] = ("; ".join(red) if red else f"{len(findings)} finding(s), {n_alleg} allegation(s) sa news" if findings else
                  "Walang nakitang red flag sa mga na-check na source.") + " *Intelligence lang: ang compliance team ang magdedesisyon."
    res["searches"] = {subj: [{"group": "Plan", "label": l["label"], "url": l["url"]} for l in res["plan"]["links"]] +
                       res["checks"].get("pep_media_links", [])}
    res["sections"] = [("Key findings", [f"[{f['label']} · {f['confidence']}] {f['text']} ({f['source']}{(' ' + f['url']) if f['url'] else ''})" for f in findings] or ["Wala"]),
                       ("Information gaps", gaps or ["Wala"]),
                       ("Boolean searches", res["plan"]["queries"]),
                       ("Evidence log", [f"{e['time']} · {e['source']}: {e['what']} {e['url']}" for e in ev])]
    if res["checks"].get("claude_web", {}).get("text"):
        res["sections"].insert(0, ("Web research (Claude)", [res["checks"]["claude_web"]["text"][:6000]] +
                                   [f"Source: {s['title']} {s['url']}" for s in res["checks"]["claude_web"]["sources"][:30]]))
    return res


# ───────────────────────── Content Hub research (Taks' second job) ─────────────────────────

CONTENT_Q = ("Research this product for short-form affiliate content in the Philippines: {name}. Notes: {notes}. Give: 1) what it is and who buys it, "
             "2) the top 3-5 selling points that the brand or listing actually states (cite), 3) common buyer questions and objections, "
             "4) trending angles / hooks / formats people use for this kind of product now, 5) claims we must NOT make (health, results, "
             "before/after, prices). Keep it short and practical, in English with Taglish hook examples.")


def content_research(name: str, notes: str = "", web: bool = True) -> dict:
    """Product research for the Content Hub: news, Wikipedia and (with Claude) cited web research."""
    out = {"name": name, "news": news(name, 6), "wiki": wikipedia(name), "web": None}
    if web:
        out["web"] = claude_web(CONTENT_Q.format(name=name, notes=notes[:400]), "topic", "Content research")
    parts = []
    if out["wiki"].get("found"):
        parts.append(f"About: {out['wiki']['extract'][:300]}")
    if out["web"] and out["web"].get("text"):
        parts.append(f"Research: {out['web']['text'][:900]}")
    if out["news"]["items"]:
        parts.append("In the news: " + "; ".join(a["title"] for a in out["news"]["items"][:3]))
    out["summary"] = " ".join(parts)[:1400]
    return out


def render_content(rs: list[dict]) -> str:
    e = htmlmod.escape
    blocks = []
    for r in rs:
        web = r.get("web") or {}
        srcs = "".join(f"<li><a href='{e(s['url'])}' target='_blank'>{e(s['title'] or s['url'])}</a></li>" for s in web.get("sources", [])[:12])
        nw = "".join(f"<li>{e(a['date'])} · <a href='{e(a['url'])}' target='_blank'>{e(a['title'])}</a></li>" for a in r["news"]["items"])
        wk = r["wiki"]
        blocks.append(f"<div class='post'><h3>🔎 {e(r['name'])}</h3>"
                      + (f"<p>{e(wk['extract'][:500])} <a href='{e(wk['url'])}' target='_blank'>Wikipedia</a></p>" if wk.get("found") else "")
                      + (f"<div>{_md(web['text'])}</div><ul>{srcs}</ul>" if web.get("text") else
                         "<p class='muted'>Web research: i-set ang Claude bilang AI provider sa ⚙️ para sa selling points, FAQs at trends na may citations.</p>")
                      + (f"<h4>Sa balita</h4><ul>{nw}</ul>" if nw else "") + "</div>")
    return ("<section class='video'><div class='right'><h2>🔎 Taks · product research para sa content</h2>" + "".join(blocks)
            + "<p class='muted'>Ginamit ito ni Asher sa captions. I-verify ang claims sa listing bago gamitin.</p></div></section>")


def _md(t: str) -> str:
    e = htmlmod.escape(t)
    e = re.sub(r"^#+\s*(.+)$", r"<h4>\1</h4>", e, flags=re.M)
    e = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", e)
    e = re.sub(r"(https?://[^\s<)]+)", r"<a href='\1' target='_blank'>\1</a>", e)
    return e.replace("\n", "<br>")


def render(r: dict) -> str:
    e = htmlmod.escape
    col = {"ESCALATE": "#e84a5f", "REVIEW": "#ffb02e", "INCOMPLETE": "#4da3ff"}.get(r["outcome"], "#3ddc84")
    lab = {"FACT": "#3ddc84", "ALLEGATION": "#ff8a3d", "POSSIBLE MATCH": "#ffb02e", "UNVERIFIED": "#9c96c9"}
    fnd = "".join(f"<tr><td><span class='pill' style='background:{lab.get(f['label'], '#9c96c9')}'>{e(f['label'])}</span></td><td>{e(f['confidence'])}</td>"
                  f"<td>{e(f['text'])}</td><td>{('<a href=' + chr(39) + e(f['url']) + chr(39) + ' target=_blank>' + e(f['source']) + '</a>') if f['url'] else e(f['source'])}</td></tr>"
                  for f in r["findings"]) or "<tr><td colspan=4>Walang findings mula sa automated sources.</td></tr>"
    cw = r["checks"].get("claude_web")
    web = (f"<h2>🌐 Web research (Claude, may citations)</h2><div class='card'>{_md(cw['text'])}</div><ul>"
           + "".join(f"<li><a href='{e(s['url'])}' target='_blank'>{e(s['title'] or s['url'])}</a></li>" for s in cw["sources"][:40]) + "</ul>") if cw and cw.get("text") else ""
    news_items = r["checks"].get("news", {}).get("items", [])
    news_html = ("<h2>📰 News mentions (GDELT, 5 taon)</h2><ul>" + "".join(
        f"<li>{e(a['date'])} · <a href='{e(a['url'])}' target='_blank'>{e(a['title'])}</a> <span class='muted'>{e(a['source'])}</span></li>" for a in news_items) + "</ul>") if news_items else ""
    wk = r["checks"].get("wikipedia", {})
    wk_html = f"<h2>📚 Wikipedia</h2><p>{e(wk.get('extract', ''))} <a href='{e(wk.get('url', ''))}' target='_blank'>source</a></p>" if wk.get("found") else ""
    hs = r["checks"].get("handles")
    hs_html = ("<h2>👤 Username check</h2><table><tr><th>Site</th><th>Status</th></tr>" + "".join(
        f"<tr><td><a href='{e(h['url'])}' target='_blank'>{e(h['site'])}</a></td><td>{e(h['status'])}</td></tr>" for h in hs) + "</table>") if hs else ""
    links = "".join(f"<li><a href='{e(l['url'])}' target='_blank'>{e(l['label'])}</a> ☐</li>" for l in r["plan"]["links"])
    pep = r["checks"].get("pep_media_links") or []
    pep_html = ("<h2>🔍 PEP · adverse media (Analyst to run)</h2><ul>" + "".join(
        f"<li><span class='tag'>{e(l['group'])}</span> <a href='{e(l['url'])}' target='_blank'>{e(l['label'])}</a> ☐</li>" for l in pep) + "</ul>") if pep else ""
    ev = "".join(f"<tr><td>{e(x['time'])}</td><td>{e(x['source'])}</td><td>{e(x['what'])}</td><td>{('<a href=' + chr(39) + e(x['url']) + chr(39) + '>link</a>') if x['url'] else ''}</td></tr>" for x in r["evidence"])
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>🔎 OSINT: {e(r['query'])}</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{font:15px/1.55 system-ui,sans-serif;background:#0d0b1a;color:#e9e6ff;margin:0;padding:24px;max-width:1050px;margin:auto}}
.card{{background:#17132e;border:1px solid #3a3270;border-radius:14px;padding:16px 20px;margin:12px 0}} h1{{margin:0}} .muted{{color:#9c96c9;font-size:13px}}
table{{width:100%;border-collapse:collapse;font-size:14px}} td,th{{border-bottom:1px solid #2a2450;padding:6px;text-align:left;vertical-align:top}}
.pill{{color:#10101a;border-radius:99px;padding:2px 9px;font-size:11px;font-weight:800;white-space:nowrap}} a{{color:#7fd4ff}} .tag{{font-size:11px;background:#2a2450;border-radius:99px;padding:1px 7px}}
.lvl{{color:#10101a;border-radius:8px;padding:4px 10px;font-weight:800}} .red li{{color:#ff8a8a}}</style></head><body>
<div class="card"><h1>🔎 OSINT report · {e(r['kind_label'])}</h1><p><b>{e(r['query'])}</b>{(' · ' + e(r['country'])) if r['country'] else ''}</p>
<p><span class="lvl" style="background:{col}">{e(r['outcome'])}</span> {e(r['why'])}</p>
<p class="muted">Researcher: Taks · Purpose: {e(r['purpose'])} · {e(r['started'])} → {e(r['finished'])} · Public sources only.</p></div>
{('<ul class="red">' + ''.join('<li>🚩 ' + e(x) + '</li>' for x in r['red']) + '</ul>') if r['red'] else ''}
<h2>🧭 Research plan</h2><p>{e(r['plan']['objective'])}</p><h4>Boolean searches</h4><ul>{''.join('<li><code>' + e(x) + '</code></li>' for x in r['plan']['queries'])}</ul>
{('<h4>Sources to check</h4><ul>' + links + '</ul>') if links else ''}
{web}<h2>🗂 Key findings</h2><table><tr><th>Label</th><th>Confidence</th><th>Finding</th><th>Source</th></tr>{fnd}</table>
<p class="muted">FACT = official record o maraming kapani-paniwalang source · ALLEGATION = iniulat pero hindi napatunayan · POSSIBLE MATCH / UNVERIFIED = kailangang i-verify.</p>
{news_html}{wk_html}{hs_html}{pep_html}
<h2>🕳 Information gaps</h2><ul>{''.join('<li>' + e(x) + '</li>' for x in r['gaps']) or '<li>Wala</li>'}</ul>
<h2>🧾 Evidence log</h2><table><tr><th>Time</th><th>Source</th><th>Result</th><th></th></tr>{ev}</table>
<p class="muted">Intelligence lang ito mula sa public sources: ang compliance team / MLRO ang magdedesisyon. Sanctions true match = STOP, MLRO, walang tip-off.
Para sa tao: lehitimong layunin lang (Data Privacy Act); walang personal na address, pamilya o sensitibong datos.</p></body></html>"""
