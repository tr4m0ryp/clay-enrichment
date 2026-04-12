"use client";

import { useState, useTransition } from "react";
import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { saveApiKey, clearApiKey } from "./actions";

const API_KEYS = [
  { key: "gemini_api_key", label: "Gemini API Key" },
  { key: "brave_search_api_key", label: "Brave Search API Key" },
  { key: "serper_api_key", label: "Serper API Key" },
] as const;

interface ApiKeysFormProps {
  keyStatus: Record<string, { configured: boolean; hint: string }>;
}

export function ApiKeysForm({ keyStatus }: ApiKeysFormProps) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [isPending, startTransition] = useTransition();

  function handleSave() {
    startTransition(async () => {
      for (const { key } of API_KEYS) {
        const val = values[key]?.trim();
        if (val) {
          await saveApiKey(key, val);
        }
      }
      setValues({});
    });
  }

  function handleClear(key: string) {
    startTransition(async () => {
      await clearApiKey(key);
    });
  }

  const hasChanges = Object.values(values).some((v) => v?.trim());

  return (
    <div className="space-y-4">
      {API_KEYS.map(({ key, label }) => {
        const status = keyStatus[key];
        return (
          <div key={key} className="space-y-1.5">
            <div className="flex items-center gap-2">
              <label className="text-sm font-medium">{label}</label>
              {status?.configured && (
                <>
                  <Badge variant="success">Configured</Badge>
                  <span className="text-xs text-muted-foreground">
                    {status.hint}
                  </span>
                  <button
                    onClick={() => handleClear(key)}
                    className="ml-auto text-muted-foreground hover:text-destructive transition-colors"
                    disabled={isPending}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </>
              )}
            </div>
            <Input
              type="password"
              placeholder={
                status?.configured
                  ? "Enter new key to replace"
                  : "Enter API key"
              }
              value={values[key] ?? ""}
              onChange={(e) =>
                setValues({ ...values, [key]: e.target.value })
              }
            />
          </div>
        );
      })}
      <Button
        onClick={handleSave}
        disabled={isPending || !hasChanges}
        variant="brand"
      >
        {isPending ? "Saving..." : "Save API Keys"}
      </Button>
    </div>
  );
}
