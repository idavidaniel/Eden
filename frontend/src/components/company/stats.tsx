"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { cx } from "@/components/ui";

/**
 * A number with the thing it measures, and where to go to argue with it.
 * Every tile links somewhere: a figure you cannot drill into is a claim.
 */
export function Stat({
  label,
  value,
  hint,
  href,
  tone = "neutral",
  icon,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  href?: string;
  tone?: "neutral" | "pass" | "pending" | "fail";
  icon?: ReactNode;
}) {
  const tones = {
    neutral: "text-ink",
    pass: "text-pass",
    pending: "text-pending",
    fail: "text-fail",
  };
  const inner = (
    <>
      <div className="flex items-center gap-1.5 text-[0.7rem] font-medium tracking-wide text-faint uppercase">
        {icon}
        {label}
      </div>
      <div className={cx("tnum mt-1.5 text-2xl font-semibold tracking-tight", tones[tone])}>
        {value}
      </div>
      {hint ? <div className="mt-0.5 text-xs text-muted">{hint}</div> : null}
    </>
  );

  const className = cx(
    "block rounded-lg border border-line bg-surface px-4 py-3",
    href && "transition-colors hover:border-line-strong hover:bg-sunken",
  );
  return href ? (
    <Link href={href} className={className}>
      {inner}
    </Link>
  ) : (
    <div className={className}>{inner}</div>
  );
}

export function StatRow({ children }: { children: ReactNode }) {
  return <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{children}</div>;
}
