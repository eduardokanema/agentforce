import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_LABS_CONFIG } from '../lib/types';
import type { LabsConfig } from '../lib/types';

const api = vi.hoisted(() => ({
  getConfig: vi.fn(),
  updateConfig: vi.fn(),
  selectLabsConfig: vi.fn(),
  getFilesystemListing: vi.fn(),
  createFilesystemFolder: vi.fn(),
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

async function renderPage(props: {
  labs?: LabsConfig;
  onLabsChange?: (labs: LabsConfig) => void;
} = {}): Promise<HTMLDivElement> {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  await act(async () => {
    root.render(<SettingsPage {...props} />);
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

  return container;
}

describe('SettingsPage', () => {
  beforeEach(() => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    api.getConfig.mockReset();
    api.updateConfig.mockReset();
    api.getFilesystemListing.mockReset();
    api.createFilesystemFolder.mockReset();
    api.selectLabsConfig.mockReset();
    api.selectLabsConfig.mockImplementation((config) => config?.labs ?? DEFAULT_LABS_CONFIG);
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
      labs: { ...DEFAULT_LABS_CONFIG },
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
      labs: { ...DEFAULT_LABS_CONFIG },
    });
    api.getFilesystemListing.mockImplementation(async (path: string) => {
      if (path === '~/Projects') {
        throw new Error('Request failed with status 403 Forbidden');
      }
      if (path === '/workspace') {
        return {
          path: '/workspace',
          entries: [{ name: 'client', path: '/workspace/client', is_dir: true }],
          parent: null,
        };
      }
      if (path === '/workspace/client') {
        return {
          path: '/workspace/client',
          entries: [],
          parent: '/workspace',
        };
      }
      throw new Error(`unexpected listing ${path}`);
    });
    api.updateConfig.mockResolvedValue({
      filesystem: {
        allowed_base_paths: ['/workspace'],
        default_start_path: '/workspace/client',
      },
      default_caps: {
        max_concurrent_workers: 2,
        max_retries_per_task: 2,
        max_wall_time_minutes: 60,
        max_cost_usd: 0,
      },
      labs: { ...DEFAULT_LABS_CONFIG },
    });

    const container = await renderPage();
    expect(container.textContent).toContain('Selected start folder');
    expect(container.textContent).toContain('~/Projects');

    await act(async () => {
      const clientButton = Array.from(container.querySelectorAll('button')).find((button) =>
        button.textContent?.includes('client'));
      clientButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    const useFolderButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent?.trim() === 'Use this folder',
    ) as HTMLButtonElement | undefined;
    expect(useFolderButton).toBeTruthy();

    await act(async () => {
      useFolderButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
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
        default_start_path: '/workspace/client',
      },
      labs: {
        black_hole_enabled: false,
      },
    });
    expect(toastHarness.addToast).toHaveBeenCalledWith('Settings saved', 'success');
  });

  it('renders Labs experimental features inside Settings', async () => {
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
      labs: { ...DEFAULT_LABS_CONFIG },
    });
    api.getFilesystemListing.mockResolvedValue({
      path: '/workspace',
      entries: [],
      parent: null,
    });

    const container = await renderPage();

    expect(container.textContent).toContain('Lab experimental features');
    expect(container.textContent).toContain('Black Hole');
    expect(container.textContent).toContain('Disabled');
  });

  it('saves Labs experimental feature changes and notifies the app shell', async () => {
    const onLabsChange = vi.fn();
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
      labs: { ...DEFAULT_LABS_CONFIG },
    });
    api.getFilesystemListing.mockResolvedValue({
      path: '/workspace',
      entries: [],
      parent: null,
    });
    api.updateConfig.mockResolvedValue({
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
      labs: { ...DEFAULT_LABS_CONFIG, black_hole_enabled: true },
    });

    const container = await renderPage({ onLabsChange });

    const blackHoleCheckbox = container.querySelector('input[name="lab-black-hole"]') as HTMLInputElement | null;
    expect(blackHoleCheckbox).toBeTruthy();
    expect(blackHoleCheckbox?.checked).toBe(false);

    await act(async () => {
      blackHoleCheckbox?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
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
        default_start_path: '~/Projects',
      },
      labs: {
        black_hole_enabled: true,
      },
    });
    expect(onLabsChange).toHaveBeenCalledWith({
      ...DEFAULT_LABS_CONFIG,
      black_hole_enabled: true,
    });
    expect(toastHarness.addToast).toHaveBeenCalledWith('Settings saved', 'success');
  });

  it('shows an explicit error toast when Labs experimental feature save fails', async () => {
    const onLabsChange = vi.fn();
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
      labs: { ...DEFAULT_LABS_CONFIG, black_hole_enabled: true },
    });
    api.getFilesystemListing.mockResolvedValue({
      path: '/workspace',
      entries: [],
      parent: null,
    });
    api.updateConfig.mockRejectedValue(new Error('save failed'));

    const container = await renderPage({
      labs: { ...DEFAULT_LABS_CONFIG, black_hole_enabled: true },
      onLabsChange,
    });

    const blackHoleCheckbox = container.querySelector('input[name="lab-black-hole"]') as HTMLInputElement | null;
    expect(blackHoleCheckbox?.checked).toBe(true);

    await act(async () => {
      blackHoleCheckbox?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
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

    expect(onLabsChange).not.toHaveBeenCalled();
    expect(toastHarness.addToast).toHaveBeenCalledWith('save failed', 'error');
  });

  it('creates a folder from the shared browser before selecting it as the start path', async () => {
    api.getConfig.mockResolvedValue({
      filesystem: {
        allowed_base_paths: ['/workspace'],
        default_start_path: '/workspace',
      },
      default_caps: {
        max_concurrent_workers: 2,
        max_retries_per_task: 2,
        max_wall_time_minutes: 60,
        max_cost_usd: 0,
      },
      labs: { ...DEFAULT_LABS_CONFIG },
    });
    api.getFilesystemListing.mockImplementation(async (path: string) => {
      if (path === '/workspace') {
        return {
          path: '/workspace',
          entries: [{ name: 'client', path: '/workspace/client', is_dir: true }],
          parent: null,
        };
      }
      if (path === '/workspace/new-app') {
        return {
          path: '/workspace/new-app',
          entries: [],
          parent: '/workspace',
        };
      }
      throw new Error(`unexpected listing ${path}`);
    });
    api.createFilesystemFolder.mockResolvedValue({ path: '/workspace/new-app' });
    api.updateConfig.mockResolvedValue({
      filesystem: {
        allowed_base_paths: ['/workspace'],
        default_start_path: '/workspace/new-app',
      },
      default_caps: {
        max_concurrent_workers: 2,
        max_retries_per_task: 2,
        max_wall_time_minutes: 60,
        max_cost_usd: 0,
      },
      labs: { ...DEFAULT_LABS_CONFIG },
    });

    const container = await renderPage();
    const newFolderInput = container.querySelector('input[placeholder="New folder name"]') as HTMLInputElement;
    expect(newFolderInput).toBeTruthy();

    await act(async () => {
      const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
      descriptor?.set?.call(newFolderInput, 'new-app');
      newFolderInput.dispatchEvent(new Event('input', { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    const createFolderButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent?.trim() === 'Create folder',
    ) as HTMLButtonElement | undefined;
    expect(createFolderButton).toBeTruthy();

    await act(async () => {
      createFolderButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(api.createFilesystemFolder).toHaveBeenCalledWith('/workspace', 'new-app');

    const useFolderButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent?.trim() === 'Use this folder',
    ) as HTMLButtonElement | undefined;
    expect(useFolderButton).toBeTruthy();

    await act(async () => {
      useFolderButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
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
        default_start_path: '/workspace/new-app',
      },
      labs: {
        black_hole_enabled: false,
      },
    });
  });
});
