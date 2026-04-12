"use server";

import { sql } from "@/lib/db";
import { revalidatePath } from "next/cache";

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

  await sql`
    UPDATE contact_campaigns
    SET outreach_status = ${status}
    WHERE id = ${id}
  `;
  revalidatePath("/leads");
}
