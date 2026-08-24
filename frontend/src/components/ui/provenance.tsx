"use client";

import { useState } from "react";
import {
  BadgeCheck,
  Ban,
  CircleDashed,
  CircleSlash,
  FileCheck2,
  Fingerprint,
  Link2,
  TriangleAlert,
  UserRoundCheck,
} from "lucide-react";
import type { CheckKind, CheckResult, Verdict } from "@/lib/types";
import { Badge, Mono, cx, type Tone } from "./index";

/**
 * The chip is the argument this whole product makes: nothing is done because
 * somebody said so, it is done because something checkable says so. It shows
 * the verdict, and opening it shows the evidence that produced the verdict.
 */

export const VERDICT_TONE: Record<Verdict, Tone> = {
  pass: "pass",
  fail: "fail",
  error: "fail",
  pending: "pending",
  skipped: "neutral",
};

export const VERDICT_LABEL: Record<Verdict, string> = {
  pass: "Passed",
  fail: "Failed",
  error: "Errored",
  pending: "Waiting",
  skipped: "Not run",
};

const VERDICT_ICON = {
  pass: BadgeCheck,
  fail: Ban,
  error: TriangleAlert,
  pending: CircleDashed,
  skipped: CircleSlash,
};

/** What kind of evidence stands behind a verdict — not decoration, the method. */
export const CHECK_ICON: Record<CheckKind, typeof BadgeCheck> = {
  command: FileCheck2,
  schema: FileCheck2,
  assertion: FileCheck2,
  citation: Link2,
  rubric: UserRoundCheck,
  human: UserRoundCheck,
};

export const CHECK_METHOD: Record<CheckKind, string> = {
  command: "a command was run and its exit status recorded",
  schema: "the file was parsed against a schema",
  assertion: "the text was matched against rules",
  citation: "every quote was looked up in the source it claims",
  rubric: "a panel of evaluators voted, and votes without a real quote were discarded",
  human: "a person decided",
};

export function VerdictChip({
  status,
  label,
  className = "",
}: {
  status: Verdict;
  label?: string;
  className?: string;
}) {
  const Icon = VERDICT_ICON[status];
  return (
    <Badge tone={VERDICT_TONE[status]} className={className}>
      <Icon size={11} />
      {label ?? VERDICT_LABEL[status]}
    </Badge>
  );
}

/** A content hash, shortened but copyable, because it is the actual proof. */
export function HashChip({ hash, label = "sha256" }: { hash: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  if (!hash) return null;
  return (
    <button
      type="button"
      title={`${label} ${hash}`}
      onClick={async () => {
        await navigator.clipboard.writeText(hash);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className={cx(
        "inline-flex items-center gap-1 rounded border border-line bg-sunken px-1.5 py-0.5",
        "font-mono text-[0.7rem] text-muted transition-colors hover:text-ink",
      )}
    >
      <Fingerprint size={10} />
      {copied ? "copied" : hash.slice(0, 10)}
    </button>
  );
}

/** One check result, expandable into the detail and evidence behind it. */
export function ProvenanceRow({ result }: { result: CheckResult }) {
  const [open, setOpen] = useState(false);
  const Icon = CHECK_ICON[result.check_kind] ?? FileCheck2;
  const evidence = Object.entries(result.evidence ?? {}).filter(([key]) => key !== "required");

  return (
    <div className="border-b border-line last:border-0">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-start gap-3 px-3 py-2.5 text-left transition-colors hover:bg-sunken"
      >
        <VerdictChip status={result.status} />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5 text-sm font-medium text-ink">
            <Icon size={12} className="shrink-0 text-faint" />
            {result.check_key}
          </span>
          <span className="mt-0.5 block truncate text-xs text-muted">{result.detail}</span>
        </span>
        {result.duration_ms ? (
          <span className="tnum shrink-0 pt-0.5 text-xs text-faint">{result.duration_ms} ms</span>
        ) : null}
      </button>

      {open ? (
        <div className="space-y-3 bg-sunken px-3 pt-1 pb-3">
          <p className="text-xs text-muted">
            <span className="font-medium text-ink">How this was decided:</span>{" "}
            {CHECK_METHOD[result.check_kind] ?? "recorded by the platform"}.
          </p>
          {result.detail ? <p className="text-sm text-ink">{result.detail}</p> : null}
          {evidence.length ? (
            <dl className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-[10rem_1fr]">
              {evidence.map(([key, value]) => (
                <div key={key} className="contents">
                  <dt className="font-mono text-faint">{key}</dt>
                  <dd className="scroll-x">
                    <Mono className="whitespace-pre-wrap text-ink">
                      {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
                    </Mono>
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}
          {result.created_at ? (
            <p className="text-xs text-faint">
              Recorded {new Date(result.created_at).toLocaleString()}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** The one-line answer for a set of results, for a header or a row. */
export function VerdictSummary({ results }: { results: CheckResult[] }) {
  if (!results.length) {
    return <span className="text-xs text-faint">No checks have run</span>;
  }
  const failed = results.filter((r) => r.status === "fail" || r.status === "error").length;
  const pending = results.filter((r) => r.status === "pending").length;
  const passed = results.filter((r) => r.status === "pass").length;

  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {passed ? <VerdictChip status="pass" label={`${passed} passed`} /> : null}
      {failed ? <VerdictChip status="fail" label={`${failed} failed`} /> : null}
      {pending ? <VerdictChip status="pending" label={`${pending} waiting`} /> : null}
    </span>
  );
}
