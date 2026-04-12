"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

type Campaign = { id: string; name: string } | null;

const CampaignCtx = createContext<{
  campaign: Campaign;
  setCampaign: (c: Campaign) => void;
}>({ campaign: null, setCampaign: () => {} });

export function CampaignProvider({ children }: { children: ReactNode }) {
  const [campaign, setCampaign] = useState<Campaign>(null);
  return (
    <CampaignCtx.Provider value={{ campaign, setCampaign }}>
      {children}
    </CampaignCtx.Provider>
  );
}

export function useCampaign() {
  return useContext(CampaignCtx);
}
