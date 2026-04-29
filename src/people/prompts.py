"""
Layer 3 prompts: contact extraction and structuring.
"""

from src.prompts.base_context import build_system_prompt


DISCOVER_CONTACTS = build_system_prompt("""\
## Task
Search the open web for current decision-makers at {company_name} ({domain}) who would be relevant for a B2B outreach campaign about {campaign_target}. Return up to 10 named contacts with title and LinkedIn URL.

## Inputs
- {company_name}: target company display name (string, e.g. "Patagonia")
- {domain}: company domain (string, e.g. "patagonia.com")
- {campaign_target}: free-text description of the outreach campaign (string, may be empty)

## Output Format -- EXACT
Return ONLY a valid JSON array matching this schema. No markdown fences. No prose before or after. No explanation. No preamble.

[
  {
    "name": "string -- full name as published, max 120 chars",
    "title": "string -- short standardized title, max 5 words",
    "linkedin_url": "string -- https://www.linkedin.com/in/... or empty string"
  }
]

### Field-by-field rules
- name: full name as published on the source. Title casing as written. NEVER include role qualifiers like "Former" or "Interim" in the name itself. Use empty string "" if no full name is found (drop the entry instead of returning a bare initial).
- title: standardized short job title. Maximum 5 words. Examples: "CEO", "Head of Sustainability", "VP Supply Chain", "Creative Director".
  - Use standard abbreviations: CEO, CTO, CFO, COO, CMO, CRO, VP, SVP, EVP, MD.
  - Strip company names: "CEO of Nike" becomes "CEO".
  - Strip locations: "VP Sales, EMEA" becomes "VP Sales".
  - Strip parenthetical info: "CFO (interim)" becomes "CFO".
  - Strip commentary: no "(unverified)", "(formerly)", "(deceased)", dates, or qualifiers.
  - English only: translate foreign titles. "Responsabile vendite" becomes "Sales Manager".
  - Current role only: "Former CEO" or "Seeking new opportunities" is NOT a valid title -- use "".
  - LinkedIn headlines that are slogans, company names, or inspirational text are NOT titles -- use "".
  - Use empty string "" if no clear current role is determinable. NEVER write "Unknown", "N/A", "No data found", or any sentinel string.
- linkedin_url: full LinkedIn profile URL starting with "https://www.linkedin.com/in/". Use empty string "" if no profile is found. NEVER fabricate a slug.

## Process -- follow exactly
1. Search Google for senior people at {company_name} ({domain}) using role keywords aligned with {campaign_target}. Prioritize: founder, CEO, COO, CMO, CRO, Head of Sustainability, Head of Product, Head of Operations, Head of Supply Chain, Head of Digital, Head of E-commerce, VP, Director.
2. Inspect company website team pages, About / Leadership pages, press releases, conference speaker pages, and LinkedIn search results.
3. Verify each person is currently employed at {company_name} (not "Former CEO", not pending). Drop anyone whose current role is at a different company.
4. Standardize titles per the rules above. Drop the title (use "") when no clear current role is determinable.
5. Deduplicate by name. If the same person appears multiple times, keep one entry with the best title and LinkedIn URL.
6. Return up to 10 contacts. Return [] if no qualified contacts are found.

## Hard Rules (model MUST obey regardless of capability)
- Output is JSON ONLY. No prose before or after. No markdown fences.
- NEVER fabricate a person who is not mentioned on a public source.
- NEVER include people who clearly work at a different company that shares a word with the target (e.g. "Four Kitchens" vs "Four").
- Empty values: "" for strings. NEVER use sentinel strings like "Unknown" or "N/A".
- Never use emojis.
- Never include keys not in the schema. Never omit keys in the schema.
- Never include comments inside the JSON.

## Output Examples
### Good output
[{"name": "Jane Smith", "title": "Head of Sustainability", "linkedin_url": "https://www.linkedin.com/in/janesmith"}, {"name": "John Doe", "title": "CEO", "linkedin_url": ""}]

### Good output (no contacts found)
[]

### Bad outputs (do NOT do these)
- "Here is the JSON: [...]"                                                                  (prose before)
- "```json\\n[...]\\n```"                                                                      (markdown fence)
- [{"name": "Jane Smith", "title": "Unknown", "linkedin_url": ""}]                            (sentinel string instead of "")
- [{"name": "Jane Smith", "title": "Former CEO", "linkedin_url": ""}]                         (former role instead of "")
- [{"name": "Jane Smith", "title": "Head of Sustainability"}]                                 (missing required key)
""")


PARSE_CONTACT_RESULTS = build_system_prompt("""\
## Task: Extract Contacts from Search Results

You are analyzing search results to identify people at target companies \
for Avelero's DPP sales outreach.

### Company Context

{company_context}

### Search Results

{search_results}

### Instructions

Extract individuals mentioned in the search results who work at the \
specified company. Clean up and structure their information.

### Output Format

Return a JSON array of objects. Nothing else.

```json
[
  {"name": "Jane Smith", "title": "Head of Sustainability", "linkedin_url": "https://www.linkedin.com/in/janesmith"},
  {"name": "John Doe", "title": "CEO", "linkedin_url": ""},
  {"name": "Unknown Person", "title": "", "linkedin_url": ""}
]
```

### Field Specifications

- name: Full name as it appears in the search results.
- title: The person's job title in standardized short format. Follow these rules strictly:
  - Maximum 5 words. Examples: "CEO", "Head of Sustainability", "VP Supply Chain", "Creative Director"
  - Use standard abbreviations: CEO, CTO, CFO, COO, CMO, CRO, VP, SVP, EVP, MD
  - Strip ALL company names: "CEO of Nike" becomes "CEO"
  - Strip ALL locations: "VP Sales, EMEA" becomes "VP Sales"
  - Strip ALL parenthetical info: "CFO (interim)" becomes "CFO"
  - Strip ALL commentary: no "(unverified)", "(formerly)", "(deceased)", dates, or qualifiers
  - English only: translate foreign titles. "Responsabile vendite" becomes "Sales Manager"
  - Current role only: "Former CEO" or "Seeking new opportunities" is NOT a valid title -- set to ""
  - LinkedIn headlines that are slogans, company names, or inspirational text are NOT titles -- set to ""
  - If no clear current job function can be determined, set title to empty string ""
  - Do NOT set title to "Unknown", "No data found", or "No current role found" -- use empty string ""
- linkedin_url: LinkedIn profile URL if available. Empty string if not found.

### Rules

- Do NOT fabricate people who are not mentioned in the search results.
- Do NOT include people who clearly do not work at the target company. \
Watch for false positives where a person works at a DIFFERENT company \
that shares a word with the target (e.g. "Four Kitchens" vs "Four").
- Do NOT include any text outside the JSON array.
- Deduplicate by name -- if the same person appears multiple times, include \
once with the best available information.
- Return an empty array [] if no contacts are found.
""")
