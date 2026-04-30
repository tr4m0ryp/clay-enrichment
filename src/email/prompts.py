"""
Layer 4 prompts: personalized cold outreach email generation.

Strict 75-100 word, 3-part cold email structure: timeline-anchored
personal hook from Contact Context, language-mirroring value bridge
tied to campaign target, low-friction question CTA. Requires 3
distinct personalization points per email.

The prompt is locked to the per-campaign approved voice via two
placeholders rendered at the TOP of the system prompt before any
target / contact context: ``{email_style_profile}`` (the campaign's
voice anchor, populated by the Next-button flow per task 015) and
``{banned_phrases}`` (campaign-specific phrases to avoid, on top of
the standard ban list below). Both are filled by ``src/email/gen.py``
from the ``campaigns`` row.
"""

from src.prompts.base_context import build_system_prompt
from src.prompts.runtime import resolve

_DEFAULT_GENERATE_EMAIL = """\
## Task: Generate a Personalized Cold Outreach Email

You are writing a single cold email on behalf of Moussa at Avelero. The email \
must follow the exact 3-part structure below. No deviations.

### Campaign Voice Profile (LOCKED -- you MUST follow)

This is the per-campaign approved voice. Every line you produce must conform. \
If the voice profile contradicts a generic instinct, the voice profile wins.

{email_style_profile}

### Campaign-Specific Banned Phrases

NEVER use any of the following in the subject or body. These are in addition \
to the standard ban list further down -- both apply.

{banned_phrases}

### Inputs

**Campaign target:** {campaign_target}

**Contact name:** {contact_name}

**Company name:** {company_name}

**Contact context (primary personalization source):**
{contact_context}

**Personalized context (campaign-specific outreach angle):**
{personalized_context}

### Required 3-Part Structure

**Part 1 -- Personal Hook (1-2 sentences):**
- One specific, verifiable observation about the recipient.
- Drawn from the Contact Context above.
- The first sentence must be entirely about the recipient. Never mention Avelero \
in this part.
- NO generic compliments. "Love what you're doing" is banned unless followed by \
a concrete, cited detail. If the Context is thin, reference a specific company \
fact instead.

Prefer TIMELINE HOOKS -- observations tied to a specific event, date, or \
inflection point:
- A recent product launch, collection drop, or market expansion
- A new hire, promotion, or leadership change
- A conference talk or panel from the past 6 months
- A funding round, partnership announcement, or strategic pivot
- An upcoming deadline or regulatory milestone affecting them

Timeline hooks achieve 2.3x higher reply rates than generic observations. \
If no timeline event is available, fall back to a specific achievement or \
public statement.

**Part 2 -- Value Bridge (1-2 sentences):**
- Connect their situation to an outcome Avelero delivers.
- Frame as what happens for THEM, not what Avelero does.
- Driven by the campaign target description.
- No feature lists. No bullet points. One clear outcome statement.
- Reference the EU regulatory timeline (mid-2028 DPP mandate) ONLY if it adds \
genuine urgency to this specific contact. Do not force it.
- Use terminology and framing from the Contact Context. If they talk about \
"brand storytelling," use that phrase. If they say "supply chain transparency," \
echo it back. People respond to their own words.

**Part 3 -- Low-Friction CTA (1 sentence):**
- A single interest-based question.
- Style: "Is this relevant to where you're focused right now?" or \
"Worth exploring, or not a priority yet?"
- NO Calendly links. NO scheduling links of any kind.
- NO "Got 30 minutes?" or "Can we hop on a call?"

### Three Custom Snippets Requirement

The email must contain at least 3 distinct personalization points:
1. The opening hook (Part 1) -- one specific fact about the recipient.
2. A connecting detail in the value bridge (Part 2) -- ties their situation to \
an outcome.
3. A contextual detail in the CTA or surrounding text -- shows this email was \
written FOR them.

Each must be traceable to a specific fact in the context. Generic observations \
do not count. If you cannot find 3 distinct facts, use the strongest 2 and \
derive the third from a different angle on existing context.

### Subject Line Rules

- 2-4 words only, under 40 characters total.
- Reference a pain point or objective relevant to the recipient.
- Do NOT use the recipient's first name in the subject.
- No exclamation marks. No ALL CAPS words.
- No generic subjects like "Partnership Opportunity" or "Quick Question".

### Anti-Pitching Constraint

CRITICAL: Do not pitch Avelero's product. Pitching reduces reply rates by 57%.
Frame everything as an outcome for the recipient, not a feature of Avelero.
Wrong: "Avelero's Passport Designer lets you customize DPP pages"
Right: "Your brand identity could extend all the way to the product passport"

### Hard Constraints

- Minimum 75 words, maximum 100 words (body only, excluding greeting and sign-off).
- Maximum 5 lines of visible text in the body.
- At least 3 personalization points (see Three Custom Snippets above).
- No feature lists or bullet points anywhere in the email.
- No Calendly or scheduling links.
- No emojis. Ever.
- No corporate filler: ban "I hope this finds you well", "I wanted to reach out", \
"I came across your company", "In today's landscape", "innovative", "cutting-edge", \
"revolutionary", "game-changing".
- The campaign-specific banned-phrase list at the top of this prompt is \
ADDITIVE on top of this standard ban list -- both apply simultaneously.
- No ALL CAPS words.
- First sentence must be about the recipient, never about Avelero.
- Do NOT mention competitors by name.
- Do NOT make claims about Avelero not supported by the company context above.
- Do NOT include unsubscribe links or legal disclaimers.
- Sign off as just "Moussa" (no last name, casual tone).
- Greeting: "Hi {contact_name}," on its own line.

### Output Format -- EXACT

Return ONLY a valid JSON object matching this schema. No markdown fences. No \
prose before or after. No explanation. No preamble.

{
  "contact_name": "string -- the recipient's name as provided in the input",
  "subject": "string -- 2-4 words, under 40 chars, no exclamation",
  "body": "string -- greeting + 3-part body + sign-off, separated by \\n\\n"
}

#### Field-by-field rules

- contact_name: echo the contact's name (provided as the Contact name input \
above) verbatim. Use empty string "" only if the input was literally \
empty -- never write "Unknown" or "N/A".
- subject: 2-4 words, under 40 characters total, no exclamation marks, no \
ALL CAPS, no recipient first-name. Use empty string "" if no acceptable \
subject can be produced (the worker will substitute a default).
- body: a single string containing the full email -- "Hi <contact_name>,", \
then \\n\\n, then Part 1, then \\n\\n, then Part 2, then \\n\\n, then Part 3, \
then \\n\\n, then "Moussa". Body word count (excluding greeting and sign-off) \
between 75 and 100. Use empty string "" only if the email cannot be \
produced -- never invent fake recipient details.

#### Output Examples

Good output:
{"contact_name": "Sara Klein", "subject": "EU passport timing", "body": "Hi Sara,\\n\\nSaw your March launch of the wool capsule with the recycled-content claim on the hangtags -- that's the kind of provenance story that translates well to the passport layer.\\n\\nWith the mid-2028 DPP deadline pulling forward, your existing transparency framing could carry straight into the QR experience without rebuilding the brand voice from scratch.\\n\\nWorth exploring as you map out 2027 production, or still too early?\\n\\nMoussa"}

Bad outputs (do NOT do these):
- "Here is the JSON: {...}"            (prose before the object)
- "```json\\n{...}\\n```"              (markdown fence)
- {"contact_name": "Unknown", ...}     (sentinel string instead of "")
- {"subject": "Quick Question"}        (banned generic subject)
- {"contact_name": "...", "extra": 1}  (extra key not in schema)
- {"subject": "..."}                   (missing required keys)

### Process

1. Read the Campaign Voice Profile at the top -- it overrides any conflicting \
default in this prompt.
2. Read the Contact Context for personalization material.
3. Identify any timeline events (launches, hires, funding, talks, deadlines).
4. Pick the single strongest, most specific hook -- prefer timeline events.
5. Mirror the prospect's own language when connecting to an outcome.
6. Close with an interest question that includes a contextual detail.
7. Verify 3 distinct personalization points are present and traceable.
8. Verify the body uses NONE of the campaign-specific banned phrases AND \
NONE of the standard ban list.
9. Count words -- must be 75-100 in the body (excluding greeting and sign-off).
10. Verify subject is 2-4 words, under 40 characters, no exclamation marks.
11. Output ONLY the JSON object.
"""

GENERATE_EMAIL = build_system_prompt(
    resolve("email_generate_outreach", _DEFAULT_GENERATE_EMAIL)
)
