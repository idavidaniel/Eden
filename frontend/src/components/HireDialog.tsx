"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { Employee, Role } from "@/lib/types";
import { Button, ErrorNote, Field, Input, Modal, Select, Textarea } from "./ui";

export default function HireDialog({
  open,
  companyId,
  roles,
  employees,
  onClose,
  onHired,
}: {
  open: boolean;
  companyId: string;
  roles: Role[];
  employees: Employee[];
  onClose: () => void;
  onHired: () => void;
}) {
  const [roleKey, setRoleKey] = useState("backend_engineer");
  const [form, setForm] = useState({ name: "", seniority: "Mid", persona: "", manager_id: "" });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const role = roles.find((item) => item.key === roleKey);
  const [personaFor, setPersonaFor] = useState<string | null>(null);

  // Show the role's default persona so it can be edited before hiring.
  if (role && personaFor !== role.key) {
    setPersonaFor(role.key);
    setForm((current) => ({ ...current, persona: role.persona }));
  }

  const submit = async () => {
    setSaving(true);
    setError("");
    try {
      await api.employees.hire(companyId, {
        role_key: roleKey,
        name: form.name || undefined,
        seniority: form.seniority,
        persona: form.persona || undefined,
        manager_id: form.manager_id || undefined,
      });
      onHired();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Hire an AI employee" wide>
      <div className="grid gap-4">
        <div>
          <p className="mb-2 text-sm text-slate-400">Role</p>
          <div className="grid max-h-56 gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
            {roles.map((item) => (
              <button
                key={item.key}
                onClick={() => setRoleKey(item.key)}
                className={`flex items-start gap-3 rounded-xl border px-3 py-2 text-left transition-colors ${
                  roleKey === item.key
                    ? "border-blue-500/50 bg-blue-500/10"
                    : "border-white/10 bg-white/5 hover:border-white/20"
                }`}
              >
                <span className="text-lg">{item.avatar}</span>
                <span>
                  <span className="block text-sm text-slate-200">{item.title}</span>
                  <span className="block text-xs text-slate-500">{item.summary}</span>
                </span>
              </button>
            ))}
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Name" hint="Leave blank to auto-name.">
            <Input
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="Auto"
            />
          </Field>
          <Field label="Seniority">
            <Select
              value={form.seniority}
              onChange={(event) => setForm({ ...form, seniority: event.target.value })}
            >
              {["Junior", "Mid", "Senior", "Principal"].map((level) => (
                <option key={level}>{level}</option>
              ))}
            </Select>
          </Field>
          <Field label="Reports to">
            <Select
              value={form.manager_id}
              onChange={(event) => setForm({ ...form, manager_id: event.target.value })}
            >
              <option value="">Nobody</option>
              {employees.map((employee) => (
                <option key={employee.id} value={employee.id}>
                  {employee.name} — {employee.title}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <Field label="Persona" hint="This is the instruction they work under.">
          <Textarea
            rows={4}
            value={form.persona}
            onChange={(event) => setForm({ ...form, persona: event.target.value })}
          />
        </Field>

        <p className="text-xs text-slate-500">
          Tools issued: {role?.toolbelt.join(", ") ?? "—"} · accounts and passwords are generated on hire.
        </p>

        {error && <ErrorNote>{error}</ErrorNote>}

        <div className="flex justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={saving}>
            {saving ? "Hiring…" : "Hire"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
