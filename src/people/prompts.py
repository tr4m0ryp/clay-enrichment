"""
Layer 3 prompts: contact extraction and structuring.
"""

from src.prompts.base_context import build_system_prompt


DISCOVER_CONTACTS = build_system_prompt("""\
## Task
Recall from your training data the named decision-makers (founders, C-level, Head-of-X) currently at {company_name} ({domain}) who would be relevant for a B2B outreach campaign about {campaign_target}. Return up to 6 contacts with full names + standardized titles. NO LinkedIn URLs (you cannot reliably know them; we set them later via verified sources).

## Inputs
- {company_name}: target company display name (string, e.g. "Patagonia")
- {domain}: company domain (string, e.g. "patagonia.com")
- {campaign_target}: free-text description of the outreach campaign (string, may be empty)

## Output Format -- EXACT
Return ONLY a valid JSON array matching this schema. No markdown fences. No prose before or after. No explanation. No preamble.

[
  {
    "name": "string -- FIRST and LAST name only, both full words, max 80 chars",
    "title": "string -- short standardized title, max 5 words",
    "linkedin_url": "string -- ALWAYS empty string \\"\\""
  }
]

### Field-by-field rules
- name: a real, verifiable person you actually know works at {company_name}. MUST contain a full first name AND a full last name (both as ASCII words, no single-letter middle initials inside, no abbreviations). NEVER fabricate plausible-sounding names. NEVER fill in with generic placeholder names ("John Doe", "Jane Smith", or made-up Western/Nordic/Romance combinations the model invents). If you can recall fewer than 2 verifiable people, return [].
  - REJECT names with embedded initials: "Anne M. Nielsen" -> drop OR resolve to the full middle name. "Beatriz M. S." -> drop entirely.
  - REJECT name patterns where multiple contacts at the same company share an unusual surname (e.g. "David Gellis", "Sarah Gellis", "Michael Gellis" all at one ~50-person brand) -- this is a hallucination signature.
  - REJECT made-up Danish/Dutch/Spanish surnames you have no specific training-data memory of. If unsure, return [].
- title: standardized short job title. Maximum 5 words. Examples: "CEO", "Head of Sustainability", "VP Supply Chain", "Creative Director", "Founder".
  - Use standard abbreviations: CEO, CTO, CFO, COO, CMO, CRO, VP, SVP, EVP, MD.
  - Strip company names: "CEO of Nike" becomes "CEO".
  - Strip locations: "VP Sales, EMEA" becomes "VP Sales".
  - Strip parenthetical info, dates, commentary.
  - English only: translate foreign titles.
  - Current role only: "Former CEO" -> drop or use "".
  - Use empty string "" if no clear current role is determinable. NEVER write "Unknown", "N/A", or any sentinel string.
- linkedin_url: ALWAYS the empty string "". The model cannot reliably know LinkedIn slug URLs; constructing them produces dead-redirect links. The downstream resolver fills this in from verified sources only.

## Process -- follow exactly
1. Recall the actual founder / CEO / COO / Head of Sustainability / Head of Product etc. at {company_name} ({domain}) from your training data.
2. If your training data has SPECIFIC named individuals at this company, list them. If your training data does not (you would be inventing names), return [] -- do not fabricate.
3. Standardize each title.
4. Deduplicate by name.
5. Return up to 6 contacts. Quality over quantity. Return [] when no verifiable individuals are recallable for this specific company.

## Hard Rules (model MUST obey regardless of capability)
- Output is JSON ONLY. No prose before or after. No markdown fences.
- NEVER fabricate a person whose name + role at this company you cannot specifically recall.
- NEVER fill in plausible-sounding placeholder names because the company is small and you don't know its team. Return [] instead.
- NEVER include LinkedIn URL slugs -- field MUST always be the empty string.
- Empty values: "" for strings. NEVER use sentinel strings like "Unknown" or "N/A".
- Never use emojis. Never include keys not in the schema. Never omit keys in the schema. Never include comments inside the JSON.

## Output Examples
### Good output (specific names known)
[{"name": "Bert van Son", "title": "Founder", "linkedin_url": ""}, {"name": "Dion Vijgeboom", "title": "CEO", "linkedin_url": ""}]

### Good output (no specific names known -- DO this instead of inventing)
[]

### Bad outputs (do NOT do these)
- [{"name": "Anne M. Nielsen", "title": "CEO", "linkedin_url": ""}]                          (initial-style middle)
- [{"name": "Beatriz M. S.", "title": "Head of Marketing", "linkedin_url": ""}]              (initials-only suffix)
- [{"name": "John Doe", ...}, {"name": "Jane Smith", ...}]                                   (placeholder names)
- [{"name": "David Gellis", ...}, {"name": "Sarah Gellis", ...}, {"name": "Michael Gellis", ...}] (fabricated dynasty at small brand)
- [{"name": "Mette Møller", "title": "CEO", "linkedin_url": "https://www.linkedin.com/in/mette-moller-12345"}] (fabricated LinkedIn slug)
- "Here is the JSON: [...]"                                                                   (prose before)
- "```json\\n[...]\\n```"                                                                       (markdown fence)
""")
