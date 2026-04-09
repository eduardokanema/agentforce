import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ConfirmDialog from './ConfirmDialog';

function renderDialog(open: boolean, variant?: 'danger' | 'warning'): HTMLDivElement {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(
      <ConfirmDialog
        confirmLabel="Proceed"
        message="This is a destructive action."
        open={open}
        title="Remove connector"
        variant={variant}
        onCancel={() => undefined}
        onConfirm={() => undefined}
      />,
    );
  });

  return container;
}

describe('ConfirmDialog', () => {
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('renders the modal shell and danger button styling when open', () => {
    const container = renderDialog(true);

    expect(container.querySelector('[role="dialog"]')).toBeTruthy();
    expect(container.textContent).toContain('Remove connector');
    expect(container.textContent).toContain('This is a destructive action.');
    expect(container.textContent).toContain('Proceed');
    expect(container.innerHTML).toContain('fixed inset-0 z-50 flex items-center justify-center bg-black/60');
    expect(container.innerHTML).toContain('bg-red/10 border border-red/30 text-red hover:bg-red/20');
  });

  it('uses the warning variant classes when requested', () => {
    const container = renderDialog(true, 'warning');

    expect(container.innerHTML).toContain('bg-amber/10 border border-amber/30 text-amber hover:bg-amber/20');
  });

  it('renders nothing when closed', () => {
    const container = renderDialog(false);

    expect(container.textContent).toBe('');
  });
});
