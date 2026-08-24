"use client";

import Link from "next/link";
import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FileWarning, History, ShieldCheck } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { api } from "@/lib/api";
import { bytes, timeAgo, when } from "@/lib/format";
import { keys } from "@/lib/hooks";
import {
  Badge,
  Empty,
  ErrorNote,
  Mono,
  PageHeader,
  Panel,
  PanelHeader,
  Skeleton,
} from "@/components/ui";
import { HashChip, ProvenanceRow, VerdictSummary } from "@/components/ui/provenance";

const INTEGRITY = {
  intact: {
    tone: "pass" as const,
    title: "These are the bytes that were checked",
    body: "The stored content still hashes to what the ledger recorded when this version was written.",
  },
  changed: {
    tone: "fail" as const,
    title: "This file is not what was checked",
    body: "The content on disk no longer hashes to what the ledger recorded. Any verdict below was reached against different bytes.",
  },
  missing: {
    tone: "fail" as const,
    title: "The content is gone",
    body: "The ledger records this version, but the stored bytes cannot be read.",
  },
};

export default function ArtifactPage({
  params,
}: {
  params: Promise<{ companyId: string; artifactId: string }>;
}) {
  const { companyId, artifactId } = use(params);

  const artifact = useQuery({
    queryKey: keys.artifact(artifactId),
    queryFn: () => api.artifacts.get(artifactId),
  });

  if (artifact.error) return <ErrorNote error={artifact.error} retry={() => artifact.refetch()} />;
  if (!artifact.data) return <Skeleton className="h-96" />;

  const row = artifact.data;
  const state = INTEGRITY[row.integrity.state as keyof typeof INTEGRITY] ?? INTEGRITY.missing;
  const isMarkdown = /\.(md|markdown)$/i.test(row.name);

  return (
    <div className="space-y-5">
      <Link
        href={`/c/${companyId}/artifacts`}
        className="inline-flex items-center gap-1.5 text-xs text-muted transition-colors hover:text-ink"
      >
        <ArrowLeft size={13} />
        All deliverables
      </Link>

      <PageHeader
        eyebrow={row.kind}
        title={row.title || row.name}
        hint={
          <span className="flex flex-wrap items-center gap-2">
            <Mono className="text-faint">{row.name}</Mono>
            <span>·</span>
            <span className="tnum">
              v{row.version} · {bytes(row.size_bytes)}
            </span>
            <span>·</span>
            <span>{timeAgo(row.updated_at)}</span>
          </span>
        }
        action={<HashChip hash={row.content_hash} />}
      />

      <div className="grid gap-5 lg:grid-cols-[1fr_22rem]">
        <Panel className="min-w-0 p-5">
          {row.content ? (
            isMarkdown ? (
              <div className="doc">
                <ReactMarkdown>{row.content}</ReactMarkdown>
              </div>
            ) : (
              <pre className="scroll-x font-mono text-xs whitespace-pre-wrap text-ink">
                {row.content}
              </pre>
            )
          ) : (
            <Empty icon={<FileWarning size={20} />} title="Nothing to show">
              This deliverable lives outside the blob store — in the repository, or behind a
              connector.
            </Empty>
          )}
        </Panel>

        <aside className="min-w-0 space-y-4">
          <Panel>
            <div
              className={
                state.tone === "pass"
                  ? "border-b border-line bg-pass-wash px-4 py-3"
                  : "border-b border-line bg-fail-wash px-4 py-3"
              }
            >
              <p
                className={
                  state.tone === "pass"
                    ? "text-sm font-medium text-pass"
                    : "text-sm font-medium text-fail"
                }
              >
                {state.title}
              </p>
              <p className="mt-1 text-xs text-ink">{state.body}</p>
            </div>
            <dl className="grid gap-x-3 gap-y-1.5 px-4 py-3 text-xs sm:grid-cols-[6rem_1fr]">
              <dt className="text-faint">Recorded</dt>
              <dd className="text-ink">{when(row.created_at)}</dd>
              <dt className="text-faint">Storage</dt>
              <dd className="text-ink">{row.storage}</dd>
              <dt className="text-faint">Locator</dt>
              <dd className="scroll-x">
                <Mono className="text-ink">{row.locator}</Mono>
              </dd>
              {row.work_item_id ? (
                <>
                  <dt className="text-faint">From</dt>
                  <dd>
                    <Link
                      href={`/c/${companyId}/work/${row.project_id}?item=${row.work_item_id}`}
                      className="text-accent hover:underline"
                    >
                      the work item that produced it
                    </Link>
                  </dd>
                </>
              ) : null}
            </dl>
          </Panel>

          <Panel>
            <PanelHeader
              icon={<ShieldCheck size={14} />}
              title="Checked"
              hint="Against this exact version"
            />
            <div className="border-b border-line px-3 py-2">
              <VerdictSummary results={row.checks} />
            </div>
            {row.checks.length ? (
              row.checks.map((result) => <ProvenanceRow key={result.id} result={result} />)
            ) : (
              <Empty title="Nothing has checked this">
                A deliverable nobody verified is a claim, not a result.
              </Empty>
            )}
          </Panel>

          {row.versions.length > 1 ? (
            <Panel>
              <PanelHeader icon={<History size={14} />} title="Versions" />
              <ul className="divide-y divide-line">
                {row.versions.map((version) => (
                  <li key={version.id}>
                    <Link
                      href={`/c/${companyId}/artifacts/${version.id}`}
                      className="flex items-center gap-2 px-3 py-2 transition-colors hover:bg-sunken"
                    >
                      <span className="tnum w-8 shrink-0 text-xs text-faint">v{version.version}</span>
                      <span className="min-w-0 flex-1 text-xs text-muted">
                        {timeAgo(version.created_at)} · {bytes(version.size_bytes)}
                      </span>
                      {version.id === row.id ? <Badge tone="accent">showing</Badge> : null}
                      <HashChip hash={version.content_hash} />
                    </Link>
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
