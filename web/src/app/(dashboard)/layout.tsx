"use client";

import { Sidebar } from "@/components/sidebar";
import { Header } from "@/components/header";
import { CampaignProvider } from "@/lib/campaign-context";
import { SidebarProvider } from "@/lib/sidebar-context";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <CampaignProvider>
      <SidebarProvider>
        <div className="flex min-h-screen">
          <Sidebar />
          <div className="sidebar-content flex flex-1 flex-col">
            <Header />
            <main className="flex-1 p-6">{children}</main>
          </div>
        </div>
      </SidebarProvider>
    </CampaignProvider>
  );
}
