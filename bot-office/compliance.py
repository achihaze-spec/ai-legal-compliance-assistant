"""The real work behind the compliance bots.

Doc Reader  -> extract_text() + classify()
Reg Checker -> check()
Risk Scout  -> score() + render_report()

Rule-based on purpose: runs offline with no API key. Each rule is a plain dict,
so adding a law or clause is just adding an entry to the lists below.
"""
from __future__ import annotations

import html
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ───────────────────────── Doc Reader ─────────────────────────

def extract_text(path: Path) -> tuple[str, int]:
    """Return (text, pages). pages is 1 for non-paged formats."""
    ext = path.suffix.lower()
    data = path.read_bytes()
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages), len(reader.pages)
    if ext == ".docx":
        import docx
        d = docx.Document(io.BytesIO(data))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        return "\n".join(parts), 1
    if ext in (".html", ".htm"):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(data, "html.parser")
        for s in soup(["script", "style"]):
            s.decompose()
        return soup.get_text("\n"), 1
    return data.decode("utf-8", errors="replace"), 1


DOC_TYPES = {
    "regulation": [r"\brepublic act\b", r"\bbe it enacted\b", r"\bsection \d+\.", r"\bcircular\b", r"\bmemorandum circular\b", r"\bimplementing rules\b"],
    "privacy_policy": [r"\bprivacy (policy|notice|statement)\b", r"\bpersonal (data|information)\b", r"\bdata subject", r"\bcookies?\b"],
    "contract": [r"\bagreement\b", r"\bparties\b", r"\bwhereas\b", r"\bhereinafter\b", r"\bin witness whereof\b", r"\bterm of this\b"],
    "policy": [r"\bhandbook\b", r"\bemployees?\b", r"\bcode of conduct\b", r"\bpolicy\b"],
}
TYPE_LABEL = {"regulation": "Regulation / Law", "privacy_policy": "Privacy Policy", "contract": "Contract",
              "policy": "Internal Policy", "unknown": "General Document"}


def classify(text: str) -> str:
    t = text.lower()
    # Strong markers win outright: enacted laws and agency issuances are regulations.
    if re.search(r"\bbe it enacted\b|\brepublic act no\b|\bimplementing rules and regulations\b|\bmemorandum circular no\b", t):
        return "regulation"
    scores = {k: sum(len(re.findall(p, t)) for p in pats) for k, pats in DOC_TYPES.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else "unknown"


# ───────────────────────── Reg Checker ─────────────────────────
# A check "passes" if ANY of its patterns is found. Weight feeds the risk score.

PRIVACY_CHECKS = [
    dict(id="consent", title="Consent to processing", ref="RA 10173 Sec. 12(a), 13",
         weight=14, patterns=[r"\bconsent\b"],
         fix="State that personal data is processed with the data subject's freely given, specific, informed consent (or another lawful basis)."),
    dict(id="purpose", title="Purpose of processing stated", ref="RA 10173 Sec. 11(a)",
         weight=10, patterns=[r"\bpurpose", r"\bwe (use|process|collect)\b.{0,60}\bto\b"],
         fix="List the specific, legitimate purposes for which personal data is collected."),
    dict(id="rights", title="Data subject rights", ref="RA 10173 Sec. 16",
         weight=12, patterns=[r"\bright to (access|object|rectif|erasure|be informed|data portability)", r"\bdata subject rights?\b", r"\brectif", r"\berasure\b"],
         fix="Explain the rights to be informed, access, object, rectify, erase/block, data portability, and to file a complaint."),
    dict(id="retention", title="Retention period", ref="RA 10173 Sec. 11(e)",
         weight=8, patterns=[r"\bretain", r"\bretention\b", r"\bstored? for\b", r"\bdelet(e|ed|ion)\b.{0,40}\b(after|within)\b"],
         fix="Say how long personal data is kept and how it is disposed of."),
    dict(id="security", title="Security measures", ref="RA 10173 Sec. 20",
         weight=12, patterns=[r"\bsecurity measures?\b", r"\bencrypt", r"\b(organizational|physical|technical) (security|measures)\b", r"\baccess control"],
         fix="Describe organizational, physical and technical security measures (e.g. encryption, access control)."),
    dict(id="breach", title="Breach notification", ref="RA 10173 Sec. 20(f); NPC Circular 16-03 (72 hours)",
         weight=10, patterns=[r"\bbreach\b", r"\b72 hours\b", r"\bnotify\b.{0,40}\b(commission|npc|data subjects?)\b"],
         fix="Commit to notifying the NPC and affected data subjects within 72 hours of a personal data breach."),
    dict(id="dpo", title="Data Protection Officer / contact", ref="RA 10173 Sec. 21(b); IRR Sec. 26",
         weight=8, patterns=[r"\bdata protection officer\b", r"\bdpo\b", r"\bcontact us\b", r"\bprivacy@"],
         fix="Name a Data Protection Officer and give contact details."),
    dict(id="sharing", title="Third-party sharing disclosed", ref="RA 10173 Sec. 21; IRR Sec. 43-44",
         weight=8, patterns=[r"\bthird[- ]part(y|ies)\b", r"\bshare\b.{0,40}\b(with|to)\b", r"\bdisclos"],
         fix="Disclose who personal data is shared with and require data sharing / outsourcing agreements."),
    dict(id="sensitive", title="Sensitive personal information handled", ref="RA 10173 Sec. 13",
         weight=6, patterns=[r"\bsensitive personal\b", r"\b(health|medical|religio|government[- ]issued|tin|sss)\b"],
         fix="If sensitive personal information is processed, state the specific lawful basis under Sec. 13.", optional=True),
    dict(id="crossborder", title="Cross-border transfer", ref="RA 10173 Sec. 21",
         weight=5, patterns=[r"\b(outside|abroad|overseas|cross[- ]border|other countries)\b"],
         fix="If data leaves the Philippines, say so and keep the same level of protection.", optional=True),
]

CONTRACT_CHECKS = [
    dict(id="parties", title="Parties identified", ref="Civil Code Art. 1318", weight=8,
         patterns=[r"\bby and between\b", r"\bparties\b", r"\bhereinafter\b"], fix="Identify each party with full legal name and address."),
    dict(id="term", title="Term / effectivity", ref="Civil Code Art. 1193", weight=6,
         patterns=[r"\bterm\b", r"\beffective (date|upon)\b", r"\beffectivity\b"], fix="State when the agreement starts and ends."),
    dict(id="termination", title="Termination clause", ref="Civil Code Art. 1191", weight=10,
         patterns=[r"\bterminat"], fix="Add grounds and notice period for termination."),
    dict(id="confidentiality", title="Confidentiality", ref="Best practice", weight=8,
         patterns=[r"\bconfidential"], fix="Add a confidentiality clause covering both parties' information."),
    dict(id="liability", title="Limitation of liability", ref="Civil Code Art. 1170-1174", weight=8,
         patterns=[r"\blimitation of liability\b", r"\bliab(le|ility)\b"], fix="Cap each party's liability and exclude indirect damages."),
    dict(id="indemnity", title="Indemnification", ref="Best practice", weight=6,
         patterns=[r"\bindemni"], fix="State who indemnifies whom for third-party claims."),
    dict(id="law", title="Governing law", ref="Civil Code Art. 1306", weight=8,
         patterns=[r"\bgoverning law\b", r"\bgoverned by\b", r"\blaws of the (republic of the )?philippines\b"], fix="Specify the governing law (e.g. laws of the Philippines)."),
    dict(id="disputes", title="Dispute resolution / venue", ref="RA 9285 (ADR Act)", weight=6,
         patterns=[r"\barbitrat", r"\bvenue\b", r"\bdispute", r"\bcourts? of\b"], fix="Specify mediation/arbitration or the venue of court actions."),
    dict(id="dataprotection", title="Data protection clause", ref="RA 10173 Sec. 14 (outsourcing)", weight=8,
         patterns=[r"\bdata privacy act\b", r"\bpersonal (data|information)\b", r"\bdata protection\b"], fix="If personal data is shared, add a DPA-compliant data processing clause.", optional=True),
    dict(id="signature", title="Signature block", ref="Civil Code Art. 1356", weight=4,
         patterns=[r"\bin witness whereof\b", r"\bsigned\b", r"\bsignature\b"], fix="Add signature blocks for authorized signatories."),
]

RED_FLAGS = [
    dict(id="sell", title="Sells personal data", weight=20, patterns=[r"\bsell\b.{0,40}\b(personal|your) (data|information)\b", r"\b(personal|your) (data|information)\b.{0,40}\b(sold|sell)\b"]),
    dict(id="noconsent", title="Processing without consent", weight=18, patterns=[r"\bwithout (your |prior )?consent\b"]),
    dict(id="forever", title="Indefinite retention", weight=10, patterns=[r"\bindefinite(ly)?\b", r"\bforever\b", r"\bpermanently retain"]),
    dict(id="unilateral", title="Unilateral changes without notice", weight=8, patterns=[r"\bwithout (prior )?notice\b", r"\bsole discretion\b"]),
    dict(id="waiver", title="Waiver of rights", weight=10, patterns=[r"\bwaives? (any|all) (rights?|claims?)\b"]),
    dict(id="unlimited", title="Unlimited liability", weight=10, patterns=[r"\bunlimited liability\b"]),
]

OBLIGATION_RE = re.compile(r"[^.\n]{20,260}\b(shall|must|is required to|are required to)\b[^.\n]{10,260}[.\n]", re.I)


@dataclass
class CheckResult:
    doc_type: str
    passed: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    obligations: list = field(default_factory=list)


def _evidence(text: str, patterns: list[str]) -> str | None:
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            s, e = max(0, m.start() - 70), min(len(text), m.end() + 90)
            return re.sub(r"\s+", " ", text[s:e]).strip()
    return None


def check(text: str, doc_type: str) -> CheckResult:
    res = CheckResult(doc_type)
    low = text.lower()
    if doc_type == "regulation":
        seen = set()
        for m in OBLIGATION_RE.finditer(text):
            s = re.sub(r"\s+", " ", m.group(0)).strip()
            if s[:60] not in seen:
                seen.add(s[:60]); res.obligations.append(s)
            if len(res.obligations) >= 15:
                break
        return res

    mentions_personal = bool(re.search(r"\bpersonal (data|information)\b|\bprivacy\b", low))
    if doc_type == "contract":
        checks = CONTRACT_CHECKS  # has its own data-protection clause check
    elif doc_type in ("privacy_policy", "policy") or mentions_personal:
        checks = PRIVACY_CHECKS
    else:
        checks = PRIVACY_CHECKS

    for c in checks:
        ev = _evidence(text, c["patterns"])
        if ev:
            res.passed.append({**c, "evidence": ev})
        elif not c.get("optional"):
            res.missing.append(c)
    for f in RED_FLAGS:
        ev = _evidence(text, f["patterns"])
        if ev:
            res.flags.append({**f, "evidence": ev})
    return res


# ───────────────────────── Risk Scout ─────────────────────────

def score(res: CheckResult) -> tuple[int, str]:
    if res.doc_type == "regulation":
        return 0, "INFO"
    total = sum(c["weight"] for c in res.passed + res.missing) or 1
    s = round(100 * sum(c["weight"] for c in res.missing) / total) + sum(f["weight"] for f in res.flags)
    s = min(100, s)
    level = "HIGH" if s >= 50 else "MEDIUM" if s >= 25 else "LOW"
    return s, level


def render_report(name: str, text: str, pages: int, res: CheckResult, risk: int, level: str) -> str:
    e = html.escape
    color = {"HIGH": "#e84a5f", "MEDIUM": "#ff8a3d", "LOW": "#3ddc84", "INFO": "#4da3ff"}[level]
    words = len(text.split())

    def rows(items, ok):
        out = []
        for c in items:
            detail = f'<q>{e(c["evidence"])}</q>' if ok else f'<span class="fix">→ {e(c["fix"])}</span>'
            out.append(f'<li class="{"ok" if ok else "miss"}"><b>{"✅" if ok else "❌"} {e(c["title"])}</b>'
                       f' <small>{e(c["ref"])}</small><br>{detail}</li>')
        return "".join(out) or '<li class="muted">None</li>'

    flags = "".join(f'<li class="flag"><b>🚩 {e(f["title"])}</b><br><q>{e(f["evidence"])}</q></li>' for f in res.flags)
    if res.doc_type == "regulation":
        body = ('<h2>Key obligations found</h2><p class="muted">This looks like a law/regulation, so Risk Scout lists the '
                '"shall / must" duties instead of grading it.</p><ol>' +
                "".join(f"<li>{e(o)}</li>" for o in res.obligations) + "</ol>")
    else:
        body = (f'<h2>Missing ({len(res.missing)})</h2><ul>{rows(res.missing, False)}</ul>'
                + (f'<h2>Red flags ({len(res.flags)})</h2><ul>{flags}</ul>' if res.flags else "")
                + f'<h2>Covered ({len(res.passed)})</h2><ul>{rows(res.passed, True)}</ul>')
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Risk report — {e(name)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{font:15px/1.5 system-ui,sans-serif;background:#0d0b1a;color:#e9e6ff;max-width:820px;margin:0 auto;padding:28px}}
.card{{background:#17132e;border:1px solid #3a3270;border-radius:14px;padding:18px 20px;margin-bottom:18px}}
.lvl{{display:inline-block;background:{color};color:#111;font-weight:800;border-radius:99px;padding:4px 14px}}
h1{{margin:0 0 6px;font-size:22px}} h2{{font-size:15px;text-transform:uppercase;letter-spacing:.06em;color:#9c96c9;margin-top:26px}}
ul,ol{{padding-left:18px}} li{{margin:10px 0}} small{{color:#8d87b8}} q{{color:#b9b3e6;font-style:italic;font-size:13px}}
.fix{{color:#ffd23d;font-size:13.5px}} .flag b{{color:#ff8a8a}} .muted{{color:#6f6a99}}
.meta{{color:#9c96c9;font-size:13px}} .disc{{color:#6f6a99;font-size:12px;margin-top:30px}}</style></head><body>
<div class="card"><h1>🛡️ {e(name)}</h1>
<div class="meta">{e(TYPE_LABEL.get(res.doc_type, res.doc_type))} · {pages} page(s) · {words:,} words · {datetime.now():%b %d, %Y %I:%M %p}</div>
<p><span class="lvl">{level}{"" if level == "INFO" else f" RISK · {risk}/100"}</span></p></div>
{body}
<p class="disc">Automated keyword-based screening by the Bot Office compliance bots. Not legal advice. Have a lawyer review before relying on it.</p>
</body></html>"""
