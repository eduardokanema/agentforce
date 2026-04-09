import { createContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

export type ToastType = 'success' | 'error' | 'info';

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastItem {
  id: string;
  message: string;
  type: ToastType;
  action?: ToastAction;
}

export interface ToastContextValue {
  toasts: ToastItem[];
  addToast: (message: string, type: ToastType, action?: ToastAction) => string;
  removeToast: (id: string) => void;
}

export const ToastContext = createContext<ToastContextValue | null>(null);

function makeToastId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }

  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function toastClassName(type: ToastType): string {
  if (type === 'success') {
    return 'border-green/30 bg-green/10 text-green';
  }

  if (type === 'error') {
    return 'border-red/30 bg-red/10 text-red';
  }

  return 'border-cyan/30 bg-cyan/10 text-cyan';
}

export function ToastViewport({ toasts, onDismiss }: { toasts: ToastItem[]; onDismiss: (id: string) => void }) {
  return (
    <div aria-live="polite" aria-atomic="true" className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`rounded-lg border px-4 py-3 text-[13px] shadow-lg ${toastClassName(toast.type)}`}
          role={toast.type === 'error' ? 'alert' : 'status'}
        >
          <div className="flex items-start gap-3">
            <p className="min-w-0 flex-1">{toast.message}</p>
            {toast.action ? (
              <button
                type="button"
                className="shrink-0 text-[11px] font-semibold uppercase tracking-[0.08em] transition-colors hover:text-text"
                onClick={() => {
                  toast.action!.onClick();
                  onDismiss(toast.id);
                }}
              >
                {toast.action.label}
              </button>
            ) : null}
            <button
              type="button"
              className="shrink-0 text-[11px] uppercase tracking-[0.08em] text-dim transition-colors hover:text-text"
              onClick={() => onDismiss(toast.id)}
            >
              Dismiss
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const timersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  const removeToast = useMemo(
    () => (id: string): void => {
      const timer = timersRef.current.get(id);
      if (timer) {
        clearTimeout(timer);
        timersRef.current.delete(id);
      }

      setToasts((current) => current.filter((toast) => toast.id !== id));
    },
    [],
  );

  const addToast = useMemo(
    () => (message: string, type: ToastType, action?: ToastAction): string => {
      const id = makeToastId();
      setToasts((current) => [...current, { id, message, type, action }]);

      const timer = setTimeout(() => {
        timersRef.current.delete(id);
        setToasts((current) => current.filter((toast) => toast.id !== id));
      }, 3000);

      timersRef.current.set(id, timer);
      return id;
    },
    [],
  );

  useEffect(
    () => () => {
      for (const timer of timersRef.current.values()) {
        clearTimeout(timer);
      }
      timersRef.current.clear();
    },
    [],
  );

  const value = useMemo(
    () => ({
      toasts,
      addToast,
      removeToast,
    }),
    [addToast, removeToast, toasts],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={removeToast} />
    </ToastContext.Provider>
  );
}
