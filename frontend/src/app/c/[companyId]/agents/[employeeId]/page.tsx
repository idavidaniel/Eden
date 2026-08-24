"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";
import { EMPLOYEE_TONES, initials } from "@/lib/format";
import { keys } from "@/lib/hooks";
import { AgentBrain } from "@/components/agent/brain";
import { AgentConsole } from "@/components/agent/console";
import { AgentOverview } from "@/components/agent/overview";
import { AgentSettings } from "@/components/agent/settings";
import { AgentTools } from "@/components/agent/tools";
import { Badge, Dot, ErrorNote, Skeleton, Tabs } from "@/components/ui";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "console", label: "Console" },
  { key: "memory", label: "Memory" },
  { key: "tools", label: "Tools & API" },
  { key: "settings", label: "Settings" },
];

export default function AgentPage({
  params,
}: {
  params: Promise<{ companyId: string; employeeId: string }>;
}) {
  const { companyId, employeeId } = use(params);
  const [tab, setTab] = useState("overview");

  const card = useQuery({
    queryKey: keys.agent(employeeId),
    queryFn: () => api.agents.card(employeeId),
  });
  const employee = useQuery({
    queryKey: ["employee", employeeId],
    queryFn: () => api.employees.get(employeeId),
  });

  if (card.error) return <ErrorNote error={card.error} retry={() => card.refetch()} />;

  return (
    <div className="space-y-5">
      <Link
        href={`/c/${companyId}/agents`}
        className="inline-flex items-center gap-1.5 text-xs text-muted transition-colors hover:text-ink"
      >
        <ArrowLeft size={13} />
        All agents
      </Link>

      <header className="flex flex-wrap items-start gap-4">
        {card.data ? (
          <span className="grid size-12 shrink-0 place-items-center rounded-full bg-accent-wash text-sm font-semibold text-accent">
            {initials(card.data.name)}
          </span>
        ) : (
          <Skeleton className="size-12 rounded-full" />
        )}
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold tracking-tight text-ink">
            {card.data?.name ?? <Skeleton className="h-6 w-40" />}
          </h1>
          <p className="text-sm text-muted">
            {card.data?.title}
            {card.data?.department ? ` · ${card.data.department}` : null}
          </p>
        </div>
        {employee.data ? (
          <Badge tone={EMPLOYEE_TONES[employee.data.status] ?? "neutral"}>
            <Dot tone={EMPLOYEE_TONES[employee.data.status] ?? "neutral"} />
            {employee.data.status_note || employee.data.status}
          </Badge>
        ) : null}
      </header>

      <Tabs tabs={TABS} active={tab} onSelect={setTab} />

      {tab === "overview" ? (
        <AgentOverview companyId={companyId} employeeId={employeeId} />
      ) : tab === "console" ? (
        <AgentConsole companyId={companyId} employeeId={employeeId} />
      ) : tab === "memory" ? (
        <AgentBrain employeeId={employeeId} />
      ) : tab === "tools" ? (
        <AgentTools employeeId={employeeId} />
      ) : (
        <AgentSettings employeeId={employeeId} />
      )}
    </div>
  );
}
