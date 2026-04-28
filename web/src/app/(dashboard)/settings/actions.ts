"use server";

import { revalidatePath } from "next/cache";
import {
  upsertSetting,
  deleteSetting,
  insertSenderAccount,
  deleteSenderAccount,
  setSenderAccountActive,
} from "@/lib/queries";

export async function saveApiKey(key: string, value: string) {
  const allowed = ["gemini_api_key", "brave_search_api_key", "serper_api_key"];
  if (!allowed.includes(key)) throw new Error(`Invalid key: ${key}`);
  await upsertSetting(key, value);
  revalidatePath("/settings");
}

export async function clearApiKey(key: string) {
  await deleteSetting(key);
  revalidatePath("/settings");
}

export async function saveSmtpConfig(host: string, port: string) {
  await upsertSetting("smtp_host", host);
  await upsertSetting("smtp_port", port);
  revalidatePath("/settings");
}

export async function addSenderAccount(
  email: string,
  password: string,
  dailyLimit: number,
) {
  await insertSenderAccount(email, password, dailyLimit);
  revalidatePath("/settings");
}

export async function removeSenderAccount(id: string) {
  await deleteSenderAccount(id);
  revalidatePath("/settings");
}

export async function toggleSenderAccount(id: string, isActive: boolean) {
  await setSenderAccountActive(id, isActive);
  revalidatePath("/settings");
}
