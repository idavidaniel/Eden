"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { Employee, Role } from "@/lib/types";
import HireDialog from "./HireDialog";
import OrgChart from "./OrgChart";
import { Avatar, Badge, Button, Card, EmptyState, SectionTitle, Spinner } from "./ui";

export default function PeopleDirectory({ companyId }: { companyId: string }) {
  const [hiring, setHiring] = useState(false);
  const [view, setView] = useState<"grid" | "org">("grid");
  const employees = useResource<Employee[]>(() => api.employees.list(companyId), [companyId], {
    intervalMs: 8000,
  });
  const roles = useResource<Role[]>(() => api.roles(), []);

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">People</h1>
          <p className="text-sm text-slate-400">
            Every employee has a role, a toolbelt and their own service accounts.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border border-white/10 p-0.5">
            {(["grid", "org"] as const).map((mode) => (
              <button
                key={mode}
                onClick={() => setView(mode)}
                className={`rounded-md px-3 py-1.5 text-xs capitalize ${
                  view === mode ? "bg-white/10 text-white" : "text-slate-400"
                }`}
              >
                {mode === "grid" ? "Roster" : "Org chart"}
              </button>
            ))}
          </div>
          <Button onClick={() => setHiring(true)}>+ Hire</Button>
        </div>
      </header>

      {employees.loading && <Spinner />}

      {employees.data?.length === 0 && (
        <EmptyState
          icon="🧑‍💼"
          title="Nobody works here yet"
          hint="Hire your first AI employee — they are issued credentials and a workspace automatically."
          action={<Button onClick={() => setHiring(true)}>Hire someone</Button>}
        />
      )}

      {view === "org" && employees.data && employees.data.length > 0 && (
        <OrgChart companyId={companyId} employees={employees.data} />
      )}

      {view === "grid" &&
        Object.entries(groupByDepartment(employees.data ?? [])).map(([department, people]) => (
          <section key={department}>
            <SectionTitle>{department}</SectionTitle>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {people.map((employee) => (
                <Link key={employee.id} href={`/companies/${companyId}/people/${employee.id}`}>
                  <Card className="h-full p-4">
                    <div className="flex items-start gap-3">
                      <Avatar emoji={employee.avatar} />
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-medium text-slate-100">{employee.name}</p>
                        <p className="truncate text-sm text-slate-400">{employee.title}</p>
                        <p className="mt-1 text-xs text-slate-500">{employee.seniority}</p>
                      </div>
                      <StatusDot status={employee.status} />
                    </div>
                    {employee.status_note && (
                      <p className="mt-3 truncate text-xs text-amber-300">⚡ {employee.status_note}</p>
                    )}
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {employee.toolbelt.map((tool) => (
                        <Badge key={tool}>{tool}</Badge>
                      ))}
                    </div>
                  </Card>
                </Link>
              ))}
            </div>
          </section>
        ))}

      <HireDialog
        open={hiring}
        companyId={companyId}
        roles={roles.data ?? []}
        employees={employees.data ?? []}
        onClose={() => setHiring(false)}
        onHired={() => {
          setHiring(false);
          employees.reload();
        }}
      />
    </div>
  );
}

function groupByDepartment(employees: Employee[]): Record<string, Employee[]> {
  return employees.reduce<Record<string, Employee[]>>((groups, employee) => {
    (groups[employee.department] ??= []).push(employee);
    return groups;
  }, {});
}

export function StatusDot({ status }: { status: string }) {
  const tone = status === "working" ? "bg-amber-400" : "bg-slate-600";
  return (
    <span className="flex items-center gap-1.5 text-xs text-slate-500">
      <span className={`h-2 w-2 rounded-full ${tone}`} />
      {status}
    </span>
  );
}
