"""Tests for the memory system."""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agentforce.memory import Memory


class TestGlobalMemory:
    def test_set_and_get(self, tmp_path):
        m = Memory(tmp_path)
        m.global_set("lang", "python")
        assert m.global_get("lang") == "python"

    def test_get_missing_returns_none(self, tmp_path):
        m = Memory(tmp_path)
        assert m.global_get("nonexistent") is None

    def test_update_existing(self, tmp_path):
        m = Memory(tmp_path)
        m.global_set("lang", "python")
        m.global_set("lang", "rust")
        assert m.global_get("lang") == "rust"

    def test_dump_format(self, tmp_path):
        m = Memory(tmp_path)
        m.global_set("key", "val", category="fact")
        dump = m.global_dump()
        assert "GLOBAL MEMORY" in dump
        assert "key" in dump
        assert "val" in dump

    def test_dump_empty(self, tmp_path):
        m = Memory(tmp_path)
        assert m.global_dump() == ""


class TestProjectMemory:
    def test_set_and_get(self, tmp_path):
        m = Memory(tmp_path)
        m.project_set("proj1", "convention", "use snake_case")
        assert m.project_get("proj1", "convention") == "use snake_case"

    def test_isolated_between_projects(self, tmp_path):
        m = Memory(tmp_path)
        m.project_set("proj1", "key", "v1")
        m.project_set("proj2", "key", "v2")
        assert m.project_get("proj1", "key") == "v1"
        assert m.project_get("proj2", "key") == "v2"

    def test_dump(self, tmp_path):
        m = Memory(tmp_path)
        m.project_set("p1", "key", "val")
        dump = m.project_dump("p1")
        assert "PROJECT MEMORY" in dump
        assert "key" in dump


class TestTaskMemory:
    def test_set_and_clear(self, tmp_path):
        m = Memory(tmp_path)
        m.task_set("task1", "progress", "halfway")
        assert m.task_get("task1", "progress") == "halfway"
        m.task_clear("task1")
        assert m.task_get("task1", "progress") is None

    def test_clear_nonexistent(self, tmp_path):
        m = Memory(tmp_path)
        m.task_clear("nonexistent")


class TestAgentContext:
    def test_combined_layers(self, tmp_path):
        m = Memory(tmp_path)
        m.global_set("global_key", "global_val")
        m.project_set("proj1", "proj_key", "proj_val")
        m.task_set("task1", "task_key", "task_val")

        ctx = m.agent_context("proj1", "task1")
        assert "global_key" in ctx
        assert "proj_key" in ctx
        assert "task_key" in ctx

    def test_no_project_memory(self, tmp_path):
        m = Memory(tmp_path)
        m.global_set("key", "val")
        ctx = m.agent_context("empty_project")
        assert "key" in ctx
        assert "PROJECT MEMORY" not in ctx


class TestPersistence:
    def test_survives_reinit(self, tmp_path):
        m1 = Memory(tmp_path)
        m1.global_set("key", "val")
        m2 = Memory(tmp_path)
        assert m2.global_get("key") == "val"
