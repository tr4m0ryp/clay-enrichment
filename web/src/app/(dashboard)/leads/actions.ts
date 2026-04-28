"use server";

import { revalidatePath } from "next/cache";
import { updateContactCampaignOutreach } from "@/lib/queries";

const VALID_STATUSES = [
  "New",
  "Email Pending Review",
  "Email Approved",
  "Sent",
  "Replied",
  "Meeting Booked",
] as const;

export async function updateOutreachStatus(id: string, status: string) {
  if (!VALID_STATUSES.includes(status as (typeof VALID_STATUSES)[number])) {
    throw new Error(`Invalid outreach status: ${status}`);
  }
  await updateContactCampaignOutreach(id, status);
  revalidatePath("/leads");
}
