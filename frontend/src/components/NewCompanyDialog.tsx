"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import type { Role } from "@/lib/types";
import { Button, ErrorNote, Field, Input, Modal, Textarea } from "./ui";

const DEFAULT_TEAM = [
  "engineering_manager",
  "product_manager",
  "backend_engineer",
  "frontend_engineer",
  "qa_engineer",
  "tech_writer",
];

export default function NewCompanyDialog({
  open,
  roles,
  onClose,
  onCreated,
}: {
  open: boolean;
  roles: Role[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const router = useRouter();
  const [form, setForm] = useState({
    name: "",
    tagline: "",
    industry: "",
    description: "",
    mission: "",
    handbook: "",
  });
  const [team, setTeam] = useState<string[]>(DEFAULT_TEAM);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const set = (key: keyof typeof form) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  const toggle = (key: string) =>
    setTeam((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key],
    );

  const submit = async () => {
    if (!form.name.trim()) return setError("The company needs a name.");
    setSaving(true);
    setError("");
    try {
      const company = await api.companies.create({ ...form, starting_team: team });
      onCreated();
      router.push(`/companies/${company.id}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Found a company" wide>
      <div className="grid gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Company name">
            <Input value={form.name} onChange={set("name")} placeholder="Lumen Analytics" />
          </Field>
          <Field label="Industry">
            <Input value={form.industry} onChange={set("industry")} placeholder="Clean energy software" />
          </Field>
        </div>

        <Field label="Tagline">
          <Input value={form.tagline} onChange={set("tagline")} placeholder="Dashboards for solar installers" />
        </Field>

        <Field label="What does it do?" hint="Every employee reads this before they start work.">
          <Textarea
            rows={3}
            value={form.description}
            onChange={set("description")}
            placeholder="We build small web tools that help solar installers track panel performance."
          />
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Mission">
            <Textarea rows={2} value={form.mission} onChange={set("mission")} />
          </Field>
          <Field label="Handbook" hint="Rules the whole company follows.">
            <Textarea
              rows={2}
              value={form.handbook}
              onChange={set("handbook")}
              placeholder="Ship small. Python for backends. Every feature needs a test."
            />
          </Field>
        </div>

        <div>
          <p className="mb-2 text-sm text-slate-400">
            Starting team <span className="text-slate-600">({team.length} hires)</span>
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {roles.map((role) => (
              <button
                key={role.key}
                onClick={() => toggle(role.key)}
                className={`flex items-start gap-3 rounded-xl border px-3 py-2 text-left transition-colors ${
                  team.includes(role.key)
                    ? "border-blue-500/50 bg-blue-500/10"
                    : "border-white/10 bg-white/5 hover:border-white/20"
                }`}
              >
                <span className="text-lg">{role.avatar}</span>
                <span>
                  <span className="block text-sm text-slate-200">{role.title}</span>
                  <span className="block text-xs text-slate-500">{role.summary}</span>
                </span>
              </button>
            ))}
          </div>
        </div>

        {error && <ErrorNote>{error}</ErrorNote>}

        <div className="flex justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={saving}>
            {saving ? "Founding…" : "Found company"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
