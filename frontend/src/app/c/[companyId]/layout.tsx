"use client";

import { use, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { keys, useLiveCompany } from "@/lib/hooks";
import { Rail } from "@/components/shell/rail";
import { TopBar } from "@/components/shell/topbar";
import { ErrorNote, Skeleton, cx } from "@/components/ui";

export default function CompanyLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ companyId: string }>;
}) {
  const { companyId } = use(params);
  const [railOpen, setRailOpen] = useState(false);

  const company = useQuery({
    queryKey: keys.company(companyId),
    queryFn: () => api.companies.get(companyId),
  });
  const ops = useQuery({
    queryKey: keys.ops(companyId),
    queryFn: () => api.companies.ops(companyId),
  });
  const inbox = useQuery({
    queryKey: keys.inbox(companyId),
    queryFn: () => api.companies.inbox(companyId),
  });

  // One connection for the whole company, opened here and shared by every page.
  useLiveCompany(companyId);

  if (company.error) {
    return (
      <div className="mx-auto max-w-lg p-8">
        <ErrorNote error={company.error} retry={() => company.refetch()} />
      </div>
    );
  }
  if (!company.data) {
    return (
      <div className="flex min-h-dvh">
        <div className="hidden w-[var(--rail)] border-r border-line lg:block" />
        <div className="flex-1 space-y-3 p-8">
          <Skeleton className="h-7 w-56" />
          <Skeleton className="h-40 w-full" />
        </div>
      </div>
    );
  }

  const waiting = inbox.data?.count ?? 0;

  return (
    <div className="flex min-h-dvh">
      {/* The rail is a drawer below lg and a column above it. */}
      {railOpen ? (
        <div
          className="fixed inset-0 z-40 bg-ink/25 lg:hidden"
          onClick={() => setRailOpen(false)}
          aria-hidden="true"
        />
      ) : null}
      <aside
        className={cx(
          "fixed inset-y-0 left-0 z-50 w-[var(--rail)] shrink-0 overflow-y-auto border-r border-line bg-surface",
          "transition-transform lg:static lg:z-auto lg:translate-x-0",
          railOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <Rail companyId={companyId} badges={{ Inbox: waiting }} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar
          company={company.data}
          ops={ops.data}
          onOpenRail={() => setRailOpen(true)}
        />
        <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-[78rem]">{children}</div>
        </main>
      </div>
    </div>
  );
}
