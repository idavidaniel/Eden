"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { ACTIVITY_ICONS, STATUS_LABELS, STATUS_TONES, timeAgo } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import type { EmployeeDetail } from "@/lib/types";
import { Avatar, Badge, Button, Card, ErrorNote, SectionTitle, Spinner } from "./ui";

type Credential = { tool: string; username: string; password: string; token: string };

export default function EmployeeProfile({
  companyId,
  employeeId,
}: {
  companyId: string;
  employeeId: string;
}) {
  const router = useRouter();
  const { data, error, loading } = useResource<EmployeeDetail>(
    () => api.employees.get(employeeId),
    [employeeId],
    { intervalMs: 10000 },
  );
  const [credentials, setCredentials] = useState<Credential[] | null>(null);
  const [busy, setBusy] = useState(false);

  const revealCredentials = async () => {
    setBusy(true);
    try {
      setCredentials((await api.employees.credentials(employeeId)).accounts);
    } finally {
      setBusy(false);
    }
  };

  const rotate = async (tool: string) => {
    const rotated = await api.employees.rotate(employeeId, tool);
    setCredentials((current) =>
      (current ?? []).map((item) => (item.tool === tool ? rotated : item)),
    );
  };

  const offboard = async () => {
    if (!confirm(`Offboard ${data?.name}? Their accounts are revoked.`)) return;
    await api.employees.remove(employeeId);
    router.push(`/companies/${companyId}/people`);
  };

  if (loading) return <Spinner />;
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!data) return null;

  return (
    <div className="space-y-6">
      <Link href={`/companies/${companyId}/people`} className="text-xs text-slate-500 hover:text-slate-300">
        ← People
      </Link>

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-4">
          <Avatar emoji={data.avatar} size="lg" />
          <div>
            <h1 className="text-2xl font-bold text-slate-100">{data.name}</h1>
            <p className="text-slate-400">
              {data.seniority} {data.title} · {data.department}
            </p>
            {data.manager && (
              <p className="mt-1 text-xs text-slate-500">
                Reports to{" "}
                <Link
                  href={`/companies/${companyId}/people/${data.manager.id}`}
                  className="text-blue-400 hover:underline"
                >
                  {data.manager.name}
                </Link>
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge
            tone={
              data.status === "working"
                ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
                : "border-white/10 bg-white/5 text-slate-400"
            }
          >
            {data.status}
            {data.status_note ? ` · ${data.status_note}` : ""}
          </Badge>
          <Button variant="danger" size="sm" onClick={offboard}>
            Offboard
          </Button>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card className="p-5">
            <SectionTitle>Persona</SectionTitle>
            <p className="text-sm leading-relaxed whitespace-pre-wrap text-slate-300">{data.persona}</p>
            <div className="mt-4 flex flex-wrap gap-1.5">
              {data.skills.map((skill) => (
                <Badge key={skill}>{skill}</Badge>
              ))}
            </div>
          </Card>

          <Card className="p-5">
            <SectionTitle>Assigned tickets</SectionTitle>
            {data.tickets.length === 0 ? (
              <p className="text-sm text-slate-500">Nothing assigned right now.</p>
            ) : (
              <ul className="divide-y divide-white/5">
                {data.tickets.map((ticket) => (
                  <li key={ticket.id} className="flex items-center gap-3 py-2">
                    <span className="font-mono text-xs text-slate-500">{ticket.key}</span>
                    <span className="min-w-0 flex-1 truncate text-sm text-slate-300">{ticket.title}</span>
                    <Badge tone={STATUS_TONES[ticket.status]}>{STATUS_LABELS[ticket.status]}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card className="p-5">
            <SectionTitle>Recent activity</SectionTitle>
            {data.activity.length === 0 ? (
              <p className="text-sm text-slate-500">No activity yet.</p>
            ) : (
              <ul className="space-y-2">
                {[...data.activity].reverse().map((event) => (
                  <li key={event.seq} className="flex items-start gap-2 text-sm">
                    <span>{ACTIVITY_ICONS[event.kind] ?? "•"}</span>
                    <span className="flex-1 text-slate-300">{event.summary}</span>
                    <span className="text-xs text-slate-600">{timeAgo(event.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <div className="space-y-6">
          <Card className="p-5">
            <SectionTitle
              action={
                credentials ? (
                  <button
                    onClick={() => setCredentials(null)}
                    className="text-xs text-slate-500 hover:text-slate-300"
                  >
                    hide
                  </button>
                ) : undefined
              }
            >
              Accounts
            </SectionTitle>
            <p className="mb-3 text-xs text-slate-500">
              Service accounts issued to {data.name.split(" ")[0]} for each tool.
            </p>

            {!credentials && (
              <div className="space-y-2">
                {data.accounts.map((account) => (
                  <div key={account.tool} className="rounded-lg border border-white/10 bg-white/5 p-3">
                    <p className="text-xs tracking-wide text-slate-500 uppercase">{account.tool}</p>
                    <p className="font-mono text-xs break-all text-slate-300">{account.username}</p>
                    <p className="font-mono text-xs text-slate-600">password ••••••••••</p>
                  </div>
                ))}
                <Button size="sm" variant="subtle" onClick={revealCredentials} disabled={busy}>
                  {busy ? "Unsealing…" : "🔑 Reveal credentials"}
                </Button>
              </div>
            )}

            {credentials && (
              <div className="space-y-2">
                {credentials.map((credential) => (
                  <div key={credential.tool} className="rounded-lg border border-white/10 bg-white/5 p-3">
                    <div className="flex items-center justify-between">
                      <p className="text-xs tracking-wide text-slate-500 uppercase">{credential.tool}</p>
                      <button
                        onClick={() => rotate(credential.tool)}
                        className="text-xs text-slate-500 hover:text-slate-200"
                      >
                        rotate
                      </button>
                    </div>
                    <Secret label="user" value={credential.username} />
                    <Secret label="pass" value={credential.password} />
                    <Secret label="token" value={credential.token} />
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card className="p-5">
            <SectionTitle>Toolbelt</SectionTitle>
            <div className="flex flex-wrap gap-1.5">
              {data.toolbelt.map((tool) => (
                <Badge key={tool} tone="border-blue-500/30 bg-blue-500/10 text-blue-300">
                  {tool}
                </Badge>
              ))}
            </div>
            <p className="mt-3 text-xs text-slate-500">
              An employee can only call tools in their belt — the platform refuses the rest.
            </p>
          </Card>
        </div>
      </div>
    </div>
  );
}

function Secret({ label, value }: { label: string; value: string }) {
  return (
    <p className="mt-1 flex items-baseline gap-2 font-mono text-xs">
      <span className="w-10 shrink-0 text-slate-600">{label}</span>
      <button
        onClick={() => navigator.clipboard?.writeText(value)}
        title="Copy"
        className="min-w-0 flex-1 truncate text-left text-slate-300 hover:text-blue-300"
      >
        {value}
      </button>
    </p>
  );
}
