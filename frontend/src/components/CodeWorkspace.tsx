"use client";

import { markdown } from "@codemirror/lang-markdown";
import { javascript } from "@codemirror/lang-javascript";
import { python } from "@codemirror/lang-python";
import { oneDark } from "@codemirror/theme-one-dark";
import CodeMirror from "@uiw/react-codemirror";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { Commit, FileEntry } from "@/lib/types";
import { Button, Card, ErrorNote, Spinner } from "./ui";

function extensionsFor(path: string) {
  if (path.endsWith(".py")) return [python()];
  if (/\.(ts|tsx|js|jsx|json)$/.test(path)) return [javascript({ typescript: path.endsWith("x") })];
  if (path.endsWith(".md")) return [markdown()];
  return [];
}

/** An editor over the project's git workspace: tree, file, history and diffs. */
export default function CodeWorkspace({
  companyId,
  projectId,
}: {
  companyId: string;
  projectId: string;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"files" | "history">("files");
  const [openCommit, setOpenCommit] = useState<string | null>(null);

  const files = useResource<{ root: string; entries: FileEntry[] }>(
    () => api.workspace.files(projectId),
    [projectId],
    { intervalMs: 6000 },
  );
  const commits = useResource<Commit[]>(() => api.workspace.commits(projectId), [projectId], {
    intervalMs: 8000,
  });
  const diff = useResource<{ diff: string }>(
    () => (openCommit ? api.workspace.commit(projectId, openCommit) : Promise.resolve({ diff: "" })),
    [openCommit],
  );

  const fileEntries = (files.data?.entries ?? []).filter((entry) => entry.type === "file");
  // Chosen file wins; otherwise show the first one, so the pane is never blank.
  const openPath = selected ?? fileEntries[0]?.path ?? null;

  useEffect(() => {
    if (!openPath) return;
    let current = true;
    api.workspace
      .file(projectId, openPath)
      .then((file) => {
        if (!current) return;
        setDraft(file.content);
        setDirty(false);
        setError("");
      })
      .catch((err) => current && setError((err as Error).message));
    return () => {
      current = false;
    };
  }, [projectId, openPath]);

  const save = async () => {
    if (!openPath) return;
    setSaving(true);
    try {
      await api.workspace.save(projectId, openPath, draft, `Edit ${openPath} from the dashboard`);
      setDirty(false);
      commits.reload();
      files.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link
            href={`/companies/${companyId}/projects/${projectId}`}
            className="text-xs text-slate-500 hover:text-slate-300"
          >
            ← Board
          </Link>
          <h1 className="mt-1 text-2xl font-bold text-slate-100">Workspace</h1>
          <p className="font-mono text-xs text-slate-600">{files.data?.root}</p>
        </div>
        <div className="flex items-center gap-2">
          {dirty && <span className="text-xs text-amber-400">unsaved changes</span>}
          <Button size="sm" onClick={save} disabled={!dirty || saving}>
            {saving ? "Committing…" : "Save & commit"}
          </Button>
        </div>
      </header>

      {error && <ErrorNote>{error}</ErrorNote>}

      <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
        <Card className="h-fit p-2">
          <div className="mb-2 flex rounded-lg border border-white/10 p-0.5">
            {(["files", "history"] as const).map((mode) => (
              <button
                key={mode}
                onClick={() => setTab(mode)}
                className={`flex-1 rounded-md px-2 py-1 text-xs capitalize ${
                  tab === mode ? "bg-white/10 text-white" : "text-slate-400"
                }`}
              >
                {mode}
              </button>
            ))}
          </div>

          {tab === "files" && (
            <div className="max-h-[32rem] overflow-y-auto">
              {files.loading && <Spinner />}
              {fileEntries.length === 0 && (
                <p className="px-2 py-6 text-center text-xs text-slate-600">
                  Empty workspace. The team fills it as they work.
                </p>
              )}
              {fileEntries.map((entry) => (
                <button
                  key={entry.path}
                  onClick={() => setSelected(entry.path)}
                  className={`block w-full truncate rounded-md px-2 py-1.5 text-left font-mono text-xs transition-colors ${
                    openPath === entry.path
                      ? "bg-blue-500/15 text-blue-200"
                      : "text-slate-400 hover:bg-white/5"
                  }`}
                  title={entry.path}
                >
                  {entry.path}
                </button>
              ))}
            </div>
          )}

          {tab === "history" && (
            <div className="max-h-[32rem] space-y-1 overflow-y-auto">
              {commits.data?.length === 0 && (
                <p className="px-2 py-6 text-center text-xs text-slate-600">No commits yet.</p>
              )}
              {commits.data?.map((commit) => (
                <button
                  key={commit.sha}
                  onClick={() => setOpenCommit(commit.sha === openCommit ? null : commit.sha)}
                  className={`block w-full rounded-md px-2 py-1.5 text-left transition-colors hover:bg-white/5 ${
                    openCommit === commit.sha ? "bg-white/10" : ""
                  }`}
                >
                  <p className="truncate text-xs text-slate-300">{commit.subject}</p>
                  <p className="font-mono text-[11px] text-slate-600">
                    {commit.sha} · {commit.author} · {commit.when}
                  </p>
                </button>
              ))}
            </div>
          )}
        </Card>

        <Card className="overflow-hidden">
          {openCommit ? (
            <div>
              <header className="flex items-center justify-between border-b border-white/10 px-4 py-2">
                <span className="font-mono text-xs text-slate-400">commit {openCommit}</span>
                <button
                  onClick={() => setOpenCommit(null)}
                  className="text-xs text-slate-500 hover:text-slate-200"
                >
                  back to editor
                </button>
              </header>
              <pre className="max-h-[34rem] overflow-auto p-4 font-mono text-xs whitespace-pre text-slate-300">
                {diff.data?.diff ?? "…"}
              </pre>
            </div>
          ) : openPath ? (
            <div>
              <header className="border-b border-white/10 px-4 py-2 font-mono text-xs text-slate-400">
                {openPath}
              </header>
              <CodeMirror
                value={draft}
                height="34rem"
                theme={oneDark}
                extensions={extensionsFor(openPath)}
                onChange={(value) => {
                  setDraft(value);
                  setDirty(true);
                }}
              />
            </div>
          ) : (
            <p className="p-10 text-center text-sm text-slate-600">Select a file to open it.</p>
          )}
        </Card>
      </div>
    </div>
  );
}
