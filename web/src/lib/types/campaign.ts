// Campaign row shape -- mirrors the columns added by schema/009_redesign_2026_04_29.sql
// and the original campaigns table from schema/001_init.sql. Used by both server
// reads (queries/*) and client components in the campaign creation flow.

export type CampaignStatus = "Active" | "Paused" | "Completed" | "Abort";

export interface Campaign {
  id: string;
  name: string;
  target_description: string;
  status: CampaignStatus;
  email_style_profile: string;
  sample_email_subject: string | null;
  sample_email_body: string | null;
  icp_brief: string;
  banned_phrases: string[];
  discovery_strategy_index: number;
  created_at: string;
  updated_at: string;
}

// Brief subset -- the five fields produced by the campaign-brief Gemini call.
// The Approve action persists these onto the campaigns row alongside name +
// target_description.
export interface CampaignBrief {
  icp_brief: string;
  voice_profile: string;
  banned_phrases: string[];
  sample_email_subject: string;
  sample_email_body: string;
}
