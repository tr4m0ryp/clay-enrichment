import { PageSkeleton, TableSkeleton } from "@/components/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <TableSkeleton rows={8} cols={6} />
    </PageSkeleton>
  );
}
