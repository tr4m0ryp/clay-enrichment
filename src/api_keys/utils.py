"""Format-validation helpers for Gemini API keys.

Ports FrogBytes_V3/lib/api-keys/utils.ts isValidKeyFormat plus the regex
patterns documented in notes/gemini-scraper-supabase-db-refactor.md
(lines 322-343, 327-334).
"""

from __future__ import annotations

import re


KEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"AIzaSy[A-Za-z0-9_-]{33}"),
    re.compile(r"AIza[A-Za-z0-9_-]{35}"),
    re.compile(r"AIza[A-Za-z0-9_\-]{33,39}"),
)

# Gemini-context markers. A file containing one of these strings is
# materially more likely to host a Gemini-enabled key. Used by the
# scraper's per-file context filter to drop AIzaSy candidates whose
# source file shows no Gemini fingerprints (Maps API leaks, Drive
# scripts, YouTube tools, Translate clients are the dominant noise).
# Lowercase comparison gives case-insensitive matching cheaply.
_GEMINI_CONTEXT_MARKERS: tuple[str, ...] = (
    "generatecontent",
    "generativemodel",
    "googlegenerativeai",
    "google.generativeai",
    "@google/generative-ai",
    "genai.configure",
    "googlegenai",
    "gemini-1.5",
    "gemini-2.0",
    "gemini-2.5",
    "gemini-3",
    "gemini_api_key",
    "gemini-api-key",
    "generative_ai_key",
    "generativelanguage.googleapis",
    "models/gemini",
    "ai.google.dev",
    "makersuite.google.com",
)

_ALLOWED_CHARS = re.compile(r"AIza[A-Za-z0-9_-]+")
_PLACEHOLDER_PATTERNS = re.compile(
    r"(test|example|sample|demo|fake|placeholder|your_api_key"
    r"|x{3,}|0{3,}|1{3,}|abc{3,})",
    re.IGNORECASE,
)


def is_valid_key_format(key: str) -> bool:
    """Return True if the candidate string matches the Gemini key shape."""
    if not key.startswith("AIza"):
        return False
    if not (35 <= len(key) <= 40):
        return False
    if _ALLOWED_CHARS.fullmatch(key) is None:
        return False
    if _PLACEHOLDER_PATTERNS.search(key):
        return False
    if len(set(key)) < 10:
        return False
    return True


def extract_keys_from_text(text: str) -> set[str]:
    """Extract all valid-format Gemini keys from a text body.

    Runs each KEY_PATTERNS regex against the text, then keeps only matches
    that pass is_valid_key_format. Returns a set so duplicates within a
    single document collapse.
    """
    found: set[str] = set()
    for pattern in KEY_PATTERNS:
        for match in pattern.findall(text):
            if is_valid_key_format(match):
                found.add(match)
    return found


def looks_like_gemini_context(text: str) -> bool:
    """True when the file text contains any Gemini SDK / model / env-var
    marker. Drops AIzaSy candidates whose source file shows no Gemini
    fingerprints; sharply increases real Gemini-yield per stored
    candidate at the cost of total candidate volume."""
    if not text:
        return False
    haystack = text.lower()
    return any(m in haystack for m in _GEMINI_CONTEXT_MARKERS)
