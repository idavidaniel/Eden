"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, MessageSquare, Play, ShieldCheck, X } from "lucide-react";
import { api } from "@/lib/api";
import { STATUS_LABELS, STATUS_TONES, bytes, timeAgo } from "@/lib/format";
import { keys } from "@/lib/hooks";
import type { Employee, WorkItem } from "@/lib/types";
import {
  Badge,
  Button,
  Empty,
  Mono,
  Panel,
  PanelHeader,
  Select,
  Skeleton,
  Textarea,
} from "@/components/ui";
import { HashChip, ProvenanceRow, VerdictSummary } from "@/components/ui/provenance";
import { useToast } from "@/components/ui/toast";

/**
 * One piece of work, and — the part that matters — the standard it is held to
 * and whether it met it. Checks are shown whether or not they have been run,
 * so "nothing has verified this" is visible rather than absent.
 */
export function ItemDetail({
  companyId,
  projectId,
  itemId,
  people,
  onClose,
}: {
  companyId: string;
  projectId: string;
  itemId: string;
  people: Employee[];
  onClose: () => void;
}) {
  const client = useQueryClient();
  const toast = useToast();
  const [comment, setComment] = useState("");

  const item = useQuery({
    queryKey: keys.workItem(itemId),
    queryFn: () => api.workItems.get(itemId),
  });
  const checks = useQuery({
    queryKey: keys.workItemChecks(itemId),
    queryFn: () => api.workItems.checks(itemId),
  });

  const invalidate = () => {
    client.invalidateQueries({ queryKey: keys.workItem(itemId) });
    client.invalidateQueries({ queryKey: keys.workItemChecks(itemId) });
    client.invalidateQueries({ queryKey: keys.workItems(projectId) });
  };

  const runChecks = useMutation({
    mutationFn: () => api.workItems.runChecks(itemId),
    onSuccess: (result) => {
      invalidate();
      const verdict = result.verdict as { ok?: boolean; summary?: string } | null;
      toast.show(verdict?.ok ? "ok" : "info", verdict?.summary ?? "Checks finished.");
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  const assign = useMutation({
    mutationFn: (assigneeId: string) =>
      api.workItems.update(itemId, { assignee_id: assigneeId || null }),
    onSuccess: invalidate,
    onError: (error: Error) => toast.show("error", error.message),
  });

  const say = useMutation({
    mutationFn: () => api.workItems.comment(itemId, comment),
    onSuccess: () => {
      setComment("");
      invalidate();
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  if (!item.data) return <Skeleton className="h-96" />;
  const row: WorkItem = item.data;
  const results = checks.data?.results ?? [];
  const unrun = (checks.data?.checks ?? []).filter(
    (check) => !results.some((result) => result.check_id === check.id),
  );

  return (
    <div className="space-y-4">
      <header className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Mono className="text-faint">{row.key}</Mono>
            <Badge tone={STATUS_TONES[row.status] ?? "neutral"}>
              {STATUS_LABELS[row.status] ?? row.status}
            </Badge>
            <Badge>{row.kind}</Badge>
            {row.rework_count > 0 ? (
              <Badge tone="pending">sent back {row.rework_count}×</Badge>
            ) : null}
          </div>
          <h2 className="mt-1 text-base font-semibold text-ink">{row.title}</h2>
        </div>
        <Button variant="quiet" size="sm" onClick={onClose} aria-label="Close">
          <X size={15} />
        </Button>
      </header>

      {row.blocked_reason ? (
        <div className="rounded-md border border-line bg-fail-wash px-3 py-2 text-sm text-fail">
          {row.blocked_reason}
        </div>
      ) : null}

      {row.description ? (
        <p className="text-sm whitespace-pre-wrap text-muted">{row.description}</p>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-xs text-muted">
          Assigned to
          <Select
            value={row.assignee_id ?? ""}
            onChange={(event) => assign.mutate(event.target.value)}
            className="h-7 w-48 py-0 text-xs"
          >
            <option value="">Nobody</option>
            {people.map((person) => (
              <option key={person.id} value={person.id}>
                {person.name} — {person.title}
              </option>
            ))}
          </Select>
        </label>
        {row.assignee_id ? (
          <Link
            href={`/c/${companyId}/agents/${row.assignee_id}`}
            className="text-xs text-accent hover:underline"
          >
            Open their console
          </Link>
        ) : null}
      </div>

      {row.acceptance_criteria.length ? (
        <div>
          <h3 className="mb-1 text-xs font-semibold text-ink">Done means</h3>
          <ul className="space-y-1">
            {row.acceptance_criteria.map((criterion, index) => (
              <li key={index} className="flex gap-2 text-sm text-muted">
                <span className="text-faint">—</span>
                {criterion}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <Panel>
        <PanelHeader
          icon={<ShieldCheck size={14} />}
          title="Verification"
          hint={
            results.length
              ? "What was checked, how, and what the evidence was"
              : "Nothing has verified this yet"
          }
          action={
            <Button
              size="sm"
              icon={<Play size={12} />}
              busy={runChecks.isPending}
              onClick={() => runChecks.mutate()}
            >
              Run checks
            </Button>
          }
        />
        <div className="border-b border-line px-3 py-2">
          <VerdictSummary results={results} />
        </div>
        {results.length ? (
          <div>
            {results.map((result) => (
              <ProvenanceRow key={result.id} result={result} />
            ))}
          </div>
        ) : null}
        {unrun.length ? (
          <div className="border-t border-line px-3 py-2">
            <p className="mb-1 text-xs text-faint">Not run yet</p>
            <div className="flex flex-wrap gap-1">
              {unrun.map((check) => (
                <Badge key={check.id} mono>
                  {check.key} · {check.kind}
                </Badge>
              ))}
            </div>
          </div>
        ) : null}
        {!results.length && !unrun.length ? (
          <Empty title="No checks apply to this yet">
            Checks come from the industry pack, the project, or the item&rsquo;s own deliverable
            spec.
          </Empty>
        ) : null}
      </Panel>

      <Panel>
        <PanelHeader icon={<Boxes size={14} />} title="Produced" />
        {checks.data?.artifacts.length ? (
          <ul className="divide-y divide-line">
            {checks.data.artifacts.map((artifact) => (
              <li key={artifact.id}>
                <Link
                  href={`/c/${companyId}/artifacts/${artifact.id}`}
                  className="flex items-center gap-3 px-3 py-2 transition-colors hover:bg-sunken"
                >
                  <span className="min-w-0 flex-1">
                    <Mono className="block truncate text-ink">{artifact.name}</Mono>
                    <span className="tnum block text-xs text-faint">
                      v{artifact.version} · {bytes(artifact.size_bytes)} ·{" "}
                      {timeAgo(artifact.updated_at)}
                    </span>
                  </span>
                  <HashChip hash={artifact.content_hash} />
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <Empty title="Nothing produced yet">
            A work item that finishes without a deliverable cannot be verified.
          </Empty>
        )}
      </Panel>

      <Panel>
        <PanelHeader icon={<MessageSquare size={14} />} title="Discussion" />
        {row.comments?.length ? (
          <ol className="divide-y divide-line">
            {row.comments.map((entry) => (
              <li key={entry.id} className="px-3 py-2">
                <div className="flex items-baseline gap-2">
                  <span className="text-xs font-medium text-ink">{entry.author_label}</span>
                  <span className="text-xs text-faint">{timeAgo(entry.created_at)}</span>
                </div>
                <p className="mt-0.5 text-sm whitespace-pre-wrap text-muted">{entry.body}</p>
              </li>
            ))}
          </ol>
        ) : null}
        <div className="border-t border-line p-3">
          <Textarea
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            placeholder="Add a note. Whoever picks this up will read it."
            className="min-h-16 text-sm"
          />
          <div className="mt-2 flex justify-end">
            <Button
              size="sm"
              variant="primary"
              disabled={!comment.trim()}
              busy={say.isPending}
              onClick={() => say.mutate()}
            >
              Comment
            </Button>
          </div>
        </div>
      </Panel>
    </div>
  );
}
