"use client";

import { useTransition } from "react";
import { Button } from "@/components/ui/button";
import { updateCampaignStatus } from "../actions";

const transitions: Record<string, string[]> = {
  Active: ["Paused", "Completed"],
  Paused: ["Active", "Completed"],
  Completed: [],
  Abort: [],
};

function variantFor(status: string) {
  switch (status) {
    case "Active":
      return "brand";
    case "Completed":
      return "default";
    default:
      return "outline";
  }
}

export function StatusActions({
  campaignId,
  currentStatus,
}: {
  campaignId: string;
  currentStatus: string;
}) {
  const [isPending, startTransition] = useTransition();
  const allowed = transitions[currentStatus] ?? [];

  if (allowed.length === 0) return null;

  return (
    <div className="flex gap-2">
      {allowed.map((status) => (
        <Button
          key={status}
          variant={variantFor(status) as "brand" | "default" | "outline"}
          size="sm"
          disabled={isPending}
          onClick={() =>
            startTransition(() => updateCampaignStatus(campaignId, status))
          }
        >
          {isPending ? "..." : status === "Active" ? "Resume" : status}
        </Button>
      ))}
    </div>
  );
}
