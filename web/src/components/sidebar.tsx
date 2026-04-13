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
import { AveleroIcon } from "@/components/avelero-icon";
import { useRef, useState } from "react";

interface NavItem {
  href: string;
  icon: React.ReactNode;
  label: string;
  exact?: boolean;
}

function NavLink({ href, icon, label, isExpanded, exact }: NavItem & { isExpanded: boolean }) {
  const pathname = usePathname();
  const isActive = exact ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);

  return (
    <Link
      prefetch
      href={href}
      title={label}
      className={cn(
        "relative flex items-center h-10 rounded text-sm font-medium transition-colors",
        isActive
          ? "bg-muted text-foreground"
          : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
      )}
    >
      <div className="flex-shrink-0 w-10 h-10 flex items-center justify-center">
        {icon}
      </div>
      <span
        className={cn(
          "truncate transition-opacity duration-150 ease-out",
          isExpanded ? "opacity-100" : "opacity-0",
        )}
      >
        {label}
      </span>
    </Link>
  );
}

const globalNav: NavItem[] = [
  { href: "/", icon: <LayoutDashboard className="h-4 w-4" />, label: "Dashboard" },
];

export function Sidebar() {
  const { campaign } = useCampaign();
  const [isExpanded, setIsExpanded] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);

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
      <aside
        ref={sidebarRef}
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex flex-col border-r border-border bg-background overflow-hidden",
          "transition-[width] duration-200 ease-out",
          isExpanded ? "w-60" : "w-14",
        )}
        onMouseEnter={() => setIsExpanded(true)}
        onMouseLeave={() => setIsExpanded(false)}
      >
        <div
          className="flex shrink-0 items-center border-b border-border overflow-hidden"
          style={{ height: 56 }}
        >
          <div className="flex-shrink-0 w-14 h-14 flex items-center justify-center">
            <AveleroIcon size={22} />
          </div>
        </div>

        <nav className="flex flex-1 flex-col gap-1 overflow-y-auto p-2">
          <Link
            prefetch
            href="/"
            title="Back to dashboard"
            className="relative flex items-center h-8 rounded text-xs font-medium text-muted-foreground hover:text-foreground transition-colors mb-1"
          >
            <div className="flex-shrink-0 w-10 h-8 flex items-center justify-center">
              <ArrowLeft className="h-3.5 w-3.5" />
            </div>
            <span
              className={cn(
                "truncate transition-opacity duration-150 ease-out",
                isExpanded ? "opacity-100" : "opacity-0",
              )}
            >
              Dashboard
            </span>
          </Link>
          <p
            className={cn(
              "mb-2 truncate px-2 text-sm font-semibold text-foreground transition-opacity duration-150 ease-out",
              isExpanded ? "opacity-100" : "opacity-0",
            )}
          >
            {campaign.name}
          </p>

          {campaignNav.map((item) => (
            <NavLink key={item.href} {...item} isExpanded={isExpanded} />
          ))}
        </nav>

        <div className="border-t border-border p-2">
          <NavLink
            href="/settings"
            icon={<Settings className="h-4 w-4" />}
            label="Settings"
            isExpanded={isExpanded}
          />
        </div>
      </aside>
    );
  }

  return (
    <aside
      ref={sidebarRef}
      className={cn(
        "fixed inset-y-0 left-0 z-40 flex flex-col border-r border-border bg-background overflow-hidden",
        "transition-[width] duration-200 ease-out",
        isExpanded ? "w-60" : "w-14",
      )}
      onMouseEnter={() => setIsExpanded(true)}
      onMouseLeave={() => setIsExpanded(false)}
    >
      <div
        className="flex shrink-0 items-center border-b border-border overflow-hidden"
        style={{ height: 56 }}
      >
        <div className="flex-shrink-0 w-14 h-14 flex items-center justify-center">
          <AveleroIcon size={22} />
        </div>
      </div>

      <nav className="flex flex-1 flex-col gap-1 overflow-y-auto p-2">
        {globalNav.map((item) => (
          <NavLink key={item.href} {...item} isExpanded={isExpanded} />
        ))}
      </nav>

      <div className="border-t border-border p-2">
        <NavLink
          href="/settings"
          icon={<Settings className="h-4 w-4" />}
          label="Settings"
          isExpanded={isExpanded}
        />
      </div>
    </aside>
  );
}
