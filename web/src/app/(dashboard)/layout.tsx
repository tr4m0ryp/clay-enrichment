import { Sidebar } from "@/components/sidebar";
import { Header } from "@/components/header";
import { CampaignProvider } from "@/lib/campaign-context";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <CampaignProvider>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex flex-1 flex-col ml-14 overflow-y-auto">
          <Header />
          <main className="flex-1 p-6">{children}</main>
        </div>
      </div>
    </CampaignProvider>
  );
}
