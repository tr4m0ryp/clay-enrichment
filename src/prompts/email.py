"""
Layer 4 prompts: personalized cold outreach email generation.

Strict 50-125 word, 3-part cold email structure: personal hook from
Contact Context, value bridge tied to campaign target, low-friction
question CTA.
"""

from src.prompts.base_context import build_system_prompt

GENERATE_EMAIL = build_system_prompt("""\
## Task: Generate a Personalized Cold Outreach Email

You are writing a single cold email on behalf of Moussa at Avelero. The email \
must follow the exact 3-part structure below. No deviations.

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
- Drawn from the Contact Context above. Pick the strongest signal: a product \
launch, LinkedIn post, hiring surge, funding round, conference talk, published \
article, or strategic initiative.
- The first sentence must be entirely about the recipient. Never mention Avelero \
in this part.
- NO generic compliments. "Love what you're doing" is banned unless followed by \
a concrete, cited detail. If the Context is thin, reference a specific company \
fact instead.

**Part 2 -- Value Bridge (1-2 sentences):**
- Connect their situation to an outcome Avelero delivers.
- Frame as what happens for THEM, not what Avelero does.
- Driven by the campaign target description.
- No feature lists. No bullet points. One clear outcome statement.
- Reference the EU regulatory timeline (mid-2028 DPP mandate) ONLY if it adds \
genuine urgency to this specific contact. Do not force it.

**Part 3 -- Low-Friction CTA (1 sentence):**
- A single interest-based question.
- Style: "Is this relevant to where you're focused right now?" or \
"Worth exploring, or not a priority yet?"
- NO Calendly links. NO scheduling links of any kind.
- NO "Got 30 minutes?" or "Can we hop on a call?"

### Subject Line Rules

- 1-5 words only, under 50 characters total.
- Reference a pain point or objective relevant to the recipient.
- Do NOT use the recipient's first name in the subject.
- No exclamation marks. No ALL CAPS words.
- No generic subjects like "Partnership Opportunity" or "Quick Question".

### Hard Constraints

- Minimum 50 words, maximum 125 words (body only, excluding greeting and sign-off).
- Maximum 7 lines of visible text in the body.
- No feature lists or bullet points anywhere in the email.
- No Calendly or scheduling links.
- No emojis. Ever.
- No corporate filler: ban "I hope this finds you well", "I wanted to reach out", \
"I came across your company", "In today's landscape", "innovative", "cutting-edge", \
"revolutionary", "game-changing".
- No ALL CAPS words.
- First sentence must be about the recipient, never about Avelero.
- Do NOT mention competitors by name.
- Do NOT make claims about Avelero not supported by the company context above.
- Do NOT include unsubscribe links or legal disclaimers.
- Sign off as just "Moussa" (no last name, casual tone).
- Greeting: "Hi {contact_name}," on its own line.

### Output Format

Return a single JSON object. Nothing else -- no markdown fences, no commentary.

```json
{{
  "contact_name": "{contact_name}",
  "subject": "short subject here",
  "body": "Hi {contact_name},\\n\\n[Part 1]\\n\\n[Part 2]\\n\\n[Part 3]\\n\\nMoussa"
}}
```

### Process

1. Read the Contact Context for personalization material.
2. Pick the single strongest, most specific hook.
3. Connect it to an outcome relevant to the campaign target.
4. Close with an interest question.
5. Count words -- must be 50-125 in the body (excluding greeting and sign-off).
6. Verify subject is 1-5 words, under 50 characters, no exclamation marks.
""")
