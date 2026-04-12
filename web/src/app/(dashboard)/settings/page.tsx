export const dynamic = "force-dynamic";

import { getSettings, getSenderAccounts } from "@/lib/queries";
import { ApiKeysForm } from "./api-keys-form";
import { SenderEmailsForm } from "./sender-emails-form";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default async function SettingsPage() {
  const [settings, accounts] = await Promise.all([
    getSettings(),
    getSenderAccounts(),
  ]);

  const settingsMap: Record<string, string> = {};
  for (const s of settings) {
    settingsMap[s.key as string] = s.value as string;
  }

  // Mask API keys -- never send full values to client
  const apiKeyNames = [
    "gemini_api_key",
    "brave_search_api_key",
    "serper_api_key",
  ];
  const keyStatus: Record<string, { configured: boolean; hint: string }> = {};
  for (const key of apiKeyNames) {
    const val = settingsMap[key];
    keyStatus[key] = {
      configured: !!val,
      hint: val
        ? val.length <= 2
          ? "**"
          : `${val[0]}${"*".repeat(Math.min(val.length - 2, 8))}${val[val.length - 1]}`
        : "",
    };
  }

  const accountsList = accounts.map((a) => ({
    id: a.id as string,
    email: a.email as string,
    daily_limit: a.daily_limit as number,
    is_active: a.is_active as boolean,
  }));

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="text-lg font-semibold">Settings</h1>

      <Card>
        <CardHeader>
          <CardTitle>API Keys</CardTitle>
          <CardDescription>
            Manage API keys used by the enrichment pipeline.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ApiKeysForm keyStatus={keyStatus} />
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
