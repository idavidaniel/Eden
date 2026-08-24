"use client";

import { useQuery } from "@tanstack/react-query";
import { Banknote, Gauge, Quote, Wrench } from "lucide-react";
import { api } from "@/lib/api";
import { money, percent, timeAgo } from "@/lib/format";
import { keys } from "@/lib/hooks";
import { Stat, StatRow } from "@/components/company/stats";
import { Badge, Empty, Mono, Panel, PanelHeader, Skeleton } from "@/components/ui";

export function AgentOverview({
  companyId,
  employeeId,
}: {
  companyId: string;
  employeeId: string;
}) {
  const card = useQuery({ queryKey: keys.agent(employeeId), queryFn: () => api.agents.card(employeeId) });
  const usage = useQuery({
    queryKey: keys.agentUsage(employeeId),
    queryFn: () => api.agents.usage(employeeId),
  });
  const performance = useQuery({
    queryKey: ["performance", "employee", employeeId],
    queryFn: () => api.employees.performance(employeeId),
  });
  const tasks = useQuery({
    queryKey: keys.agentTasks(employeeId),
    queryFn: () => api.agents.tasks(employeeId),
  });

  return (
    <div className="space-y-5">
      <StatRow>
        <Stat
          icon={<Gauge size={11} />}
          label="Passed first time"
          value={percent(performance.data?.first_try_pass_rate)}
          tone={
            performance.data?.first_try_pass_rate == null
              ? "neutral"
              : performance.data.first_try_pass_rate >= 0.7
                ? "pass"
                : "pending"
          }
          hint={`over ${performance.data?.items_considered ?? 0} items`}
        />
        <Stat
          label="Sent back"
          value={percent(performance.data?.rework_rate)}
          tone={
            (performance.data?.rework_rate ?? 0) > 0.4 ? "fail" : "neutral"
          }
          hint="reopened after review"
        />
        <Stat
          icon={<Banknote size={11} />}
          label="Spent today"
          value={money(usage.data?.today.cost_micros)}
          tone={usage.data?.over_budget ? "fail" : "neutral"}
          hint={
            usage.data?.budget_daily_micros
              ? `cap ${money(usage.data.budget_daily_micros)}`
              : "no daily cap"
          }
        />
        <Stat
          label="Tokens per deliverable"
          value={
            performance.data?.tokens_per_artifact
              ? Math.round(performance.data.tokens_per_artifact).toLocaleString()
              : "—"
          }
          hint="prompt + completion"
        />
      </StatRow>

      {performance.data?.note ? (
        <p className="text-xs text-muted">{performance.data.note}</p>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel>
          <PanelHeader
            icon={<Quote size={14} />}
            title="Who they think they are"
            hint="The persona that goes into every system prompt"
          />
          <div className="px-4 py-3">
            {card.data ? (
              <p className="text-sm text-ink">{card.data.persona || "No persona written."}</p>
            ) : (
              <Skeleton className="h-16" />
            )}
            {card.data?.skills.length ? (
              <div className="mt-3 flex flex-wrap gap-1">
                {card.data.skills.map((skill) => (
                  <Badge key={skill}>{skill}</Badge>
                ))}
              </div>
            ) : null}
          </div>
        </Panel>

        <Panel>
          <PanelHeader
            icon={<Wrench size={14} />}
            title="Recent tasks"
            hint="Everything queued for or asked of this agent"
          />
          {tasks.data?.length ? (
            <ul className="divide-y divide-line">
              {tasks.data.slice(0, 8).map((task) => (
                <li key={task.id} className="flex items-center gap-3 px-4 py-2">
                  <Badge
                    tone={
                      task.status === "done"
                        ? "pass"
                        : task.status === "failed"
                          ? "fail"
                          : task.status === "running" || task.status === "leased"
                            ? "accent"
                            : "neutral"
                    }
                  >
                    {task.status}
                  </Badge>
                  <span className="min-w-0 flex-1">
                    <Mono className="block truncate text-ink">{task.kind}</Mono>
                    <span className="block truncate text-xs text-faint">
                      from {task.source} · {task.created_by}
                    </span>
                  </span>
                  <span className="shrink-0 text-xs text-faint">{timeAgo(task.created_at)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty title="Nothing has been asked of them yet">
              Use the console tab to give them something to do.
            </Empty>
          )}
        </Panel>
      </div>
      <p className="text-xs text-faint">
        Company{" "}
        <Mono>
          <a className="hover:text-accent" href={`/c/${companyId}`}>
            {card.data?.company.name}
          </a>
        </Mono>
      </p>
    </div>
  );
}
