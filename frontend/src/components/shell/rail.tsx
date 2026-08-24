"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Boxes,
  FlaskConical,
  Inbox,
  ListChecks,
  MessagesSquare,
  Network,
  Plug,
  ScrollText,
  Settings,
  ShieldCheck,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cx } from "@/components/ui";

interface Item {
  href: string;
  label: string;
  icon: LucideIcon;
  hint: string;
}

/**
 * Grouped by the question each page answers, not by which table it reads.
 * "Who is here", "what is being made", "can I believe it", "what needs me".
 */
export function railFor(companyId: string): { group: string; items: Item[] }[] {
  const at = (path: string) => `/c/${companyId}${path}`;
  return [
    {
      group: "The company",
      items: [
        { href: at(""), label: "Overview", icon: Network, hint: "What happened, and what it cost" },
        { href: at("/agents"), label: "Agents", icon: Users, hint: "Everyone, and their API" },
        { href: at("/rooms"), label: "Rooms", icon: MessagesSquare, hint: "Channels and meetings" },
      ],
    },
    {
      group: "The work",
      items: [
        { href: at("/work"), label: "Work", icon: ListChecks, hint: "Projects and their items" },
        { href: at("/artifacts"), label: "Deliverables", icon: Boxes, hint: "What was produced" },
        { href: at("/studio"), label: "Studio", icon: FlaskConical, hint: "Files, commits, preview" },
        { href: at("/knowledge"), label: "Knowledge", icon: ScrollText, hint: "Documents and memory" },
      ],
    },
    {
      group: "You",
      items: [
        { href: at("/inbox"), label: "Inbox", icon: Inbox, hint: "Decisions waiting on you" },
        { href: at("/ops"), label: "Proof & ops", icon: ShieldCheck, hint: "The ledger and the clock" },
        { href: at("/connections"), label: "Connections", icon: Plug, hint: "What agents can reach" },
        { href: at("/settings"), label: "Settings", icon: Settings, hint: "Industry, handbook, halt" },
      ],
    },
  ];
}

export function Rail({ companyId, badges }: { companyId: string; badges?: Record<string, number> }) {
  const pathname = usePathname();
  const groups = railFor(companyId);
  const home = `/c/${companyId}`;

  return (
    <nav aria-label="Company" className="flex flex-col gap-5 px-3 py-4">
      {groups.map((group) => (
        <div key={group.group}>
          <p className="mb-1 px-2 text-[0.65rem] font-semibold tracking-[0.1em] text-faint uppercase">
            {group.group}
          </p>
          <ul className="space-y-0.5">
            {group.items.map((item) => {
              const active =
                item.href === home ? pathname === home : pathname.startsWith(item.href);
              const badge = badges?.[item.label];
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    title={item.hint}
                    aria-current={active ? "page" : undefined}
                    className={cx(
                      "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors",
                      active
                        ? "bg-accent-wash font-medium text-accent"
                        : "text-muted hover:bg-sunken hover:text-ink",
                    )}
                  >
                    <item.icon size={15} className="shrink-0" />
                    <span className="flex-1 truncate">{item.label}</span>
                    {badge ? (
                      <span className="tnum rounded-full bg-pending-wash px-1.5 text-[0.7rem] font-medium text-pending">
                        {badge}
                      </span>
                    ) : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
