import { Sidebar } from "@/components/sidebar";
import { Header } from "@/components/header";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex flex-1 flex-col" style={{ marginLeft: 240 }}>
        <Header />
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
