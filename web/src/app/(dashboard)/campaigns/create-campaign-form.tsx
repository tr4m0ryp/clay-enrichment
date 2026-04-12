"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createCampaign } from "./actions";

export function CreateCampaignForm() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [target, setTarget] = useState("");
  const [isPending, startTransition] = useTransition();
  const router = useRouter();
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) nameRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  function close() {
    setOpen(false);
    setName("");
    setTarget("");
  }

  function handleSubmit() {
    if (!name.trim()) return;
    startTransition(async () => {
      await createCampaign(name.trim(), target.trim());
      close();
      router.refresh();
    });
  }

  return (
    <>
      <Button variant="brand" size="sm" onClick={() => setOpen(true)}>
        <Plus className="h-4 w-4 mr-1.5" />
        New Campaign
      </Button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={close}
          />
          <div className="relative w-full max-w-md rounded-lg border border-border bg-background shadow-lg">
            <div className="flex items-center justify-between border-b border-border px-5 py-4">
              <h2 className="text-sm font-semibold text-foreground">
                Create Campaign
              </h2>
              <button
                onClick={close}
                className="rounded p-1 text-muted-foreground hover:text-foreground transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-4 px-5 py-4">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">
                  Name
                </label>
                <Input
                  ref={nameRef}
                  placeholder="Campaign name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleSubmit();
                  }}
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">
                  Target Description
                </label>
                <textarea
                  className="min-h-[100px] w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  placeholder="Who should this campaign reach?"
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
              <Button
                variant="outline"
                size="sm"
                disabled={isPending}
                onClick={close}
              >
                Cancel
              </Button>
              <Button
                variant="brand"
                size="sm"
                disabled={isPending || !name.trim()}
                onClick={handleSubmit}
              >
                {isPending ? "Creating..." : "Create"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
