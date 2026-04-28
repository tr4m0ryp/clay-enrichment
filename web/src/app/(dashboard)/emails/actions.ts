"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import {
  approveEmailById,
  rejectEmailById,
  updateEmailContent,
  getNextPendingEmailId,
} from "@/lib/queries";

export async function approveEmail(id: string) {
  await approveEmailById(id);
  revalidatePath("/emails");
}

export async function rejectEmail(id: string) {
  await rejectEmailById(id);
  revalidatePath("/emails");
}

export async function approveEmailAndNext(id: string) {
  await approveEmailById(id);
  revalidatePath("/emails");
  const nextId = await getNextPendingEmailId();
  redirect(nextId ? `/emails/${nextId}` : "/emails");
}

export async function rejectEmailAndNext(id: string) {
  await rejectEmailById(id);
  revalidatePath("/emails");
  const nextId = await getNextPendingEmailId();
  redirect(nextId ? `/emails/${nextId}` : "/emails");
}

export async function updateEmail(id: string, subject: string, body: string) {
  await updateEmailContent(id, subject, body);
  revalidatePath("/emails");
  revalidatePath(`/emails/${id}`);
}
