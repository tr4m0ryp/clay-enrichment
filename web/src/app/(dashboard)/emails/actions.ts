"use server";

import { sql } from "@/lib/db";
import { revalidatePath } from "next/cache";

export async function approveEmail(id: string) {
  await sql`
    UPDATE emails
    SET status = 'Approved'
    WHERE id = ${id} AND status = 'Pending Review'
  `;
  revalidatePath("/emails");
}

export async function rejectEmail(id: string) {
  await sql`
    UPDATE emails
    SET status = 'Rejected'
    WHERE id = ${id} AND status = 'Pending Review'
  `;
  revalidatePath("/emails");
}

export async function updateEmail(id: string, subject: string, body: string) {
  await sql`
    UPDATE emails
    SET subject = ${subject}, body = ${body}, updated_at = now()
    WHERE id = ${id}
  `;
  revalidatePath("/emails");
  revalidatePath(`/emails/${id}`);
}
