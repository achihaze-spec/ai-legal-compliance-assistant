"""Website / URL due-diligence check for KYB.

Looks at: reachability and redirects, HTTPS and certificate, domain age (RDAP),
first archive snapshot (Wayback), the page itself (business name, privacy / terms /
contact / refund pages, contact details), red-flag keywords for high-risk activity,
and runs the Data Privacy Act check on the site's privacy policy when one is linked.

Every external lookup that fails is reported as "Analyst to run", never as clear.
"""
from __future__ import annotations

import datetime as dt
import re
import socket
import ssl
from urllib.parse import quote, urljoin, urlparse

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

RED_FLAGS = {
    "Gambling / betting": r"\b(casino|betting|sportsbook|sabong|e-sabong|online slots?|jackpot|baccarat|poker room)\b",
    "Crypto / investment": r"\b(crypto|bitcoin|usdt|forex|binary options?|investment plan|guaranteed (returns?|profits?|income)|double your money|daily roi|passive income)\b",
    "Adult content": r"\b(adult content|xxx|escort|cam girls?)\b",
    "Pharma without prescription": r"\b(no prescription|without (a )?prescription|buy (viagra|cialis|tramadol))\b",
    "Counterfeit": r"\b(replica|1:1 copy|class a|first copy|ua quality)\b",
    "Pressure / too good to be true": r"\b(limited slots?|act now|100% legit|guaranteed approval|risk[- ]free)\b",
}
PAGES = {
    "Privacy policy": r"privacy|data[- ]privacy|patakaran",
    "Terms": r"terms|conditions|kasunduan",
    "Contact": r"contact|makipag-ugnayan",
    "About": r"about|tungkol",
    "Refund / returns": r"refund|return|exchange",
}


def _registrable(host: str) -> str:
    parts = host.lower().strip(".").split(".")
    if len(parts) >= 3 and parts[-2] in ("com", "net", "org", "gov", "edu", "co") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])  # e.g. shop.example.com.ph -> example.com.ph
    return ".".join(parts[-2:])


def _cert(host: str) -> dict:
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=10) as sock, ctx.wrap_socket(sock, server_hostname=host) as s:
        c = s.getpeercert()
    exp = dt.datetime.strptime(c["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=dt.timezone.utc)
    issuer = dict(x[0] for x in c.get("issuer", ()))
    return {"valid": True, "expires": exp.date().isoformat(), "days_left": (exp - dt.datetime.now(dt.timezone.utc)).days,
            "issuer": issuer.get("organizationName", "")}


def _rdap(domain: str, requests) -> dict:
    r = requests.get(f"https://rdap.org/domain/{quote(domain)}", timeout=15, headers={"User-Agent": UA})
    r.raise_for_status()
    d = r.json()
    ev = {e.get("eventAction"): e.get("eventDate", "")[:10] for e in d.get("events", [])}
    created = ev.get("registration")
    age = (dt.date.today() - dt.date.fromisoformat(created)).days if created else None
    registrar = ""
    for ent in d.get("entities", []):
        if "registrar" in (ent.get("roles") or []):
            vc = ent.get("vcardArray", [None, []])[1]
            registrar = next((v[3] for v in vc if v and v[0] == "fn"), "")
    return {"created": created, "age_days": age, "expires": ev.get("expiration"), "registrar": registrar}


def _wayback_first(domain: str, requests) -> str | None:
    r = requests.get("https://web.archive.org/cdx/search/cdx", params={"url": domain, "limit": 1, "output": "json", "fl": "timestamp"},
                     timeout=20, headers={"User-Agent": UA})
    r.raise_for_status()
    rows = r.json()
    return f"{rows[1][0][:4]}-{rows[1][0][4:6]}-{rows[1][0][6:8]}" if len(rows) > 1 else None


def check(url: str, business_name: str = "") -> dict:
    import requests
    from bs4 import BeautifulSoup

    url = url.strip()
    if not re.match(r"https?://", url):
        url = "https://" + url
    host = urlparse(url).hostname or ""
    domain = _registrable(host)
    findings, facts, analyst = [], {"input": url, "domain": domain}, []
    add = lambda lvl, msg: findings.append({"level": lvl, "msg": msg})

    # DNS
    try:
        facts["ip"] = socket.gethostbyname(host)
    except OSError:
        add("high", "Hindi ma-resolve ang domain (walang DNS). Patay o pekeng website?")
        return {"url": url, "facts": facts, "findings": findings, "analyst": ["Manual check ng website"], "rating": "HIGH"}

    # page + redirects
    html, final = "", url
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": UA}, allow_redirects=True)
        final = r.url
        facts.update(status=r.status_code, final_url=final, redirects=[h.headers.get("location", "") for h in r.history])
        if r.status_code >= 400:
            add("medium", f"Sumagot ang site ng HTTP {r.status_code}")
        if urlparse(final).hostname and _registrable(urlparse(final).hostname) != domain:
            add("high", f"Nagre-redirect sa ibang domain: {urlparse(final).hostname}")
        html = r.text if "html" in r.headers.get("content-type", "") else ""
    except Exception as exc:
        add("medium", f"Hindi mabuksan ang site ({type(exc).__name__})")
        analyst.append("Buksan ang website nang manual")
    facts["https"] = final.startswith("https://")
    if not facts["https"]:
        add("medium", "Walang HTTPS (hindi naka-encrypt ang data ng customer)")

    # certificate
    try:
        facts["cert"] = _cert(urlparse(final).hostname or host)
        if facts["cert"]["days_left"] < 14:
            add("medium", f"Malapit nang mag-expire ang SSL certificate ({facts['cert']['expires']})")
    except Exception as exc:
        facts["cert"] = {"valid": False, "error": type(exc).__name__}
        if facts["https"]:
            add("high", "Invalid o may problema ang SSL certificate")

    # domain age (RDAP)
    try:
        facts["whois"] = _rdap(domain, requests)
        age = facts["whois"]["age_days"]
        if age is not None and age < 30:
            add("high", f"Napakabagong domain: {age} araw lang (rehistrado {facts['whois']['created']})")
        elif age is not None and age < 180:
            add("medium", f"Bagong domain: {age} araw (rehistrado {facts['whois']['created']})")
    except Exception as exc:
        facts["whois"] = {"error": type(exc).__name__}
        analyst.append(f"WHOIS / domain age para sa {domain}")

    # archive history
    try:
        facts["first_archived"] = _wayback_first(domain, requests)
        if not facts["first_archived"]:
            add("low", "Walang record sa Wayback Machine (walang history ang site)")
    except Exception:
        analyst.append(f"Wayback Machine history para sa {domain}")

    # page content
    if html:
        soup = BeautifulSoup(html, "html.parser")
        for s in soup(["script", "style", "noscript"]):
            s.decompose()
        text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
        facts["title"] = (soup.title.string or "").strip()[:150] if soup.title else ""
        links = [(a.get_text(" ", strip=True), urljoin(final, a.get("href", ""))) for a in soup.find_all("a", href=True)]
        found = {}
        for label, pat in PAGES.items():
            hit = next((h for t, h in links if re.search(pat, t + " " + h, re.I)), None)
            found[label] = hit
            if not hit and label in ("Privacy policy", "Terms", "Contact"):
                add("medium", f"Walang makitang {label} page")
        facts["pages"] = found
        facts["emails"] = sorted(set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text)))[:5]
        facts["phones"] = sorted(set(re.findall(r"(?:\+63|0)9\d{2}[\s-]?\d{3}[\s-]?\d{4}", text)))[:5]
        if not facts["emails"] and not facts["phones"]:
            add("medium", "Walang email o phone number sa homepage")
        flags = []
        for label, pat in RED_FLAGS.items():
            m = re.search(pat, text, re.I)
            if m:
                flags.append(label)
                add("high" if label in ("Gambling / betting", "Crypto / investment", "Counterfeit") else "medium",
                    f"Red-flag na aktibidad: {label} (“{m.group(0)}”)")
        facts["red_flags"] = flags
        if business_name:
            tokens = [t for t in re.findall(r"[a-z0-9]+", business_name.lower())
                      if len(t) > 2 and t not in ("inc", "corp", "corporation", "ltd", "llc", "company", "the", "and", "opc")]
            hay = (facts["title"] + " " + text[:20000] + " " + domain).lower()
            hit = sum(t in hay for t in tokens)
            facts["name_match"] = f"{hit}/{len(tokens)} salita ng pangalan nakita"
            if tokens and hit == 0:
                add("high", f"Hindi lumalabas sa website ang pangalang “{business_name}”")
        # Data Privacy Act check on the privacy policy page
        if found.get("Privacy policy"):
            try:
                import compliance
                pr = requests.get(found["Privacy policy"], timeout=20, headers={"User-Agent": UA})
                ptxt = re.sub(r"\s+", " ", BeautifulSoup(pr.text, "html.parser").get_text(" "))
                res = compliance.check(ptxt, "privacy_policy")
                score, level = compliance.score(res)
                facts["privacy_check"] = {"level": level, "score": score, "missing": [c["title"] for c in res.missing],
                                          "flags": [f["title"] for f in res.flags]}
                if level != "LOW":
                    add("medium", f"Privacy policy: {level} risk sa DPA check (kulang: {', '.join(facts['privacy_check']['missing'][:4]) or 'wala'})")
            except Exception:
                analyst.append("Basahin ang privacy policy page")
    rank = {"high": 3, "medium": 2, "low": 1}
    worst = max((rank[f["level"]] for f in findings), default=0)
    rating = {3: "HIGH", 2: "MEDIUM", 1: "LOW", 0: "LOW"}[worst]
    if analyst and rating == "LOW":
        rating = "INCOMPLETE"
    analyst += [f"Google Safe Browsing: https://transparencyreport.google.com/safe-browsing/search?url={quote(domain)}",
                f"Scam reports: https://www.scamadviser.com/check-website/{quote(domain)}"]
    return {"url": url, "facts": facts, "findings": findings, "analyst": analyst, "rating": rating}
