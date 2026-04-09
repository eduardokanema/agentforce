import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Model } from '../lib/types';

const navigateMock = vi.hoisted(() => vi.fn());

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

import PlanModePage from './PlanModePage';

function createStreamingResponse(): {
  response: Response;
  push: (chunk: string) => void;
  close: () => void;
} {
  const encoder = new TextEncoder();
  let controller: ReadableStreamDefaultController<Uint8Array> | null = null;
  const response = new Response(
    new ReadableStream<Uint8Array>({
      start(streamController) {
        controller = streamController;
      },
    }),
    { headers: { 'Content-Type': 'text/event-stream' } },
  );

  return {
    response,
    push(chunk: string) {
      controller?.enqueue(encoder.encode(chunk));
    },
    close() {
      controller?.close();
    },
  };
}

function renderPage(fetchMock: ReturnType<typeof vi.fn>): { container: HTMLDivElement; root: Root } {
  vi.stubGlobal('fetch', fetchMock);

  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(<PlanModePage />);
  });

  return { container, root };
}

describe('PlanModePage', () => {
  beforeEach(() => {
    navigateMock.mockReset();
  });

  afterEach(() => {
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
  });

  it('drives the compose, generate, edit, and launch flow', async () => {
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
      {
        id: 'claude-haiku-4-5',
        name: 'Claude Haiku 4.5',
        provider: 'Anthropic',
        cost_per_1k_input: 0.00025,
        cost_per_1k_output: 0.00125,
        latency_label: 'Fast',
      },
    ];
    const stream = createStreamingResponse();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/models') {
        return new Response(JSON.stringify(models), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/plan') {
        return stream.response;
      }
      if (url === '/api/missions') {
        return new Response(JSON.stringify({ id: 'mission-123' }), {
          headers: { 'Content-Type': 'application/json' },
        });
      }

      throw new Error(`unexpected fetch ${url}`);
    });
    const { container, root } = renderPage(fetchMock);

    await act(async () => {
      await Promise.resolve();
    });

    expect(container.textContent).toContain('Generate Plan →');
    expect(container.innerHTML).toContain('Claude Opus 4.5');
    expect(container.innerHTML).toContain('bg-cyan-bg');

    const prompt = container.querySelector('textarea[placeholder="Describe what you want to build..."]') as HTMLTextAreaElement;
    const workspace = container.querySelector('input[placeholder="/path/to/project"]') as HTMLInputElement;
    const generateButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Generate Plan'),
    ) as HTMLButtonElement;

    expect(generateButton.disabled).toBe(true);

    await act(async () => {
      prompt.value = 'Build a launch flow';
      prompt.dispatchEvent(new Event('input', { bubbles: true }));
      workspace.value = '/Users/rent/Projects/agentforce';
      workspace.dispatchEvent(new Event('input', { bubbles: true }));
    });

    expect(generateButton.disabled).toBe(false);

    await act(async () => {
      generateButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    expect(fetchMock).toHaveBeenCalledWith('/api/plan', expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
    }));

    await act(async () => {
      stream.push('data: name: Launch Mission\n\n');
      stream.push('data: goal: Ship the plan builder\n\n');
      stream.push('data: definition_of_done:\n\n');
      stream.push('data:   - Prompt is editable\n\n');
      stream.push('data: tasks:\n\n');
      stream.push('data:   - id: task-1\n\n');
      stream.push('data:     title: Launch work\n\n');
      stream.push('data:     description: Do the thing\n\n');
      stream.push('data:     acceptance_criteria:\n\n');
      stream.push('data:       - Works\n\n');
      stream.push('data:     model: claude-sonnet-4-5\n\n');
      stream.push('data: [DONE]\n\n');
    });

    await act(async () => {
      await Promise.resolve();
    });

    expect(container.textContent).toContain('Mission name');
    expect(container.textContent).toContain('Launch Mission');
    expect(container.textContent).toContain('Launch work');
    expect(container.textContent).toContain('Raw YAML');

    const missionName = container.querySelector('input[aria-label="Mission name"]') as HTMLInputElement;
    expect(missionName.value).toBe('Launch Mission');

    const taskSelect = container.querySelector('select[aria-label="Task model"]') as HTMLSelectElement;
    const optionLabels = Array.from(taskSelect.options).map((option) => option.value);
    expect(optionLabels).toEqual(['claude-opus-4-5', 'claude-sonnet-4-5', 'claude-haiku-4-5']);

    const rawYamlToggle = container.querySelector('summary') as HTMLElement;
    await act(async () => {
      rawYamlToggle.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    const rawYaml = container.querySelector('textarea[aria-label="Raw YAML"]') as HTMLTextAreaElement;
    expect(rawYaml.value).toContain('Launch Mission');

    await act(async () => {
      rawYaml.value = rawYaml.value.replace('Launch Mission', 'Launch Mission Edited');
      rawYaml.dispatchEvent(new Event('input', { bubbles: true }));
    });

    const launchButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Launch Mission'),
    ) as HTMLButtonElement;
    expect(launchButton.disabled).toBe(false);

    await act(async () => {
      launchButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    expect(fetchMock).toHaveBeenCalledWith('/api/missions', expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
      body: expect.stringContaining('Launch Mission Edited'),
    }));
    expect(navigateMock).toHaveBeenCalledWith('/mission/mission-123');

    act(() => {
      root.unmount();
    });
  });
});
