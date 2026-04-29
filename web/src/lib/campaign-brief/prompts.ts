// Strict-template prompts for the campaign-brief Gemini calls. TS port of
// src/campaign_brief/prompts.py (Python) so the web layer does not reach into
// the Python source tree. Output schema is invariant across served-model
// tiers per F16 in research/campaign_creation_redesign.md.
//
// Two template strings, both rendered via fillTemplate() before calling
// Gemini. The placeholders are simple {token} substitutions identical to the
// Python implementation.

const AVELERO_CONTEXT = `## Avelero -- Company Context

Avelero is a fashion-tech SaaS company providing a digital product passport (DPP) platform built for fashion, streetwear, and lifestyle brands. Founded by Rafael Mevis, headquartered in Europe. Website: https://www.avelero.com

### What Is a Digital Product Passport (DPP)?

A DPP is a product-level digital record containing material origins, environmental impact data, care instructions, and end-of-life options (repair, resale, recycling). Consumers access passports by scanning a QR code on the product label or packaging. The EU Ecodesign for Sustainable Products Regulation (ESPR) mandates DPPs for all textile products entering the EU market by mid-2028.

### Avelero Platform Capabilities

- Passport Designer: Fully customizable templates (typography, colors, layouts). Embeds care guides, repair services, resale options, brand storytelling, newsletter signups, and campaign banners. On-brand experience, not generic compliance pages.
- LCA Engine: ML-powered lifecycle assessment using ISO 14040/14044 methodology. Estimates carbon and water impact from minimal input. No environmental science background required.
- Data Integration: Accepts Excel, PDF, direct uploads. API connections to Shopify, PLM, and ERP systems. AI-powered data gap detection and auto-completion.
- GS1 Digital Link Standard: QR codes follow the GS1 Digital Link structure, avoiding vendor lock-in. A single QR code serves both consumer passport access and POS scanning.

### Value Proposition (Three Pillars)

1. Speed: Most brands go from raw data to live passports in days, not months.
2. Post-Purchase Engagement: Passports embed care guides, repair services, and resale options that keep customers returning after purchase -- a revenue and retention channel.
3. Regulatory Readiness: Built around EU ESPR compliance. Built-in LCA engine eliminates separate environmental assessment subscriptions.

### Target Market

Mid-market fashion, streetwear, and lifestyle brands that:
- Sell physical products (apparel, footwear, accessories) in the EU market
- Have 20-500 employees
- Face upcoming EU DPP compliance deadlines (mandatory mid-2028)
- Value speed of implementation over enterprise customization
- Care about brand experience and post-purchase customer engagement

### Outreach Identity

All outreach is sent by Moussa on behalf of Avelero. Sign-off: "Moussa, Avelero"
`;

const GENERATE_BODY = `## Task
Research the cold-email style and ideal customer profile that would resonate for the campaign described below. Output a structured campaign brief with an ICP definition, voice profile, banned phrases, and one sample cold email demonstrating the voice.

## Inputs
- {campaign_name}: short campaign name string (e.g. "Q3 EU Streetwear").
- {target_description}: free-text description of who the campaign targets (industry, segment, geography, decision-makers, signals).
- {sample_emails}: optional concatenated string of 1-3 example cold emails the user likes, separated by the literal divider "\\n---\\n". Empty string when the user provided none.

Inputs as filled by the caller follow this paragraph:

- campaign_name: {campaign_name}
- target_description: {target_description}
- sample_emails: {sample_emails}

## Output Format -- EXACT
Return ONLY a valid JSON object matching this schema. No markdown fences. No prose before or after. No commentary. The object MUST contain exactly these five keys, in any order, and no additional keys.

{
  "icp_brief": "string -- enriched ICP description, max 1500 chars. Sharper version of target_description with industry, geography, size, signals.",
  "voice_profile": "string -- voice/tone description for cold-email copy: vocabulary, cadence, dos and donts. Max 1500 chars.",
  "banned_phrases": ["string"],
  "sample_email_subject": "string -- 2-4 words, max 40 chars, no exclamation marks, no recipient name",
  "sample_email_body": "string -- 75-100 word body following the campaign's voice profile. Greeting + 3 parts (personal hook, value bridge, CTA) + sign-off."
}

### Field-by-field rules
- icp_brief: must add specificity beyond target_description. Include company size band, geographic clusters, decision-maker titles, and intent signals to look for. Max 1500 chars. Use empty string "" only if target_description was itself empty. NEVER write "Unknown", "N/A", "TBD", or any sentinel.
- voice_profile: structured "We always.../We never.../When X, do Y" guidance. Reference the sample_emails (if provided) for tone calibration; otherwise default to direct, problem-focused, no-fluff B2B voice. Max 1500 chars. Use empty string "" if not determinable.
- banned_phrases: 5 to 15 phrases the email-gen step MUST avoid. Include corporate filler ("I hope this finds you well"), buzzwords ("innovative", "cutting-edge", "synergy"), and anything that contradicts the voice_profile. Use empty list [] when no specific bans are warranted.
- sample_email_subject: 2 to 4 words, max 40 characters. NEVER use the recipient's first name. NEVER use exclamation marks. NEVER use emojis. Use empty string "" only if the body itself is empty.
- sample_email_body: 75 to 100 words. Demonstrates the voice. Greeting + personal hook + value bridge + CTA + sign-off. Use placeholder tokens like "[FirstName]", "[Company]", "[Recent event]" for recipient-specific references -- NEVER invent specific people, companies, or events. Sign off as "Moussa".

## Process
1. Use grounded search to research cold-email norms in the campaign's vertical. Identify what tone, length, and angle works.
2. Synthesize an icp_brief that goes beyond the user's target_description -- add company size, geography, titles, signals.
3. Calibrate the voice_profile from the sample_emails the user provided. If none were provided, default to direct, problem-focused, no-fluff B2B copy.
4. Pick 5 to 15 banned_phrases the email gen must avoid.
5. Draft one sample_email_subject (2-4 words, max 40 chars) and one sample_email_body (75-100 words) demonstrating the voice using placeholder tokens for recipient-specific facts.

## Hard Rules
- Output is JSON ONLY. No prose. No markdown fences. No commentary.
- Empty values: "" for strings, [] for lists. Never use "Unknown", "N/A", "TBD", "None", or any other sentinel string.
- Never fabricate company-specific facts, named individuals, or recent events in the sample. Use [FirstName], [Company], [Recent event] placeholders if you need recipient-specific tokens.
- Never use emojis anywhere in the output.
- Never include keys not in the schema. Never omit keys. Exactly five keys: icp_brief, voice_profile, banned_phrases, sample_email_subject, sample_email_body.
`;

const REGENERATE_BODY = `## Task
Regenerate the sample cold email for this campaign incorporating the user's feedback. Keep the campaign's icp_brief, voice_profile, and banned_phrases unchanged -- the user only edited the sample, not the voice. Output a full five-key brief object so the caller's persistence path stays uniform.

## Inputs
- {campaign_name}: short campaign name string.
- {target_description}: free-text campaign target description.
- {prior_voice_profile}: the locked voice profile -- echo back unchanged.
- {prior_banned_phrases}: the locked banned phrases JSON list rendered as a string -- echo back unchanged in banned_phrases output, and ensure the new sample_email_body avoids every entry.
- {prior_sample_subject}: the previous sample_email_subject draft.
- {prior_sample_body}: the previous sample_email_body draft.
- {user_feedback}: free-text user feedback.

Inputs as filled by the caller follow this paragraph:

- campaign_name: {campaign_name}
- target_description: {target_description}
- prior_voice_profile: {prior_voice_profile}
- prior_banned_phrases: {prior_banned_phrases}
- prior_sample_subject: {prior_sample_subject}
- prior_sample_body: {prior_sample_body}
- user_feedback: {user_feedback}

## Output Format -- EXACT
Return ONLY a valid JSON object matching this schema. No markdown fences. No prose before or after. The object MUST contain exactly these five keys and no additional keys.

{
  "icp_brief": "string -- echo back the campaign's existing icp_brief unchanged",
  "voice_profile": "string -- echo back the prior_voice_profile unchanged",
  "banned_phrases": ["string"],
  "sample_email_subject": "string -- updated per user feedback, 2-4 words, max 40 chars, no exclamation marks, no recipient name",
  "sample_email_body": "string -- updated per user feedback, 75-100 words, follows voice_profile, avoids every banned phrase"
}

### Field-by-field rules
- icp_brief: echo back the campaign's existing icp_brief value unchanged.
- voice_profile: echo back prior_voice_profile verbatim. Do NOT rewrite, summarize, or improve it.
- banned_phrases: echo back prior_banned_phrases verbatim as a JSON list of strings.
- sample_email_subject: 2 to 4 words, max 40 characters. NEVER use the recipient's first name. NEVER use exclamation marks. NEVER use emojis. Apply the user_feedback to update the subject when relevant.
- sample_email_body: 75 to 100 words. Apply the user_feedback. Must follow voice_profile. Must avoid every entry in banned_phrases. Use placeholder tokens like "[FirstName]", "[Company]", "[Recent event]" for recipient-specific references. Sign off as "Moussa".

## Process
1. Apply the user_feedback to the prior_sample_subject and prior_sample_body. Tighten, restructure, or change angle per the feedback.
2. Verify the new sample_email_body still follows the voice_profile and avoids every phrase in banned_phrases.
3. Echo icp_brief, voice_profile, and banned_phrases back unchanged.

## Hard Rules
- Output is JSON ONLY. No prose. No markdown fences. No commentary.
- Empty values: "" for strings, [] for lists.
- Never modify icp_brief, voice_profile, or banned_phrases. Echo them back as received.
- Never fabricate company-specific facts. Use [FirstName], [Company], [Recent event] placeholders.
- Never use emojis anywhere in the output.
- Never include keys not in the schema. Never omit keys.
`;

export const GENERATE_BRIEF_PROMPT = `${AVELERO_CONTEXT}\n---\n\n${GENERATE_BODY}`;
export const REGENERATE_SAMPLE_PROMPT = `${AVELERO_CONTEXT}\n---\n\n${REGENERATE_BODY}`;

// Render a prompt template with the provided values. The Python service
// uses .replace("{key}", value) per token; we mirror that here so the
// behaviour is identical. Values are coerced to strings -- arrays become
// JSON-stringified lists (matching how the Python code passes lists).
export function fillTemplate(
  template: string,
  values: Record<string, string | string[] | undefined | null>,
): string {
  let out = template;
  for (const [key, raw] of Object.entries(values)) {
    const stringValue =
      raw == null
        ? ""
        : Array.isArray(raw)
          ? JSON.stringify(raw)
          : raw;
    out = out.split(`{${key}}`).join(stringValue);
  }
  return out;
}
