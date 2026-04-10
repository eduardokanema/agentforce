"""Durable mission plan draft storage."""
from __future__ import annotations

import fcntl
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from . import state_io

_DRAFT_DIR_NAME = "drafts"
_OWNER_DIR_MODE = 0o700
_OWNER_FILE_MODE = 0o600
_TERMINAL_STATUSES = {"finalized", "cancelled"}
_SECRET_PATTERNS = (
    re.compile(r"Bearer\s+[^\s\"']+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]+"),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _redact_string(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    return value


def redact_persisted_content(value: Any) -> Any:
    """Strip obvious secret literals before draft content is written to disk."""
    return _sanitize(value)


@dataclass(frozen=True)
class MissionDraftV1:
    id: str
    revision: int
    status: str
    name: str
    goal: str
    created_at: datetime
    updated_at: datetime
    draft_spec: dict[str, Any]
    turns: list[dict[str, Any]]
    validation: dict[str, Any]
    activity_log: list[Any]
    approved_models: list[str]
    workspace_paths: list[str]
    companion_profile: dict[str, Any]
    draft_notes: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "revision": self.revision,
            "status": self.status,
            "name": self.name,
            "goal": self.goal,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "draft_spec": self.draft_spec,
            "turns": self.turns,
            "validation": self.validation,
            "activity_log": self.activity_log,
            "approved_models": self.approved_models,
            "workspace_paths": self.workspace_paths,
            "companion_profile": self.companion_profile,
            "draft_notes": self.draft_notes,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MissionDraftV1:
        draft_spec = dict(payload.get("draft_spec") or {})

        created_at_val = payload.get("created_at")
        if isinstance(created_at_val, str):
            created_at = _parse_timestamp(created_at_val) or _utc_now()
        elif isinstance(created_at_val, datetime):
            created_at = created_at_val
        else:
            created_at = _utc_now()

        updated_at_val = payload.get("updated_at")
        if isinstance(updated_at_val, str):
            updated_at = _parse_timestamp(updated_at_val) or _utc_now()
        elif isinstance(updated_at_val, datetime):
            updated_at = updated_at_val
        else:
            updated_at = _utc_now()

        return cls(
            id=str(payload["id"]),
            revision=int(payload["revision"]),
            status=str(payload["status"]),
            name=str(draft_spec.get("name") or payload.get("name") or ""),
            goal=str(draft_spec.get("goal") or payload.get("goal") or ""),
            created_at=created_at,
            updated_at=updated_at,
            draft_spec=draft_spec,
            turns=list(payload.get("turns") or []),
            validation=dict(payload.get("validation") or {}),
            activity_log=list(payload.get("activity_log") or []),
            approved_models=list(payload.get("approved_models") or []),
            workspace_paths=list(payload.get("workspace_paths") or []),
            companion_profile=dict(payload.get("companion_profile") or {}),
            draft_notes=list(payload.get("draft_notes") or []),
        )

    def copy_with(self, **changes: Any) -> MissionDraftV1:
        payload = self.to_dict()
        payload.update(changes)
        return MissionDraftV1.from_dict(payload)


@dataclass(frozen=True)
class DraftSaveResult:
    status: str
    draft: MissionDraftV1 | None


class PlanDraftStore:
    """JSON-backed store for mission planner drafts."""

    def __init__(self, drafts_dir: Path | None = None) -> None:
        self._drafts_dir = drafts_dir or (state_io.get_agentforce_home() / _DRAFT_DIR_NAME)

    def create(
        self,
        draft_id: str,
        *,
        status: str,
        draft_spec: dict[str, Any],
        turns: list[dict[str, Any]],
        validation: dict[str, Any],
        activity_log: list[Any],
        approved_models: list[str],
        workspace_paths: list[str],
        companion_profile: dict[str, Any],
        draft_notes: list[dict[str, Any]],
    ) -> MissionDraftV1:
        now = _utc_now()
        draft = MissionDraftV1(
            id=draft_id,
            revision=1,
            status=status,
            name=str(draft_spec.get("name") or ""),
            goal=str(draft_spec.get("goal") or ""),
            created_at=now,
            updated_at=now,
            draft_spec=dict(draft_spec),
            turns=list(turns),
            validation=dict(validation),
            activity_log=list(activity_log),
            approved_models=list(approved_models),
            workspace_paths=list(workspace_paths),
            companion_profile=dict(companion_profile),
            draft_notes=list(draft_notes),
        )
        sanitized = self._sanitized_draft(draft)
        with self._locked_store():
            self._write_draft(sanitized)
        return sanitized

    def load(self, draft_id: str) -> MissionDraftV1 | None:
        path = self._draft_path(draft_id)
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        draft = MissionDraftV1.from_dict(payload)
        return draft.copy_with(updated_at=self._last_activity_at(draft, path))

    def list_all(self, include_terminal: bool = False) -> list[MissionDraftV1]:
        """Scan the drafts directory and return all MissionDraftV1 objects."""
        if not self._drafts_dir.exists():
            return []

        results: list[MissionDraftV1] = []
        for path in self._drafts_dir.glob("*.json"):
            draft = self.load(path.stem)
            if draft is None:
                continue
            if not include_terminal and draft.status in _TERMINAL_STATUSES:
                continue
            results.append(draft)

        results.sort(key=lambda d: d.updated_at, reverse=True)
        return results

    def save(self, draft: MissionDraftV1, *, expected_revision: int) -> DraftSaveResult:
        with self._locked_store():
            current = self.load(draft.id)
            if current is None:
                return DraftSaveResult(status="conflict", draft=None)
            if current.revision != expected_revision:
                return DraftSaveResult(status="conflict", draft=current)

            updated = draft.copy_with(revision=current.revision + 1)
            sanitized = self._sanitized_draft(updated)
            self._write_draft(sanitized)
            return DraftSaveResult(status="saved", draft=sanitized)

    def prune_expired(self, *, now: str | datetime | None = None) -> list[str]:
        current_time = self._coerce_datetime(now) or _utc_now()
        pruned: list[str] = []
        if not self._drafts_dir.exists():
            return pruned

        for path in sorted(self._drafts_dir.glob("*.json")):
            draft = self.load(path.stem)
            if draft is None:
                continue
            last_activity_at = self._last_activity_at(draft, path)
            if not is_draft_expired(draft, last_activity_at=last_activity_at, now=current_time):
                continue
            path.unlink(missing_ok=True)
            pruned.append(draft.id)
        return pruned

    def _draft_path(self, draft_id: str) -> Path:
        return self._drafts_dir / f"{draft_id}.json"

    def _ensure_dir(self) -> None:
        self._drafts_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self._drafts_dir, _OWNER_DIR_MODE)

    def _write_draft(self, draft: MissionDraftV1) -> None:
        self._ensure_dir()
        path = self._draft_path(draft.id)
        payload = json.dumps(draft.to_dict(), indent=2)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self._drafts_dir,
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
        os.chmod(temp_path, _OWNER_FILE_MODE)
        os.replace(temp_path, path)
        os.chmod(path, _OWNER_FILE_MODE)

    def _lock_path(self) -> Path:
        return self._drafts_dir / ".drafts.lock"

    def _locked_store(self):
        self._ensure_dir()
        return _StoreLock(self._lock_path())

    def _sanitized_draft(self, draft: MissionDraftV1) -> MissionDraftV1:
        payload = redact_persisted_content(draft.to_dict())
        return MissionDraftV1.from_dict(payload)

    def _last_activity_at(self, draft: MissionDraftV1, path: Path) -> datetime:
        if draft.activity_log:
            last_entry = draft.activity_log[-1]
            if isinstance(last_entry, dict):
                parsed = _parse_timestamp(str(last_entry.get("timestamp") or ""))
                if parsed is not None:
                    return parsed
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)

    @staticmethod
    def _coerce_datetime(value: str | datetime | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        return _parse_timestamp(value)


def is_draft_expired(
    draft: MissionDraftV1,
    *,
    last_activity_at: str | datetime | None,
    now: str | datetime | None = None,
) -> bool:
    if draft.status not in _TERMINAL_STATUSES:
        return False
    current_time = PlanDraftStore._coerce_datetime(now) or _utc_now()
    last_activity = PlanDraftStore._coerce_datetime(last_activity_at)
    if last_activity is None:
        return False
    return last_activity <= current_time - timedelta(days=30)


class _StoreLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle = None

    def __enter__(self):
        self._handle = self._path.open("a+", encoding="utf-8")
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        os.chmod(self._path, _OWNER_FILE_MODE)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._handle is None:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None
