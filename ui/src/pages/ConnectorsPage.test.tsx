import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Provider } from '../lib/types';
import { configureProvider, deleteProvider, getProviders, testProvider } from '../lib/api';

const api = vi.hoisted(() => ({
  getProviders: vi.fn(),
  configureProvider: vi.fn(),
  testProvider: vi.fn(),
  deleteProvider: vi.fn(),
  updateProviderModels: vi.fn(),
  refreshProviderModels: vi.fn(),
  deactivateProvider: vi.fn().mockResolvedValue(undefined),
  activateProvider: vi.fn().mockResolvedValue(undefined),
  getDefaultModel: vi.fn().mockResolvedValue({ model: null }),
  setDefaultModel: vi.fn().mockResolvedValue(undefined),
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

import ConnectorsPage from './ConnectorsPage';

const openrouterProvider: Provider = {
  id: 'openrouter',
  display_name: 'OpenRouter',
  description: 'Access hundreds of AI models via a single API key with live pricing.',
  requires_key: true,
  active: true,
  last_configured: '2026-04-08T12:00:00Z',
  enabled_models: ['anthropic/claude-sonnet-4-6'],
  default_model: null,
  all_models: [
    { id: 'anthropic/claude-sonnet-4-6', name: 'Claude Sonnet 4.6', cost_per_1k_input: 0.003, cost_per_1k_output: 0.015, latency_label: 'Cloud' },
    { id: 'openai/gpt-4o', name: 'GPT-4o', cost_per_1k_input: 0.005, cost_per_1k_output: 0.015, latency_label: 'Cloud' },
  ],
};

const ollamaProvider: Provider = {
  id: 'ollama',
  display_name: 'Ollama (Local)',
  description: 'Run AI models locally on your machine.',
  requires_key: false,
  active: true,
  last_configured: null,
  enabled_models: null,
  default_model: null,
  all_models: [
    { id: 'llama3.2:latest', name: 'llama3.2:latest', cost_per_1k_input: 0, cost_per_1k_output: 0, latency_label: 'Local' },
  ],
};

async function renderPage(): Promise<HTMLDivElement> {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  await act(async () => {
    root.render(<ConnectorsPage />);
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

  return container;
}

async function flush(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe('ConnectorsPage', () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.mocked(getProviders).mockReset();
    vi.mocked(configureProvider).mockReset();
    vi.mocked(testProvider).mockReset();
    vi.mocked(deleteProvider).mockReset();
    api.updateProviderModels.mockReset();
    toastHarness.addToast.mockReset();
  });

  afterEach(() => {
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
    delete (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT;
  });

  it('renders provider cards with active status and model list', async () => {
    vi.mocked(getProviders).mockResolvedValue([openrouterProvider, ollamaProvider]);

    const container = await renderPage();

    expect(container.textContent).toContain('Models');
    expect(container.textContent).toContain('OpenRouter');
    expect(container.textContent).toContain('Ollama (Local)');
    expect(container.textContent).toContain('Active');
    expect(container.querySelectorAll('article')).toHaveLength(2);
    // Model list shown for active provider
    expect(container.textContent).toContain('Claude Sonnet 4.6');
  });

  it('shows Connect button for inactive provider and expands API key form', async () => {
    const inactiveOpenRouter: Provider = { ...openrouterProvider, active: false, all_models: [] };
    vi.mocked(getProviders).mockResolvedValue([inactiveOpenRouter]);

    const container = await renderPage();

    const connectButton = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Connect',
    ) as HTMLButtonElement;
    expect(connectButton).toBeTruthy();

    act(() => {
      connectButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    const input = container.querySelector('input[type="password"]') as HTMLInputElement;
    expect(input).toBeTruthy();

    vi.mocked(configureProvider).mockResolvedValue(undefined);
    vi.mocked(testProvider).mockResolvedValue({ ok: true });
    vi.mocked(getProviders).mockResolvedValue([openrouterProvider]);

    act(() => {
      input.value = 'sk-or-test-key';
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });

    const saveButton = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.includes('Save & Test'),
    ) as HTMLButtonElement;

    await act(async () => {
      saveButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(vi.mocked(configureProvider)).toHaveBeenCalledWith('openrouter', 'sk-or-test-key');
    expect(toastHarness.addToast).toHaveBeenCalledWith('OpenRouter connected', 'success');
  });

  it('confirms removal and calls deleteProvider', async () => {
    vi.mocked(getProviders).mockResolvedValue([openrouterProvider]);
    vi.mocked(deleteProvider).mockResolvedValue(undefined);

    const container = await renderPage();

    const removeButton = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Remove',
    ) as HTMLButtonElement;
    expect(removeButton).toBeTruthy();

    act(() => {
      removeButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    const dialog = container.querySelector('[role="dialog"]') as HTMLElement;
    expect(dialog).toBeTruthy();
    const confirmButton = Array.from(dialog.querySelectorAll('button')).find(
      (b) => b.textContent === 'Remove',
    ) as HTMLButtonElement;
    expect(confirmButton).toBeTruthy();

    await act(async () => {
      confirmButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      await flush();
    });

    expect(vi.mocked(deleteProvider)).toHaveBeenCalledWith('openrouter');
    expect(toastHarness.addToast).toHaveBeenCalledWith('OpenRouter removed', 'success');
  });
});
