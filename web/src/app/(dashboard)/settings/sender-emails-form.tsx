"use client";

import { useState, useTransition } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  saveSmtpConfig,
  addSenderAccount,
  removeSenderAccount,
  toggleSenderAccount,
} from "./actions";

interface SenderAccount {
  id: string;
  email: string;
  daily_limit: number;
  is_active: boolean;
}

interface SenderEmailsFormProps {
  smtpHost: string;
  smtpPort: string;
  accounts: SenderAccount[];
}

export function SenderEmailsForm({
  smtpHost,
  smtpPort,
  accounts,
}: SenderEmailsFormProps) {
  const [host, setHost] = useState(smtpHost);
  const [port, setPort] = useState(smtpPort);
  const [isPending, startTransition] = useTransition();

  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newLimit, setNewLimit] = useState("10");
  const [showAddForm, setShowAddForm] = useState(false);

  function handleSaveSmtp() {
    startTransition(async () => {
      await saveSmtpConfig(host.trim(), port.trim());
    });
  }

  function handleAddAccount() {
    if (!newEmail.trim() || !newPassword.trim()) return;
    startTransition(async () => {
      await addSenderAccount(
        newEmail.trim(),
        newPassword.trim(),
        parseInt(newLimit) || 10,
      );
      setNewEmail("");
      setNewPassword("");
      setNewLimit("10");
      setShowAddForm(false);
    });
  }

  function handleRemove(id: string) {
    startTransition(async () => {
      await removeSenderAccount(id);
    });
  }

  function handleToggle(id: string, currentlyActive: boolean) {
    startTransition(async () => {
      await toggleSenderAccount(id, !currentlyActive);
    });
  }

  const smtpDirty = host !== smtpHost || port !== smtpPort;

  return (
    <div className="space-y-6">
      {/* SMTP Config */}
      <div className="space-y-3">
        <h3 className="text-sm font-medium">SMTP Server</h3>
        <div className="grid grid-cols-[1fr_100px] gap-3">
          <div className="space-y-1.5">
            <label className="text-xs text-muted-foreground">Host</label>
            <Input
              placeholder="smtp.gmail.com"
              value={host}
              onChange={(e) => setHost(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs text-muted-foreground">Port</label>
            <Input
              placeholder="587"
              value={port}
              onChange={(e) => setPort(e.target.value)}
            />
          </div>
        </div>
        {smtpDirty && (
          <Button
            onClick={handleSaveSmtp}
            disabled={isPending}
            variant="brand"
            size="sm"
          >
            {isPending ? "Saving..." : "Save SMTP"}
          </Button>
        )}
      </div>

      <div className="border-t border-border" />

      {/* Sender Accounts */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium">Sender Accounts</h3>
          {!showAddForm && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowAddForm(true)}
            >
              <Plus className="mr-1.5 h-3.5 w-3.5" />
              Add
            </Button>
          )}
        </div>

        {showAddForm && (
          <div className="space-y-3 rounded border border-border p-4">
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Email</label>
              <Input
                type="email"
                placeholder="sender@example.com"
                value={newEmail}
                onChange={(e) => setNewEmail(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">
                Password
              </label>
              <Input
                type="password"
                placeholder="App password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">
                Daily Limit
              </label>
              <Input
                type="number"
                min="1"
                value={newLimit}
                onChange={(e) => setNewLimit(e.target.value)}
              />
            </div>
            <div className="flex gap-2">
              <Button
                onClick={handleAddAccount}
                disabled={
                  isPending || !newEmail.trim() || !newPassword.trim()
                }
                variant="brand"
                size="sm"
              >
                {isPending ? "Adding..." : "Add Account"}
              </Button>
              <Button
                onClick={() => setShowAddForm(false)}
                variant="ghost"
                size="sm"
              >
                Cancel
              </Button>
            </div>
          </div>
        )}

        {accounts.length === 0 && !showAddForm && (
          <p className="text-sm text-muted-foreground">
            No sender accounts configured.
          </p>
        )}

        {accounts.map((account) => (
          <div
            key={account.id}
            className="flex items-center gap-3 rounded border border-border px-4 py-3"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{account.email}</p>
              <p className="text-xs text-muted-foreground">
                Limit: {account.daily_limit}/day
              </p>
            </div>
            <Badge
              variant={account.is_active ? "success" : "outline"}
              className="cursor-pointer select-none"
              onClick={() => handleToggle(account.id, account.is_active)}
            >
              {account.is_active ? "Active" : "Inactive"}
            </Badge>
            <button
              onClick={() => handleRemove(account.id)}
              className="text-muted-foreground transition-colors hover:text-destructive"
              disabled={isPending}
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
