"""Shared execution-profile catalog and normalization helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentforce.core.spec import ExecutionProfile


_FIXED_MEDIUM_THINKING = ("medium",)
_OPENCODE_THINKING = ("low", "medium", "high", "xhigh")


@dataclass(frozen=True)
class ProfileNormalizationResult:
    profile: ExecutionProfile
    valid: bool
    repaired: bool
    reason: str | None = None


def supported_thinking_for_provider(provider_id: str) -> list[str]:
    if provider_id == "opencode":
        return list(_OPENCODE_THINKING)
    return list(_FIXED_MEDIUM_THINKING)


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
            return list(provider_meta.get("cached_models") or [])
        if provider_id in {"claude", "codex", "gemini"}:
            return list(providers._get_provider_models(provider_id) or [])
        return list(provider_meta.get("cached_models") or [])
    if provider_id == "ollama":
        try:
            return list(providers._fetch_ollama_models() or [])
        except Exception:
            return []
    return list(provider_meta.get("cached_models") or [])


def _catalog_models(*, include_disabled: bool = False) -> list[dict[str, Any]]:
    provider_catalogue, metadata = _provider_sources()
    catalog_models: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    for provider_id, catalogue in provider_catalogue.items():
        provider_meta = metadata.get(provider_id, {})
        active = _provider_active(provider_id, provider_meta, catalogue)
        enabled_models = provider_meta.get("enabled_models")
        models = _provider_models(provider_id, provider_meta, catalogue)
        supported_thinking = supported_thinking_for_provider(provider_id)
        provider_name = str(catalogue.get("display_name") or provider_id)

        for model in models:
            model_id = str(model.get("id") or "").strip()
            if not model_id:
                continue
            dedupe_key = (provider_id, model_id)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            enabled = enabled_models is None or model_id in enabled_models
            selectable = active and enabled
            if not include_disabled and not selectable:
                continue
            catalog_models.append({
                "id": model_id,
                "provider_id": provider_id,
                "provider": provider_name,
                "agent": provider_id,
                "model_id": model_id,
                "name": str(model.get("name") or model_id),
                "cost_per_1k_input": float(model.get("cost_per_1k_input", 0.0) or 0.0),
                "cost_per_1k_output": float(model.get("cost_per_1k_output", 0.0) or 0.0),
                "latency_label": str(model.get("latency_label") or ""),
                "supported_thinking": list(supported_thinking),
                "active": active,
                "enabled": enabled,
                "selectable": selectable,
            })
    return catalog_models


def list_execution_profiles() -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for model in _catalog_models():
        for thinking in model["supported_thinking"]:
            profiles.append({
                "id": profile_id(model["provider_id"], model["model_id"], thinking),
                "label": f"{model['provider']} · {model['name']} · {thinking}",
                "provider_id": model["provider_id"],
                "provider": model["provider"],
                "agent": model["agent"],
                "model": model["model_id"],
                "model_id": model["model_id"],
                "name": model["name"],
                "thinking": thinking,
                "supported_thinking": list(model["supported_thinking"]),
                "cost_per_1k_input": model["cost_per_1k_input"],
                "cost_per_1k_output": model["cost_per_1k_output"],
                "latency_label": model["latency_label"],
            })
    return profiles


def list_provider_models() -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for model in _catalog_models(include_disabled=True):
        grouped.setdefault(model["provider_id"], []).append(model)
    return grouped


def profile_id(provider_id: str | None, model_id: str | None, thinking: str | None) -> str:
    return f"{(provider_id or '').strip()}:{(model_id or '').strip()}:{(thinking or '').strip()}"


def parse_profile_id(value: str | None) -> ExecutionProfile | None:
    if not isinstance(value, str):
        return None
    provider_id, sep, remainder = value.partition(":")
    if not sep:
        return None
    model_id, sep, thinking = remainder.rpartition(":")
    if not sep:
        return None
    if not provider_id or not model_id or not thinking:
        return None
    return ExecutionProfile(agent=provider_id, model=model_id, thinking=thinking)


def available_models_for_provider(provider_id: str) -> list[str]:
    return [
        str(model["model_id"])
        for model in _catalog_models()
        if model["provider_id"] == provider_id
    ]


def selectable_profiles_for_provider(provider_id: str) -> list[ExecutionProfile]:
    return [
        ExecutionProfile(agent=profile["agent"], model=profile["model"], thinking=profile["thinking"])
        for profile in list_execution_profiles()
        if profile["provider_id"] == provider_id
    ]


def normalize_execution_profile(profile: ExecutionProfile | None) -> ProfileNormalizationResult:
    if profile is None or not profile.configured():
        return ProfileNormalizationResult(profile=ExecutionProfile(), valid=False, repaired=False, reason="missing_profile")

    desired_agent = str(profile.agent or "").strip()
    desired_model = str(profile.model or "").strip()
    desired_thinking = str(profile.thinking or "").strip() or "medium"

    provider_profiles = [
        candidate
        for candidate in selectable_profiles_for_provider(desired_agent)
        if candidate.model
    ]

    for candidate in provider_profiles:
        if candidate.model == desired_model and candidate.thinking == desired_thinking:
            return ProfileNormalizationResult(profile=candidate, valid=True, repaired=False)

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

    if provider_profiles:
        replacement = provider_profiles[0]
        return ProfileNormalizationResult(
            profile=replacement,
            valid=True,
            repaired=True,
            reason="replaced_with_same_provider_profile",
        )

    return ProfileNormalizationResult(
        profile=ExecutionProfile(agent=desired_agent, model=desired_model, thinking=desired_thinking),
        valid=False,
        repaired=False,
        reason="no_same_provider_replacement",
    )


def normalize_profile_dict(payload: dict[str, Any] | None) -> ProfileNormalizationResult:
    return normalize_execution_profile(ExecutionProfile.from_dict(payload))
