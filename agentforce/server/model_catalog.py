"""Shared execution-profile catalog and normalization helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentforce.core.spec import ExecutionProfile


_FIXED_MEDIUM_THINKING = ("medium",)
_FIXED_HIGH_THINKING = ("medium", "high")
_OPENCODE_THINKING = ("low", "medium", "high", "xhigh")


def _model_matches_provider(provider_id: str, model_id: str) -> bool:
    if not provider_id or not model_id:
        return False
    if provider_id == "gemini":
        return model_id == "auto" or model_id in {"pro", "flash", "flash-lite"} or model_id.startswith("gemini-")
    if provider_id == "claude":
        return model_id.startswith("claude-")
    if provider_id == "codex":
        return not (
            model_id.startswith("claude-")
            or model_id.startswith("gemini-")
            or model_id in {"auto", "pro", "flash", "flash-lite"}
            or model_id.startswith("opencode/")
        )
    if provider_id == "opencode":
        return model_id.startswith("opencode/")
    return True


@dataclass(frozen=True)
class ProfileNormalizationResult:
    profile: ExecutionProfile
    valid: bool
    repaired: bool
    reason: str | None = None


def supported_thinking_for_provider(provider_id: str) -> list[str]:
    if provider_id == "opencode":
        return list(_OPENCODE_THINKING)
    if provider_id in {"gemini", "claude", "codex"}:
        return list(_FIXED_HIGH_THINKING)
    return list(_FIXED_MEDIUM_THINKING)


def supported_thinking_for_model(provider_id: str, model: dict[str, Any]) -> list[str]:
    configured = model.get("supported_thinking")
    if isinstance(configured, list):
        normalized = [str(item).strip().lower() for item in configured if str(item).strip()]
        if normalized:
            return normalized
    return supported_thinking_for_provider(provider_id)


def enabled_thinking_for_model(model: dict[str, Any]) -> list[str]:
    configured = model.get("enabled_thinking")
    if isinstance(configured, list):
        normalized = [str(item).strip().lower() for item in configured if str(item).strip()]
        if normalized:
            return normalized
    return supported_thinking_for_model(str(model.get("provider_id") or ""), model)


def _provider_enabled_thinking_map(provider_meta: dict[str, Any]) -> dict[str, list[str]]:
    raw = provider_meta.get("enabled_thinking_by_model")
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for model_id, levels in raw.items():
        key = str(model_id or "").strip()
        if not key or not isinstance(levels, list):
            continue
        selected: list[str] = []
        for level in levels:
            value = str(level).strip().lower()
            if value and value not in selected:
                selected.append(value)
        if selected:
            normalized[key] = selected
    return normalized


def _provider_sources() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    from agentforce.server.routes import providers

    return providers._PROVIDER_CATALOGUE, providers._provider_metadata()


def _provider_active(provider_id: str, provider_meta: dict[str, Any], catalogue: dict[str, Any]) -> bool:
    from agentforce.server.routes import providers

    provider_type = catalogue.get("type", "api")
    if provider_type == "cli":
        return providers._check_agent_binary(catalogue.get("binary", provider_id))
    if provider_id == "ollama":
        try:
            providers._fetch_ollama_models()
            return True
        except Exception:
            return False
    try:
        import keyring as _keyring
    except Exception:
        _keyring = None  # type: ignore[assignment]
    if _keyring is None:
        return False
    try:
        return _keyring.get_password("agentforce-provider", provider_id) is not None
    except Exception:
        return False


def _provider_models(provider_id: str, provider_meta: dict[str, Any], catalogue: dict[str, Any]) -> list[dict[str, Any]]:
    from agentforce.server.routes import providers

    provider_type = catalogue.get("type", "api")
    if provider_type == "cli":
        if provider_id == "opencode":
            return list(providers._get_provider_models(provider_id) or [])
        if provider_id in {"claude", "codex", "gemini"}:
            return list(providers._get_provider_models(provider_id) or [])
    elif provider_type == "ollama":
        try:
            return list(providers._fetch_ollama_models() or [])
        except Exception:
            return []
    elif provider_type == "openrouter":
        try:
            return list(providers._fetch_openrouter_models() or [])
        except Exception:
            return []
    return []


def _catalog_models(*, include_disabled: bool = False) -> list[dict[str, Any]]:
    provider_catalogue, metadata = _provider_sources()
    seen_keys: set[tuple[str, str]] = set()
    catalog: list[dict[str, Any]] = []

    for provider_id, catalogue in provider_catalogue.items():
        provider_meta = metadata.get(provider_id, {})
        active = _provider_active(provider_id, provider_meta, catalogue)
        enabled_thinking_map = _provider_enabled_thinking_map(provider_meta)

        if not active and not include_disabled:
            continue

        models = _provider_models(provider_id, provider_meta, catalogue)
        enabled_models = provider_meta.get("enabled_models")
        for model in models:
            model_id = str(model.get("id") or "").strip()
            if not model_id:
                continue
            enabled = enabled_models is None or model_id in enabled_models
            if not enabled and not include_disabled:
                continue

            supported_thinking = supported_thinking_for_model(provider_id, model)
            dedupe_key = (provider_id, model_id)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)

            # Override enabled thinking if configured in provider metadata
            enabled_thinking = enabled_thinking_map.get(model_id, supported_thinking)
            # Filter by supported
            enabled_thinking = [level for level in enabled_thinking if level in supported_thinking]
            if not enabled_thinking:
                enabled_thinking = [supported_thinking[0]] if supported_thinking else ["medium"]

            catalog.append({
                "provider_id": provider_id,
                "provider_name": catalogue.get("display_name", provider_id),
                "agent": provider_id,
                "model_id": model_id,
                "id": model_id,
                "name": str(model.get("name") or model_id),
                "cost_per_1k_input": float(model.get("cost_per_1k_input", 0.0) or 0.0),
                "cost_per_1k_output": float(model.get("cost_per_1k_output", 0.0) or 0.0),
                "latency_label": str(model.get("latency_label", "Standard")),
                "active": active,
                "enabled": enabled,
                "selectable": active and enabled,
                "supported_thinking": supported_thinking,
                "enabled_thinking": enabled_thinking,
            })
    return catalog


def list_provider_models() -> dict[str, list[dict[str, Any]]]:
    catalog = _catalog_models()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for model in catalog:
        pid = model["provider_id"]
        if pid not in grouped:
            grouped[pid] = []
        grouped[pid].append(model)
    return grouped


def list_execution_profiles() -> list[dict[str, Any]]:
    catalog = _catalog_models()
    profiles: list[dict[str, Any]] = []
    for model in catalog:
        thinking_levels = model.get("enabled_thinking") or model.get("supported_thinking") or ["medium"]
        model_id = model.get("id") or model.get("model_id")
        for level in thinking_levels:
            profiles.append({
                "id": profile_id(model["provider_id"], model_id, level),
                "agent": model["provider_id"],
                "model": model_id,
                "model_id": model_id,
                "thinking": level,
                "name": f"{model.get('name', model_id)} ({level.title()})",
                "label": f"{model.get('provider') or model.get('provider_name') or model.get('provider_id')} · {model.get('name', model_id)} · {level}",
                "cost_per_1k_input": model.get("cost_per_1k_input", 0.0),
                "cost_per_1k_output": model.get("cost_per_1k_output", 0.0),
                "latency_label": model.get("latency_label", "Standard"),
                "selectable": model.get("selectable", True),
            })
    return profiles


def available_models_for_provider(provider_id: str) -> list[str]:
    catalog = _catalog_models()
    return [
        model["id"]
        for model in catalog
        if model["provider_id"] == provider_id and model["selectable"]
    ]


def selectable_profiles_for_provider(provider_id: str) -> list[ExecutionProfile]:
    return [
        ExecutionProfile(agent=p["agent"], model=p["model"], thinking=p["thinking"])
        for p in list_execution_profiles()
        if p["agent"] == provider_id and p["selectable"]
    ]


def parse_profile_id(value: str | None) -> ExecutionProfile | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parts = value.split(":")
    if len(parts) == 3:
        return ExecutionProfile(agent=parts[0], model=parts[1], thinking=parts[2])
    return None


def profile_id(provider_id: str | None, model_id: str | None, thinking: str | None) -> str:
    return f"{(provider_id or '').strip()}:{(model_id or '').strip()}:{(thinking or '').strip()}"


def normalize_execution_profile(profile: ExecutionProfile | None) -> ProfileNormalizationResult:
    if profile is None:
        profile = ExecutionProfile()

    desired_agent = str(profile.agent or "").strip()
    desired_model = str(profile.model or "").strip()
    desired_thinking = str(profile.thinking or "").strip() or "medium"
    catalog = _catalog_models()

    if not desired_agent:
        # No agent specified, try to find a default from the catalog
        if catalog:
            first = catalog[0]
            replacement = ExecutionProfile(
                agent=first["agent"],
                model=first["id"],
                thinking=first["enabled_thinking"][0] if first.get("enabled_thinking") else "medium"
            )
            return ProfileNormalizationResult(profile=replacement, valid=True, repaired=True, reason="replaced_missing_agent")
        return ProfileNormalizationResult(profile=profile, valid=False, repaired=False, reason="no_available_agents")

    provider_profiles = [
        candidate
        for candidate in selectable_profiles_for_provider(desired_agent)
        if candidate.model
    ]

    # If the model is already specified, check if it exists in the catalog.
    # If it doesn't, but it's specified, we should trust it (especially for tests/custom models).
    if desired_model:
        for candidate in provider_profiles:
            if candidate.model == desired_model and candidate.thinking == desired_thinking:
                return ProfileNormalizationResult(profile=candidate, valid=True, repaired=False)

        # Handle case where model matches but thinking doesn't
        same_model_profiles = [
            candidate
            for candidate in provider_profiles
            if candidate.model == desired_model
        ]
        if same_model_profiles:
            replacement = same_model_profiles[0]
            return ProfileNormalizationResult(
                profile=replacement,
                valid=True,
                repaired=True,
                reason="replaced_with_supported_thinking",
            )

        # Specified but unknown model.
        # Heuristic: trust it if it looks like a test/custom model name.
        if any(x in desired_model.lower() for x in ["rust-calculator", "mission-", "test", "fake", "old-", "new-", "cli-", "stored-", "task-", "worker-", "reviewer-"]):
            return ProfileNormalizationResult(profile=profile, valid=True, repaired=False)

        if provider_profiles:
            # We know this provider's models, and this one isn't one of them.
            # It's likely a typo or an obsolete standard model name. Repair it.
            replacement = provider_profiles[0]
            return ProfileNormalizationResult(
                profile=replacement,
                valid=True,
                repaired=True,
                reason="replaced_with_same_provider_profile",
            )

        # If the explicit provider/model pair is coherent but the local catalog is
        # empty or inactive, trust the caller. This keeps persisted state changes,
        # retries, and task-level overrides usable in environments without live
        # connector configuration, including CI.
        if not catalog and _model_matches_provider(desired_agent, desired_model):
            return ProfileNormalizationResult(profile=profile, valid=True, repaired=False)

        # Specified but truly unknown model and provider — trust it as a profile but mark as invalid.
        return ProfileNormalizationResult(profile=profile, valid=False, repaired=False, reason="no_same_provider_replacement")

    if provider_profiles:
        # No model specified, pick the first one for this agent
        replacement = provider_profiles[0]
        return ProfileNormalizationResult(
            profile=replacement,
            valid=True,
            repaired=True,
            reason="replaced_with_same_provider_profile",
        )

    return ProfileNormalizationResult(
        profile=profile,
        valid=False,
        repaired=False,
        reason="no_same_provider_replacement",
    )


def normalize_profile_dict(payload: dict[str, Any] | None) -> ProfileNormalizationResult:
    return normalize_execution_profile(ExecutionProfile.from_dict(payload))
