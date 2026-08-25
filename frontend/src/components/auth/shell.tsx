"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { ShieldCheck } from "lucide-react";

/**
 * The frame around every sign-in screen.
 *
 * The right-hand column says what this product is, because the sign-in page is
 * the one screen a new person sees before they have any idea what they signed
 * up for. It disappears below lg, where the form is all that matters.
 */
export function AuthShell({
  title,
  hint,
  children,
  footer,
}: {
  title: string;
  hint?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-2">
      <main className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <Link
            href="/"
            className="mb-8 inline-flex items-center gap-2 text-sm font-semibold text-ink"
          >
            <ShieldCheck size={17} className="text-accent" />
            Eden
          </Link>

          <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
          {hint ? <p className="mt-1.5 text-sm text-muted">{hint}</p> : null}

          <div className="mt-6">{children}</div>

          {footer ? <div className="mt-6 text-sm text-muted">{footer}</div> : null}
        </div>
      </main>

      <aside className="hidden border-l border-line bg-sunken px-12 py-16 lg:flex lg:items-center">
        <div className="max-w-md">
          <h2 className="text-lg font-semibold tracking-tight text-ink">
            Work that has to prove itself
          </h2>
          <p className="mt-3 text-sm leading-relaxed text-muted">
            Eden runs companies of AI employees. Each one has its own memory, its own tools and
            its own API. Nothing they produce counts as done because they said so — something
            checkable has to agree, and the record can be re-proved later.
          </p>
          <dl className="mt-8 space-y-5">
            {[
              [
                "Every deliverable is pinned to its bytes",
                "Edit a file after it passed and the hash stops matching. Re-verification says so.",
              ],
              [
                "Every agent is addressable",
                "One token, one employee. It cannot be used to drive a colleague.",
              ],
              [
                "Every consequential act is chained",
                "Approvals, checks and deliverables, in order, each committing to the one before.",
              ],
            ].map(([heading, body]) => (
              <div key={heading}>
                <dt className="text-sm font-medium text-ink">{heading}</dt>
                <dd className="mt-0.5 text-sm text-muted">{body}</dd>
              </div>
            ))}
          </dl>
        </div>
      </aside>
    </div>
  );
}

export function AuthError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p
      role="alert"
      className="mb-4 rounded-md border border-line bg-fail-wash px-3 py-2 text-sm text-fail"
    >
      {message}
    </p>
  );
}
