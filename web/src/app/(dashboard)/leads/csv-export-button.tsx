"use client";

import { Button } from "@/components/ui/button";
import type { LeadRow } from "./lead-table";

const COLUMNS: { header: string; pick: (l: LeadRow) => string | number | null | undefined }[] = [
  { header: "Company", pick: (l) => l.company_name },
  { header: "Company URL", pick: (l) => l.company_url },
  { header: "Name", pick: (l) => l.name },
  { header: "Job Title", pick: (l) => l.job_title },
  { header: "Email", pick: (l) => l.email },
  { header: "Email Verified", pick: (l) => (l.email_verified ? "Yes" : "No") },
  { header: "LinkedIn", pick: (l) => l.linkedin_url },
  { header: "Fit Score", pick: (l) => l.company_fit_score },
  { header: "Relevance Score", pick: (l) => l.relevance_score },
  { header: "Email Subject", pick: (l) => l.email_subject },
  { header: "Email Body", pick: (l) => l.email_body },
  { header: "Score Reasoning", pick: (l) => l.score_reasoning },
  { header: "Context", pick: (l) => l.context },
  { header: "Personalized Context", pick: (l) => l.personalized_context },
  { header: "Campaign", pick: (l) => l.campaign_name ?? null },
];

function csvCell(value: string | number | null | undefined): string {
  if (value == null) return "";
  const s = String(value);
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function buildCsv(leads: LeadRow[]): string {
  const headerRow = COLUMNS.map((c) => csvCell(c.header)).join(",");
  const dataRows = leads.map((l) =>
    COLUMNS.map((c) => csvCell(c.pick(l))).join(","),
  );
  return [headerRow, ...dataRows].join("\r\n");
}

function isoStamp(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}` +
    `-${pad(d.getHours())}${pad(d.getMinutes())}`
  );
}

export function CsvExportButton({ leads }: { leads: LeadRow[] }) {
  const onClick = () => {
    const csv = buildCsv(leads);
    const blob = new Blob(["﻿" + csv], {
      type: "text/csv;charset=utf-8;",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `high-priority-leads-${isoStamp()}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <Button
      variant="brand"
      size="sm"
      onClick={onClick}
      disabled={leads.length === 0}
      title={leads.length === 0 ? "No leads to export" : "Download CSV"}
    >
      Export CSV
    </Button>
  );
}
