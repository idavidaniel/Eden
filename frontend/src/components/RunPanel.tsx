"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import type { ProjectDetail, Run } from "@/lib/types";
import { Button, Card, ErrorNote, Textarea } from "./ui";

const LIVE = new Set(["queued", "running", "paused"]);

/** Start / pause / cancel the autonomous run, and show what phase it is in. */
export default function RunPanel({
  project,
  onChanged,
}: {
  project: ProjectDetail;
  onChanged: () => void;
}) {
  const [brief, setBrief] = useState(project.brief);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const latest = project.runs[0];
  const live = latest && LIVE.has(latest.status);

  const run = useResource<Run>(
    () => (live ? api.runs.get(latest.id) : Promise.resolve(latest)),
    [latest?.id, live],
    { intervalMs: live ? 3000 : undefined },
  );
  const current = run.data ?? latest;
  const note = typeof current?.stats?.note === "string" ? current.stats.note : "";

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try {
      await action();
      onChanged();
      run.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold tracking-wide text-slate-300 uppercase">
            Autonomous run
          </h2>
          {current ? (
            <>
              <p className="mt-1 text-sm text-slate-400">
                <StatusPill status={current.status} /> phase{" "}
                <span className="text-slate-300">{current.phase}</span> · started{" "}
                {timeAgo(current.created_at)}
                {current.stats?.tickets ? (
                  <>
                    {" "}
                    · {current.stats.done}/{current.stats.tickets} tickets done
                  </>
                ) : null}
              </p>
              {/* A finished run that left work behind should say so, rather than
                  looking like a board that stopped moving for no reason. */}
              {!live && note && (
                <p className="mt-2 rounded-lg border border-amber-500/25 bg-amber-500/5 px-3 py-2 text-sm text-amber-200">
                  {note}
                </p>
              )}
            </>
          ) : (
            <p className="mt-1 text-sm text-slate-500">
              The manager will break the brief into tickets and hand them to the right people.
            </p>
          )}
          {current?.error && <p className="mt-2 text-sm text-rose-400">{current.error}</p>}
        </div>

        <div className="flex items-center gap-2">
          {live ? (
            <>
              {current?.status === "paused" ? (
                <Button size="sm" disabled={busy} onClick={() => act(() => api.runs.control(latest.id, "resume"))}>
                  ▶ Resume
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="subtle"
                  disabled={busy}
                  onClick={() => act(() => api.runs.control(latest.id, "pause"))}
                >
                  ⏸ Pause
                </Button>
              )}
              <Button
                size="sm"
                variant="danger"
                disabled={busy}
                onClick={() => act(() => api.runs.control(latest.id, "cancel"))}
              >
                Stop
              </Button>
            </>
          ) : (
            <Button disabled={busy} onClick={() => act(() => api.projects.startRun(project.id, brief))}>
              {busy ? "Starting…" : current ? "▶ Run again" : "▶ Start run"}
            </Button>
          )}
        </div>
      </div>

      {!live && (
        <div className="mt-4">
          <Textarea
            rows={3}
            value={brief}
            onChange={(event) => setBrief(event.target.value)}
            placeholder="What should the team build?"
          />
          <p className="mt-1 text-xs text-slate-600">
            Edited briefs are saved with the next run. Existing to-do tickets are worked first.
          </p>
        </div>
      )}

      {error && <div className="mt-3">
        <ErrorNote>{error}</ErrorNote>
      </div>}
    </Card>
  );
}

function StatusPill({ status }: { status: string }) {
  const tones: Record<string, string> = {
    running: "text-amber-300",
    queued: "text-sky-300",
    paused: "text-slate-300",
    completed: "text-emerald-300",
    failed: "text-rose-300",
    cancelled: "text-slate-400",
  };
  return <span className={`font-medium ${tones[status] ?? "text-slate-300"}`}>{status}</span>;
}
