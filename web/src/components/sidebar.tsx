"use client";

import {
  LayoutDashboard,
  Target,
  Building2,
  Users,
  Mail,
  Star,
  ArrowLeft,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { useCampaign } from "@/lib/campaign-context";

interface NavItem {
  href: string;
  icon: React.ReactNode;
  label: string;
}

function NavLink({ href, icon, label }: NavItem) {
  const pathname = usePathname();
  const isActive = pathname === href || pathname.startsWith(`${href}/`);

  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-3 rounded px-3 py-2 text-sm font-medium transition-colors",
        isActive
          ? "bg-muted text-foreground"
          : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
      )}
    >
      {icon}
      {label}
    </Link>
  );
}

const globalNav: NavItem[] = [
  { href: "/", icon: <LayoutDashboard className="h-4 w-4" />, label: "Dashboard" },
  { href: "/campaigns", icon: <Target className="h-4 w-4" />, label: "Campaigns" },
];

export function Sidebar() {
  const { campaign } = useCampaign();

  if (campaign) {
    const base = `/campaigns/${campaign.id}`;
    const campaignNav: NavItem[] = [
      { href: base, icon: <Target className="h-4 w-4" />, label: "Overview" },
      { href: `${base}/companies`, icon: <Building2 className="h-4 w-4" />, label: "Companies" },
      { href: `${base}/contacts`, icon: <Users className="h-4 w-4" />, label: "Contacts" },
      { href: `${base}/leads`, icon: <Star className="h-4 w-4" />, label: "Leads" },
      { href: `${base}/emails`, icon: <Mail className="h-4 w-4" />, label: "Emails" },
    ];

    return (
      <aside
        className="fixed inset-y-0 left-0 z-40 flex flex-col border-r border-border bg-background"
        style={{ width: 240 }}
      >
        <div
          className="flex shrink-0 items-center border-b border-border px-5 font-semibold tracking-tight"
          style={{ height: 56 }}
        >
          Clay Enrichment
        </div>

        <nav className="flex flex-1 flex-col gap-1 overflow-y-auto px-3 py-4">
          <Link
            href="/campaigns"
            className="mb-2 flex items-center gap-2 rounded px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Campaigns
          </Link>

          <p className="mb-3 truncate px-3 text-sm font-semibold text-foreground">
            {campaign.name}
          </p>

          {campaignNav.map((item) => (
            <NavLink key={item.href} {...item} />
          ))}
        </nav>
      </aside>
    );
  }

  return (
    <aside
      className="fixed inset-y-0 left-0 z-40 flex flex-col border-r border-border bg-background"
      style={{ width: 240 }}
    >
      <div
        className="flex shrink-0 items-center border-b border-border px-5 font-semibold tracking-tight"
        style={{ height: 56 }}
      >
        Clay Enrichment
      </div>

      <nav className="flex flex-1 flex-col gap-1 overflow-y-auto px-3 py-4">
        {globalNav.map((item) => (
          <NavLink key={item.href} {...item} />
        ))}
      </nav>
    </aside>
  );
}
