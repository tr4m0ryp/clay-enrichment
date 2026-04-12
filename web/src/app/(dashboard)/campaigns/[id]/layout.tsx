import { getCampaignById } from "@/lib/queries";
import { CampaignSetter } from "./campaign-setter";

export default async function CampaignLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const campaign = await getCampaignById(id);

  return (
    <>
      <CampaignSetter id={id} name={campaign?.name ?? "Campaign"} />
      {children}
    </>
  );
}
