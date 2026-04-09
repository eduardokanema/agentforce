import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Connector } from '../lib/types';
import { configureConnector, deleteConnector, getConnectors, testConnector } from '../lib/api';

const api = vi.hoisted(() => ({
  getConnectors: vi.fn(),
  configureConnector: vi.fn(),
  testConnector: vi.fn(),
  deleteConnector: vi.fn(),
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

function getConnectorCards(container: HTMLDivElement): HTMLElement[] {
  return Array.from(container.querySelectorAll('article'));
}

describe('ConnectorsPage', () => {
  type ConnectorFixture = Connector & { description: string };

  const connectors: ConnectorFixture[] = [
    { name: 'github', display_name: 'GitHub', description: 'Access repos and PRs', active: true, token_last4: '1234', last_configured: '2026-04-08T12:00:00Z' },
    { name: 'anthropic', display_name: 'Anthropic', description: 'Claude API key', active: true, token_last4: 'abcd', last_configured: '2026-04-08T12:00:00Z' },
    { name: 'slack', display_name: 'Slack', description: 'Send notifications', active: false },
    { name: 'linear', display_name: 'Linear', description: 'Track issues', active: false },
    { name: 'sentry', display_name: 'Sentry', description: 'Error monitoring', active: false },
    { name: 'notion', display_name: 'Notion', description: 'Documentation', active: false },
  ];

  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.mocked(getConnectors).mockReset();
    vi.mocked(configureConnector).mockReset();
    vi.mocked(testConnector).mockReset();
    vi.mocked(deleteConnector).mockReset();
    toastHarness.addToast.mockReset();
  });

  afterEach(() => {
    document.body.innerHTML = '';
    delete (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT;
  });

  it('renders six connector cards with active token hints and inactive configure actions', async () => {
    vi.mocked(getConnectors).mockResolvedValue(connectors);

    const container = await renderPage();

    expect(container.textContent).toContain('Connectors');
    expect(container.textContent).toContain('Manage API tokens for external services');
    expect(getConnectorCards(container)).toHaveLength(6);
    expect(container.textContent).toContain('Token: ••••1234');
    expect(container.textContent).toContain('Token: ••••abcd');
    expect(container.textContent).toContain('Configure');
    expect(container.textContent).toContain('Reconfigure');
    expect(container.textContent).toContain('Remove');
  });

  it('expands an inline configure form with password visibility controls and saves the token', async () => {
    vi.mocked(getConnectors).mockResolvedValue(connectors);
    vi.mocked(configureConnector).mockResolvedValue(undefined);
    vi.mocked(testConnector).mockResolvedValue({ ok: true });

    const container = await renderPage();

    const githubCard = Array.from(container.querySelectorAll('article')).find((card) =>
      card.textContent?.includes('GitHub'),
    ) as HTMLElement;
    const configureButton = Array.from(githubCard.querySelectorAll('button')).find(
      (button) => button.textContent === 'Reconfigure',
    ) as HTMLButtonElement;

    act(() => {
      configureButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    const input = container.querySelector('input[type="password"]') as HTMLInputElement;
    expect(input).toBeTruthy();

    act(() => {
      input.value = 'token-123456';
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });

    const toggleButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent?.includes('👁'),
    ) as HTMLButtonElement;

    act(() => {
      toggleButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    expect((container.querySelector('input') as HTMLInputElement).type).toBe('text');

    const saveButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === 'Save & Test',
    ) as HTMLButtonElement;

    await act(async () => {
      saveButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(vi.mocked(configureConnector)).toHaveBeenCalledWith('github', 'token-123456');
    expect(vi.mocked(testConnector)).toHaveBeenCalledWith('github');
    expect(toastHarness.addToast).toHaveBeenCalledWith('Connector connected', 'success');
    expect((container.querySelector('input') as HTMLInputElement).value).toBe('');
  });

  it('confirms removal, calls delete, and refreshes the list', async () => {
    vi.mocked(getConnectors).mockResolvedValue(connectors);
    vi.mocked(deleteConnector).mockResolvedValue(undefined);

    const container = await renderPage();

    const githubCard = Array.from(container.querySelectorAll('article')).find((card) =>
      card.textContent?.includes('GitHub'),
    ) as HTMLElement;
    const removeButton = Array.from(githubCard.querySelectorAll('button')).find(
      (button) => button.textContent === 'Remove',
    ) as HTMLButtonElement;

    act(() => {
      removeButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    expect(container.textContent).toContain('Remove connector "GitHub"?');
    const confirmButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === 'Remove Connector',
    ) as HTMLButtonElement;

    await act(async () => {
      confirmButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    expect(vi.mocked(deleteConnector)).toHaveBeenCalledWith('github');
    expect(vi.mocked(getConnectors)).toHaveBeenCalledTimes(2);
    expect(toastHarness.addToast).toHaveBeenCalledWith('Connector "GitHub" removed', 'success');
  });
});
