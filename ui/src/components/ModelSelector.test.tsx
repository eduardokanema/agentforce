import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Model } from '../lib/types';
import ModelSelector from './ModelSelector';

function renderSelector(
  selected: string[],
  onChange = vi.fn(),
): { container: HTMLDivElement; root: ReturnType<typeof createRoot>; onChange: ReturnType<typeof vi.fn> } {
  const models: Model[] = [
    {
      id: 'claude-opus-4-5',
      name: 'Claude Opus 4.5',
      provider: 'Anthropic',
      cost_per_1k_input: 0.015,
      cost_per_1k_output: 0.075,
      latency_label: 'Powerful',
    },
    {
      id: 'claude-sonnet-4-5',
      name: 'Claude Sonnet 4.5',
      provider: 'Anthropic',
      cost_per_1k_input: 0.003,
      cost_per_1k_output: 0.015,
      latency_label: 'Standard',
    },
  ];

  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(<ModelSelector models={models} selected={selected} onChange={onChange} />);
  });

  return { container, root, onChange };
}

describe('ModelSelector', () => {
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('renders model cards with the requested chrome', () => {
    const { container, root } = renderSelector(['claude-opus-4-5']);

    expect(container.innerHTML).toContain('grid-cols-1 sm:grid-cols-3 gap-3');
    expect(container.textContent).toContain('Claude Opus 4.5');
    expect(container.textContent).toContain('$0.015/1k');
    expect(container.textContent).toContain('Powerful');
    expect(container.textContent).toContain('Anthropic');

    act(() => {
      root.unmount();
    });
  });

  it('keeps at least one model selected while toggling cards', () => {
    const { container, root, onChange } = renderSelector(['claude-opus-4-5']);
    const cards = Array.from(container.querySelectorAll('button'));

    act(() => {
      cards[0].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onChange).not.toHaveBeenCalled();

    act(() => {
      cards[1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onChange).toHaveBeenCalledWith(['claude-opus-4-5', 'claude-sonnet-4-5']);

    act(() => {
      root.unmount();
    });
  });
});
