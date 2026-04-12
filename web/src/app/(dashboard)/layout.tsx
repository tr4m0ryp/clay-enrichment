"use client";

import { Sidebar } from "@/components/sidebar";
import { Header } from "@/components/header";
import { CampaignProvider } from "@/lib/campaign-context";
import { SidebarProvider, useSidebar } from "@/lib/sidebar-context";

function DashboardContent({ children }: { children: React.ReactNode }) {
  const { collapsed } = useSidebar();
  const marginLeft = collapsed ? 56 : 240;

  return (
    <div
      className="flex flex-1 flex-col transition-[margin-left] duration-200"
      style={{ marginLeft }}
    >
      <Header />
      <main className="flex-1 p-6">{children}</main>
    </div>
  );
}

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
          <DashboardContent>{children}</DashboardContent>
        </div>
      </SidebarProvider>
    </CampaignProvider>
  );
}
