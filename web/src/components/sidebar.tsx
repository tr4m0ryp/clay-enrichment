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
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { useCampaign } from "@/lib/campaign-context";
import { useSidebar } from "@/lib/sidebar-context";
import { AveleroLogo } from "@/components/avelero-logo";

interface NavItem {
  href: string;
  icon: React.ReactNode;
  label: string;
  exact?: boolean;
}

function NavLink({ href, icon, label, exact }: NavItem) {
  const pathname = usePathname();
  const isActive = exact ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);

  return (
    <Link
      href={href}
      title={label}
      className={cn(
        "sidebar-navlink flex items-center gap-3 rounded px-3 py-2 text-sm font-medium transition-colors",
        isActive
          ? "bg-muted text-foreground"
          : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
      )}
    >
      {icon}
      <span className="sidebar-label">{label}</span>
    </Link>
  );
}

const globalNav: NavItem[] = [
  { href: "/", icon: <LayoutDashboard className="h-4 w-4" />, label: "Dashboard" },
];

export function Sidebar() {
  const { campaign } = useCampaign();
  const { toggle } = useSidebar();

  if (campaign) {
    const base = `/campaigns/${campaign.id}`;
    const campaignNav: NavItem[] = [
      { href: base, icon: <Target className="h-4 w-4" />, label: "Overview", exact: true },
      { href: `${base}/leads`, icon: <Star className="h-4 w-4" />, label: "Leads" },
      { href: `${base}/companies`, icon: <Building2 className="h-4 w-4" />, label: "Companies" },
      { href: `${base}/contacts`, icon: <Users className="h-4 w-4" />, label: "Contacts" },
      { href: `${base}/emails`, icon: <Mail className="h-4 w-4" />, label: "Emails" },
    ];

    return (
      <aside className="sidebar fixed inset-y-0 left-0 z-40 flex flex-col border-r border-border bg-background">
        <div
          className="sidebar-header flex shrink-0 items-center border-b border-border px-5"
          style={{ height: 56 }}
        >
          <AveleroLogo height={20} />
        </div>

        <nav className="sidebar-nav flex flex-1 flex-col gap-1 overflow-y-auto px-3 py-4">
          <Link
            href="/"
            title="Back to dashboard"
            className="sidebar-navlink mb-2 flex items-center gap-2 rounded px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            <span className="sidebar-label">Dashboard</span>
          </Link>
          <p className="sidebar-label mb-3 truncate px-3 text-sm font-semibold text-foreground">
            {campaign.name}
          </p>

          {campaignNav.map((item) => (
            <NavLink key={item.href} {...item} />
          ))}
        </nav>

        <div className="sidebar-footer border-t border-border px-3 py-3">
          <NavLink
            href="/settings"
            icon={<Settings className="h-4 w-4" />}
            label="Settings"
          />
          <button
            onClick={toggle}
            title="Collapse sidebar"
            className="sidebar-navlink mt-1 flex w-full items-center gap-3 rounded px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-muted/50 hover:text-foreground transition-colors"
          >
            <PanelLeftClose className="h-4 w-4" />
            <span className="sidebar-label">Collapse</span>
          </button>
        </div>
      </aside>
    );
  }

  return (
    <aside className="sidebar fixed inset-y-0 left-0 z-40 flex flex-col border-r border-border bg-background">
      <div
        className="sidebar-header flex shrink-0 items-center border-b border-border px-5"
        style={{ height: 56 }}
      >
        <AveleroLogo height={20} />
      </div>

      <nav className="sidebar-nav flex flex-1 flex-col gap-1 overflow-y-auto px-3 py-4">
        {globalNav.map((item) => (
          <NavLink key={item.href} {...item} />
        ))}
      </nav>

      <div className="sidebar-footer border-t border-border px-3 py-3">
        <NavLink
          href="/settings"
          icon={<Settings className="h-4 w-4" />}
          label="Settings"
        />
        <button
          onClick={toggle}
          title="Collapse sidebar"
          className="sidebar-navlink mt-1 flex w-full items-center gap-3 rounded px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-muted/50 hover:text-foreground transition-colors"
        >
          <PanelLeftClose className="h-4 w-4" />
          <span className="sidebar-label">Collapse</span>
        </button>
      </div>
    </aside>
  );
}
