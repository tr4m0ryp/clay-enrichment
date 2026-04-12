"use client";

import { updateOutreachStatus } from "./actions";

const STATUSES = [
  "New",
  "Email Pending Review",
  "Email Approved",
  "Sent",
  "Replied",
  "Meeting Booked",
] as const;

export function OutreachSelect({
  leadId,
  current,
}: {
  leadId: string;
  current: string;
}) {
  return (
    <select
      defaultValue={current}
      onChange={(e) => updateOutreachStatus(leadId, e.target.value)}
      className="h-8 rounded border border-border bg-background px-2 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      {STATUSES.map((s) => (
        <option key={s} value={s}>
          {s}
        </option>
      ))}
    </select>
  );
}
