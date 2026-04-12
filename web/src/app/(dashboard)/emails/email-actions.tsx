"use client";

import { Button } from "@/components/ui/button";
import { approveEmail, rejectEmail } from "./actions";

export function EmailActions({ emailId }: { emailId: string }) {
  return (
    <div className="mt-4 flex gap-2">
      <Button
        variant="brand"
        size="sm"
        onClick={() => approveEmail(emailId)}
      >
        Approve
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={() => rejectEmail(emailId)}
      >
        Reject
      </Button>
    </div>
  );
}
