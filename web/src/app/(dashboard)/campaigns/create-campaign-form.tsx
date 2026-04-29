"use client";

import Link from "next/link";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

// Was a modal with a single-step name + target form. The new multi-step
// brief flow lives at /campaigns/new (Step 1 form -> Step 2 AI brief ->
// Step 3 regenerate / approve), so this component is now just a navigation
// trigger. Kept under the same export name + filename so existing imports
// don't break.

export function CreateCampaignForm() {
  return (
    <Button variant="brand" size="sm" asChild>
      <Link href="/campaigns/new">
        <Plus className="h-4 w-4 mr-1.5" />
        New Campaign
      </Link>
    </Button>
  );
}
