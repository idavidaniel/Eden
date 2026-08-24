"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import {
  Banknote,
  Clock,
  Globe,
  Link2,
  ScrollText,
  ShieldCheck,
  Wrench,
  Zap,
} from "lucide-react";
import { api } from "@/lib/api";
import { money, timeAgo, when } from "@/lib/format";
import { keys } from "@/lib/hooks";
import type { ProofReport } from "@/lib/types";
import { Stat, StatRow } from "@/components/company/stats";
import {
  Badge,
  Button,
  Empty,
  Mono,
  PageHeader,
  Panel,
  PanelHeader,
  Row,
  Select,
  Skeleton,
  Table,
  Tabs,
  Td,
  Th,
  Toggle,
} from "@/components/ui";
import { HashChip, VerdictChip } from "@/components/ui/provenance";
import { useToast } from "@/components/ui/toast";

const TABS = [
  { key: "proof", label: "Proof" },
  { key: "ledger", label: "Ledger" },
  { key: "clock", label: "Clock" },
  { key: "spend", label: "Spend" },
  { key: "tools", label: "Tool calls" },
  { key: "sources", label: "Sources" },
];

export default function Ops({ params }: { params: Promise<{ companyId: string }> }) {
  const { companyId } = use(params);
  const search = useSearchParams();
  const [tab, setTab] = useState("proof");

  return (
    <div className="space-y-5">
      <PageHeader
        title="Proof & ops"
        hint="Whether the record still holds, what it cost, and what the company reached for."
      />
      <Tabs tabs={TABS} active={tab} onSelect={setTab} />

      {tab === "proof" ? (
        <Proof companyId={companyId} initialProject={search.get("project")} />
      ) : tab === "ledger" ? (
        <Ledger companyId={companyId} />
      ) : tab === "clock" ? (
        <ClockPanel companyId={companyId} />
      ) : tab === "spend" ? (
        <Spend companyId={companyId} />
      ) : tab === "tools" ? (
        <ToolCalls companyId={companyId} />
      ) : (
        <Sources companyId={companyId} />
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function Proof({ companyId, initialProject }: { companyId: string; initialProject: string | null }) {
  const toast = useToast();
  const [projectId, setProjectId] = useState(initialProject ?? "");
  const [report, setReport] = useState<ProofReport | null>(null);

  const projects = useQuery({
    queryKey: keys.projects(companyId),
    queryFn: () => api.projects.list(companyId),
  });

  const verify = useMutation({
    mutationFn: () => api.projects.verify(projectId),
    onSuccess: (result) => {
      setReport(result);
      toast.show(result.proved ? "ok" : "error", result.note);
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  return (
    <div className="space-y-4">
      <Panel>
        <PanelHeader
          icon={<ShieldCheck size={14} />}
          title="Re-prove a finished project"
          hint="Re-reads the chain, re-hashes every deliverable, and runs every deterministic check again."
          action={
            <div className="flex items-center gap-2">
              <Select
                value={projectId}
                onChange={(event) => setProjectId(event.target.value)}
                className="h-8 w-52 py-0 text-xs"
                aria-label="Project"
              >
                <option value="">Pick a project</option>
                {(projects.data ?? []).map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.key} — {project.name}
                  </option>
                ))}
              </Select>
              <Button
                size="sm"
                variant="primary"
                disabled={!projectId}
                busy={verify.isPending}
                onClick={() => verify.mutate()}
              >
                Verify
              </Button>
            </div>
          }
        />

        {report ? (
          <div className="space-y-4 p-4">
            {/* Three outcomes, not two: proved, disproved, and never checked.
                Collapsing the third into either of the others is the lie this
                page exists to prevent. */}
            <div
              className={
                report.proved
                  ? "rounded-md border border-line bg-pass-wash px-4 py-3"
                  : report.has_evidence
                    ? "rounded-md border border-line bg-fail-wash px-4 py-3"
                    : "rounded-md border border-line bg-pending-wash px-4 py-3"
              }
            >
              <p
                className={
                  report.proved
                    ? "text-sm font-semibold text-pass"
                    : report.has_evidence
                      ? "text-sm font-semibold text-fail"
                      : "text-sm font-semibold text-pending"
                }
              >
                {report.proved
                  ? "It still holds."
                  : report.has_evidence
                    ? "It no longer holds."
                    : "There is nothing to prove."}
              </p>
              <p className="mt-1 text-sm text-ink">{report.note}</p>
              <p className="mt-1 text-xs text-faint">Checked {when(report.checked_at)}</p>
            </div>

            <StatRow>
              <Stat
                label="Chain"
                value={report.chain.intact ? "Intact" : "Broken"}
                tone={report.chain.intact ? "pass" : "fail"}
                hint={`${report.chain.entries} entries`}
              />
              <Stat
                label="Deliverables intact"
                value={`${report.artifacts.intact}/${report.artifacts.total}`}
                tone={report.artifacts.intact === report.artifacts.total ? "pass" : "fail"}
                hint={
                  report.artifacts.not_in_ledger.length
                    ? `${report.artifacts.not_in_ledger.length} never recorded`
                    : "all recorded in the chain"
                }
              />
              <Stat
                label="Checks replayed"
                value={report.checks.replayed.length}
                tone={
                  report.checks.disagreements.length
                    ? "fail"
                    : report.has_evidence
                      ? "pass"
                      : "pending"
                }
                hint={
                  report.has_evidence
                    ? `${report.checks.disagreements.length} now disagree`
                    : "nothing has been checked"
                }
              />
              <Stat
                label="Could not replay"
                value={report.checks.skipped.length}
                tone="pending"
                hint="a model or a person decided"
              />
            </StatRow>

            {report.checks.disagreements.length ? (
              <Panel>
                <PanelHeader
                  title="These no longer agree with what was recorded"
                  hint="Either the deliverable changed, or the standard did."
                />
                <Table>
                  <thead>
                    <tr>
                      <Th>Check</Th>
                      <Th>Item</Th>
                      <Th>Then</Th>
                      <Th>Now</Th>
                      <Th>Detail</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.checks.disagreements.map((row, index) => (
                      <Row key={index}>
                        <Td>
                          <Mono>{row.check_key}</Mono>
                        </Td>
                        <Td className="text-muted">{row.work_item ?? "—"}</Td>
                        <Td>
                          <VerdictChip status={row.then as "pass"} />
                        </Td>
                        <Td>
                          <VerdictChip status={row.now as "fail"} />
                        </Td>
                        <Td className="max-w-sm text-xs text-muted">{row.detail}</Td>
                      </Row>
                    ))}
                  </tbody>
                </Table>
              </Panel>
            ) : null}

            {report.checks.skipped.length ? (
              <div>
                <h3 className="mb-1.5 text-xs font-semibold text-ink">
                  Reported as recorded, not replayed
                </h3>
                <ul className="space-y-1">
                  {report.checks.skipped.map((row, index) => (
                    <li key={index} className="flex flex-wrap items-center gap-2 text-xs">
                      <Mono className="text-ink">{row.check_key}</Mono>
                      <VerdictChip status={row.then as "pass"} />
                      <span className="text-muted">{row.reason}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <Link
              href={`/api/backend/projects/${projectId}/work-record`}
              target="_blank"
              className="inline-block text-xs text-accent hover:underline"
            >
              Download the work record as JSON
            </Link>
          </div>
        ) : (
          <Empty icon={<ShieldCheck size={22} />} title="Nothing verified in this session">
            Pick a project and verify it. This does not take the company&rsquo;s word for anything
            — it re-runs the evidence.
          </Empty>
        )}
      </Panel>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function Ledger({ companyId }: { companyId: string }) {
  const toast = useToast();
  const ledger = useQuery({
    queryKey: keys.ledger(companyId),
    queryFn: () => api.companies.ledger(companyId, 200),
  });
  const verify = useMutation({
    mutationFn: () => api.companies.verifyLedger(companyId),
    onSuccess: (result) =>
      toast.show(
        result.intact ? "ok" : "error",
        result.intact
          ? `All ${result.entries} entries recompute correctly.`
          : `Broken at height ${result.problems[0]?.height}: ${result.problems[0]?.problem}`,
      ),
    onError: (error: Error) => toast.show("error", error.message),
  });

  return (
    <Panel>
      <PanelHeader
        icon={<ScrollText size={14} />}
        title="The chain"
        hint="Each entry commits to the one before it, so nothing can be quietly rewritten."
        action={
          <Button size="sm" busy={verify.isPending} onClick={() => verify.mutate()}>
            Recompute every hash
          </Button>
        }
      />
      {ledger.isLoading ? (
        <Skeleton className="h-64 m-4" />
      ) : ledger.data?.entries.length ? (
        <Table>
          <thead>
            <tr>
              <Th align="right">Height</Th>
              <Th>Kind</Th>
              <Th>Actor</Th>
              <Th>Subject</Th>
              <Th>Hash</Th>
              <Th align="right">At</Th>
            </tr>
          </thead>
          <tbody>
            {ledger.data.entries.map((entry) => (
              <Row key={entry.seq}>
                <Td align="right" className="tnum text-faint">
                  {entry.height}
                </Td>
                <Td>
                  <Mono>{entry.kind}</Mono>
                </Td>
                <Td className="text-muted">{entry.actor_label}</Td>
                <Td className="text-muted">{entry.subject_kind ?? "—"}</Td>
                <Td>
                  <HashChip hash={entry.hash} />
                </Td>
                <Td align="right" className="text-muted">
                  {timeAgo(entry.at)}
                </Td>
              </Row>
            ))}
          </tbody>
        </Table>
      ) : (
        <Empty icon={<ScrollText size={22} />} title="The chain is empty" />
      )}
    </Panel>
  );
}

/* -------------------------------------------------------------------------- */

function ClockPanel({ companyId }: { companyId: string }) {
  const client = useQueryClient();
  const toast = useToast();

  const ops = useQuery({ queryKey: keys.ops(companyId), queryFn: () => api.companies.ops(companyId) });
  const autonomy = useMutation({
    mutationFn: (enabled: boolean) => api.companies.autonomy(companyId, enabled),
    onSuccess: (result) => {
      client.invalidateQueries({ queryKey: keys.ops(companyId) });
      toast.show(
        "info",
        result.autonomous
          ? "The clock will start work here on its own."
          : "The clock will leave this company alone.",
      );
    },
    onError: (error: Error) => toast.show("error", error.message),
  });
  const tick = useMutation({
    mutationFn: () => api.clock.tick(),
    onSuccess: (result) => {
      client.invalidateQueries({ queryKey: keys.ops(companyId) });
      toast.show(
        "info",
        `${result.created} queued, ${result.dispatched} started, ${result.reclaimed} reclaimed.`,
      );
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  const clock = ops.data?.clock;

  return (
    <div className="space-y-4">
      <StatRow>
        <Stat
          icon={<Clock size={11} />}
          label="Clock"
          value={clock?.running ? "Running" : "Stopped"}
          tone={clock?.running ? "pass" : "neutral"}
          hint={clock ? `every ${clock.tick_seconds}s` : undefined}
        />
        <Stat label="Ticks" value={clock?.ticks ?? "—"} hint={`last ${timeAgo(clock?.last_tick)}`} />
        <Stat label="Turns started" value={clock?.dispatched ?? "—"} />
        <Stat
          label="Leases reclaimed"
          value={clock?.reclaimed ?? "—"}
          tone={clock?.reclaimed ? "pending" : "neutral"}
          hint="workers that died mid-turn"
        />
      </StatRow>

      <Panel>
        <PanelHeader icon={<Zap size={14} />} title="Autonomy" />
        <div className="space-y-4 p-4">
          <Toggle
            checked={Boolean(ops.data?.autonomous)}
            onChange={(next) => autonomy.mutate(next)}
            label="Let this company work without being asked"
            hint="Off by default. On, the clock finds ready work and starts it — which spends money."
          />
          <div className="flex items-center justify-between border-t border-line pt-3">
            <p className="text-xs text-muted">Or drive one pass by hand, right now.</p>
            <Button size="sm" busy={tick.isPending} onClick={() => tick.mutate()}>
              Tick once
            </Button>
          </div>
          {clock?.last_error ? (
            <p className="rounded border border-line bg-fail-wash px-3 py-2 text-xs text-fail">
              Last error: {clock.last_error}
            </p>
          ) : null}
        </div>
      </Panel>

      {ops.data?.tasks ? (
        <Panel>
          <PanelHeader title="Task queue" />
          <div className="flex flex-wrap gap-2 p-4">
            {Object.entries(ops.data.tasks).map(([status, total]) => (
              <Badge key={status} tone={status === "failed" ? "fail" : "neutral"}>
                {status} <span className="tnum">{total}</span>
              </Badge>
            ))}
          </div>
        </Panel>
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function Spend({ companyId }: { companyId: string }) {
  const ops = useQuery({ queryKey: keys.ops(companyId), queryFn: () => api.companies.ops(companyId) });
  const performance = useQuery({
    queryKey: keys.performance(companyId),
    queryFn: () => api.companies.performance(companyId),
  });
  const spend = ops.data?.spend;

  return (
    <div className="space-y-4">
      <StatRow>
        <Stat
          icon={<Banknote size={11} />}
          label="Today"
          value={money(spend?.today.cost_micros)}
          hint={`${spend?.today.calls ?? 0} model calls`}
        />
        <Stat label="This month" value={money(spend?.month.cost_micros)} />
        <Stat label="All time" value={money(spend?.all_time.cost_micros)} />
        <Stat
          label="Tokens today"
          value={(
            (spend?.today.prompt_tokens ?? 0) + (spend?.today.completion_tokens ?? 0)
          ).toLocaleString()}
          hint="prompt + completion"
        />
      </StatRow>
      <p className="text-xs text-faint">
        {spend?.note ?? "Cost is an estimate from a configurable rate table; tokens are measured."}
      </p>

      <Panel>
        <PanelHeader title="How each agent is doing" hint="Read from finished work, not self-report." />
        {performance.data?.employees.length ? (
          <Table>
            <thead>
              <tr>
                <Th>Agent</Th>
                <Th align="right">Items</Th>
                <Th align="right">Passed first time</Th>
                <Th align="right">Sent back</Th>
                <Th align="right">Median hours</Th>
              </tr>
            </thead>
            <tbody>
              {performance.data.employees.map((row) => (
                <Row key={row.employee_id}>
                  <Td>{row.name}</Td>
                  <Td align="right" className="tnum text-muted">
                    {row.items_considered}
                  </Td>
                  <Td align="right" className="tnum">
                    {row.first_try_pass_rate == null
                      ? "—"
                      : `${Math.round(row.first_try_pass_rate * 100)}%`}
                  </Td>
                  <Td align="right" className="tnum">
                    {row.rework_rate == null ? "—" : `${Math.round(row.rework_rate * 100)}%`}
                  </Td>
                  <Td align="right" className="tnum text-muted">
                    {row.median_hours_to_done?.toFixed(1) ?? "—"}
                  </Td>
                </Row>
              ))}
            </tbody>
          </Table>
        ) : (
          <Empty title="Not enough finished work to judge anyone yet" />
        )}
      </Panel>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function ToolCalls({ companyId }: { companyId: string }) {
  const calls = useQuery({
    queryKey: keys.toolCalls(companyId),
    queryFn: () => api.companies.toolCalls(companyId, 200),
  });

  return (
    <Panel>
      <PanelHeader
        icon={<Wrench size={14} />}
        title="Every tool call"
        hint="Including the ones that were refused, and why."
      />
      {calls.data?.length ? (
        <Table>
          <thead>
            <tr>
              <Th>Tool</Th>
              <Th>Who</Th>
              <Th>Result</Th>
              <Th align="right">Took</Th>
              <Th align="right">When</Th>
            </tr>
          </thead>
          <tbody>
            {calls.data.map((call) => (
              <Row key={call.id}>
                <Td>
                  <Mono>{call.tool}</Mono>
                </Td>
                <Td className="text-muted">{call.employee_label}</Td>
                <Td>
                  {call.blocked_reason ? (
                    <span>
                      <Badge tone="fail">blocked</Badge>
                      <span className="mt-0.5 block max-w-md text-xs text-muted">
                        {call.blocked_reason}
                      </span>
                    </span>
                  ) : (
                    <span>
                      <Badge tone={call.ok ? "pass" : "fail"}>{call.ok ? "ok" : "failed"}</Badge>
                      <span className="mt-0.5 block max-w-md truncate text-xs text-faint">
                        {call.result_preview}
                      </span>
                    </span>
                  )}
                </Td>
                <Td align="right" className="tnum text-muted">
                  {call.duration_ms} ms
                </Td>
                <Td align="right" className="text-muted">
                  {timeAgo(call.created_at)}
                </Td>
              </Row>
            ))}
          </tbody>
        </Table>
      ) : (
        <Empty icon={<Wrench size={22} />} title="No tools have been used yet" />
      )}
    </Panel>
  );
}

/* -------------------------------------------------------------------------- */

function Sources({ companyId }: { companyId: string }) {
  const sources = useQuery({
    queryKey: keys.sources(companyId),
    queryFn: () => api.companies.sources(companyId, 200),
  });

  return (
    <Panel>
      <PanelHeader
        icon={<Globe size={14} />}
        title="Everything fetched from outside"
        hint="Kept so a citation can be resolved against the page it claims to come from."
      />
      {sources.data?.length ? (
        <ul className="divide-y divide-line">
          {sources.data.map((source) => (
            <li key={source.id} className="px-4 py-2.5">
              <div className="flex items-start gap-2">
                <Link2 size={13} className="mt-0.5 shrink-0 text-faint" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-ink">
                    {source.title || source.url}
                  </span>
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="block truncate text-xs text-accent hover:underline"
                  >
                    {source.url}
                  </a>
                </span>
                <HashChip hash={source.content_hash} label="content" />
                <span className="shrink-0 text-xs text-faint">{timeAgo(source.created_at)}</span>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <Empty icon={<Globe size={22} />} title="Nothing has been fetched">
          Agents cannot reach the internet until you allow a host under Connections.
        </Empty>
      )}
    </Panel>
  );
}
