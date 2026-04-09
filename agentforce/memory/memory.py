"""Minimalist memory system — global + per-project + ephemeral task memory.

Uses disk-backed KV store with semantic indexing for retrieval.
Designed to be swapped for more sophisticated backends (vector DBs) later.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class MemoryEntry:
    """A single memory entry."""
    key: str
    value: str
    category: str = "general"     # general, convention, lesson, fact
    source: str = ""              # mission_id, task_id, "global"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "category": self.category,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> MemoryEntry:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class Memory:
    """Hierarchical memory: global → project → task (ephemeral).
    
    Storage is flat JSON files — simple, portable, no dependencies.
    Designed to be swapped for lancedb/tinydb/etc later.
    """

    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)
        # Layer directories
        self._global_dir = self.base / "global"
        self._global_dir.mkdir(exist_ok=True)

    # ── Layer helpers ──

    def _layer_dir(self, layer: str) -> Path:
        """Get directory for a memory layer."""
        d = self.base / layer
        d.mkdir(exist_ok=True)
        return d

    def _global_file(self) -> Path:
        return self._global_dir / "memory.json"

    def _project_file(self, project_id: str) -> Path:
        return self._layer_dir("projects") / f"{project_id}.json"

    def _task_file(self, task_id: str) -> Path:
        return self._layer_dir("tasks") / f"{task_id}.json"

    # ── Read helpers ──

    def _read_file(self, path: Path) -> list[MemoryEntry]:
        if not path.exists():
            return []
        with open(path) as f:
            data = json.load(f)
        return [MemoryEntry.from_dict(e) for e in data]

    def _write_file(self, path: Path, entries: list[MemoryEntry]):
        with open(path, "w") as f:
            json.dump([e.to_dict() for e in entries], f, indent=2)

    # ── Global memory ──

    def global_get(self, key: str) -> str | None:
        for e in self._read_file(self._global_file()):
            if e.key == key:
                return e.value
        return None

    def global_set(self, key: str, value: str, category: str = "general"):
        entries = self._read_file(self._global_file())
        for e in entries:
            if e.key == key:
                e.value = value
                e.updated_at = datetime.now(timezone.utc).isoformat()
                break
        else:
            entries.append(MemoryEntry(key=key, value=value, category=category, source="global"))
        self._write_file(self._global_file(), entries)

    def global_dump(self) -> str:
        """Dump all global memory as a formatted string for context injection."""
        entries = self._read_file(self._global_file())
        if not entries:
            return ""
        return "GLOBAL MEMORY:\n" + "\n".join(f"  [{e.category}] {e.key}: {e.value}" for e in entries)

    # ── Project memory ──

    def project_get(self, project_id: str, key: str) -> str | None:
        for e in self._read_file(self._project_file(project_id)):
            if e.key == key:
                return e.value
        return None

    def project_set(self, project_id: str, key: str, value: str, category: str = "general"):
        pfile = self._project_file(project_id)
        entries = self._read_file(pfile)
        for e in entries:
            if e.key == key:
                e.value = value
                e.updated_at = datetime.now(timezone.utc).isoformat()
                break
        else:
            entries.append(MemoryEntry(key=key, value=value, category=category, source=project_id))
        self._write_file(pfile, entries)

    def project_dump(self, project_id: str) -> str:
        entries = self._read_file(self._project_file(project_id))
        if not entries:
            return ""
        return f"PROJECT MEMORY ({project_id}):\n" + "\n".join(
            f"  [{e.category}] {e.key}: {e.value}" for e in entries
        )

    # ── Ephemeral task memory (auto-cleaned on task completion) ──

    def task_get(self, task_id: str, key: str) -> str | None:
        for e in self._read_file(self._task_file(task_id)):
            if e.key == key:
                return e.value
        return None

    def task_set(self, task_id: str, key: str, value: str, category: str = "general"):
        tfile = self._task_file(task_id)
        entries = self._read_file(tfile)
        for e in entries:
            if e.key == key:
                e.value = value
                e.updated_at = datetime.now(timezone.utc).isoformat()
                break
        else:
            entries.append(MemoryEntry(key=key, value=value, category=category, source=task_id))
        self._write_file(tfile, entries)

    def task_clear(self, task_id: str):
        """Remove ephemeral task memory when task is complete."""
        tfile = self._task_file(task_id)
        if tfile.exists():
            tfile.unlink()

    def task_dump(self, task_id: str) -> str:
        entries = self._read_file(self._task_file(task_id))
        if not entries:
            return ""
        return f"TASK MEMORY ({task_id}):\n" + "\n".join(
            f"  [{e.category}] {e.key}: {e.value}" for e in entries
        )

    # ── Combined context for agents ──

    def agent_context(self, project_id: str, task_id: str | None = None, query: str | None = None) -> str:
        """Combine all memory layers into a single context string for agent injection."""
        parts = []

        global_mem = self.global_dump()
        if global_mem:
            parts.append(global_mem)

        proj_mem = self.project_dump(project_id)
        if proj_mem:
            parts.append(proj_mem)

        if task_id:
            task_mem = self.task_dump(task_id)
            if task_mem:
                parts.append(task_mem)

        return "\n\n".join(parts) if parts else ""

    # ── Bulk operations ──

    def clear_project(self, project_id: str):
        """Remove all project memory."""
        f = self._project_file(project_id)
        if f.exists():
            f.unlink()
