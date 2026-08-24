"use client";

import Link from "next/link";
import {
  createElement,
  forwardRef,
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { X } from "lucide-react";

export const cx = (...parts: (string | false | null | undefined)[]) =>
  parts.filter(Boolean).join(" ");

/* -------------------------------------------------------------------------- */
/* Button                                                                      */
/* -------------------------------------------------------------------------- */

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "quiet" | "danger";
  size?: "sm" | "md";
  icon?: ReactNode;
  busy?: boolean;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", icon, busy, children, className, disabled, ...rest },
  ref,
) {
  const variants = {
    primary: "bg-accent text-accent-ink hover:bg-accent-hover border-transparent",
    secondary: "bg-surface text-ink border-line-strong hover:bg-sunken",
    quiet: "bg-transparent text-muted border-transparent hover:bg-sunken hover:text-ink",
    danger: "bg-transparent text-fail border-line-strong hover:bg-fail-wash",
  };
  const sizes = { sm: "h-7 px-2.5 text-xs gap-1.5", md: "h-9 px-3.5 text-sm gap-2" };
  return (
    <button
      ref={ref}
      disabled={disabled || busy}
      className={cx(
        "inline-flex items-center justify-center rounded-md border font-medium",
        "transition-colors disabled:pointer-events-none disabled:opacity-45",
        variants[variant],
        sizes[size],
        className,
      )}
      {...rest}
    >
      {busy ? <Spinner /> : icon}
      {children}
    </button>
  );
});

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Working"
      className={cx(
        "inline-block size-3.5 shrink-0 animate-spin rounded-full",
        "border-2 border-current border-r-transparent opacity-70",
        className,
      )}
    />
  );
}

/* -------------------------------------------------------------------------- */
/* Surfaces                                                                    */
/* -------------------------------------------------------------------------- */

export function Panel({
  children,
  className = "",
  as = "section",
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "article" | "aside";
}) {
  return createElement(
    as,
    { className: cx("rounded-lg border border-line bg-surface", className) },
    children,
  );
}

export function PanelHeader({
  title,
  hint,
  action,
  icon,
}: {
  title: ReactNode;
  hint?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-3">
      <div className="min-w-0">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-ink">
          {icon}
          {title}
        </h2>
        {hint ? <p className="mt-0.5 text-xs text-muted">{hint}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </header>
  );
}

export function PageHeader({
  eyebrow,
  title,
  hint,
  action,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  hint?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 pb-5">
      <div className="min-w-0">
        {eyebrow ? (
          <div className="mb-1 text-[0.7rem] font-semibold tracking-[0.09em] text-faint uppercase">
            {eyebrow}
          </div>
        ) : null}
        <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
        {hint ? <p className="mt-1 max-w-prose text-sm text-muted">{hint}</p> : null}
      </div>
      {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
    </header>
  );
}

export function Empty({
  icon,
  title,
  children,
  action,
}: {
  icon?: ReactNode;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-14 text-center">
      {icon ? <div className="text-faint">{icon}</div> : null}
      <p className="text-sm font-medium text-ink">{title}</p>
      {children ? <p className="max-w-sm text-sm text-muted">{children}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={cx("animate-pulse rounded bg-sunken", className)} />;
}

export function ErrorNote({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="rounded-lg border border-line bg-fail-wash px-4 py-3">
      <p className="text-sm font-medium text-fail">That did not load.</p>
      <p className="mt-1 text-sm text-ink">{message}</p>
      {retry ? (
        <Button size="sm" className="mt-3" onClick={retry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Labels and status                                                           */
/* -------------------------------------------------------------------------- */

export type Tone = "neutral" | "pass" | "pending" | "fail" | "accent";

const TONES: Record<Tone, string> = {
  neutral: "bg-idle-wash text-muted border-line",
  pass: "bg-pass-wash text-pass border-transparent",
  pending: "bg-pending-wash text-pending border-transparent",
  fail: "bg-fail-wash text-fail border-transparent",
  accent: "bg-accent-wash text-accent border-transparent",
};

export function Badge({
  children,
  tone = "neutral",
  mono,
  className = "",
}: {
  children: ReactNode;
  tone?: Tone;
  mono?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[0.7rem] font-medium whitespace-nowrap",
        mono && "font-mono tracking-tight",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/** State as a shape as well as a colour, so it reads without relying on hue. */
export function Dot({ tone = "neutral" }: { tone?: Tone }) {
  const fills: Record<Tone, string> = {
    neutral: "bg-idle",
    pass: "bg-pass",
    pending: "bg-pending",
    fail: "bg-fail",
    accent: "bg-accent",
  };
  return <span className={cx("inline-block size-1.5 shrink-0 rounded-full", fills[tone])} />;
}

export function Mono({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={cx("font-mono text-[0.78rem] tracking-tight", className)}>{children}</span>;
}

/* -------------------------------------------------------------------------- */
/* Tables                                                                      */
/* -------------------------------------------------------------------------- */

export function Table({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className="scroll-x">
      <table className={cx("w-full min-w-[36rem] border-collapse text-sm", className)}>
        {children}
      </table>
    </div>
  );
}

export function Th({
  children,
  align = "left",
  className = "",
}: {
  children?: ReactNode;
  align?: "left" | "right";
  className?: string;
}) {
  return (
    <th
      className={cx(
        "border-b border-line px-3 py-2 text-[0.7rem] font-semibold tracking-wider text-faint uppercase",
        align === "right" ? "text-right" : "text-left",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function Td({
  children,
  align = "left",
  className = "",
}: {
  children?: ReactNode;
  align?: "left" | "right";
  className?: string;
}) {
  return (
    <td
      className={cx(
        "border-b border-line px-3 py-2 align-top",
        align === "right" ? "text-right" : "text-left",
        className,
      )}
    >
      {children}
    </td>
  );
}

export function Row({
  children,
  href,
  onClick,
}: {
  children: ReactNode;
  href?: string;
  onClick?: () => void;
}) {
  const interactive = Boolean(href || onClick);
  return (
    <tr
      onClick={onClick}
      className={cx(
        "group",
        interactive && "cursor-pointer transition-colors hover:bg-sunken",
      )}
    >
      {children}
    </tr>
  );
}

/** A cell whose whole area is a link, so the row is genuinely clickable. */
export function LinkCell({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className="block -mx-3 -my-2 px-3 py-2 hover:text-accent">
      {children}
    </Link>
  );
}

/* -------------------------------------------------------------------------- */
/* Form fields                                                                 */
/* -------------------------------------------------------------------------- */

export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: ReactNode;
  error?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-ink">{label}</span>
      {children}
      {error ? (
        <span className="mt-1 block text-xs text-fail">{error}</span>
      ) : hint ? (
        <span className="mt-1 block text-xs text-muted">{hint}</span>
      ) : null}
    </label>
  );
}

const controlClass =
  "w-full rounded-md border border-line-strong bg-surface px-2.5 py-1.5 text-sm text-ink " +
  "placeholder:text-faint focus:border-accent focus:outline-none";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    return <input ref={ref} className={cx(controlClass, className)} {...rest} />;
  },
);

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...rest }, ref) {
    return (
      <textarea ref={ref} className={cx(controlClass, "min-h-24 resize-y", className)} {...rest} />
    );
  },
);

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, children, ...rest }, ref) {
    return (
      <select ref={ref} className={cx(controlClass, "pr-8", className)} {...rest}>
        {children}
      </select>
    );
  },
);

export function Toggle({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  hint?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <p className="text-sm font-medium text-ink">{label}</p>
        {hint ? <p className="mt-0.5 text-xs text-muted">{hint}</p> : null}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cx(
          "relative mt-0.5 h-5 w-9 shrink-0 rounded-full border transition-colors disabled:opacity-45",
          checked ? "border-transparent bg-accent" : "border-line-strong bg-sunken",
        )}
      >
        <span
          className={cx(
            "absolute top-0.5 size-3.5 rounded-full bg-surface transition-[left]",
            checked ? "left-[1.15rem]" : "left-0.5",
          )}
        />
      </button>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Tabs and dialogs                                                            */
/* -------------------------------------------------------------------------- */

export function Tabs({
  tabs,
  active,
  onSelect,
}: {
  tabs: { key: string; label: string; count?: number }[];
  active: string;
  onSelect: (key: string) => void;
}) {
  return (
    <div className="scroll-x border-b border-line" role="tablist">
      <div className="flex min-w-max gap-1">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            role="tab"
            aria-selected={tab.key === active}
            onClick={() => onSelect(tab.key)}
            className={cx(
              "relative -mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors",
              tab.key === active
                ? "border-accent text-ink"
                : "border-transparent text-muted hover:text-ink",
            )}
          >
            {tab.label}
            {typeof tab.count === "number" ? (
              <span className="tnum ml-1.5 text-xs text-faint">{tab.count}</span>
            ) : null}
          </button>
        ))}
      </div>
    </div>
  );
}

export function Dialog({
  open,
  onClose,
  title,
  hint,
  children,
  footer,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  hint?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    panel.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 sm:p-8">
      <div
        className="fixed inset-0 bg-ink/25 backdrop-blur-[1px]"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={cx(
          "relative w-full rounded-xl border border-line bg-surface shadow-[var(--shadow-lifted)]",
          wide ? "max-w-3xl" : "max-w-lg",
        )}
      >
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-ink">{title}</h2>
            {hint ? <p className="mt-0.5 text-sm text-muted">{hint}</p> : null}
          </div>
          <Button variant="quiet" size="sm" onClick={onClose} aria-label="Close">
            <X size={15} />
          </Button>
        </header>
        <div className="px-5 py-4">{children}</div>
        {footer ? (
          <footer className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</footer>
        ) : null}
      </div>
    </div>
  );
}

/** Reveal something once and only once — a minted secret, mostly. */
export function Reveal({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="rounded-md border border-line bg-sunken p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className="text-xs font-medium text-ink">{label}</span>
        <Button
          size="sm"
          variant="quiet"
          onClick={async () => {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 1600);
          }}
        >
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <code className="block break-all font-mono text-xs text-ink">{value}</code>
    </div>
  );
}
