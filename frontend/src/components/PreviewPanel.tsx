"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { useResource } from "@/lib/hooks";
import type { PreviewState } from "@/lib/types";
import { Button, Card, ErrorNote, SectionTitle, Select } from "./ui";

/** Builds the app for the web and shows it, since the container has no screen. */
export default function PreviewPanel({ projectId }: { projectId: string }) {
  const [chosen, setChosen] = useState("");
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(true);

  const packages = useResource<{ packages: string[] }>(
    () => api.projects.packages(projectId),
    [projectId],
  );
  const preview = useResource<PreviewState>(() => api.projects.preview(projectId), [projectId], {
    // Poll while a build is running; builds take a couple of minutes.
    intervalMs: 5000,
  });

  const state = preview.data ?? {};
  const building = state.status === "building";
  const options = packages.data?.packages ?? [];
  const target = chosen || state.package || options[0] || "";

  const start = async () => {
    setError("");
    try {
      await api.projects.buildPreview(projectId, target);
      preview.reload();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <Card className="p-5">
      <SectionTitle
        action={
          <button
            onClick={() => setExpanded((current) => !current)}
            className="text-xs text-slate-500 hover:text-slate-300"
          >
            {expanded ? "collapse" : "expand"}
          </button>
        }
      >
        Live preview
      </SectionTitle>

      {options.length === 0 ? (
        <p className="text-sm text-slate-500">
          No Flutter package in the workspace yet — a preview needs a directory with a
          <code className="mx-1 font-mono text-xs">pubspec.yaml</code>.
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <Select
            className="w-56"
            value={target}
            onChange={(event) => setChosen(event.target.value)}
            disabled={building}
          >
            {options.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </Select>
          <Button onClick={start} disabled={building || !target}>
            {building ? "Building…" : "Build web preview"}
          </Button>
          {state.status === "ready" && state.url && (
            <a
              href={state.url}
              target="_blank"
              rel="noreferrer"
              className="text-sm text-blue-400 hover:underline"
            >
              open in a new tab ↗
            </a>
          )}
          {state.built_at && state.status === "ready" && (
            <span className="text-xs text-slate-600">built {timeAgo(state.built_at)}</span>
          )}
        </div>
      )}

      {building && (
        <p className="mt-3 text-sm text-amber-300">
          Compiling {state.package} for the web. This takes a minute or two the first time.
        </p>
      )}

      {error && <div className="mt-3"><ErrorNote>{error}</ErrorNote></div>}

      {state.status === "failed" && (
        <div className="mt-3">
          <p className="mb-1 text-sm text-rose-300">The build failed:</p>
          <pre className="max-h-48 overflow-auto rounded-lg border border-rose-500/20 bg-rose-500/5 p-3 font-mono text-xs whitespace-pre-wrap text-rose-200">
            {state.error}
          </pre>
        </div>
      )}

      {expanded && state.status === "ready" && state.url && (
        <div className="mt-4 overflow-hidden rounded-xl border border-white/10 bg-black">
          <iframe
            key={state.built_at}
            src={state.url}
            title="App preview"
            className="h-[36rem] w-full"
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
          />
        </div>
      )}
    </Card>
  );
}
