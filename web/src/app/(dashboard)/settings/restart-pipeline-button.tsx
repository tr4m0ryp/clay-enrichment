"use client";

import { useState, useTransition } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { restartPipeline } from "./actions";

type Result = { ok: boolean; message: string } | null;

export function RestartPipelineButton() {
  const [isPending, startTransition] = useTransition();
  const [result, setResult] = useState<Result>(null);

  function handleClick() {
    if (
      !window.confirm(
        "Restart the clay-pipeline service? The pipeline will be unavailable for a few seconds while it reboots. Saved prompt overrides will take effect on restart.",
      )
    ) {
      return;
    }
    setResult(null);
    startTransition(async () => {
      const r = await restartPipeline();
      setResult(r);
      if (r.ok) {
        // Clear the success badge after a few seconds.
        setTimeout(() => setResult(null), 5000);
      }
    });
  }

  return (
    <div className="flex items-center gap-3">
      {result && (
        <span
          className={`text-xs ${
            result.ok ? "text-green-600" : "text-destructive"
          }`}
        >
          {result.message}
        </span>
      )}
      <Button
        variant="outline"
        size="sm"
        disabled={isPending}
        onClick={handleClick}
      >
        <RefreshCw
          className={`mr-1.5 h-3.5 w-3.5 ${isPending ? "animate-spin" : ""}`}
        />
        {isPending ? "Restarting..." : "Restart pipeline"}
      </Button>
    </div>
  );
}
