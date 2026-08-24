"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Inbox as InboxIcon, X } from "lucide-react";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { keys } from "@/lib/hooks";
import type { Approval } from "@/lib/types";
import {
  Badge,
  Button,
  Empty,
  ErrorNote,
  Input,
  Mono,
  PageHeader,
  Panel,
  PanelHeader,
  Skeleton,
} from "@/components/ui";
import { useToast } from "@/components/ui/toast";

export default function InboxPage({ params }: { params: Promise<{ companyId: string }> }) {
  const { companyId } = use(params);

  const inbox = useQuery({
    queryKey: keys.inbox(companyId),
    queryFn: () => api.companies.inbox(companyId),
  });

  if (inbox.error) return <ErrorNote error={inbox.error} retry={() => inbox.refetch()} />;

  const approvals = inbox.data?.approvals ?? [];
  const blocked = inbox.data?.blocked_items ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Inbox"
        hint="Everything the company has stopped and handed to you, because it could not decide."
      />

      {inbox.isLoading ? (
        <Skeleton className="h-48" />
      ) : approvals.length || blocked.length ? (
        <div className="space-y-5">
          {approvals.length ? (
            <Panel>
              <PanelHeader
                title="Waiting on your decision"
                hint="Answer and whatever was blocked starts moving again."
              />
              <ul className="divide-y divide-line">
                {approvals.map((approval) => (
                  <ApprovalRow key={approval.id} companyId={companyId} approval={approval} />
                ))}
              </ul>
            </Panel>
          ) : null}

          {blocked.length ? (
            <Panel>
              <PanelHeader
                title="Blocked work"
                hint="Stopped for a reason that is not a pending approval."
              />
              <ul className="divide-y divide-line">
                {blocked.map((item) => (
                  <li key={item.id} className="px-4 py-3">
                    <Link
                      href={`/c/${companyId}/work/${item.project_id}?item=${item.id}`}
                      className="group"
                    >
                      <div className="flex items-center gap-2">
                        <Mono className="text-faint">{item.key}</Mono>
                        <span className="text-sm text-ink group-hover:underline">{item.title}</span>
                      </div>
                      {item.blocked_reason ? (
                        <p className="mt-1 text-sm text-fail">{item.blocked_reason}</p>
                      ) : null}
                    </Link>
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}
        </div>
      ) : (
        <Panel>
          <Empty icon={<InboxIcon size={22} />} title="Nothing needs you">
            When an agent hits a decision it should not make on its own — an ambiguous brief, an
            irreversible action, a check that needs a person — it stops and asks here.
          </Empty>
        </Panel>
      )}
    </div>
  );
}

function ApprovalRow({ companyId, approval }: { companyId: string; approval: Approval }) {
  const client = useQueryClient();
  const toast = useToast();
  const [note, setNote] = useState("");

  const decide = useMutation({
    mutationFn: (approved: boolean) => api.approvals.decide(approval.id, approved, note),
    onSuccess: (result) => {
      client.invalidateQueries({ queryKey: keys.inbox(companyId) });
      client.invalidateQueries({ queryKey: keys.ledger(companyId) });
      toast.show("ok", `Recorded as ${result.status}. The chain has it.`);
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="pending">{approval.subject_kind}</Badge>
        <span className="text-xs text-muted">{approval.requested_label}</span>
        <span className="text-xs text-faint">{timeAgo(approval.created_at)}</span>
      </div>

      <p className="mt-1.5 text-sm font-medium text-ink">{approval.title}</p>
      {approval.reason ? <p className="mt-1 text-sm text-muted">{approval.reason}</p> : null}

      {approval.work_item_id && approval.project_id ? (
        <Link
          href={`/c/${companyId}/work/${approval.project_id}?item=${approval.work_item_id}`}
          className="mt-1.5 inline-block text-xs text-accent hover:underline"
        >
          See the work this is holding up
        </Link>
      ) : null}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Input
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Your answer, in your words — they read this."
          className="min-w-48 flex-1"
        />
        <Button
          size="sm"
          variant="primary"
          icon={<Check size={13} />}
          busy={decide.isPending}
          onClick={() => decide.mutate(true)}
        >
          Approve
        </Button>
        <Button
          size="sm"
          variant="danger"
          icon={<X size={13} />}
          busy={decide.isPending}
          onClick={() => decide.mutate(false)}
        >
          Refuse
        </Button>
      </div>
    </li>
  );
}
