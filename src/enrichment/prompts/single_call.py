"""Single-call enrichment prompt -- combined research + structure.

This prompt drives a single Gemini 3 grounded structured call that
collapses the legacy four-call enrichment chain (website resolve ->
grounded research -> JSON structure -> scrape fallback) into one
``generate_content`` round trip with ``google_search`` grounding and
``responseMimeType=application/json``.

Per F3 / R7 in ``research/campaign_creation_redesign.md``, Gemini 3
supports tool combos and JSON mode in the same call. Per F16, the
prompt is written defensively so its output schema is invariant
across served-model tiers -- the same prompt also feeds the legacy
two-step path on a Gemini 2.5 fallback (the worker uses the legacy
``RESEARCH_COMPANY_GROUNDED`` + ``STRUCTURE_COMPANY_ENRICHMENT``
prompts there, not this one). The prompt follows the Strict Prompt
Template verbatim.
"""

from __future__ import annotations

from src.prompts.base_context import build_system_prompt


ENRICH_COMPANY_SINGLE_CALL = build_system_prompt("""\
## Task
Research the target company using grounded Google Search and emit a single \
structured DPP enrichment profile (website discovery + market research + \
DPP fit scoring) in one JSON object.

## Inputs (each is a templated placeholder filled by the caller)
- {company_name}: official-or-best-known company name (string, e.g. "Patagonia").
- {company_website}: canonical website URL if already known (string, may be \
"" -- in that case the model must find it via grounded search; e.g. \
"https://www.patagonia.com" or "").
- {campaign_target}: free-text description of the campaign's ideal customer \
profile and outreach angle (string, e.g. "EU mid-market sustainable \
streetwear brands").

## Output Format -- EXACT
Return ONLY a valid JSON object matching this schema. No markdown fences. \
No prose before or after. No explanation. No preamble.

{
  "company_name": "string -- official name; max 200 chars",
  "website": "string -- canonical https://... URL or empty string",
  "industry": "string -- one of: Fashion, Streetwear, Lifestyle, Other",
  "location": "string -- 'City, Country' or empty string",
  "size": "string -- employee range estimate (e.g. '50-100 employees') or empty string",
  "products": ["string -- product category, max 60 chars per item"],
  "sustainability_focus": false,
  "premium_positioning": false,
  "eu_presence": "string -- 1-2 sentences on EU operations or empty string",
  "recent_news": "string -- 1-2 sentences on key recent developments or empty string",
  "dpp_fit_score": 0,
  "dpp_fit_reasoning": "string -- 2-3 sentences citing specific evidence, or empty string",
  "key_selling_points": ["string -- evidence-based selling point, max 280 chars per item"],
  "company_summary": "string -- max 150 words factual summary"
}

### Field-by-field rules
- company_name: official company name as found in research. Mirror the \
``{company_name}`` input only when the search produces no clearer canonical \
form. Never write "Unknown" / "N/A" -- just keep the input as-is.
- website: canonical homepage URL. If grounded search confirms a domain, \
return it as ``https://www.<domain>``. If no website is confirmable, return \
the empty string ``""``. NEVER guess or fabricate domains.
- industry: exactly one of ``"Fashion"``, ``"Streetwear"``, ``"Lifestyle"``, \
``"Other"``. Anything else (sportswear, luxury, athletic, etc.) collapses \
to ``"Other"``.
- location: ``"City, Country"`` for the headquarters. Empty string ``""`` \
when not determinable. NEVER write "Unknown" / "N/A" / "Worldwide".
- size: employee range estimate (e.g. ``"50-100 employees"``, \
``"500+ employees"``). Empty string ``""`` when not determinable.
- products: list of product categories sold (e.g. \
``["sneakers", "denim", "outerwear"]``). Empty list ``[]`` when not \
determinable.
- sustainability_focus: ``true`` only when the research surfaces visible \
sustainability commitments, certifications (B-Corp, GOTS, OEKO-TEX, Fair \
Trade, Bluesign, Cradle to Cradle), published impact reports, or circular \
economy programs. ``false`` otherwise.
- premium_positioning: ``true`` only when products are priced above \
mass-market or positioned as premium / luxury. ``false`` for mass-market \
or when not determinable.
- eu_presence: 1-2 factual sentences on EU operations (countries served, \
warehouses, retail stores, EU revenue mix). Empty string ``""`` when no \
EU presence detected.
- recent_news: 1-2 factual sentences on key developments in the last 12 \
months (product launches, funding, leadership changes, market expansion). \
Empty string ``""`` when none found.
- dpp_fit_score: integer 1-10 per the scoring criteria below. Use ``0`` \
only when literally no signal could be retrieved.
- dpp_fit_reasoning: 2-3 sentences explaining the score with specific \
evidence cited from the grounded research. Empty string ``""`` when score \
is ``0``.
- key_selling_points: exactly 3 items when ``dpp_fit_score >= 5``, \
otherwise empty list ``[]``. Each item must reference a specific researched \
fact (not generic DPP benefits) and connect that fact to an Avelero \
capability.
- company_summary: factual summary, maximum 150 words, based only on \
researched evidence. Empty string ``""`` when no signal could be retrieved.

### DPP Fit Scoring Criteria (1-10)
Weight, in order:
1. EU Relevance (high): EU-based or actively selling in the EU. Score 0-2 \
when no EU presence is detected.
2. Industry Fit (high): fashion, streetwear, lifestyle, apparel, footwear, \
or accessories. Non-fashion companies cap at 3 regardless of other factors.
3. Premium Positioning (medium): premium or mid-premium pricing.
4. Sustainability Focus (medium): existing certifications, programs, or \
material commitments.
5. DTC Presence (lower): direct-to-consumer channel strength.
6. Regulatory Exposure (medium): explicit ESPR / DPP / Ecodesign mentions \
or supply-chain transparency activity.
7. Recent Timeline Events (signal): EU expansion, new launches, \
sustainability program kickoffs, or funding events in the last 12 months.

Bands:
- 8-10: strong fit across most criteria; ideal prospect.
- 5-7: moderate fit; pursue with a specific angle.
- 1-4: poor fit; missing critical criteria (no EU presence, non-fashion).

## Process -- follow exactly
1. If ``{company_website}`` is empty, run a grounded search to identify the \
canonical homepage URL.
2. Run grounded searches that combine ``{company_name}`` with each of the \
following keywords in turn: ``"sustainability"``, ``"EU expansion"``, \
``"funding"``, ``"compliance"``, ``"recent news"``, ``"team size"``.
3. Read the ``{campaign_target}`` text and weight findings towards the \
campaign's ICP angle when scoring DPP fit.
4. Synthesize the search results into the schema above. Use empty values \
``""`` / ``[]`` / ``0`` / ``false`` whenever a field has no supporting \
evidence in the research.
5. Score ``dpp_fit_score`` against the criteria above. If ``dpp_fit_score \
>= 5``, populate exactly 3 ``key_selling_points`` each citing a specific \
researched fact; otherwise leave ``key_selling_points`` as ``[]``.
6. Emit ONLY the JSON object. No markdown fences. No prose. No commentary.

## Hard Rules (model MUST obey regardless of capability)
- Output is JSON ONLY. No prose before or after. No markdown fences.
- If a field cannot be filled, use the type-appropriate empty value: ``""`` \
for strings, ``[]`` for lists, ``0`` for integers, ``false`` for booleans.
- Never fabricate facts. If uncertain, output the empty value.
- Never use emojis.
- Never include keys not in the schema. Never omit keys in the schema.
- Never include comments inside the JSON.
- Never write sentinel strings ``"Unknown"`` / ``"N/A"`` / ``"None found"`` \
in any field -- use the empty string instead.
- Never give ``dpp_fit_score >= 5`` to a non-fashion / non-lifestyle \
company.

## Output Examples
### Good output
{"company_name": "Patagonia", "website": "https://www.patagonia.com", \
"industry": "Lifestyle", "location": "Ventura, USA", "size": "1000+ \
employees", "products": ["outerwear", "footwear", "accessories"], \
"sustainability_focus": true, "premium_positioning": true, "eu_presence": \
"Operates in 14 EU countries via own retail and DTC. Has logistics hub \
in Amsterdam.", "recent_news": "Launched ReCrafted in EU markets in Q1 \
2026. Disclosed B-Corp re-certification.", "dpp_fit_score": 9, \
"dpp_fit_reasoning": "Strong EU footprint, premium positioning, and \
established sustainability program align with DPP early-adopter profile. \
Recent ReCrafted launch indicates active interest in transparent product \
records.", "key_selling_points": ["Existing material traceability program \
maps directly to Avelero LCA Engine inputs.", "EU-wide retail with mid-2028 \
ESPR deadline making compliance unavoidable.", "ReCrafted resale program \
extends naturally to a Passport Designer post-purchase flow."], \
"company_summary": "Patagonia is a US outdoor lifestyle brand with deep \
EU operations and a long-running sustainability program."}

### Bad outputs (do NOT do these)
- "Here is the JSON: {...}"            (prose before)
- "```json\\n{...}\\n```"               (markdown fence)
- {"company_name": "Unknown", ...}     (sentinel string instead of "")
- {"company_name": "...", "extra": "..."}  (extra keys not in schema)
- {"company_name": "..."}              (missing required keys)
- {"dpp_fit_score": 8, "key_selling_points": []}  (>=5 must have 3 items)
""")
