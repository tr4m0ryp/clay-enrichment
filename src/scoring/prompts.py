"""Combined contact structuring + campaign-aware scoring prompt.

``STRUCTURE_AND_SCORE_PERSON`` takes the raw grounded research text from
the person-research worker plus a campaign target description, structures
the research into citable fields, and scores the contact against the
campaign target -- all in one JSON call.

Follows the Strict Prompt Template (F16): explicit in-prompt JSON schema,
field-by-field rules, type-appropriate empty values (``""``, ``[]``,
``0``, ``false``), hard "Output ONLY JSON" rules, and good/bad output
examples. The output schema is invariant across served-model tiers
(Gemini 3 Pro -> 2.5 Pro -> 2.5 Flash) so the worker's parser stays
fixed regardless of any downshift inside the api_keys pool.

The schema preserved here is consumed by ``src/scoring/worker.py`` and
written to the ``contact_campaigns`` junction table plus the
denormalized ``contacts`` row. Field names and semantics MUST stay
identical to keep downstream readers and the SQL schema unchanged.
"""

from __future__ import annotations

from src.prompts.base_context import build_system_prompt
from src.prompts.runtime import resolve


_DEFAULT_STRUCTURE_AND_SCORE_PERSON = """\
## Task
Structure raw person research into citable fields and score the contact's \
fit against the campaign target description. Output a single JSON object \
combining structured profile, scoring, and personalized outreach hooks.

## Inputs
- {campaign_target}: free-text description of the campaign's ideal \
contact (industry, role, signals, geography). The PRIMARY scoring \
reference -- not any fixed role hierarchy.
- {contact_name}: the contact's full name as known in the pipeline.
- {contact_title}: the contact's job title from the discovery layer. \
May be stale -- use the researched title when research contradicts it.
- {company_name}: name of the contact's current employer.
- {person_research}: raw grounded research text about this contact \
(career history, public posts, talks, achievements, recent activity).
- {company_summary}: enrichment summary of the contact's company \
(industry, sustainability focus, recent events, DPP fit signals).

Inputs as filled by the caller follow this paragraph:

- campaign_target: {campaign_target}
- contact_name: {contact_name}
- contact_title: {contact_title}
- company_name: {company_name}
- person_research: {person_research}
- company_summary: {company_summary}

## Output Format -- EXACT
Return ONLY a valid JSON object matching this schema. No markdown \
fences. No prose before or after. No explanation. No preamble. The \
object MUST contain exactly these eleven keys, in any order, and no \
additional keys.

{
  "determined_role": "string -- current role/title verified from research, max 200 chars",
  "professional_background": "string -- 2-3 sentences on role, career, expertise, max 800 chars",
  "achievements": "string -- specific achievements/milestones/recognitions, max 800 chars",
  "public_activity": "string -- conference talks, articles, interviews, social posts, max 800 chars",
  "key_topics": ["string"],
  "relevance_signals": "string -- specific facts connecting this person to the campaign domain, max 800 chars",
  "research_quality": "string -- exactly one of \\"high\\", \\"medium\\", \\"low\\"",
  "context_summary": "string -- structured Role | Background | Key hooks summary, max 500 chars",
  "relevance_score": 0,
  "score_reasoning": "string -- 2-3 sentences explaining the score against the campaign target, max 800 chars",
  "personalized_context": "string -- 3-5 numbered outreach hooks each citing a concrete fact, max 1500 chars"
}

### Field-by-field rules
- determined_role: the actual current role/title as verified from \
``{person_research}``. If research contradicts ``{contact_title}``, \
use the researched value. Use empty string "" when research does not \
verify any current role. NEVER write "Unknown", "N/A", "Not found", or \
any sentinel string.
- professional_background: 2 to 3 sentences covering current role, \
career path, and domain expertise. Factual, evidence-based, no \
speculation. Use empty string "" if the research is too thin to write \
even one sentence.
- achievements: specific, citable accomplishments -- awards, product \
launches, funding rounds, published work, named programs. Use empty \
string "" if no achievements appear in the research. NEVER write "No \
data found" or "None".
- public_activity: conference talks, published articles, interviews, \
podcasts, named social-media posts -- with the venue or publication \
when available. Use empty string "" if none present in the research.
- key_topics: list of 3 to 5 short topic labels the contact is \
associated with based on the research (e.g. "circular fashion", \
"DPP", "supply chain transparency"). Use empty list [] if no clear \
topics emerge. Each label max 60 chars.
- relevance_signals: specific facts from the research that connect \
this person to the campaign target domain. Use empty string "" if \
none. NEVER write "No relevance signals found".
- research_quality: exactly one of "high" / "medium" / "low". "high" \
means multiple corroborating sources with specific details; "medium" \
means some useful info but gaps; "low" means thin or mostly generic \
content. Use "low" if no usable research is available.
- context_summary: concise structured summary in the format \
"Role | Background | Key hooks". Maximum 500 characters. Use empty \
string "" only when ``{person_research}`` is itself empty.
- relevance_score: integer 1 to 10 per the scoring guidelines below. \
Use 0 if no usable research is available -- the worker treats 0 as a \
deferred-scoring sentinel and clamps stored scores to 1..10. Do NOT \
output a string for this field; output a JSON integer.
- score_reasoning: 2 to 3 sentences. MUST reference the campaign \
target and the specific evidence that raised or lowered the score. \
If research was thin, state that explicitly in the reasoning. Use \
empty string "" only when the score itself was 0 due to no inputs.
- personalized_context: 3 to 5 numbered outreach hooks. Each hook \
cites one concrete fact from the research (a talk, a launch, a post, \
a regulatory filing, a partnership) and connects it to the campaign \
value proposition. Prioritize TIMELINE hooks -- recent events, \
upcoming deadlines, new initiatives. Use empty string "" only when \
no usable research is available. NEVER write generic hooks like \
"this person could benefit from our product".

### Scoring guidelines (1 to 10 scale)
- 9 to 10: near-perfect match. Role, expertise, and research signals \
align directly with ``{campaign_target}``. Research confirms active \
involvement.
- 7 to 8: strong match. Role fits well; research confirms relevant \
activity (publications, projects, public statements).
- 5 to 6: moderate match. Tangential. Role or background partially \
overlaps but the connection is not strong.
- 3 to 4: weak match. Company is relevant but role does not align with \
``{campaign_target}``. Outreach may work via internal referral.
- 1 to 2: poor match. Neither role nor background suggests relevance.

A CEO is NOT automatically a 9. A sustainability manager is NOT \
automatically a 7. Score against ``{campaign_target}`` only, NOT \
against fixed role-tier buckets.

When research_quality is "low", be conservative -- do not inflate the \
score on assumptions. Note the data limitation in score_reasoning.

## Process
1. Parse ``{person_research}`` and ``{company_summary}``. Extract only \
facts that are stated; do not invent connecting details.
2. Determine the current role: prefer ``{person_research}`` over \
``{contact_title}`` when they conflict. Fall back to "" if neither is \
verifiable.
3. Fill professional_background, achievements, public_activity, \
key_topics, and relevance_signals from the research evidence. Use \
type-appropriate empty values when a field is unsupported.
4. Set research_quality based on source breadth and specificity.
5. Score against ``{campaign_target}`` using the 1-10 guidelines. \
Cite the specific evidence that raised or lowered the score in \
score_reasoning.
6. Draft 3 to 5 personalized_context hooks. Each must cite a concrete \
fact from the research and connect it to ``{campaign_target}``. \
Prioritize TIMELINE events. Number them 1., 2., 3. ...
7. Write context_summary as "Role | Background | Key hooks", max 500 \
characters.

## Hard Rules
- Output is JSON ONLY. No prose before or after. No markdown fences. \
No commentary. No explanation.
- Empty values: "" for strings, [] for lists, 0 for integers, false \
for booleans. NEVER write "Unknown", "N/A", "TBD", "No data found", \
"None found", or any other sentinel string.
- Never fabricate research findings. Only reference facts present in \
``{person_research}`` and ``{company_summary}``.
- Never inflate the relevance_score on assumptions when \
research_quality is "low".
- Never use emojis anywhere in the output.
- Never include keys not in the schema. Never omit keys. Exactly \
eleven keys: determined_role, professional_background, achievements, \
public_activity, key_topics, relevance_signals, research_quality, \
context_summary, relevance_score, score_reasoning, \
personalized_context.
- Never include comments inside the JSON.
- relevance_score is a JSON integer, NOT a string. key_topics is a \
JSON array of strings, NOT a comma-separated string.

## Output Examples
### Good output (abridged)
{"determined_role": "Head of Sustainability", "professional_background": "Leads sustainability at a mid-market EU fashion brand. Five years at the company, previously at a circular-economy nonprofit. Owns the company's ESPR and DPP roadmap.", "achievements": "Launched the company's circular denim program in Q1 2026. Spoke at Copenhagen Fashion Summit 2025 on DPP as a brand storytelling tool. Named to BoF Sustainability 25 (2025).", "public_activity": "Copenhagen Fashion Summit 2025 talk titled \\"making DPP a brand storytelling tool\\". Quoted in Vogue Business 2026-03 on EU compliance timelines. LinkedIn post 2026-03 criticizing compliance-first DPP vendors.", "key_topics": ["DPP", "circular fashion", "supply chain transparency", "ESPR compliance"], "relevance_signals": "Public ESPR/DPP advocacy; led circular denim launch Q1 2026; on record about compliance-first vendors missing brand experience.", "research_quality": "high", "context_summary": "Head of Sustainability | 5 yrs at the brand, ex circular-economy NGO | Copenhagen Fashion Summit 2025 talk; Q1 2026 circular denim launch; LinkedIn frustration with compliance-first DPP vendors", "relevance_score": 9, "score_reasoning": "Direct match to the campaign target: owns the brand's DPP roadmap, has publicly framed DPP as a brand-storytelling tool (Avelero's exact positioning), and the Q1 2026 circular launch is a live timeline anchor for outreach.", "personalized_context": "1. Spoke at Copenhagen Fashion Summit 2025 on \\"making DPP a brand storytelling tool\\" -- directly aligned with Avelero's Passport Designer positioning.\\n2. Led the launch of the brand's circular denim program in Q1 2026 -- active in the supply-chain transparency space where DPP adds immediate value.\\n3. LinkedIn post from March 2026 expressed frustration with \\"compliance-first DPP vendors that ignore brand experience\\" -- Avelero's design-forward approach is the exact counter.\\n4. Brand expanding into 4 new EU markets in 2026 -- mid-2028 DPP mandate becomes unavoidable at this scale."}

### Good output (thin research, low quality)
{"determined_role": "", "professional_background": "", "achievements": "", "public_activity": "", "key_topics": [], "relevance_signals": "", "research_quality": "low", "context_summary": "", "relevance_score": 3, "score_reasoning": "Research returned no specific evidence beyond the contact's title. Conservative score reflects the data gap; no signals raised or lowered the baseline.", "personalized_context": ""}

### Bad outputs (do NOT do these)
- "Here is the JSON: {...}"                                 (prose before)
- "```json\\n{...}\\n```"                                    (markdown fence)
- {"determined_role": "Unknown", ...}                        (sentinel string instead of "")
- {"relevance_score": "8", ...}                              (string instead of integer)
- {"key_topics": "DPP, circular fashion", ...}               (comma-string instead of list)
- {"relevance_signals": "No relevance signals found", ...}   (sentinel string instead of "")
- {"determined_role": "...", "extra_field": "..."}           (extra key not in schema)
- {"determined_role": "..."}                                 (missing required keys)
"""

STRUCTURE_AND_SCORE_PERSON = build_system_prompt(
    resolve("scoring_structure_and_score_person", _DEFAULT_STRUCTURE_AND_SCORE_PERSON)
)
