"""Tests for VectorMemory — lancedb-backed vector memory system."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

pytest.importorskip("lancedb", reason="lancedb not installed; install agentforce[vector]")
from agentforce.memory.vector_memory import VectorMemory


class TestGlobalLayer:
    def test_set_and_get(self, tmp_path):
        m = VectorMemory(tmp_path)
        m.global_set("lang", "python")
        assert m.global_get("lang") == "python"

    def test_get_missing_returns_none(self, tmp_path):
        m = VectorMemory(tmp_path)
        assert m.global_get("nonexistent") is None

    def test_upsert_updates_value(self, tmp_path):
        m = VectorMemory(tmp_path)
        m.global_set("lang", "python")
        m.global_set("lang", "rust")
        assert m.global_get("lang") == "rust"

    def test_dump_format(self, tmp_path):
        m = VectorMemory(tmp_path)
        m.global_set("key", "val", category="fact")
        dump = m.global_dump()
        assert "GLOBAL MEMORY" in dump
        assert "key" in dump
        assert "val" in dump

    def test_dump_empty(self, tmp_path):
        m = VectorMemory(tmp_path)
        assert m.global_dump() == ""


class TestProjectLayer:
    def test_set_and_get(self, tmp_path):
        m = VectorMemory(tmp_path)
        m.project_set("proj1", "convention", "use snake_case")
        assert m.project_get("proj1", "convention") == "use snake_case"

    def test_isolated_between_projects(self, tmp_path):
        m = VectorMemory(tmp_path)
        m.project_set("proj1", "key", "v1")
        m.project_set("proj2", "key", "v2")
        assert m.project_get("proj1", "key") == "v1"
        assert m.project_get("proj2", "key") == "v2"

    def test_upsert_updates_value(self, tmp_path):
        m = VectorMemory(tmp_path)
        m.project_set("proj1", "key", "old")
        m.project_set("proj1", "key", "new")
        assert m.project_get("proj1", "key") == "new"

    def test_dump_format(self, tmp_path):
        m = VectorMemory(tmp_path)
        m.project_set("p1", "key", "val")
        dump = m.project_dump("p1")
        assert "PROJECT MEMORY" in dump
        assert "key" in dump

    def test_clear_project(self, tmp_path):
        m = VectorMemory(tmp_path)
        m.project_set("proj1", "key", "val")
        m.clear_project("proj1")
        assert m.project_get("proj1", "key") is None

    def test_clear_project_nonexistent(self, tmp_path):
        m = VectorMemory(tmp_path)
        m.clear_project("nope")  # must not raise


class TestTaskLayer:
    def test_set_and_get(self, tmp_path):
        m = VectorMemory(tmp_path)
        m.task_set("task1", "progress", "halfway")
        assert m.task_get("task1", "progress") == "halfway"

    def test_task_clear(self, tmp_path):
        m = VectorMemory(tmp_path)
        m.task_set("task1", "progress", "halfway")
        m.task_clear("task1")
        assert m.task_get("task1", "progress") is None

    def test_task_clear_nonexistent(self, tmp_path):
        m = VectorMemory(tmp_path)
        m.task_clear("nope")  # must not raise

    def test_task_clear_only_removes_target(self, tmp_path):
        m = VectorMemory(tmp_path)
        m.task_set("task1", "k", "v1")
        m.task_set("task2", "k", "v2")
        m.task_clear("task1")
        assert m.task_get("task1", "k") is None
        assert m.task_get("task2", "k") == "v2"

    def test_upsert_updates_value(self, tmp_path):
        m = VectorMemory(tmp_path)
        m.task_set("task1", "k", "old")
        m.task_set("task1", "k", "new")
        assert m.task_get("task1", "k") == "new"

    def test_dump_format(self, tmp_path):
        m = VectorMemory(tmp_path)
        m.task_set("t1", "key", "val")
        dump = m.task_dump("t1")
        assert "TASK MEMORY" in dump
        assert "key" in dump

    def test_dump_empty(self, tmp_path):
        m = VectorMemory(tmp_path)
        assert m.task_dump("empty") == ""


class TestAgentContext:
    def test_combined_layers(self, tmp_path):
        m = VectorMemory(tmp_path)
        m.global_set("global_key", "global_val")
        m.project_set("proj1", "proj_key", "proj_val")
        m.task_set("task1", "task_key", "task_val")
        ctx = m.agent_context("proj1", "task1")
        assert "global_key" in ctx
        assert "proj_key" in ctx
        assert "task_key" in ctx

    def test_no_task(self, tmp_path):
        m = VectorMemory(tmp_path)
        m.global_set("key", "val")
        ctx = m.agent_context("proj1")
        assert "key" in ctx
        assert "TASK MEMORY" not in ctx

    def test_empty_context(self, tmp_path):
        m = VectorMemory(tmp_path)
        assert m.agent_context("proj1") == ""


class TestAgentContextSemantic:
    def test_query_returns_relevant_entries(self, tmp_path):
        """agent_context with query returns entries (semantic search path)."""
        m = VectorMemory(tmp_path)
        m.global_set("python_version", "3.11", category="config")
        m.project_set("proj1", "framework", "django", category="config")
        ctx = m.agent_context("proj1", query="python framework configuration")
        assert ctx != ""
        assert isinstance(ctx, str)

    def test_semantic_returns_fewer_than_full_dump(self, tmp_path):
        """top_k limits entries returned vs full dump."""
        m = VectorMemory(tmp_path)
        for i in range(20):
            m.global_set(f"key_{i}", f"value about topic {i}")
        full = m.agent_context("proj1")
        semantic = m.agent_context("proj1", query="value about topic", top_k=3)
        full_count = full.count("\n") + 1
        semantic_count = semantic.count("\n") + 1
        assert semantic_count < full_count

    def test_backward_compatible_no_query(self, tmp_path):
        """agent_context without query works as before."""
        m = VectorMemory(tmp_path)
        m.global_set("key", "val")
        m.project_set("proj1", "pkey", "pval")
        ctx = m.agent_context("proj1")
        assert "key" in ctx
        assert "pkey" in ctx

    def test_fallback_on_empty_query(self, tmp_path):
        """query=None triggers full dump fallback."""
        m = VectorMemory(tmp_path)
        m.global_set("key", "val")
        ctx_no_query = m.agent_context("proj1")
        ctx_none_query = m.agent_context("proj1", query=None)
        assert ctx_no_query == ctx_none_query

    def test_with_task_id_and_query(self, tmp_path):
        """Semantic search includes task layer when task_id provided."""
        m = VectorMemory(tmp_path)
        m.global_set("global_key", "global_val")
        m.project_set("proj1", "proj_key", "proj_val")
        m.task_set("task1", "task_key", "task_val")
        ctx = m.agent_context("proj1", task_id="task1", query="task project global")
        assert ctx != ""

    def test_init_exports_vector_memory(self):
        """VectorMemory is exported from agentforce.memory."""
        from agentforce.memory import VectorMemory as VM
        assert VM is VectorMemory


class TestPersistence:
    def test_survives_reinit_global(self, tmp_path):
        m1 = VectorMemory(tmp_path)
        m1.global_set("key", "val")
        m2 = VectorMemory(tmp_path)
        assert m2.global_get("key") == "val"

    def test_survives_reinit_project(self, tmp_path):
        m1 = VectorMemory(tmp_path)
        m1.project_set("proj1", "key", "val")
        m2 = VectorMemory(tmp_path)
        assert m2.project_get("proj1", "key") == "val"

    def test_survives_reinit_task(self, tmp_path):
        m1 = VectorMemory(tmp_path)
        m1.task_set("task1", "key", "val")
        m2 = VectorMemory(tmp_path)
        assert m2.task_get("task1", "key") == "val"
