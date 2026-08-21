"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getHealth, streamTask, type Health } from "@/lib/api";

const DEFAULT_PERSONA = "You are a senior data analyst AI employee.";
const DEFAULT_HUMAN = "The client wants clear, concise answers with the reasoning shown.";

export default function ControlPlane() {
  const [task, setTask] = useState("");
  const [persona, setPersona] = useState(DEFAULT_PERSONA);
  const [human, setHuman] = useState(DEFAULT_HUMAN);
  const [threadId, setThreadId] = useState("demo-thread");
  const [reasoning, setReasoning] = useState("");
  const [answer, setAnswer] = useState("");
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const reasoningRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then(setHealth)
      .catch(() => setHealth(null));
    return () => controller.abort();
  }, []);

  // Keep the newest tokens in view while the trace grows.
  useEffect(() => {
    const node = reasoningRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [reasoning]);

  const dispatch = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setRunning(true);
    setReasoning("");
    setAnswer("");
    setError("");

    try {
      const events = streamTask(
        { thread_id: threadId, message: task, persona_block: persona, human_block: human },
        controller.signal,
      );
      for await (const event of events) {
        if (event.type === "reasoning") setReasoning((prev) => prev + event.delta);
        else if (event.type === "content") setAnswer((prev) => prev + event.delta);
        else if (event.type === "error") setError(event.delta);
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") setError((err as Error).message);
    } finally {
      setRunning(false);
    }
  }, [task, persona, human, threadId]);

  const stop = () => abortRef.current?.abort();

  return (
    <div className="min-h-screen p-6 sm:p-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-8">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-r from-blue-500 to-purple-600 font-bold shadow-[0_0_15px_rgba(59,130,246,0.5)]">
              AI
            </div>
            <div>
              <h1 className="bg-gradient-to-r from-blue-400 to-purple-400 bg-clip-text text-2xl font-extrabold tracking-tight text-transparent sm:text-3xl">
                EaaS Control Plane
              </h1>
              <p className="text-sm text-slate-400">
                {health ? `${health.model} · ${health.persistence} state · ${health.cache} cache` : "Backend unreachable"}
              </p>
            </div>
          </div>
          <StatusPill health={health} />
        </header>

        <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
          <section className="glass-panel flex h-fit flex-col gap-4 p-6">
            <h2 className="border-b border-white/10 pb-2 text-lg font-semibold">Assign task</h2>

            <Field label="Thread">
              <input
                className={inputClass}
                value={threadId}
                onChange={(event) => setThreadId(event.target.value)}
              />
            </Field>

            <Field label="Persona (core memory)">
              <textarea
                className={inputClass}
                rows={3}
                value={persona}
                onChange={(event) => setPersona(event.target.value)}
              />
            </Field>

            <Field label="About the human (core memory)">
              <textarea
                className={inputClass}
                rows={2}
                value={human}
                onChange={(event) => setHuman(event.target.value)}
              />
            </Field>

            <Field label="Instruction">
              <textarea
                className={inputClass}
                rows={4}
                placeholder="e.g. Summarise Q3 churn drivers in three bullets."
                value={task}
                onChange={(event) => setTask(event.target.value)}
              />
            </Field>

            <div className="flex gap-3">
              <button
                onClick={dispatch}
                disabled={running || !task.trim()}
                className="flex-1 rounded-lg bg-gradient-to-r from-blue-600 to-purple-600 py-3 font-medium shadow-[0_0_15px_rgba(59,130,246,0.3)] transition-all hover:from-blue-500 hover:to-purple-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {running ? "Running…" : "Dispatch task"}
              </button>
              {running && (
                <button
                  onClick={stop}
                  className="rounded-lg border border-white/15 px-4 text-sm text-slate-300 transition-colors hover:bg-white/5"
                >
                  Stop
                </button>
              )}
            </div>

            {error && (
              <p className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
                {error}
              </p>
            )}
          </section>

          <section className="flex flex-col gap-6 lg:col-span-2">
            <Panel title="Inner monologue (reasoning stream)" accent="text-purple-400">
              <pre
                ref={reasoningRef}
                className="max-h-80 min-h-[200px] flex-1 overflow-y-auto rounded-xl border border-slate-800 bg-slate-950/80 p-4 font-mono text-sm whitespace-pre-wrap text-slate-400"
              >
                {reasoning || (running ? "Waiting for the first token…" : "Awaiting task execution…")}
              </pre>
            </Panel>

            <Panel title="Final synthesized output" accent="text-blue-400">
              <div className="min-h-[150px] flex-1 rounded-xl border border-slate-700 bg-slate-900/60 p-4 leading-relaxed whitespace-pre-wrap text-slate-100">
                {answer || <span className="text-slate-500 italic">No output yet.</span>}
              </div>
            </Panel>
          </section>
        </div>
      </div>
    </div>
  );
}

const inputClass =
  "w-full resize-none rounded-lg border border-slate-700 bg-slate-900/80 p-3 text-sm text-slate-200 outline-none transition-all focus:border-blue-500 focus:ring-1 focus:ring-blue-500";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm text-slate-400">{label}</span>
      {children}
    </label>
  );
}

function Panel({
  title,
  accent,
  children,
}: {
  title: string;
  accent: string;
  children: React.ReactNode;
}) {
  return (
    <div className="glass-panel flex flex-1 flex-col gap-4 p-6">
      <h2 className={`text-lg font-semibold ${accent}`}>{title}</h2>
      {children}
    </div>
  );
}

function StatusPill({ health }: { health: Health | null }) {
  const ok = health?.status === "ok" && health.llm_configured;
  const label = !health ? "Backend offline" : health.llm_configured ? "Runtime active" : "No API key";
  return (
    <span
      className={`glass-panel px-4 py-2 text-sm font-medium ${ok ? "text-green-400" : "text-amber-400"}`}
    >
      ● {label}
    </span>
  );
}
