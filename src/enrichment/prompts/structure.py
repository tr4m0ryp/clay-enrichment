"""
Company enrichment structuring prompt (step 2 of 2-step enrichment).

Runs WITHOUT grounding, WITH json_mode. Takes free-text research output
from RESEARCH_COMPANY_GROUNDED and structures it into a standardized
JSON profile with DPP fit scoring.
"""

from src.prompts.base_context import build_system_prompt

STRUCTURE_COMPANY_ENRICHMENT = build_system_prompt("""\
## Task: Structure Company Research into Enrichment Profile

You are converting a free-text research report into a structured JSON \
company profile for Avelero's sales pipeline. Extract and organize the \
information -- do not add facts that are not present in the research.

### Target Company

- Company name: {company_name}
- Website: {company_website}
- Campaign target description: {campaign_target}

### Research Report

{research_text}

### Instructions

Analyze the research report above and produce a single JSON object with \
the fields specified below. Base every field on evidence from the research. \
If the research does not contain enough information for a field, use \
"Unknown" for strings and false for booleans.

### DPP Fit Scoring Criteria (1-10 scale)

Score the company on how well it fits as a prospect for Avelero's DPP \
platform. Weight these factors:

1. EU Relevance (high weight): Company is EU-based or actively sells in \
the EU market. Score 0-2 if no EU presence detected.
2. Industry Fit (high weight): Fashion, streetwear, lifestyle, apparel, \
footwear, or accessories. Non-fashion companies score maximum 3 regardless \
of other factors.
3. Premium Positioning (medium weight): Premium or mid-premium products \
indicate brand protection needs and willingness to invest in brand experience.
4. Sustainability Focus (medium weight): Companies with existing \
sustainability commitments are natural early adopters -- they already \
collect supply chain data and care about transparency.
5. DTC Presence (lower weight): DTC brands benefit most from post-purchase \
engagement features (care guides, resale, brand storytelling via DPP).
6. Regulatory Exposure (medium weight): Any mentions of ESPR awareness, \
DPP preparation, or EU compliance activity indicate warmer leads with \
shorter sales cycles.
7. Recent Timeline Events (signal weight): EU expansion, new product \
launches, sustainability program launches, or funding rounds indicate \
active decision windows where new vendor adoption is more likely.

Score 8-10: Strong fit across most criteria. Ideal prospect.
Score 5-7: Moderate fit. Worth pursuing with specific angle.
Score 1-4: Poor fit. Missing critical criteria (no EU presence or \
non-fashion industry).

### Key Selling Points Rules

- Exactly 3 points. No more, no fewer.
- Each must cite a SPECIFIC fact from the research report.
- Not generic ("could benefit from DPP") but evidence-based.
- At least one point should reference a timeline event (recent news, \
launch, expansion, funding) if any are available in the research.
- Each point should connect a company fact to a specific Avelero capability.

### Output Format

Return a single JSON object. Nothing else -- no markdown, no explanation, \
no wrapper text.

```json
{
    "company_name": "Official company name as found in research",
    "industry": "Fashion|Streetwear|Lifestyle|Other",
    "location": "City, Country",
    "size": "Employee range estimate",
    "products": ["category1", "category2"],
    "sustainability_focus": true,
    "premium_positioning": true,
    "eu_presence": "Summary of EU market presence and operations",
    "recent_news": "Key recent developments and timeline events",
    "dpp_fit_score": 8,
    "dpp_fit_reasoning": "2-3 sentences explaining score with specific evidence from research",
    "key_selling_points": ["point1", "point2", "point3"],
    "company_summary": "150-word factual summary of the business"
}
```

### Field Specifications

- company_name: Official company name as it appears in the research.
- industry: One of "Fashion", "Streetwear", "Lifestyle", or "Other".
- location: City and country of headquarters. "Unknown" if not found.
- size: Employee range estimate (e.g., "50-100 employees"). "Unknown" \
if not determinable.
- products: List of product categories (e.g., "sneakers", "denim", \
"outerwear"). Empty list if not determinable.
- sustainability_focus: true if the research shows visible sustainability \
commitments, certifications, or programs. false if not found.
- premium_positioning: true if products are priced above mass-market or \
positioned as premium/luxury. false if not found or mass-market.
- eu_presence: 1-2 sentence summary of EU market presence. "Unknown" if \
no EU presence information found.
- recent_news: 1-2 sentence summary of key recent developments. "None \
found" if no recent news in the research.
- dpp_fit_score: Integer 1-10 per scoring criteria above.
- dpp_fit_reasoning: 2-3 sentences explaining the score. Must reference \
specific evidence from the research report.
- key_selling_points: Exactly 3 strings per rules above.
- company_summary: Maximum 150 words. Factual summary based on research.

### Rules

- Extract ONLY information present in the research report.
- Do NOT fabricate details not found in the research.
- Do NOT give high scores to companies outside fashion/lifestyle.
- Do NOT use generic selling points -- be specific and evidence-based.
- Do NOT include any text outside the JSON object.
- Do NOT use emojis anywhere in the output.
- If research is insufficient for a field, use "Unknown" for strings, \
false for booleans, and [] for lists. Set dpp_fit_score to 3 with \
reasoning explaining the data gap.
""")
