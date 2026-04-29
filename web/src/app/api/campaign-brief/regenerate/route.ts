import { NextResponse } from "next/server";
import type { CampaignBrief } from "@/lib/types/campaign";
import {
  regenerateSampleEmail,
  GeminiBriefError,
} from "@/lib/campaign-brief/service";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface RegenerateBody {
  name?: unknown;
  target_description?: unknown;
  prior_brief?: unknown;
  user_feedback?: unknown;
}

const NAME_MAX = 100;
const TARGET_MAX = 5000;
const FEEDBACK_MAX = 5000;

// Validate the incoming prior_brief blob so we don't pass garbage straight
// into the prompt template. Tolerant: every field defaults to an empty
// string / list when absent, since the user could (theoretically) hit this
// route with a partial brief, but the locked fields are still re-asserted
// downstream.
function coerceBrief(input: unknown): CampaignBrief | null {
  if (!input || typeof input !== "object") return null;
  const obj = input as Record<string, unknown>;
  const phrases = Array.isArray(obj.banned_phrases)
    ? (obj.banned_phrases.filter((x) => typeof x === "string") as string[])
    : [];
  return {
    icp_brief: typeof obj.icp_brief === "string" ? obj.icp_brief : "",
    voice_profile:
      typeof obj.voice_profile === "string" ? obj.voice_profile : "",
    banned_phrases: phrases,
    sample_email_subject:
      typeof obj.sample_email_subject === "string"
        ? obj.sample_email_subject
        : "",
    sample_email_body:
      typeof obj.sample_email_body === "string"
        ? obj.sample_email_body
        : "",
  };
}

export async function POST(request: Request) {
  let body: RegenerateBody;
  try {
    body = (await request.json()) as RegenerateBody;
  } catch {
    return NextResponse.json(
      { error: "Invalid JSON body" },
      { status: 400 },
    );
  }

  const name = typeof body.name === "string" ? body.name.trim() : "";
  const target =
    typeof body.target_description === "string"
      ? body.target_description.trim()
      : "";
  const feedback =
    typeof body.user_feedback === "string"
      ? body.user_feedback.trim()
      : "";

  if (!name || name.length > NAME_MAX) {
    return NextResponse.json(
      { error: `name is required and max ${NAME_MAX} chars` },
      { status: 400 },
    );
  }
  if (target.length > TARGET_MAX) {
    return NextResponse.json(
      { error: `target_description is max ${TARGET_MAX} chars` },
      { status: 400 },
    );
  }
  if (!feedback || feedback.length > FEEDBACK_MAX) {
    return NextResponse.json(
      { error: `user_feedback is required and max ${FEEDBACK_MAX} chars` },
      { status: 400 },
    );
  }

  const prior = coerceBrief(body.prior_brief);
  if (!prior) {
    return NextResponse.json(
      { error: "prior_brief object is required" },
      { status: 400 },
    );
  }

  try {
    const brief = await regenerateSampleEmail(name, target, prior, feedback);
    return NextResponse.json({ brief });
  } catch (err) {
    const message =
      err instanceof GeminiBriefError
        ? err.message
        : (err as Error).message || "Regenerate failed";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
