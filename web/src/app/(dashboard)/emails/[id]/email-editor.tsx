"use client";

import { useState } from "react";
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
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState(initialSubject);
  const [body, setBody] = useState(initialBody);
  const [saving, setSaving] = useState(false);

  if (!editing) {
    return (
      <div className="space-y-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Subject</CardTitle>
            <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
              Edit
            </Button>
          </CardHeader>
          <CardContent>
            <p className="text-sm font-medium text-foreground">{subject}</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Email Body</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-relaxed text-muted-foreground whitespace-pre-line">
              {body}
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  async function handleSave() {
    setSaving(true);
    await updateEmail(emailId, subject, body);
    setSaving(false);
    setEditing(false);
  }

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
            rows={12}
            className="w-full rounded border border-border bg-background px-3 py-2 text-sm leading-relaxed transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        </CardContent>
      </Card>

      <div className="flex gap-2">
        <Button variant="brand" size="sm" onClick={handleSave} disabled={saving}>
          {saving ? "Saving..." : "Save"}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setSubject(initialSubject);
            setBody(initialBody);
            setEditing(false);
          }}
        >
          Cancel
        </Button>
      </div>
    </div>
  );
}
