"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { ACTIVITY_ICONS, timeAgo } from "@/lib/format";
import { useActivity, useResource } from "@/lib/hooks";
import type { ActivityEvent } from "@/lib/types";

/** Right-hand rail that tails everything happening inside the company. */
export default function LiveFeed({ companyId }: { companyId: string }) {
  const [open, setOpen] = useState(true);
  const history = useResource<{ events: ActivityEvent[] }>(
    () => api.companies.activity(companyId, { limit: 60 }),
    [companyId],
  );
  const events = useActivity(companyId, history.data?.events ?? []);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [events.length]);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed right-4 bottom-4 z-40 rounded-full border border-white/15 bg-slate-900 px-4 py-2 text-sm text-slate-300 shadow-lg"
      >
        📡 Live feed
      </button>
    );
  }

  return (
    <aside className="sticky top-0 hidden h-screen w-80 shrink-0 flex-col border-l border-white/10 bg-slate-950/60 xl:flex">
      <header className="flex items-center justify-between border-b border-white/10 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-70" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
          </span>
          <h2 className="text-sm font-semibold text-slate-200">Live activity</h2>
        </div>
        <button onClick={() => setOpen(false)} className="text-xs text-slate-500 hover:text-slate-300">
          hide
        </button>
      </header>

      <div className="flex-1 space-y-2 overflow-y-auto px-3 py-3">
        {events.length === 0 && (
          <p className="px-1 py-6 text-center text-sm text-slate-600">
            Nothing has happened yet. Start a project run and the team&apos;s work shows up here.
          </p>
        )}
        {events.map((event) => (
          <article
            key={event.seq}
            className="rounded-xl border border-white/5 bg-white/[0.03] px-3 py-2 text-sm"
          >
            <div className="flex items-start gap-2">
              <span>{ACTIVITY_ICONS[event.kind] ?? "•"}</span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs text-slate-500">{event.actor}</p>
                <p className="text-slate-300">{event.summary}</p>
                <p className="mt-0.5 text-[11px] text-slate-600">{timeAgo(event.created_at)}</p>
              </div>
            </div>
          </article>
        ))}
        <div ref={bottomRef} />
      </div>
    </aside>
  );
}
