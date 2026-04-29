"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const NAME_MAX = 100;
const TARGET_MAX = 5000;
const SAMPLE_MAX = 5000;

export interface Step1Patch {
  name?: string;
  target?: string;
  sample1?: string;
  sample2?: string;
  sample3?: string;
}

interface Step1Props {
  name: string;
  target: string;
  sample1: string;
  sample2: string;
  sample3: string;
  loading: boolean;
  onChange: (patch: Step1Patch) => void;
  onNext: () => void;
}

export function Step1({
  name,
  target,
  sample1,
  sample2,
  sample3,
  loading,
  onChange,
  onNext,
}: Step1Props) {
  const trimmedName = name.trim();
  const trimmedTarget = target.trim();
  const canNext =
    trimmedName.length > 0 &&
    trimmedName.length <= NAME_MAX &&
    trimmedTarget.length > 0 &&
    trimmedTarget.length <= TARGET_MAX &&
    !loading;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Campaign details</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="space-y-1.5">
            <label
              htmlFor="campaign-name"
              className="text-xs font-medium text-muted-foreground"
            >
              Name
            </label>
            <Input
              id="campaign-name"
              placeholder="e.g. Q3 EU Streetwear"
              value={name}
              maxLength={NAME_MAX}
              onChange={(e) => onChange({ name: e.target.value })}
            />
            <p className="text-xs text-muted-foreground">
              Must be unique. Up to {NAME_MAX} characters.
            </p>
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="campaign-target"
              className="text-xs font-medium text-muted-foreground"
            >
              Target description
            </label>
            <textarea
              id="campaign-target"
              className="min-h-[140px] w-full resize-y rounded border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              placeholder="Describe the audience: industry, segment, geography, decision-makers, intent signals."
              value={target}
              maxLength={TARGET_MAX}
              onChange={(e) => onChange({ target: e.target.value })}
            />
            <p className="text-xs text-muted-foreground">
              {target.length} / {TARGET_MAX} characters
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Sample emails (optional)</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-xs text-muted-foreground">
            Paste 1-3 cold emails whose voice you want the campaign to
            emulate. Leave blank to use the default direct B2B style.
          </p>
          <SampleField
            label="Sample 1"
            value={sample1}
            onChange={(v) => onChange({ sample1: v })}
          />
          <SampleField
            label="Sample 2"
            value={sample2}
            onChange={(v) => onChange({ sample2: v })}
          />
          <SampleField
            label="Sample 3"
            value={sample3}
            onChange={(v) => onChange({ sample3: v })}
          />
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <Button
          variant="brand"
          size="default"
          disabled={!canNext}
          onClick={onNext}
        >
          {loading ? "Generating..." : "Next"}
        </Button>
      </div>
    </div>
  );
}

function SampleField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-medium text-muted-foreground">
        {label}
      </label>
      <textarea
        className="min-h-[80px] w-full resize-y rounded border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        placeholder="Paste a cold email in your preferred voice..."
        value={value}
        maxLength={SAMPLE_MAX}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
