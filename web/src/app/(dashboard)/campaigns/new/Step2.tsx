"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CampaignBrief } from "@/lib/types/campaign";

interface Step2Props {
  loading: boolean;
  brief: CampaignBrief | null;
  onApprove: () => void;
  onRegenerate: () => void;
  onBack: () => void;
}

// Step 2: AI brief review. While loading shows a skeleton; once the brief
// arrives renders the four sections plus the sample email and exposes
// "Regenerate with feedback" + "Approve".
export function Step2({
  loading,
  brief,
  onApprove,
  onRegenerate,
  onBack,
}: Step2Props) {
  if (loading || !brief) {
    return <BriefSkeleton />;
  }
  return (
    <div className="space-y-6">
      <BriefView brief={brief} />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button variant="outline" size="default" onClick={onBack}>
          Back
        </Button>
        <div className="flex flex-wrap gap-2">
          <Button variant="default" size="default" onClick={onRegenerate}>
            Regenerate with feedback
          </Button>
          <Button variant="brand" size="default" onClick={onApprove}>
            Approve
          </Button>
        </div>
      </div>
    </div>
  );
}

export function BriefView({ brief }: { brief: CampaignBrief }) {
  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>ICP brief</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="whitespace-pre-wrap text-sm text-foreground">
            {brief.icp_brief || (
              <span className="text-muted-foreground">
                No ICP brief returned.
              </span>
            )}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Voice profile</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="whitespace-pre-wrap text-sm text-foreground">
            {brief.voice_profile || (
              <span className="text-muted-foreground">
                No voice profile returned.
              </span>
            )}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Banned phrases</CardTitle>
        </CardHeader>
        <CardContent>
          {brief.banned_phrases.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No banned phrases.
            </p>
          ) : (
            <ul className="flex flex-wrap gap-1.5">
              {brief.banned_phrases.map((phrase, idx) => (
                <li
                  key={`${idx}-${phrase}`}
                  className="rounded-full border border-border bg-muted px-2.5 py-1 text-xs text-foreground"
                >
                  {phrase}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Sample email</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <p className="text-xs font-medium text-muted-foreground">
              Subject
            </p>
            <p className="mt-1 font-mono text-sm text-foreground">
              {brief.sample_email_subject || (
                <span className="text-muted-foreground">No subject.</span>
              )}
            </p>
          </div>
          <div>
            <p className="text-xs font-medium text-muted-foreground">Body</p>
            <pre className="mt-1 whitespace-pre-wrap rounded border border-border bg-muted/30 p-3 font-mono text-xs text-foreground">
              {brief.sample_email_body || "(empty)"}
            </pre>
          </div>
        </CardContent>
      </Card>
    </>
  );
}

function BriefSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true">
      <div className="rounded border border-dashed border-border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
        Researching the ICP and drafting the sample email. This usually takes
        3-10 seconds.
      </div>
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className="space-y-3 rounded-lg border border-border bg-background p-6 shadow-sm"
        >
          <div className="h-4 w-40 animate-pulse rounded bg-muted" />
          <div className="h-3 w-full animate-pulse rounded bg-muted" />
          <div className="h-3 w-5/6 animate-pulse rounded bg-muted" />
          <div className="h-3 w-2/3 animate-pulse rounded bg-muted" />
        </div>
      ))}
    </div>
  );
}
