import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface QuotaCardProps {
  title: string;
  used: number;
  total: number;
  description?: string;
  // Optional secondary metric -- e.g. credits used while the primary
  // metric is API call count. Rendered small below the main number.
  subline?: string;
}

export function QuotaCard({
  title,
  used,
  total,
  description,
  subline,
}: QuotaCardProps) {
  const safeTotal = Math.max(total, 1);
  const pct = Math.min(100, Math.round((used / safeTotal) * 100));
  // Color the bar by burn rate: green under 60%, amber 60-85%, red beyond.
  const barColor =
    pct >= 85
      ? "bg-destructive"
      : pct >= 60
        ? "bg-amber-500"
        : "bg-primary";

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-bold tabular-nums text-foreground">
            {used.toLocaleString()}
          </span>
          <span className="text-sm font-medium tabular-nums text-muted-foreground">
            / {total.toLocaleString()}
          </span>
          <span className="ml-auto text-xs text-muted-foreground tabular-nums">
            {pct}%
          </span>
        </div>
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            className={cn("h-full transition-all", barColor)}
            style={{ width: `${pct}%` }}
          />
        </div>
        {subline && (
          <p className="mt-2 text-xs tabular-nums text-foreground/70">
            {subline}
          </p>
        )}
        {description && (
          <p className="mt-1 text-xs text-muted-foreground">{description}</p>
        )}
      </CardContent>
    </Card>
  );
}
