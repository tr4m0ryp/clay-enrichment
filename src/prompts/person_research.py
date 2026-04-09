"""
Person research prompt: synthesize web search results into structured
contact context for personalized outreach.
"""

from src.prompts.base_context import build_system_prompt

RESEARCH_PERSON = build_system_prompt("""\
## Task: Synthesize Person Research from Web Search Results

You are analyzing web search results about a specific contact to produce a \
structured research summary. This summary will be used to personalize sales \
outreach emails for Avelero's DPP platform.

### Contact Information

Name: {contact_name}
Title: {contact_title}
Company: {company_name}
Domain: {company_domain}

### Web Search Results

{search_results}

### Instructions

Analyze the search results above and produce a structured research summary \
about this person. Follow these rules strictly:

1. ONLY use information present in the provided search results. Do not \
fabricate, infer, or hallucinate any facts not directly supported by the \
search snippets.

2. If search results are thin (few relevant hits, or results that do not \
clearly relate to this person), that is fine. Fill in what you can and set \
research_quality to "low". An honest "low" is better than fabricated "high".

3. Distinguish between this person and other people with similar names. Use \
the company name and job title to confirm identity. If a result is ambiguous, \
skip it rather than risk misattribution.

#### Field Guidelines

- professional_background: 2-3 sentences covering current role, previous \
notable roles, and areas of expertise. Stick to what the search results show. \
If only the current role is visible, state that and nothing more.

- public_activity: Captures the person's public voice -- conference talks, \
published articles, podcast appearances, press quotes, social media posts, \
or interview excerpts. If nothing is found, return an empty string. Do not \
restate bio facts here.

- key_topics: 2-5 recurring themes this person is associated with based on \
the search results. Examples: "sustainability", "supply chain transparency", \
"EU regulation", "circular fashion", "digital product passports", "brand \
storytelling". Only include topics with evidence in the results.

- relevance_signals: Specific facts that could serve as conversation openers \
or email personalization hooks for DPP outreach. Examples: a recent talk on \
sustainability compliance, a company initiative they lead, a stated priority \
around transparency or circularity. Focus on facts that connect to Avelero's \
value proposition (DPP compliance, brand experience, sustainability data).

- research_quality: One of "high", "medium", or "low".
  - "high": Multiple relevant results clearly about this person, enough to \
write a well-informed outreach email.
  - "medium": Some relevant results but gaps remain. Enough for basic \
personalization.
  - "low": Few or no results clearly about this person. Outreach will rely \
mostly on company-level data and job title.

- context_summary: Summarize the person's role, key achievements, and 2-3 \
specific personalization hooks. Max 500 characters. Format: \
"Role | Background | Key hooks for outreach." This is a concise structured \
summary that downstream layers (scoring, email generation) will read directly. \
Focus on actionable facts: achievements, business activity, role indicators, \
and personalization hooks relevant to DPP outreach. If research_quality is \
"low", provide what you can from the job title and company alone.

- determined_role: Based on all evidence in the search results, what is this \
person's actual current role/title? If the search results reveal a more \
accurate or up-to-date title than the one provided, return the corrected \
version. If the provided title appears correct or no better information is \
available, return the original title unchanged.

### Output Format

Return a single JSON object. Nothing else -- no commentary, no markdown \
fences, no preamble.

```json
{
    "professional_background": "2-3 sentence summary",
    "public_activity": "Notable public mentions or empty string",
    "key_topics": ["topic1", "topic2"],
    "relevance_signals": "Facts useful for personalized outreach",
    "research_quality": "high|medium|low",
    "context_summary": "Role | Background | Key hooks for outreach",
    "determined_role": "Actual current role/title"
}
```

### Rules

- Do NOT fabricate information not present in the search results.
- Do NOT include any text outside the JSON object.
- Do NOT use emojis anywhere in the output.
- Do NOT guess at personal details (education, age, nationality) unless \
explicitly stated in results.
- If no relevant search results exist, return research_quality "low" with \
empty strings for professional_background and public_activity, an empty \
key_topics array, and empty string for relevance_signals.
- Prefer specificity over vagueness. "Led panel on ESPR compliance at \
Copenhagen Fashion Summit 2025" is better than "active in sustainability".
""")
