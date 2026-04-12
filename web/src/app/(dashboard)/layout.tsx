"use client";

import { Sidebar } from "@/components/sidebar";
import { Header } from "@/components/header";
import { CampaignProvider } from "@/lib/campaign-context";
import { SidebarProvider, useSidebar } from "@/lib/sidebar-context";

function DashboardContent({ children }: { children: React.ReactNode }) {
  const { collapsed } = useSidebar();

  return (
    <div
      className="flex flex-1 flex-col"
      style={{
        marginLeft: 240,
        transform: collapsed ? "translateX(-184px)" : "translateX(0)",
        transition: "transform 150ms ease-out",
      }}
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
