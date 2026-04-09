import { act, type ReactElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Terminal from './Terminal';

function renderToContainer(element: ReactElement): { root: Root; container: HTMLDivElement } {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(element);
  });

  return { root, container };
}

function setDimensionMocks(): void {
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
    configurable: true,
    get: () => 480,
  });
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
    configurable: true,
    get: () => 800,
  });
}

describe('Terminal', () => {
  let originalScrollTo: unknown;
  let clipboardWriteText: ReturnType<typeof vi.fn>;
  let originalClipboard: Clipboard | undefined;

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    setDimensionMocks();

    originalScrollTo = HTMLElement.prototype.scrollTo;
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      writable: true,
      value: vi.fn(),
    });

    clipboardWriteText = vi.fn().mockResolvedValue(undefined);
    originalClipboard = navigator.clipboard;
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: clipboardWriteText },
    });
  });

  afterEach(() => {
    document.body.innerHTML = '';

    if (originalScrollTo) {
      Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
        configurable: true,
        writable: true,
        value: originalScrollTo,
      });
    } else {
      delete (HTMLElement.prototype as { scrollTo?: unknown }).scrollTo;
    }

    if (originalClipboard) {
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: originalClipboard,
      });
    } else {
      delete (navigator as { clipboard?: Clipboard }).clipboard;
    }
  });

  it('virtualizes large streams, renders ANSI, and badges user instructions', () => {
    const lines = Array.from({ length: 10_000 }, (_, index) => `line ${index}`);
    lines[5] = '\u001b[32mgreen\u001b[0m';
    lines[6] = '[USER INSTRUCTION] do the thing';

    const { container } = renderToContainer(<Terminal lines={lines} done={true} />);

    const renderedRows = container.querySelectorAll('[style*="position: absolute"]');
    expect(renderedRows.length).toBeGreaterThan(0);
    expect(renderedRows.length).toBeLessThan(200);
    expect(container.textContent).toContain('green');
    expect(container.querySelector('span[style*="color"]')).not.toBeNull();
    expect(container.textContent).toContain('[USER]');
  });

  it('filters output, copies all lines, and shows no-match feedback', async () => {
    const lines = ['alpha', 'beta', 'gamma'];
    const { container } = renderToContainer(<Terminal lines={lines} done={true} />);

    const input = container.querySelector('input[placeholder="Filter output..."]') as HTMLInputElement;
    expect(input).not.toBeNull();

    await act(async () => {
      Simulate.change(input, { target: { value: 'beta' } } as any);
    });

    const filteredRows = Array.from(container.querySelectorAll('[style*="position: absolute"]'));
    expect(filteredRows.map((row) => row.textContent ?? '').join(' ')).toContain('beta');
    expect(filteredRows.map((row) => row.textContent ?? '').join(' ')).not.toContain('alpha');
    expect(filteredRows.map((row) => row.textContent ?? '').join(' ')).not.toContain('gamma');

    await act(async () => {
      Simulate.change(input, { target: { value: 'zzz' } } as any);
    });

    expect(container.textContent).toContain("No matches for 'zzz'");

    const copyButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Copy'),
    );
    expect(copyButton).toBeDefined();

    await act(async () => {
      copyButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    expect(clipboardWriteText).toHaveBeenCalledWith(lines.join('\n'));
  });

  it('switches auto-scroll behavior when toggled', () => {
    const scrollToMock = HTMLElement.prototype.scrollTo as unknown as ReturnType<typeof vi.fn>;
    const initialLines = ['first'];
    const { root, container } = renderToContainer(<Terminal lines={initialLines} done={false} />);

    scrollToMock.mockClear();

    act(() => {
      root.render(<Terminal lines={['first', 'second']} done={false} />);
    });

    expect(scrollToMock).toHaveBeenCalled();

    const toggle = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Auto'),
    );
    expect(toggle).toBeDefined();

    act(() => {
      toggle?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    scrollToMock.mockClear();

    act(() => {
      root.render(<Terminal lines={['first', 'second', 'third']} done={false} />);
    });

    expect(scrollToMock).not.toHaveBeenCalled();

    act(() => {
      root.unmount();
    });
  });
});
