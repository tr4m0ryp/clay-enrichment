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
  // Fall back to process.env when the settings table has no entry
  const apiKeyNames = [
    "gemini_api_key",
    "brave_search_api_key",
    "serper_api_key",
  ];
  const envKeyMap: Record<string, string> = {
    gemini_api_key: "GEMINI_API_KEY",
    brave_search_api_key: "BRAVE_SEARCH_API_KEY",
    serper_api_key: "SERPER_API_KEY",
  };
  const keyStatus: Record<string, { configured: boolean; hint: string }> = {};
  for (const key of apiKeyNames) {
    const envName = envKeyMap[key];
    const val =
      settingsMap[key] ||
      (envName ? process.env[envName] : undefined) ||
      "";
    keyStatus[key] = {
      configured: !!val,
      hint: val
        ? val.length <= 8
          ? `${val.slice(0, 2)}${"*".repeat(4)}${val.slice(-2)}`
          : `${val.slice(0, 4)}${"*".repeat(6)}${val.slice(-4)}`
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
