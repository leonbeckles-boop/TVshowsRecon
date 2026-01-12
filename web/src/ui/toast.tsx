import React, { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";

type ToastKind = "success" | "error" | "info";
export type Toast = { id: number; kind: ToastKind; message: string };

type Ctx = {
  toasts: Toast[];
  push: (kind: ToastKind, message: string, ms?: number) => void;
  remove: (id: number) => void;
};

const ToastCtx = createContext<Ctx | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counter = useRef(1);

  const remove = useCallback((id: number) => {
    setToasts((t) => t.filter((x) => x.id !== id));
  }, []);

  const push = useCallback(
    (kind: ToastKind, message: string, ms = 2500) => {
      const id = counter.current++;
      setToasts((prev) => [...prev, { id, kind, message }]);
      if (ms > 0) {
        setTimeout(() => remove(id), ms);
      }
    },
    [remove]
  );

  const value = useMemo<Ctx>(() => ({ toasts, push, remove }), [toasts, push, remove]);

  return (
    <ToastCtx.Provider value={value}>
      {children}
      <Toaster />
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return {
    success: (msg: string, ms?: number) => ctx.push("success", msg, ms),
    error: (msg: string, ms?: number) => ctx.push("error", msg, ms),
    info: (msg: string, ms?: number) => ctx.push("info", msg, ms),
  };
}

function Toaster() {
  const ctx = useContext(ToastCtx);
  if (!ctx) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {ctx.toasts.map((t) => (
        <div
          key={t.id}
          className={[
            "min-w-[220px] max-w-sm rounded-xl shadow-lg border px-3 py-2 text-sm",
            t.kind === "success" && "bg-emerald-50 border-emerald-200 text-emerald-900",
            t.kind === "error" && "bg-rose-50 border-rose-200 text-rose-900",
            t.kind === "info" && "bg-slate-50 border-slate-200 text-slate-900",
          ]
            .filter(Boolean)
            .join(" ")}
          role="status"
        >
          {t.message}
        </div>
      ))}
    </div>
  );
}
