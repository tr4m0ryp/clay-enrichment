function Shimmer({ className = "" }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded bg-muted ${className}`}
    />
  );
}

export function TableSkeleton({
  rows = 8,
  cols = 5,
}: {
  rows?: number;
  cols?: number;
}) {
  return (
    <div className="mt-6 space-y-3">
      {/* Header row */}
      <div className="flex gap-4 px-4 py-3">
        {Array.from({ length: cols }).map((_, i) => (
          <Shimmer key={i} className="h-3 flex-1" />
        ))}
      </div>
      {/* Data rows */}
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-4 px-4 py-3">
          {Array.from({ length: cols }).map((_, c) => (
            <Shimmer key={c} className="h-4 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}

export function PageSkeleton({
  title = true,
  subtitle = true,
  children,
}: {
  title?: boolean;
  subtitle?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <div>
      {title && <Shimmer className="h-6 w-48" />}
      {subtitle && <Shimmer className="mt-2 h-4 w-72" />}
      {children}
    </div>
  );
}

export function OverviewSkeleton() {
  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <Shimmer className="h-4 w-20" />
        <Shimmer className="mt-2 h-7 w-64" />
        <div className="mt-2 flex gap-3">
          <Shimmer className="h-5 w-16" />
          <Shimmer className="h-5 w-32" />
        </div>
      </div>
      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="rounded-lg border border-border p-4">
            <Shimmer className="h-4 w-20" />
            <Shimmer className="mt-2 h-7 w-12" />
          </div>
        ))}
      </div>
      {/* Card */}
      <div className="rounded-lg border border-border p-6">
        <Shimmer className="h-5 w-36" />
        <Shimmer className="mt-4 h-20 w-full" />
      </div>
    </div>
  );
}

export function CardListSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded-lg border border-border p-4 space-y-3">
          <Shimmer className="h-4 w-3/4" />
          <Shimmer className="h-3 w-1/2" />
          <Shimmer className="h-3 w-2/3" />
        </div>
      ))}
    </div>
  );
}
