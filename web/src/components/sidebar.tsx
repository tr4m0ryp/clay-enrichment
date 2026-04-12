import {
  LayoutDashboard,
  Target,
  Building2,
  Users,
  Mail,
  Star,
} from "lucide-react";
import { NavLink } from "@/components/nav-link";

const navItems = [
  { href: "/", icon: <LayoutDashboard className="h-4 w-4" />, label: "Dashboard" },
  { href: "/campaigns", icon: <Target className="h-4 w-4" />, label: "Campaigns" },
  { href: "/companies", icon: <Building2 className="h-4 w-4" />, label: "Companies" },
  { href: "/contacts", icon: <Users className="h-4 w-4" />, label: "Contacts" },
  { href: "/emails", icon: <Mail className="h-4 w-4" />, label: "Emails" },
  { href: "/leads", icon: <Star className="h-4 w-4" />, label: "Leads" },
];

export function Sidebar() {
  return (
    <aside
      className="fixed inset-y-0 left-0 z-40 flex flex-col border-r border-border bg-background"
      style={{ width: 240 }}
    >
      {/* Brand */}
      <div
        className="flex shrink-0 items-center border-b border-border px-5 font-semibold tracking-tight"
        style={{ height: 56 }}
      >
        Clay Enrichment
      </div>

      {/* Navigation */}
      <nav className="flex flex-1 flex-col gap-1 overflow-y-auto px-3 py-4">
        {navItems.map((item) => (
          <NavLink key={item.href} {...item} />
        ))}
      </nav>
    </aside>
  );
}
