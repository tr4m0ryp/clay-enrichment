"""Shared output schema + exclusion lists for all 13 discovery strategies.

Every strategy in tier1/tier2/tier3 emits the SAME JSON array schema. This
module owns the canonical Output Format / Hard Rules / Output Examples
block so each strategy prompt references it instead of redefining it.

Per F15 the response is parsed by the discovery worker through
`src/utils/json_extract.py`. Per F16 the schema must be type-defended so
that Gemini 3 Pro down through Gemini 2.5 Flash all emit the same shape.
"""

from __future__ import annotations

# Known DPP competitors -- never returned by any discovery strategy.
COMPETITOR_BLOCKLIST: tuple[str, ...] = (
    "Avelero",
    "Arianee",
    "EON",
    "Certilogo",
    "Renoon",
    "TrusTrace",
    "Retraced",
    "Carbonfact",
)

# Very large enterprises -- out of mid-market ICP, never returned.
LARGE_ENTERPRISE_BLOCKLIST: tuple[str, ...] = (
    "Nike",
    "Adidas",
    "LVMH",
    "Kering",
    "Inditex",
    "H&M Group",
)


COMPANY_LIST_OUTPUT_FORMAT = """\
## Output Format -- EXACT
Return ONLY a valid JSON array. No markdown fences. No prose before or after.

[
  {
    "company_name": "string -- official company name",
    "website_url": "string -- https://... or empty string if not found",
    "location": "string -- city, country (e.g. 'Copenhagen, Denmark') or empty string",
    "fit_reason": "string -- one sentence why this matches the ICP, max 200 chars",
    "signal": "string -- the specific intent signal (recent hire, funding round, etc.) or empty string for non-Tier-1 strategies",
    "source_url": "string -- URL from the grounded search citations or empty string"
  }
]

### Field-by-field rules
- company_name: NEVER use sentinel strings. Empty array [] if no companies found.
- website_url: must start with http:// or https:// or be "". No trailing whitespace.
- location: city + country. Empty string "" if not determinable.
- fit_reason: must reference a specific fact from the search results, not a generic platitude.
- signal: only populated for Tier 1 strategies (S01-S06). Empty string for Tier 2/3.

## Hard Rules
- Output is JSON ONLY. No prose. No markdown fences.
- Return an empty array [] if no matching companies found, never null.
- NEVER fabricate companies. Only return companies that appeared in your grounded search.
- NEVER include companies in the EXCLUDED_NAMES list (case-insensitive match).
- NEVER include Avelero or known DPP competitors (Arianee, EON, Certilogo, Renoon, TrusTrace, Retraced, Carbonfact).
- NEVER include very large enterprises (Nike, Adidas, LVMH, Kering, Inditex, H&M Group).
- Never use emojis.

## Output Examples
### Good output
[
  {"company_name": "Filling Pieces", "website_url": "https://www.fillingpieces.com", "location": "Amsterdam, Netherlands", "fit_reason": "Mid-size EU streetwear brand with sustainability messaging and DTC presence", "signal": "Just hired Head of Sustainability per their 2026-04 LinkedIn post", "source_url": "https://linkedin.com/company/filling-pieces"}
]

### Good output (no matches)
[]

### Bad outputs (do NOT do these)
- {"companies": [...]}                 (object wrapping, schema is array)
- "Here are some companies: [...]"     (prose before)
- ```json [...] ```                    (markdown fence)
- [{"company_name": "Unknown", ...}]   (sentinel string instead of "")
"""


# Sub-rotation value lists for Tier 2 strategies -- indexed by ctx.* % len(values).
GEOGRAPHIES: tuple[str, ...] = (
    "Copenhagen",
    "Stockholm",
    "Berlin",
    "Amsterdam",
    "Paris",
    "Milan",
    "Barcelona",
    "Lisbon",
    "Antwerp",
    "Eindhoven",
    "Munich",
    "Zurich",
)


SUB_NICHES: tuple[str, ...] = (
    "streetwear",
    "denim",
    "footwear",
    "eyewear",
    "accessories",
    "swimwear",
    "lingerie",
    "kidswear",
    "vintage / secondhand",
    "athletic / performance",
)


CERTIFICATIONS: tuple[str, ...] = (
    "B-Corp",
    "GOTS",
    "OEKO-TEX",
    "Fair Trade",
    "Bluesign",
    "Cradle to Cradle",
)


def format_excluded_names(names: list[str]) -> str:
    """Comma-join the excluded names list for embedding in the prompt.

    The discovery worker is responsible for capping this list at ~150
    names before passing it in. We just stringify here.
    """
    if not names:
        return "(none)"
    return ", ".join(names)
