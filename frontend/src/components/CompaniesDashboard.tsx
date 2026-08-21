"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { Company, Role } from "@/lib/types";
import NewCompanyDialog from "./NewCompanyDialog";
import { Button, Card, EmptyState, ErrorNote, Spinner } from "./ui";

export default function CompaniesDashboard() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const companies = useResource<Company[]>(() => api.companies.list(), []);
  const roles = useResource<Role[]>(() => api.roles(), []);
  const health = useResource(() => api.health(), []);

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <header className="mb-10 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs tracking-[0.2em] text-slate-500 uppercase">Eden platform</p>
          <h1 className="mt-1 bg-gradient-to-r from-blue-300 via-violet-300 to-blue-300 bg-clip-text text-4xl font-bold text-transparent">
            Your companies
          </h1>
          <p className="mt-2 max-w-xl text-slate-400">
            Each company runs on its own team of AI employees. They get roles, credentials and
            tools, then work your projects together.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {health.data && (
            <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-slate-400">
              {health.data.llm_configured ? "🟢" : "🟡"} {health.data.model.split("/").pop()}
            </span>
          )}
          <Button onClick={() => setDialogOpen(true)}>+ New company</Button>
        </div>
      </header>

      {companies.error && <ErrorNote>{companies.error}</ErrorNote>}
      {companies.loading && <Spinner label="Loading companies…" />}

      {companies.data?.length === 0 && (
        <EmptyState
          icon="🏢"
          title="No companies yet"
          hint="Found one, describe what it does, and Eden hires a starting team for it."
          action={<Button onClick={() => setDialogOpen(true)}>Found a company</Button>}
        />
      )}

      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {companies.data?.map((company) => (
          <Link key={company.id} href={`/companies/${company.id}`}>
            <Card className="h-full p-5 transition-colors hover:border-white/25 hover:bg-slate-900/70">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold text-slate-100">{company.name}</h2>
                  <p className="text-sm text-slate-500">{company.industry ?? "Unspecified industry"}</p>
                </div>
                {company.stats.working_now > 0 && (
                  <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-xs text-amber-300">
                    {company.stats.working_now} working
                  </span>
                )}
              </div>
              <p className="mt-3 line-clamp-2 min-h-[2.5rem] text-sm text-slate-400">
                {company.tagline ?? company.description ?? "No description yet."}
              </p>
              <dl className="mt-4 grid grid-cols-3 gap-2 border-t border-white/5 pt-3 text-center">
                <div>
                  <dt className="text-xs text-slate-500">Employees</dt>
                  <dd className="text-lg font-semibold">{company.stats.employees}</dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Projects</dt>
                  <dd className="text-lg font-semibold">{company.stats.projects}</dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Tickets</dt>
                  <dd className="text-lg font-semibold">
                    {company.stats.tickets_done}/{company.stats.tickets}
                  </dd>
                </div>
              </dl>
            </Card>
          </Link>
        ))}
      </div>

      <NewCompanyDialog
        open={dialogOpen}
        roles={roles.data ?? []}
        onClose={() => setDialogOpen(false)}
        onCreated={() => {
          setDialogOpen(false);
          companies.reload();
        }}
      />
    </div>
  );
}
