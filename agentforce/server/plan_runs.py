"""Durable planning run and version storage."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from . import state_io
from .plan_drafts import redact_persisted_content

_OWNER_DIR_MODE = 0o700
_OWNER_FILE_MODE = 0o600


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class PlanStepRecord:
    name: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    message: str = ""
    summary: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "message": self.message,
            "summary": self.summary,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PlanStepRecord:
        return cls(
            name=str(payload.get("name") or ""),
            status=str(payload.get("status") or ""),
            started_at=payload.get("started_at"),
            completed_at=payload.get("completed_at"),
            message=str(payload.get("message") or ""),
            summary=str(payload.get("summary") or ""),
            tokens_in=int(payload.get("tokens_in") or 0),
            tokens_out=int(payload.get("tokens_out") or 0),
            cost_usd=float(payload.get("cost_usd") or 0.0),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class PlanRunRecord:
    id: str
    draft_id: str
    base_revision: int
    head_revision_seen: int
    status: str
    trigger_kind: str
    trigger_message: str
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    stale: bool = False
    current_step: str | None = None
    steps: list[PlanStepRecord] = field(default_factory=list)
    result_version_id: str | None = None
    promoted_version_id: str | None = None
    launched_mission_id: str | None = None
    error_message: str = ""
    changelog: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    retry_group_id: str = ""
    retry_of_run_id: str | None = None
    retry_attempt: int = 0
    retry_limit: int = 0
    retry_locked: bool = False
    failed_step: str | None = None
    intervention_generation: int = 0
    resume_state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "draft_id": self.draft_id,
            "base_revision": self.base_revision,
            "head_revision_seen": self.head_revision_seen,
            "status": self.status,
            "trigger_kind": self.trigger_kind,
            "trigger_message": self.trigger_message,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "stale": self.stale,
            "current_step": self.current_step,
            "steps": [step.to_dict() for step in self.steps],
            "result_version_id": self.result_version_id,
            "promoted_version_id": self.promoted_version_id,
            "launched_mission_id": self.launched_mission_id,
            "error_message": self.error_message,
            "changelog": self.changelog,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
            "retry_group_id": self.retry_group_id or self.id,
            "retry_of_run_id": self.retry_of_run_id,
            "retry_attempt": self.retry_attempt,
            "retry_limit": self.retry_limit,
            "retry_locked": self.retry_locked,
            "failed_step": self.failed_step,
            "intervention_generation": self.intervention_generation,
            "resume_state": self.resume_state,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PlanRunRecord:
        raw_steps = list(payload.get("steps") or [])
        return cls(
            id=str(payload.get("id") or ""),
            draft_id=str(payload.get("draft_id") or ""),
            base_revision=int(payload.get("base_revision") or 0),
            head_revision_seen=int(payload.get("head_revision_seen") or payload.get("base_revision") or 0),
            status=str(payload.get("status") or "queued"),
            trigger_kind=str(payload.get("trigger_kind") or "auto"),
            trigger_message=str(payload.get("trigger_message") or ""),
            created_at=str(payload.get("created_at") or _utc_now()),
            started_at=payload.get("started_at"),
            completed_at=payload.get("completed_at"),
            stale=bool(payload.get("stale") or False),
            current_step=payload.get("current_step"),
            steps=[
                step if isinstance(step, PlanStepRecord) else PlanStepRecord.from_dict(step)
                for step in raw_steps
            ],
            result_version_id=payload.get("result_version_id"),
            promoted_version_id=payload.get("promoted_version_id"),
            launched_mission_id=payload.get("launched_mission_id"),
            error_message=str(payload.get("error_message") or ""),
            changelog=list(payload.get("changelog") or []),
            tokens_in=int(payload.get("tokens_in") or 0),
            tokens_out=int(payload.get("tokens_out") or 0),
            cost_usd=float(payload.get("cost_usd") or 0.0),
            retry_group_id=str(payload.get("retry_group_id") or payload.get("id") or ""),
            retry_of_run_id=payload.get("retry_of_run_id"),
            retry_attempt=int(payload.get("retry_attempt") or 0),
            retry_limit=int(payload.get("retry_limit") or 0),
            retry_locked=bool(payload.get("retry_locked") or False),
            failed_step=payload.get("failed_step"),
            intervention_generation=int(payload.get("intervention_generation") or 0),
            resume_state=dict(payload.get("resume_state") or {}),
        )

    def copy_with(self, **changes: Any) -> PlanRunRecord:
        payload = self.to_dict()
        payload.update(changes)
        return PlanRunRecord.from_dict(payload)


@dataclass(frozen=True)
class PlanVersionRecord:
    id: str
    draft_id: str
    source_run_id: str
    revision_base: int
    created_at: str
    draft_spec_snapshot: dict[str, Any]
    changelog: list[str] = field(default_factory=list)
    validation: dict[str, Any] = field(default_factory=dict)
    launched_mission_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "draft_id": self.draft_id,
            "source_run_id": self.source_run_id,
            "revision_base": self.revision_base,
            "created_at": self.created_at,
            "draft_spec_snapshot": self.draft_spec_snapshot,
            "changelog": self.changelog,
            "validation": self.validation,
            "launched_mission_id": self.launched_mission_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PlanVersionRecord:
        return cls(
            id=str(payload.get("id") or ""),
            draft_id=str(payload.get("draft_id") or ""),
            source_run_id=str(payload.get("source_run_id") or ""),
            revision_base=int(payload.get("revision_base") or 0),
            created_at=str(payload.get("created_at") or _utc_now()),
            draft_spec_snapshot=dict(payload.get("draft_spec_snapshot") or {}),
            changelog=list(payload.get("changelog") or []),
            validation=dict(payload.get("validation") or {}),
            launched_mission_id=payload.get("launched_mission_id"),
        )

    def copy_with(self, **changes: Any) -> PlanVersionRecord:
        payload = self.to_dict()
        payload.update(changes)
        return PlanVersionRecord.from_dict(payload)


class PlanRunStore:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root or (state_io.get_agentforce_home() / "plans")
        self._runs_dir = self._root / "runs"
        self._versions_dir = self._root / "versions"

    def create_run(
        self,
        run_id: str,
        *,
        draft_id: str,
        base_revision: int,
        trigger_kind: str,
        trigger_message: str,
    ) -> PlanRunRecord:
        run = PlanRunRecord(
            id=run_id,
            draft_id=draft_id,
            base_revision=base_revision,
            head_revision_seen=base_revision,
            status="queued",
            trigger_kind=trigger_kind,
            trigger_message=trigger_message,
            created_at=_utc_now(),
        )
        self.save_run(run)
        return run

    def load_run(self, run_id: str) -> PlanRunRecord | None:
        path = self._runs_dir / f"{run_id}.json"
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as handle:
            return PlanRunRecord.from_dict(json.load(handle))

    def save_run(self, run: PlanRunRecord) -> None:
        self._write_json(self._runs_dir / f"{run.id}.json", run.to_dict())

    def list_runs_for_draft(self, draft_id: str) -> list[PlanRunRecord]:
        if not self._runs_dir.exists():
            return []
        runs: list[PlanRunRecord] = []
        for path in sorted(self._runs_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                with path.open(encoding="utf-8") as handle:
                    run = PlanRunRecord.from_dict(json.load(handle))
            except Exception:
                continue
            if run.draft_id == draft_id:
                runs.append(run)
        return runs

    def create_version(
        self,
        version_id: str,
        *,
        draft_id: str,
        source_run_id: str,
        revision_base: int,
        draft_spec_snapshot: dict[str, Any],
        changelog: list[str],
        validation: dict[str, Any],
    ) -> PlanVersionRecord:
        version = PlanVersionRecord(
            id=version_id,
            draft_id=draft_id,
            source_run_id=source_run_id,
            revision_base=revision_base,
            created_at=_utc_now(),
            draft_spec_snapshot=dict(draft_spec_snapshot),
            changelog=list(changelog),
            validation=dict(validation),
        )
        self.save_version(version)
        return version

    def save_version(self, version: PlanVersionRecord) -> None:
        self._write_json(self._versions_dir / f"{version.id}.json", version.to_dict())

    def load_version(self, version_id: str) -> PlanVersionRecord | None:
        path = self._versions_dir / f"{version_id}.json"
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as handle:
            return PlanVersionRecord.from_dict(json.load(handle))

    def list_versions_for_draft(self, draft_id: str) -> list[PlanVersionRecord]:
        if not self._versions_dir.exists():
            return []
        versions: list[PlanVersionRecord] = []
        for path in sorted(self._versions_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                with path.open(encoding="utf-8") as handle:
                    version = PlanVersionRecord.from_dict(json.load(handle))
            except Exception:
                continue
            if version.draft_id == draft_id:
                versions.append(version)
        return versions

    def summarize_for_mission(self, mission_id: str) -> dict[str, Any] | None:
        linked: list[PlanVersionRecord] = []
        for version in self.list_all_versions():
            if version.launched_mission_id == mission_id:
                linked.append(version)
        if not linked:
            return None
        version = sorted(linked, key=lambda item: item.created_at)[-1]
        run = self.load_run(version.source_run_id)
        if run is None:
            return None
        return {
            "draft_id": version.draft_id,
            "source_run_id": run.id,
            "source_version_id": version.id,
            "planning_cost_usd": run.cost_usd,
            "planning_tokens_in": run.tokens_in,
            "planning_tokens_out": run.tokens_out,
            "changelog": version.changelog,
            "created_at": version.created_at,
        }

    def list_all_versions(self) -> list[PlanVersionRecord]:
        if not self._versions_dir.exists():
            return []
        versions: list[PlanVersionRecord] = []
        for path in self._versions_dir.glob("*.json"):
            try:
                with path.open(encoding="utf-8") as handle:
                    versions.append(PlanVersionRecord.from_dict(json.load(handle)))
            except Exception:
                continue
        return versions

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, _OWNER_DIR_MODE)
        sanitized = redact_persisted_content(payload)
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(json.dumps(sanitized, indent=2))
        os.chmod(temp_path, _OWNER_FILE_MODE)
        os.replace(temp_path, path)
        os.chmod(path, _OWNER_FILE_MODE)
