import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import BlackHoleHero from "./BlackHoleHero";

const animationHarness = vi.hoisted(() => {
  let nextId = 1;
  let now = 16;
  const callbacks = new Map<number, FrameRequestCallback>();

  return {
    request(callback: FrameRequestCallback): number {
      const id = nextId;
      nextId += 1;
      callbacks.set(id, callback);
      return id;
    },
    cancel(id: number): void {
      callbacks.delete(id);
    },
    flush(stepMs = 16): void {
      const pending = Array.from(callbacks.values());
      callbacks.clear();
      now += stepMs;
      for (const callback of pending) {
        callback(now);
      }
    },
    pending(): number {
      return callbacks.size;
    },
    reset(): void {
      nextId = 1;
      now = 16;
      callbacks.clear();
    },
  };
});

const intersectionHarness = vi.hoisted(() => {
  let callback: IntersectionObserverCallback | null = null;
  return {
    bind(next: IntersectionObserverCallback): void {
      callback = next;
    },
    emit(isIntersecting: boolean): void {
      callback?.(
        [
          {
            isIntersecting,
            intersectionRatio: isIntersecting ? 1 : 0,
            boundingClientRect: {} as DOMRectReadOnly,
            intersectionRect: {} as DOMRectReadOnly,
            rootBounds: null,
            target: document.createElement("canvas"),
            time: 0,
          },
        ],
        {} as IntersectionObserver,
      );
    },
    reset(): void {
      callback = null;
    },
  };
});

class MockResizeObserver {
  observe(): void {}

  disconnect(): void {}
}

class MockIntersectionObserver {
  constructor(callback: IntersectionObserverCallback) {
    intersectionHarness.bind(callback);
  }

  observe(): void {}

  disconnect(): void {
    intersectionHarness.reset();
  }
}

function createContextMock(): CanvasRenderingContext2D {
  const gradient = { addColorStop: vi.fn() };
  const context = {
    clearRect: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    fillRect: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    fill: vi.fn(),
    ellipse: vi.fn(),
    createRadialGradient: vi.fn(() => gradient),
    set fillStyle(_value: string | CanvasGradient | CanvasPattern) {},
    set strokeStyle(_value: string | CanvasGradient | CanvasPattern) {},
    set lineWidth(_value: number) {},
    set filter(_value: string) {},
    set lineCap(_value: CanvasLineCap) {},
    set globalCompositeOperation(_value: GlobalCompositeOperation) {},
    set shadowColor(_value: string) {},
    set shadowBlur(_value: number) {},
  };

  return context as unknown as CanvasRenderingContext2D;
}

function renderHero(reducedMotion = false): { container: HTMLDivElement; root: Root } {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(
      <BlackHoleHero
        campaignState="child_mission_running"
        campaignStatus="child_mission_running"
        loopNumber={2}
        metricLabel="Violations"
        metricBefore={5}
        metricAfter={4}
        reducedMotion={reducedMotion}
      />,
    );
  });

  return { container, root };
}

let visibilityState: DocumentVisibilityState = "visible";

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  animationHarness.reset();
  intersectionHarness.reset();
  visibilityState = "visible";

  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
    () => createContextMock(),
  );
  vi.spyOn(HTMLCanvasElement.prototype, "getBoundingClientRect").mockImplementation(
    () => ({
      width: 960,
      height: 420,
      top: 0,
      left: 0,
      right: 960,
      bottom: 420,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    }) as DOMRect,
  );
  vi.stubGlobal("ResizeObserver", MockResizeObserver);
  vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn((callback: FrameRequestCallback) => animationHarness.request(callback)),
  );
  vi.stubGlobal(
    "cancelAnimationFrame",
    vi.fn((id: number) => animationHarness.cancel(id)),
  );
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => visibilityState,
  });
});

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

afterAll(() => {
  delete (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT;
});

describe("BlackHoleHero", () => {
  it("pauses the animation when hidden or offscreen and resumes when visible again", () => {
    const { root } = renderHero();
    const requestAnimationFrameMock = window.requestAnimationFrame as unknown as ReturnType<typeof vi.fn>;
    const cancelAnimationFrameMock = window.cancelAnimationFrame as unknown as ReturnType<typeof vi.fn>;

    act(() => {
      animationHarness.flush();
      animationHarness.flush();
    });

    expect(requestAnimationFrameMock.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(animationHarness.pending()).toBe(1);

    visibilityState = "hidden";
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(cancelAnimationFrameMock).toHaveBeenCalled();
    expect(animationHarness.pending()).toBe(0);

    const scheduledBeforeResume = requestAnimationFrameMock.mock.calls.length;
    visibilityState = "visible";
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(requestAnimationFrameMock.mock.calls.length).toBeGreaterThan(scheduledBeforeResume);

    act(() => {
      animationHarness.flush();
      intersectionHarness.emit(false);
    });
    expect(animationHarness.pending()).toBe(0);

    const scheduledBeforeViewportResume = requestAnimationFrameMock.mock.calls.length;
    act(() => {
      intersectionHarness.emit(true);
    });
    expect(requestAnimationFrameMock.mock.calls.length).toBeGreaterThan(scheduledBeforeViewportResume);

    act(() => {
      root.unmount();
    });
  });

  it("renders a static frame without keeping the animation loop alive in reduced motion mode", () => {
    const { root } = renderHero(true);
    const requestAnimationFrameMock = window.requestAnimationFrame as unknown as ReturnType<typeof vi.fn>;

    act(() => {
      animationHarness.flush();
    });

    expect(requestAnimationFrameMock).toHaveBeenCalledTimes(1);
    expect(animationHarness.pending()).toBe(0);

    act(() => {
      root.unmount();
    });
  });
});
