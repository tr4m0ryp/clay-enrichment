"use client";

import { useEffect } from "react";
import { useCampaign } from "@/lib/campaign-context";

export function CampaignSetter({ id, name }: { id: string; name: string }) {
  const { setCampaign } = useCampaign();
  useEffect(() => {
    setCampaign({ id, name });
    return () => setCampaign(null);
  }, [id, name, setCampaign]);
  return null;
}
