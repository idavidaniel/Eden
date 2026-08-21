"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { Project } from "@/lib/types";
import { Card, EmptyState, SectionTitle, Spinner } from "./ui";

/** Each project owns one git workspace; this is the way in. */
export default function WorkspacePicker({ companyId }: { companyId: string }) {
  const projects = useResource<Project[]>(() => api.projects.list(companyId), [companyId]);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-slate-100">Code</h1>
        <p className="text-sm text-slate-400">
          Every project has a real git repository. Employees commit to it under their own names.
        </p>
      </header>

      {projects.loading && <Spinner />}
      {projects.data?.length === 0 && (
        <EmptyState icon="💻" title="No workspaces yet" hint="Workspaces are created with projects." />
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {projects.data?.map((project) => (
          <Link key={project.id} href={`/companies/${companyId}/projects/${project.id}/code`}>
            <Card className="p-5">
              <SectionTitle>{project.key}</SectionTitle>
              <p className="font-medium text-slate-100">{project.name}</p>
              <p className="mt-1 line-clamp-2 text-sm text-slate-500">{project.brief}</p>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
