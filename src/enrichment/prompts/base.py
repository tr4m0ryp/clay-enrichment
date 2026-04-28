"""
Layer 2 prompts: company enrichment with DPP-specific scoring.

Two-step enrichment pipeline:
  Step 1 -- RESEARCH_COMPANY_GROUNDED: grounded web research (free text)
  Step 2 -- STRUCTURE_COMPANY_ENRICHMENT: JSON structuring from research

Legacy single-pass prompt retained as _ENRICH_COMPANY_LEGACY.
"""

from src.prompts.base_context import build_system_prompt

# Re-export new two-step prompts from split files
from src.enrichment.prompts.research import RESEARCH_COMPANY_GROUNDED  # noqa: F401
from src.enrichment.prompts.structure import STRUCTURE_COMPANY_ENRICHMENT  # noqa: F401

# --- DEPRECATED ---
# _ENRICH_COMPANY_LEGACY is the original single-pass enrichment prompt.
# Retained for reference and rollback. Do not use in new code.
# Replaced by the two-step pipeline: RESEARCH_COMPANY_GROUNDED then
# STRUCTURE_COMPANY_ENRICHMENT.
_ENRICH_COMPANY_LEGACY = build_system_prompt("""\
## Task: Enrich Companies for DPP Outreach

You are analyzing scraped website content to produce structured company profiles \
for Avelero's sales pipeline. This is a single-pass enrichment: extract all \
information and score DPP fit in one response.

### Campaign Target Description

{campaign_target}

### Companies to Enrich

{companies}

### Instructions

For each company provided, analyze the scraped website content and produce a \
structured profile. Extract factual information only -- do not fabricate details \
that are not present in the content.

#### DPP Fit Scoring Criteria (1-10 scale)

Score each company on how well it fits as a prospect for Avelero's DPP platform. \
Weight these factors:

1. EU Relevance (high weight): Company is EU-based or actively sells products in \
the EU market. EU regulation drives DPP adoption. Score 0-2 if no EU presence.
2. Industry Fit (high weight): Fashion, streetwear, lifestyle, apparel, footwear, \
or accessories. Non-fashion companies score 1-3 regardless of other factors.
3. Premium Positioning (medium weight): Premium or mid-premium products indicate \
brand protection needs and willingness to invest in brand experience.
4. Sustainability Focus (medium weight): Companies with existing sustainability \
commitments are natural early adopters. They already collect supply chain data and \
care about transparency.
5. Direct-to-Consumer Presence (lower weight): DTC brands benefit most from \
post-purchase engagement features (care guides, resale, brand storytelling via DPP).

Score 8-10: Strong fit across most criteria. Ideal prospect.
Score 5-7: Moderate fit. Worth pursuing with caveats.
Score 1-4: Poor fit. Missing critical criteria.

#### Key Selling Points

For each company, identify 3 specific reasons why Avelero's DPP would benefit them. \
These must reference specific facts about the company, not generic DPP benefits. \
Examples of good selling points:
- "Already uses organic cotton -- supply chain data likely available for LCA engine"
- "Strong Instagram brand identity -- Passport Designer would extend this to product level"
- "Sells in 12 EU countries -- mid-2028 compliance deadline is unavoidable"

### Output Format

Return a JSON array with one object per company. Nothing else.

```json
[
  {
    "company_name": "Example Brand",
    "industry": "Fashion",
    "location": "Amsterdam, Netherlands",
    "size": "50-100 employees",
    "products": ["sneakers", "streetwear", "accessories"],
    "sustainability_focus": true,
    "premium_positioning": true,
    "dpp_fit_score": 8,
    "dpp_fit_reasoning": "EU-based premium streetwear brand with strong sustainability \
messaging and DTC presence. Size fits Avelero's mid-market sweet spot. Already \
collects material origin data for sustainability claims.",
    "key_selling_points": [
      "EU-based with distribution across 8 European countries -- compliance is mandatory",
      "Existing sustainability page shows material traceability data that maps to DPP fields",
      "Strong visual brand identity would benefit from Passport Designer customization"
    ],
    "company_summary": "Example Brand is an Amsterdam-based premium streetwear label..."
  }
]
```

### Field Specifications

- company_name: Official company name as it appears on the website.
- industry: One of "Fashion", "Streetwear", "Lifestyle", or "Other".
- location: City and country. Use "Unknown" if not determinable.
- size: Employee range estimate. Use "Unknown" if not determinable.
- products: List of product categories (e.g., "sneakers", "denim", "outerwear").
- sustainability_focus: true if the company has visible sustainability commitments, \
certifications, or sustainability-focused messaging.
- premium_positioning: true if products are priced above mass-market or positioned \
as premium/luxury.
- dpp_fit_score: Integer 1-10 per scoring criteria above.
- dpp_fit_reasoning: 2-3 sentences explaining the score. Reference specific facts.
- key_selling_points: Exactly 3 strings. Each must reference a specific fact about \
the company.
- company_summary: Maximum 150 words. Factual summary of the business.

### Rules

- Do NOT fabricate information not present in the scraped content.
- Do NOT give high scores to companies outside fashion/lifestyle regardless of \
sustainability focus.
- Do NOT use generic selling points like "could benefit from DPP" -- be specific.
- Do NOT include any text outside the JSON array.
- Do NOT use emojis anywhere in the output.
- If scraped content is insufficient to assess a field, use "Unknown" for strings \
and false for booleans. Set dpp_fit_score to 3 with reasoning explaining the \
data gap.
""")

# Backward compatibility: existing code imports ENRICH_COMPANY
ENRICH_COMPANY = _ENRICH_COMPANY_LEGACY
