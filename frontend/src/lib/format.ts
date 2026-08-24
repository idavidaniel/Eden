import type { Tone } from "@/components/ui";
import type { WorkStatus } from "./types";

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 45) return "just now";
  const minutes = seconds / 60;
  if (minutes < 60) return `${Math.round(minutes)}m ago`;
  const hours = minutes / 60;
  if (hours < 24) return `${Math.round(hours)}h ago`;
  const days = hours / 24;
  if (days < 30) return `${Math.round(days)}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function when(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

/** Costs are stored in millionths of a dollar; nothing else in the UI divides. */
export function money(micros: number | null | undefined): string {
  if (!micros) return "$0.00";
  const dollars = micros / 1_000_000;
  if (dollars > 0 && dollars < 0.01) return "<$0.01";
  return `$${dollars.toFixed(dollars < 100 ? 2 : 0)}`;
}

export function count(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value < 1000) return String(value);
  if (value < 1_000_000) return `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)}k`;
  return `${(value / 1_000_000).toFixed(1)}M`;
}

export function percent(fraction: number | null | undefined): string {
  return fraction == null ? "—" : `${Math.round(fraction * 100)}%`;
}

export function bytes(size: number | null | undefined): string {
  if (!size) return "0 B";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} kB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export function titleCase(value: string): string {
  return value.replace(/[_-]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export const STATUS_LABELS: Record<string, string> = {
  backlog: "Backlog",
  todo: "To do",
  in_progress: "In progress",
  in_review: "In review",
  done: "Done",
  blocked: "Blocked",
};

/** Board order, which is also the order work actually moves in. */
export const BOARD_COLUMNS: WorkStatus[] = [
  "backlog",
  "todo",
  "in_progress",
  "in_review",
  "done",
];

export const STATUS_TONES: Record<string, Tone> = {
  backlog: "neutral",
  todo: "neutral",
  in_progress: "accent",
  in_review: "pending",
  done: "pass",
  blocked: "fail",
};

export const EMPLOYEE_TONES: Record<string, Tone> = {
  idle: "neutral",
  working: "accent",
  blocked: "fail",
  waiting: "pending",
  offboarded: "neutral",
};

/** Grouped so the activity feed can be filtered by what kind of thing happened. */
export const EVENT_GROUPS: Record<string, string> = {
  company: "company",
  employee: "people",
  project: "work",
  run: "work",
  ticket: "work",
  work_item: "work",
  code: "code",
  preview: "code",
  autofix: "code",
  check: "verification",
  artifact: "verification",
  approval: "verification",
  agent: "messages",
  chat: "messages",
  wiki: "knowledge",
  identity: "security",
  token: "security",
  tool: "security",
};

export function eventGroup(kind: string): string {
  return EVENT_GROUPS[kind.split(".")[0]] ?? "other";
}
