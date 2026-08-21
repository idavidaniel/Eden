export function timeAgo(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 45) return "just now";
  const minutes = seconds / 60;
  if (minutes < 60) return `${Math.round(minutes)}m ago`;
  const hours = minutes / 60;
  if (hours < 24) return `${Math.round(hours)}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function initials(name: string): string {
  return name
    .split(" ")
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export const STATUS_LABELS: Record<string, string> = {
  backlog: "Backlog",
  todo: "To do",
  in_progress: "In progress",
  in_review: "In review",
  done: "Done",
  blocked: "Blocked",
};

export const STATUS_TONES: Record<string, string> = {
  backlog: "border-slate-600/60 bg-slate-700/30 text-slate-300",
  todo: "border-sky-500/40 bg-sky-500/10 text-sky-300",
  in_progress: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  in_review: "border-violet-500/40 bg-violet-500/10 text-violet-300",
  done: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  blocked: "border-rose-500/40 bg-rose-500/10 text-rose-300",
};

export const ACTIVITY_ICONS: Record<string, string> = {
  "company.created": "🏢",
  "employee.hired": "🎉",
  "employee.offboarded": "👋",
  "project.created": "📁",
  "run.queued": "⏳",
  "run.started": "▶️",
  "run.planning": "🧭",
  "run.completed": "✅",
  "run.failed": "💥",
  "run.cancelled": "🛑",
  "ticket.created": "🎫",
  "ticket.started": "🔨",
  "ticket.updated": "🔄",
  "ticket.comment": "💬",
  "ticket.step_limit": "⏳",
  "code.write": "📝",
  "code.delete": "🗑️",
  "code.commit": "📦",
  "wiki.published": "📚",
  "chat.message": "💬",
  "identity.revealed": "🔑",
  "identity.rotated": "♻️",
};
