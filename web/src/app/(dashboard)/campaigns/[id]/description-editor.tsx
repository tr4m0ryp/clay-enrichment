"use client";

import { useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { updateTargetDescription } from "../actions";

export function DescriptionEditor({
  campaignId,
  initialValue,
}: {
  campaignId: string;
  initialValue: string;
}) {
  const [value, setValue] = useState(initialValue);
  const [isPending, startTransition] = useTransition();
  const isDirty = value !== initialValue;

  return (
    <div className="space-y-3">
      <textarea
        className="min-h-[120px] w-full resize-y rounded border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Describe the target audience for this campaign..."
      />
      {isDirty && (
        <div className="flex gap-2">
          <Button
            variant="brand"
            size="sm"
            disabled={isPending}
            onClick={() =>
              startTransition(() =>
                updateTargetDescription(campaignId, value)
              )
            }
          >
            {isPending ? "Saving..." : "Save"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={isPending}
            onClick={() => setValue(initialValue)}
          >
            Cancel
          </Button>
        </div>
      )}
    </div>
  );
}
