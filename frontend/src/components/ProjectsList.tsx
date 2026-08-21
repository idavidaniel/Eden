"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import type { Project } from "@/lib/types";
import { Button, Card, EmptyState, ErrorNote, Field, Input, Modal, Spinner, Textarea } from "./ui";

export default function ProjectsList({ companyId }: { companyId: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const projects = useResource<Project[]>(() => api.projects.list(companyId), [companyId], {
    intervalMs: 10000,
  });

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Projects</h1>
          <p className="text-sm text-slate-400">
            Write a brief; the manager turns it into tickets and the team works them.
          </p>
        </div>
        <Button onClick={() => setOpen(true)}>+ New project</Button>
      </header>

      {projects.error && <ErrorNote>{projects.error}</ErrorNote>}
      {projects.loading && <Spinner />}

      {projects.data?.length === 0 && (
        <EmptyState
          icon="📋"
          title="No projects yet"
          hint="Describe what you want built. Be specific about the outcome — that is what gets decomposed."
          action={<Button onClick={() => setOpen(true)}>Create a project</Button>}
        />
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {projects.data?.map((project) => {
          const total = project.counts.total ?? 0;
          const done = project.counts.done ?? 0;
          return (
            <Link key={project.id} href={`/companies/${companyId}/projects/${project.id}`}>
              <Card className="h-full p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="font-semibold text-slate-100">{project.name}</h2>
                    <p className="font-mono text-xs text-slate-500">{project.key}</p>
                  </div>
                  <span className="text-xs text-slate-500">{timeAgo(project.created_at)}</span>
                </div>
                <p className="mt-3 line-clamp-3 text-sm text-slate-400">{project.brief || "No brief."}</p>

                <div className="mt-4">
                  <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-blue-500 to-emerald-500 transition-all"
                      style={{ width: `${total ? (done / total) * 100 : 0}%` }}
                    />
                  </div>
                  <div className="mt-2 flex justify-between text-xs text-slate-500">
                    <span>
                      {done}/{total} tickets done
                    </span>
                    <span className="capitalize">{project.status.replace("_", " ")}</span>
                  </div>
                </div>
              </Card>
            </Link>
          );
        })}
      </div>

      <NewProjectDialog
        open={open}
        companyId={companyId}
        onClose={() => setOpen(false)}
        onCreated={(project) => {
          setOpen(false);
          router.push(`/companies/${companyId}/projects/${project.id}`);
        }}
      />
    </div>
  );
}

function NewProjectDialog({
  open,
  companyId,
  onClose,
  onCreated,
}: {
  open: boolean;
  companyId: string;
  onClose: () => void;
  onCreated: (project: Project) => void;
}) {
  const [name, setName] = useState("");
  const [brief, setBrief] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!name.trim()) return setError("Give the project a name.");
    setSaving(true);
    setError("");
    try {
      onCreated(await api.projects.create(companyId, { name, brief }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="New project">
      <div className="grid gap-4">
        <Field label="Project name">
          <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="Panel Health CLI" />
        </Field>
        <Field
          label="Brief"
          hint="What should exist when this is done? Include constraints and how you will judge it."
        >
          <Textarea
            rows={6}
            value={brief}
            onChange={(event) => setBrief(event.target.value)}
            placeholder="Build a Python CLI that reads a CSV of panel readings and reports underperforming panels. Support a --threshold flag. Include a README and tests."
          />
        </Field>
        {error && <ErrorNote>{error}</ErrorNote>}
        <div className="flex justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={saving}>
            {saving ? "Creating…" : "Create project"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
