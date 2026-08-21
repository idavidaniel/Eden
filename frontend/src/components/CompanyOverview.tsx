"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { STATUS_TONES } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import type { Employee, Project } from "@/lib/types";
import { useCompany } from "./CompanyShell";
import { Avatar, Badge, Card, EmptyState, SectionTitle, StatTile } from "./ui";

export default function CompanyOverview({ companyId }: { companyId: string }) {
  const { company } = useCompany();
  const employees = useResource<Employee[]>(() => api.employees.list(companyId), [companyId], {
    intervalMs: 8000,
  });
  const projects = useResource<Project[]>(() => api.projects.list(companyId), [companyId], {
    intervalMs: 10000,
  });

  const working = employees.data?.filter((e) => e.status === "working") ?? [];

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-3xl font-bold text-slate-100">{company?.name}</h1>
        <p className="mt-1 max-w-3xl text-slate-400">
          {company?.description ?? "No description yet — add one in Settings so the team knows what they are building."}
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Employees" value={company?.stats.employees ?? 0} />
        <StatTile label="Projects" value={company?.stats.projects ?? 0} />
        <StatTile
          label="Tickets done"
          value={`${company?.stats.tickets_done ?? 0}/${company?.stats.tickets ?? 0}`}
        />
        <StatTile
          label="Working now"
          value={working.length}
          tone={working.length ? "text-amber-300" : "text-slate-100"}
        />
      </div>

      <section>
        <SectionTitle
          action={
            <Link href={`/companies/${companyId}/people`} className="text-xs text-blue-400 hover:underline">
              View all →
            </Link>
          }
        >
          Who is working right now
        </SectionTitle>
        {working.length === 0 ? (
          <Card className="px-4 py-6 text-sm text-slate-500">
            Everyone is idle. Start a run on a project and the team picks up tickets.
          </Card>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {working.map((employee) => (
              <Link key={employee.id} href={`/companies/${companyId}/people/${employee.id}`}>
                <Card className="flex items-center gap-3 p-4">
                  <Avatar emoji={employee.avatar} />
                  <div className="min-w-0">
                    <p className="truncate font-medium text-slate-200">{employee.name}</p>
                    <p className="truncate text-xs text-amber-300">{employee.status_note}</p>
                  </div>
                </Card>
              </Link>
            ))}
          </div>
        )}
      </section>

      <section>
        <SectionTitle
          action={
            <Link href={`/companies/${companyId}/projects`} className="text-xs text-blue-400 hover:underline">
              All projects →
            </Link>
          }
        >
          Projects
        </SectionTitle>
        {projects.data?.length === 0 ? (
          <EmptyState
            icon="📋"
            title="No projects yet"
            hint="A project is a brief plus a board. Create one and the manager breaks it into tickets."
            action={
              <Link
                href={`/companies/${companyId}/projects`}
                className="rounded-lg bg-gradient-to-r from-blue-600 to-violet-600 px-4 py-2 text-sm font-medium"
              >
                Create a project
              </Link>
            }
          />
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {projects.data?.map((project) => (
              <Link key={project.id} href={`/companies/${companyId}/projects/${project.id}`}>
                <Card className="h-full p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-semibold text-slate-100">{project.name}</p>
                      <p className="font-mono text-xs text-slate-500">{project.key}</p>
                    </div>
                    <Badge tone={STATUS_TONES[project.status] ?? STATUS_TONES.backlog}>
                      {project.status.replace("_", " ")}
                    </Badge>
                  </div>
                  <p className="mt-3 line-clamp-2 text-sm text-slate-400">{project.brief}</p>
                  <div className="mt-4 flex gap-4 border-t border-white/5 pt-3 text-xs text-slate-500">
                    <span>{project.counts.total ?? 0} tickets</span>
                    <span className="text-emerald-400">{project.counts.done ?? 0} done</span>
                    <span className="text-amber-400">{project.counts.in_progress ?? 0} in progress</span>
                  </div>
                </Card>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
