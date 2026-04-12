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

  async function handleSave() {
    setSaving(true);
    await updateEmail(emailId, subject, body);
    setSaving(false);
    setEditing(false);
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Subject</CardTitle>
          {!editing && (
            <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
              Edit
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {editing ? (
            <Input
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            />
          ) : (
            <p className="text-sm font-medium text-foreground">{subject}</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Email Body</CardTitle>
          {!editing && (
            <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
              Edit
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {editing ? (
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={14}
              className="w-full resize-y rounded border border-border bg-background px-3 py-2 text-sm text-foreground leading-relaxed transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          ) : (
            <p className="text-sm leading-relaxed text-muted-foreground whitespace-pre-line">
              {body}
            </p>
          )}
        </CardContent>
      </Card>

      {editing && (
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
      )}
    </div>
  );
}
