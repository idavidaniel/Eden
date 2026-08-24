"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GraduationCap, SlidersHorizontal } from "lucide-react";
import { api } from "@/lib/api";
import { money } from "@/lib/format";
import { keys } from "@/lib/hooks";
import type { Employee } from "@/lib/types";
import {
  Badge,
  Button,
  Empty,
  Field,
  Input,
  Panel,
  PanelHeader,
  Select,
  Skeleton,
  Textarea,
  Toggle,
} from "@/components/ui";
import { useToast } from "@/components/ui/toast";

const AUTONOMY = [
  { key: "supervised", label: "Supervised", hint: "Ask before anything irreversible." },
  { key: "normal", label: "Normal", hint: "Work alone, escalate when stuck." },
  { key: "trusted", label: "Trusted", hint: "Fewer approvals, more rope." },
];

interface Form {
  persona: string;
  autonomy: string;
  budget: string;
  apiEnabled: boolean;
}

function formFrom(employee: Employee | undefined): Form {
  return {
    persona: employee?.persona ?? "",
    autonomy: employee?.autonomy_level || "normal",
    budget: employee?.budget_daily_micros
      ? String(employee.budget_daily_micros / 1_000_000)
      : "",
    apiEnabled: employee?.api_enabled ?? true,
  };
}

export function AgentSettings({ employeeId }: { employeeId: string }) {
  const client = useQueryClient();
  const toast = useToast();

  const employee = useQuery({
    queryKey: ["employee", employeeId],
    queryFn: () => api.employees.get(employeeId),
  });

  // The form is seeded from what was loaded, and re-seeded only when a
  // genuinely different version arrives — never on every render, and never
  // while you are halfway through typing into it.
  const [draft, setDraft] = useState<{ from: string; form: Form } | null>(null);
  const loaded = employee.data;
  const stamp = loaded ? `${loaded.id}:${loaded.persona}:${loaded.autonomy_level}` : "";
  const form = draft?.from === stamp ? draft.form : formFrom(loaded);
  const edit = (patch: Partial<Form>) => setDraft({ from: stamp, form: { ...form, ...patch } });

  const save = useMutation({
    mutationFn: () =>
      api.agents.configure(employeeId, {
        persona: form.persona,
        autonomy_level: form.autonomy,
        budget_daily_micros: form.budget.trim()
          ? Math.round(Number(form.budget) * 1_000_000)
          : null,
        api_enabled: form.apiEnabled,
      }),
    onSuccess: (updated) => {
      client.invalidateQueries({ queryKey: ["employee", employeeId] });
      client.invalidateQueries({ queryKey: keys.agent(employeeId) });
      toast.show("ok", "Saved.");
      if (updated.notes?.length) toast.show("info", updated.notes.join(" "));
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  const coach = useMutation({
    mutationFn: () => api.employees.coach(employeeId),
    onError: (error: Error) => toast.show("error", error.message),
  });

  if (!employee.data) return <Skeleton className="h-64" />;

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Panel>
        <PanelHeader
          icon={<SlidersHorizontal size={14} />}
          title="How they work"
          hint="Changes apply to their next turn."
        />
        <div className="space-y-4 p-4">
          <Field label="Persona" hint="Goes into every system prompt, verbatim.">
            <Textarea
              value={form.persona}
              onChange={(event) => edit({ persona: event.target.value })}
              className="min-h-28"
            />
          </Field>

          <Field
            label="Autonomy"
            hint={AUTONOMY.find((entry) => entry.key === form.autonomy)?.hint}
          >
            <Select value={form.autonomy} onChange={(event) => edit({ autonomy: event.target.value })}>
              {AUTONOMY.map((entry) => (
                <option key={entry.key} value={entry.key}>
                  {entry.label}
                </option>
              ))}
            </Select>
          </Field>

          <Field
            label="Daily spend cap, in dollars"
            hint="Reached, they refuse to start a turn rather than stopping halfway through one. Blank for no cap."
          >
            <Input
              value={form.budget}
              onChange={(event) => edit({ budget: event.target.value })}
              inputMode="decimal"
              placeholder="5.00"
              className="tnum"
            />
          </Field>

          <Toggle
            checked={form.apiEnabled}
            onChange={(next) => edit({ apiEnabled: next })}
            label="Reachable over the API"
            hint="Off, their tokens stop authenticating and only you can drive them."
          />

          <div className="flex justify-end">
            <Button variant="primary" busy={save.isPending} onClick={() => save.mutate()}>
              Save
            </Button>
          </div>
        </div>
      </Panel>

      <Panel className="self-start">
        <PanelHeader
          icon={<GraduationCap size={14} />}
          title="Coaching"
          hint="Read from what actually happened, and proposed — never applied on its own."
          action={
            <Button size="sm" busy={coach.isPending} onClick={() => coach.mutate()}>
              Look at their record
            </Button>
          }
        />
        {coach.data?.proposals.length ? (
          <ul className="divide-y divide-line">
            {coach.data.proposals.map((proposal, index) => (
              <li key={index} className="px-4 py-3">
                <div className="flex items-center gap-2">
                  <Badge mono>{proposal.field}</Badge>
                  <span className="text-xs text-muted">
                    {proposal.from || "—"} → <span className="text-ink">{proposal.to}</span>
                  </span>
                </div>
                <p className="mt-1.5 text-sm text-ink">{proposal.why}</p>
                <Button
                  size="sm"
                  className="mt-2"
                  onClick={() => {
                    if (proposal.field === "autonomy_level") edit({ autonomy: proposal.to });
                    if (proposal.field === "persona") edit({ persona: proposal.to });
                    toast.show("info", "Applied to the form. Save to keep it.");
                  }}
                >
                  Use this
                </Button>
              </li>
            ))}
          </ul>
        ) : coach.isSuccess ? (
          <Empty title="Nothing to change">
            Their record does not support a confident recommendation yet.
          </Empty>
        ) : (
          <div className="px-4 py-6 text-sm text-muted">
            Coaching reads first-try pass rate, rework and cost — the same figures on the overview
            tab — and proposes a change only when there is enough finished work to justify one.
            {employee.data.budget_daily_micros ? (
              <span className="mt-2 block text-xs text-faint">
                Current cap {money(employee.data.budget_daily_micros)}/day.
              </span>
            ) : null}
          </div>
        )}
      </Panel>
    </div>
  );
}
