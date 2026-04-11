import type { ReactNode } from "react";

interface CockpitSupportDrawerProps {
  title: string;
  description: string;
  label: string;
  onClose: () => void;
  children: ReactNode;
}

export default function CockpitSupportDrawer({
  title,
  description,
  label,
  onClose,
  children,
}: CockpitSupportDrawerProps) {
  return (
    <div
      className="fixed inset-0 z-40 flex items-end bg-[rgba(4,8,14,0.72)] p-4 backdrop-blur-sm xl:static xl:z-auto xl:block xl:bg-transparent xl:p-0 xl:backdrop-blur-none"
      role="dialog"
      aria-modal="true"
      aria-label={label}
      onClick={onClose}
    >
      <div
        className="max-h-[calc(100vh-2rem)] w-full overflow-hidden rounded-[1.3rem] border border-border bg-[radial-gradient(circle_at_top,rgba(34,211,238,0.12),transparent_52%),linear-gradient(180deg,rgba(13,21,37,0.98),rgba(9,16,30,0.98))] shadow-[0_24px_80px_rgba(0,0,0,0.42)] xl:max-h-none xl:rounded-[1.2rem] xl:shadow-[0_18px_48px_rgba(0,0,0,0.28)]"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-4 border-b border-border/80 px-5 py-4">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan">
              Support Surface
            </div>
            <h2 className="mt-2 text-lg font-semibold tracking-[-0.03em] text-text">
              {title}
            </h2>
            <p className="mt-1 max-w-[44ch] text-xs leading-6 text-dim">
              {description}
            </p>
          </div>
          <button
            type="button"
            className="rounded-full border border-border bg-black/10 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-dim transition-colors hover:bg-card hover:text-text"
            onClick={onClose}
          >
            Close
          </button>
        </header>
        <div className="max-h-[calc(100vh-9rem)] overflow-y-auto p-4 xl:max-h-[calc(100vh-9.5rem)] xl:p-5">
          {children}
        </div>
      </div>
    </div>
  );
}
