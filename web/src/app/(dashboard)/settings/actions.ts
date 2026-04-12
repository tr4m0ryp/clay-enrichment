"use server";

import { sql } from "@/lib/db";
import { revalidatePath } from "next/cache";

export async function saveApiKey(key: string, value: string) {
  const allowed = ["gemini_api_key", "brave_search_api_key", "serper_api_key"];
  if (!allowed.includes(key)) throw new Error(`Invalid key: ${key}`);
  await sql`
    INSERT INTO settings (key, value) VALUES (${key}, ${value})
    ON CONFLICT (key) DO UPDATE SET value = ${value}, updated_at = now()
  `;
  revalidatePath("/settings");
}

export async function clearApiKey(key: string) {
  await sql`DELETE FROM settings WHERE key = ${key}`;
  revalidatePath("/settings");
}

export async function saveSmtpConfig(host: string, port: string) {
  await sql`
    INSERT INTO settings (key, value) VALUES ('smtp_host', ${host})
    ON CONFLICT (key) DO UPDATE SET value = ${host}, updated_at = now()
  `;
  await sql`
    INSERT INTO settings (key, value) VALUES ('smtp_port', ${port})
    ON CONFLICT (key) DO UPDATE SET value = ${port}, updated_at = now()
  `;
  revalidatePath("/settings");
}

export async function addSenderAccount(
  email: string,
  password: string,
  dailyLimit: number,
) {
  await sql`
    INSERT INTO sender_accounts (email, password, daily_limit)
    VALUES (${email}, ${password}, ${dailyLimit})
  `;
  revalidatePath("/settings");
}

export async function removeSenderAccount(id: string) {
  await sql`DELETE FROM sender_accounts WHERE id = ${id}`;
  revalidatePath("/settings");
}

export async function toggleSenderAccount(id: string, isActive: boolean) {
  await sql`
    UPDATE sender_accounts SET is_active = ${isActive} WHERE id = ${id}
  `;
  revalidatePath("/settings");
}
