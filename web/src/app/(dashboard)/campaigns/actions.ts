"use server";

import { sql } from "@/lib/db";
import { revalidatePath } from "next/cache";

export async function updateCampaignStatus(id: string, status: string) {
  const allowed = ["Active", "Paused", "Completed", "Abort"];
  if (!allowed.includes(status)) {
    throw new Error(`Invalid status: ${status}`);
  }
  await sql`UPDATE campaigns SET status = ${status}, updated_at = now() WHERE id = ${id}`;
  revalidatePath("/");
  revalidatePath(`/campaigns/${id}`);
}

export async function updateTargetDescription(id: string, description: string) {
  await sql`UPDATE campaigns SET target_description = ${description}, updated_at = now() WHERE id = ${id}`;
  revalidatePath(`/campaigns/${id}`);
}

export async function createCampaign(name: string, targetDescription: string) {
  await sql`INSERT INTO campaigns (name, target_description) VALUES (${name}, ${targetDescription})`;
  revalidatePath("/");
}
