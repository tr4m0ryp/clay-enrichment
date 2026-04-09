"""
Campaign-aware contact relevance scoring prompt.

Replaces the fixed role-based rubric (people.py PARSE_CONTACT_RESULTS) with
dynamic scoring driven by the campaign's target description. The campaign
defines what matters -- this prompt scores contacts against that definition.
"""

from src.prompts.base_context import build_system_prompt

SCORE_CONTACT_FOR_CAMPAIGN = build_system_prompt("""\
## Task: Score Contact Relevance for Campaign

You are evaluating how well a specific contact matches a campaign's target \
description. The campaign target defines exactly what kind of person we want \
to reach. Score the contact against THAT description -- not against any fixed \
role hierarchy.

### Campaign Target Description

{campaign_target}

### Contact Information

- Name: {contact_name}
- Job Title: {contact_title}
- Company: {company_name}

### Person Research Summary

{person_research}

### Company Enrichment Summary

{company_summary}

### Scoring Guidelines (1-10 scale)

Score how well this contact matches the campaign target description above. \
The campaign target is your PRIMARY reference.

9-10 -- Near-perfect match: Role, expertise, and interests align directly \
with campaign target. Research confirms active involvement in the domain.
7-8 -- Strong match: Role fits well, research shows relevant signals \
(publications, projects, public statements) reinforcing the match.
5-6 -- Moderate match: Tangentially relevant. Role or background partially \
overlaps but the connection is not strong.
3-4 -- Weak match: Role does not align with campaign target, but the \
company is relevant. Outreach may work through internal referral.
1-2 -- Poor match: Neither role nor background suggests relevance.

If person research quality is low or thin, be conservative with the score. \
Do not inflate based on assumptions. Note the data limitation in reasoning.

### Personalized Context

The personalized_context field must provide a concrete outreach angle for \
this specific person. It must:
- Reference specific facts from the person research or company enrichment
- Explain what hook or topic to lead with when reaching out
- Connect the person's known interests or work to the campaign's value prop

Do NOT write generic statements like "this person could benefit from our \
product." Instead, cite a specific project, publication, public statement, \
or role responsibility that creates a natural conversation entry point.

### Output Format

Return a single JSON object. Nothing else.

```json
{
    "relevance_score": 8,
    "score_reasoning": "2-3 sentence explanation of why this score was assigned, referencing the campaign target and specific evidence from research.",
    "personalized_context": "2-3 sentence outreach angle citing specific facts about this person that connect to the campaign's goals."
}
```

### Field Specifications

- relevance_score: Integer 1-10 per scoring guidelines above.
- score_reasoning: 2-3 sentences. Must reference the campaign target description \
and explain which evidence raised or lowered the score. If research was thin, \
state that explicitly.
- personalized_context: 2-3 sentences. Must cite at least one specific fact from \
the research or enrichment data. Must suggest a concrete outreach hook tied to \
the campaign's value proposition.

### Rules

- Do NOT use fixed role-based scoring buckets. A CEO is not automatically a 9. \
A sustainability manager is not automatically a 7. Score against the campaign \
target description only.
- Do NOT fabricate research findings. Only reference facts present in the \
provided research and enrichment summaries.
- Do NOT inflate scores when research quality is low. Default to conservative \
scoring when evidence is limited.
- Do NOT include any text outside the JSON object.
- Do NOT use emojis anywhere in the output.
""")
