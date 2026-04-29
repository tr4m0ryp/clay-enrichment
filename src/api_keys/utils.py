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

# Strong Gemini-context markers: SDK class invocations, REST endpoints,
# and Gemini-specific env-var names. Presence of any one strong marker
# is sufficient to accept the file. These are hard to fake -- they
# indicate the project actually wired up Gemini, not just mentions it.
_GEMINI_STRONG_MARKERS: tuple[str, ...] = (
    # SDK class names / methods (Python, JS, Go, Java)
    "googlegenerativeai",          # JS SDK class
    "google.generativeai",         # Python SDK module
    "@google/generative-ai",       # NPM package
    "genai.configure",             # Python init
    "genai.generativemodel",       # Python class
    "getgenerativemodel",          # JS / Java method
    "googlegenai",                 # newer SDK
    "generativemodel(",            # Python class instantiation
    # REST endpoints leave no doubt about Gemini usage
    "generativelanguage.googleapis",
    "models/gemini",
    "v1beta/models/gemini",
    "generatecontent(",            # method call
    ".generatecontent",            # method call
    "generate_content(",           # Python snake_case
    # Gemini-specific env var names
    "gemini_api_key",
    "google_gemini_api_key",
    "generative_ai_key",
    "gemini-api-key",
)

# Placeholder / template / docs phrases. If any of these appear in the
# file, treat it as a documentation stub regardless of any strong-marker
# match -- production code rarely has these strings near a real key.
_DEMO_REJECTION_MARKERS: tuple[str, ...] = (
    "your_api_key_here",
    "your-api-key-here",
    "your_api_key:",
    "<your_api_key>",
    "<your-api-key>",
    "<your_gemini_key>",
    "<your_key>",
    "<your-key>",
    "your_gemini_api_key_here",
    "replace_with_your",
    "replace-with-your",
    "insert your api key",
    "your gemini key here",
    "aizasyyour",       # common placeholder prefix in tutorials
    "aizasydummy",
    "aizasy_test_",
    "key_here_replace",
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
    """True when the file looks like real Gemini-using production code.

    Two-stage filter:
    1. Reject if the file contains any obvious placeholder/template phrase
       ('your_api_key_here', '<your_key>', etc.). These are tutorial /
       docs stubs whose AIza tokens are by definition fake.
    2. Accept only when the file contains a STRONG Gemini marker:
       an SDK class name, an SDK method call, a REST URL, or a
       Gemini-specific env var. Mere mentions of model ids
       ('gemini-2.5') without an SDK invocation are dropped -- those
       are usually blog posts or release notes.

    Trade-off: lower total candidate volume per cycle, materially higher
    real-yield per stored candidate.
    """
    if not text:
        return False
    haystack = text.lower()
    if any(d in haystack for d in _DEMO_REJECTION_MARKERS):
        return False
    return any(m in haystack for m in _GEMINI_STRONG_MARKERS)
