"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { useCompany } from "./CompanyShell";
import { Badge, Button, Card, ErrorNote, Field, Input, SectionTitle, Textarea } from "./ui";

const TOOLS = [
  {
    key: "tracker",
    name: "Issue tracker",
    provider: "Built in",
    detail: "Epics, tickets, statuses and comments. Jira-shaped.",
    icon: "📋",
  },
  {
    key: "wiki",
    name: "Wiki",
    provider: "Built in",
    detail: "Spaces, pages and version history. Confluence-shaped.",
    icon: "📚",
  },
  {
    key: "workspace",
    name: "Code workspace",
    provider: "Built in",
    detail: "A git repository per project, plus a sandboxed command runner.",
    icon: "💻",
  },
  { key: "chat", name: "Chat", provider: "Built in", detail: "Channels shared with you.", icon: "💬" },
];

export default function CompanySettings({ companyId }: { companyId: string }) {
  const router = useRouter();
  const { company, reload } = useCompany();
  const [form, setForm] = useState({
    name: "",
    tagline: "",
    industry: "",
    description: "",
    mission: "",
    handbook: "",
  });
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [seededFor, setSeededFor] = useState<string | null>(null);

  // Seed the form the first time the company arrives (a render-phase update,
  // which React handles without an extra commit).
  if (company && seededFor !== company.id) {
    setSeededFor(company.id);
    setForm({
      name: company.name,
      tagline: company.tagline ?? "",
      industry: company.industry ?? "",
      description: company.description ?? "",
      mission: company.mission ?? "",
      handbook: company.handbook ?? "",
    });
  }

  const set = (key: keyof typeof form) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  const save = async () => {
    setError("");
    try {
      await api.companies.update(companyId, form);
      setSaved(true);
      reload();
      setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const remove = async () => {
    if (!confirm(`Delete ${company?.name}? Employees, projects and tickets go with it.`)) return;
    await api.companies.remove(companyId);
    router.push("/");
  };

  return (
    <div className="max-w-3xl space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-slate-100">Settings</h1>
        <p className="text-sm text-slate-400">
          The profile below is prepended to every employee&apos;s instructions.
        </p>
      </header>

      <Card className="space-y-4 p-5">
        <SectionTitle>Company profile</SectionTitle>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name">
            <Input value={form.name} onChange={set("name")} />
          </Field>
          <Field label="Industry">
            <Input value={form.industry} onChange={set("industry")} />
          </Field>
        </div>
        <Field label="Tagline">
          <Input value={form.tagline} onChange={set("tagline")} />
        </Field>
        <Field label="What it does">
          <Textarea rows={3} value={form.description} onChange={set("description")} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Mission">
            <Textarea rows={3} value={form.mission} onChange={set("mission")} />
          </Field>
          <Field label="Handbook" hint="House rules every employee follows.">
            <Textarea rows={3} value={form.handbook} onChange={set("handbook")} />
          </Field>
        </div>
        {error && <ErrorNote>{error}</ErrorNote>}
        <div className="flex items-center gap-3">
          <Button onClick={save}>Save changes</Button>
          {saved && <span className="text-sm text-emerald-400">Saved.</span>}
        </div>
      </Card>

      <Card className="p-5">
        <SectionTitle>Tools</SectionTitle>
        <p className="mb-4 text-sm text-slate-500">
          Employees get an account per tool. Each tool sits behind an adapter, so a built-in module
          can be swapped for the real SaaS without changing how employees work.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          {TOOLS.map((tool) => (
            <div key={tool.key} className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
              <div className="flex items-center justify-between">
                <p className="font-medium text-slate-200">
                  {tool.icon} {tool.name}
                </p>
                <Badge tone="border-emerald-500/30 bg-emerald-500/10 text-emerald-300">
                  {tool.provider}
                </Badge>
              </div>
              <p className="mt-2 text-xs text-slate-500">{tool.detail}</p>
            </div>
          ))}
        </div>
        <p className="mt-4 text-xs text-slate-600">
          External providers (Jira Cloud, Confluence, GitHub) are not connected yet — the adapter
          interface is in place, the connectors are not written.
        </p>
      </Card>

      <Card className="border-rose-500/20 p-5">
        <SectionTitle>Danger zone</SectionTitle>
        <p className="mb-3 text-sm text-slate-400">
          Deleting a company removes its employees, projects, tickets, wiki and chat history.
          Workspace files on disk are left alone.
        </p>
        <Button variant="danger" onClick={remove}>
          Delete company
        </Button>
      </Card>
    </div>
  );
}
