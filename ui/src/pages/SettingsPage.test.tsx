import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  getConfig: vi.fn(),
  updateConfig: vi.fn(),
}));

const toastHarness = vi.hoisted(() => ({
  addToast: vi.fn(),
  removeToast: vi.fn(),
  toasts: [],
}));

vi.mock('../lib/api', () => api);
vi.mock('../hooks/useToast', () => ({
  useToast: () => toastHarness,
}));

import SettingsPage from './SettingsPage';

async function renderPage(): Promise<HTMLDivElement> {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  await act(async () => {
    root.render(<SettingsPage />);
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

  return container;
}

describe('SettingsPage', () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    api.getConfig.mockReset();
    api.updateConfig.mockReset();
    toastHarness.addToast.mockReset();
  });

  afterEach(() => {
    document.body.innerHTML = '';
    delete (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT;
  });

  it('loads and saves the workspace browser start path through dashboard settings', async () => {
    api.getConfig.mockResolvedValue({
      filesystem: {
        allowed_base_paths: ['/workspace'],
        default_start_path: '~/Projects',
      },
      default_caps: {
        max_concurrent_workers: 2,
        max_retries_per_task: 2,
        max_wall_time_minutes: 60,
        max_cost_usd: 0,
      },
    });
    api.updateConfig.mockResolvedValue({
      filesystem: {
        allowed_base_paths: ['/workspace'],
        default_start_path: '~/Code',
      },
      default_caps: {
        max_concurrent_workers: 2,
        max_retries_per_task: 2,
        max_wall_time_minutes: 60,
        max_cost_usd: 0,
      },
    });

    const container = await renderPage();
    const input = container.querySelector('#filesystem-default-start-path') as HTMLInputElement;
    expect(input.value).toBe('~/Projects');

    await act(async () => {
      const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
      descriptor?.set?.call(input, '~/Code');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    const saveButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent?.trim() === 'Save',
    ) as HTMLButtonElement | undefined;
    expect(saveButton).toBeTruthy();

    await act(async () => {
      saveButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(api.updateConfig).toHaveBeenCalledWith({
      default_caps: {
        max_concurrent_workers: 2,
        max_retries_per_task: 2,
        max_wall_time_minutes: 60,
        max_cost_usd: 0,
      },
      filesystem: {
        allowed_base_paths: [],
        default_start_path: '~/Code',
      },
    });
    expect(toastHarness.addToast).toHaveBeenCalledWith('Settings saved', 'success');
  });
});
