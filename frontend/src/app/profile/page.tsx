"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Building2, LogOut, Monitor, UserRound } from "lucide-react";
import { auth } from "@/lib/auth";
import { timeAgo, when } from "@/lib/format";
import { useSession } from "@/lib/session";
import { TwoFactorPanel } from "@/components/auth/two-factor";
import {
  Badge,
  Button,
  Empty,
  ErrorNote,
  Field,
  Input,
  Mono,
  PageHeader,
  Panel,
  PanelHeader,
  Skeleton,
} from "@/components/ui";
import { useToast } from "@/components/ui/toast";

export default function Profile() {
  const { account, loading, signOut, signingOut, refresh } = useSession();
  const toast = useToast();
  const [name, setName] = useState<string | null>(null);

  const sessions = useQuery({
    queryKey: ["sessions"],
    queryFn: auth.sessions,
    enabled: Boolean(account),
  });

  const save = useMutation({
    mutationFn: () => auth.updateMe({ full_name: name ?? "" }),
    onSuccess: () => {
      refresh();
      setName(null);
      toast.show("ok", "Saved.");
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  if (loading) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 px-6 py-12">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (!account) {
    return (
      <div className="mx-auto max-w-md px-6 py-12">
        <ErrorNote error={new Error("You are not signed in.")} />
        <Button variant="primary" className="mt-4">
          <Link href="/login">Sign in</Link>
        </Button>
      </div>
    );
  }

  const currentName = name ?? account.full_name;

  return (
    <div className="mx-auto max-w-3xl space-y-5 px-6 py-12">
      <Link
        href="/"
        className="inline-flex items-center gap-1.5 text-xs text-muted transition-colors hover:text-ink"
      >
        <ArrowLeft size={13} />
        All companies
      </Link>

      <PageHeader
        title="Your account"
        hint={`Signed in as ${account.email}`}
        action={
          <Button
            variant="secondary"
            icon={<LogOut size={14} />}
            busy={signingOut}
            onClick={signOut}
          >
            Sign out
          </Button>
        }
      />

      <Panel>
        <PanelHeader icon={<UserRound size={14} />} title="Details" />
        <div className="space-y-4 p-4">
          <Field label="Full name">
            <Input value={currentName} onChange={(event) => setName(event.target.value)} />
          </Field>
          <Field
            label="Email"
            hint="Changing this has to prove the new address is yours, which is not built yet."
          >
            <Input value={account.email} readOnly disabled />
          </Field>
          {name !== null && name !== account.full_name ? (
            <div className="flex justify-end">
              <Button variant="primary" size="sm" busy={save.isPending} onClick={() => save.mutate()}>
                Save
              </Button>
            </div>
          ) : null}
        </div>
      </Panel>

      <Panel>
        <PanelHeader icon={<Building2 size={14} />} title="Organisation" />
        <dl className="grid gap-x-4 gap-y-2 p-4 text-sm sm:grid-cols-[10rem_1fr]">
          <dt className="text-muted">Name</dt>
          <dd className="text-ink">{account.tenant.name ?? "—"}</dd>
          <dt className="text-muted">Companies</dt>
          <dd className="tnum text-ink">{account.companies ?? 0}</dd>
          <dt className="text-muted">Your role</dt>
          <dd>
            {account.is_owner ? <Badge tone="accent">Owner</Badge> : <Badge>Member</Badge>}
          </dd>
          <dt className="text-muted">Joined</dt>
          <dd className="text-ink">{when(account.created_at)}</dd>
        </dl>
      </Panel>

      <TwoFactorPanel status={account.two_factor} onChanged={refresh} />

      <ChangePassword />

      <Panel>
        <PanelHeader
          icon={<Monitor size={14} />}
          title="Where you are signed in"
          hint="If one of these is not you, change your password — it ends all of them."
          action={
            <Button
              size="sm"
              onClick={async () => {
                await auth.logOutEverywhere();
                signOut();
              }}
            >
              Sign out everywhere
            </Button>
          }
        />
        {sessions.data?.length ? (
          <ul className="divide-y divide-line">
            {sessions.data.map((row) => (
              <li key={row.id} className="flex items-center gap-3 px-4 py-2.5">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-ink">
                    {row.user_agent || "An unnamed client"}
                  </span>
                  <Mono className="block text-xs text-faint">{row.ip || "unknown address"}</Mono>
                </span>
                <span className="shrink-0 text-xs text-faint">{timeAgo(row.created_at)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <Empty title="No other sessions" />
        )}
      </Panel>
    </div>
  );
}

function ChangePassword() {
  const toast = useToast();
  const { signOut } = useSession();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");

  const change = useMutation({
    mutationFn: () => auth.changePassword(current, next),
    onSuccess: (result) => {
      setCurrent("");
      setNext("");
      toast.show(
        "ok",
        result.other_sessions_ended
          ? `Changed. ${result.other_sessions_ended} other session(s) were signed out.`
          : "Changed.",
      );
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  return (
    <Panel>
      <PanelHeader
        title="Password"
        hint="Changing it signs out every other device, because that is usually the point."
      />
      <div className="space-y-4 p-4">
        <Field label="Current password">
          <Input
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
          />
        </Field>
        <Field label="New password" hint="At least 10 characters.">
          <Input
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(event) => setNext(event.target.value)}
          />
        </Field>
        <div className="flex items-center justify-between">
          <button
            type="button"
            className="text-xs text-muted hover:text-ink"
            onClick={signOut}
          >
            Sign out instead
          </button>
          <Button
            variant="primary"
            size="sm"
            busy={change.isPending}
            disabled={!current || next.length < 10}
            onClick={() => change.mutate()}
          >
            Change password
          </Button>
        </div>
      </div>
    </Panel>
  );
}
