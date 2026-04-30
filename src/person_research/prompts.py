"""Person research prompts -- single grounded structured call (per F6/F16).

Replaces the legacy free-text grounded prompt with a Strict-Prompt-Template
JSON-emitting prompt. The new prompt instructs Gemini to autonomously search
the open web for one specific contact and return a typed JSON envelope:
    { "research_text", "key_topics", "research_quality", "sources" }

Per F16 the template is verbatim so output structure stays invariant from
Gemini 3 Pro down through Gemini 2.5 Flash. The worker pairs this prompt
with ``retry_on_malformed_json`` and the tolerant JSON extractor.
"""

from __future__ import annotations

from src.prompts.base_context import build_system_prompt


RESEARCH_PERSON_STRUCTURED = build_system_prompt("""\
## Task
Research one specific contact and return a typed JSON brief that downstream campaign-scoring and email-generation steps can consume directly. You do NOT have web search access for this call -- recall from your training data what you specifically know about this person at this company. When you don't have specific knowledge, return empty fields and research_quality="low" -- do NOT fabricate plausible-sounding facts to fill space.

## Inputs (each is a templated placeholder filled by the caller)
- {contact_name}: contact's full name (string, e.g. "Jane Smith")
- {contact_title}: contact's job title (string, e.g. "Head of Sustainability")
- {company_name}: employer company name (string, e.g. "Patagonia")
- {domain}: employer canonical domain, no scheme, no www (string, e.g. "patagonia.com")

## Output Format -- EXACT
Return ONLY a valid JSON object matching this schema. No markdown fences. No prose before or after. No explanation. No preamble.

{
  "research_text": "string -- multi-paragraph research brief. Sections: Professional Background, Achievements & Milestones, Public Activity, Industry Involvement, Recent Activity (last 6-12 months), DPP/Sustainability Relevance. Cite specific facts (names, dates, event titles, publications). Plain prose, no markdown headings required, no JSON inside.",
  "key_topics": ["string -- max 60 chars, lowercase, e.g. 'sustainability', 'supply chain transparency'"],
  "research_quality": "string -- one of: high, medium, low",
  "sources": ["string -- absolute https URL pulled from the grounded search citations"]
}

### Field-by-field rules
- research_text: 600-2000 chars of plain prose. Confirm identity using {company_name} and {contact_title} before attributing facts -- never confuse the contact with someone else of the same name. If a section has no findings, write one sentence stating that explicitly (an honest gap is better than a fabricated fact). Use empty string "" if NOTHING about this person can be confirmed in any search result. NEVER write "Unknown", "N/A", "No data found", or any sentinel string.
- key_topics: 0-7 recurring themes the contact is publicly associated with. Each entry max 60 chars, lowercase. Empty list [] if nothing usable. Do NOT include the company name as a topic.
- research_quality: exactly one of "high" / "medium" / "low".
  - "high": multiple relevant, citable facts across categories; clear identity confirmation.
  - "medium": some useful facts but gaps remain; identity confirmed.
  - "low": very few results clearly about this person; rely on title + company alone.
  Use "low" if research_text is empty.
- sources: empty list [] is the EXPECTED output for this call -- you do not have search access, so you cannot produce real citation URLs. Do NOT fabricate URLs. NEVER list LinkedIn slug URLs, conference URLs, or news-article URLs you "remember" -- those are reconstructed and almost always 404. The sources field exists for a future grounded variant of this call; for now, leave it [].

## Process -- follow exactly
1. Verify from training data that you specifically recall this person at this company. If unsure, set research_text="" and research_quality="low".
2. Compose research_text from the FACTS YOU KNOW about this person + this company combination -- e.g. "Bert van Son founded MUD Jeans in 2012 and pioneered the lease-a-jean circular model" is acceptable if widely-reported in your training. "Bert van Son spoke at the 2026 Copenhagen Fashion Summit" is NOT acceptable unless you have specific recall of that event.
3. Pick research_quality honestly:
   - "high" only when you have multiple specific, verifiable facts about THIS person at THIS company
   - "medium" when you have role + general industry knowledge but limited person-specific facts
   - "low" when you can only restate the role + company already given in the input
4. If a section has no findings, state that explicitly inside research_text in one sentence ("No public-profile information specifically about this person at this company found in training data").

## Hard Rules (model MUST obey regardless of capability)
- Output is JSON ONLY. No prose before or after. No markdown fences.
- If a field cannot be filled, use the type-appropriate empty value: "" for strings, [] for lists.
- Never fabricate facts, citations, or URLs. If uncertain, output the empty value or state the gap inside research_text.
- Never confuse this person with others sharing the same name -- always anchor on {company_name} and {contact_title}.
- Never use emojis.
- Never include keys not in the schema. Never omit keys in the schema.
- Never include comments inside the JSON.

## Output Examples
### Good output
{"research_text": "Jane Smith leads sustainability at Patagonia, where she has driven the Worn Wear repair program since 2023. She spoke on ESPR readiness at Copenhagen Fashion Summit 2025 and is quoted in Vogue Business 2026-02 on traceability investments. Recent activity (last 6 months): announced partnership with bluesign in 2026-03; presented Patagonia's 2026 sustainability report. DPP relevance is direct -- the brand publicly tracks fibre origin and is preparing for ESPR mandates.", "key_topics": ["sustainability", "supply chain transparency", "circular fashion", "espr"], "research_quality": "high", "sources": ["https://www.patagonia.com/our-footprint/", "https://copenhagenfashionsummit.com/speakers/jane-smith", "https://www.voguebusiness.com/sustainability/patagonia-traceability-2026"]}

### Good output (thin signal)
{"research_text": "No public profile clearly tied to this contact at the specified company was found. Searches across LinkedIn cached pages, conference sites, and press archives returned no results for the name combined with the company or title. Outreach should rely on company-level context.", "key_topics": [], "research_quality": "low", "sources": []}

### Bad outputs (do NOT do these)
- "Here is the JSON: {...}"                                                                                              (prose before)
- "```json\\n{...}\\n```"                                                                                                  (markdown fence)
- {"research_text": "Unknown", "key_topics": [], "research_quality": "low", "sources": []}                               (sentinel string instead of "")
- {"research_text": "...", "key_topics": [...], "research_quality": "maybe", "sources": [...]}                           (research_quality not in allowed set)
- {"research_text": "...", "key_topics": [...], "research_quality": "high", "sources": [...], "extra_field": "..."}      (extra key not in schema)
- {"research_text": "..."}                                                                                                (missing required keys)
""")
