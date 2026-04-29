// Thin HTTP client that proxies to the Python FastAPI service at
// 127.0.0.1:5001. The Python service routes Gemini calls through the
// api_keys pool (key rotation, tier descent, circuit breaker) -- the
// same chokepoint pipeline workers use.
//
// Used by /api/campaign-brief/generate and /regenerate routes only.

import type { CampaignBrief } from "@/lib/types/campaign";

const BRIEF_BASE =
  process.env.CLAY_BRIEF_BASE_URL || "http://127.0.0.1:5001";
const HTTP_TIMEOUT_MS = 90_000;

const REQUIRED_KEYS: ReadonlyArray<keyof CampaignBrief> = [
  "icp_brief",
  "voice_profile",
  "banned_phrases",
  "sample_email_subject",
  "sample_email_body",
];

export class GeminiBriefError extends Error {}

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

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((x): x is string => typeof x === "string");
}

async function callBriefService<T>(
  path: string,
  payload: unknown,
): Promise<T> {
  const ctrl = new AbortController();
  const timeout = setTimeout(() => ctrl.abort(), HTTP_TIMEOUT_MS);
  let resp: Response;
  try {
    resp = await fetch(`${BRIEF_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: ctrl.signal,
    });
  } catch (err) {
    throw new GeminiBriefError(
      `Brief service unreachable: ${(err as Error).message}`,
    );
  } finally {
    clearTimeout(timeout);
  }

  const text = await resp.text();
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new GeminiBriefError(
      `Brief service returned non-JSON: ${text.slice(0, 200)}`,
    );
  }
  if (!resp.ok) {
    const detail =
      (parsed as { detail?: unknown })?.detail ?? text.slice(0, 200);
    throw new GeminiBriefError(
      `Brief service ${resp.status}: ${
        typeof detail === "string" ? detail : JSON.stringify(detail)
      }`,
    );
  }
  return parsed as T;
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
  const result = await callBriefService<unknown>(
    "/campaign-brief/generate",
    {
      name: name || "",
      target_description: targetDescription,
      sample_emails: sampleEmails.filter(Boolean),
    },
  );
  if (!validateBrief(result)) {
    throw new GeminiBriefError(
      "Brief service response missing required keys",
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
  const result = await callBriefService<unknown>(
    "/campaign-brief/regenerate",
    {
      name: name || "",
      target_description: targetDescription || "",
      prior_brief: priorBrief,
      user_feedback: userFeedback,
    },
  );
  if (!validateBrief(result)) {
    throw new GeminiBriefError(
      "Brief service response missing required keys",
    );
  }
  // Force-preserve the locked fields client-side as a safety net
  // (Python service already does this, but a second guard is cheap).
  return {
    icp_brief: priorBrief.icp_brief,
    voice_profile: priorBrief.voice_profile,
    banned_phrases: priorBrief.banned_phrases,
    sample_email_subject: result.sample_email_subject,
    sample_email_body: result.sample_email_body,
  };
}
