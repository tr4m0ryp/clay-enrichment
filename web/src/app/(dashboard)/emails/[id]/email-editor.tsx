"use client";

import { useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { updateEmail } from "../actions";

interface EmailEditorProps {
  emailId: string;
  initialSubject: string;
  initialBody: string;
}

export function EmailEditor({
  emailId,
  initialSubject,
  initialBody,
}: EmailEditorProps) {
  const [subject, setSubject] = useState(initialSubject);
  const [body, setBody] = useState(initialBody);
  const [isPending, startTransition] = useTransition();
  const isDirty = subject !== initialSubject || body !== initialBody;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Subject</CardTitle>
        </CardHeader>
        <CardContent>
          <Input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Email Body</CardTitle>
        </CardHeader>
        <CardContent>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={14}
            className="w-full resize-y rounded border border-border bg-background px-3 py-2 text-sm text-foreground leading-relaxed placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        </CardContent>
      </Card>

      {isDirty && (
        <div className="flex gap-2">
          <Button
            variant="brand"
            size="sm"
            disabled={isPending}
            onClick={() =>
              startTransition(() => updateEmail(emailId, subject, body))
            }
          >
            {isPending ? "Saving..." : "Save"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={isPending}
            onClick={() => {
              setSubject(initialSubject);
              setBody(initialBody);
            }}
          >
            Cancel
          </Button>
        </div>
      )}
    </div>
  );
}
