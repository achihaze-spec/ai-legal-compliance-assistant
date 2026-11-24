"""Asher's SEO desk (Content Manager + SEO Manager).

Tasks:
  audit       crawl a site (robots.txt respected) → technical + on-page issues with fixes, Core Web Vitals (PageSpeed, free)
  keywords    keyword ideas from Google / DuckDuckGo autocomplete (PH), questions, intent, clusters
  brief       content brief for a keyword (AI if set, otherwise built from the keyword data)
  competitor  your site vs competitors: titles, content depth, schema, speed, shared topics
  geo         AI search / GEO visibility: how the brand shows up in AI answers (Claude web search), entity + schema signals
Not available for free: search volume and keyword difficulty (Ahrefs, SEMrush, Keyword Planner), and your own Search
Console / GA4 numbers (need a Google login): the reports say so instead of guessing.
"""
from __future__ import annotations

import csv
import html as htmlmod
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote, urldefrag, urljoin, urlparse

UA = "Mozilla/5.0 (compatible; BotOffice-SEO-Audit/1.0)"
TASKS = {"audit": "Technical + on-page SEO audit", "keywords": "Keyword research", "brief": "Content brief",
         "competitor": "Competitor SEO analysis", "geo": "AI search / GEO visibility"}
STOP = set("the a an and or of for to in on with at by from is are ng sa ang mga na at para ni kay ba po".split())


def _norm(url: str) -> str:
    url = url.strip()
    if not re.match(r"https?://", url):
        url = "https://" + url
    return urldefrag(url)[0]


# ───────────────────────── crawler + audit ─────────────────────────

def _page_facts(url: str, r, soup) -> dict:
    t = soup.title.string.strip() if soup.title and soup.title.string else ""
    md = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    robots = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    canon = soup.find("link", rel=lambda v: v and "canonical" in v)
    host = urlparse(r.url).hostname
    links_in, links_out = set(), set()
    for a in soup.find_all("a", href=True):
        h = urldefrag(urljoin(r.url, a["href"]))[0]
        if not h.startswith("http"):
            continue
        (links_in if urlparse(h).hostname == host else links_out).add(h)
    imgs = soup.find_all("img")
    jsonld = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            d = json.loads(s.string or "{}")
            for item in (d if isinstance(d, list) else d.get("@graph", [d]) if isinstance(d, dict) else []):
                if isinstance(item, dict) and item.get("@type"):
                    jsonld += item["@type"] if isinstance(item["@type"], list) else [item["@type"]]
        except (ValueError, TypeError, AttributeError):
            jsonld.append("invalid JSON-LD")
    body = soup.body or soup
    for s in body(["script", "style", "noscript"]):
        s.decompose()
    text = re.sub(r"\s+", " ", body.get_text(" ")).strip()
    return {"url": url, "final": r.url, "status": r.status_code, "hops": len(r.history), "ms": int(r.elapsed.total_seconds() * 1000),
            "kb": round(len(r.content) / 1024), "title": t, "desc": (md.get("content") or "").strip() if md else None,
            "h1": [h.get_text(" ", strip=True)[:120] for h in soup.find_all("h1")], "h2": [h.get_text(" ", strip=True)[:100] for h in soup.find_all("h2")][:20],
            "canonical": canon.get("href") if canon else None, "noindex": bool(robots and "noindex" in (robots.get("content") or "").lower()),
            "viewport": bool(soup.find("meta", attrs={"name": "viewport"})), "lang": (soup.html.get("lang") if soup.html else None),
            "hreflang": len(soup.find_all("link", hreflang=True)), "og": bool(soup.find("meta", property="og:title")),
            "schema": sorted(set(map(str, jsonld))), "words": len(text.split()), "imgs": len(imgs),
            "no_alt": sum(1 for i in imgs if not (i.get("alt") or "").strip()), "internal": sorted(links_in)[:300], "external": sorted(links_out)[:100]}


def crawl(start: str, max_pages: int = 30) -> dict:
    import requests
    from bs4 import BeautifulSoup
    from urllib import robotparser
    start = _norm(start)
    root = f"{urlparse(start).scheme}://{urlparse(start).netloc}"
    S = requests.Session()
    S.headers["User-Agent"] = UA
    site = {"start": start, "root": root, "robots": None, "sitemaps": [], "sitemap_urls": [], "pages": [], "errors": [], "blocked": []}
    rp = robotparser.RobotFileParser()
    try:
        rr = S.get(root + "/robots.txt", timeout=15)
        if rr.ok and "text" in rr.headers.get("content-type", "text"):
            site["robots"] = rr.text[:4000]
            rp.parse(rr.text.splitlines())
            site["sitemaps"] = re.findall(r"(?im)^sitemap:\s*(\S+)", rr.text)
        else:
            rp.parse([])
    except Exception as exc:
        site["errors"].append(f"robots.txt: {type(exc).__name__}")
        rp.parse([])
    for sm in (site["sitemaps"] or [root + "/sitemap.xml"])[:3]:
        try:
            x = S.get(sm, timeout=20)
            if x.ok:
                locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", x.text)
                if any(l.endswith(".xml") for l in locs[:5]):   # sitemap index: read the first child sitemaps
                    for child in [l for l in locs if l.endswith(".xml")][:3]:
                        try:
                            site["sitemap_urls"] += re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", S.get(child, timeout=20).text)
                        except Exception:
                            pass
                else:
                    site["sitemap_urls"] += locs
                if not site["sitemaps"]:
                    site["sitemaps"] = [sm]
        except Exception:
            pass
    site["sitemap_urls"] = site["sitemap_urls"][:1000]
    queue, seen = [start], {start}
    while queue and len(site["pages"]) < max_pages:
        url = queue.pop(0)
        if not rp.can_fetch(UA, url):
            site["blocked"].append(url)
            continue
        try:
            r = S.get(url, timeout=20, allow_redirects=True)
        except Exception as exc:
            site["pages"].append({"url": url, "status": 0, "error": type(exc).__name__})
            continue
        if "html" not in r.headers.get("content-type", ""):
            continue
        f = _page_facts(url, r, BeautifulSoup(r.text, "html.parser"))
        site["pages"].append(f)
        for l in f["internal"]:
            if l not in seen and not re.search(r"\.(jpg|jpeg|png|gif|webp|svg|pdf|zip|mp4|css|js)$|/cart|/checkout|/account|\?", l, re.I):
                seen.add(l)
                queue.append(l)
        time.sleep(0.3)   # be polite
    return site


def link_status(urls: list[str], n: int = 40) -> dict:
    import requests
    from concurrent.futures import ThreadPoolExecutor

    def one(u):
        try:
            r = requests.head(u, timeout=10, allow_redirects=True, headers={"User-Agent": UA})
            if r.status_code in (405, 403):
                r = requests.get(u, timeout=10, allow_redirects=True, headers={"User-Agent": UA}, stream=True)
            return u, r.status_code
        except Exception as exc:
            return u, type(exc).__name__
    with ThreadPoolExecutor(max_workers=8) as ex:
        return dict(ex.map(one, urls[:n]))


def pagespeed(url: str) -> dict:
    import requests
    try:
        j = requests.get("https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                         params={"url": url, "strategy": "mobile", "category": "performance"}, timeout=90).json()
        lh = j.get("lighthouseResult", {})
        au = lh.get("audits", {})
        field = j.get("loadingExperience", {}).get("metrics", {})
        val = lambda k: au.get(k, {}).get("displayValue", "")
        return {"ok": "lighthouseResult" in j, "score": round((lh.get("categories", {}).get("performance", {}).get("score") or 0) * 100),
                "lcp": val("largest-contentful-paint"), "cls": val("cumulative-layout-shift"), "tbt": val("total-blocking-time"),
                "field": {k: v.get("category") for k, v in field.items()}, "error": j.get("error", {}).get("message", "")}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


def audit(url: str, max_pages: int = 30) -> dict:
    site = crawl(url, max_pages)
    pages = [p for p in site["pages"] if p.get("status") == 200 and "title" in p]
    issues = []

    def add(sev, area, msg, fix, urls=()):
        issues.append({"sev": sev, "area": area, "msg": msg, "fix": fix, "urls": list(urls)[:15], "count": len(urls) or 1})
    if not pages:
        add("high", "Crawl", "Walang mabasang page (blocked, down, o JavaScript-only)", "Tingnan kung bukas ang site at kung pinapayagan ng robots.txt ang crawler")
    bad = [p for p in site["pages"] if p.get("status", 200) >= 400 or p.get("status") == 0]
    if bad:
        add("high", "Technical", f"{len(bad)} page na error (4xx/5xx o hindi maabot)", "Ayusin o i-301 redirect sa tamang page", [p["url"] for p in bad])
    if not site["robots"]:
        add("medium", "Technical", "Walang robots.txt", "Gumawa ng robots.txt na may 'Sitemap:' line")
    if not site["sitemap_urls"]:
        add("medium", "Technical", "Walang nakitang XML sitemap", "Gumawa ng sitemap.xml at i-submit sa Google Search Console")
    if site["start"].startswith("http://") or any(p["final"].startswith("http://") for p in pages):
        add("high", "Technical", "May pages na hindi HTTPS", "I-redirect lahat sa HTTPS")
    chains = [p for p in pages if p["hops"] > 1]
    if chains:
        add("medium", "Technical", "Redirect chains (2+ hops)", "Diretsong i-redirect sa huling URL", [p["url"] for p in chains])
    for key, label, lo, hi in (("title", "Title", 15, 60), ("desc", "Meta description", 70, 160)):
        missing = [p["url"] for p in pages if not p[key]]
        if missing:
            add("high" if key == "title" else "medium", "On-page", f"Walang {label}", f"Maglagay ng natatanging {label} na may main keyword", missing)
        long_ = [p["url"] for p in pages if p[key] and len(p[key]) > hi]
        if long_:
            add("low", "On-page", f"{label} lampas {hi} characters (mapuputol sa Google)", f"Paikliin sa ≤{hi}", long_)
        short = [p["url"] for p in pages if p[key] and len(p[key]) < lo]
        if short:
            add("low", "On-page", f"{label} masyadong maikli (<{lo})", "Gawing mas descriptive", short)
        dup = defaultdict(list)
        for p in pages:
            if p[key]:
                dup[p[key].strip().lower()].append(p["url"])
        d = [u for us in dup.values() if len(us) > 1 for u in us]
        if d:
            add("medium", "On-page", f"Duplicate {label}", "Gawing unique ang bawat page", d)
    no_h1 = [p["url"] for p in pages if not p["h1"]]
    if no_h1:
        add("medium", "On-page", "Walang H1", "Isang malinaw na H1 bawat page", no_h1)
    many_h1 = [p["url"] for p in pages if len(p["h1"]) > 1]
    if many_h1:
        add("low", "On-page", "Higit sa isang H1", "Isa lang na H1; gawing H2 ang iba", many_h1)
    alt = [p["url"] for p in pages if p["no_alt"]]
    if alt:
        add("medium", "On-page", f"{sum(p['no_alt'] for p in pages)} larawan na walang alt text", "Maglagay ng descriptive alt text (accessibility + image search)", alt)
    thin = [p["url"] for p in pages[1:] if p["words"] < 300]
    if thin:
        add("medium", "Content", "Thin content (<300 salita)", "Dagdagan ng kapaki-pakinabang na content, FAQs, o pagsamahin ang mga page", thin)
    noidx = [p["url"] for p in pages if p["noindex"]]
    if noidx:
        add("high", "Indexing", "May noindex na pages", "Tiyaking sinadya; alisin ang noindex sa pages na dapat lumabas sa Google", noidx)
    nocanon = [p["url"] for p in pages if not p["canonical"]]
    if nocanon:
        add("low", "Indexing", "Walang canonical tag", "Maglagay ng self-referencing canonical", nocanon)
    noview = [p["url"] for p in pages if not p["viewport"]]
    if noview:
        add("high", "Mobile", "Walang mobile viewport meta", '<meta name="viewport" content="width=device-width, initial-scale=1">', noview)
    if pages and not any(p["schema"] for p in pages):
        add("medium", "Structured data", "Walang structured data (JSON-LD)", "Organization + WebSite sa home; Product/Article/FAQPage sa tamang pages")
    if pages and not pages[0]["lang"]:
        add("low", "Technical", "Walang lang attribute sa <html>", '<html lang="en"> o "fil"')
    noog = [p["url"] for p in pages if not p["og"]]
    if noog:
        add("low", "Social", "Walang Open Graph tags", "og:title, og:description, og:image para maganda sa FB/Messenger", noog)
    slow = [p["url"] for p in pages if p["ms"] > 1500]
    if slow:
        add("medium", "Speed", "Mabagal sumagot ang server (>1.5s)", "Caching / mas mabilis na hosting / CDN", slow)
    crawled = {p["url"] for p in pages} | {p["final"] for p in pages}
    linked = {l for p in pages for l in p["internal"]}
    if site["sitemap_urls"] and len(pages) < 30:
        orphans = [u for u in site["sitemap_urls"][:300] if u not in linked and u not in crawled][:50]
        if orphans:
            add("low", "Architecture", "Posibleng orphan pages (nasa sitemap pero walang internal link sa na-crawl)", "Lagyan ng internal links mula sa kaugnay na pages", orphans)
    ext = sorted({l for p in pages for l in p["external"]})
    st = link_status(ext, 40) if ext else {}
    broken = [u for u, s in st.items() if not isinstance(s, int) or s >= 400]
    if broken:
        add("medium", "Links", f"{len(broken)} sirang external link", "Palitan o alisin", broken)
    ps = pagespeed(site["start"]) if pages else {"ok": False}
    if ps.get("ok") and ps["score"] < 50:
        add("high", "Core Web Vitals", f"Mobile performance score {ps['score']}/100 (LCP {ps['lcp']}, CLS {ps['cls']})",
            "I-compress ang images, bawasan ang JavaScript, lazy-load, gumamit ng CDN")
    elif ps.get("ok") and ps["score"] < 90:
        add("medium", "Core Web Vitals", f"Mobile performance score {ps['score']}/100", "Tingnan ang PageSpeed suggestions")
    w = {"high": 8, "medium": 4, "low": 1}
    score = max(0, 100 - sum(w[i["sev"]] for i in issues))
    issues.sort(key=lambda i: ("high", "medium", "low").index(i["sev"]))
    return {"site": site, "pages": pages, "issues": issues, "score": score, "pagespeed": ps, "external_checked": len(st)}


# ───────────────────────── keywords ─────────────────────────

INTENT = [("transactional", r"\b(buy|order|shop|bili|bilhin|price|presyo|magkano|discount|sale|cod|shopee|lazada|tiktok shop|deliver|near me)\b"),
          ("commercial", r"\b(best|top|review|reviews|vs|versus|compare|legit|worth|alternative|recommended|sulit)\b"),
          ("informational", r"\b(how|what|why|when|paano|ano|bakit|kailan|guide|tips|meaning|ibig sabihin|tutorial|benefits|side effects)\b")]


def suggest(q: str, hl: str = "en", gl: str = "ph") -> list[str]:
    import requests
    out = []
    try:
        r = requests.get("https://suggestqueries.google.com/complete/search", params={"client": "firefox", "hl": hl, "gl": gl, "q": q},
                         timeout=10, headers={"User-Agent": UA})
        out += r.json()[1]
    except Exception:
        pass
    try:
        r = requests.get("https://duckduckgo.com/ac/", params={"q": q, "kl": f"{gl}-{hl}"}, timeout=10, headers={"User-Agent": UA})
        out += [x.get("phrase", "") for x in r.json()]
    except Exception:
        pass
    return [s for s in out if s]


def keywords(seed: str) -> dict:
    from concurrent.futures import ThreadPoolExecutor
    seed = seed.strip().lower()
    mods = ["", "best", "paano", "how to", "ano ang", "review", "vs", "for", "legit", "where to buy", "benefits", "tips", "near me"] + list("abcdefghijklmnoprstuvwy")
    qs = [f"{m} {seed}".strip() if m in ("best", "paano", "how to", "ano ang", "where to buy") else f"{seed} {m}".strip() for m in mods]
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(suggest, qs))
    kws = []
    for lst in res:
        for k in lst:
            k = re.sub(r"\s+", " ", k.lower()).strip()
            if k and k not in kws:
                kws.append(k)
    rows = []
    for k in kws[:300]:
        intent = next((name for name, pat in INTENT if re.search(pat, k)), "navigational" if len(k.split()) <= 2 else "informational")
        rows.append({"keyword": k, "intent": intent, "words": len(k.split()), "long_tail": len(k.split()) >= 4,
                     "question": bool(re.match(r"(how|what|why|when|where|which|paano|ano|bakit|saan|kailan|magkano)\b", k))})
    seedw = set(seed.split())
    clusters = defaultdict(list)
    for r in rows:
        toks = [t for t in r["keyword"].split() if t not in seedw and t not in STOP and len(t) > 2]
        clusters[toks[0] if toks else "(core)"].append(r["keyword"])
    top = dict(sorted(clusters.items(), key=lambda kv: -len(kv[1]))[:20])
    return {"seed": seed, "rows": rows, "clusters": top, "ok": bool(rows),
            "note": "Libreng sources (autocomplete) ay walang search volume o difficulty: gamitin ang Google Keyword Planner / Ahrefs / SEMrush para doon."}


# ───────────────────────── brief, competitor, GEO ─────────────────────────

BRIEF_SCHEMA = {"type": "object", "properties": {
    "title_options": {"type": "array", "items": {"type": "string"}}, "meta_description": {"type": "string"}, "h1": {"type": "string"},
    "search_intent": {"type": "string"}, "outline": {"type": "array", "items": {"type": "string"}}, "faqs": {"type": "array", "items": {"type": "string"}},
    "entities": {"type": "array", "items": {"type": "string"}}, "internal_links": {"type": "array", "items": {"type": "string"}},
    "schema": {"type": "array", "items": {"type": "string"}}, "word_count": {"type": "integer"}, "cta": {"type": "string"},
    "geo_tips": {"type": "array", "items": {"type": "string"}}},
    "required": ["title_options", "meta_description", "h1", "search_intent", "outline", "faqs", "entities", "internal_links", "schema", "word_count", "cta", "geo_tips"],
    "additionalProperties": False}


def brief(keyword: str, site: str = "") -> dict:
    import ai
    kw = keywords(keyword)
    qs = [r["keyword"] for r in kw["rows"] if r["question"]][:12]
    related = [r["keyword"] for r in kw["rows"] if not r["question"]][:25]
    b = None
    if ai.available():
        b = ai._ask_json("You are an SEO manager for a Philippine brand. Write a practical content brief. Plain, accurate, no invented facts or prices; "
                         "optimise for Google and for AI answers (clear definitions, entities, FAQs, structured data).",
                         f"Main keyword: {keyword}\nSite: {site or '-'}\nPeople also search: {', '.join(related)}\nQuestions: {', '.join(qs)}", BRIEF_SCHEMA, 4000)
    if not b:
        k = keyword.strip()
        b = {"title_options": [f"{k.title()}: Complete Guide (2026)", f"Best {k.title()} sa Pilipinas: Ano ang Dapat Malaman", f"{k.title()}: Tips, FAQs at Paano Pumili"],
             "meta_description": f"Lahat ng dapat malaman tungkol sa {k}: paano pumili, mga tip at sagot sa karaniwang tanong."[:155],
             "h1": k.title(), "search_intent": next((r["intent"] for r in kw["rows"] if r["keyword"] == k.lower()), "informational"),
             "outline": [f"Ano ang {k}?"] + [c.title() for c in list(kw["clusters"])[:6] if c != "(core)"] + ["FAQs", "Konklusyon + CTA"],
             "faqs": qs[:8], "entities": list(kw["clusters"])[:10], "internal_links": ["Product / category page", "Kaugnay na blog post", "Contact / Shop page"],
             "schema": ["Article", "FAQPage", "BreadcrumbList"], "word_count": 1200, "cta": "Tingnan ang produkto / Mag-message sa amin",
             "geo_tips": ["Simulan sa 2-3 pangungusap na direktang sagot", "Gumamit ng FAQ na may maikling sagot", "Ilagay ang brand at entities nang malinaw", "Magdagdag ng Organization at FAQPage schema"]}
        b["by"] = "template"
    else:
        b["by"] = ai.provider()
    return {"keyword": keyword, "brief": b, "kw": kw}


def competitor(mine: str, others: list[str]) -> dict:
    sites = []
    for u in [mine] + others[:4]:
        if not u.strip():
            continue
        s = crawl(u, 8)
        pages = [p for p in s["pages"] if p.get("status") == 200 and "title" in p]
        terms = Counter(t for p in pages for t in re.findall(r"[a-zñ]{4,}", " ".join([p["title"]] + p["h1"] + p["h2"]).lower()) if t not in STOP)
        ps = pagespeed(s["start"]) if pages else {"ok": False}
        sites.append({"url": s["start"], "pages": len(pages), "avg_words": round(sum(p["words"] for p in pages) / len(pages)) if pages else 0,
                      "schema": sorted({t for p in pages for t in p["schema"]}), "sitemap_urls": len(s["sitemap_urls"]),
                      "titles": [p["title"] for p in pages[:5]], "terms": [t for t, _ in terms.most_common(15)], "speed": ps.get("score") if ps.get("ok") else None})
    if sites:
        mine_terms = set(sites[0]["terms"])
        for s in sites[1:]:
            s["gap"] = [t for t in s["terms"] if t not in mine_terms][:10]
    return {"sites": sites}


GEO_Q = ("Check the AI search / generative engine visibility of the brand '{brand}' (website: {site}) in the Philippines. Search the web as a user would. "
         "Report: 1) what sources and answers come up for the brand and for its main product category, 2) whether the brand is cited, by whom, and how it is "
         "described, 3) competitors that AI answers mention instead, 4) entity signals (Wikipedia/Wikidata, Google Business Profile, marketplaces, social "
         "profiles, consistent name/address/phone), 5) the top 8 actions to get cited more (content, FAQs, schema, PR, reviews). Cite sources.")


def geo(brand: str, site: str = "") -> dict:
    import osint
    out = {"brand": brand, "site": site, "web": osint.claude_web(GEO_Q.format(brand=brand, site=site or "-"), "topic", "Content research"),
           "wiki": osint.wikipedia(brand), "schema": [], "sameas": []}
    if site:
        try:
            s = crawl(site, 1)
            if s["pages"] and "schema" in s["pages"][0]:
                out["schema"] = s["pages"][0]["schema"]
        except Exception:
            pass
    tips = []
    if not out["wiki"].get("found"):
        tips.append("Walang Wikipedia page: magtayo ng ibang authoritative mentions (news, directories, marketplaces) at Wikidata kung karapat-dapat")
    if site and not any(t in ("Organization", "LocalBusiness", "Store", "Brand") for t in out["schema"]):
        tips.append("Magdagdag ng Organization/LocalBusiness schema na may sameAs (FB, IG, TikTok, Shopee)")
    tips += ["Gumawa ng FAQ pages na may maikli at direktang sagot", "Pare-parehong pangalan, address at contact sa lahat ng listing",
             "Kumuha ng reviews at banggit sa PH media / bloggers", "Maglagay ng malinaw na 'About' at product facts (walang exaggerated claims)"]
    out["tips"] = tips
    return out


# ───────────────────────── report ─────────────────────────

def save_csv(rows: list[dict], path: Path) -> str:
    if not rows:
        return ""
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(dict.fromkeys(k for r in rows for k in r)), extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (", ".join(v) if isinstance(v, list) else v) for k, v in r.items()})
    return path.name


def render(task: str, target: str, res: dict, base: str) -> str:
    e = htmlmod.escape
    body = []
    if task == "audit":
        a = res
        col = "#3ddc84" if a["score"] >= 80 else "#ffb02e" if a["score"] >= 50 else "#e84a5f"
        ps = a["pagespeed"]
        body.append(f"<div class='card'><h2>Score <span class='lvl' style='background:{col}'>{a['score']}/100</span></h2>"
                    f"<p>{len(a['pages'])} page na na-crawl · {len(a['site']['sitemap_urls'])} URL sa sitemap · robots.txt: {'meron' if a['site']['robots'] else 'wala'} · "
                    f"{a['external_checked']} external link na na-check</p>"
                    + (f"<p>⚡ PageSpeed (mobile): <b>{ps['score']}/100</b> · LCP {e(ps['lcp'])} · CLS {e(ps['cls'])} · TBT {e(ps['tbt'])}"
                       + (f" · Field data: {e(json.dumps(ps['field']))}" if ps.get('field') else "") + "</p>" if ps.get("ok") else
                       f"<p class='muted'>PageSpeed: hindi nakuha ({e(ps.get('error', ''))}). Subukan sa pagespeed.web.dev</p>") + "</div>")
        rows = "".join(f"<tr><td><span class='pill {i['sev']}'>{i['sev'].upper()}</span></td><td>{e(i['area'])}</td><td>{e(i['msg'])}"
                       + (f"<details><summary>{i['count']} URL</summary><small>{'<br>'.join(e(u) for u in i['urls'])}</small></details>" if i["urls"] else "")
                       + f"</td><td>{e(i['fix'])}</td></tr>" for i in a["issues"]) or "<tr><td colspan=4>✅ Walang nakitang isyu</td></tr>"
        body.append(f"<h2>🛠 Issues (pinakamahalaga muna)</h2><table><tr><th>Priority</th><th>Area</th><th>Issue</th><th>Ayos</th></tr>{rows}</table>")
        pr = "".join(f"<tr><td><a href='{e(p['url'])}' target='_blank'>{e(p['url'][:70])}</a></td><td>{e(p['title'][:70])}</td><td>{len(p['title'])}</td>"
                     f"<td>{len(p['desc'] or '')}</td><td>{len(p['h1'])}</td><td>{p['words']}</td><td>{p['no_alt']}</td><td>{e(', '.join(p['schema'])[:40])}</td><td>{p['ms']}</td></tr>"
                     for p in a["pages"])
        body.append(f"<h2>📄 Pages</h2><table><tr><th>URL</th><th>Title</th><th>T len</th><th>Desc len</th><th>H1</th><th>Words</th><th>No alt</th><th>Schema</th><th>ms</th></tr>{pr}</table>")
    elif task == "keywords":
        k = res
        cl = "".join(f"<div class='post'><b>{e(c)}</b> <span class='muted'>({len(ks)})</span><br><small>{e(' · '.join(ks[:14]))}</small></div>" for c, ks in k["clusters"].items())
        rows = "".join(f"<tr><td>{e(r['keyword'])}</td><td>{e(r['intent'])}</td><td>{'✔' if r['long_tail'] else ''}</td><td>{'❓' if r['question'] else ''}</td></tr>" for r in k["rows"][:200])
        body.append(f"<p class='muted'>{e(k['note'])}</p><h2>🧩 Clusters</h2>{cl or '<p>Walang nakuha (offline?)</p>'}"
                    f"<h2>🔑 Keywords ({len(k['rows'])})</h2><table><tr><th>Keyword</th><th>Intent</th><th>Long-tail</th><th>Tanong</th></tr>{rows}</table>")
    elif task == "brief":
        b = res["brief"]
        lst = lambda xs: "".join(f"<li>{e(str(x))}</li>" for x in xs)
        body.append(f"<div class='card'><p><b>Intent:</b> {e(b['search_intent'])} · <b>Haba:</b> ~{b['word_count']} salita · <b>by</b> {e(b.get('by', ''))}</p>"
                    f"<h4>Title options</h4><ol>{lst(b['title_options'])}</ol><h4>Meta description</h4><p>{e(b['meta_description'])}</p>"
                    f"<h4>H1</h4><p>{e(b['h1'])}</p><h4>Outline</h4><ol>{lst(b['outline'])}</ol><h4>FAQs</h4><ul>{lst(b['faqs'])}</ul>"
                    f"<h4>Entities / topics to cover</h4><p>{e(', '.join(b['entities']))}</p><h4>Internal links</h4><ul>{lst(b['internal_links'])}</ul>"
                    f"<h4>Schema</h4><p>{e(', '.join(b['schema']))}</p><h4>CTA</h4><p>{e(b['cta'])}</p><h4>AI search (GEO) tips</h4><ul>{lst(b['geo_tips'])}</ul></div>")
    elif task == "competitor":
        rows = "".join(f"<tr><td><a href='{e(s['url'])}' target='_blank'>{e(s['url'][:50])}</a>{' (ikaw)' if i == 0 else ''}</td><td>{s['pages']}</td><td>{s['avg_words']}</td>"
                       f"<td>{s['sitemap_urls']}</td><td>{e(', '.join(s['schema'])[:60])}</td><td>{s['speed'] if s['speed'] is not None else '?'}</td>"
                       f"<td><small>{e(', '.join(s['terms'][:10]))}</small></td><td><small>{e(', '.join(s.get('gap', [])))}</small></td></tr>" for i, s in enumerate(res["sites"]))
        body.append("<table><tr><th>Site</th><th>Pages crawled</th><th>Avg words</th><th>Sitemap URLs</th><th>Schema</th><th>Speed</th><th>Top topics</th>"
                    f"<th>Topic gap vs you</th></tr>{rows}</table><p class='muted'>Topic gap = mga salitang madalas sa titles/headings nila pero wala sa iyo.</p>")
    elif task == "geo":
        import osint
        w = res.get("web") or {}
        body.append((f"<div class='card'>{osint._md(w['text'])}</div><ul>" + "".join(f"<li><a href='{e(s['url'])}' target='_blank'>{e(s['title'] or s['url'])}</a></li>" for s in w.get("sources", [])[:30]) + "</ul>")
                    if w.get("text") else "<p class='muted'>Para sa totoong AI search check, i-set ang Claude bilang AI provider sa ⚙️ (gumagamit ng web search).</p>")
        body.append(f"<h2>Signals</h2><p>Wikipedia: {'✅ ' + e(res['wiki'].get('title', '')) if res['wiki'].get('found') else '❌ wala'} · Schema sa home: {e(', '.join(res['schema']) or 'wala')}</p>"
                    f"<h2>Actions</h2><ul>{''.join('<li>' + e(t) + '</li>' for t in res['tips'])}</ul>")
    csvs = "".join(f"<a class='btn' href='{base}{e(f)}' download>⬇ {e(f)}</a> " for f in res.get("_csv", []) if f)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>📈 SEO: {e(target)}</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{font:15px/1.5 system-ui,sans-serif;background:#0b2a3a;color:#eafaff;margin:0;padding:22px;max-width:1150px;margin:auto}} .muted{{color:#9cc7d6;font-size:13px}}
.card,.post{{background:#103a4f;border:1px solid #1f6a86;border-radius:14px;padding:12px 16px;margin:10px 0}} table{{width:100%;border-collapse:collapse;font-size:13px}}
td,th{{border-bottom:1px solid #1f6a86;padding:5px;text-align:left;vertical-align:top}} a{{color:#7fe3ff}} .lvl{{color:#10202a;border-radius:8px;padding:2px 10px}}
.pill{{border-radius:99px;padding:1px 8px;font-size:11px;font-weight:800;color:#10202a}} .pill.high{{background:#ff8a8a}} .pill.medium{{background:#ffd23d}} .pill.low{{background:#9cc7d6}}
.btn{{background:#ffd23d;color:#2a1a00;border-radius:8px;padding:6px 10px;font-weight:700;text-decoration:none;display:inline-block;margin:4px 0}}</style></head>
<body><h1>📈 {e(TASKS[task])}</h1><p><b>{e(target)}</b> · by Asher (SEO Manager) {csvs}</p>{''.join(body)}
<p class="muted">Walang search volume, rankings, clicks o conversions dito: kailangan ang Google Search Console / GA4 (Google login) o bayad na tools (Ahrefs, SEMrush).
I-verify bago i-implement; ang audit ay snapshot ng mga na-crawl na page lang.</p></body></html>"""
