"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CornerDownLeft, Eye, SquareTerminal } from "lucide-react";
import { api } from "@/lib/api";
import { keys } from "@/lib/hooks";
import {
  Badge,
  Button,
  Dialog,
  Empty,
  Mono,
  Panel,
  PanelHeader,
  Select,
  Textarea,
} from "@/components/ui";
import { useToast } from "@/components/ui/toast";

interface Turn {
  from: "you" | "agent";
  text: string;
  tools?: { name: string; ok: boolean }[];
  status?: string;
  context?: Record<string, unknown>;
}

/**
 * Talking to one employee directly.
 *
 * This is the same endpoint an external caller hits with a token, so what you
 * see here is exactly what an integration gets — including the tool calls and
 * the context report, which are the two things that explain a bad answer.
 */
export function AgentConsole({
  companyId,
  employeeId,
}: {
  companyId: string;
  employeeId: string;
}) {
  const client = useQueryClient();
  const toast = useToast();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [projectId, setProjectId] = useState("");
  const [showPrompt, setShowPrompt] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  const projects = useQuery({
    queryKey: keys.projects(companyId),
    queryFn: () => api.projects.list(companyId),
  });
  const prompt = useQuery({
    queryKey: ["agent", employeeId, "prompt", projectId],
    queryFn: () => api.agents.prompt(employeeId, projectId || undefined),
    enabled: showPrompt,
  });

  const ask = useMutation({
    mutationFn: (message: string) =>
      api.agents.message(employeeId, { message, project_id: projectId || undefined }),
    onSuccess: (reply) => {
      setTurns((current) => [
        ...current,
        {
          from: "agent",
          text: reply.reply,
          tools: reply.tool_calls,
          status: reply.status,
          context: reply.context,
        },
      ]);
      client.invalidateQueries({ queryKey: keys.agentUsage(employeeId) });
      client.invalidateQueries({ queryKey: keys.agentTasks(employeeId) });
    },
    onError: (error: Error) => {
      toast.show("error", error.message);
      setTurns((current) => [
        ...current,
        { from: "agent", text: error.message, status: "error" },
      ]);
    },
  });

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  const send = () => {
    const message = draft.trim();
    if (!message || ask.isPending) return;
    setTurns((current) => [...current, { from: "you", text: message }]);
    setDraft("");
    ask.mutate(message);
  };

  return (
    <Panel>
      <PanelHeader
        icon={<SquareTerminal size={14} />}
        title="Console"
        hint="One turn per message, with their memory, their tools and their budget"
        action={
          <div className="flex items-center gap-2">
            <Select
              value={projectId}
              onChange={(event) => setProjectId(event.target.value)}
              className="h-7 w-44 py-0 text-xs"
              aria-label="Project context"
            >
              <option value="">No project context</option>
              {(projects.data ?? []).map((project) => (
                <option key={project.id} value={project.id}>
                  {project.key} — {project.name}
                </option>
              ))}
            </Select>
            <Button size="sm" variant="quiet" icon={<Eye size={13} />} onClick={() => setShowPrompt(true)}>
              Prompt
            </Button>
          </div>
        }
      />

      <div className="max-h-[26rem] min-h-[14rem] overflow-y-auto px-4 py-3">
        {turns.length ? (
          <ol className="space-y-4">
            {turns.map((turn, index) => (
              <li key={index}>
                <div className="mb-1 text-[0.7rem] font-semibold tracking-wide text-faint uppercase">
                  {turn.from === "you" ? "You" : "Reply"}
                  {turn.status && turn.status !== "done" ? (
                    <Badge
                      tone={turn.status === "refused" || turn.status === "error" ? "fail" : "pending"}
                      className="ml-2"
                    >
                      {turn.status.replace(/_/g, " ")}
                    </Badge>
                  ) : null}
                </div>
                <p className="text-sm whitespace-pre-wrap text-ink">{turn.text}</p>
                {turn.tools?.length ? (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {turn.tools.map((call, position) => (
                      <Badge key={position} tone={call.ok === false ? "fail" : "neutral"} mono>
                        {call.name}
                      </Badge>
                    ))}
                  </div>
                ) : null}
                {turn.context ? <ContextReport report={turn.context} /> : null}
              </li>
            ))}
          </ol>
        ) : (
          <Empty icon={<SquareTerminal size={20} />} title="Nothing said yet">
            Ask them something. The same request works over HTTP with their token.
          </Empty>
        )}
        <div ref={bottom} />
      </div>

      <div className="border-t border-line p-3">
        <Textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) send();
          }}
          placeholder="What are you working on?"
          className="min-h-16"
        />
        <div className="mt-2 flex items-center justify-between">
          <span className="text-xs text-faint">⌘↵ to send</span>
          <Button
            variant="primary"
            size="sm"
            icon={<CornerDownLeft size={13} />}
            busy={ask.isPending}
            onClick={send}
            disabled={!draft.trim()}
          >
            Send
          </Button>
        </div>
      </div>

      <Dialog
        open={showPrompt}
        onClose={() => setShowPrompt(false)}
        title="The system prompt, exactly as it runs"
        hint="Nothing is hidden from you that is not hidden from them."
        wide
      >
        <pre className="scroll-x max-h-[60vh] overflow-y-auto rounded-md border border-line bg-sunken p-3 font-mono text-xs whitespace-pre-wrap text-ink">
          {prompt.data?.system_prompt ?? "Loading…"}
        </pre>
      </Dialog>
    </Panel>
  );
}

/** What went into the turn, tier by tier — the answer to "why did it say that". */
function ContextReport({ report }: { report: Record<string, unknown> }) {
  const tiers = Object.entries(report).filter(
    ([key, value]) => typeof value === "object" && value !== null && key !== "total_chars",
  ) as [string, { chars?: number; trimmed?: boolean }][];
  const tokens = report.estimated_tokens;

  return (
    <details className="mt-2">
      <summary className="cursor-pointer text-xs text-muted hover:text-ink">
        Context: about {typeof tokens === "number" ? tokens.toLocaleString() : "?"} tokens
      </summary>
      <ul className="mt-1.5 space-y-0.5">
        {tiers.map(([tier, detail]) => (
          <li key={tier} className="flex items-center gap-2 text-xs">
            <Mono className="w-24 text-faint">{tier}</Mono>
            <span className="tnum text-muted">{(detail.chars ?? 0).toLocaleString()} chars</span>
            {detail.trimmed ? <Badge tone="pending">trimmed to fit</Badge> : null}
          </li>
        ))}
      </ul>
    </details>
  );
}
