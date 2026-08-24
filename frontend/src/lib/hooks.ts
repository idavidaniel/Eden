"use client";

import { useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { api } from "./api";
import { eventGroup } from "./format";
import { subscribe } from "./stream";
import type { ActivityEvent } from "./types";

/** Query keys in one place, so an invalidation cannot miss a list by typo. */
export const keys = {
  companies: ["companies"] as const,
  company: (id: string) => ["company", id] as const,
  ops: (id: string) => ["ops", id] as const,
  pack: (id: string) => ["pack", id] as const,
  employees: (id: string) => ["employees", id] as const,
  agent: (id: string) => ["agent", id] as const,
  agentMemory: (id: string, q: string) => ["agent", id, "memory", q] as const,
  agentTasks: (id: string) => ["agent", id, "tasks"] as const,
  agentTokens: (id: string) => ["agent", id, "tokens"] as const,
  agentUsage: (id: string) => ["agent", id, "usage"] as const,
  projects: (id: string) => ["projects", id] as const,
  project: (id: string) => ["project", id] as const,
  workItems: (id: string) => ["work-items", id] as const,
  workItem: (id: string) => ["work-item", id] as const,
  workItemChecks: (id: string) => ["work-item", id, "checks"] as const,
  artifacts: (id: string) => ["artifacts", id] as const,
  artifact: (id: string) => ["artifact", id] as const,
  ledger: (id: string) => ["ledger", id] as const,
  inbox: (id: string) => ["inbox", id] as const,
  toolCalls: (id: string) => ["tool-calls", id] as const,
  sources: (id: string) => ["sources", id] as const,
  performance: (id: string) => ["performance", id] as const,
  meetings: (id: string) => ["meetings", id] as const,
  connections: (id: string) => ["connections", id] as const,
  documents: (id: string) => ["documents", id] as const,
  channels: (id: string) => ["channels", id] as const,
  activity: (id: string) => ["activity", id] as const,
  health: ["health"] as const,
};

/**
 * Live activity, plus the invalidations it implies.
 *
 * An event is not just a line in a feed: `check.result` means a work item's
 * verdict changed, `artifact.version` means the deliverable list is stale. One
 * subscription drives both, so the interface stays honest without polling.
 */
export function useLiveCompany(companyId: string) {
  const client = useQueryClient();
  // Only what the stream delivered lives in state. History stays in the query
  // cache and the two are joined at render time, so they cannot drift apart
  // and switching company cannot leave the previous one's events behind.
  const [streamed, setStreamed] = useState<{ id: string; events: ActivityEvent[] }>({
    id: companyId,
    events: [],
  });

  const history = useQuery({
    queryKey: keys.activity(companyId),
    queryFn: () => api.companies.activity(companyId),
    enabled: Boolean(companyId),
  });

  const ready = Boolean(history.data);
  const cursor = history.data?.cursor ?? 0;

  useEffect(() => {
    if (!companyId || !ready) return;
    return subscribe(companyId, cursor, (event) => {
      setStreamed((current) => {
        const events = current.id === companyId ? current.events : [];
        if (events.some((item) => item.seq === event.seq)) return current;
        return { id: companyId, events: [...events, event].slice(-500) };
      });
      invalidateFor(client, companyId, event);
    });
    // `cursor` is where the connection resumes from; it is read once at open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, client, ready]);

  const events = useMemo(() => {
    const seed = history.data?.events ?? [];
    if (streamed.id !== companyId) return seed;
    return [...seed, ...streamed.events.filter((event) => event.seq > cursor)];
  }, [history.data, streamed, companyId, cursor]);

  return { events, loading: history.isLoading, error: history.error };
}

function invalidateFor(
  client: ReturnType<typeof useQueryClient>,
  companyId: string,
  event: ActivityEvent,
) {
  const stale: QueryKey[] = [keys.ops(companyId)];
  const group = eventGroup(event.kind);

  if (group === "work" || group === "verification") {
    stale.push(keys.projects(companyId), keys.artifacts(companyId), keys.ledger(companyId));
    const projectId = event.project_id;
    if (projectId) stale.push(keys.project(projectId), keys.workItems(projectId));
    const workItemId = event.payload?.work_item_id ?? event.payload?.ticket_id;
    if (typeof workItemId === "string") {
      stale.push(keys.workItem(workItemId), keys.workItemChecks(workItemId));
    }
  }
  if (group === "verification") stale.push(keys.inbox(companyId));
  if (group === "people") stale.push(keys.employees(companyId));
  if (group === "messages") stale.push(keys.inbox(companyId));
  if (group === "security") stale.push(keys.toolCalls(companyId), keys.sources(companyId));
  if (group === "knowledge") stale.push(keys.documents(companyId));

  for (const key of stale) client.invalidateQueries({ queryKey: key });
}

/** A task's steps as they land, straight from the agent's own SSE endpoint. */
export function useTaskStream(employeeId: string, taskId: string | null) {
  // Keyed by task rather than cleared in an effect, so a stale frame arriving
  // after a switch cannot be mistaken for the new task's first step.
  const [live, setLive] = useState<{
    id: string | null;
    steps: Record<string, unknown>[];
    task: Record<string, unknown> | null;
  }>({ id: taskId, steps: [], task: null });

  useEffect(() => {
    if (!taskId) return;
    const source = new EventSource(`/api/backend/agents/${employeeId}/tasks/${taskId}/stream`);

    source.addEventListener("step", (frame) => {
      try {
        const step = JSON.parse((frame as MessageEvent).data);
        setLive((current) =>
          current.id === taskId
            ? { ...current, steps: [...current.steps, step] }
            : { id: taskId, steps: [step], task: null },
        );
      } catch {
        /* ignore a malformed frame rather than losing the stream */
      }
    });
    source.addEventListener("task", (frame) => {
      try {
        const next = JSON.parse((frame as MessageEvent).data);
        setLive((current) =>
          current.id === taskId
            ? { ...current, task: next }
            : { id: taskId, steps: [], task: next },
        );
        if (["done", "failed", "cancelled"].includes(next.status)) source.close();
      } catch {
        /* as above */
      }
    });
    return () => source.close();
  }, [employeeId, taskId]);

  const current = live.id === taskId ? live : { steps: [], task: null };
  return { steps: current.steps, task: current.task };
}

/** Persisted theme, with system as a real third state rather than a default. */
export function useTheme() {
  // The inline script in the root layout has already stamped the element, so
  // the DOM is the source of truth. `useSyncExternalStore` reads it without an
  // effect and keeps the server render ("system") from mismatching.
  const theme = useSyncExternalStore(subscribeToTheme, readTheme, () => "system" as const);

  const choose = (next: "system" | "light" | "dark") => {
    if (next === "system") {
      localStorage.removeItem("eden-theme");
      delete document.documentElement.dataset.theme;
    } else {
      localStorage.setItem("eden-theme", next);
      document.documentElement.dataset.theme = next;
    }
    for (const listener of themeListeners) listener();
  };

  return { theme, choose };
}

const themeListeners = new Set<() => void>();

function subscribeToTheme(listener: () => void) {
  themeListeners.add(listener);
  return () => themeListeners.delete(listener);
}

function readTheme(): "system" | "light" | "dark" {
  const stamped = document.documentElement.dataset.theme;
  return stamped === "light" || stamped === "dark" ? stamped : "system";
}
