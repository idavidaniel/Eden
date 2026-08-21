"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import { STATUS_LABELS, STATUS_TONES } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import type { Employee, ProjectDetail, Ticket, TicketStatus } from "@/lib/types";
import RunPanel from "./RunPanel";
import TicketDrawer from "./TicketDrawer";
import { Avatar, Badge, Button, Card, EmptyState, ErrorNote, Field, Input, Modal, Spinner, Textarea } from "./ui";

const COLUMNS: TicketStatus[] = ["backlog", "todo", "in_progress", "in_review", "done"];

export default function ProjectBoard({
  companyId,
  projectId,
}: {
  companyId: string;
  projectId: string;
}) {
  const [openTicket, setOpenTicket] = useState<string | null>(null);
  const [composing, setComposing] = useState(false);
  const [dragging, setDragging] = useState<string | null>(null);

  const project = useResource<ProjectDetail>(() => api.projects.get(projectId), [projectId], {
    intervalMs: 5000,
  });
  const tickets = useResource<Ticket[]>(() => api.projects.tickets(projectId), [projectId], {
    intervalMs: 4000,
  });
  const employees = useResource<Employee[]>(() => api.employees.list(companyId), [companyId], {
    intervalMs: 15000,
  });

  const peopleById = new Map((employees.data ?? []).map((employee) => [employee.id, employee]));

  const move = useCallback(
    async (ticketId: string, status: TicketStatus) => {
      tickets.setData(
        (current) =>
          current?.map((ticket) => (ticket.id === ticketId ? { ...ticket, status } : ticket)) ?? null,
      );
      await api.tickets.update(ticketId, { status });
      tickets.reload();
      project.reload();
    },
    [project, tickets],
  );

  if (project.loading) return <Spinner />;
  if (project.error) return <ErrorNote>{project.error}</ErrorNote>;
  if (!project.data) return null;

  const blocked = (tickets.data ?? []).filter((ticket) => ticket.status === "blocked");

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link href={`/companies/${companyId}/projects`} className="text-xs text-slate-500 hover:text-slate-300">
            ← Projects
          </Link>
          <h1 className="mt-1 text-2xl font-bold text-slate-100">{project.data.name}</h1>
          <p className="font-mono text-xs text-slate-500">{project.data.key}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link href={`/companies/${companyId}/projects/${projectId}/code`}>
            <Button variant="subtle" size="sm">
              💻 Workspace
            </Button>
          </Link>
          <Button variant="subtle" size="sm" onClick={() => setComposing(true)}>
            + Ticket
          </Button>
        </div>
      </header>

      <RunPanel
        project={project.data}
        onChanged={() => {
          project.reload();
          tickets.reload();
        }}
      />

      {blocked.length > 0 && (
        <Card className="border-rose-500/30 bg-rose-500/5 p-4">
          <p className="text-sm text-rose-300">
            {blocked.length} blocked ticket{blocked.length > 1 ? "s" : ""}:{" "}
            {blocked.map((ticket) => ticket.key).join(", ")}
          </p>
        </Card>
      )}

      {tickets.data?.length === 0 ? (
        <EmptyState
          icon="🎫"
          title="The board is empty"
          hint="Start a run and the manager fills it, or add a ticket yourself."
          action={<Button onClick={() => setComposing(true)}>Add a ticket</Button>}
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          {COLUMNS.map((status) => {
            const column = (tickets.data ?? []).filter((ticket) => ticket.status === status);
            return (
              <div
                key={status}
                onDragOver={(event) => event.preventDefault()}
                onDrop={() => {
                  if (dragging) move(dragging, status);
                  setDragging(null);
                }}
                className="flex min-h-[8rem] flex-col gap-2 rounded-2xl border border-white/5 bg-white/[0.02] p-2"
              >
                <div className="flex items-center justify-between px-2 py-1">
                  <h2 className="text-xs font-semibold tracking-wide text-slate-400 uppercase">
                    {STATUS_LABELS[status]}
                  </h2>
                  <span className="text-xs text-slate-600">{column.length}</span>
                </div>

                {column.map((ticket) => {
                  const assignee = ticket.assignee_id ? peopleById.get(ticket.assignee_id) : undefined;
                  return (
                    <article
                      key={ticket.id}
                      draggable
                      onDragStart={() => setDragging(ticket.id)}
                      onDragEnd={() => setDragging(null)}
                      onClick={() => setOpenTicket(ticket.id)}
                      className={`cursor-pointer rounded-xl border border-white/10 bg-slate-900/80 p-3 transition-colors hover:border-white/25 ${
                        dragging === ticket.id ? "opacity-40" : ""
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono text-[11px] text-slate-500">{ticket.key}</span>
                        {ticket.priority === "high" && (
                          <span className="text-[11px] text-rose-400">high</span>
                        )}
                      </div>
                      <p className="mt-1 line-clamp-3 text-sm text-slate-200">{ticket.title}</p>
                      <div className="mt-3 flex items-center justify-between">
                        <Badge tone={STATUS_TONES[ticket.status]}>{ticket.type}</Badge>
                        {assignee ? (
                          <span className="flex items-center gap-1.5 text-xs text-slate-400">
                            <Avatar emoji={assignee.avatar} size="sm" />
                            {assignee.name.split(" ")[0]}
                          </span>
                        ) : (
                          <span className="text-xs text-slate-600">unassigned</span>
                        )}
                      </div>
                    </article>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}

      <TicketDrawer
        ticketId={openTicket}
        employees={employees.data ?? []}
        onClose={() => setOpenTicket(null)}
        onChanged={() => {
          tickets.reload();
          project.reload();
        }}
      />

      <NewTicketDialog
        open={composing}
        projectId={projectId}
        employees={employees.data ?? []}
        onClose={() => setComposing(false)}
        onCreated={() => {
          setComposing(false);
          tickets.reload();
          project.reload();
        }}
      />
    </div>
  );
}

function NewTicketDialog({
  open,
  projectId,
  employees,
  onClose,
  onCreated,
}: {
  open: boolean;
  projectId: string;
  employees: Employee[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [form, setForm] = useState({ title: "", description: "", assignee_id: "", criteria: "" });
  const [error, setError] = useState("");

  const submit = async () => {
    if (!form.title.trim()) return setError("A ticket needs a title.");
    try {
      await api.projects.createTicket(projectId, {
        title: form.title,
        description: form.description,
        assignee_id: form.assignee_id || null,
        status: "todo",
        acceptance_criteria: form.criteria
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean),
      });
      setForm({ title: "", description: "", assignee_id: "", criteria: "" });
      onCreated();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="New ticket">
      <div className="grid gap-4">
        <Field label="Title">
          <Input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} />
        </Field>
        <Field label="Description">
          <Textarea
            rows={4}
            value={form.description}
            onChange={(event) => setForm({ ...form, description: event.target.value })}
          />
        </Field>
        <Field label="Acceptance criteria" hint="One per line — QA checks against these.">
          <Textarea
            rows={3}
            value={form.criteria}
            onChange={(event) => setForm({ ...form, criteria: event.target.value })}
          />
        </Field>
        <Field label="Assign to">
          <select
            className="w-full rounded-lg border border-slate-700 bg-slate-950/70 px-3 py-2 text-sm"
            value={form.assignee_id}
            onChange={(event) => setForm({ ...form, assignee_id: event.target.value })}
          >
            <option value="">Unassigned</option>
            {employees.map((employee) => (
              <option key={employee.id} value={employee.id}>
                {employee.name} — {employee.title}
              </option>
            ))}
          </select>
        </Field>
        {error && <ErrorNote>{error}</ErrorNote>}
        <div className="flex justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={submit}>Create ticket</Button>
        </div>
      </div>
    </Modal>
  );
}
