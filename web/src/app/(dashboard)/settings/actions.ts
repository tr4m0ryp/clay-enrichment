"use server";

import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { revalidatePath } from "next/cache";
import {
  upsertSetting,
  deleteSetting,
  insertSenderAccount,
  deleteSenderAccount,
  setSenderAccountActive,
} from "@/lib/queries";
import { PROMPTS } from "@/lib/prompts/registry";

const execFileAsync = promisify(execFile);

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

// Restart the clay-pipeline systemd unit so prompt overrides (and any
// other module-level config the pipeline reads at import time) pick up
// new values. Wired to the NOPASSWD sudoers rule installed by deploy.sh
// at /etc/sudoers.d/clay-restart.
export async function restartPipeline(): Promise<{
  ok: boolean;
  message: string;
}> {
  try {
    await execFileAsync(
      "/usr/bin/sudo",
      ["-n", "/usr/bin/systemctl", "restart", "clay-pipeline"],
      { timeout: 30_000 },
    );
  } catch (err) {
    const e = err as { stderr?: string; message?: string };
    return {
      ok: false,
      message: (e.stderr || e.message || "restart failed").trim().slice(0, 400),
    };
  }

  // Give systemd a brief moment to settle, then confirm the unit is up.
  await new Promise((r) => setTimeout(r, 1500));
  try {
    const { stdout } = await execFileAsync(
      "/usr/bin/sudo",
      ["-n", "/usr/bin/systemctl", "is-active", "clay-pipeline"],
      { timeout: 10_000 },
    );
    const state = stdout.trim();
    return {
      ok: state === "active",
      message:
        state === "active"
          ? "Pipeline restarted and active."
          : `Restart issued, but unit reports state: ${state}`,
    };
  } catch (err) {
    const e = err as { stdout?: string; stderr?: string; message?: string };
    return {
      ok: false,
      message: (
        e.stdout || e.stderr || e.message || "status check failed"
      )
        .trim()
        .slice(0, 400),
    };
  }
}
