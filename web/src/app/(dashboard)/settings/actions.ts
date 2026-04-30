"use server";

import { revalidatePath } from "next/cache";
import {
  upsertSetting,
  deleteSetting,
  insertSenderAccount,
  deleteSenderAccount,
  setSenderAccountActive,
} from "@/lib/queries";
import { PROMPTS } from "@/lib/prompts/registry";

const PROMPT_KEY_PREFIX = "prompt:";

function assertKnownPromptKey(key: string) {
  if (!PROMPTS.some((p) => p.key === key)) {
    throw new Error(`Unknown prompt key: ${key}`);
  }
}

export async function savePrompt(key: string, value: string) {
  assertKnownPromptKey(key);
  const trimmed = value.replace(/\s+$/g, "");
  if (!trimmed.trim()) {
    // Empty value is treated as a reset.
    await deleteSetting(`${PROMPT_KEY_PREFIX}${key}`);
  } else {
    await upsertSetting(`${PROMPT_KEY_PREFIX}${key}`, trimmed);
  }
  revalidatePath("/settings");
}

export async function resetPrompt(key: string) {
  assertKnownPromptKey(key);
  await deleteSetting(`${PROMPT_KEY_PREFIX}${key}`);
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
