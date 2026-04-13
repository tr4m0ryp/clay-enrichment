"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";

const TABS = ["Pending Review", "Approved", "Sent", "Rejected"] as const;

export function FilterTabs({ current }: { current: string }) {
  return (
    <div className="flex gap-1 border-b border-border">
      {TABS.map((tab) => (
        <Link
          prefetch
          key={tab}
          href={`/emails?status=${encodeURIComponent(tab)}`}
          className={cn(
            "px-4 py-2 text-sm font-medium transition-colors",
            current === tab
              ? "border-b-2 border-foreground text-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {tab}
        </Link>
      ))}
    </div>
  );
}
