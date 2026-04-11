import { useEffect, useMemo, useRef, useState } from "react";

interface BlackHoleHeroProps {
  campaignState: string;
  campaignStatus?: string;
  loopNumber?: number;
  metricLabel?: string;
  metricBefore?: string | number;
  metricBeforeLabel?: string;
  metricAfter?: string | number;
  metricAfterLabel?: string;
  title?: string;
  description?: string;
  reducedMotion?: boolean;
  className?: string;
}

type HeroTone = {
  accent: string;
  glow: string;
  badge: string;
};

const TAU = Math.PI * 2;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function hashString(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function formatMetric(value?: string | number): string {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value.toLocaleString() : "—";
  }
  if (typeof value === "string" && value.trim()) {
    return value;
  }
  return "—";
}

function toneForState(state: string): HeroTone {
  const normalized = state.trim().toLowerCase();
  if (
    normalized.includes("block") ||
    normalized.includes("hold") ||
    normalized.includes("error") ||
    normalized.includes("fail")
  ) {
    return {
      accent: "text-red",
      glow: "rgba(255, 107, 107, 0.38)",
      badge: "border-red/25 bg-red/10 text-red",
    };
  }

  if (
    normalized.includes("ready") ||
    normalized.includes("launch") ||
    normalized.includes("go")
  ) {
    return {
      accent: "text-green",
      glow: "rgba(46, 204, 138, 0.35)",
      badge: "border-green/25 bg-green/10 text-green",
    };
  }

  if (
    normalized.includes("run") ||
    normalized.includes("active") ||
    normalized.includes("live") ||
    normalized.includes("stream")
  ) {
    return {
      accent: "text-cyan",
      glow: "rgba(34, 211, 238, 0.35)",
      badge: "border-cyan/25 bg-cyan/10 text-cyan",
    };
  }

  return {
    accent: "text-amber",
    glow: "rgba(240, 180, 41, 0.32)",
    badge: "border-amber/25 bg-amber/10 text-amber",
  };
}

function drawEllipseSegment(
  ctx: CanvasRenderingContext2D,
  centerX: number,
  centerY: number,
  radiusX: number,
  radiusY: number,
  angleA: number,
  angleB: number,
  phase: number,
  wobble: number,
): void {
  const aX = centerX + Math.cos(angleA) * radiusX * (1 + Math.sin(angleA * 2.7 + phase) * wobble);
  const aY = centerY + Math.sin(angleA) * radiusY * (1 + Math.cos(angleA * 1.9 + phase * 0.7) * wobble * 0.5);
  const bX = centerX + Math.cos(angleB) * radiusX * (1 + Math.sin(angleB * 2.7 + phase) * wobble);
  const bY = centerY + Math.sin(angleB) * radiusY * (1 + Math.cos(angleB * 1.9 + phase * 0.7) * wobble * 0.5);

  ctx.beginPath();
  ctx.moveTo(aX, aY);
  ctx.lineTo(bX, bY);
  ctx.stroke();
}

function drawHotspot(
  ctx: CanvasRenderingContext2D,
  centerX: number,
  centerY: number,
  radiusX: number,
  radiusY: number,
  angle: number,
  glow: string,
  scale = 1,
): void {
  const x = centerX + Math.cos(angle) * radiusX;
  const y = centerY + Math.sin(angle) * radiusY;
  const gradient = ctx.createRadialGradient(x, y, 0, x, y, radiusX * 0.18 * scale);
  gradient.addColorStop(0, glow);
  gradient.addColorStop(0.3, glow.replace(/0\.\d+\)$/, "0.2)"));
  gradient.addColorStop(1, "rgba(0, 0, 0, 0)");
  ctx.fillStyle = gradient;
  ctx.beginPath();
  ctx.ellipse(x, y, radiusX * 0.14 * scale, radiusY * 0.14 * scale, angle * 0.12, 0, TAU);
  ctx.fill();
}

function drawHeroFrame(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  elapsedMs: number,
  seed: number,
  reducedMotion: boolean,
  tone: HeroTone,
): void {
  ctx.clearRect(0, 0, width, height);
  ctx.save();

  const centerX = width * 0.52;
  const centerY = height * 0.53;
  const coreRadius = Math.min(width, height) * 0.15;
  const diskRadiusX = Math.min(width, height) * 0.33;
  const diskRadiusY = Math.min(width, height) * 0.11;
  const time = reducedMotion ? 0 : elapsedMs / 1000;
  const phase = seed * 0.000031 + time * 0.8;
  const drift = 0.018 + ((seed >>> 3) % 9) * 0.0025;
  const spin = 1.35 + ((seed >>> 8) % 7) * 0.08;
  const lightAngle = Math.PI * 0.95 + Math.sin(phase * 0.65) * 0.08;
  const warmAngle = Math.PI * 0.05 + Math.cos(phase * 0.37) * 0.13;

  const bg = ctx.createRadialGradient(
    centerX - width * 0.06,
    centerY - height * 0.18,
    0,
    centerX,
    centerY,
    Math.max(width, height) * 0.9,
  );
  bg.addColorStop(0, "rgba(15, 24, 42, 0.96)");
  bg.addColorStop(0.45, "rgba(8, 12, 21, 0.98)");
  bg.addColorStop(1, "rgba(2, 3, 5, 1)");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, width, height);

  const halo = ctx.createRadialGradient(
    centerX,
    centerY,
    coreRadius * 0.2,
    centerX,
    centerY,
    Math.max(diskRadiusX, diskRadiusY) * 3.4,
  );
  halo.addColorStop(0, "rgba(255, 196, 120, 0.02)");
  halo.addColorStop(0.25, "rgba(34, 211, 238, 0.04)");
  halo.addColorStop(0.55, "rgba(240, 180, 41, 0.08)");
  halo.addColorStop(1, "rgba(0, 0, 0, 0)");
  ctx.fillStyle = halo;
  ctx.fillRect(0, 0, width, height);

  ctx.globalCompositeOperation = "lighter";

  ctx.save();
  ctx.filter = "blur(6px)";
  ctx.lineCap = "round";
  ctx.strokeStyle = "rgba(255, 164, 73, 0.12)";
  ctx.lineWidth = diskRadiusY * 0.95;
  for (let segment = 0; segment < 32; segment += 1) {
    const start = (segment / 32) * TAU;
    const end = start + TAU / 32 * 0.58;
    drawEllipseSegment(ctx, centerX, centerY, diskRadiusX, diskRadiusY, start, end, phase, drift * 0.5);
  }
  ctx.restore();

  ctx.save();
  ctx.lineCap = "round";
  ctx.filter = "blur(1.25px)";
  for (let segment = 0; segment < 140; segment += 1) {
    const start = (segment / 140) * TAU + time * spin * 0.12;
    const end = start + TAU / 140 * 1.08;
    const angle = start + TAU / 280;
    const front = clamp(Math.cos(angle - lightAngle) * 0.55 + 0.55, 0, 1);
    const crescent = clamp(Math.cos(angle - warmAngle) * 0.45 + 0.55, 0, 1);
    const turbulence = Math.sin(angle * 7.2 + phase * 3.1) * 0.07 + Math.sin(angle * 13.4 + seed * 0.001) * 0.04;
    const energy = clamp(front * 0.65 + crescent * 0.35 + turbulence, 0, 1);
    const widthMix = 1.2 + energy * 5.6;
    const alpha = reducedMotion ? 0.08 + energy * 0.13 : 0.05 + energy * 0.22;
    const coreMix = 1 - Math.min(1, Math.abs(Math.sin(angle)) * 0.7);

    ctx.strokeStyle = `rgba(${Math.round(255)}, ${Math.round(184 + 42 * energy)}, ${Math.round(110 + 90 * energy)}, ${alpha})`;
    ctx.lineWidth = widthMix;
    drawEllipseSegment(ctx, centerX, centerY, diskRadiusX * (1 + turbulence * 0.25), diskRadiusY * (1 + turbulence * 0.45), start, end, phase, drift);

    if (coreMix > 0.15) {
      ctx.strokeStyle = `rgba(255, ${Math.round(224 * energy + 28)}, ${Math.round(210 * coreMix)}, ${alpha * 0.55})`;
      ctx.lineWidth = widthMix * 0.55;
      drawEllipseSegment(ctx, centerX, centerY, diskRadiusX * 0.91, diskRadiusY * 0.91, start, end, phase * 1.1, drift * 0.3);
    }
  }
  ctx.restore();

  ctx.save();
  ctx.globalCompositeOperation = "screen";
  ctx.filter = "blur(10px)";
  ctx.strokeStyle = "rgba(255, 197, 109, 0.12)";
  ctx.lineWidth = 2;
  for (let arc = 0; arc < 3; arc += 1) {
    const arcPhase = phase * (0.45 + arc * 0.12) + arc * 1.2;
    ctx.beginPath();
    ctx.ellipse(
      centerX + Math.cos(arcPhase) * coreRadius * 0.12,
      centerY + Math.sin(arcPhase * 0.8) * coreRadius * 0.08,
      diskRadiusX * (1.18 + arc * 0.14),
      diskRadiusY * (0.86 + arc * 0.1),
      -0.2 + arc * 0.12,
      Math.PI * (0.12 + arc * 0.04),
      Math.PI * (0.82 + arc * 0.08),
    );
    ctx.stroke();
  }
  ctx.restore();

  ctx.save();
  ctx.globalCompositeOperation = "screen";
  ctx.fillStyle = "rgba(0, 0, 0, 1)";
  ctx.shadowColor = "rgba(0, 0, 0, 0.9)";
  ctx.shadowBlur = coreRadius * 0.28;
  ctx.beginPath();
  ctx.ellipse(centerX, centerY, coreRadius * 0.72, coreRadius * 0.68, 0, 0, TAU);
  ctx.fill();

  const horizon = ctx.createRadialGradient(centerX, centerY, coreRadius * 0.28, centerX, centerY, coreRadius * 1.12);
  horizon.addColorStop(0, "rgba(0, 0, 0, 0.9)");
  horizon.addColorStop(0.65, "rgba(0, 0, 0, 0.95)");
  horizon.addColorStop(0.84, "rgba(255, 184, 73, 0.08)");
  horizon.addColorStop(1, "rgba(255, 211, 152, 0)");
  ctx.fillStyle = horizon;
  ctx.beginPath();
  ctx.ellipse(centerX, centerY, coreRadius * 1.05, coreRadius * 1.02, 0, 0, TAU);
  ctx.fill();
  ctx.restore();

  drawHotspot(ctx, centerX, centerY, diskRadiusX, diskRadiusY, lightAngle + Math.sin(phase * 1.8) * 0.12, "rgba(255, 231, 172, 0.55)", 0.88);
  drawHotspot(ctx, centerX, centerY, diskRadiusX * 0.92, diskRadiusY * 0.92, warmAngle - Math.sin(phase * 1.3) * 0.16, tone.glow, 0.72);

  ctx.save();
  ctx.globalCompositeOperation = "screen";
  ctx.filter = "blur(0.8px)";
  ctx.strokeStyle = "rgba(255, 248, 220, 0.12)";
  ctx.lineWidth = 1.25;
  ctx.beginPath();
  ctx.ellipse(centerX, centerY, diskRadiusX * 1.4, diskRadiusY * 1.08, -0.16, Math.PI * 0.95, Math.PI * 1.62);
  ctx.stroke();
  ctx.restore();

  ctx.restore();
}

function describeMetric(metricLabel?: string, before?: string | number, after?: string | number): string {
  const pieces = [metricLabel ?? "Metric", formatMetric(before), formatMetric(after)];
  return `${pieces[0]} moved from ${pieces[1]} to ${pieces[2]}.`;
}

function usePrefersReducedMotion(override?: boolean): boolean {
  const [prefersReduced, setPrefersReduced] = useState(() => {
    if (typeof override === "boolean") {
      return override;
    }
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return false;
    }
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  });

  useEffect(() => {
    if (typeof override === "boolean") {
      setPrefersReduced(override);
      return;
    }
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      setPrefersReduced(false);
      return;
    }

    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = (): void => setPrefersReduced(media.matches);
    update();

    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", update);
      return () => media.removeEventListener("change", update);
    }

    media.addListener(update);
    return () => media.removeListener(update);
  }, [override]);

  return prefersReduced;
}

export default function BlackHoleHero({
  campaignState,
  campaignStatus,
  loopNumber = 0,
  metricLabel,
  metricBefore,
  metricBeforeLabel,
  metricAfter,
  metricAfterLabel,
  title = "Campaign telemetry",
  description = "The accretion flow stays asymmetrical on purpose so the live state reads like motion, not a spinner.",
  reducedMotion,
  className,
}: BlackHoleHeroProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stateLabel = campaignStatus ?? campaignState;
  const tone = useMemo(() => toneForState(stateLabel), [stateLabel]);
  const seed = useMemo(() => hashString(`${stateLabel}|${loopNumber}`), [stateLabel, loopNumber]);
  const prefersReducedMotion = usePrefersReducedMotion(reducedMotion);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }

    let context: CanvasRenderingContext2D | null = null;
    try {
      context = canvas.getContext("2d");
    } catch {
      return;
    }
    if (!context) {
      return;
    }

    let disposed = false;
    let animationFrame = 0;
    let width = 0;
    let height = 0;

    const resize = (): void => {
      if (disposed) {
        return;
      }

      const rect = canvas.getBoundingClientRect();
      const devicePixelRatio = clamp(window.devicePixelRatio || 1, 1, 2.25);
      const nextWidth = Math.max(1, Math.floor(rect.width * devicePixelRatio));
      const nextHeight = Math.max(1, Math.floor(rect.height * devicePixelRatio));

      if (canvas.width !== nextWidth || canvas.height !== nextHeight) {
        canvas.width = nextWidth;
        canvas.height = nextHeight;
      }

      width = nextWidth;
      height = nextHeight;
      drawHeroFrame(context, width, height, performance.now(), seed, prefersReducedMotion, tone);
    };

    const resizeObserver = typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(() => {
          resize();
        })
      : null;

    resizeObserver?.observe(canvas);
    window.addEventListener("resize", resize);
    resize();

    const tick = (now: number): void => {
      if (disposed) {
        return;
      }
      drawHeroFrame(context, width, height, now, seed, prefersReducedMotion, tone);
      animationFrame = window.requestAnimationFrame(tick);
    };

    if (!prefersReducedMotion) {
      animationFrame = window.requestAnimationFrame(tick);
    }

    return () => {
      disposed = true;
      window.cancelAnimationFrame(animationFrame);
      resizeObserver?.disconnect();
      window.removeEventListener("resize", resize);
    };
  }, [prefersReducedMotion, seed, tone]);

  const beforeLabel = metricBeforeLabel ?? "Before";
  const afterLabel = metricAfterLabel ?? "After";
  const metricSummary = describeMetric(metricLabel, metricBefore, metricAfter);

  return (
    <section
      className={[
        "overflow-hidden rounded-[1.6rem] border border-border bg-[radial-gradient(circle_at_top_left,rgba(255,196,120,0.12),transparent_28%),radial-gradient(circle_at_70%_30%,rgba(34,211,238,0.08),transparent_34%),linear-gradient(180deg,rgba(7,12,22,0.98),rgba(3,5,9,0.98))]",
        className ?? "",
      ].join(" ")}
      aria-label={metricSummary}
    >
      <div className="relative isolate min-h-[22rem] overflow-hidden sm:min-h-[24rem] lg:min-h-[27rem]">
        <canvas
          ref={canvasRef}
          className="absolute inset-0 h-full w-full"
          aria-hidden="true"
        />

        <div
          className="absolute inset-0 bg-[radial-gradient(circle_at_50%_45%,rgba(255,255,255,0.06),transparent_32%),linear-gradient(90deg,rgba(0,0,0,0.16),transparent_20%,transparent_80%,rgba(0,0,0,0.22))]"
          aria-hidden="true"
        />

        <div className="absolute inset-0 flex flex-col justify-between p-5 sm:p-6">
          <div className="flex items-start justify-between gap-4">
            <div className="max-w-[34rem]">
              <div className={`text-[11px] font-semibold uppercase tracking-[0.16em] ${tone.accent}`}>
                {stateLabel}
              </div>
              <h2 className="mt-2 text-[clamp(1.7rem,3vw,2.55rem)] font-semibold tracking-[-0.05em] text-text">
                {title}
              </h2>
              <p className="mt-3 max-w-[42rem] text-sm leading-7 text-dim">
                {description}
              </p>
            </div>

            <div className="flex flex-col items-end gap-2 text-[11px]">
              <span className={`rounded-full border px-3 py-1 font-mono uppercase tracking-[0.12em] ${tone.badge}`}>
                loop {String(loopNumber).padStart(2, "0")}
              </span>
              {prefersReducedMotion ? (
                <span className="rounded-full border border-border bg-surface/90 px-3 py-1 font-mono text-dim">
                  reduced motion
                </span>
              ) : (
                <span className="rounded-full border border-border bg-surface/80 px-3 py-1 font-mono text-dim">
                  live accretion
                </span>
              )}
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] md:items-end">
            <div className="rounded-[1.1rem] border border-border/70 bg-black/22 px-4 py-3 backdrop-blur-sm">
              <div className="text-[11px] uppercase tracking-[0.12em] text-muted">
                {metricLabel ?? "Mission delta"}
              </div>
              <div className="mt-2 flex flex-wrap items-end gap-x-5 gap-y-2">
                <div>
                  <div className="font-mono text-[11px] uppercase tracking-[0.1em] text-dim">
                    {beforeLabel}
                  </div>
                  <div className="mt-1 text-hero text-text">
                    {formatMetric(metricBefore)}
                  </div>
                </div>
                <div className="pb-1 text-sm text-dim">→</div>
                <div>
                  <div className="font-mono text-[11px] uppercase tracking-[0.1em] text-dim">
                    {afterLabel}
                  </div>
                  <div className="mt-1 text-hero text-text">
                    {formatMetric(metricAfter)}
                  </div>
                </div>
              </div>
            </div>

            <div className="rounded-[1.1rem] border border-border/70 bg-black/18 px-4 py-3 backdrop-blur-sm">
              <div className="text-[11px] uppercase tracking-[0.12em] text-muted">
                Campaign State
              </div>
              <div className="mt-2 text-base font-semibold tracking-[-0.03em] text-text">
                {stateLabel}
              </div>
              <div className="mt-3 text-sm leading-6 text-dim">
                The bright crescent tracks the current loop while the outer arcs stay faint enough for integration overlays to sit above them.
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
