"""BDD tests for VectorMemory semantic retrieval."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pytest_bdd import given, scenarios, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from agentforce.memory.vector_memory import VectorMemory

scenarios("vector_memory.feature")


# ── Scenario: Storing and retrieving a global memory entry ────────────────────

@given("a fresh VectorMemory instance", target_fixture="mem")
def fresh_vector_memory(tmp_path):
    return VectorMemory(tmp_path)


@when('I store a global entry with key "lang" and value "python"')
def store_global_entry(mem):
    mem.global_set("lang", "python")


@then('retrieving key "lang" returns "python"')
def retrieve_global_entry(mem):
    assert mem.global_get("lang") == "python"


# ── Scenario: Semantic search returns relevant entries ────────────────────────

_AUTH_KEYS = ["jwt_tokens", "auth_middleware", "session_security"]

_DIVERSE_ENTRIES = [
    ("jwt_tokens",       "JSON Web Tokens used for stateless authentication"),
    ("oauth_flow",       "OAuth 2.0 authorization code flow for third-party access"),
    ("cooking_pasta",    "Classic carbonara recipe uses guanciale and pecorino"),
    ("db_config",        "PostgreSQL database connection pool settings"),
    ("auth_middleware",  "Authentication middleware validates bearer tokens on each request"),
    ("cloud_storage",    "AWS S3 bucket configuration for static file hosting"),
    ("color_palette",    "Material design primary and secondary color tokens"),
    ("session_security", "Session tokens expire after 24 hours to limit exposure"),
    ("k8s_pods",         "Kubernetes pod autoscaler monitors CPU utilisation"),
    ("plant_care",       "Succulent watering schedule once per two weeks"),
]


@given("a VectorMemory loaded with 10 diverse topic entries", target_fixture="mem")
def vector_memory_diverse(tmp_path):
    m = VectorMemory(tmp_path)
    for key, value in _DIVERSE_ENTRIES:
        m.global_set(key, value)
    return m


@when('I query for "authentication security tokens"', target_fixture="search_result")
def query_auth(mem):
    return mem.agent_context("proj", query="authentication security tokens", top_k=5)


@then("the auth-related entries appear in the result")
def auth_entries_present(search_result):
    # At least one of the auth-related keys must appear in the top-k results
    matches = [key for key in _AUTH_KEYS if key in search_result]
    assert matches, (
        f"Expected at least one auth-related entry in result, got:\n{search_result}"
    )


# ── Scenario: Task memory is cleared after task completion ────────────────────

@given('a VectorMemory with entries stored under task "task_001"', target_fixture="mem")
def vector_memory_with_task(tmp_path):
    m = VectorMemory(tmp_path)
    m.task_set("task_001", "progress", "implementation complete")
    m.task_set("task_001", "notes", "all tests passing")
    return m


@when('I clear the task memory for "task_001"')
def clear_task(mem):
    mem.task_clear("task_001")


@then('no entries are returned for task "task_001"')
def task_entries_gone(mem):
    assert mem.task_get("task_001", "progress") is None
    assert mem.task_get("task_001", "notes") is None
    assert mem.task_dump("task_001") == ""


# ── Scenario: Backward-compatible agent_context without query ─────────────────

@given('a VectorMemory with global entry "deploy_env" set to "production"', target_fixture="mem")
def vector_memory_with_global(tmp_path):
    m = VectorMemory(tmp_path)
    m.global_set("deploy_env", "production")
    return m


@when("I call agent_context without a query parameter", target_fixture="ctx")
def call_agent_context_no_query(mem):
    return mem.agent_context("myproject")


@then('"deploy_env" appears in the returned context')
def deploy_env_in_context(ctx):
    assert "deploy_env" in ctx
    assert "production" in ctx
