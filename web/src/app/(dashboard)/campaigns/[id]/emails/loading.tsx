import { PageSkeleton, CardListSkeleton } from "@/components/skeletons";

export default function Loading() {
  return (
    <PageSkeleton>
      <CardListSkeleton count={6} />
    </PageSkeleton>
  );
}
