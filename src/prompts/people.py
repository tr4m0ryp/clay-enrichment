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
  {
    "name": "Jane Smith",
    "title": "Head of Sustainability",
    "linkedin_url": "https://www.linkedin.com/in/janesmith"
  }
]
```

### Field Specifications

- name: Full name as it appears in the search results.
- title: Job title. Use the most recent title if multiple are found.
- linkedin_url: LinkedIn profile URL if available. Empty string if not found.

### Rules

- Do NOT fabricate people who are not mentioned in the search results.
- Do NOT include people who clearly do not work at the target company.
- Do NOT include any text outside the JSON array.
- Deduplicate by name -- if the same person appears multiple times, include \
once with the best available information.
- Return an empty array [] if no contacts are found.
""")
