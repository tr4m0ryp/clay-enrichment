"""
Layer 3 prompts: contact extraction and structuring.
"""

from src.prompts.base_context import build_system_prompt

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
