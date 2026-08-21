"use client";

import Link from "next/link";
import type { Employee } from "@/lib/types";
import { Avatar, Card } from "./ui";

/** Reporting lines, drawn from each employee's manager_id. */
export default function OrgChart({
  companyId,
  employees,
}: {
  companyId: string;
  employees: Employee[];
}) {
  const roots = employees.filter((e) => !e.manager_id || !employees.some((m) => m.id === e.manager_id));

  return (
    <div className="space-y-6">
      {roots.map((root) => (
        <Node key={root.id} companyId={companyId} employee={root} employees={employees} depth={0} />
      ))}
    </div>
  );
}

function Node({
  companyId,
  employee,
  employees,
  depth,
}: {
  companyId: string;
  employee: Employee;
  employees: Employee[];
  depth: number;
}) {
  const reports = employees.filter((e) => e.manager_id === employee.id);
  return (
    <div className={depth > 0 ? "ml-6 border-l border-white/10 pl-6" : ""}>
      <Link href={`/companies/${companyId}/people/${employee.id}`}>
        <Card className="mb-3 flex items-center gap-3 p-3">
          <Avatar emoji={employee.avatar} size="sm" />
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-slate-100">{employee.name}</p>
            <p className="truncate text-xs text-slate-500">{employee.title}</p>
          </div>
          {reports.length > 0 && (
            <span className="ml-auto text-xs text-slate-600">{reports.length} reports</span>
          )}
        </Card>
      </Link>
      {reports.map((report) => (
        <Node
          key={report.id}
          companyId={companyId}
          employee={report}
          employees={employees}
          depth={depth + 1}
        />
      ))}
    </div>
  );
}
