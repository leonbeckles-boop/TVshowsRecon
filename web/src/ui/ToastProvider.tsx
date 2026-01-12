// src/ui/ToastProvider.tsx
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

type ToastKind = "info" | "success" | "error";
type ToastItem = { id: string; kind: ToastKind; message: string };

type ToastContextType = {
  addToast: (kind: ToastKind, message: string) => void;
  info: (message: string) => void;
  success: (message: string) => void;
  error: (message: string) => void;
};

const ToastContext = createContext<ToastContextType | null>(null);

function uid() {
  return Math.random().toString(36).slice(2);
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const remove = useCallback((id: string) => {
    setToasts((t) => t.filter((x) => x.id !== id));
  }, []);

  const addToast = useCallback((kind: ToastKind, message: string) => {
    const id = uid();
    setToasts((t) => [...t, { id, kind, message }]);
    // Auto-hide after 4s
    setTimeout(() => remove(id), 4000);
  }, [remove]);

  // Listen for global API error/info events
  useEffect(() => {
    const onErr = (e: Event) => {
      const ce = e as CustomEvent<string>;
      const msg = ce.detail || "Something went wrong";
      addToast("error", msg);
    };
    const onInfo = (e: Event) => {
      const ce = e as CustomEvent<string>;
      const msg = ce.detail || "";
      if (msg) addToast("info", msg);
    };
    window.addEventListener("app:error", onErr as EventListener);
    window.addEventListener("app:info", onInfo as EventListener);
    return () => {
      window.removeEventListener("app:error", onErr as EventListener);
      window.removeEventListener("app:info", onInfo as EventListener);
    };
  }, [addToast]);

  const value = useMemo<ToastContextType>(
    () => ({
      addToast,
      info: (m: string) => addToast("info", m),
      success: (m: string) => addToast("success", m),
      error: (m: string) => addToast("error", m),
    }),
    [addToast]
  );

  return (
    <ToastContext.Provider value={value}>
      {children}

      {/* Toast stack - bottom right */}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={
              "pointer-events-auto rounded-lg px-4 py-3 shadow-lg border transition-opacity " +
              (t.kind === "error"
                ? "bg-red-50 border-red-200 text-red-800"
                : t.kind === "success"
                ? "bg-green-50 border-green-200 text-green-800"
                : "bg-white border-gray-200 text-gray-900")
            }
          >
            <div className="text-sm">{t.message}</div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToastContext(): ToastContextType {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToastContext must be used within <ToastProvider>");
  return ctx;
}
