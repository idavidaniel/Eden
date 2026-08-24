"use client";

import Link from "next/link";
import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Banknote,
  BadgeCheck,
  Boxes,
  ListChecks,
  ShieldCheck,
  Users,
} from "lucide-react";
import { api } from "@/lib/api";
import { money, percent, timeAgo } from "@/lib/format";
import { keys, useLiveCompany } from "@/lib/hooks";
import { Feed } from "@/components/company/feed";
import { Stat, StatRow } from "@/components/company/stats";
import {
  Badge,
  Button,
  Dot,
  Empty,
  Mono,
  PageHeader,
  Panel,
  PanelHeader,
  Skeleton,
} from "@/components/ui";

export default function Overview({ params }: { params: Promise<{ companyId: string }> }) {
  const { companyId } = use(params);
  const { events } = useLiveCompany(companyId);

  const company = useQuery({
    queryKey: keys.company(companyId),
    queryFn: () => api.companies.get(companyId),
  });
  const ops = useQuery({ queryKey: keys.ops(companyId), queryFn: () => api.companies.ops(companyId) });
  const projects = useQuery({
    queryKey: keys.projects(companyId),
    queryFn: () => api.projects.list(companyId),
  });
  const employees = useQuery({
    queryKey: keys.employees(companyId),
    queryFn: () => api.employees.list(companyId),
  });
  const ledger = useQuery({
    queryKey: keys.ledger(companyId),
    queryFn: () => api.companies.ledger(companyId, 8),
  });

  const at = (path: string) => `/c/${companyId}${path}`;
  const working = (employees.data ?? []).filter((person) => person.status === "working");
  const stats = company.data?.stats ?? {};
  const verified = stats.checks_passed ?? 0;
  const attempted = (stats.checks_passed ?? 0) + (stats.checks_failed ?? 0);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={company.data?.pack_key.replace(/_/g, " ")}
        title={company.data?.name ?? <Skeleton className="h-6 w-48" />}
        hint={company.data?.tagline || company.data?.description}
        action={
          <Button variant="primary" icon={<ArrowRight size={14} />}>
            <Link href={at("/work")}>Go to the work</Link>
          </Button>
        }
      />

      <StatRow>
        <Stat
          icon={<Users size={11} />}
          label="On the payroll"
          value={employees.data?.length ?? "—"}
          hint={working.length ? `${working.length} working right now` : "Nobody is mid-turn"}
          href={at("/agents")}
        />
        <Stat
          icon={<ListChecks size={11} />}
          label="Open work"
          value={stats.open_work_items ?? "—"}
          hint={`${stats.done_work_items ?? 0} finished`}
          href={at("/work")}
        />
        <Stat
          icon={<BadgeCheck size={11} />}
          label="Checks passed"
          value={attempted ? percent(verified / attempted) : "—"}
          tone={attempted && verified / attempted < 0.6 ? "fail" : "pass"}
          hint={attempted ? `${verified} of ${attempted} runs` : "Nothing verified yet"}
          href={at("/ops")}
        />
        <Stat
          icon={<Banknote size={11} />}
          label="Spent today"
          value={money(ops.data?.spend?.today?.cost_micros ?? 0)}
          hint={`${money(ops.data?.spend?.month?.cost_micros ?? 0)} this month`}
          href={at("/ops")}
        />
      </StatRow>

      <div className="grid gap-5 lg:grid-cols-[1.25fr_1fr]">
        <div className="space-y-5">
          <Panel>
            <PanelHeader
              icon={<ListChecks size={14} />}
              title="Projects"
              hint="What the company has been asked to produce"
              action={
                <Link href={at("/work")} className="text-xs text-accent hover:underline">
                  All work
                </Link>
              }
            />
            {projects.isLoading ? (
              <div className="space-y-2 p-4">
                <Skeleton className="h-12" />
                <Skeleton className="h-12" />
              </div>
            ) : projects.data?.length ? (
              <ul className="divide-y divide-line">
                {projects.data.slice(0, 5).map((project) => (
                  <li key={project.id}>
                    <Link
                      href={at(`/work/${project.id}`)}
                      className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-sunken"
                    >
                      <Mono className="shrink-0 text-faint">{project.key}</Mono>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-ink">
                          {project.name}
                        </span>
                        <span className="block truncate text-xs text-muted">{project.brief}</span>
                      </span>
                      <Badge tone={project.status === "done" ? "pass" : "neutral"}>
                        {project.status.replace(/_/g, " ")}
                      </Badge>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <Empty icon={<ListChecks size={20} />} title="No projects yet">
                A project is a brief. The company plans it, does it, and has to prove it.
              </Empty>
            )}
          </Panel>

          <Panel>
            <PanelHeader
              icon={<ShieldCheck size={14} />}
              title="The record"
              hint="Every consequential act, hash-chained in order"
              action={
                <Link href={at("/ops")} className="text-xs text-accent hover:underline">
                  Verify it
                </Link>
              }
            />
            {ledger.data?.entries.length ? (
              <ol className="divide-y divide-line">
                {ledger.data.entries.slice(0, 6).map((entry) => (
                  <li key={entry.seq} className="flex items-center gap-3 px-4 py-2">
                    <span className="tnum w-8 shrink-0 font-mono text-xs text-faint">
                      {entry.height}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-mono text-xs text-ink">{entry.kind}</span>
                      <span className="block truncate text-xs text-muted">{entry.actor_label}</span>
                    </span>
                    <Mono className="shrink-0 text-faint">{entry.hash.slice(0, 8)}</Mono>
                  </li>
                ))}
              </ol>
            ) : (
              <Empty icon={<ShieldCheck size={20} />} title="The chain is empty">
                Nothing has been recorded yet.
              </Empty>
            )}
          </Panel>
        </div>

        <Panel className="lg:sticky lg:top-[calc(var(--topbar)+1.5rem)] lg:self-start">
          <PanelHeader
            icon={<Boxes size={14} />}
            title="Live"
            hint={
              working.length ? (
                <span className="flex items-center gap-1.5">
                  <Dot tone="accent" />
                  {working.map((person) => person.name.split(" ")[0]).join(", ")} working
                </span>
              ) : (
                `Last event ${timeAgo(events.at(-1)?.created_at)}`
              )
            }
          />
          <div className="max-h-[34rem] overflow-y-auto">
            <Feed events={events} companyId={companyId} limit={30} />
          </div>
        </Panel>
      </div>
    </div>
  );
}
