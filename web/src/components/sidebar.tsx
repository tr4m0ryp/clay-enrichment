"use client";

import {
  LayoutDashboard,
  Target,
  Building2,
  Users,
  Mail,
  Star,
  ArrowLeft,
  Settings,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { useCampaign } from "@/lib/campaign-context";
import { useSidebar } from "@/lib/sidebar-context";
import { AveleroLogo } from "@/components/avelero-logo";
import { AveleroIcon } from "@/components/avelero-icon";

interface NavItem {
  href: string;
  icon: React.ReactNode;
  label: string;
}

function NavLink({ href, icon, label, collapsed }: NavItem & { collapsed: boolean }) {
  const pathname = usePathname();
  const isActive = pathname === href || pathname.startsWith(`${href}/`);

  return (
    <Link
      href={href}
      title={collapsed ? label : undefined}
      className={cn(
        "flex items-center rounded text-sm font-medium transition-colors",
        collapsed ? "justify-center px-2 py-2" : "gap-3 px-3 py-2",
        isActive
          ? "bg-muted text-foreground"
          : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
      )}
    >
      {icon}
      {!collapsed && label}
    </Link>
  );
}

const globalNav: NavItem[] = [
  { href: "/", icon: <LayoutDashboard className="h-4 w-4" />, label: "Dashboard" },
];

export function Sidebar() {
  const { campaign } = useCampaign();
  const { collapsed, toggle } = useSidebar();
  const width = collapsed ? 56 : 240;

  if (campaign) {
    const base = `/campaigns/${campaign.id}`;
    const campaignNav: NavItem[] = [
      { href: base, icon: <Target className="h-4 w-4" />, label: "Overview" },
      { href: `${base}/leads`, icon: <Star className="h-4 w-4" />, label: "Leads" },
      { href: `${base}/companies`, icon: <Building2 className="h-4 w-4" />, label: "Companies" },
      { href: `${base}/contacts`, icon: <Users className="h-4 w-4" />, label: "Contacts" },
      { href: `${base}/emails`, icon: <Mail className="h-4 w-4" />, label: "Emails" },
    ];

    return (
      <aside
        className="fixed inset-y-0 left-0 z-40 flex flex-col border-r border-border bg-background transition-[width] duration-200"
        style={{ width }}
      >
        <div
          className={cn(
            "flex shrink-0 items-center border-b border-border",
            collapsed ? "justify-center" : "justify-between px-5",
          )}
          style={{ height: 56 }}
        >
          {collapsed ? <AveleroIcon size={20} /> : <AveleroLogo height={20} />}
          {!collapsed && (
            <button
              onClick={toggle}
              className="text-muted-foreground hover:text-foreground transition-colors"
            >
              <PanelLeftClose className="h-4 w-4" />
            </button>
          )}
        </div>

        <nav className={cn("flex flex-1 flex-col gap-1 overflow-y-auto py-4", collapsed ? "px-1.5" : "px-3")}>
          {collapsed ? (
            <Link
              href="/"
              title="Back to dashboard"
              className="mb-2 flex justify-center rounded px-2 py-1.5 text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
            </Link>
          ) : (
            <>
              <Link
                href="/"
                className="mb-2 flex items-center gap-2 rounded px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
              >
                <ArrowLeft className="h-3.5 w-3.5" />
                Dashboard
              </Link>
              <p className="mb-3 truncate px-3 text-sm font-semibold text-foreground">
                {campaign.name}
              </p>
            </>
          )}

          {campaignNav.map((item) => (
            <NavLink key={item.href} {...item} collapsed={collapsed} />
          ))}
        </nav>

        <div className={cn("border-t border-border py-3", collapsed ? "px-1.5" : "px-3")}>
          {collapsed && (
            <button
              onClick={toggle}
              title="Expand sidebar"
              className="mb-1 flex w-full justify-center rounded px-2 py-2 text-muted-foreground hover:bg-muted/50 hover:text-foreground transition-colors"
            >
              <PanelLeftOpen className="h-4 w-4" />
            </button>
          )}
          <NavLink
            href="/settings"
            icon={<Settings className="h-4 w-4" />}
            label="Settings"
            collapsed={collapsed}
          />
        </div>
      </aside>
    );
  }

  return (
    <aside
      className="fixed inset-y-0 left-0 z-40 flex flex-col border-r border-border bg-background transition-[width] duration-200"
      style={{ width }}
    >
      <div
        className={cn(
          "flex shrink-0 items-center border-b border-border",
          collapsed ? "justify-center" : "justify-between px-5",
        )}
        style={{ height: 56 }}
      >
        {collapsed ? <AveleroIcon size={20} /> : <AveleroLogo height={20} />}
        {!collapsed && (
          <button
            onClick={toggle}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <PanelLeftClose className="h-4 w-4" />
          </button>
        )}
      </div>

      <nav className={cn("flex flex-1 flex-col gap-1 overflow-y-auto py-4", collapsed ? "px-1.5" : "px-3")}>
        {globalNav.map((item) => (
          <NavLink key={item.href} {...item} collapsed={collapsed} />
        ))}
      </nav>

      <div className={cn("border-t border-border py-3", collapsed ? "px-1.5" : "px-3")}>
        {collapsed && (
          <button
            onClick={toggle}
            title="Expand sidebar"
            className="mb-1 flex w-full justify-center rounded px-2 py-2 text-muted-foreground hover:bg-muted/50 hover:text-foreground transition-colors"
          >
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        )}
        <NavLink
          href="/settings"
          icon={<Settings className="h-4 w-4" />}
          label="Settings"
          collapsed={collapsed}
        />
      </div>
    </aside>
  );
}
