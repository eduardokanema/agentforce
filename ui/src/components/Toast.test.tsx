import { act, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider } from './Toast';
import { useToast } from '../hooks/useToast';

function ToastHarness() {
  const { addToast, toasts } = useToast();

  useEffect(() => {
    addToast('Saved successfully', 'success');
  }, [addToast]);

  return (
    <div>
      <button type="button" onClick={() => addToast('Manual info', 'info')}>
        Add toast
      </button>
      <span data-toast-count>{toasts.length}</span>
    </div>
  );
}

describe('ToastProvider', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = '';
  });

  it('renders bottom-right toasts and auto-dismisses after 3 seconds', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    await act(async () => {
      root.render(
        <ToastProvider>
          <ToastHarness />
        </ToastProvider>,
      );
    });

    expect(document.body.textContent).toContain('Saved successfully');
    expect(document.body.querySelector('.fixed.bottom-4.right-4.z-50')).toBeTruthy();

    await act(async () => {
      vi.advanceTimersByTime(3000);
    });

    expect(document.body.textContent).not.toContain('Saved successfully');

    await act(async () => {
      const button = container.querySelector('button');
      button?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    expect(document.body.textContent).toContain('Manual info');
  });
});
