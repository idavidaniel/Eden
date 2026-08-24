"use client";

import { use, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Building2, OctagonX, RefreshCw, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { keys } from "@/lib/hooks";
import type { Company } from "@/lib/types";
import {
  Badge,
  Button,
  Dialog,
  Field,
  Input,
  Mono,
  PageHeader,
  Panel,
  PanelHeader,
  Skeleton,
  Textarea,
} from "@/components/ui";
import { useToast } from "@/components/ui/toast";

interface Form {
  name: string;
  tagline: string;
  description: string;
  mission: string;
  handbook: string;
}

const formFrom = (company?: Company): Form => ({
  name: company?.name ?? "",
  tagline: company?.tagline ?? "",
  description: company?.description ?? "",
  mission: company?.mission ?? "",
  handbook: company?.handbook ?? "",
});

export default function Settings({ params }: { params: Promise<{ companyId: string }> }) {
  const { companyId } = use(params);
  const client = useQueryClient();
  const toast = useToast();
  const router = useRouter();
  const [closing, setClosing] = useState(false);

  const company = useQuery({
    queryKey: keys.company(companyId),
    queryFn: () => api.companies.get(companyId),
  });
  const pack = useQuery({ queryKey: keys.pack(companyId), queryFn: () => api.companies.pack(companyId) });

  const [draft, setDraft] = useState<{ from: string; form: Form } | null>(null);
  const stamp = company.data ? `${company.data.id}:${company.data.name}:${company.data.handbook}` : "";
  const form = draft?.from === stamp ? draft.form : formFrom(company.data);
  const edit = (patch: Partial<Form>) => setDraft({ from: stamp, form: { ...form, ...patch } });

  const save = useMutation({
    mutationFn: () => api.companies.update(companyId, form),
    onSuccess: (updated) => {
      client.setQueryData(keys.company(companyId), updated);
      toast.show("ok", "Saved. Everyone reads this on their next turn.");
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  const reapply = useMutation({
    mutationFn: () => api.companies.reapplyPack(companyId),
    onSuccess: (result) => {
      client.invalidateQueries({ queryKey: keys.pack(companyId) });
      toast.show("ok", `Re-read ${result.pack}: ${result.roles} roles, ${result.checks} checks.`);
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  const close = useMutation({
    mutationFn: () => api.companies.remove(companyId),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.companies });
      toast.show("info", "Closed.");
      router.push("/");
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  if (!company.data) return <Skeleton className="h-96" />;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Settings"
        hint="What this company is, and what shape it takes."
        action={
          <Button variant="primary" busy={save.isPending} onClick={() => save.mutate()}>
            Save
          </Button>
        }
      />

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel>
          <PanelHeader icon={<Building2 size={14} />} title="Identity" />
          <div className="space-y-4 p-4">
            <Field label="Name">
              <Input value={form.name} onChange={(event) => edit({ name: event.target.value })} />
            </Field>
            <Field label="Tagline" hint="One line. Shown wherever the company is listed.">
              <Input
                value={form.tagline}
                onChange={(event) => edit({ tagline: event.target.value })}
              />
            </Field>
            <Field label="What it does" hint="Goes into every employee's system prompt.">
              <Textarea
                value={form.description}
                onChange={(event) => edit({ description: event.target.value })}
              />
            </Field>
            <Field label="Mission" hint="What the company is trying to achieve, beyond the next task.">
              <Textarea
                value={form.mission}
                onChange={(event) => edit({ mission: event.target.value })}
              />
            </Field>
            <Field
              label="Handbook"
              hint="House rules. How to write, what to never do, who decides what. Everyone reads this."
            >
              <Textarea
                value={form.handbook}
                onChange={(event) => edit({ handbook: event.target.value })}
                className="min-h-40"
              />
            </Field>
          </div>
        </Panel>

        <div className="space-y-5">
          <Panel>
            <PanelHeader
              title="Industry"
              hint="The pack decides the roles, the deliverables and how work gets checked."
              action={
                <Button
                  size="sm"
                  icon={<RefreshCw size={12} />}
                  busy={reapply.isPending}
                  onClick={() => reapply.mutate()}
                >
                  Re-read from disk
                </Button>
              }
            />
            <div className="space-y-3 p-4">
              <div className="flex items-center gap-2">
                <Mono className="text-ink">{company.data.pack_key}</Mono>
                <span className="text-sm text-muted">{pack.data?.name}</span>
              </div>
              <p className="text-sm text-muted">{pack.data?.description}</p>

              <div>
                <p className="mb-1 text-xs font-medium text-ink">Work is called</p>
                <div className="flex flex-wrap gap-1">
                  {(pack.data?.work_item_kinds ?? []).map((kind) => (
                    <Badge key={kind}>{kind.replace(/_/g, " ")}</Badge>
                  ))}
                </div>
              </div>

              <div>
                <p className="mb-1 text-xs font-medium text-ink">Deliverables</p>
                <div className="flex flex-wrap gap-1">
                  {(pack.data?.artifact_kinds ?? []).map((kind) => (
                    <Badge key={kind.key} tone="accent">
                      {kind.name}
                    </Badge>
                  ))}
                </div>
              </div>

              <div>
                <p className="mb-1 text-xs font-medium text-ink">Checked by</p>
                <ul className="space-y-1">
                  {(pack.data?.checks ?? []).map((check) => (
                    <li key={check.id} className="flex items-start gap-2 text-xs">
                      <Badge mono>{check.kind}</Badge>
                      <span className="text-muted">{check.name}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </Panel>

          <Panel>
            <PanelHeader icon={<OctagonX size={14} />} title="Stopping" />
            <div className="space-y-3 p-4">
              <p className="text-sm text-muted">
                Halting refuses every turn immediately, including ones already queued. It does not
                lose anything — it stops the company acting until you resume it.
              </p>
              {company.data.halted ? (
                <p className="rounded-md border border-line bg-fail-wash px-3 py-2 text-sm text-fail">
                  Currently halted: {company.data.halt_reason || "stopped by you"}
                </p>
              ) : null}
              <div className="border-t border-line pt-3">
                <Button variant="danger" icon={<Trash2 size={13} />} onClick={() => setClosing(true)}>
                  Close this company
                </Button>
              </div>
            </div>
          </Panel>
        </div>
      </div>

      <Dialog
        open={closing}
        onClose={() => setClosing(false)}
        title={`Close ${company.data.name}?`}
        hint="Its people, work, deliverables and ledger all go with it. This cannot be undone."
        footer={
          <>
            <Button onClick={() => setClosing(false)}>Keep it</Button>
            <Button variant="danger" busy={close.isPending} onClick={() => close.mutate()}>
              Close it permanently
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted">
          If you only want it to stop working, halt it instead — that is reversible and keeps the
          record.
        </p>
      </Dialog>
    </div>
  );
}
