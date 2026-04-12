"use client";

import { useRouter } from "next/navigation";

interface Campaign {
  id: string;
  name: string;
}

export function CampaignFilter({
  campaigns,
  current,
}: {
  campaigns: Campaign[];
  current: string;
}) {
  const router = useRouter();

  return (
    <select
      value={current}
      onChange={(e) => router.push(`/leads?campaign=${e.target.value}`)}
      className="h-9 rounded border border-border bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      <option value="all">All Campaigns</option>
      {campaigns.map((c) => (
        <option key={c.id} value={c.id}>
          {c.name}
        </option>
      ))}
    </select>
  );
}
