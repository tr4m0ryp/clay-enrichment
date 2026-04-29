"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CampaignBrief } from "@/lib/types/campaign";
import { BriefView } from "./Step2";

const FEEDBACK_MAX = 5000;

interface Step3Props {
  brief: CampaignBrief;
  loading: boolean;
  onRegenerate: (feedback: string) => Promise<void>;
  onApprove: () => void;
  onBack: () => void;
}

// Step 3: regenerate-with-feedback loop. Shows the same brief view as
// Step 2 plus a textarea for feedback. Submitting the feedback runs the
// regenerate call and replaces the sample in-place; the locked fields
// (icp_brief / voice_profile / banned_phrases) are server-preserved so
// the visible chips and voice text stay constant.
export function Step3({
  brief,
  loading,
  onRegenerate,
  onApprove,
  onBack,
}: Step3Props) {
  const [feedback, setFeedback] = useState("");
  const trimmed = feedback.trim();
  const canRegenerate =
    !loading && trimmed.length > 0 && trimmed.length <= FEEDBACK_MAX;

  async function submitFeedback() {
    if (!canRegenerate) return;
    await onRegenerate(trimmed);
    setFeedback("");
  }

  return (
    <div className="space-y-6">
      <BriefView brief={brief} />

      <Card>
        <CardHeader>
          <CardTitle>Refine the sample</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">
            Feedback updates only the sample subject + body. The ICP brief,
            voice profile, and banned phrases stay locked.
          </p>
          <textarea
            className="min-h-[120px] w-full resize-y rounded border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            placeholder='e.g. "Make it shorter, lead with the metric."'
            value={feedback}
            maxLength={FEEDBACK_MAX}
            onChange={(e) => setFeedback(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            {feedback.length} / {FEEDBACK_MAX}
          </p>
          <div className="flex justify-end">
            <Button
              variant="default"
              size="default"
              disabled={!canRegenerate}
              onClick={submitFeedback}
            >
              {loading ? "Regenerating..." : "Regenerate"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button
          variant="outline"
          size="default"
          onClick={onBack}
          disabled={loading}
        >
          Back to brief
        </Button>
        <Button
          variant="brand"
          size="default"
          disabled={loading}
          onClick={onApprove}
        >
          Approve
        </Button>
      </div>
    </div>
  );
}
