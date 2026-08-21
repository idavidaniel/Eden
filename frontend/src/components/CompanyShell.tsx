"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, type ReactNode } from "react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { Company } from "@/lib/types";
import LiveFeed from "./LiveFeed";
import { ErrorNote, Spinner } from "./ui";

const CompanyContext = createContext<{ company: Company | null; reload: () => void }>({
  company: null,
  reload: () => {},
});

export const useCompany = () => useContext(CompanyContext);

const NAV = [
  { href: "", label: "Overview", icon: "🏠" },
  { href: "/people", label: "People", icon: "🧑‍💼" },
  { href: "/projects", label: "Projects", icon: "📋" },
  { href: "/code", label: "Code", icon: "💻" },
  { href: "/wiki", label: "Wiki", icon: "📚" },
  { href: "/chat", label: "Chat", icon: "💬" },
  { href: "/settings", label: "Settings", icon: "⚙️" },
];

export default function CompanyShell({
  companyId,
  children,
}: {
  companyId: string;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const { data: company, error, reload } = useResource<Company>(
    () => api.companies.get(companyId),
    [companyId],
    { intervalMs: 15000 },
  );

  const base = `/companies/${companyId}`;
  const isActive = (href: string) =>
    href === "" ? pathname === base : pathname.startsWith(`${base}${href}`);

  return (
    <CompanyContext.Provider value={{ company, reload }}>
      <div className="flex min-h-screen">
        <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-white/10 bg-slate-950/60 px-3 py-5 lg:flex">
          <Link href="/" className="mb-1 block px-3 text-xs text-slate-500 hover:text-slate-300">
            ← All companies
          </Link>
          <div className="mb-6 px-3">
            <p className="truncate text-lg font-semibold text-slate-100">
              {company?.name ?? "Loading…"}
            </p>
            <p className="truncate text-xs text-slate-500">{company?.tagline ?? ""}</p>
          </div>

          <nav className="flex flex-1 flex-col gap-1">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={`${base}${item.href}`}
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                  isActive(item.href)
                    ? "bg-white/10 text-white"
                    : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
                }`}
              >
                <span>{item.icon}</span>
                {item.label}
              </Link>
            ))}
          </nav>

          {company && (
            <div className="mt-4 border-t border-white/10 px-3 pt-4 text-xs text-slate-500">
              <p>{company.stats.employees} employees</p>
              <p>
                {company.stats.tickets_done}/{company.stats.tickets} tickets done
              </p>
            </div>
          )}
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <nav className="flex gap-1 overflow-x-auto border-b border-white/10 bg-slate-950/60 px-3 py-2 lg:hidden">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={`${base}${item.href}`}
                className={`rounded-lg px-3 py-1.5 text-sm whitespace-nowrap ${
                  isActive(item.href) ? "bg-white/10 text-white" : "text-slate-400"
                }`}
              >
                {item.icon} {item.label}
              </Link>
            ))}
          </nav>

          <main className="min-w-0 flex-1 px-5 py-6 lg:px-8">
            {error && <ErrorNote>{error}</ErrorNote>}
            {!company && !error && <Spinner label="Loading company…" />}
            {company && children}
          </main>
        </div>

        <LiveFeed companyId={companyId} />
      </div>
    </CompanyContext.Provider>
  );
}
