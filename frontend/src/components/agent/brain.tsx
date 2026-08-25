"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, Lock, Search, Sparkles, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { timeAgo, titleCase } from "@/lib/format";
import { keys } from "@/lib/hooks";
import type { Memory, MemoryBlock } from "@/lib/types";
import {
  Badge,
  Button,
  Empty,
  Field,
  Input,
  Mono,
  Panel,
  PanelHeader,
  Skeleton,
  Textarea,
} from "@/components/ui";
import { useToast } from "@/components/ui/toast";

const BLOCK_HINTS: Record<string, string> = {
  persona: "Who they are. Always in the prompt.",
  company: "What the company is and how it works.",
  focus: "What they are on right now.",
  human: "What they have learnt about you.",
};

const KIND_TONE = {
  fact: "neutral",
  procedure: "accent",
  episode: "neutral",
  preference: "neutral",
} as const;

/**
 * Memory is the part of an agent you can actually inspect and correct, so it
 * gets its own tab: the always-loaded blocks, and the searchable store with the
 * retrieval preview that shows what a given question would pull in.
 */
export function AgentBrain({ employeeId }: { employeeId: string }) {
  const [search, setSearch] = useState("");
  const [pending, setPending] = useState("");

  const memory = useQuery({
    queryKey: keys.agentMemory(employeeId, search),
    queryFn: () => api.agents.memory(employeeId, search || undefined),
  });

  return (
    <div className="grid gap-5 lg:grid-cols-[20rem_1fr]">
      <div className="space-y-3">
        <h2 className="text-[0.7rem] font-semibold tracking-[0.09em] text-faint uppercase">
          Always loaded
        </h2>
        {memory.data
          ? memory.data.blocks.map((block) => (
              <BlockEditor key={block.id} employeeId={employeeId} block={block} />
            ))
          : [0, 1, 2, 3].map((index) => <Skeleton key={index} className="h-28" />)}
      </div>

      <div className="space-y-4">
        <Panel>
          <PanelHeader
            icon={<Search size={14} />}
            title="Retrieved on demand"
            hint={
              memory.data
                ? `${memory.data.counts.total} kept${
                    memory.data.counts.showing < memory.data.counts.total
                      ? `, ${memory.data.counts.showing} shown`
                      : ""
                  } · ${
                    memory.data.retrieval_mode === "vector"
                      ? "searched by meaning"
                      : "searched by words (no embedding model)"
                  }`
                : "Loading"
            }
          />
          <div className="border-b border-line p-3">
            <form
              onSubmit={(event) => {
                event.preventDefault();
                setSearch(pending);
              }}
              className="flex gap-2"
            >
              <Input
                value={pending}
                onChange={(event) => setPending(event.target.value)}
                placeholder="Ask what they would remember — “when does Northwind get billed?”"
              />
              <Button type="submit" variant="secondary">
                Preview
              </Button>
              {search ? (
                <Button
                  variant="quiet"
                  onClick={() => {
                    setSearch("");
                    setPending("");
                  }}
                >
                  Clear
                </Button>
              ) : null}
            </form>
            {search ? (
              <p className="mt-2 text-xs text-muted">
                This is exactly what would be pulled into a turn asking that, in this order.
              </p>
            ) : null}
          </div>

          {memory.data?.memories.length ? (
            <ul className="divide-y divide-line">
              {memory.data.memories.map((row) => (
                <MemoryRow key={row.id} employeeId={employeeId} memory={row} />
              ))}
            </ul>
          ) : (
            <Empty icon={<Brain size={20} />} title={search ? "Nothing matches" : "Nothing learnt yet"}>
              {search
                ? "They would go into that turn without anything relevant."
                : "Facts get remembered as work happens. Procedures are only distilled from work whose checks passed."}
            </Empty>
          )}
        </Panel>

        <TeachBox employeeId={employeeId} />
      </div>
    </div>
  );
}

function BlockEditor({ employeeId, block }: { employeeId: string; block: MemoryBlock }) {
  const client = useQueryClient();
  const toast = useToast();
  const [content, setContent] = useState(block.content);
  const dirty = content !== block.content;

  const save = useMutation({
    mutationFn: () => api.agents.setBlock(employeeId, block.label, { content }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["agent", employeeId, "memory"] });
      toast.show("ok", `Their ${block.label} block is updated.`);
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  const over = content.length > block.char_limit;

  return (
    <Panel className="p-3">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-xs font-semibold text-ink">
          {titleCase(block.label)}
          {block.pinned ? <Lock size={11} className="text-faint" /> : null}
        </span>
        <span className={`tnum text-[0.7rem] ${over ? "text-fail" : "text-faint"}`}>
          {content.length}/{block.char_limit}
        </span>
      </div>
      <p className="mb-2 text-xs text-muted">{BLOCK_HINTS[block.label]}</p>
      <Textarea
        value={content}
        onChange={(event) => setContent(event.target.value)}
        className="min-h-20 text-xs"
      />
      <div className="mt-2 flex items-center justify-between">
        <span className="text-[0.7rem] text-faint">
          v{block.version} · {block.updated_by}
        </span>
        {dirty ? (
          <Button size="sm" variant="primary" busy={save.isPending} onClick={() => save.mutate()}>
            Save
          </Button>
        ) : null}
      </div>
    </Panel>
  );
}

function MemoryRow({ employeeId, memory }: { employeeId: string; memory: Memory }) {
  const client = useQueryClient();
  const toast = useToast();
  const invalidate = () => client.invalidateQueries({ queryKey: ["agent", employeeId, "memory"] });

  const forget = useMutation({
    mutationFn: () => api.agents.forget(employeeId, memory.id),
    onSuccess: () => {
      invalidate();
      toast.show("info", "Archived. It is kept, but no longer retrieved.");
    },
    onError: (error: Error) => toast.show("error", error.message),
  });
  const promote = useMutation({
    mutationFn: () => api.agents.promote(employeeId, memory.id),
    onSuccess: () => {
      invalidate();
      toast.show("ok", "Everyone in the company can retrieve this now.");
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  return (
    <li className="group px-4 py-3">
      <div className="flex items-start gap-2">
        <Badge tone={KIND_TONE[memory.kind as keyof typeof KIND_TONE] ?? "neutral"}>
          {memory.kind}
        </Badge>
        {memory.outcome ? (
          <Badge tone={memory.outcome === "rejected" || memory.outcome === "reopened" ? "fail" : "pass"}>
            {memory.outcome}
          </Badge>
        ) : null}
        {memory.scope === "company" ? <Badge tone="accent">shared</Badge> : null}
        <span className="flex-1" />
        {memory.score != null ? (
          <Mono className="text-faint" >{memory.score.toFixed(3)}</Mono>
        ) : null}
      </div>

      <p className="mt-1.5 text-sm text-ink">{memory.title}</p>
      {memory.body ? <p className="mt-0.5 text-xs text-muted">{memory.body}</p> : null}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.7rem] text-faint">
        <span className="tnum">used {memory.uses}×</span>
        <span className="tnum">confidence {memory.confidence.toFixed(2)}</span>
        {memory.used_by.length > 1 ? <span>{memory.used_by.length} agents</span> : null}
        {!memory.has_embedding ? <span>word-matched only</span> : null}
        <span>{timeAgo(memory.created_at)}</span>
        <span className="flex-1" />
        <span className="flex gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          {memory.scope !== "company" ? (
            <Button size="sm" variant="quiet" busy={promote.isPending} onClick={() => promote.mutate()}>
              Share
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="quiet"
            icon={<Trash2 size={12} />}
            busy={forget.isPending}
            onClick={() => forget.mutate()}
            aria-label="Archive this memory"
          />
        </span>
      </div>
    </li>
  );
}

function TeachBox({ employeeId }: { employeeId: string }) {
  const client = useQueryClient();
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");

  const teach = useMutation({
    mutationFn: () => api.agents.teach(employeeId, { title, body, kind: "fact" }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["agent", employeeId, "memory"] });
      setTitle("");
      setBody("");
      toast.show("ok", "They know that now.");
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  return (
    <Panel>
      <PanelHeader
        icon={<Sparkles size={14} />}
        title="Tell them something"
        hint="Facts only. A procedure has to be earned by work whose checks passed."
      />
      <div className="space-y-3 p-3">
        <Field label="What is true">
          <Input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Northwind bills monthly, in arrears"
          />
        </Field>
        <Field label="Detail" hint="Optional. Anything that would help them use it correctly.">
          <Textarea
            value={body}
            onChange={(event) => setBody(event.target.value)}
            className="min-h-16"
          />
        </Field>
        <div className="flex justify-end">
          <Button
            variant="primary"
            size="sm"
            disabled={!title.trim()}
            busy={teach.isPending}
            onClick={() => teach.mutate()}
          >
            Teach them
          </Button>
        </div>
      </div>
    </Panel>
  );
}
