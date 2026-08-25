"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ChevronsUpDown,
  LogOut,
  Menu,
  MonitorCog,
  Moon,
  OctagonX,
  Play,
  Sun,
  UserRound,
} from "lucide-react";
import { api } from "@/lib/api";
import { money } from "@/lib/format";
import { keys, useTheme } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Company, OpsSnapshot } from "@/lib/types";
import { Badge, Button, Dot, cx } from "@/components/ui";
import { useToast } from "@/components/ui/toast";

export function TopBar({
  company,
  ops,
  onOpenRail,
}: {
  company: Company;
  ops?: OpsSnapshot;
  onOpenRail: () => void;
}) {
  const client = useQueryClient();
  const toast = useToast();
  const [switching, setSwitching] = useState(false);

  const halt = useMutation({
    mutationFn: (halted: boolean) =>
      api.companies.halt(
        company.id,
        halted,
        halted ? "Stopped from the top bar" : "",
      ),
    onSuccess: (next) => {
      client.setQueryData(keys.company(company.id), next);
      client.invalidateQueries({ queryKey: keys.ops(company.id) });
      toast.show("info", next.halted ? "Everything here is stopped." : "Work can start again.");
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  const spendToday = ops?.spend?.today?.cost_micros ?? 0;

  return (
    <header
      className="sticky top-0 z-30 flex h-[var(--topbar)] items-center gap-2 border-b border-line bg-surface/90 px-3 backdrop-blur"
    >
      <Button
        variant="quiet"
        size="sm"
        className="lg:hidden"
        onClick={onOpenRail}
        aria-label="Open navigation"
      >
        <Menu size={16} />
      </Button>

      <button
        type="button"
        onClick={() => setSwitching(true)}
        className="flex min-w-0 items-center gap-2 rounded-md px-2 py-1 text-left transition-colors hover:bg-sunken"
      >
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold text-ink">{company.name}</span>
          <span className="block truncate text-[0.7rem] text-faint">
            {company.industry || company.pack_key.replace(/_/g, " ")}
          </span>
        </span>
        <ChevronsUpDown size={13} className="shrink-0 text-faint" />
      </button>

      <div className="flex-1" />

      {company.halted ? (
        <Badge tone="fail">
          <OctagonX size={11} />
          Halted
        </Badge>
      ) : ops?.autonomous ? (
        <Badge tone="accent">
          <Dot tone="accent" />
          Running on its own
        </Badge>
      ) : null}

      <Link
        href={`/c/${company.id}/ops`}
        className="tnum hidden rounded-md px-2 py-1 font-mono text-xs text-muted transition-colors hover:bg-sunken hover:text-ink sm:block"
        title="Spent today across every agent"
      >
        {money(spendToday)} today
      </Link>

      <Button
        size="sm"
        variant={company.halted ? "primary" : "quiet"}
        icon={company.halted ? <Play size={14} /> : <OctagonX size={14} />}
        busy={halt.isPending}
        onClick={() => halt.mutate(!company.halted)}
      >
        {company.halted ? "Resume" : "Halt"}
      </Button>

      <ThemeSwitch />
      <AccountMenu />

      <CompanySwitcher
        open={switching}
        onClose={() => setSwitching(false)}
        currentId={company.id}
      />
    </header>
  );
}

function AccountMenu() {
  const { account, signOut, signingOut } = useSession();
  const [open, setOpen] = useState(false);
  if (!account) return null;

  const initials = (account.full_name || account.email)
    .split(/[\s@.]+/)
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-label="Your account"
        className="grid size-7 shrink-0 place-items-center rounded-full bg-accent-wash text-[0.65rem] font-semibold text-accent transition-opacity hover:opacity-80"
      >
        {initials}
      </button>

      {open ? (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} aria-hidden="true" />
          <div className="absolute top-[var(--topbar)] right-3 z-50 w-60 rounded-lg border border-line bg-surface py-1 shadow-[var(--shadow-lifted)]">
            <div className="border-b border-line px-3 py-2">
              <p className="truncate text-sm font-medium text-ink">
                {account.full_name || "Your account"}
              </p>
              <p className="truncate text-xs text-faint">{account.email}</p>
              <p className="mt-1 truncate text-xs text-muted">{account.tenant.name}</p>
            </div>
            <Link
              href="/profile"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 px-3 py-2 text-sm text-ink transition-colors hover:bg-sunken"
            >
              <UserRound size={14} className="text-faint" />
              Your account
              {account.two_factor.enabled ? null : (
                <Badge tone="pending" className="ml-auto">
                  2FA off
                </Badge>
              )}
            </Link>
            <button
              type="button"
              onClick={signOut}
              disabled={signingOut}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-ink transition-colors hover:bg-sunken disabled:opacity-50"
            >
              <LogOut size={14} className="text-faint" />
              Sign out
            </button>
          </div>
        </>
      ) : null}
    </>
  );
}


function ThemeSwitch() {
  const { theme, choose } = useTheme();
  const options = [
    { key: "light", icon: Sun, label: "Light" },
    { key: "system", icon: MonitorCog, label: "Match the system" },
    { key: "dark", icon: Moon, label: "Dark" },
  ] as const;

  return (
    <div className="hidden items-center rounded-md border border-line p-0.5 sm:flex">
      {options.map((option) => (
        <button
          key={option.key}
          type="button"
          aria-label={option.label}
          aria-pressed={theme === option.key}
          onClick={() => choose(option.key)}
          className={cx(
            "rounded p-1 transition-colors",
            theme === option.key ? "bg-sunken text-ink" : "text-faint hover:text-ink",
          )}
        >
          <option.icon size={13} />
        </button>
      ))}
    </div>
  );
}

function CompanySwitcher({
  open,
  onClose,
  currentId,
}: {
  open: boolean;
  onClose: () => void;
  currentId: string;
}) {
  const router = useRouter();
  const { data } = useQuery({ queryKey: keys.companies, queryFn: api.companies.list, enabled: open });

  if (!open) return null;
  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} aria-hidden="true" />
      <div className="absolute top-[var(--topbar)] left-3 z-50 w-72 rounded-lg border border-line bg-surface py-1 shadow-[var(--shadow-lifted)]">
        {(data ?? []).map((entry) => (
          <button
            key={entry.id}
            type="button"
            onClick={() => {
              onClose();
              router.push(`/c/${entry.id}`);
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-sunken"
          >
            <span className="flex-1 truncate">
              <span className="block truncate text-ink">{entry.name}</span>
              <span className="block truncate text-xs text-faint">
                {entry.industry || entry.pack_key.replace(/_/g, " ")}
              </span>
            </span>
            {entry.id === currentId ? <Check size={14} className="text-accent" /> : null}
          </button>
        ))}
        <div className="mt-1 border-t border-line pt-1">
          <Link
            href="/"
            onClick={onClose}
            className="block px-3 py-2 text-sm text-accent transition-colors hover:bg-sunken"
          >
            All companies
          </Link>
        </div>
      </div>
    </>
  );
}
