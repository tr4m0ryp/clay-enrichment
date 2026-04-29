"""Static + dynamic GitHub Code Search query bank.

Ports FrogBytes_V3/lib/api-keys/scraper.ts:170-326 verbatim. The static
bank lives in `_STATIC_QUERIES`; dynamic recency queries are computed from
the current month at run time. ``build_all_queries`` returns the
concatenation in the order static then dynamic, matching the TS spreader.
"""

from __future__ import annotations

from datetime import datetime


# 1:1 port of FrogBytes_V3/lib/api-keys/scraper.ts:170-306. Order preserved
# so query rotation indices stay stable across runs.
_STATIC_QUERIES: list[str] = [
    # ===== HIGH-YIELD CORE PATTERNS =====
    # Direct API key patterns (most effective)
    "AIzaSy",
    "AIza",
    # Environment variable patterns (very common)
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GEMINI_API_KEY",
    "GEMINI_KEY",
    "GENERATIVE_AI_KEY",
    # ===== LATEST GEMINI MODELS (2.5+) =====
    # Focus on latest models to avoid old/deprecated keys
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-1.5-pro-latest",
    "gemini-1.5-flash-latest",
    "gemini-2.0-flash",
    "gemini-2.0-flash-exp",
    "gemini-exp-1206",
    "gemini-exp-1121",
    # ===== CURRENT SDK PATTERNS =====
    # Focus on current, actively maintained SDKs
    "@google/generative-ai",
    "GoogleGenerativeAI",
    "generative-ai",
    "google-generativeai",
    # ===== FILE EXTENSION TARGETING =====
    # Target specific file types where keys are commonly leaked
    "AIzaSy extension:env",
    "AIzaSy extension:js",
    "AIzaSy extension:ts",
    "AIzaSy extension:py",
    "AIzaSy extension:json",
    "AIzaSy extension:yaml",
    "AIzaSy extension:yml",
    "AIzaSy extension:txt",
    "GEMINI_API_KEY extension:env",
    "GOOGLE_API_KEY extension:env",
    # ===== FILENAME TARGETING =====
    # Target specific filenames where keys are commonly found
    "AIzaSy filename:.env",
    "AIzaSy filename:config.js",
    "AIzaSy filename:config.ts",
    "AIzaSy filename:settings.json",
    "AIzaSy filename:.env.local",
    "AIzaSy filename:.env.example",
    "GEMINI_API_KEY filename:.env",
    "GOOGLE_API_KEY filename:.env",
    # ===== PATH TARGETING =====
    # Target common paths where config files exist
    "AIzaSy path:config",
    "AIzaSy path:.github",
    "AIzaSy path:src/config",
    "AIzaSy path:lib/config",
    "GEMINI_API_KEY path:config",
    # ===== LANGUAGE-SPECIFIC PATTERNS =====
    # Target specific languages with high adoption
    "GEMINI_API_KEY language:JavaScript",
    "GEMINI_API_KEY language:TypeScript",
    "GEMINI_API_KEY language:Python",
    "AIzaSy language:JavaScript",
    "AIzaSy language:TypeScript",
    "AIzaSy language:Python",
    # ===== CODE USAGE PATTERNS =====
    # Common variable declarations and imports
    "process.env.GEMINI_API_KEY",
    "process.env.GOOGLE_API_KEY",
    "const geminiApiKey",
    "const googleApiKey",
    "import { GoogleGenerativeAI }",
    "new GoogleGenerativeAI(",
    "genai.configure(api_key=",
    "GoogleAI(api_key=",
    # ===== GENERATE-CONTENT USAGE PATTERNS =====
    # Bias toward code that actually CALLS generateContent. This filters
    # out keys whose Google Cloud project never enabled the Gemini API
    # (38% of our scraped corpus by error_message bucket). Keys appearing
    # next to a generateContent call are far likelier to belong to a
    # project that has the API enabled.
    "AIzaSy generateContent",
    "AIzaSy generate_content",
    "AIzaSy generateContentStream",
    "AIzaSy streamGenerateContent",
    "AIzaSy getGenerativeModel",
    "AIzaSy GenerativeModel",
    "AIzaSy genai.GenerativeModel",
    "AIzaSy startChat",
    "AIzaSy sendMessage",
    "AIzaSy models/gemini",
    "GEMINI_API_KEY generateContent",
    "GEMINI_API_KEY generate_content",
    "GEMINI_API_KEY GenerativeModel",
    "GEMINI_API_KEY getGenerativeModel",
    "GOOGLE_API_KEY generateContent",
    ":generateContent AIza",
    "models/gemini-2.5-flash:generateContent",
    "models/gemini-2.5-pro:generateContent",
    "v1beta/models/gemini",
    # ===== RECENT ACTIVITY FILTERS =====
    # Focus on recently active repositories (more likely to have valid keys)
    "AIzaSy pushed:>2024-11-01",
    "AIzaSy pushed:>2024-12-01",
    "GEMINI_API_KEY pushed:>2024-11-01",
    "GEMINI_API_KEY pushed:>2024-12-01",
    "GoogleGenerativeAI pushed:>2024-11-01",
    "@google/generative-ai pushed:>2024-11-01",
    # ===== REPOSITORY SIZE FILTERS =====
    # Target smaller repos (more likely to have accidentally committed keys)
    "AIzaSy size:<1000",
    "GEMINI_API_KEY size:<1000",
    "AIzaSy size:<5000",
    "GEMINI_API_KEY size:<5000",
    # ===== COMBINED PATTERNS =====
    # High-precision combined searches
    "AIzaSy GoogleGenerativeAI",
    "GEMINI_API_KEY @google/generative-ai",
    "AIzaSy gemini-1.5-pro",
    "GEMINI_API_KEY gemini-1.5-flash",
    "process.env.GEMINI_API_KEY @google/generative-ai",
    # ===== TUTORIAL/EXAMPLE PATTERNS =====
    # Educational content often contains working keys
    "AIzaSy tutorial",
    "AIzaSy example",
    "GEMINI_API_KEY tutorial",
    "GEMINI_API_KEY example",
    "gemini api key tutorial",
    # ===== DEPLOYMENT PATTERNS =====
    # Keys in deployment configs
    "AIzaSy docker-compose",
    "AIzaSy Dockerfile",
    "GEMINI_API_KEY docker",
    "AIzaSy vercel",
    "AIzaSy netlify",
    # ===== TESTING PATTERNS =====
    # Test files often contain real keys
    "AIzaSy filename:test",
    "GEMINI_API_KEY filename:test",
    "AIzaSy path:test",
    "AIzaSy path:tests",
    # ===== DOCUMENTATION PATTERNS =====
    # README and docs sometimes contain keys
    "AIzaSy filename:README",
    "GEMINI_API_KEY filename:README",
    "AIzaSy path:docs",
    "GEMINI_API_KEY path:docs",
]


def build_static_queries() -> list[str]:
    """Return the static query bank as a fresh list (callers can mutate)."""
    return list(_STATIC_QUERIES)


def build_dynamic_queries(now: datetime) -> list[str]:
    """Return 18 month-back recency queries seeded from ``now``.

    For each ``i in 1..6`` compute ``d = first day of (now's month - i)``
    formatted ``YYYY-MM-DD`` and emit three queries: ``AIzaSy pushed:>{d}``,
    ``GEMINI_API_KEY pushed:>{d}``, ``GoogleGenerativeAI pushed:>{d}``. The
    month subtraction wraps via plain integer math so December stays
    correct without dateutil.
    """
    queries: list[str] = []
    for months_back in range(1, 7):
        # Mirror the JS Date(year, month - i, 1) constructor: month is
        # zero-indexed in JS; subtracting i and letting it go negative
        # rolls the year back. We replicate that with divmod.
        zero_indexed_month = (now.month - 1) - months_back
        year_offset, target_month_zero = divmod(zero_indexed_month, 12)
        year = now.year + year_offset
        month = target_month_zero + 1
        date_str = f"{year:04d}-{month:02d}-01"
        queries.append(f"AIzaSy pushed:>{date_str}")
        queries.append(f"GEMINI_API_KEY pushed:>{date_str}")
        queries.append(f"GoogleGenerativeAI pushed:>{date_str}")
    return queries


def build_all_queries(now: datetime) -> list[str]:
    """Concatenate the static + dynamic banks (static first, dynamic last)."""
    return [*_STATIC_QUERIES, *build_dynamic_queries(now)]
