"""Optional Claude brain for the bots.

If the `anthropic` package is installed and credentials are available
(ANTHROPIC_API_KEY, or an `ant auth login` profile), Reg Checker and Caption
Writer ask Claude. Otherwise every function returns None and the bots fall
back to their rule-based / template behaviour, so the office always works.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("bot-office.ai")

MODEL = os.environ.get("BOT_OFFICE_MODEL", "claude-opus-5-5")
MAX_DOC_CHARS = 600_000  # ~150K tokens; longer docs are reviewed in part and the report says so

try:
    import anthropic
except ImportError:  # SDK not installed: AI features stay off
    anthropic = None

_client = None
_disabled = False  # set after an authentication failure so we stop trying


def _has_credentials() -> bool:
    if any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE",
                                       "ANTHROPIC_IDENTITY_TOKEN", "ANTHROPIC_IDENTITY_TOKEN_FILE")):
        return True
    return (Path.home() / ".config" / "anthropic").is_dir()  # `ant auth login` profile


def _get_client():
    global _client
    if anthropic is None or _disabled or os.environ.get("BOT_OFFICE_AI", "on").lower() == "off":
        return None
    if not _has_credentials():
        return None
    if _client is None:
        try:
            _client = anthropic.Anthropic()
        except Exception as exc:  # no credentials configured
            log.info("Claude disabled: %s", exc)
            return None
    return _client


def available() -> bool:
    return _get_client() is not None


def _ask_json(system: str, user: str, schema: dict, max_tokens: int = 16000) -> dict | None:
    global _disabled
    client = _get_client()
    if client is None:
        return None
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # if a safety classifier declines, retry on a fallback model
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.AuthenticationError:
        _disabled = True
        log.warning("Claude: invalid credentials, using rule-based fallback")
        return None
    except anthropic.RateLimitError:
        log.warning("Claude: rate limited, using rule-based fallback")
        return None
    except anthropic.APIStatusError as exc:
        log.warning("Claude API error %s: %s", exc.status_code, exc.message)
        return None
    except anthropic.APIConnectionError:
        log.warning("Claude: network error, using rule-based fallback")
        return None
    except Exception as exc:  # e.g. no usable credentials found at request time: never break the bots over optional AI
        _disabled = True
        log.warning("Claude unavailable (%s: %s), using rule-based fallback", type(exc).__name__, exc)
        return None
    if response.stop_reason in ("refusal", "max_tokens"):
        log.warning("Claude stopped with %s", response.stop_reason)
        return None
    text = next((b.text for b in response.content if b.type == "text"), None)
    try:
        return json.loads(text) if text else None
    except json.JSONDecodeError:
        return None


# ───────────────────────── Reg Checker ─────────────────────────
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "risk_level": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "law": {"type": "string"},
                    "quote": {"type": "string"},
                    "fix": {"type": "string"},
                },
                "required": ["title", "severity", "law", "quote", "fix"],
                "additionalProperties": False,
            },
        },
        "rule_check_corrections": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "risk_level", "issues", "rule_check_corrections"],
    "additionalProperties": False,
}

REVIEW_SYSTEM = (
    "You are a Philippine compliance reviewer. You review business documents (privacy policies, "
    "contracts, internal policies) against the Data Privacy Act of 2012 (RA 10173), its IRR and NPC "
    "circulars, and general Civil Code contract principles. Base every issue on the document text: "
    "the quote field must be copied verbatim from it. Cite the specific section of the law. Keep the "
    "summary to 2-3 plain-language sentences a business owner can act on. A keyword-based checker "
    "already ran; in rule_check_corrections, list any of its results that are wrong (e.g. it marked "
    "something present that is only mentioned in passing), or leave the list empty."
)


def review_document(name: str, doc_type: str, text: str, rule_summary: str) -> dict | None:
    """Claude's second opinion on a document. Returns None when AI is off."""
    partial = len(text) > MAX_DOC_CHARS
    body = text[:MAX_DOC_CHARS]
    user = (
        f"Document: {name}\nDetected type: {doc_type}\n"
        f"Keyword checker results:\n{rule_summary}\n\n"
        + ("NOTE: only the first part of a long document is included below.\n\n" if partial else "")
        + f"<document>\n{body}\n</document>"
    )
    result = _ask_json(REVIEW_SYSTEM, user, REVIEW_SCHEMA)
    if result is not None:
        result["partial"] = partial
    return result


# ───────────────────────── Caption Writer ─────────────────────────
CAPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "hook": {"type": "string"},
        "caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "cta": {"type": "string"},
    },
    "required": ["hook", "caption", "hashtags", "cta"],
    "additionalProperties": False,
}

CAPTION_SYSTEM = (
    "You write short-form social captions (TikTok, Reels, Shorts) for a Filipino audience in natural "
    "Taglish. hook: the on-screen first line, under 10 words. caption: 1-3 short sentences. hashtags: "
    "5-8 relevant tags without the # sign. cta: one short call to action. Do not invent facts, prices "
    "or claims that are not in the brief."
)


def write_caption(brief: str) -> dict | None:
    return _ask_json(CAPTION_SYSTEM, brief, CAPTION_SCHEMA, max_tokens=4000)
