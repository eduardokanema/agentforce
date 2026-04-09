import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { MissionDraft, Model } from '../lib/types';
import { serializeMissionPlanYaml } from '../lib/planYaml';
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

function flushPromises(): Promise<void> {
  return act(async () => {
    await Promise.resolve();
  });
}

function makeDraft(overrides: Partial<MissionDraft> = {}): MissionDraft {
  return {
    id: 'draft-123',
    revision: 3,
    status: 'draft',
    draft_spec: {
      name: 'Calculator Mission',
      goal: 'Build a calculator cockpit',
      definition_of_done: ['Planner summary is current'],
      caps: {
        max_tokens_per_task: 100000,
        max_retries_global: 3,
        max_retries_per_task: 3,
        max_wall_time_minutes: 120,
        max_human_interventions: 2,
        max_cost_usd: null,
        max_concurrent_workers: 3,
      },
      execution_defaults: {
        worker: {
          agent: 'codex',
          model: 'claude-sonnet-4-5',
          thinking: 'medium',
        },
        reviewer: {
          agent: 'codex',
          model: 'claude-haiku-4-5',
          thinking: 'low',
        },
      },
      tasks: [
        {
          id: '01',
          title: 'Draft the planner flow',
          description: 'Build the planning route',
          acceptance_criteria: ['PlanModePage.test.tsx passes'],
          dependencies: [],
          max_retries: 3,
          output_artifacts: [],
        },
      ],
    },
    turns: [
      { role: 'user', content: 'Build a calculator mission' },
      { role: 'assistant', content: 'I drafted the initial mission plan.' },
    ],
    validation: {
      summary: ['Ready to refine'],
      issues: [],
    },
    activity_log: [],
    approved_models: ['claude-sonnet-4-5', 'claude-haiku-4-5'],
    workspace_paths: ['/workspace/app'],
    companion_profile: {
      id: 'planner',
      label: 'Planner',
      model: 'claude-opus-4-5',
    },
    draft_notes: [],
    ...overrides,
  };
}

function renderPage(
  fetchMock: ReturnType<typeof vi.fn>,
  initialEntry = '/plan',
): { container: HTMLDivElement; root: Root } {
  vi.stubGlobal('fetch', fetchMock);
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/plan" element={<PlanModePage />} />
        </Routes>
      </MemoryRouter>,
    );
  });

  return { container, root };
}

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

describe('PlanModePage', () => {
  afterEach(() => {
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
  });

  it('loads models, creates a planning draft, and renders transcript plus engineering panels', async () => {
    const createdDraft = makeDraft();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/models') {
        return new Response(JSON.stringify(models), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/config') {
        return new Response(JSON.stringify({
          filesystem: { allowed_base_paths: ['/workspace'] },
          default_caps: {
            max_concurrent_workers: 2,
            max_retries_per_task: 2,
            max_wall_time_minutes: 60,
            max_cost_usd: 0,
          },
        }), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url.startsWith('/api/filesystem')) {
        return new Response(JSON.stringify({
          path: '/workspace',
          entries: [{ name: 'app', path: '/workspace/app', is_dir: true }],
          parent: null,
        }), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/plan/drafts') {
        return new Response(JSON.stringify({ id: 'draft-123', revision: 1 }), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/plan/drafts/draft-123') {
        return new Response(JSON.stringify(createdDraft), {
          headers: { 'Content-Type': 'application/json' },
        });
      }

      throw new Error(`unexpected fetch ${url}`);
    });

    const { container, root } = renderPage(fetchMock);
    await flushPromises();

    expect(container.textContent).toContain('Claude Opus 4.5');

    const prompt = container.querySelector('textarea') as HTMLTextAreaElement;
    await act(async () => {
      prompt.value = 'Build a calculator mission';
      prompt.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await flushPromises();

    const selectFolderButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Select this folder'));
    expect(selectFolderButton).toBeTruthy();

    await act(async () => {
      selectFolderButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    const openDraftButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Open Flight Plan')) as HTMLButtonElement | undefined;
    expect(openDraftButton).toBeTruthy();

    await act(async () => {
      openDraftButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flushPromises();

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/plan/drafts',
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('Build a calculator mission'),
      }),
    );
    expect(container.textContent).toContain('Flight Director');
    expect(container.textContent).toContain('Engineering Controls');
    expect(container.textContent).toContain('Calculator Mission');
    expect(container.textContent).toContain('Draft the planner flow');
    expect(
      (container.querySelector('textarea[aria-label="Mission YAML export"]') as HTMLTextAreaElement | null)?.value,
    ).toEqual(expect.stringContaining('name: "Calculator Mission"'));
    expect(
      (container.querySelector('textarea[aria-label="Mission YAML export"]') as HTMLTextAreaElement | null)?.value,
    ).toEqual(expect.stringContaining('goal: "Build a calculator cockpit"'));
    expect(
      (container.querySelector('textarea[aria-label="Mission YAML export"]') as HTMLTextAreaElement | null)?.value,
    ).toEqual(expect.stringContaining('definition_of_done:'));
    expect(
      (container.querySelector('textarea[aria-label="Mission YAML export"]') as HTMLTextAreaElement | null)?.value,
    ).toEqual(expect.stringContaining('tasks:'));
    expect(
      (container.querySelector('textarea[aria-label="Mission YAML export"]') as HTMLTextAreaElement | null)?.value,
    ).toContain('execution_defaults:');

    act(() => {
      root.unmount();
    });
  });

  it('resumes an existing draft from /api/plan/drafts/:id', async () => {
    const resumedDraft = makeDraft({
      id: 'draft-resume',
      draft_spec: {
        ...makeDraft().draft_spec,
        name: 'Resumed Draft',
      },
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/models') {
        return new Response(JSON.stringify(models), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/plan/drafts/draft-resume') {
        return new Response(JSON.stringify(resumedDraft), {
          headers: { 'Content-Type': 'application/json' },
        });
      }

      throw new Error(`unexpected fetch ${url}`);
    });

    const { container, root } = renderPage(fetchMock, '/plan?draft=draft-resume');
    await flushPromises();

    expect(fetchMock).toHaveBeenCalledWith('/api/plan/drafts/draft-resume', expect.anything());
    expect(container.textContent).toContain('Resumed Draft');
    expect(container.textContent).toContain('Flight Director');

    act(() => {
      root.unmount();
    });
  });

  it('applies a follow-up planner turn and refreshes both transcript and draft summary', async () => {
    const stream = createStreamingResponse();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/models') {
        return new Response(JSON.stringify(models), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/plan/drafts/draft-123') {
        const lastFetchBody = fetchMock.mock.calls.find(([calledUrl]) => String(calledUrl) === '/api/plan/drafts/draft-123/messages');
        const afterTurn = Boolean(lastFetchBody);
        return new Response(JSON.stringify(makeDraft({
          revision: afterTurn ? 4 : 3,
          draft_spec: {
            ...makeDraft().draft_spec,
            name: afterTurn ? 'Calculator Mission Refined' : 'Calculator Mission',
          },
          turns: afterTurn ? [
            { role: 'user', content: 'Build a calculator mission' },
            { role: 'assistant', content: 'I drafted the initial mission plan.' },
            { role: 'user', content: 'Tighten the summary' },
            { role: 'assistant', content: 'I tightened the mission summary and task wording.' },
          ] : makeDraft().turns,
        })), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/plan/drafts/draft-123/messages') {
        expect(init).toEqual(expect.objectContaining({ method: 'POST' }));
        return stream.response;
      }

      throw new Error(`unexpected fetch ${url}`);
    });

    const { container, root } = renderPage(fetchMock, '/plan?draft=draft-123');
    await flushPromises();

    const followUp = container.querySelector('textarea') as HTMLTextAreaElement;
    await act(async () => {
      followUp.value = 'Tighten the summary';
      followUp.dispatchEvent(new Event('input', { bubbles: true }));
    });

    const sendButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Send to Planner'));
    expect(sendButton).toBeTruthy();

    await act(async () => {
      sendButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    await act(async () => {
      stream.push('data: {"type":"status","phase":"planning","status":"started"}\n\n');
      stream.push('data: {"type":"assistant","phase":"planning","status":"completed","content":"I tightened the mission summary and task wording."}\n\n');
      stream.push('data: [DONE]\n\n');
    });
    await flushPromises();

    expect(container.textContent).toContain('I tightened the mission summary and task wording.');
    expect(container.textContent).toContain('Calculator Mission Refined');

    act(() => {
      root.unmount();
    });
  });

  it('renders a visible conflict recovery message for stale draft revisions', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/models') {
        return new Response(JSON.stringify(models), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/plan/drafts/draft-123') {
        return new Response(JSON.stringify(makeDraft()), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/plan/drafts/draft-123/spec') {
        return new Response(JSON.stringify({
          error: 'draft revision conflict',
          revision: 4,
        }), {
          status: 409,
          headers: { 'Content-Type': 'application/json' },
        });
      }

      throw new Error(`unexpected fetch ${url}`);
    });

    const { container, root } = renderPage(fetchMock, '/plan?draft=draft-123');
    await flushPromises();

    const summaryName = container.querySelector('input[aria-label="Mission name"]') as HTMLInputElement | null;
    expect(summaryName).toBeTruthy();

    await act(async () => {
      summaryName!.value = 'Conflicting Rename';
      summaryName!.dispatchEvent(new Event('input', { bubbles: true }));
    });

    const saveButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Save Summary'));
    expect(saveButton).toBeTruthy();

    await act(async () => {
      saveButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flushPromises();

    expect(container.textContent?.toLowerCase()).toContain('conflict');

    act(() => {
      root.unmount();
    });
  });

  it('shows parse errors for invalid yaml imports and keeps the current draft spec unchanged', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/models') {
        return new Response(JSON.stringify(models), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/plan/drafts/draft-123') {
        return new Response(JSON.stringify(makeDraft()), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/plan/drafts/draft-123/import-yaml') {
        expect(init).toEqual(expect.objectContaining({ method: 'POST' }));
        return new Response(JSON.stringify({
          error: 'invalid mission yaml: parse error on line 1',
        }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        });
      }

      throw new Error(`unexpected fetch ${url}`);
    });

    const { container, root } = renderPage(fetchMock, '/plan?draft=draft-123');
    await flushPromises();

    const importField = container.querySelector('textarea[aria-label="Import YAML"]') as HTMLTextAreaElement | null;
    expect(importField).toBeTruthy();

    await act(async () => {
      importField!.value = 'name: Broken\n  - nope';
      importField!.dispatchEvent(new Event('input', { bubbles: true }));
    });

    const applyButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Apply YAML'));
    expect(applyButton).toBeTruthy();

    await act(async () => {
      applyButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flushPromises();

    expect(container.textContent?.toLowerCase()).toContain('parse error');
    expect((container.querySelector('article input') as HTMLInputElement | null)?.value).toBe(
      'Draft the planner flow',
    );

    act(() => {
      root.unmount();
    });
  });

  it('imports valid yaml and refreshes the rendered task cards', async () => {
    const importedDraft = makeDraft({
      draft_spec: {
        ...makeDraft().draft_spec,
        name: 'Imported Mission',
        tasks: [
          {
            ...makeDraft().draft_spec.tasks[0],
            title: 'Imported task title',
          },
        ],
      },
    });

    let currentDraft = makeDraft();
    const importedYaml = serializeMissionPlanYaml(importedDraft.draft_spec);

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/models') {
        return new Response(JSON.stringify(models), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/plan/drafts/draft-123') {
        return new Response(JSON.stringify(currentDraft), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/plan/drafts/draft-123/import-yaml') {
        expect(JSON.parse(String(init?.body)).yaml).toBe(importedYaml);
        currentDraft = importedDraft;
        return new Response(JSON.stringify({
          id: 'draft-123',
          revision: 4,
          draft_spec: importedDraft.draft_spec,
        }), {
          headers: { 'Content-Type': 'application/json' },
        });
      }

      throw new Error(`unexpected fetch ${url}`);
    });

    const { container, root } = renderPage(fetchMock, '/plan?draft=draft-123');
    await flushPromises();

    const importField = container.querySelector('textarea[aria-label="Import YAML"]') as HTMLTextAreaElement | null;
    expect(importField).toBeTruthy();

    await act(async () => {
      importField!.value = importedYaml;
      importField!.dispatchEvent(new Event('input', { bubbles: true }));
    });

    const applyButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Apply YAML'));
    expect(applyButton).toBeTruthy();

    await act(async () => {
      applyButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flushPromises();

    expect((container.querySelector('input[aria-label="Mission name"]') as HTMLInputElement | null)?.value).toBe(
      'Imported Mission',
    );
    expect((container.querySelector('article input') as HTMLInputElement | null)?.value).toBe(
      'Imported task title',
    );

    act(() => {
      root.unmount();
    });
  });

  it('renders advisory warnings without disabling the send planner action', async () => {
    const warningDraft = makeDraft({
      draft_spec: {
        ...makeDraft().draft_spec,
        definition_of_done: ['done'],
        tasks: Array.from({ length: 8 }, (_, index) => ({
          id: String(index + 1).padStart(2, '0'),
          title: `Task ${index + 1}`,
          description: 'Do work',
          acceptance_criteria: ['please finish'],
          dependencies: [],
          max_retries: 3,
          output_artifacts: [],
          execution: index === 0 ? {
            worker: {
              agent: 'codex',
              model: 'claude-sonnet-4-5',
              thinking: 'medium',
            },
            reviewer: {
              agent: 'codex',
              model: 'claude-haiku-4-5',
              thinking: 'low',
            },
          } : undefined,
        })),
      },
      draft_notes: [
        {
          text: 'Retain until launch',
        },
      ],
    });

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/models') {
        return new Response(JSON.stringify(models), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/plan/drafts/draft-123') {
        return new Response(JSON.stringify(warningDraft), {
          headers: { 'Content-Type': 'application/json' },
        });
      }

      throw new Error(`unexpected fetch ${url}`);
    });

    const { container, root } = renderPage(fetchMock, '/plan?draft=draft-123');
    await flushPromises();

    expect(container.textContent).toContain('Advisory Flight Checks');
    expect(container.textContent).not.toContain('Draft-only notes are present');

    const followUp = container.querySelector('textarea#planner-follow-up') as HTMLTextAreaElement | null;
    expect(followUp).toBeTruthy();

    await act(async () => {
      followUp!.value = 'Keep the planner moving';
      followUp!.dispatchEvent(new Event('input', { bubbles: true }));
    });

    const sendButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Send to Planner')) as HTMLButtonElement | undefined;
    expect(sendButton).toBeTruthy();
    expect(sendButton?.disabled).toBe(false);

    act(() => {
      root.unmount();
    });
  });

  it('applies structured task edits against the draft spec', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/models') {
        return new Response(JSON.stringify(models), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/plan/drafts/draft-123') {
        return new Response(JSON.stringify(makeDraft()), {
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/plan/drafts/draft-123/spec') {
        expect(init).toEqual(expect.objectContaining({ method: 'PATCH' }));
        expect(String(init?.body)).toContain('Updated acceptance criterion');
        return new Response(JSON.stringify({ id: 'draft-123', revision: 4 }), {
          headers: { 'Content-Type': 'application/json' },
        });
      }

      throw new Error(`unexpected fetch ${url}`);
    });

    const { container, root } = renderPage(fetchMock, '/plan?draft=draft-123');
    await flushPromises();

    const acceptanceCriteriaField = container.querySelector(
      'textarea[aria-label="Task 01 acceptance criteria"]',
    ) as HTMLTextAreaElement | null;
    expect(acceptanceCriteriaField).toBeTruthy();

    await act(async () => {
      acceptanceCriteriaField!.value = 'Updated acceptance criterion';
      acceptanceCriteriaField!.dispatchEvent(new Event('input', { bubbles: true }));
    });

    const saveButton = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Save Tasks'));
    expect(saveButton).toBeTruthy();

    await act(async () => {
      saveButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flushPromises();

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/plan/drafts/draft-123/spec',
      expect.objectContaining({
        method: 'PATCH',
        body: expect.stringContaining('Updated acceptance criterion'),
      }),
    );

    act(() => {
      root.unmount();
    });
  });
});
