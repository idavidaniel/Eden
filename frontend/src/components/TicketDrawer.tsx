"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { STATUS_LABELS, STATUS_TONES, timeAgo } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import type { Employee, Ticket, TicketStatus } from "@/lib/types";
import { Avatar, Badge, Button, Input, Modal, Select, Spinner } from "./ui";

const STATUSES: TicketStatus[] = ["backlog", "todo", "in_progress", "in_review", "done", "blocked"];

/** Ticket detail: description, criteria, who did what, and the agent's own log. */
export default function TicketDrawer({
  ticketId,
  employees,
  onClose,
  onChanged,
}: {
  ticketId: string | null;
  employees: Employee[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const [comment, setComment] = useState("");
  const ticket = useResource<Ticket>(
    () => (ticketId ? api.tickets.get(ticketId) : Promise.resolve(null as unknown as Ticket)),
    [ticketId],
  );

  const update = async (body: Record<string, unknown>) => {
    if (!ticketId) return;
    await api.tickets.update(ticketId, body);
    ticket.reload();
    onChanged();
  };

  const remove = async () => {
    if (!ticketId || !confirm(`Delete ${data?.key}? This cannot be undone.`)) return;
    await api.tickets.remove(ticketId);
    onChanged();
    onClose();
  };

  const send = async () => {
    if (!ticketId || !comment.trim()) return;
    await api.tickets.comment(ticketId, comment);
    setComment("");
    ticket.reload();
  };

  const data = ticket.data;
  const assignee = employees.find((employee) => employee.id === data?.assignee_id);

  return (
    <Modal open={Boolean(ticketId)} onClose={onClose} title={data ? `${data.key} · ${data.title}` : "Ticket"} wide>
      {ticket.loading && <Spinner />}
      {data && (
        <div className="grid gap-5">
          <div className="flex flex-wrap items-center gap-3">
            <Select
              className="w-40"
              value={data.status}
              onChange={(event) => update({ status: event.target.value })}
            >
              {STATUSES.map((status) => (
                <option key={status} value={status}>
                  {STATUS_LABELS[status]}
                </option>
              ))}
            </Select>
            <Select
              className="w-56"
              value={data.assignee_id ?? ""}
              onChange={(event) => update({ assignee_id: event.target.value || null })}
            >
              <option value="">Unassigned</option>
              {employees.map((employee) => (
                <option key={employee.id} value={employee.id}>
                  {employee.name} — {employee.title}
                </option>
              ))}
            </Select>
            <Badge tone={STATUS_TONES[data.status]}>{data.type}</Badge>
            {assignee && (
              <span className="flex items-center gap-2 text-sm text-slate-400">
                <Avatar emoji={assignee.avatar} size="sm" />
                {assignee.name}
              </span>
            )}
            <Button size="sm" variant="danger" className="ml-auto" onClick={remove}>
              Delete
            </Button>
          </div>

          <section>
            <h3 className="mb-1 text-xs tracking-wide text-slate-500 uppercase">Description</h3>
            <p className="text-sm whitespace-pre-wrap text-slate-300">
              {data.description || "No description."}
            </p>
          </section>

          {data.acceptance_criteria.length > 0 && (
            <section>
              <h3 className="mb-1 text-xs tracking-wide text-slate-500 uppercase">Acceptance criteria</h3>
              <ul className="list-inside list-disc space-y-1 text-sm text-slate-300">
                {data.acceptance_criteria.map((criterion) => (
                  <li key={criterion}>{criterion}</li>
                ))}
              </ul>
            </section>
          )}

          {data.result && (
            <section className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3">
              <h3 className="mb-1 text-xs tracking-wide text-emerald-400 uppercase">Reported result</h3>
              <p className="text-sm whitespace-pre-wrap text-slate-300">{data.result}</p>
            </section>
          )}

          {data.steps && data.steps.length > 0 && (
            <section>
              <h3 className="mb-2 text-xs tracking-wide text-slate-500 uppercase">Work log</h3>
              <div className="space-y-3">
                {data.steps.map((step) => (
                  <details key={step.id} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                    <summary className="cursor-pointer text-sm text-slate-300">
                      {step.kind} · {step.tool_calls.length} tool calls ·{" "}
                      {timeAgo(step.created_at)}
                      {step.status === "step_limit" && (
                        <span className="ml-2 text-amber-400">ran out of steps</span>
                      )}
                    </summary>
                    {step.output && (
                      <p className="mt-2 text-sm whitespace-pre-wrap text-slate-400">{step.output}</p>
                    )}
                    <ul className="mt-2 space-y-1">
                      {step.tool_calls.map((call, index) => (
                        <li key={index} className="font-mono text-xs text-slate-500">
                          <span className="text-blue-400">{call.name}</span>(
                          {Object.keys(call.arguments).join(", ")}) → {call.result.slice(0, 120)}
                        </li>
                      ))}
                    </ul>
                    {step.reasoning && (
                      <details className="mt-2">
                        <summary className="cursor-pointer text-xs text-slate-600">reasoning</summary>
                        <p className="mt-1 text-xs whitespace-pre-wrap text-slate-500">{step.reasoning}</p>
                      </details>
                    )}
                  </details>
                ))}
              </div>
            </section>
          )}

          <section>
            <h3 className="mb-2 text-xs tracking-wide text-slate-500 uppercase">Comments</h3>
            <div className="space-y-2">
              {(data.comments ?? []).map((entry) => (
                <div key={entry.id} className="rounded-lg border border-white/5 bg-white/[0.03] p-3">
                  <p className="text-xs text-slate-500">
                    {entry.author_label} · {timeAgo(entry.created_at)}
                  </p>
                  <p className="text-sm whitespace-pre-wrap text-slate-300">{entry.body}</p>
                </div>
              ))}
              {(data.comments ?? []).length === 0 && (
                <p className="text-sm text-slate-600">No comments yet.</p>
              )}
            </div>
            <div className="mt-3 flex gap-2">
              <Input
                value={comment}
                onChange={(event) => setComment(event.target.value)}
                onKeyDown={(event) => event.key === "Enter" && send()}
                placeholder="Leave a note for the team…"
              />
              <Button onClick={send}>Send</Button>
            </div>
          </section>
        </div>
      )}
    </Modal>
  );
}
