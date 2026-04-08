"""Vector-backed memory system using lancedb + fastembed.

Drop-in replacement for Memory with semantic search capability.
Uses a single 'memories' table with a layer column for namespace isolation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import lancedb
import pyarrow as pa

if TYPE_CHECKING:
    from fastembed import TextEmbedding

_SCHEMA = pa.schema([
    pa.field("key", pa.string()),
    pa.field("value", pa.string()),
    pa.field("category", pa.string()),
    pa.field("source", pa.string()),
    pa.field("layer", pa.string()),
    pa.field("created_at", pa.string()),
    pa.field("updated_at", pa.string()),
    pa.field("vector", pa.list_(pa.float32(), 384)),
])

_EMBED_MODEL = "BAAI/bge-small-en-v1.5"


class VectorMemory:
    """Hierarchical memory backed by lancedb.

    Layers:
        global          — shared across all projects
        project:<id>    — per-project
        task:<id>       — ephemeral per-task
    """

    def __init__(self, base_dir: str | Path):
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(self._base / "lancedb")
        self._tbl = self._open_table()
        self._embedder: TextEmbedding | None = None

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _open_table(self):
        if "memories" in self._db.list_tables().tables:
            return self._db.open_table("memories")
        return self._db.create_table("memories", schema=_SCHEMA)

    def _embed(self, text: str) -> list[float]:
        if self._embedder is None:
            from fastembed import TextEmbedding
            self._embedder = TextEmbedding(model_name=_EMBED_MODEL)
        return list(next(iter(self._embedder.embed([text])))[: 384].tolist())

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _query_one(self, layer: str, key: str) -> dict | None:
        try:
            rows = (
                self._tbl.search()
                .where(f"layer = '{layer}' AND key = '{key}'", prefilter=True)
                .limit(1)
                .to_list()
            )
        except Exception:
            return None
        return rows[0] if rows else None

    def _query_layer(self, layer: str) -> list[dict]:
        try:
            return (
                self._tbl.search()
                .where(f"layer = '{layer}'", prefilter=True)
                .limit(10_000)
                .to_list()
            )
        except Exception:
            return []

    def _upsert(self, layer: str, key: str, value: str, category: str, source: str):
        now = self._now()
        existing = self._query_one(layer, key)
        vector = self._embed(value)

        if existing:
            self._tbl.delete(f"layer = '{layer}' AND key = '{key}'")
            created_at = existing.get("created_at", now)
        else:
            created_at = now

        self._tbl.add([{
            "key": key,
            "value": value,
            "category": category,
            "source": source,
            "layer": layer,
            "created_at": created_at,
            "updated_at": now,
            "vector": vector,
        }])

    def _delete_layer(self, layer: str):
        try:
            self._tbl.delete(f"layer = '{layer}'")
        except Exception:
            pass

    def _format_entries(self, rows: list[dict], header: str) -> str:
        if not rows:
            return ""
        lines = "\n".join(
            f"  [{r['category']}] {r['key']}: {r['value']}" for r in rows
        )
        return f"{header}:\n{lines}"

    # ── Global memory ─────────────────────────────────────────────────────────

    def global_set(self, key: str, value: str, category: str = "general"):
        self._upsert("global", key, value, category, "global")

    def global_get(self, key: str) -> str | None:
        row = self._query_one("global", key)
        return row["value"] if row else None

    def global_dump(self) -> str:
        return self._format_entries(self._query_layer("global"), "GLOBAL MEMORY")

    # ── Project memory ────────────────────────────────────────────────────────

    def project_set(self, project_id: str, key: str, value: str, category: str = "general"):
        self._upsert(f"project:{project_id}", key, value, category, project_id)

    def project_get(self, project_id: str, key: str) -> str | None:
        row = self._query_one(f"project:{project_id}", key)
        return row["value"] if row else None

    def project_dump(self, project_id: str) -> str:
        return self._format_entries(
            self._query_layer(f"project:{project_id}"),
            f"PROJECT MEMORY ({project_id})",
        )

    def clear_project(self, project_id: str):
        self._delete_layer(f"project:{project_id}")

    # ── Task memory ───────────────────────────────────────────────────────────

    def task_set(self, task_id: str, key: str, value: str, category: str = "general"):
        self._upsert(f"task:{task_id}", key, value, category, task_id)

    def task_get(self, task_id: str, key: str) -> str | None:
        row = self._query_one(f"task:{task_id}", key)
        return row["value"] if row else None

    def task_dump(self, task_id: str) -> str:
        return self._format_entries(
            self._query_layer(f"task:{task_id}"),
            f"TASK MEMORY ({task_id})",
        )

    def task_clear(self, task_id: str):
        self._delete_layer(f"task:{task_id}")

    # ── Combined agent context ────────────────────────────────────────────────

    def agent_context(
        self,
        project_id: str,
        task_id: str | None = None,
        query: str | None = None,
        top_k: int = 8,
    ) -> str:
        if query is None:
            return self._agent_context_full(project_id, task_id)
        try:
            return self._agent_context_semantic(project_id, task_id, query, top_k)
        except Exception:
            return self._agent_context_full(project_id, task_id)

    def _agent_context_full(self, project_id: str, task_id: str | None) -> str:
        parts = []
        g = self.global_dump()
        if g:
            parts.append(g)
        p = self.project_dump(project_id)
        if p:
            parts.append(p)
        if task_id:
            t = self.task_dump(task_id)
            if t:
                parts.append(t)
        return "\n\n".join(parts) if parts else ""

    def _agent_context_semantic(
        self, project_id: str, task_id: str | None, query: str, top_k: int
    ) -> str:
        vector = self._embed(query)
        layers = ["global", f"project:{project_id}"]
        if task_id:
            layers.append(f"task:{task_id}")

        layer_filter = " OR ".join(f"layer = '{l}'" for l in layers)
        rows = (
            self._tbl.search(vector)
            .where(layer_filter, prefilter=True)
            .limit(top_k)
            .to_list()
        )
        if not rows:
            return ""

        # Group by layer for section headers
        layer_order = {l: i for i, l in enumerate(layers)}
        rows.sort(key=lambda r: layer_order.get(r["layer"], 99))

        headers = {
            "global": "GLOBAL MEMORY",
            f"project:{project_id}": f"PROJECT MEMORY ({project_id})",
        }
        if task_id:
            headers[f"task:{task_id}"] = f"TASK MEMORY ({task_id})"

        by_layer: dict[str, list[dict]] = {}
        for row in rows:
            by_layer.setdefault(row["layer"], []).append(row)

        parts = []
        for layer in layers:
            if layer in by_layer:
                parts.append(self._format_entries(by_layer[layer], headers[layer]))
        return "\n\n".join(p for p in parts if p)
