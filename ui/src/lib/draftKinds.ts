import type { DraftKind, MissionDraft, MissionSummary } from "./types";

export const SIMPLE_PLAN_DRAFT_KIND: DraftKind = "simple_plan";
export const BLACK_HOLE_DRAFT_KIND: DraftKind = "black_hole";

export function normalizeDraftKind(value: unknown): DraftKind {
  return value === BLACK_HOLE_DRAFT_KIND ? BLACK_HOLE_DRAFT_KIND : SIMPLE_PLAN_DRAFT_KIND;
}

export function draftKindFromValidation(validation: unknown): DraftKind {
  if (validation && typeof validation === "object") {
    const record = validation as Record<string, unknown>;
    if (record.black_hole_config && typeof record.black_hole_config === "object") {
      return BLACK_HOLE_DRAFT_KIND;
    }
    return normalizeDraftKind(record.draft_kind);
  }
  return SIMPLE_PLAN_DRAFT_KIND;
}

export function draftKindForEntity(
  entity: Pick<MissionDraft, "draft_kind" | "validation"> | Pick<MissionSummary, "draft_kind"> | null | undefined,
): DraftKind {
  if (!entity) {
    return SIMPLE_PLAN_DRAFT_KIND;
  }
  if ("validation" in entity) {
    return entity.draft_kind ? normalizeDraftKind(entity.draft_kind) : draftKindFromValidation(entity.validation);
  }
  return normalizeDraftKind(entity.draft_kind);
}

export function isBlackHoleDraft(
  entity: Pick<MissionDraft, "draft_kind" | "validation"> | Pick<MissionSummary, "draft_kind"> | null | undefined,
): boolean {
  return draftKindForEntity(entity) === BLACK_HOLE_DRAFT_KIND;
}

export function draftHref(
  entity: { mission_id?: string; id?: string; draft_kind?: DraftKind | string | null; validation?: Record<string, unknown> } | null | undefined,
): string {
  const draftId = entity?.mission_id ?? entity?.id ?? "";
  return draftKindForEntity(entity as Pick<MissionDraft, "draft_kind" | "validation"> | Pick<MissionSummary, "draft_kind"> | null)
    === BLACK_HOLE_DRAFT_KIND
    ? `/black-hole/${draftId}`
    : `/plan/${draftId}`;
}
