export const dynamic = "force-dynamic";

import { getSettings, getSenderAccounts } from "@/lib/queries";
import { PROMPTS } from "@/lib/prompts/registry";
import { loadPromptDefault } from "@/lib/prompts/loader";
import { PromptsForm, type PromptItem } from "./prompts-form";
import { RestartPipelineButton } from "./restart-pipeline-button";
import { SenderEmailsForm } from "./sender-emails-form";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const PROMPT_KEY_PREFIX = "prompt:";

export default async function SettingsPage() {
  const [settings, accounts, defaults] = await Promise.all([
    getSettings(),
    getSenderAccounts(),
    Promise.all(
      PROMPTS.map((p) => loadPromptDefault(p.pythonFile, p.pythonSymbol)),
    ),
  ]);

  const settingsMap: Record<string, string> = {};
  for (const s of settings) {
    settingsMap[s.key as string] = s.value as string;
  }

  const promptItems: PromptItem[] = PROMPTS.map((p, i) => ({
    key: p.key,
    title: p.title,
    description: p.description,
    category: p.category,
    defaultText: defaults[i] ?? "",
    overrideText: settingsMap[`${PROMPT_KEY_PREFIX}${p.key}`] ?? null,
  }));

  const accountsList = accounts.map((a) => ({
    id: a.id as string,
    email: a.email as string,
    daily_limit: a.daily_limit as number,
    is_active: a.is_active as boolean,
  }));

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Settings</h1>
        <RestartPipelineButton />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>System Prompts</CardTitle>
          <CardDescription>
            Fine-tune the prompts that drive the enrichment pipeline. Each
            prompt is grouped by the worker that uses it -- click to expand,
            edit, and save. Restart the pipeline to apply changes.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <PromptsForm prompts={promptItems} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Sender Emails</CardTitle>
          <CardDescription>
            SMTP configuration and sender accounts for outbound emails.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <SenderEmailsForm
            smtpHost={settingsMap["smtp_host"] ?? ""}
            smtpPort={settingsMap["smtp_port"] ?? "587"}
            accounts={accountsList}
          />
        </CardContent>
      </Card>
    </div>
  );
}
