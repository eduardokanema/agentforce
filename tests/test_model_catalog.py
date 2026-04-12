from __future__ import annotations

from agentforce.core.spec import ExecutionProfile
from agentforce.server import model_catalog


def test_list_execution_profiles_returns_combined_selectable_profiles(monkeypatch):
    monkeypatch.setattr(
        model_catalog,
        "_catalog_models",
        lambda include_disabled=False: [
            {
                "provider_id": "codex",
                "provider": "Codex CLI",
                "agent": "codex",
                "model_id": "gpt-5.4",
                "name": "GPT-5.4",
                "cost_per_1k_input": 0.0,
                "cost_per_1k_output": 0.0,
                "latency_label": "Standard",
                "supported_thinking": ["medium"],
                "selectable": True,
            },
            {
                "provider_id": "opencode",
                "provider": "OpenCode",
                "agent": "opencode",
                "model_id": "anthropic/claude-sonnet-4-6",
                "name": "Claude Sonnet 4.6",
                "cost_per_1k_input": 0.0,
                "cost_per_1k_output": 0.0,
                "latency_label": "Cloud",
                "supported_thinking": ["low", "medium", "high", "xhigh"],
                "selectable": True,
            },
            {
                "provider_id": "claude",
                "provider": "Claude Code",
                "agent": "claude",
                "model_id": "claude-sonnet-4-6",
                "name": "Claude Sonnet 4.6",
                "cost_per_1k_input": 0.0,
                "cost_per_1k_output": 0.0,
                "latency_label": "Standard",
                "supported_thinking": ["medium"],
                "selectable": False,
            },
        ],
    )

    profiles = model_catalog.list_execution_profiles()

    assert [profile["id"] for profile in profiles] == [
        "codex:gpt-5.4:medium",
        "opencode:anthropic/claude-sonnet-4-6:low",
        "opencode:anthropic/claude-sonnet-4-6:medium",
        "opencode:anthropic/claude-sonnet-4-6:high",
        "opencode:anthropic/claude-sonnet-4-6:xhigh",
    ]
    assert profiles[0]["model_id"] == "gpt-5.4"
    assert profiles[0]["thinking"] == "medium"
    assert profiles[0]["label"] == "Codex CLI · GPT-5.4 · medium"


def test_normalize_execution_profile_repairs_same_provider_only(monkeypatch):
    monkeypatch.setattr(
        model_catalog,
        "_catalog_models",
        lambda include_disabled=False: [
            {
                "provider_id": "codex",
                "provider": "Codex CLI",
                "agent": "codex",
                "model_id": "gpt-5.4-mini",
                "name": "GPT-5.4 Mini",
                "cost_per_1k_input": 0.0,
                "cost_per_1k_output": 0.0,
                "latency_label": "Fast",
                "supported_thinking": ["medium"],
                "selectable": True,
            },
            {
                "provider_id": "claude",
                "provider": "Claude Code",
                "agent": "claude",
                "model_id": "claude-sonnet-4-6",
                "name": "Claude Sonnet 4.6",
                "cost_per_1k_input": 0.0,
                "cost_per_1k_output": 0.0,
                "latency_label": "Standard",
                "supported_thinking": ["medium"],
                "selectable": True,
            },
        ],
    )

    repaired = model_catalog.normalize_execution_profile(
        ExecutionProfile(agent="codex", model="gpt-5.4", thinking="high"),
    )

    assert repaired.profile == ExecutionProfile(agent="codex", model="gpt-5.4-mini", thinking="medium")
    assert repaired.repaired is True
    assert repaired.valid is True
    assert repaired.reason == "replaced_with_same_provider_profile"

    invalid = model_catalog.normalize_execution_profile(
        ExecutionProfile(agent="gemini", model="gemini-2.5-pro", thinking="medium"),
    )

    assert invalid.profile == ExecutionProfile(agent="gemini", model="gemini-2.5-pro", thinking="medium")
    assert invalid.repaired is False
    assert invalid.valid is False
    assert invalid.reason == "no_same_provider_replacement"
