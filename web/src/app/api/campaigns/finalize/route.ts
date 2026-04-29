import { NextResponse } from "next/server";
import { revalidatePath } from "next/cache";
import { insertCampaignFull } from "@/lib/queries/campaigns";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface FinalizeBody {
  name?: unknown;
  target_description?: unknown;
  icp_brief?: unknown;
  voice_profile?: unknown;
  banned_phrases?: unknown;
  sample_email_subject?: unknown;
  sample_email_body?: unknown;
}

const NAME_MAX = 100;
const TARGET_MAX = 5000;
const ICP_MAX = 4000;
const VOICE_MAX = 4000;
const SUBJECT_MAX = 200;
const BODY_MAX = 4000;
const PHRASE_MAX = 200;
const PHRASE_LIST_MAX = 30;

function coerceString(value: unknown, max: number): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (trimmed.length > max) return null;
  return trimmed;
}

function coercePhrases(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  if (value.length > PHRASE_LIST_MAX) return null;
  const out: string[] = [];
  for (const item of value) {
    if (typeof item !== "string") return null;
    const trimmed = item.trim();
    if (!trimmed) continue;
    if (trimmed.length > PHRASE_MAX) return null;
    out.push(trimmed);
  }
  return out;
}

// POST: persist a fully-approved campaign brief to the campaigns table.
// Body shape: {name, target_description, icp_brief, voice_profile,
// banned_phrases, sample_email_subject, sample_email_body}. Returns
// {id} of the new row on success. The voice_profile is stored in the
// campaigns.email_style_profile column per schema/009.
export async function POST(request: Request) {
  let body: FinalizeBody;
  try {
    body = (await request.json()) as FinalizeBody;
  } catch {
    return NextResponse.json(
      { error: "Invalid JSON body" },
      { status: 400 },
    );
  }

  const name = coerceString(body.name, NAME_MAX);
  if (!name) {
    return NextResponse.json(
      { error: `name is required and max ${NAME_MAX} chars` },
      { status: 400 },
    );
  }
  const target = coerceString(body.target_description, TARGET_MAX);
  if (!target) {
    return NextResponse.json(
      {
        error: `target_description is required and max ${TARGET_MAX} chars`,
      },
      { status: 400 },
    );
  }
  const icp = coerceString(body.icp_brief, ICP_MAX);
  const voice = coerceString(body.voice_profile, VOICE_MAX);
  const subject = coerceString(body.sample_email_subject, SUBJECT_MAX);
  const emailBody = coerceString(body.sample_email_body, BODY_MAX);
  if (icp == null || voice == null || subject == null || emailBody == null) {
    return NextResponse.json(
      { error: "brief fields missing or too long" },
      { status: 400 },
    );
  }
  const phrases = coercePhrases(body.banned_phrases);
  if (phrases == null) {
    return NextResponse.json(
      { error: "banned_phrases must be a list of strings" },
      { status: 400 },
    );
  }

  let id: string;
  try {
    id = await insertCampaignFull({
      name,
      target_description: target,
      email_style_profile: voice,
      sample_email_subject: subject,
      sample_email_body: emailBody,
      icp_brief: icp,
      banned_phrases: phrases,
    });
  } catch (err) {
    const raw = (err as Error).message || "Persistence failed";
    if (/duplicate|unique/i.test(raw) && /campaigns_name_key|name/i.test(raw)) {
      return NextResponse.json(
        {
          error:
            `A campaign named "${name}" already exists. Go back to Step 1 ` +
            `and choose a different name.`,
        },
        { status: 409 },
      );
    }
    return NextResponse.json({ error: raw }, { status: 500 });
  }

  revalidatePath("/");
  revalidatePath("/campaigns");
  return NextResponse.json({ id });
}
