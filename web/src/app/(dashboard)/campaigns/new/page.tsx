"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import type { CampaignBrief } from "@/lib/types/campaign";
import { Step1 } from "./Step1";
import { Step2 } from "./Step2";
import { Step3 } from "./Step3";

type StepId = 1 | 2 | 3;

interface FormState {
  name: string;
  target: string;
  sample1: string;
  sample2: string;
  sample3: string;
}

const EMPTY_FORM: FormState = {
  name: "",
  target: "",
  sample1: "",
  sample2: "",
  sample3: "",
};

// Multi-step campaign creation flow. Step 1 collects name + target + up to
// three sample emails; on Next we POST to /api/campaign-brief/generate and
// transition to Step 2. Step 2 displays the AI brief; "Regenerate" moves
// into Step 3. Step 3 takes feedback, calls /api/campaign-brief/regenerate,
// and shows the updated sample. "Approve" on either Step 2 or Step 3 calls
// /api/campaigns/finalize and redirects to /campaigns/[id].
export default function NewCampaignPage() {
  const router = useRouter();
  const [step, setStep] = useState<StepId>(1);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [brief, setBrief] = useState<CampaignBrief | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function collectSamples(): string[] {
    return [form.sample1, form.sample2, form.sample3]
      .map((s) => s.trim())
      .filter(Boolean);
  }

  async function postJson<T>(
    url: string,
    body: unknown,
  ): Promise<{ ok: true; data: T } | { ok: false; error: string }> {
    try {
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const json = (await resp.json().catch(() => null)) as
        | { error?: string }
        | T
        | null;
      if (!resp.ok) {
        const message =
          (json && typeof json === "object" && "error" in json
            ? (json as { error?: string }).error
            : null) || `Request failed (${resp.status})`;
        return { ok: false, error: message };
      }
      return { ok: true, data: json as T };
    } catch (err) {
      return { ok: false, error: (err as Error).message || "Network error" };
    }
  }

  async function handleGenerate() {
    setError(null);
    setLoading(true);
    setStep(2);
    const result = await postJson<{ brief: CampaignBrief }>(
      "/api/campaign-brief/generate",
      {
        name: form.name.trim(),
        target_description: form.target.trim(),
        sample_emails: collectSamples(),
      },
    );
    setLoading(false);
    if (!result.ok) {
      setError(result.error);
      setStep(1);
      return;
    }
    setBrief(result.data.brief);
  }

  async function handleRegenerate(feedback: string): Promise<void> {
    if (!brief) return;
    setError(null);
    setLoading(true);
    const result = await postJson<{ brief: CampaignBrief }>(
      "/api/campaign-brief/regenerate",
      {
        name: form.name.trim(),
        target_description: form.target.trim(),
        prior_brief: brief,
        user_feedback: feedback.trim(),
      },
    );
    setLoading(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    setBrief(result.data.brief);
  }

  async function handleApprove() {
    if (!brief) return;
    setError(null);
    setLoading(true);
    const result = await postJson<{ id: string }>(
      "/api/campaigns/finalize",
      {
        name: form.name.trim(),
        target_description: form.target.trim(),
        icp_brief: brief.icp_brief,
        voice_profile: brief.voice_profile,
        banned_phrases: brief.banned_phrases,
        sample_email_subject: brief.sample_email_subject,
        sample_email_body: brief.sample_email_body,
      },
    );
    setLoading(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    router.push(`/campaigns/${result.data.id}`);
  }

  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <div>
        <Link
          href="/campaigns"
          className="inline-flex items-center text-sm text-muted-foreground hover:text-foreground"
        >
          <ChevronLeft className="h-4 w-4" />
          Campaigns
        </Link>
        <h1 className="mt-2 text-2xl font-semibold text-foreground">
          New Campaign
        </h1>
        <StepIndicator step={step} />
      </div>

      {error && (
        <div className="rounded border border-destructive/40 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {step === 1 && (
        <Step1
          name={form.name}
          target={form.target}
          sample1={form.sample1}
          sample2={form.sample2}
          sample3={form.sample3}
          loading={loading}
          onChange={(patch) => setForm((prev) => ({ ...prev, ...patch }))}
          onNext={handleGenerate}
        />
      )}

      {step === 2 && (
        <Step2
          loading={loading}
          brief={brief}
          onApprove={handleApprove}
          onRegenerate={() => setStep(3)}
          onBack={() => {
            setStep(1);
            setBrief(null);
          }}
        />
      )}

      {step === 3 && brief && (
        <Step3
          brief={brief}
          loading={loading}
          onRegenerate={handleRegenerate}
          onApprove={handleApprove}
          onBack={() => setStep(2)}
        />
      )}
    </div>
  );
}

function StepIndicator({ step }: { step: StepId }) {
  const steps = [
    { id: 1, label: "Details" },
    { id: 2, label: "Review brief" },
    { id: 3, label: "Refine" },
  ];
  return (
    <ol className="mt-3 flex items-center gap-2 text-xs">
      {steps.map((s) => {
        const active = step === s.id;
        const done = step > s.id;
        const cls = active
          ? "bg-blue-50 text-blue-700 border-blue-200"
          : done
            ? "bg-emerald-50 text-emerald-700 border-emerald-200"
            : "bg-muted text-muted-foreground border-transparent";
        return (
          <li
            key={s.id}
            className={`rounded-full border px-2 py-0.5 ${cls}`}
          >
            Step {s.id} -- {s.label}
          </li>
        );
      })}
    </ol>
  );
}
