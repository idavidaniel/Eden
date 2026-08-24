"use client";

import { use, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import CodeMirror from "@uiw/react-codemirror";
import { javascript } from "@codemirror/lang-javascript";
import { markdown } from "@codemirror/lang-markdown";
import { python } from "@codemirror/lang-python";
import { oneDark } from "@codemirror/theme-one-dark";
import {
  File as FileIcon,
  Folder,
  GitCommitHorizontal,
  Hammer,
  MonitorPlay,
  Save,
} from "lucide-react";
import { api } from "@/lib/api";
import { bytes, timeAgo } from "@/lib/format";
import { keys, useTheme } from "@/lib/hooks";
import {
  Badge,
  Button,
  Empty,
  Mono,
  PageHeader,
  Panel,
  PanelHeader,
  Select,
  Skeleton,
  Tabs,
  cx,
} from "@/components/ui";
import { useToast } from "@/components/ui/toast";

/** The workspace an agent actually writes into, and the preview it builds. */
export default function Studio({ params }: { params: Promise<{ companyId: string }> }) {
  const { companyId } = use(params);
  const [projectId, setProjectId] = useState("");
  const [tab, setTab] = useState("files");

  const projects = useQuery({
    queryKey: keys.projects(companyId),
    queryFn: () => api.projects.list(companyId),
  });
  const active = projectId || projects.data?.[0]?.id || "";

  return (
    <div className="space-y-5">
      <PageHeader
        title="Studio"
        hint="The repository the team works in, its history, and whether it runs."
        action={
          <Select
            value={active}
            onChange={(event) => setProjectId(event.target.value)}
            className="w-56"
            aria-label="Project"
          >
            {(projects.data ?? []).map((project) => (
              <option key={project.id} value={project.id}>
                {project.key} — {project.name}
              </option>
            ))}
          </Select>
        }
      />

      {!active ? (
        <Panel>
          <Empty icon={<Folder size={22} />} title="No project to open">
            Create a project and its workspace appears here.
          </Empty>
        </Panel>
      ) : (
        <>
          <Tabs
            tabs={[
              { key: "files", label: "Files" },
              { key: "history", label: "History" },
              { key: "preview", label: "Preview" },
            ]}
            active={tab}
            onSelect={setTab}
          />
          {tab === "files" ? (
            <Files projectId={active} />
          ) : tab === "history" ? (
            <History projectId={active} />
          ) : (
            <Preview projectId={active} />
          )}
        </>
      )}
    </div>
  );
}

function languageFor(path: string) {
  if (/\.(ts|tsx|js|jsx|json)$/i.test(path)) return [javascript({ typescript: true, jsx: true })];
  if (/\.py$/i.test(path)) return [python()];
  if (/\.(md|markdown)$/i.test(path)) return [markdown()];
  return [];
}

function Files({ projectId }: { projectId: string }) {
  const client = useQueryClient();
  const toast = useToast();
  const { resolved } = useTheme();
  const [path, setPath] = useState<string | null>(null);
  const [buffer, setBuffer] = useState<{ path: string; text: string } | null>(null);

  const tree = useQuery({
    queryKey: ["files", projectId],
    queryFn: () => api.workspace.files(projectId),
  });
  const file = useQuery({
    queryKey: ["file", projectId, path],
    queryFn: () => api.workspace.file(projectId, path!),
    enabled: Boolean(path),
  });

  const save = useMutation({
    mutationFn: () => api.workspace.save(projectId, buffer!.path, buffer!.text, "Edited by you"),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["file", projectId, path] });
      client.invalidateQueries({ queryKey: ["commits", projectId] });
      setBuffer(null);
      toast.show("ok", "Saved and committed.");
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  const text = buffer?.path === path ? buffer.text : (file.data?.content ?? "");
  const dirty = buffer?.path === path && buffer.text !== file.data?.content;

  return (
    <div className="grid gap-5 lg:grid-cols-[18rem_1fr]">
      <Panel className="max-h-[34rem] self-start overflow-y-auto">
        <PanelHeader title="Workspace" hint={tree.data?.root} />
        {tree.isLoading ? (
          <Skeleton className="m-3 h-40" />
        ) : tree.data?.entries.length ? (
          <ul className="p-1">
            {tree.data.entries.map((entry) => (
              <li key={entry.path}>
                <button
                  type="button"
                  disabled={entry.is_dir}
                  onClick={() => setPath(entry.path)}
                  className={cx(
                    "flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-xs transition-colors",
                    entry.is_dir
                      ? "cursor-default text-faint"
                      : entry.path === path
                        ? "bg-accent-wash text-accent"
                        : "text-muted hover:bg-sunken hover:text-ink",
                  )}
                >
                  {entry.is_dir ? (
                    <Folder size={12} className="shrink-0" />
                  ) : (
                    <FileIcon size={12} className="shrink-0" />
                  )}
                  <span className="truncate font-mono">{entry.path}</span>
                  {!entry.is_dir ? (
                    <span className="tnum ml-auto shrink-0 text-[0.65rem] text-faint">
                      {bytes(entry.size)}
                    </span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <Empty title="Empty workspace">
            Nothing has been written here yet.
          </Empty>
        )}
      </Panel>

      <Panel className="min-w-0">
        <PanelHeader
          title={path ? <Mono>{path}</Mono> : "No file open"}
          hint={dirty ? "Unsaved changes" : undefined}
          action={
            path ? (
              <Button
                size="sm"
                variant="primary"
                icon={<Save size={12} />}
                disabled={!dirty}
                busy={save.isPending}
                onClick={() => save.mutate()}
              >
                Save
              </Button>
            ) : null
          }
        />
        {path ? (
          file.isLoading ? (
            <Skeleton className="m-3 h-80" />
          ) : (
            <CodeMirror
              value={text}
              height="30rem"
              theme={resolved === "dark" ? oneDark : undefined}
              extensions={languageFor(path)}
              onChange={(next) => setBuffer({ path, text: next })}
            />
          )
        ) : (
          <Empty icon={<FileIcon size={20} />} title="Pick a file">
            You are editing the same working tree the agents commit into.
          </Empty>
        )}
      </Panel>
    </div>
  );
}

function History({ projectId }: { projectId: string }) {
  const [sha, setSha] = useState<string | null>(null);
  const commits = useQuery({
    queryKey: ["commits", projectId],
    queryFn: () => api.workspace.commits(projectId),
  });
  const diff = useQuery({
    queryKey: ["commit", projectId, sha],
    queryFn: () => api.workspace.commit(projectId, sha!),
    enabled: Boolean(sha),
  });

  return (
    <div className="grid gap-5 lg:grid-cols-[20rem_1fr]">
      <Panel className="max-h-[34rem] self-start overflow-y-auto">
        <PanelHeader icon={<GitCommitHorizontal size={14} />} title="Commits" />
        {commits.data?.length ? (
          <ul className="divide-y divide-line">
            {commits.data.map((commit) => (
              <li key={commit.sha}>
                <button
                  type="button"
                  onClick={() => setSha(commit.sha)}
                  className={cx(
                    "w-full px-3 py-2 text-left transition-colors",
                    commit.sha === sha ? "bg-accent-wash" : "hover:bg-sunken",
                  )}
                >
                  <p className="truncate text-sm text-ink">{commit.message}</p>
                  <p className="mt-0.5 flex items-center gap-2 text-xs text-faint">
                    <Mono>{commit.sha.slice(0, 7)}</Mono>
                    <span>{commit.author}</span>
                    <span>{timeAgo(commit.at)}</span>
                  </p>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <Empty title="No commits yet" />
        )}
      </Panel>

      <Panel className="min-w-0">
        <PanelHeader title={sha ? <Mono>{sha.slice(0, 12)}</Mono> : "No commit selected"} />
        {sha ? (
          <pre className="scroll-x max-h-[30rem] overflow-y-auto p-3 font-mono text-xs whitespace-pre text-ink">
            {diff.data?.diff ?? "Loading…"}
          </pre>
        ) : (
          <Empty title="Pick a commit to see what changed" />
        )}
      </Panel>
    </div>
  );
}

function Preview({ projectId }: { projectId: string }) {
  const client = useQueryClient();
  const toast = useToast();
  const [pkg, setPkg] = useState("");

  const packages = useQuery({
    queryKey: ["packages", projectId],
    queryFn: () => api.projects.packages(projectId),
  });
  const preview = useQuery({
    queryKey: ["preview", projectId],
    queryFn: () => api.projects.preview(projectId),
    refetchInterval: (query) =>
      query.state.data?.status === "building" ? 3000 : false,
  });

  const build = useMutation({
    mutationFn: () => api.projects.buildPreview(projectId, pkg || packages.data!.packages[0]),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["preview", projectId] });
      toast.show("info", "Building. This can take a few minutes the first time.");
    },
    onError: (error: Error) => toast.show("error", error.message),
  });

  const autofix = useMutation({
    mutationFn: () => api.projects.autofix(projectId),
    onSuccess: (result) => toast.show("info", `Debugging with: ${result.command}`),
    onError: (error: Error) => toast.show("error", error.message),
  });

  const state = preview.data;

  return (
    <div className="space-y-4">
      <Panel>
        <PanelHeader
          icon={<MonitorPlay size={14} />}
          title="Preview"
          hint="Builds what the team wrote and serves it, so you can use the thing rather than read about it."
          action={
            <div className="flex items-center gap-2">
              {(packages.data?.packages.length ?? 0) > 1 ? (
                <Select
                  value={pkg}
                  onChange={(event) => setPkg(event.target.value)}
                  className="h-8 w-40 py-0 text-xs"
                  aria-label="Package"
                >
                  {packages.data!.packages.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </Select>
              ) : null}
              <Button
                size="sm"
                variant="primary"
                busy={build.isPending || state?.status === "building"}
                disabled={!packages.data?.packages.length}
                onClick={() => build.mutate()}
              >
                Build
              </Button>
            </div>
          }
        />

        <div className="space-y-3 p-4">
          {state?.status ? (
            <div className="flex items-center gap-2">
              <Badge
                tone={
                  state.status === "ready"
                    ? "pass"
                    : state.status === "failed"
                      ? "fail"
                      : "pending"
                }
              >
                {state.status}
              </Badge>
              {state.package ? <Mono className="text-faint">{state.package}</Mono> : null}
              {state.url ? (
                <a
                  href={state.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="text-sm text-accent hover:underline"
                >
                  Open it
                </a>
              ) : null}
            </div>
          ) : null}

          {state?.error ? (
            <div className="rounded-md border border-line bg-fail-wash px-3 py-2">
              <p className="text-sm text-fail">{state.error}</p>
              <Button
                size="sm"
                className="mt-2"
                icon={<Hammer size={12} />}
                busy={autofix.isPending}
                onClick={() => autofix.mutate()}
              >
                Have them debug it
              </Button>
            </div>
          ) : null}

          {state?.log ? (
            <pre className="scroll-x max-h-80 overflow-y-auto rounded-md border border-line bg-sunken p-3 font-mono text-xs whitespace-pre text-ink">
              {state.log}
            </pre>
          ) : (
            <p className="text-sm text-muted">
              Nothing has been built yet.
              {packages.data?.packages.length
                ? " Pick a package and build it."
                : " No buildable package was found in the workspace."}
            </p>
          )}
        </div>
      </Panel>
    </div>
  );
}
