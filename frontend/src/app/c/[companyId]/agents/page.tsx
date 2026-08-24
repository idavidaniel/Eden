"use client";

import Link from "next/link";
import { use, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search, UserRoundPlus } from "lucide-react";
import { api } from "@/lib/api";
import { EMPLOYEE_TONES, initials, money, titleCase } from "@/lib/format";
import { keys } from "@/lib/hooks";
import {
  Badge,
  Button,
  Dialog,
  Dot,
  Empty,
  ErrorNote,
  Field,
  Input,
  Mono,
  PageHeader,
  Panel,
  Select,
  Skeleton,
} from "@/components/ui";
import { useToast } from "@/components/ui/toast";

export default function Agents({ params }: { params: Promise<{ companyId: string }> }) {
  const { companyId } = use(params);
  const [search, setSearch] = useState("");
  const [hiring, setHiring] = useState(false);

  const employees = useQuery({
    queryKey: keys.employees(companyId),
    queryFn: () => api.employees.list(companyId),
  });

  const byDepartment = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const matched = (employees.data ?? []).filter(
      (person) =>
        !needle ||
        `${person.name} ${person.title} ${person.role_key} ${person.capabilities.join(" ")}`
          .toLowerCase()
          .includes(needle),
    );
    const groups = new Map<string, typeof matched>();
    for (const person of matched) {
      const key = person.department || "Everyone else";
      groups.set(key, [...(groups.get(key) ?? []), person]);
    }
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [employees.data, search]);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Agents"
        hint="Everyone here has their own memory, their own tools, their own budget and their own API."
        action={
          <>
            <div className="relative">
              <Search
                size={14}
                className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-faint"
              />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search by name or capability"
                className="w-56 pl-8"
              />
            </div>
            <Button variant="primary" icon={<Plus size={14} />} onClick={() => setHiring(true)}>
              Hire
            </Button>
          </>
        }
      />

      {employees.error ? (
        <ErrorNote error={employees.error} retry={() => employees.refetch()} />
      ) : employees.isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
        </div>
      ) : byDepartment.length ? (
        byDepartment.map(([department, people]) => (
          <section key={department}>
            <h2 className="mb-2 text-[0.7rem] font-semibold tracking-[0.09em] text-faint uppercase">
              {titleCase(department)}
              <span className="tnum ml-2 font-normal">{people.length}</span>
            </h2>
            <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {people.map((person) => (
                <li key={person.id}>
                  <Link
                    href={`/c/${companyId}/agents/${person.id}`}
                    className="block h-full rounded-lg border border-line bg-surface p-4 transition-colors hover:border-line-strong hover:bg-sunken"
                  >
                    <div className="flex items-start gap-3">
                      <span className="grid size-9 shrink-0 place-items-center rounded-full bg-accent-wash text-xs font-semibold text-accent">
                        {person.avatar || initials(person.name)}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold text-ink">
                          {person.name}
                        </span>
                        <span className="block truncate text-xs text-muted">{person.title}</span>
                      </span>
                      <Badge tone={EMPLOYEE_TONES[person.status] ?? "neutral"}>
                        <Dot tone={EMPLOYEE_TONES[person.status] ?? "neutral"} />
                        {person.status}
                      </Badge>
                    </div>

                    {person.status_note ? (
                      <p className="mt-2 line-clamp-2 text-xs text-muted">{person.status_note}</p>
                    ) : null}

                    <div className="mt-3 flex flex-wrap gap-1">
                      {person.capabilities.slice(0, 4).map((capability) => (
                        <Badge key={capability}>{capability.replace(/_/g, " ")}</Badge>
                      ))}
                    </div>

                    <div className="mt-3 flex items-center justify-between border-t border-line pt-2 text-xs text-faint">
                      <Mono>{person.role_key}</Mono>
                      <span className="tnum">
                        {person.budget_daily_micros
                          ? `${money(person.budget_daily_micros)}/day cap`
                          : person.api_enabled
                            ? "API on"
                            : "API off"}
                      </span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))
      ) : (
        <Panel>
          <Empty
            icon={<UserRoundPlus size={22} />}
            title={search ? "Nobody matches that" : "Nobody has been hired yet"}
            action={
              search ? null : (
                <Button variant="primary" onClick={() => setHiring(true)}>
                  Hire someone
                </Button>
              )
            }
          >
            {search
              ? "Try a different name, role or capability."
              : "Roles come from this company's industry pack."}
          </Empty>
        </Panel>
      )}

      <HireDialog companyId={companyId} open={hiring} onClose={() => setHiring(false)} />
    </div>
  );
}

function HireDialog({
  companyId,
  open,
  onClose,
}: {
  companyId: string;
  open: boolean;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const toast = useToast();
  const [roleKey, setRoleKey] = useState("");
  const [name, setName] = useState("");

  const pack = useQuery({
    queryKey: keys.pack(companyId),
    queryFn: () => api.companies.pack(companyId),
    enabled: open,
  });
  const role = pack.data?.roles.find((entry) => entry.key === roleKey) ?? pack.data?.roles[0];

  const hire = useMutation({
    mutationFn: () =>
      api.employees.hire(companyId, {
        role_key: role?.key,
        name: name.trim() || undefined,
      }),
    onSuccess: (person) => {
      client.invalidateQueries({ queryKey: keys.employees(companyId) });
      toast.show("ok", `${person.name} started as ${person.title}.`);
      setName("");
      onClose();
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Hire someone"
      hint="They arrive with their role's tools, capabilities and a fresh memory."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" busy={hire.isPending} onClick={() => hire.mutate()}>
            Hire
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Role" hint={role?.summary}>
          <Select value={role?.key ?? ""} onChange={(event) => setRoleKey(event.target.value)}>
            {(pack.data?.roles ?? []).map((entry) => (
              <option key={entry.key} value={entry.key}>
                {entry.title} — {entry.department}
              </option>
            ))}
          </Select>
        </Field>

        <Field label="Name" hint="Leave blank and one gets generated.">
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Ada Kern"
          />
        </Field>

        {role?.capabilities.length ? (
          <div>
            <p className="mb-1.5 text-xs font-medium text-ink">They will be able to</p>
            <div className="flex flex-wrap gap-1">
              {role.capabilities.map((capability) => (
                <Badge key={capability} tone="accent">
                  {capability.replace(/_/g, " ")}
                </Badge>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </Dialog>
  );
}
