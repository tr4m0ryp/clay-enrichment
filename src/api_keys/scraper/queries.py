"""Static + dynamic GitHub Code Search query bank.

Ports FrogBytes_V3/lib/api-keys/scraper.ts:170-326 verbatim. The static
bank lives in `_STATIC_QUERIES`; dynamic recency queries are computed from
the current month at run time. ``build_all_queries`` returns the
concatenation in the order static then dynamic, matching the TS spreader.
"""

from __future__ import annotations

from datetime import datetime, timedelta


# 1:1 port of FrogBytes_V3/lib/api-keys/scraper.ts:170-306. Order preserved
# so query rotation indices stay stable across runs.
_STATIC_QUERIES: list[str] = [
    # ===== GEMINI-LABELED ENV VARS (highest yield, lowest noise) =====
    # These env-var names are Gemini-specific by convention. Files
    # containing them are far more likely to host a Gemini-active key
    # than generic AIzaSy hits in random Maps/Drive/YouTube projects.
    "GEMINI_API_KEY",
    "GOOGLE_GEMINI_API_KEY",
    "GEMINI_KEY",
    "GENERATIVE_AI_KEY",
    # GOOGLE_API_KEY kept because it's commonly used for Gemini too,
    # but the post-extract context filter drops files that don't show
    # any Gemini fingerprint.
    "GOOGLE_API_KEY",
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
    # ===== FILE-TYPE TARGETING (Gemini-named env files) =====
    # Trimmed: dropped 'AIzaSy filename:test', 'AIzaSy filename:README',
    # 'AIzaSy size:<5000', 'AIzaSy tutorial' etc. -- they pulled mostly
    # non-Gemini Google keys (Maps/Drive/YouTube). Kept env-files where
    # the var name itself is Gemini-specific.
    "GEMINI_API_KEY extension:env",
    "GEMINI_API_KEY filename:.env",
    "GEMINI_API_KEY filename:.env.local",
    "GOOGLE_GEMINI_API_KEY filename:.env",
    "GEMINI_API_KEY language:Python",
    "GEMINI_API_KEY language:TypeScript",
    "GEMINI_API_KEY language:JavaScript",
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
    # ===== HIGH-PRECISION CO-SEARCH (Gemini SDK + AIzaSy in same file) =====
    # Files containing both an AIzaSy and a Gemini SDK string almost
    # always belong to a Gemini-using project. These are the highest-
    # yield static queries we have.
    "AIzaSy GoogleGenerativeAI",
    "AIzaSy GoogleGenAI",
    "AIzaSy genai.configure",
    "AIzaSy genai.GenerativeModel",
    "AIzaSy GenerativeModel",
    "AIzaSy getGenerativeModel",
    "AIzaSy generateContent",
    "AIzaSy generate_content",
    "AIzaSy gemini-2.5-pro",
    "AIzaSy gemini-2.5-flash",
    "AIzaSy gemini-3-flash-preview",
    "AIzaSy models/gemini",
    "AIzaSy generativelanguage.googleapis",
    "GEMINI_API_KEY @google/generative-ai",
    "GEMINI_API_KEY google.generativeai",
    "GEMINI_API_KEY gemini-2.5-pro",
    "GEMINI_API_KEY gemini-2.5-flash",
    "GEMINI_API_KEY GoogleGenerativeAI",
    "GEMINI_API_KEY GenerativeModel",
    "GOOGLE_API_KEY GoogleGenerativeAI",
    "GOOGLE_API_KEY genai.configure",
    "process.env.GEMINI_API_KEY @google/generative-ai",
    # ===== REST URL PATTERNS =====
    # Keys leaked next to direct REST URLs are guaranteed Gemini context.
    "models/gemini-2.5-flash:generateContent",
    "models/gemini-2.5-pro:generateContent",
    "models/gemini-3-flash-preview:generateContent",
    "v1beta/models/gemini",
    # ===== RECENT ACTIVITY FILTERS =====
    # Focus on recently active repos. Note: GitHub Code Search returns
    # very few results with `pushed:>` filters because indexed code older
    # than ~6 months gets dropped; kept only the broadest of these.
    "GEMINI_API_KEY pushed:>2024-12-01",
    "GoogleGenerativeAI pushed:>2024-11-01",
    "@google/generative-ai pushed:>2024-11-01",
]


def build_static_queries() -> list[str]:
    """Return the static query bank as a fresh list (callers can mutate)."""
    return list(_STATIC_QUERIES)


_DAY_HORIZONS: tuple[int, ...] = (1, 2, 3, 7)
_MONTH_HORIZONS: tuple[int, ...] = (1, 3, 6)
_DYNAMIC_PATTERNS: tuple[str, ...] = (
    "AIzaSy",
    "GEMINI_API_KEY",
    "GoogleGenerativeAI",
    "generateContent",
)


def build_dynamic_queries(now: datetime) -> list[str]:
    """Recency queries biased toward freshly-pushed code.

    Day-granular ``pushed:>`` filters target the narrow window where
    leaks haven't yet been swept by Google's GitHub Secret Scanner
    (which runs every few minutes against new commits). Month-granular
    filters cover slightly older leaks that might still be live.

    Patterns rotated against each horizon: AIzaSy, GEMINI_API_KEY,
    GoogleGenerativeAI, generateContent. Total = (4 days + 3 months) * 4
    patterns = 28 dynamic queries.
    """
    queries: list[str] = []

    # Day-back: catch the freshest leaks pre-Secret-Scanner sweep.
    for days_back in _DAY_HORIZONS:
        date_str = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
        for pattern in _DYNAMIC_PATTERNS:
            queries.append(f"{pattern} pushed:>{date_str}")

    # Month-back: slightly older fresh code that might still have live keys.
    for months_back in _MONTH_HORIZONS:
        # Mirror JS Date(year, month - i, 1): month is zero-indexed; let
        # it go negative and divmod rolls the year back.
        zero_indexed_month = (now.month - 1) - months_back
        year_offset, target_month_zero = divmod(zero_indexed_month, 12)
        year = now.year + year_offset
        month = target_month_zero + 1
        date_str = f"{year:04d}-{month:02d}-01"
        for pattern in _DYNAMIC_PATTERNS:
            queries.append(f"{pattern} pushed:>{date_str}")

    return queries


def build_all_queries(now: datetime) -> list[str]:
    """Concatenate the dynamic + static banks. Dynamic comes FIRST so the
    orchestrator's per-cycle iteration hits freshly-pushed code before
    Google's Secret Scanner can revoke it. Callers should NOT rotate
    these by a random index -- doing so leaks the dynamic-first ordering."""
    return [*build_dynamic_queries(now), *_STATIC_QUERIES]
