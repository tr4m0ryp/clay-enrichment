import * as React from "react";
import { type VariantProps, cva } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      variant: {
        default: "bg-muted text-foreground",
        brand: "bg-blue-50 text-blue-700",
        outline: "border border-border text-muted-foreground",
        destructive: "bg-red-50 text-red-700",
        success: "bg-emerald-50 text-emerald-700",
        warning: "bg-amber-50 text-amber-700",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

const dotColorMap: Record<string, string> = {
  default: "bg-foreground/40",
  brand: "bg-blue-500",
  outline: "bg-muted-foreground/50",
  destructive: "bg-red-500",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
};

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {
  dot?: boolean;
}

function Badge({ className, variant, dot = true, children, ...props }: BadgeProps) {
  const v = variant ?? "default";
  return (
    <div className={cn(badgeVariants({ variant, className }))} {...props}>
      {dot && (
        <span
          className={cn("h-1.5 w-1.5 shrink-0 rounded-full", dotColorMap[v])}
        />
      )}
      {children}
    </div>
  );
}

export { Badge, badgeVariants };
