"""Hazel's command box: one instruction (+ any files) from the dashboard, routed to the right team.

  KYB / KYC / due diligence            → compliance team (KYB on the attached documents or a Drive link)
  affiliate + a product link            → Affiliate Studio (5 videos)
  research / osint / sino si … / alamin → Taks (OSINT research)
  post / caption / reel / content / videos or photos attached → Content Hub (inspo links in the text are watched)
  review / contract / policy, or documents only → compliance document review
  nothing attached                      → Taks researches the instruction (anything)
"""
from __future__ import annotations

import re
from pathlib import Path

import osint

MEDIA = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv", ".3gp", ".wmv", ".flv", ".mts", ".m2ts",
         ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
DOCS = {".pdf", ".docx", ".doc", ".txt", ".md", ".html", ".htm", ".rtf"}

RE = {
    "seo": re.compile(r"\b(seo|keyword research|keywords?|content brief|site audit|seo audit|backlinks?|rankings?|serp|geo|ai search|ai overview|chatgpt visibility|meta description)\b", re.I),
    "kyb": re.compile(r"\b(kyb|kyc|ubo|due diligence|onboard(ing)?|merchant review|edd|beneficial owner)\b", re.I),
    "affiliate": re.compile(r"\b(affiliate|5 videos?|limang video|five videos?)\b", re.I),
    "research": re.compile(r"\b(research|i-?research|osint|imbestiga(han)?|investigate|alamin|sino si|sino ang|hanapin|background check|look ?up|find out|"
                           r"ano ang|what is|who is|saliksikin)\b", re.I),
    "content": re.compile(r"\b(post|i-?post|caption|reels?|tiktok|content|schedule|i-?schedule|edit|i-?edit|gawan|inspo|upload|fb|ig|instagram|facebook)\b", re.I),
    "review": re.compile(r"\b(review|i-?review|contract|kontrata|privacy|dpa|policy|compliance check|i-?check ang (doc|document|kontrata))\b", re.I),
}
PRODUCT_LINK = re.compile(r"https?://\S*(shopee\.|shope\.ee|s\.shopee|tiktok\.com/\S*(product|view/product)|vt\.tiktok\.com|lazada\.)\S*", re.I)
DRIVE_LINK = re.compile(r"https?://(drive|docs)\.google\.com/\S+", re.I)
PURPOSE = [("KYC / KYB due diligence", r"kyc|kyb|due diligence|onboard"), ("AML / sanctions / PEP review", r"aml|sanction|pep|launder"),
           ("Fraud investigation", r"fraud|scam|modus|estafa|panloloko"), ("Vendor due diligence", r"vendor|supplier"),
           ("Brand / impersonation check", r"impersonat|fake account|poser|brand"), ("Competitor / market research", r"competitor|market|kakumpitensya"),
           ("Content research", r"content|trend|viral|hook")]


CANCEL = re.compile(r"^\s*(cancel|i-?cancel|stop|ihinto|itigil|huwag (na )?(i-?)?post|wag (na )?(i-?)?post)\b", re.I)


def is_cancel(text: str) -> bool:
    """'cancel', 'cancel David', 'cancel lahat ng posts', 'stop posting', 'wag na i-post'."""
    return bool(CANCEL.search(text)) and not re.search(r"https?://", text)


def subject(text: str) -> str:
    """The instruction minus links and command words: what the instruction is about."""
    t = re.sub(r"https?://\S+", " ", text)
    for r in RE.values():
        t = r.sub(" ", t)
    t = re.sub(r"\b(please|paki|pa|mo|ito|ito ang|itong|yung|ang|ng|nga|naman|for|para sa|sa|kay|lahat|files?|naka-?attach|attached|bukas|ngayon)\b", " ", t, flags=re.I)
    t = re.sub(r"[\"“”:;,.!?]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


SKIP_START = {"sino", "ano", "research", "kyb", "kyc", "review", "paki", "please", "i-research", "alamin", "hanapin", "check", "i-check",
              "investigate", "imbestigahan", "osint", "who", "what", "find", "look"}


def entity(text: str) -> str:
    """The most specific thing named in the instruction: wallet, @handle, domain, company, then a person's name."""
    t = re.sub(r"https?://\S*(shopee|shope\.ee|tiktok\.com/\S*product)\S*", " ", text, flags=re.I)
    for pat in (r"\b(0x[a-fA-F0-9]{40}|bc1[a-z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34}|T[1-9A-HJ-NP-Za-km-z]{33})\b",
                r"(@[\w.]{2,40})", r"[\"“](.{3,80}?)[\"”]",
                r"\b((?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|ph|net|org|io|co|shop|store|online|xyz|app|biz|info)(?:\.[a-z]{2})?)\b",
                r"\b([A-Z][\w&.'-]*(?:\s+[A-Z][\w&.'-]*)*\s+(?:Inc|Corp|Corporation|Ltd|Limited|LLC|Co|Company|Holdings|OPC|Trading|Enterprises|Group)\b\.?)"):
        m = re.search(pat, t)
        if m:
            return m.group(1).strip()
    for m in re.finditer(r"\b([A-ZÑ][a-zñ]+(?:\s+(?:de|dela|del|delos|de la|[A-ZÑ][a-zñ]+)){1,4})\b", t):
        words = m.group(1).split()
        while words and words[0].lower() in SKIP_START:
            words = words[1:]
        if len(words) >= 2:
            return " ".join(words)
    return ""


def route(text: str, names: list[str]) -> dict:
    exts = [Path(n).suffix.lower() for n in names]
    media = [n for n, e in zip(names, exts) if e in MEDIA]
    docs = [n for n, e in zip(names, exts) if e in DOCS]
    links = re.findall(r"https?://[^\s<>\"']+", text)
    product = [l for l in links if PRODUCT_LINK.match(l)]
    drive = [l for l in links if DRIVE_LINK.match(l)]
    hit = {k: bool(r.search(text)) for k, r in RE.items()}
    purpose = next((p for p, pat in PURPOSE if re.search(pat, text, re.I)), "General research")
    if hit["seo"] and not hit["kyb"]:
        action = "seo"
    elif hit["kyb"]:
        action = "kyb"
    elif hit["affiliate"] and product:
        action = "affiliate"
    elif hit["research"] and not media:
        action = "research"
    elif hit["content"] or media:
        action = "content"
    elif docs or hit["review"]:
        action = "review" if docs else "research"
    else:
        action = "research"
    ent = entity(text)
    if not ent:   # a country on its own ("Research Seychelles country risk")
        ent = next((c.title() for c in osint.COUNTRIES if len(c) > 3 and re.search(rf"\b{re.escape(c)}\b", text, re.I)
                    and re.search(r"country|bansa|risk|sanction|fatf|jurisdiction", text, re.I)), "")
    subj = ent or subject(text)
    low = text.lower()
    seo_task = ("competitor" if "competitor" in low and len(links) > 1 else "brief" if "brief" in low else
                "geo" if re.search(r"\b(geo|ai search|ai overview|chatgpt)\b", low) else
                "keywords" if re.search(r"keyword", low) else "audit" if (links or (ent and "." in ent)) else "keywords")
    return {"action": action, "subject": subj, "seo_task": seo_task, "entity": ent, "links": links, "product": product, "drive": drive, "purpose": purpose,
            "media": media, "docs": docs, "notes": re.sub(r"https?://\S+", " ", text).strip(), "kind": _kind(subj, purpose) if ent else "topic"}


def _kind(subj: str, purpose: str) -> str:
    k = osint.detect(subj)
    if subj.lower() in osint.COUNTRIES:
        return "country"
    if k == "person" and purpose in ("Content research", "Competitor / market research") and not re.search(r"\b(sino|who)\b", subj, re.I):
        return "topic" if purpose != "Competitor / market research" else "competitor"
    return k


LABEL = {"seo": "📈 Asher (SEO)", "kyb": "🛡️ KYB (Pablo, Bailey, Charlie + Taks sweep)", "affiliate": "🛒 Affiliate Studio", "research": "🔎 Taks (OSINT research)",
         "content": "📱 Content Hub (JP, Asher, Shane, Jacob, Ashley, David)", "review": "⚖️ Compliance review (Pablo → Bailey → Charlie)"}
