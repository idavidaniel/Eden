"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  Activity,
  BadgeCheck,
  Ban,
  Boxes,
  Code2,
  MessagesSquare,
  ScrollText,
  ShieldAlert,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { eventGroup, timeAgo } from "@/lib/format";
import type { ActivityEvent } from "@/lib/types";
import { Empty, cx } from "@/components/ui";

const GROUP_ICON: Record<string, LucideIcon> = {
  company: Activity,
  people: Users,
  work: BadgeCheck,
  code: Code2,
  verification: BadgeCheck,
  messages: MessagesSquare,
  knowledge: ScrollText,
  security: ShieldAlert,
  other: Activity,
};

/** Only failures get a colour. Everything else is the same weight as everything else. */
function toneFor(kind: string): string {
  if (/(failed|error|blocked|rejected|halted|exhausted)/.test(kind)) return "text-fail";
  if (/(passed|completed|done|approved|built)/.test(kind)) return "text-pass";
  return "text-faint";
}

export function Feed({
  events,
  companyId,
  limit = 40,
}: {
  events: ActivityEvent[];
  companyId: string;
  limit?: number;
}) {
  const [filter, setFilter] = useState<string>("all");

  const groups = useMemo(() => {
    const found = new Set(events.map((event) => eventGroup(event.kind)));
    return ["all", ...Array.from(found).sort()];
  }, [events]);

  const shown = useMemo(() => {
    const filtered =
      filter === "all" ? events : events.filter((event) => eventGroup(event.kind) === filter);
    return filtered.slice(-limit).reverse();
  }, [events, filter, limit]);

  if (!events.length) {
    return (
      <Empty icon={<Activity size={20} />} title="Nothing has happened yet">
        Start a project and this fills up as the work moves.
      </Empty>
    );
  }

  return (
    <div>
      {groups.length > 2 ? (
        <div className="scroll-x flex gap-1 border-b border-line px-3 py-2">
          {groups.map((group) => (
            <button
              key={group}
              type="button"
              onClick={() => setFilter(group)}
              className={cx(
                "rounded px-2 py-0.5 text-xs whitespace-nowrap transition-colors",
                filter === group ? "bg-sunken font-medium text-ink" : "text-muted hover:text-ink",
              )}
            >
              {group}
            </button>
          ))}
        </div>
      ) : null}

      <ol className="divide-y divide-line">
        {shown.map((event) => {
          const Icon = GROUP_ICON[eventGroup(event.kind)] ?? Activity;
          const target = linkFor(companyId, event);
          const body = (
            <>
              <Icon size={13} className={cx("mt-0.5 shrink-0", toneFor(event.kind))} />
              <span className="min-w-0 flex-1">
                <span className="block text-sm text-ink">{event.summary}</span>
                <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-faint">
                  <span>{event.actor}</span>
                  <span aria-hidden="true">·</span>
                  <span className="font-mono">{event.kind}</span>
                </span>
              </span>
              <span className="shrink-0 pt-0.5 text-xs whitespace-nowrap text-faint">
                {timeAgo(event.created_at)}
              </span>
            </>
          );
          return (
            <li key={event.seq}>
              {target ? (
                <Link href={target} className="flex gap-2.5 px-3 py-2.5 transition-colors hover:bg-sunken">
                  {body}
                </Link>
              ) : (
                <div className="flex gap-2.5 px-3 py-2.5">{body}</div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** An event that names something should take you to that something. */
function linkFor(companyId: string, event: ActivityEvent): string | null {
  const payload = event.payload ?? {};
  const at = (path: string) => `/c/${companyId}${path}`;
  const artifactId = payload.artifact_id;
  if (typeof artifactId === "string") return at(`/artifacts/${artifactId}`);
  const workItemId = payload.work_item_id ?? payload.ticket_id;
  if (typeof workItemId === "string" && event.project_id) {
    return at(`/work/${event.project_id}?item=${workItemId}`);
  }
  if (event.project_id) return at(`/work/${event.project_id}`);
  if (event.employee_id) return at(`/agents/${event.employee_id}`);
  return null;
}

export const FEED_ICONS = { Boxes, Ban };
