import { NextResponse } from "next/server";
import {
  generateCampaignBrief,
  GeminiBriefError,
} from "@/lib/campaign-brief/service";

// Force the route onto the Node.js runtime: the Gemini call uses fetch with
// a 60-second timeout and we want a real Node lifecycle (not Edge / V8
// isolate) for that.
export const runtime = "nodejs";
// Each request runs a synchronous (3-10s) Gemini call -- never cache.
export const dynamic = "force-dynamic";

interface GenerateBody {
  name?: unknown;
  target_description?: unknown;
  sample_emails?: unknown;
}

const NAME_MAX = 100;
const TARGET_MAX = 5000;
const SAMPLE_MAX = 5000;

export async function POST(request: Request) {
  let body: GenerateBody;
  try {
    body = (await request.json()) as GenerateBody;
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

  if (!name || name.length > NAME_MAX) {
    return NextResponse.json(
      { error: `name is required and max ${NAME_MAX} chars` },
      { status: 400 },
    );
  }
  if (!target || target.length > TARGET_MAX) {
    return NextResponse.json(
      {
        error: `target_description is required and max ${TARGET_MAX} chars`,
      },
      { status: 400 },
    );
  }

  // sample_emails is optional, max 3 entries, each capped at SAMPLE_MAX.
  const rawSamples = Array.isArray(body.sample_emails)
    ? body.sample_emails
    : [];
  const samples: string[] = [];
  for (const item of rawSamples) {
    if (typeof item !== "string") continue;
    const trimmed = item.trim();
    if (!trimmed) continue;
    if (trimmed.length > SAMPLE_MAX) {
      return NextResponse.json(
        { error: `sample_email entries are max ${SAMPLE_MAX} chars` },
        { status: 400 },
      );
    }
    samples.push(trimmed);
    if (samples.length >= 3) break;
  }

  try {
    const brief = await generateCampaignBrief(name, target, samples);
    return NextResponse.json({ brief });
  } catch (err) {
    const message =
      err instanceof GeminiBriefError
        ? err.message
        : (err as Error).message || "Brief generation failed";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
