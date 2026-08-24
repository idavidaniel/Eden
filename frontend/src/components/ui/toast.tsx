"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { AlertCircle, CheckCircle2, Info } from "lucide-react";
import { cx } from "./index";

type Kind = "ok" | "error" | "info";
interface Toast {
  id: number;
  kind: Kind;
  message: string;
}

const ToastContext = createContext<{ show: (kind: Kind, message: string) => void }>({
  show: () => {},
});

export const useToast = () => useContext(ToastContext);

/** Say what happened, in the past tense, and get out of the way. */
export function ToastHost({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const show = useCallback((kind: Kind, message: string) => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current.slice(-3), { id, kind, message }]);
    setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), 5200);
  }, []);

  const value = useMemo(() => ({ show }), [show]);
  const icons = { ok: CheckCircle2, error: AlertCircle, info: Info };
  const tones = {
    ok: "border-pass/40 bg-pass-wash text-pass",
    error: "border-fail/40 bg-fail-wash text-fail",
    info: "border-line bg-surface text-ink",
  };

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed right-4 bottom-4 z-[60] flex w-80 flex-col gap-2"
      >
        {toasts.map((toast) => {
          const Icon = icons[toast.kind];
          return (
            <div
              key={toast.id}
              className={cx(
                "pointer-events-auto flex items-start gap-2 rounded-lg border px-3 py-2.5",
                "shadow-[var(--shadow-lifted)]",
                tones[toast.kind],
              )}
            >
              <Icon size={15} className="mt-0.5 shrink-0" />
              <p className="text-sm">{toast.message}</p>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
