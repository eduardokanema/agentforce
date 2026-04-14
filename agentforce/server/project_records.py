"""Durable metadata for project harness lifecycle actions."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import state_io


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_path(path: str | None) -> str:
    text = str(path or "").strip()
    if not text:
        return ""
    try:
        return str(Path(text).expanduser().resolve())
    except Exception:
        return text


def _unique_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for path in paths:
        normalized = _normalize_path(path)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


@dataclass(frozen=True)
class ProjectRecord:
    project_id: str
    repo_root: str
    name: str | None
    goal: str | None
    working_directories: list[str]
    archived_at: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectRecord":
        return cls(
            project_id=str(payload.get("project_id") or "").strip(),
            repo_root=_normalize_path(str(payload.get("repo_root") or "")),
            name=str(payload.get("name") or "").strip() or None,
            goal=str(payload.get("goal") or "").strip() or None,
            working_directories=_unique_paths([str(value) for value in list(payload.get("working_directories") or [])]),
            archived_at=str(payload.get("archived_at") or "").strip() or None,
            created_at=str(payload.get("created_at") or "").strip(),
            updated_at=str(payload.get("updated_at") or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProjectRecordStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (state_io.get_agentforce_home() / "projects.json")

    def _load(self) -> dict[str, ProjectRecord]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        records: dict[str, ProjectRecord] = {}
        for key, value in data.items():
            if not isinstance(value, dict):
                continue
            record = ProjectRecord.from_dict(value)
            if record.project_id:
                records[key] = record
        return records

    def _save(self, records: dict[str, ProjectRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {project_id: record.to_dict() for project_id, record in records.items()}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list_all(self) -> list[ProjectRecord]:
        return sorted(self._load().values(), key=lambda record: record.updated_at, reverse=True)

    def get(self, project_id: str) -> ProjectRecord | None:
        return self._load().get(project_id)

    def save_record(
        self,
        *,
        project_id: str,
        repo_root: str,
        name: str | None = None,
        goal: str | None = None,
        working_directories: list[str] | None = None,
        archived_at: str | None = None,
        created_at: str | None = None,
    ) -> ProjectRecord:
        records = self._load()
        existing = records.get(project_id)
        now = _utc_now()
        record = ProjectRecord(
            project_id=project_id,
            repo_root=_normalize_path(repo_root),
            name=str(name or "").strip() or (existing.name if existing is not None else None),
            goal=str(goal or "").strip() or (existing.goal if existing is not None else None),
            working_directories=_unique_paths(
                list(working_directories or [])
                or (existing.working_directories if existing is not None else [])
            ),
            archived_at=archived_at if archived_at is not None else (existing.archived_at if existing is not None else None),
            created_at=created_at or (existing.created_at if existing is not None else now),
            updated_at=now,
        )
        records[project_id] = record
        self._save(records)
        return record

    def update(
        self,
        project_id: str,
        *,
        name: str | None = None,
        goal: str | None = None,
        working_directories: list[str] | None = None,
    ) -> ProjectRecord | None:
        existing = self.get(project_id)
        if existing is None:
            return None
        records = self._load()
        current = records[project_id]
        updated = ProjectRecord(
            project_id=current.project_id,
            repo_root=current.repo_root,
            name=current.name if name is None else (str(name).strip() or None),
            goal=current.goal if goal is None else (str(goal).strip() or None),
            working_directories=current.working_directories if working_directories is None else _unique_paths(list(working_directories)),
            archived_at=current.archived_at,
            created_at=current.created_at,
            updated_at=_utc_now(),
        )
        records[project_id] = updated
        self._save(records)
        return updated

    def archive(self, project_id: str) -> ProjectRecord | None:
        existing = self.get(project_id)
        if existing is None:
            return None
        return self.save_record(
            project_id=existing.project_id,
            repo_root=existing.repo_root,
            name=existing.name,
            goal=existing.goal,
            working_directories=existing.working_directories,
            archived_at=_utc_now(),
            created_at=existing.created_at,
        )

    def unarchive(self, project_id: str) -> ProjectRecord | None:
        existing = self.get(project_id)
        if existing is None:
            return None
        return self.save_record(
            project_id=existing.project_id,
            repo_root=existing.repo_root,
            name=existing.name,
            goal=existing.goal,
            working_directories=existing.working_directories,
            archived_at="",
            created_at=existing.created_at,
        )

    def delete(self, project_id: str) -> bool:
        records = self._load()
        if project_id not in records:
            return False
        records.pop(project_id, None)
        self._save(records)
        return True
