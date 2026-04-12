"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createCampaign } from "./actions";

export function CreateCampaignForm() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [target, setTarget] = useState("");
  const [isPending, startTransition] = useTransition();
  const router = useRouter();

  function handleSubmit() {
    if (!name.trim()) return;
    startTransition(async () => {
      await createCampaign(name.trim(), target.trim());
      setName("");
      setTarget("");
      setOpen(false);
      router.refresh();
    });
  }

  if (!open) {
    return (
      <Button variant="brand" size="sm" onClick={() => setOpen(true)}>
        New Campaign
      </Button>
    );
  }

  return (
    <div className="rounded-lg border border-border p-4 space-y-3">
      <p className="text-sm font-medium text-foreground">Create Campaign</p>
      <Input
        placeholder="Campaign name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        autoFocus
      />
      <textarea
        className="min-h-[80px] w-full resize-y rounded border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        placeholder="Target description (who should this campaign reach?)"
        value={target}
        onChange={(e) => setTarget(e.target.value)}
      />
      <div className="flex gap-2">
        <Button
          variant="brand"
          size="sm"
          disabled={isPending || !name.trim()}
          onClick={handleSubmit}
        >
          {isPending ? "Creating..." : "Create"}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={isPending}
          onClick={() => {
            setOpen(false);
            setName("");
            setTarget("");
          }}
        >
          Cancel
        </Button>
      </div>
    </div>
  );
}
