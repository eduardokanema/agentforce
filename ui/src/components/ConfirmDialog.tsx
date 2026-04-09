export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
  confirmLabel?: string;
  variant?: 'danger' | 'warning';
}

function confirmButtonClassName(variant: ConfirmDialogProps['variant']): string {
  if (variant === 'warning') {
    return 'bg-amber/10 border border-amber/30 text-amber hover:bg-amber/20';
  }

  return 'bg-red/10 border border-red/30 text-red hover:bg-red/20';
}

export default function ConfirmDialog({
  open,
  title,
  message,
  onConfirm,
  onCancel,
  confirmLabel = 'Confirm',
  variant = 'danger',
}: ConfirmDialogProps) {
  if (!open) {
    return null;
  }

  return (
    <div aria-modal="true" className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" role="dialog">
      <div className="mx-4 w-full max-w-sm rounded-xl border border-border bg-card p-6 shadow-xl">
        <h2 className="mb-2 text-[16px] font-semibold text-text">{title}</h2>
        <p className="mb-6 text-[13px] text-dim">{message}</p>
        <div className="flex justify-end gap-3">
          <button
            type="button"
            className="rounded border border-border px-4 py-1.5 text-[13px] text-dim transition-colors hover:bg-surface"
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            type="button"
            className={`rounded px-4 py-1.5 text-[13px] transition-colors ${confirmButtonClassName(variant)}`}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
