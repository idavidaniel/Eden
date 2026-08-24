"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, Play, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { keys } from "@/lib/hooks";
import { Board } from "@/components/work/board";
import { ItemDetail } from "@/components/work/item";
import { Badge, Button, ErrorNote, Mono, PageHeader, Panel, Skeleton } from "@/components/ui";
import { useToast } from "@/components/ui/toast";

export default function ProjectPage({
  params,
}: {
  params: Promise<{ companyId: string; projectId: string }>;
}) {
  const { companyId, projectId } = use(params);
  const search = useSearchParams();
  const [selected, setSelected] = useState<string | null>(search.get("item"));
  const client = useQueryClient();
  const toast = useToast();

  const project = useQuery({
    queryKey: keys.project(projectId),
    queryFn: () => api.projects.get(projectId),
  });
  const items = useQuery({
    queryKey: keys.workItems(projectId),
    queryFn: () => api.projects.workItems(projectId),
  });
  const people = useQuery({
    queryKey: keys.employees(companyId),
    queryFn: () => api.employees.list(companyId),
  });

  const start = useMutation({
    mutationFn: () => api.projects.start(projectId),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.project(projectId) });
      toast.show("ok", "Planning has started.");
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  if (project.error) return <ErrorNote error={project.error} retry={() => project.refetch()} />;

  return (
    <div className="space-y-5">
      <Link
        href={`/c/${companyId}/work`}
        className="inline-flex items-center gap-1.5 text-xs text-muted transition-colors hover:text-ink"
      >
        <ArrowLeft size={13} />
        All work
      </Link>

      <PageHeader
        eyebrow={project.data ? <Mono>{project.data.key}</Mono> : undefined}
        title={project.data?.name ?? <Skeleton className="h-6 w-48" />}
        hint={project.data?.brief}
        action={
          <>
            {project.data ? (
              <Badge tone={project.data.status === "done" ? "pass" : "neutral"}>
                {project.data.status.replace(/_/g, " ")}
              </Badge>
            ) : null}
            <Button
              size="sm"
              icon={<ShieldCheck size={13} />}
              onClick={() => toast.show("info", "Opening the proof page.")}
            >
              <Link href={`/c/${companyId}/ops?project=${projectId}`}>Prove it</Link>
            </Button>
            <Button
              variant="primary"
              size="sm"
              icon={<Play size={13} />}
              busy={start.isPending}
              onClick={() => start.mutate()}
            >
              {items.data?.length ? "Run again" : "Start"}
            </Button>
          </>
        }
      />

      <div className="grid gap-5 xl:grid-cols-[1fr_24rem]">
        <div className="min-w-0">
          {items.isLoading ? (
            <Skeleton className="h-64" />
          ) : (
            <Board
              projectId={projectId}
              items={items.data ?? []}
              people={people.data ?? []}
              selectedId={selected}
              onSelect={setSelected}
            />
          )}
        </div>

        <aside className="min-w-0 xl:sticky xl:top-[calc(var(--topbar)+1.5rem)] xl:max-h-[calc(100dvh-var(--topbar)-3rem)] xl:self-start xl:overflow-y-auto">
          {selected ? (
            <ItemDetail
              companyId={companyId}
              projectId={projectId}
              itemId={selected}
              people={people.data ?? []}
              onClose={() => setSelected(null)}
            />
          ) : (
            <Panel className="px-4 py-8 text-center">
              <p className="text-sm text-muted">Pick a card.</p>
              <p className="mt-1 text-xs text-faint">
                Everything about how a piece of work was verified lives here.
              </p>
            </Panel>
          )}
        </aside>
      </div>
    </div>
  );
}
