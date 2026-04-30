"use client";

import * as React from "react";
import { Dialog } from "./dialog";
import { cn } from "@/lib/utils";

interface ExpandableCellProps {
  label: string;
  content: string | null;
  className?: string;
  emptyText?: string;
}

export function ExpandableCell({
  label,
  content,
  className,
  emptyText = "--",
}: ExpandableCellProps) {
  const [open, setOpen] = React.useState(false);

  if (!content) {
    return <span className="text-muted-foreground">{emptyText}</span>;
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          "group block w-full text-left rounded px-1 -mx-1 py-0.5 -my-0.5 hover:bg-muted focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
          className,
        )}
        title="Click to expand"
      >
        <span className="text-xs text-muted-foreground line-clamp-2 group-hover:text-foreground">
          {content}
        </span>
      </button>
      <Dialog open={open} onClose={() => setOpen(false)} title={label}>
        <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-foreground">
          {content}
        </p>
      </Dialog>
    </>
  );
}
