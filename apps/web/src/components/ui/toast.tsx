import { X } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/** A tiny, dependency-free toast primitive — enough to surface an action failure (an approve
 *  or cancel that the server rejected) instead of a silent no-op. Not a general notification
 *  system; keep it small. Errors auto-dismiss after a few seconds or on click. */

type ToastVariant = "default" | "error" | "success";

interface ToastRecord {
  id: number;
  title: string;
  description?: string;
  variant: ToastVariant;
}

export interface ToastOptions {
  title: string;
  description?: string;
  variant?: ToastVariant;
}

interface ToastContextValue {
  toast: (opts: ToastOptions) => void;
}

// Default is a no-op so a component that calls useToast() outside a provider (e.g. an isolated
// unit test) simply doesn't toast, rather than crashing.
const ToastContext = createContext<ToastContextValue>({ toast: () => {} });

let _nextId = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastRecord[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (opts: ToastOptions) => {
      const id = ++_nextId;
      setToasts((prev) => [
        ...prev,
        { id, title: opts.title, description: opts.description, variant: opts.variant ?? "default" },
      ]);
      // Errors linger a little longer so the message can be read; all auto-dismiss.
      setTimeout(() => dismiss(id), opts.variant === "error" ? 8000 : 5000);
    },
    [dismiss],
  );

  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  return useContext(ToastContext);
}

function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: ToastRecord[];
  onDismiss: (id: number) => void;
}) {
  if (toasts.length === 0) return null;
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          aria-live="polite"
          className={cn(
            "pointer-events-auto flex items-start gap-3 rounded-lg bg-card p-3 shadow-lg ring-1",
            t.variant === "error" ? "ring-destructive/40" : "ring-white/12",
          )}
        >
          <div className="min-w-0 flex-1">
            <p
              className={cn(
                "text-sm font-medium leading-snug",
                t.variant === "error" && "text-destructive",
              )}
            >
              {t.title}
            </p>
            {t.description && (
              <p className="mt-0.5 break-words text-xs leading-snug text-muted-foreground">
                {t.description}
              </p>
            )}
          </div>
          <button
            type="button"
            aria-label="Dismiss notification"
            onClick={() => onDismiss(t.id)}
            className="shrink-0 rounded border-0 bg-transparent p-0.5 text-muted-foreground hover:text-foreground"
          >
            <X className="size-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}
