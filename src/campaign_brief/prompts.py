"""Prompts for the campaign brief feature.

Two strings, both rendered with ``.replace("{...}", value)`` by the
service module:

- ``GENERATE_BRIEF`` -- produces the full brief on Next-button click.
- ``REGENERATE_SAMPLE`` -- updates only the sample email when the user
  edits and clicks Regenerate; the locked icp_brief / voice_profile /
  banned_phrases are echoed back unchanged.

Both prompts follow the Strict Prompt Template (F16) verbatim:
explicit JSON schema in-prompt, field-by-field rules, type-appropriate
empty values, hard "Output ONLY JSON" rules, and good/bad output
examples. Output schema is invariant across served-model tiers
(Gemini 3 Pro -> 2.5 Pro -> 2.5 Flash) so the caller's parser stays
fixed.
"""

from __future__ import annotations

from src.prompts.base_context import build_system_prompt
from src.prompts.runtime import resolve


_DEFAULT_GENERATE_BRIEF = """\
## Task
Research the cold-email style and ideal customer profile that would \
resonate for the campaign described below. Output a structured campaign \
brief with an ICP definition, voice profile, banned phrases, and one \
sample cold email demonstrating the voice.

## Inputs
- {campaign_name}: short campaign name string (e.g. "Q3 EU Streetwear").
- {target_description}: free-text description of who the campaign \
targets (industry, segment, geography, decision-makers, signals).
- {sample_emails}: optional concatenated string of 1-3 example cold \
emails the user likes, separated by the literal divider "\\n---\\n". \
Empty string when the user provided none.

Inputs as filled by the caller follow this paragraph:

- campaign_name: {campaign_name}
- target_description: {target_description}
- sample_emails: {sample_emails}

## Output Format -- EXACT
Return ONLY a valid JSON object matching this schema. No markdown \
fences. No prose before or after. No commentary. The object MUST \
contain exactly these five keys, in any order, and no additional keys.

{
  "icp_brief": "string -- enriched ICP description, max 1500 chars. Sharper version of target_description with industry, geography, size, signals.",
  "voice_profile": "string -- voice/tone description for cold-email copy: vocabulary, cadence, dos and donts. Max 1500 chars.",
  "banned_phrases": ["string"],
  "sample_email_subject": "string -- 2-4 words, max 40 chars, no exclamation marks, no recipient name",
  "sample_email_body": "string -- 75-100 word body following the campaign's voice profile. Greeting + 3 parts (personal hook, value bridge, CTA) + sign-off."
}

### Field-by-field rules
- icp_brief: must add specificity beyond target_description. Include \
company size band, geographic clusters, decision-maker titles, and \
intent signals to look for. Max 1500 chars. Use empty string "" only \
if target_description was itself empty. NEVER write "Unknown", "N/A", \
"TBD", or any sentinel.
- voice_profile: structured "We always.../We never.../When X, do Y" \
guidance. Reference the sample_emails (if provided) for tone \
calibration; otherwise default to direct, problem-focused, no-fluff \
B2B voice. Max 1500 chars. Use empty string "" if not determinable.
- banned_phrases: 5 to 15 phrases the email-gen step MUST avoid. \
Include corporate filler ("I hope this finds you well"), buzzwords \
("innovative", "cutting-edge", "synergy"), and anything that \
contradicts the voice_profile. Use empty list [] when no specific \
bans are warranted.
- sample_email_subject: 2 to 4 words, max 40 characters. NEVER use \
the recipient's first name. NEVER use exclamation marks. NEVER use \
emojis. Use empty string "" only if the body itself is empty.
- sample_email_body: 75 to 100 words. Demonstrates the voice. Greeting \
+ personal hook + value bridge + CTA + sign-off. Use placeholder \
tokens like "[FirstName]", "[Company]", "[Recent event]" for \
recipient-specific references -- NEVER invent specific people, \
companies, or events. Sign off as "Moussa".

## Process
1. Use grounded search to research cold-email norms in the campaign's \
vertical (e.g. EU sustainable fashion outreach, B2B SaaS to mid-market, \
streetwear DTC, etc.). Identify what tone, length, and angle works.
2. Synthesize an icp_brief that goes beyond the user's \
target_description -- add company size, geography, titles, signals.
3. Calibrate the voice_profile from the sample_emails the user \
provided. If none were provided, default to direct, problem-focused, \
no-fluff B2B copy with short paragraphs and one clear CTA.
4. Pick 5 to 15 banned_phrases the email gen must avoid -- corporate \
filler and buzzwords plus anything that contradicts the voice profile.
5. Draft one sample_email_subject (2-4 words, max 40 chars) and one \
sample_email_body (75-100 words) demonstrating the voice using \
placeholder tokens for recipient-specific facts.

## Hard Rules
- Output is JSON ONLY. No prose. No markdown fences. No commentary.
- Empty values: "" for strings, [] for lists. Never use "Unknown", \
"N/A", "TBD", "None", or any other sentinel string.
- Never fabricate company-specific facts, named individuals, or recent \
events in the sample. Use [FirstName], [Company], [Recent event] \
placeholders if you need recipient-specific tokens.
- Never use emojis anywhere in the output.
- Never include keys not in the schema. Never omit keys. Exactly five \
keys: icp_brief, voice_profile, banned_phrases, sample_email_subject, \
sample_email_body.

## Output Examples
### Good output (abridged)
{"icp_brief": "Mid-market EU sustainable fashion brands (50-300 employees, HQ in DK/NL/DE/SE), B-Corp or similar certification, DTC + wholesale, currently scaling sustainability reporting -- decision makers are Heads of Sustainability, COOs, founders.", "voice_profile": "We always lead with a recipient-specific observation. We never pitch the product in the first email. We mirror the prospect's own language. We use short paragraphs and one clear CTA. We never say 'I hope this finds you well' or 'innovative'.", "banned_phrases": ["I hope this finds you well", "innovative", "cutting-edge", "revolutionary", "synergy", "leverage"], "sample_email_subject": "ESPR readiness", "sample_email_body": "Hi [FirstName], saw your team launched the Spring circular collection last month -- the take-back program signals you've already mapped your supply chain. Most brands at your size find that mapping is 80% of the DPP work; the remaining 20% is brand-level customization, which is where teams hit a wall. Worth comparing notes? Moussa"}

### Bad outputs (do NOT do these)
- {"icp_brief": "Unknown", "voice_profile": "...", ...}        (sentinel string instead of "")
- {"icp_brief": "...", "voice_profile": "...", "extra_thing": "..."}  (extra key)
- "Here is the campaign brief: {...}"                          (prose before)
- "```json\\n{...}\\n```"                                       (markdown fence)
"""

GENERATE_BRIEF = build_system_prompt(
    resolve("campaign_brief_generate", _DEFAULT_GENERATE_BRIEF)
)


_DEFAULT_REGENERATE_SAMPLE = """\
## Task
Regenerate the sample cold email for this campaign incorporating the \
user's feedback. Keep the campaign's icp_brief, voice_profile, and \
banned_phrases unchanged -- the user only edited the sample, not the \
voice. Output a full five-key brief object so the caller's persistence \
path stays uniform.

## Inputs
- {campaign_name}: short campaign name string.
- {target_description}: free-text campaign target description.
- {prior_voice_profile}: the locked voice profile -- echo back \
unchanged in the voice_profile output field.
- {prior_banned_phrases}: the locked banned phrases JSON list rendered \
as a string -- echo back unchanged in banned_phrases output, and \
ensure the new sample_email_body avoids every entry.
- {prior_sample_subject}: the previous sample_email_subject draft.
- {prior_sample_body}: the previous sample_email_body draft.
- {user_feedback}: free-text user feedback (e.g. "Make it shorter", \
"More direct", "Don't mention compliance", "Lead with the metric").

Inputs as filled by the caller follow this paragraph:

- campaign_name: {campaign_name}
- target_description: {target_description}
- prior_voice_profile: {prior_voice_profile}
- prior_banned_phrases: {prior_banned_phrases}
- prior_sample_subject: {prior_sample_subject}
- prior_sample_body: {prior_sample_body}
- user_feedback: {user_feedback}

## Output Format -- EXACT
Return ONLY a valid JSON object matching this schema. No markdown \
fences. No prose before or after. The object MUST contain exactly \
these five keys and no additional keys.

{
  "icp_brief": "string -- echo back the campaign's existing icp_brief unchanged",
  "voice_profile": "string -- echo back the prior_voice_profile unchanged",
  "banned_phrases": ["string"],
  "sample_email_subject": "string -- updated per user feedback, 2-4 words, max 40 chars, no exclamation marks, no recipient name",
  "sample_email_body": "string -- updated per user feedback, 75-100 words, follows voice_profile, avoids every banned phrase"
}

### Field-by-field rules
- icp_brief: echo back the campaign's existing icp_brief value \
unchanged. The caller will overwrite this field anyway, but you MUST \
emit a non-empty string here when one exists. Use "" only when the \
caller passed no prior icp_brief.
- voice_profile: echo back prior_voice_profile verbatim. Do NOT \
rewrite, summarize, or "improve" it. The user only edited the sample.
- banned_phrases: echo back prior_banned_phrases verbatim as a JSON \
list of strings. Do NOT add or remove entries. Use empty list [] only \
when prior_banned_phrases was itself empty.
- sample_email_subject: 2 to 4 words, max 40 characters. NEVER use \
the recipient's first name. NEVER use exclamation marks. NEVER use \
emojis. Apply the user_feedback to update the subject when relevant.
- sample_email_body: 75 to 100 words. Apply the user_feedback. Must \
follow voice_profile. Must avoid every entry in banned_phrases. Use \
placeholder tokens like "[FirstName]", "[Company]", "[Recent event]" \
for recipient-specific references -- NEVER invent specific people, \
companies, or events. Sign off as "Moussa".

## Process
1. Use grounded search if needed to incorporate any vertical-specific \
detail the user_feedback hints at (e.g. "Reference the new ESPR draft").
2. Apply the user_feedback to the prior_sample_subject and \
prior_sample_body. Tighten, restructure, or change angle per the \
feedback.
3. Verify the new sample_email_body still follows the voice_profile \
and avoids every phrase in banned_phrases.
4. Echo icp_brief, voice_profile, and banned_phrases back unchanged.

## Hard Rules
- Output is JSON ONLY. No prose. No markdown fences. No commentary.
- Empty values: "" for strings, [] for lists. Never use "Unknown", \
"N/A", "TBD", "None", or any other sentinel string.
- Never modify icp_brief, voice_profile, or banned_phrases. Echo them \
back as received. The caller force-preserves these fields after parse, \
so any drift you introduce will be discarded -- emit them faithfully \
to keep the round trip clean.
- Never fabricate company-specific facts, named individuals, or recent \
events in the sample. Use [FirstName], [Company], [Recent event] \
placeholders.
- Never use emojis anywhere in the output.
- Never include keys not in the schema. Never omit keys. Exactly five \
keys: icp_brief, voice_profile, banned_phrases, sample_email_subject, \
sample_email_body.

## Output Examples
### Good output (abridged, after user_feedback="make it shorter, lead with the metric")
{"icp_brief": "Mid-market EU sustainable fashion brands (50-300 employees, HQ in DK/NL/DE/SE)...", "voice_profile": "We always lead with a recipient-specific observation. We never pitch the product in the first email...", "banned_phrases": ["I hope this finds you well", "innovative", "cutting-edge"], "sample_email_subject": "80/20 on DPP", "sample_email_body": "Hi [FirstName], 80% of the DPP lift is supply-chain mapping; your Spring take-back program suggests you've done that. The other 20% is brand-level customization, which is where most teams stall. Worth comparing notes? Moussa"}

### Bad outputs (do NOT do these)
- {"icp_brief": "(rewritten)", ...}                            (modified locked field)
- {"voice_profile": "Updated voice based on feedback", ...}    (modified locked field)
- {"banned_phrases": [], ...} when prior had entries           (silently dropped locked list)
- "Here is the regenerated sample: {...}"                      (prose before)
- "```json\\n{...}\\n```"                                       (markdown fence)
"""

REGENERATE_SAMPLE = build_system_prompt(
    resolve("campaign_brief_regenerate_sample", _DEFAULT_REGENERATE_SAMPLE)
)
