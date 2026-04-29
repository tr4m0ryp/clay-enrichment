// Service-layer wrappers that mirror src/campaign_brief/service.py:
//   generateCampaignBrief(name, target_description, sample_emails)
//   regenerateSampleEmail(name, target_description, prior_brief, user_feedback)
//
// Both run one Gemini grounded + JSON-mode call, validate the result against
// the five-key schema, and return a fully-populated CampaignBrief or throw.
// On the regenerate path the locked fields (icp_brief, voice_profile,
// banned_phrases) are force-preserved from the prior brief in case the model
// drifted -- identical behaviour to the Python service.

import type { CampaignBrief } from "@/lib/types/campaign";
import { generateGroundedJson, GeminiBriefError } from "./gemini";
import {
  GENERATE_BRIEF_PROMPT,
  REGENERATE_SAMPLE_PROMPT,
  fillTemplate,
} from "./prompts";

const REQUIRED_KEYS: ReadonlyArray<keyof CampaignBrief> = [
  "icp_brief",
  "voice_profile",
  "banned_phrases",
  "sample_email_subject",
  "sample_email_body",
];

const TARGET_PREVIEW = 500;
const FEEDBACK_PREVIEW = 1000;

// Validate the parsed object has every required key. Empty values are fine
// (per F16 the prompt forces empty-string / empty-list fallbacks); only
// missing keys are a hard failure.
function validateBrief(parsed: unknown): parsed is CampaignBrief {
  if (!parsed || typeof parsed !== "object") return false;
  const obj = parsed as Record<string, unknown>;
  for (const key of REQUIRED_KEYS) {
    if (!(key in obj)) return false;
  }
  if (!Array.isArray(obj.banned_phrases)) return false;
  if (typeof obj.icp_brief !== "string") return false;
  if (typeof obj.voice_profile !== "string") return false;
  if (typeof obj.sample_email_subject !== "string") return false;
  if (typeof obj.sample_email_body !== "string") return false;
  return true;
}

// Coerce a possibly-loose array of unknown values into string[]; non-string
// entries are dropped. Used to harden banned_phrases against model drift.
function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((x): x is string => typeof x === "string");
}

export async function generateCampaignBrief(
  name: string,
  targetDescription: string,
  sampleEmails: string[] = [],
): Promise<CampaignBrief> {
  if (!targetDescription) {
    throw new GeminiBriefError(
      "target_description is required to generate a campaign brief",
    );
  }
  const samplesStr = sampleEmails.length
    ? sampleEmails.filter(Boolean).join("\n---\n")
    : "";

  const prompt = fillTemplate(GENERATE_BRIEF_PROMPT, {
    campaign_name: name || "",
    target_description: targetDescription,
    sample_emails: samplesStr,
  });
  const userMessage =
    `Generate the campaign brief for: ${name || "(unnamed campaign)"}\n` +
    `Target: ${targetDescription.slice(0, TARGET_PREVIEW)}`;

  const result = await generateGroundedJson<unknown>({
    systemPrompt: prompt,
    userMessage,
  });
  if (!validateBrief(result)) {
    throw new GeminiBriefError(
      "Gemini output missing required brief keys",
    );
  }
  return {
    icp_brief: result.icp_brief,
    voice_profile: result.voice_profile,
    banned_phrases: toStringArray(result.banned_phrases),
    sample_email_subject: result.sample_email_subject,
    sample_email_body: result.sample_email_body,
  };
}

export async function regenerateSampleEmail(
  name: string,
  targetDescription: string,
  priorBrief: CampaignBrief,
  userFeedback: string,
): Promise<CampaignBrief> {
  if (!userFeedback) {
    throw new GeminiBriefError("user_feedback is required to regenerate");
  }
  if (!priorBrief || typeof priorBrief !== "object") {
    throw new GeminiBriefError("prior_brief is required to regenerate");
  }

  const prompt = fillTemplate(REGENERATE_SAMPLE_PROMPT, {
    campaign_name: name || "",
    target_description: targetDescription || "",
    prior_voice_profile: priorBrief.voice_profile || "",
    prior_banned_phrases: priorBrief.banned_phrases || [],
    prior_sample_subject: priorBrief.sample_email_subject || "",
    prior_sample_body: priorBrief.sample_email_body || "",
    user_feedback: userFeedback.slice(0, FEEDBACK_PREVIEW),
  });
  const userMessage =
    `Regenerate the sample email for: ${name || "(unnamed campaign)"}\n` +
    `User feedback: ${userFeedback.slice(0, TARGET_PREVIEW)}`;

  const result = await generateGroundedJson<unknown>({
    systemPrompt: prompt,
    userMessage,
  });
  if (!validateBrief(result)) {
    throw new GeminiBriefError(
      "Gemini output missing required brief keys",
    );
  }

  // Force-preserve the locked fields from prior_brief regardless of any
  // model drift on the regenerate path (identical to the Python service).
  return {
    icp_brief: priorBrief.icp_brief,
    voice_profile: priorBrief.voice_profile,
    banned_phrases: priorBrief.banned_phrases,
    sample_email_subject: result.sample_email_subject,
    sample_email_body: result.sample_email_body,
  };
}

export { GeminiBriefError };
