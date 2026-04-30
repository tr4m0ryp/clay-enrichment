"use client";

import { useState, useTransition } from "react";
import { ChevronDown, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { savePrompt, resetPrompt } from "./actions";

export interface PromptItem {
  key: string;
  title: string;
  description: string;
  category: string;
  defaultText: string;
  overrideText: string | null;
}

interface PromptsFormProps {
  prompts: PromptItem[];
}

export function PromptsForm({ prompts }: PromptsFormProps) {
  // Group by category, preserving the registry order within each group.
  const groups = new Map<string, PromptItem[]>();
  for (const p of prompts) {
    const list = groups.get(p.category) ?? [];
    list.push(p);
    groups.set(p.category, list);
  }

  return (
    <div className="space-y-8">
      {Array.from(groups.entries()).map(([category, items]) => (
        <div key={category} className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {category}
          </h3>
          <div className="space-y-2">
            {items.map((p) => (
              <PromptRow key={p.key} item={p} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function PromptRow({ item }: { item: PromptItem }) {
  const initial = item.overrideText ?? item.defaultText;
  const [text, setText] = useState(initial);
  const [open, setOpen] = useState(false);
  const [isPending, startTransition] = useTransition();

  const isCustom = item.overrideText !== null;
  const isDirty = text !== initial;

  function handleSave() {
    startTransition(async () => {
      await savePrompt(item.key, text);
    });
  }

  function handleReset() {
    startTransition(async () => {
      await resetPrompt(item.key);
      setText(item.defaultText);
    });
  }

  function handleCancel() {
    setText(initial);
  }

  return (
    <div className="rounded border border-border bg-card">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/40"
      >
        <ChevronDown
          className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${
            open ? "rotate-0" : "-rotate-90"
          }`}
        />
        <span className="flex-1 text-sm font-medium">{item.title}</span>
        {isCustom ? (
          <Badge variant="success">Custom</Badge>
        ) : (
          <Badge variant="outline">Default</Badge>
        )}
      </button>

      {open && (
        <div className="space-y-4 border-t border-border px-4 py-4">
          <p className="text-sm text-muted-foreground leading-relaxed">
            {item.description}
          </p>

          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={18}
            spellCheck={false}
            className="w-full resize-y rounded border border-border bg-background px-3 py-2 font-mono text-xs leading-relaxed text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />

          <div className="flex flex-wrap items-center gap-2">
            {isDirty && (
              <>
                <Button
                  variant="brand"
                  size="sm"
                  disabled={isPending}
                  onClick={handleSave}
                >
                  {isPending ? "Saving..." : "Save"}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={isPending}
                  onClick={handleCancel}
                >
                  Cancel
                </Button>
              </>
            )}
            {isCustom && !isDirty && (
              <Button
                variant="ghost"
                size="sm"
                disabled={isPending}
                onClick={handleReset}
                className="text-muted-foreground hover:text-foreground"
              >
                <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                Reset to default
              </Button>
            )}
            <span className="ml-auto text-xs text-muted-foreground">
              Restart the pipeline to pick up changes.
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
