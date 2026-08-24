"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderPlus, ListChecks, Play } from "lucide-react";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { keys } from "@/lib/hooks";
import {
  Badge,
  Button,
  Dialog,
  Empty,
  ErrorNote,
  Field,
  Input,
  Mono,
  PageHeader,
  Panel,
  Skeleton,
  Textarea,
} from "@/components/ui";
import { useToast } from "@/components/ui/toast";

export default function Work({ params }: { params: Promise<{ companyId: string }> }) {
  const { companyId } = use(params);
  const [starting, setStarting] = useState(false);

  const projects = useQuery({
    queryKey: keys.projects(companyId),
    queryFn: () => api.projects.list(companyId),
  });

  return (
    <div className="space-y-5">
      <PageHeader
        title="Work"
        hint="A project is a brief. The company plans it, does it, and has to prove it."
        action={
          <Button variant="primary" icon={<FolderPlus size={14} />} onClick={() => setStarting(true)}>
            New project
          </Button>
        }
      />

      {projects.error ? (
        <ErrorNote error={projects.error} retry={() => projects.refetch()} />
      ) : projects.isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
      ) : projects.data?.length ? (
        <ul className="space-y-3">
          {projects.data.map((project) => {
            const counts = project.counts ?? {};
            const total = counts.total ?? 0;
            const done = counts.done ?? 0;
            return (
              <li key={project.id}>
                <Link
                  href={`/c/${companyId}/work/${project.id}`}
                  className="block rounded-lg border border-line bg-surface p-4 transition-colors hover:border-line-strong hover:bg-sunken"
                >
                  <div className="flex flex-wrap items-start gap-3">
                    <Mono className="mt-0.5 shrink-0 text-faint">{project.key}</Mono>
                    <div className="min-w-0 flex-1">
                      <h2 className="text-sm font-semibold text-ink">{project.name}</h2>
                      <p className="mt-0.5 line-clamp-2 text-sm text-muted">{project.brief}</p>
                    </div>
                    <Badge tone={project.status === "done" ? "pass" : "neutral"}>
                      {project.status.replace(/_/g, " ")}
                    </Badge>
                  </div>

                  {total ? (
                    <div className="mt-3">
                      <div
                        className="h-1 overflow-hidden rounded-full bg-sunken"
                        role="progressbar"
                        aria-valuenow={done}
                        aria-valuemax={total}
                        aria-label={`${done} of ${total} items finished`}
                      >
                        <div
                          className="h-full rounded-full bg-pass"
                          style={{ width: `${Math.round((done / total) * 100)}%` }}
                        />
                      </div>
                      <p className="tnum mt-1.5 text-xs text-faint">
                        {done} of {total} finished
                        {counts.blocked ? ` · ${counts.blocked} blocked` : ""} ·{" "}
                        {timeAgo(project.created_at)}
                      </p>
                    </div>
                  ) : (
                    <p className="mt-3 text-xs text-faint">
                      Nothing planned yet · {timeAgo(project.created_at)}
                    </p>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      ) : (
        <Panel>
          <Empty
            icon={<ListChecks size={22} />}
            title="No projects yet"
            action={
              <Button variant="primary" onClick={() => setStarting(true)}>
                Write the first brief
              </Button>
            }
          >
            Describe what you want. The company breaks it into work, assigns it, and each piece
            has to pass its checks before it counts as done.
          </Empty>
        </Panel>
      )}

      <NewProject companyId={companyId} open={starting} onClose={() => setStarting(false)} />
    </div>
  );
}

function NewProject({
  companyId,
  open,
  onClose,
}: {
  companyId: string;
  open: boolean;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState("");
  const [brief, setBrief] = useState("");
  const [startNow, setStartNow] = useState(true);

  const create = useMutation({
    mutationFn: async () => {
      const project = await api.projects.create(companyId, { name, brief });
      if (startNow) await api.projects.start(project.id);
      return project;
    },
    onSuccess: (project) => {
      client.invalidateQueries({ queryKey: keys.projects(companyId) });
      toast.show("ok", startNow ? "Planning has started." : `${project.name} created.`);
      setName("");
      setBrief("");
      onClose();
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New project"
      hint="Say what you want, not how to build it. The plan is theirs to write."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            icon={startNow ? <Play size={13} /> : undefined}
            busy={create.isPending}
            disabled={!name.trim() || !brief.trim()}
            onClick={() => create.mutate()}
          >
            {startNow ? "Create and start" : "Create"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Name">
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Sensor Portal"
            autoFocus
          />
        </Field>
        <Field
          label="Brief"
          hint="What it is for, who uses it, and what would make it wrong. Detail here saves rework."
        >
          <Textarea
            value={brief}
            onChange={(event) => setBrief(event.target.value)}
            className="min-h-32"
            placeholder="A page that lists our sensors, shows the last reading for each, and flags any that have gone quiet for more than an hour."
          />
        </Field>
        <label className="flex cursor-pointer items-center gap-2 text-sm text-ink">
          <input
            type="checkbox"
            className="accent-[var(--accent)]"
            checked={startNow}
            onChange={(event) => setStartNow(event.target.checked)}
          />
          Start planning straight away
        </label>
      </div>
    </Dialog>
  );
}
