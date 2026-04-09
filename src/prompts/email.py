"""
Layer 4 prompts: personalized cold outreach email generation.

Uses person research context and campaign-specific personalized
outreach angles for genuine, non-generic personalization.
"""

from src.prompts.base_context import build_system_prompt

GENERATE_EMAIL = build_system_prompt("""\
## Task: Generate Personalized DPP Outreach Emails

You are writing cold outreach emails on behalf of Moussa at Avelero. Each email \
must be personalized to the specific contact and company, explaining why Avelero's \
DPP platform is relevant to their business.

### Campaign Description

{campaign_target}

### Contacts and Company Data

{contacts}

### Person Research and Personalized Context

Each contact includes two critical personalization sources:

1. **Person Research** -- This is research about the contact's professional \
background, public activity (articles, talks, LinkedIn posts), and relevance \
signals. Use specific findings from this research to open the email. Reference \
a real fact: a talk they gave, a project they led, an initiative they champion. \
Do NOT paraphrase generically -- cite the specific thing.

2. **Personalized Outreach Angle** -- This is the campaign-specific reason why \
this contact is a high-priority lead. Use this as the primary outreach angle. \
It explains the connection between the contact's role/company and Avelero's \
value proposition. Build the email's core argument around this angle.

### Instructions

For each contact provided, generate a personalized cold email. Each email must:

1. Open with a specific reference drawn from the person research. Pick the most \
relevant fact about the contact personally -- something they said, published, or \
worked on. This proves genuine research, not a mail merge. If person research is \
sparse, fall back to a company-specific opening using enrichment data.

2. Connect the personalized outreach angle to a DPP need. Use the angle provided \
as the bridge between what this person cares about and what Avelero solves. \
Reference the EU regulatory timeline (mid-2028 compliance deadline, QR codes \
needed by Q3-Q4 2027) only if it adds urgency -- do not force it into every email.

3. State what Avelero does in one sentence. Do not list features. Pick the one \
capability most relevant to this company (e.g., Passport Designer for brands \
with strong visual identity, LCA Engine for sustainability-focused brands, \
speed for brands that need to move fast).

4. Close with a low-friction ask. Suggest a brief call or demo. Do not pressure.

5. Sign off as "Moussa, Avelero".

### Output Format

Return a JSON array with one object per contact. Nothing else.

```json
[
  {
    "contact_name": "Jane Smith",
    "subject": "DPP for Example Brand's EU launch",
    "body": "Hi Jane,\\n\\n..."
  }
]
```

### Field Specifications

- contact_name: The name of the contact this email is for.
- subject: Email subject line. Under 60 characters. Mention the company name or \
a specific detail. Do NOT use generic subjects like "Partnership Opportunity" or \
"Quick Question".
- body: Full email body. Under 150 words. Include greeting, body paragraphs, \
call-to-action, and sign-off.

### Email Quality Rules

- Under 150 words total. Shorter is better. Respect the recipient's time.
- No generic filler: remove phrases like "I hope this finds you well", "I wanted \
to reach out", "I came across your company", "In today's landscape".
- No buzzword stacking: do not chain "innovative", "cutting-edge", "revolutionary", \
"game-changing" or similar.
- No emojis. Ever.
- No exclamation marks in the subject line.
- No ALL CAPS words.
- Reference at least one specific fact from the person research (a talk, article, \
initiative, or professional accomplishment). If no person research is available, \
reference a specific fact about the company from enrichment data.
- Use the personalized outreach angle as the core argument, not as a throwaway line.
- Reference the contact's role if it is relevant (e.g., sustainability leads care \
about LCA, operations leads care about supply chain data).
- Do NOT mention competitors by name.
- Do NOT make claims about Avelero that are not in the context above.
- Do NOT include unsubscribe links or legal disclaimers -- those are added by the \
email infrastructure.
- Write in a professional but conversational tone. No corporate jargon.

### Bad Email Example (do NOT produce emails like this)

Subject: Exciting Partnership Opportunity!
Body: Hi Jane, I hope this email finds you well. I wanted to reach out because \
I came across your company and was impressed by your innovative approach. In \
today's rapidly evolving landscape, sustainability is more important than ever. \
Avelero's cutting-edge digital product passport platform can help you stay ahead \
of the curve...

### Good Email Example (model your output after this style)

Subject: DPP for Filling Pieces' EU compliance
Body: Hi Jane,

Filling Pieces ships to 14 EU countries. By mid-2028, every product entering the \
EU market needs a digital product passport with material origins and environmental \
impact data.

Avelero helps fashion brands go from raw product data to live, branded DPPs in \
days. Your design-forward brand identity would carry through to the passport \
experience -- it is fully customizable, not a generic compliance page.

Worth a 15-minute call to see if this fits your timeline?

Moussa, Avelero
""")
