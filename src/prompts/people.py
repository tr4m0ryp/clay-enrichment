"""
Layer 3 prompts: contact discovery and relevance parsing.
"""

from src.prompts.base_context import build_system_prompt

PARSE_CONTACT_RESULTS = build_system_prompt("""\
## Task: Extract and Score Contacts for DPP Outreach

You are analyzing search results to identify people at target companies who are \
relevant contacts for Avelero's DPP sales outreach.

### Company Context

{company_context}

### Search Results

{search_results}

### Instructions

Extract individuals mentioned in the search results who work at the specified \
company. For each person, assess their relevance as a DPP outreach target.

#### Relevance Scoring (1-10 scale)

Score each contact on how likely they are to be the right person to receive a DPP \
sales email from Avelero. Use these role-based weights:

Decision Makers (score 8-10):
- CEO, Co-Founder, Founder, Managing Director
- COO, Chief Operating Officer
- Head of Product, VP Product

Sustainability and Compliance Leads (score 7-9):
- Sustainability Director/Manager/Lead
- CSR Manager, ESG Lead
- Compliance Manager, Regulatory Affairs

Operations and Supply Chain (score 6-8):
- Head of Supply Chain, Supply Chain Director
- Head of Operations, Operations Director
- Head of Production, Production Director
- Sourcing Manager

Marketing and Brand (score 4-6):
- CMO, Brand Director, Head of Marketing
- Creative Director (relevant if DPP is positioned as brand tool)

Other Roles (score 1-3):
- Software engineers, designers, HR, finance, legal, sales
- Interns, assistants, coordinators (unless sustainability-specific)

Boost score by +1 if the person has publicly posted about sustainability, \
circularity, or EU regulation. Cap at 10.

### Output Format

Return a JSON array of objects. Nothing else.

```json
[
  {
    "name": "Jane Smith",
    "title": "Head of Sustainability",
    "linkedin_url": "https://www.linkedin.com/in/janesmith",
    "relevance_score": 9
  }
]
```

### Field Specifications

- name: Full name as it appears in the search results.
- title: Job title. Use the most recent title if multiple are found.
- linkedin_url: LinkedIn profile URL if available. Empty string if not found.
- relevance_score: Integer 1-10 per scoring criteria above.

### Rules

- Do NOT fabricate people who are not mentioned in the search results.
- Do NOT include people who clearly do not work at the target company.
- Do NOT include any text outside the JSON array.
- Do NOT assign high relevance scores to roles unrelated to product, operations, \
sustainability, or executive decision-making.
- If a person's title is ambiguous or missing, set relevance_score to 3.
- Deduplicate by name -- if the same person appears multiple times, include once \
with the best available information.
- Return an empty array [] if no relevant contacts are found.
""")
