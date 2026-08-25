"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, LogOut, OctagonX, Plus, UserRound, Users } from "lucide-react";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { keys } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Pack } from "@/lib/types";
import {
  Badge,
  Button,
  Dialog,
  Empty,
  ErrorNote,
  Field,
  Input,
  PageHeader,
  Panel,
  Select,
  Skeleton,
  Textarea,
} from "@/components/ui";
import { useToast } from "@/components/ui/toast";

export default function Companies() {
  const { account, signOut, signingOut } = useSession();
  const [founding, setFounding] = useState(false);
  const companies = useQuery({ queryKey: keys.companies, queryFn: api.companies.list });
  const health = useQuery({ queryKey: keys.health, queryFn: api.health });

  return (
    <div className="mx-auto max-w-5xl px-6 py-12">
      <PageHeader
        eyebrow={account?.tenant.name ?? "Eden"}
        title="Your companies"
        hint="Each one is staffed by AI employees whose work is checked before it counts as done."
        action={
          <>
            <Button icon={<UserRound size={14} />}>
              <Link href="/profile">Account</Link>
            </Button>
            <Button
              variant="quiet"
              icon={<LogOut size={14} />}
              busy={signingOut}
              onClick={signOut}
            >
              Sign out
            </Button>
            <Button variant="primary" icon={<Plus size={14} />} onClick={() => setFounding(true)}>
              Found a company
            </Button>
          </>
        }
      />

      {account && !account.two_factor.enabled ? (
        <div className="mb-5 flex flex-wrap items-center gap-3 rounded-lg border border-line bg-sunken px-4 py-3">
          <p className="flex-1 text-sm text-muted">
            Your account is protected by a password alone. Two-factor takes a minute to set up.
          </p>
          <Button size="sm">
            <Link href="/profile">Turn it on</Link>
          </Button>
        </div>
      ) : null}

      {health.data && !health.data.llm_configured ? (
        <div className="mb-5 rounded-lg border border-line bg-pending-wash px-4 py-3 text-sm text-pending">
          No model is configured, so nobody here can actually work. Set{" "}
          <code className="font-mono">NVIDIA_API_KEY</code> and restart the backend.
        </div>
      ) : null}

      {companies.error ? (
        <ErrorNote error={companies.error} retry={() => companies.refetch()} />
      ) : companies.isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      ) : companies.data?.length ? (
        <ul className="grid gap-3 sm:grid-cols-2">
          {companies.data.map((company) => (
            <li key={company.id}>
              <Link
                href={`/c/${company.id}`}
                className="block h-full rounded-lg border border-line bg-surface p-4 transition-colors hover:border-line-strong hover:bg-sunken"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="truncate text-sm font-semibold text-ink">{company.name}</h2>
                    <p className="mt-0.5 truncate text-xs text-faint">
                      {company.industry || company.pack_key.replace(/_/g, " ")}
                    </p>
                  </div>
                  {company.halted ? (
                    <Badge tone="fail">
                      <OctagonX size={11} />
                      Halted
                    </Badge>
                  ) : null}
                </div>
                <p className="mt-2 line-clamp-2 text-sm text-muted">
                  {company.tagline || company.description || "No brief written yet."}
                </p>
                <div className="mt-3 flex items-center gap-3 text-xs text-faint">
                  <span className="flex items-center gap-1">
                    <Users size={11} />
                    {company.stats?.employees ?? 0}
                  </span>
                  <span>{company.stats?.open_work_items ?? 0} open</span>
                  <span className="ml-auto">{timeAgo(company.created_at)}</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <Panel>
          <Empty
            icon={<Building2 size={22} />}
            title="No companies yet"
            action={
              <Button variant="primary" icon={<Plus size={14} />} onClick={() => setFounding(true)}>
                Found the first one
              </Button>
            }
          >
            Pick an industry and Eden staffs it with the roles that industry actually has.
          </Empty>
        </Panel>
      )}

      <FoundDialog open={founding} onClose={() => setFounding(false)} />
    </div>
  );
}

function FoundDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const client = useQueryClient();
  const toast = useToast();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [packKey, setPackKey] = useState("software_studio");
  const [team, setTeam] = useState<string[]>([]);

  const packs = useQuery({ queryKey: ["packs"], queryFn: api.packs, enabled: open });
  const pack: Pack | undefined = packs.data?.find((entry) => entry.key === packKey);

  const found = useMutation({
    mutationFn: () =>
      api.companies.create({
        name,
        description,
        pack: packKey,
        starting_team: team.length ? team : undefined,
      }),
    onSuccess: (company) => {
      client.invalidateQueries({ queryKey: keys.companies });
      toast.show("ok", `${company.name} is open for business.`);
      onClose();
      router.push(`/c/${company.id}`);
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  const choosePack = (key: string) => {
    setPackKey(key);
    setTeam([]);
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Found a company"
      hint="The industry decides the roles, the deliverables, and how work gets checked."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            busy={found.isPending}
            disabled={!name.trim()}
            onClick={() => found.mutate()}
          >
            Found it
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Name">
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Marsh & Idris"
            autoFocus
          />
        </Field>

        <Field label="Industry" hint={pack?.description}>
          <Select value={packKey} onChange={(event) => choosePack(event.target.value)}>
            {(packs.data ?? []).map((entry) => (
              <option key={entry.key} value={entry.key}>
                {entry.name}
              </option>
            ))}
          </Select>
        </Field>

        <Field label="What it does" hint="One or two sentences. Everyone hired will read this.">
          <Textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Commercial contracts for small manufacturers."
          />
        </Field>

        {pack?.roles.length ? (
          <fieldset>
            <legend className="mb-1.5 text-xs font-medium text-ink">
              Who to hire{" "}
              <span className="font-normal text-muted">
                — leave all unticked for a sensible default team
              </span>
            </legend>
            <div className="grid max-h-52 gap-1 overflow-y-auto rounded-md border border-line p-2 sm:grid-cols-2">
              {pack.roles.map((role) => (
                <label
                  key={role.key}
                  className="flex cursor-pointer items-start gap-2 rounded px-1.5 py-1 hover:bg-sunken"
                >
                  <input
                    type="checkbox"
                    className="mt-1 accent-[var(--accent)]"
                    checked={team.includes(role.key)}
                    onChange={(event) =>
                      setTeam((current) =>
                        event.target.checked
                          ? [...current, role.key]
                          : current.filter((key) => key !== role.key),
                      )
                    }
                  />
                  <span className="min-w-0">
                    <span className="block truncate text-sm text-ink">{role.title}</span>
                    <span className="block truncate text-xs text-faint">{role.department}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
        ) : null}
      </div>
    </Dialog>
  );
}
