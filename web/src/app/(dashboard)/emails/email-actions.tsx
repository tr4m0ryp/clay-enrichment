"use client";

import { Button } from "@/components/ui/button";
import {
  approveEmail,
  rejectEmail,
  approveEmailAndNext,
  rejectEmailAndNext,
} from "./actions";

export function EmailActions({
  emailId,
  navigateToNext,
}: {
  emailId: string;
  navigateToNext?: boolean;
}) {
  const approve = navigateToNext ? approveEmailAndNext : approveEmail;
  const reject = navigateToNext ? rejectEmailAndNext : rejectEmail;

  return (
    <div
      className="mt-4 flex gap-2"
      onClick={(e) => e.preventDefault()}
    >
      <Button
        variant="brand"
        size="sm"
        onClick={(e) => {
          e.preventDefault();
          approve(emailId);
        }}
      >
        Approve
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={(e) => {
          e.preventDefault();
          reject(emailId);
        }}
      >
        Reject
      </Button>
    </div>
  );
}
