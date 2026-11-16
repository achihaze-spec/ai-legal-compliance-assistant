"""Optional AI brain for the bots: Claude, or open models through Ollama.

Provider is chosen in ⚙️ Settings (`ai_provider`):
  claude        Anthropic API (ANTHROPIC_API_KEY or an `ant auth login` profile), structured outputs
  ollama_cloud  Ollama's cloud (https://ollama.com), needs an Ollama API key (Authorization: Bearer)
  ollama_local  Ollama on this computer (http://localhost:11434), no key
Ollama speaks the Anthropic Messages API, so the same SDK is used with another base_url.
Ollama's cloud models do not support structured outputs, so for Ollama the JSON shape is
asked for in the prompt and checked here; anything malformed falls back to templates.
If no provider is usable every function returns None and the bots use their rule-based /
template behaviour, so the office always works.
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


def _settings() -> dict:
    try:
        import veo
        return veo.load()
    except Exception:
        return {}


def provider() -> str:
    return _settings().get("ai_provider", "claude")


def _get_client():
    global _client
    if anthropic is None or _disabled or os.environ.get("BOT_OFFICE_AI", "on").lower() == "off":
        return None
    s = _settings()
    p = s.get("ai_provider", "claude")
    if p == "ollama_local":
        return anthropic.Anthropic(base_url=s.get("ollama_url") or "http://localhost:11434", api_key="ollama", max_retries=1)
    if p == "ollama_cloud":
        key = s.get("ollama_api_key", "")
        # Ollama's cloud wants Authorization: Bearer (auth_token), not x-api-key
        return anthropic.Anthropic(base_url="https://ollama.com", auth_token=key, max_retries=1) if key else None
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


def _extract_json(text: str) -> dict | None:
    """First JSON object in a model reply (handles ```json fences and chatter around it)."""
    if not text:
        return None
    t = text.strip()
    if "```" in t:
        parts = t.split("```")
        t = next((p[4:] if p.startswith("json") else p for p in parts[1::2]), t)
    start, depth = t.find("{"), 0
    if start < 0:
        return None
    for i in range(start, len(t)):
        depth += {"{": 1, "}": -1}.get(t[i], 0)
        if depth == 0:
            try:
                return json.loads(t[start:i + 1])
            except json.JSONDecodeError:
                return None
    return None


def _valid(obj, schema) -> bool:
    """Small JSON-schema check (type / required / enum / items) for Ollama replies."""
    t = schema.get("type")
    if t == "object":
        return isinstance(obj, dict) and all(k in obj and _valid(obj[k], schema["properties"][k]) for k in schema.get("required", []))
    if t == "array":
        return isinstance(obj, list) and all(_valid(x, schema.get("items", {})) for x in obj)
    if t == "string":
        return isinstance(obj, str) and ("enum" not in schema or obj in schema["enum"])
    if t == "number":
        return isinstance(obj, (int, float)) and not isinstance(obj, bool)
    if t == "boolean":
        return isinstance(obj, bool)
    return True


def _ask_json_ollama(client, system: str, user: str, schema: dict, max_tokens: int) -> dict | None:
    s = _settings()
    instr = ("\n\nReply with ONE JSON object only, no other text, matching this JSON Schema:\n" + json.dumps(schema))
    for attempt in range(2):  # one retry if the JSON comes back malformed
        try:
            resp = client.messages.create(model=s.get("ollama_model") or "gemma4:31b", max_tokens=max_tokens,
                                          system=system + instr, messages=[{"role": "user", "content": user}])
        except Exception as exc:
            log.warning("Ollama error (%s: %s), using template fallback", type(exc).__name__, exc)
            return None
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        obj = _extract_json(text)
        if obj is not None and _valid(obj, schema):
            return obj
        log.warning("Ollama reply was not valid JSON for the schema (attempt %d)", attempt + 1)
    return None


def _ask_json(system: str, user: str, schema: dict, max_tokens: int = 16000) -> dict | None:
    global _disabled
    client = _get_client()
    if client is None:
        return None
    if provider().startswith("ollama"):
        return _ask_json_ollama(client, system, user, schema, min(max_tokens, 8000))
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
