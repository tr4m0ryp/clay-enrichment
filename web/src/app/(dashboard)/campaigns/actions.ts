"use server";

import { revalidatePath } from "next/cache";
import {
  updateCampaignStatus as setCampaignStatus,
  updateCampaignTargetDescription,
  insertCampaign,
} from "@/lib/queries";

export async function updateCampaignStatus(id: string, status: string) {
  const allowed = ["Active", "Paused", "Completed", "Abort"];
  if (!allowed.includes(status)) {
    throw new Error(`Invalid status: ${status}`);
  }
  await setCampaignStatus(id, status);
  revalidatePath("/");
  revalidatePath(`/campaigns/${id}`);
}

export async function updateTargetDescription(id: string, description: string) {
  await updateCampaignTargetDescription(id, description);
  revalidatePath(`/campaigns/${id}`);
}

export async function createCampaign(name: string, targetDescription: string) {
  await insertCampaign(name, targetDescription);
  revalidatePath("/");
}
