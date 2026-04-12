"""
Combined contact structuring and campaign-aware scoring prompt.

STRUCTURE_AND_SCORE_PERSON replaces the separate person research structuring
and campaign scoring steps. It takes raw grounded research text plus a campaign
target and produces structured contact data, relevance scoring, and
personalized outreach hooks in one JSON call.
"""

from src.prompts.base_context import build_system_prompt

STRUCTURE_AND_SCORE_PERSON = build_system_prompt("""\
## Task: Structure Research and Score Contact for Campaign

You have two jobs in a single pass:
1. Structure raw person research into clean, citable fields.
2. Score the contact's relevance against a specific campaign target and \
generate personalized outreach hooks.

### Campaign Target Description

{campaign_target}

### Contact Information

- Name: {contact_name}
- Job Title (may be outdated): {contact_title}
- Company: {company_name}

### Person Research (raw grounded text)

{person_research}

### Company Enrichment Summary

{company_summary}

---

### Part 1: Structure the Research

Extract and organize the raw research into the structured fields below. \
Use only facts present in the research text. If a field has no supporting \
evidence, write "No data found" rather than inventing content.

### Part 2: Score Against Campaign Target

Score how well this contact matches the campaign target description above. \
The campaign target is your PRIMARY reference -- not any fixed role hierarchy.

#### Scoring Guidelines (1-10 scale)

9-10 -- Near-perfect match: Role, expertise, and research signals align \
directly with the campaign target. Research confirms active involvement.
7-8 -- Strong match: Role fits well, research confirms relevant activity \
(publications, projects, public statements).
5-6 -- Moderate match: Tangentially relevant. Role or background partially \
overlaps but the connection is not strong.
3-4 -- Weak match: Company is relevant but role does not align with campaign \
target. Outreach may work through internal referral.
1-2 -- Poor match: Neither role nor background suggests relevance.

If research quality is low or thin, be conservative with the score. Do not \
inflate based on assumptions. Note the data limitation in score_reasoning.

### Part 3: Generate Personalized Outreach Hooks

The personalized_context field is the primary input for email personalization. \
It must contain 3-5 distinct outreach hooks as a numbered list. Each hook must:

- Cite a SPECIFIC fact: a talk, a product launch, a LinkedIn post, an \
initiative, an achievement, a regulatory filing, a partnership announcement.
- Prioritize TIMELINE HOOKS: recent events, upcoming deadlines, new \
initiatives. Timeline hooks generate 3.4x more meetings than static facts.
- Connect the cited fact to the campaign's value proposition.
- Use the prospect's own language where possible (quote phrases from their \
posts, talks, or interviews when available in the research).

Example of good personalized_context:
```
1. Spoke at Copenhagen Fashion Summit 2025 on "making DPP a brand storytelling \
tool" -- directly aligned with Avelero's Passport Designer positioning.
2. Led the launch of their circular denim program in Q1 2026 -- active in the \
supply chain transparency space where DPP adds immediate value.
3. LinkedIn post from March 2026 expressed frustration with "compliance-first \
DPP vendors that ignore brand experience" -- Avelero's design-forward approach \
is the exact counter.
4. Company expanding into 4 new EU markets in 2026 -- mid-2028 DPP mandate \
becomes unavoidable at this scale.
```

Do NOT write generic hooks like "this person could benefit from our product." \
Every hook must reference a concrete, verifiable fact from the research.

### Output Format

Return a single JSON object. Nothing else.

```json
{{
    "determined_role": "Actual current role/title verified from research",
    "professional_background": "2-3 sentence summary of role, career, expertise",
    "achievements": "Key achievements, milestones, recognitions -- specific and citable",
    "public_activity": "Conference talks, articles, interviews, social posts",
    "key_topics": ["topic1", "topic2", "topic3"],
    "relevance_signals": "Specific facts connecting this person to DPP/sustainability/fashion-tech",
    "research_quality": "high|medium|low",
    "context_summary": "Concise structured summary: Role | Background | Key hooks. Max 500 chars.",
    "relevance_score": 8,
    "score_reasoning": "2-3 sentences explaining the score against the campaign target, citing specific evidence.",
    "personalized_context": "3-5 specific outreach hooks as numbered list. Each cites a concrete fact. Prioritize timeline events."
}}
```

### Field Specifications

- determined_role: The actual current role/title as verified from the research. \
If research contradicts the provided title, use the researched one.
- professional_background: 2-3 sentences covering current role, career path, \
and domain expertise. Factual, no speculation.
- achievements: Specific, citable accomplishments -- awards, product launches, \
funding rounds, published work. Write "No data found" if none in research.
- public_activity: Conference talks, published articles, interviews, podcasts, \
social media posts mentioned in research. Write "No data found" if none.
- key_topics: Array of 3-5 topic strings the person is associated with based \
on research evidence. Use short labels (e.g., "circular fashion", "DPP", \
"supply chain transparency").
- relevance_signals: Specific facts from the research that connect this person \
to DPP, sustainability, fashion-tech, or the campaign target domain. Write \
"No relevance signals found" if none.
- research_quality: "high" if multiple corroborating sources with specific \
details; "medium" if some useful info but gaps; "low" if thin or mostly \
generic content.
- context_summary: Concise structured summary in the format \
"Role | Background | Key hooks". Maximum 500 characters. This is used as \
a quick-reference field.
- relevance_score: Integer 1-10 per scoring guidelines above.
- score_reasoning: 2-3 sentences. Must reference the campaign target and \
explain which evidence raised or lowered the score. If research was thin, \
state that explicitly.
- personalized_context: 3-5 specific outreach hooks as a numbered list. Each \
hook cites a concrete fact and connects it to the campaign value proposition. \
Prioritize timeline events (recent launches, upcoming deadlines, new roles).

### Rules

- Score against the campaign target, NOT fixed role hierarchies. A CEO is not \
automatically a 9. A sustainability manager is not automatically a 7.
- Do NOT fabricate research findings. Only reference facts present in the \
provided research and enrichment summaries.
- Do NOT inflate scores when research quality is low. Default to conservative \
scoring when evidence is limited.
- Do NOT include any text outside the JSON object.
- Do NOT use emojis anywhere in the output.
""")


# ---------------------------------------------------------------------------
# DEPRECATED -- kept for backward compatibility during migration.
# Use STRUCTURE_AND_SCORE_PERSON instead, which combines structuring + scoring.
# ---------------------------------------------------------------------------
_SCORE_CONTACT_FOR_CAMPAIGN_LEGACY = build_system_prompt("""\
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
{{
    "relevance_score": 8,
    "score_reasoning": "2-3 sentence explanation of why this score was assigned, referencing the campaign target and specific evidence from research.",
    "personalized_context": "2-3 sentence outreach angle citing specific facts about this person that connect to the campaign's goals."
}}
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
