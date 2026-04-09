"""Provider, connector, agent, telemetry, and model API routes."""
from __future__ import annotations

import json as _jsonlib
import os
import ssl
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import request as urllib_request

from .. import state_io
from ...utils import fmt_duration


_KNOWN_CONNECTORS = {
    "github": "GitHub",
    "slack": "Slack",
    "linear": "Linear",
    "sentry": "Sentry",
    "notion": "Notion",
    "anthropic": "Anthropic",
}

_PROVIDER_CATALOGUE: dict[str, dict[str, Any]] = {
    "openrouter": {
        "display_name": "OpenRouter",
        "description": "Access hundreds of AI models (Claude, GPT-4, Gemini, Llama…) via a single API key with live pricing.",
        "type": "api",
        "requires_key": True,
        "models": [],
    },
    "ollama": {
        "display_name": "Ollama",
        "description": "Run AI models locally on your machine. Install models with `ollama pull`.",
        "type": "api",
        "requires_key": False,
        "models": [],
    },
    "opencode": {
        "display_name": "OpenCode",
        "description": "Open-source AI coding agent. Shares models from your configured OpenRouter key.",
        "type": "cli",
        "binary": "opencode",
        "requires_key": False,
        "models": [],
    },
    "claude": {
        "display_name": "Claude Code",
        "description": "Anthropic's official coding CLI. Authenticated separately via the `claude` binary.",
        "type": "cli",
        "binary": "claude",
        "requires_key": False,
        "models": [],
    },
    "codex": {
        "display_name": "Codex CLI",
        "description": "OpenAI's coding assistant CLI. Authenticated separately via the `codex` binary.",
        "type": "cli",
        "binary": "codex",
        "requires_key": False,
        "models": [],
    },
}

_CLAUDE_CODE_MODELS: list[dict[str, Any]] = [
    {"id": "claude-opus-4-5", "name": "Claude Opus 4.5", "latency_label": "Powerful"},
    {"id": "claude-sonnet-4-5", "name": "Claude Sonnet 4.5", "latency_label": "Standard"},
    {"id": "claude-haiku-4-5", "name": "Claude Haiku 4.5", "latency_label": "Fast"},
]

_CODEX_MODELS_STATIC_FALLBACK: list[dict[str, Any]] = [
    {"id": "gpt-5.4", "name": "GPT-5.4", "latency_label": "Standard"},
    {"id": "gpt-5.4-mini", "name": "GPT-5.4-Mini", "latency_label": "Fast"},
    {"id": "gpt-5.3-codex", "name": "GPT-5.3-Codex", "latency_label": "Standard"},
    {"id": "gpt-5.2", "name": "GPT-5.2", "latency_label": "Standard"},
]
_PROVIDERS_FETCH_LOCK = threading.Lock()
_PROVIDER_MODELS_CACHE_TTL = timedelta(hours=24)


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _load_config() -> dict:
    config_path = state_io.get_agentforce_home() / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml

        with open(config_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _get_allowed_base_paths() -> list[str]:
    config = _load_config()
    fs = config.get("filesystem", {})
    paths = fs.get("allowed_base_paths", [])
    return [str(Path(p).expanduser().resolve()) for p in paths if p]


def _parse_query(raw_path: str) -> dict[str, str]:
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(raw_path)
    qs = parse_qs(parsed.query)
    return {k: v[0] for k, v in qs.items() if v}


def _check_agent_binary(binary: str) -> bool:
    import shutil

    return shutil.which(binary) is not None


def _fetch_openrouter_models(api_key: str) -> list[dict]:
    req = urllib_request.Request(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {api_key}", "HTTP-Referer": "https://agentforce.local"},
    )
    with urllib_request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
        data = _jsonlib.loads(resp.read().decode("utf-8"))
    models = []
    for m in data.get("data", []):
        pricing = m.get("pricing", {})
        prompt_price = float(pricing.get("prompt", 0) or 0)
        completion_price = float(pricing.get("completion", 0) or 0)
        models.append({
            "id": m["id"],
            "name": m.get("name", m["id"]),
            "cost_per_1k_input": round(prompt_price * 1000, 8),
            "cost_per_1k_output": round(completion_price * 1000, 8),
            "latency_label": "Cloud",
            "context_length": m.get("context_length"),
        })
    return sorted(models, key=lambda x: x["name"].lower())


def _fetch_ollama_models() -> list[dict]:
    with urllib_request.urlopen(
        urllib_request.Request("http://localhost:11434/api/tags"),
        timeout=3,
    ) as resp:
        data = _jsonlib.loads(resp.read().decode("utf-8"))
    return [
        {
            "id": m.get("name", ""),
            "name": m.get("name", ""),
            "cost_per_1k_input": 0.0,
            "cost_per_1k_output": 0.0,
            "latency_label": "Local",
        }
        for m in data.get("models", [])
        if m.get("name")
    ]


def _fetch_claude_code_models() -> list[dict]:
    return [{"cost_per_1k_input": 0.0, "cost_per_1k_output": 0.0, **m} for m in _CLAUDE_CODE_MODELS]


def _fetch_codex_models() -> list[dict]:
    cache_path = Path.home() / ".codex" / "models_cache.json"
    if cache_path.exists():
        try:
            with open(cache_path, encoding="utf-8") as fh:
                payload = _jsonlib.load(fh)
            models = payload if isinstance(payload, list) else payload.get("models", [])
            if isinstance(models, list) and models:
                return [
                    {
                        "id": m.get("id", ""),
                        "name": m.get("name", m.get("id", "")),
                        "cost_per_1k_input": float(m.get("cost_per_1k_input", 0.0) or 0.0),
                        "cost_per_1k_output": float(m.get("cost_per_1k_output", 0.0) or 0.0),
                        "latency_label": m.get("latency_label", "Standard"),
                    }
                    for m in models
                    if m.get("id")
                ]
        except Exception:
            pass
    return [{"cost_per_1k_input": 0.0, "cost_per_1k_output": 0.0, **m} for m in _CODEX_MODELS_STATIC_FALLBACK]


def _provider_metadata() -> dict[str, dict]:
    return state_io._load_providers_metadata()


def _provider_models_cache_stale(meta: dict[str, Any]) -> bool:
    cached_models = meta.get("cached_models")
    if not cached_models:
        return True
    cached_at = _parse_iso_datetime(meta.get("models_cached_at"))
    if cached_at is None:
        return False
    return datetime.now(timezone.utc) - cached_at >= _PROVIDER_MODELS_CACHE_TTL


def _get_provider_models(provider_name: str) -> list[dict]:
    fetchers = {
        "claude": _fetch_claude_code_models,
        "codex": _fetch_codex_models,
    }
    fetcher = fetchers.get(provider_name)
    metadata = _provider_metadata()
    meta = metadata.get(provider_name, {})

    if fetcher is None:
        return meta.get("cached_models", [])

    if not _provider_models_cache_stale(meta):
        return meta.get("cached_models", [])

    with _PROVIDERS_FETCH_LOCK:
        metadata = _provider_metadata()
        meta = metadata.get(provider_name, {})
        if not _provider_models_cache_stale(meta):
            return meta.get("cached_models", [])
        models = fetcher()
        if models:
            meta["cached_models"] = models
            meta["models_cached_at"] = _now_iso()
            metadata[provider_name] = meta
            state_io._save_providers_metadata(metadata)
        return models


def _models_list() -> list[dict]:
    try:
        import keyring as _keyring
    except Exception:
        _keyring = None  # type: ignore[assignment]

    metadata = _provider_metadata()
    models: list[dict] = []
    seen: set[str] = set()

    for provider_id, catalogue in _PROVIDER_CATALOGUE.items():
        meta = metadata.get(provider_id, {})
        enabled = meta.get("enabled_models")
        provider_type = catalogue.get("type", "api")

        if provider_type == "cli":
            if not _check_agent_binary(catalogue.get("binary", provider_id)):
                continue
            if provider_id == "opencode":
                source: list[dict] = metadata.get("openrouter", {}).get("cached_models", [])
            elif provider_id in {"claude", "codex"}:
                source = _get_provider_models(provider_id)
            elif "cached_models" in meta:
                source = meta["cached_models"]
            else:
                source = []
        elif provider_id == "ollama":
            try:
                source = _fetch_ollama_models()
            except Exception:
                continue
        else:
            token = None
            if _keyring is not None:
                try:
                    token = _keyring.get_password("agentforce-provider", provider_id)
                except Exception:
                    pass
            if not token:
                continue
            source = meta.get("cached_models", [])

        for model in source:
            mid = model["id"]
            if mid in seen:
                continue
            if enabled is None or mid in enabled:
                seen.add(mid)
                models.append({
                    "id": mid,
                    "name": model["name"],
                    "provider": catalogue["display_name"],
                    "cost_per_1k_input": model["cost_per_1k_input"],
                    "cost_per_1k_output": model["cost_per_1k_output"],
                    "latency_label": model["latency_label"],
                })
    return models


def _providers_list() -> list[dict]:
    try:
        import keyring as _keyring
    except Exception:
        _keyring = None  # type: ignore[assignment]

    metadata = _provider_metadata()
    agents_meta = metadata.get("_agents", {})
    default_agent = agents_meta.get("default_agent")

    result = []
    for provider_id, catalogue in _PROVIDER_CATALOGUE.items():
        meta = metadata.get(provider_id, {})
        enabled_models = meta.get("enabled_models")
        provider_type = catalogue.get("type", "api")

        if provider_type == "cli":
            binary = catalogue.get("binary", provider_id)
            active = _check_agent_binary(binary)
            if provider_id == "opencode":
                all_models: list[dict] = metadata.get("openrouter", {}).get("cached_models", [])
            elif provider_id in {"claude", "codex"}:
                all_models = _get_provider_models(provider_id)
            elif "cached_models" in meta:
                all_models = meta["cached_models"]
            else:
                all_models = []
            result.append({
                "id": provider_id,
                "display_name": catalogue["display_name"],
                "description": catalogue.get("description", ""),
                "type": "cli",
                "binary": binary,
                "requires_key": False,
                "active": active,
                "is_default": provider_id == default_agent,
                "last_configured": None,
                "enabled_models": enabled_models,
                "default_model": meta.get("default_model"),
                "all_models": all_models,
            })
        else:
            if provider_id == "ollama":
                active = False
                live_models: list[dict] = []
                try:
                    live_models = _fetch_ollama_models()
                    active = True
                except Exception:
                    pass
                all_models = live_models
            else:
                token = None
                if _keyring is not None:
                    try:
                        token = _keyring.get_password("agentforce-provider", provider_id)
                    except Exception:
                        pass
                active = token is not None
                all_models = meta.get("cached_models", [])
            result.append({
                "id": provider_id,
                "display_name": catalogue["display_name"],
                "description": catalogue.get("description", ""),
                "type": "api",
                "requires_key": catalogue.get("requires_key", True),
                "active": active,
                "is_default": False,
                "last_configured": meta.get("last_configured"),
                "enabled_models": enabled_models,
                "default_model": meta.get("default_model"),
                "all_models": all_models,
            })
    return result


def _activate_agent(agent_id: str) -> tuple[int, dict]:
    cli_ids = {pid for pid, cat in _PROVIDER_CATALOGUE.items() if cat.get("type") == "cli"}
    if agent_id and agent_id not in cli_ids:
        return 404, {"error": f"Unknown agent: {agent_id!r}"}
    metadata = _provider_metadata()
    agents_meta = metadata.setdefault("_agents", {})
    if agent_id:
        agents_meta["default_agent"] = agent_id
    else:
        agents_meta.pop("default_agent", None)
    state_io._save_providers_metadata(metadata)
    return 200, {"activated": bool(agent_id)}


def _set_agent_model(agent_id: str, model: str | None) -> tuple[int, dict]:
    if agent_id not in {pid for pid, cat in _PROVIDER_CATALOGUE.items() if cat.get("type") == "cli"}:
        return 404, {"error": f"Unknown agent: {agent_id!r}"}
    metadata = _provider_metadata()
    agents_meta = metadata.setdefault("_agents", {})
    agent_meta = agents_meta.setdefault(agent_id, {})
    if model:
        agent_meta["model"] = model
    else:
        agent_meta.pop("model", None)
    state_io._save_providers_metadata(metadata)
    return 200, {"updated": True}


def _get_global_default_model() -> dict:
    metadata = _provider_metadata()
    return {"model": metadata.get("_default_model")}


def _set_global_default_model(model_id: str | None) -> tuple[int, dict]:
    metadata = _provider_metadata()
    if model_id:
        metadata["_default_model"] = model_id
    else:
        metadata.pop("_default_model", None)
    state_io._save_providers_metadata(metadata)
    return 200, {"updated": True}


def _refresh_provider_models(provider_id: str) -> tuple[int, dict]:
    if provider_id not in _PROVIDER_CATALOGUE:
        return 404, {"error": f"Unknown provider: {provider_id!r}"}
    catalogue = _PROVIDER_CATALOGUE[provider_id]
    provider_type = catalogue.get("type", "api")

    if provider_type == "cli":
        if provider_id == "opencode":
            return 200, {"refreshed": True}
        try:
            if provider_id == "claude":
                models = _fetch_claude_code_models()
            elif provider_id == "codex":
                models = _fetch_codex_models()
            else:
                return 400, {"error": f"No model fetcher for {provider_id!r}"}
        except Exception as exc:
            return 500, {"error": str(exc)}
        metadata = _provider_metadata()
        meta = metadata.get(provider_id, {})
        meta["cached_models"] = models
        meta["models_cached_at"] = _now_iso()
        metadata[provider_id] = meta
        state_io._save_providers_metadata(metadata)
        return 200, {"refreshed": True, "count": len(models)}

    if provider_id == "ollama":
        return 200, {"refreshed": True}
    try:
        import keyring

        api_key = keyring.get_password("agentforce-provider", provider_id)
    except Exception as exc:
        return 500, {"error": str(exc)}
    if not api_key:
        return 400, {"error": "no api key configured"}
    try:
        models = _fetch_openrouter_models(api_key)
    except Exception as exc:
        return 500, {"error": str(exc)}
    metadata = _provider_metadata()
    meta = metadata.get(provider_id, {})
    meta["cached_models"] = models
    meta["models_cached_at"] = _now_iso()
    metadata[provider_id] = meta
    state_io._save_providers_metadata(metadata)
    return 200, {"refreshed": True, "count": len(models)}


def _configure_provider(provider_id: str, body: dict) -> tuple[int, dict]:
    if provider_id not in _PROVIDER_CATALOGUE:
        return 404, {"error": f"Unknown provider: {provider_id!r}"}
    catalogue = _PROVIDER_CATALOGUE[provider_id]
    if catalogue.get("requires_key", True):
        api_key = body.get("api_key")
        if not isinstance(api_key, str) or not api_key.strip():
            return 400, {"error": "api_key is required"}
        try:
            import keyring

            keyring.set_password("agentforce-provider", provider_id, api_key)
        except Exception as exc:
            return 500, {"error": str(exc)}
        metadata = _provider_metadata()
        meta = metadata.get(provider_id, {})
        meta["last_configured"] = _now_iso()
        try:
            meta["cached_models"] = _fetch_openrouter_models(api_key)
            meta["models_cached_at"] = _now_iso()
        except Exception:
            pass
        metadata[provider_id] = meta
        state_io._save_providers_metadata(metadata)
    return 200, {"configured": True}


def _test_provider(provider_id: str) -> tuple[int, dict]:
    if provider_id == "ollama":
        try:
            _fetch_ollama_models()
            return 200, {"ok": True}
        except Exception as exc:
            return 200, {"ok": False, "error": str(exc)}
    try:
        import keyring

        token = keyring.get_password("agentforce-provider", provider_id)
    except Exception as exc:
        return 200, {"ok": False, "error": str(exc)}
    if not token:
        return 200, {"ok": False, "error": "no api key configured"}
    try:
        urllib_request.urlopen(
            urllib_request.Request(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {token}", "HTTP-Referer": "https://agentforce.local"},
            ),
            timeout=10,
            context=_ssl_context(),
        )
        return 200, {"ok": True}
    except Exception as exc:
        return 200, {"ok": False, "error": str(exc)}


def _update_provider_models(provider_id: str, body: dict) -> tuple[int, dict]:
    if provider_id not in _PROVIDER_CATALOGUE:
        return 404, {"error": f"Unknown provider: {provider_id!r}"}
    enabled_models = body.get("enabled_models")
    default_model = body.get("default_model")
    if not isinstance(enabled_models, list) and enabled_models is not None:
        return 400, {"error": "enabled_models must be a list or null"}
    metadata = _provider_metadata()
    meta = metadata.get(provider_id, {})
    meta["enabled_models"] = enabled_models
    if default_model is not None:
        meta["default_model"] = default_model
    metadata[provider_id] = meta
    state_io._save_providers_metadata(metadata)
    return 200, {"updated": True}


def _deactivate_provider(provider_id: str) -> tuple[int, dict]:
    if provider_id not in _PROVIDER_CATALOGUE:
        return 404, {"error": f"Unknown provider: {provider_id!r}"}
    try:
        import keyring

        try:
            keyring.delete_password("agentforce-provider", provider_id)
        except Exception:
            pass
    except Exception as exc:
        return 500, {"error": str(exc)}
    return 200, {"deactivated": True}


def _delete_provider_data(provider_id: str) -> tuple[int, dict]:
    if provider_id not in _PROVIDER_CATALOGUE:
        return 404, {"error": f"Unknown provider: {provider_id!r}"}
    try:
        import keyring

        try:
            keyring.delete_password("agentforce-provider", provider_id)
        except Exception:
            pass
    except Exception as exc:
        return 500, {"error": str(exc)}
    metadata = _provider_metadata()
    metadata.pop(provider_id, None)
    state_io._save_providers_metadata(metadata)
    return 200, {"deleted": True}


def _connector_test_request(name: str, token: str) -> None:
    if not token:
        raise ValueError("no token configured")

    if name == "github":
        req = urllib_request.Request(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "AgentForce",
            },
        )
        urllib_request.urlopen(req, timeout=10)
        return

    if name == "slack":
        req = urllib_request.Request(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib_request.urlopen(req, timeout=10) as resp:
            payload = _jsonlib.loads(resp.read().decode("utf-8") or "{}")
        if not payload.get("ok"):
            raise RuntimeError(payload.get("error", "slack auth failed"))
        return

    if name == "linear":
        req = urllib_request.Request(
            "https://api.linear.app/graphql",
            data=_jsonlib.dumps({"query": "{ viewer { id } }"}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        urllib_request.urlopen(req, timeout=10)
        return

    if name == "sentry":
        req = urllib_request.Request(
            "https://sentry.io/api/0/",
            headers={"Authorization": f"Bearer {token}"},
        )
        urllib_request.urlopen(req, timeout=10)
        return

    if name == "notion":
        req = urllib_request.Request(
            "https://api.notion.com/v1/users/me",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": "2022-06-28",
            },
        )
        urllib_request.urlopen(req, timeout=10)
        return

    if name == "anthropic":
        from anthropic import Anthropic

        client = Anthropic(api_key=token)
        client.models.list()
        return

    if not token.strip():
        raise ValueError("no token configured")


def _connectors_get(handler, parts: list[str]) -> tuple[int, dict | None]:
    metadata = state_io._load_connectors_metadata()
    try:
        import keyring
    except Exception as exc:
        return 500, {"error": str(exc)}
    connectors = []
    for name, display_name in _KNOWN_CONNECTORS.items():
        token = None
        try:
            token = keyring.get_password("agentforce", name)
        except Exception:
            token = None
        connectors.append({
            "name": name,
            "display_name": display_name,
            "active": token is not None,
            "last_configured": metadata.get(name, {}).get("last_configured"),
        })
    return 200, connectors


def _telemetry_get(handler, parts: list[str]) -> tuple[int, dict | None]:
    missions = state_io._load_all_missions()
    total_tasks = 0
    total_cost = 0.0
    total_tokens_in = 0
    total_tokens_out = 0
    missions_by_cost = []
    tasks_by_cost = []
    retry_distribution = {"0": 0, "1": 0, "2+": 0}
    cost_over_time = []

    for state in missions:
        total_tasks += len(state.task_states)
        total_cost += state.cost_usd
        total_tokens_in += state.tokens_in
        total_tokens_out += state.tokens_out
        missions_by_cost.append({
            "mission_id": state.mission_id,
            "name": state.spec.name,
            "cost_usd": state.cost_usd,
            "tokens_in": state.tokens_in,
            "tokens_out": state.tokens_out,
            "duration": fmt_duration(state.started_at, state.completed_at),
            "retries": state.total_retries,
        })
        for task_id, task_state in state.task_states.items():
            task_spec = next((task for task in state.spec.tasks if task.id == task_id), None)
            tasks_by_cost.append({
                "mission_id": state.mission_id,
                "task_id": task_id,
                "task": task_spec.title if task_spec else task_id,
                "mission": state.spec.name,
                "model": state.worker_model,
                "cost_usd": task_state.cost_usd,
                "retries": task_state.retries,
            })
            if task_state.retries <= 0:
                retry_distribution["0"] += 1
            elif task_state.retries == 1:
                retry_distribution["1"] += 1
            else:
                retry_distribution["2+"] += 1

    ordered_missions = sorted(
        missions,
        key=lambda state: (
            _parse_iso_datetime(state.started_at) or datetime.min.replace(tzinfo=timezone.utc),
            state.mission_id,
        ),
    )
    cumulative_cost = 0.0
    for state in ordered_missions:
        cumulative_cost += state.cost_usd
        cost_over_time.append({
            "mission_name": state.spec.name,
            "cumulative_cost": round(cumulative_cost, 4),
        })

    missions_by_cost.sort(key=lambda item: item["cost_usd"], reverse=True)
    tasks_by_cost.sort(key=lambda item: item["cost_usd"], reverse=True)
    return 200, {
        "total_missions": len(missions),
        "total_tasks": total_tasks,
        "total_cost_usd": total_cost,
        "total_tokens_in": total_tokens_in,
        "total_tokens_out": total_tokens_out,
        "missions_by_cost": missions_by_cost[:5],
        "tasks_by_cost": tasks_by_cost[:5],
        "retry_distribution": retry_distribution,
        "cost_over_time": cost_over_time,
    }


def _connectors_post(handler, parts: list[str], body: dict) -> tuple[int, dict | None]:
    if len(parts) == 4 and parts[3] == "configure":
        token = body.get("token")
        if not isinstance(token, str) or not token:
            return 400, {"error": "token is required"}
        try:
            import keyring

            keyring.set_password("agentforce", parts[2], token)
        except Exception as exc:
            return 500, {"error": str(exc)}
        metadata = state_io._load_connectors_metadata()
        metadata[parts[2]] = {
            "active": True,
            "last_configured": _now_iso(),
        }
        state_io._save_connectors_metadata(metadata)
        return 200, {"configured": True}
    if len(parts) == 4 and parts[3] == "test":
        try:
            import keyring

            token = keyring.get_password("agentforce", parts[2])
            _connector_test_request(parts[2], token or "")
        except Exception as exc:
            return 200, {"ok": False, "error": str(exc)}
        return 200, {"ok": True}
    return 404, {"error": "Not found"}


def _connectors_delete(handler, parts: list[str]) -> tuple[int, dict | None]:
    try:
        import keyring

        try:
            keyring.delete_password("agentforce", parts[2])
        except Exception:
            pass
    except Exception as exc:
        return 500, {"error": str(exc)}
    metadata = state_io._load_connectors_metadata()
    metadata.pop(parts[2], None)
    state_io._save_connectors_metadata(metadata)
    return 200, {"deleted": True}


def get(handler, parts: list[str], query: dict) -> tuple[int, dict | None]:
    if len(parts) == 2 and parts[1] == "models":
        return 200, _models_list()
    if len(parts) == 3 and parts[1] == "models" and parts[2] == "default":
        return 200, _get_global_default_model()
    if len(parts) == 2 and parts[1] == "providers":
        return 200, _providers_list()
    if len(parts) == 2 and parts[1] == "agents":
        return 200, _providers_list()
    if len(parts) == 2 and parts[1] == "telemetry":
        return _telemetry_get(handler, parts)
    if len(parts) == 2 and parts[1] == "connectors":
        return _connectors_get(handler, parts)
    if len(parts) == 2 and parts[1] == "config":
        config = _load_config()
        fs = config.get("filesystem", {})
        raw_paths = fs.get("allowed_base_paths", [])
        expanded = [str(Path(p).expanduser().resolve()) for p in raw_paths if p]
        return 200, {"filesystem": {"allowed_base_paths": expanded}}
    return 404, {"error": "Not found"}


def post(handler, parts: list[str], query: dict) -> tuple[int, dict | None]:
    try:
        body = handler._read_json_body()
    except ValueError as exc:
        return 400, {"error": str(exc)}

    if len(parts) == 3 and parts[1] == "models" and parts[2] == "default":
        model_id = body.get("model") if isinstance(body, dict) else None
        return _set_global_default_model(model_id)

    if len(parts) == 4 and parts[1] == "providers":
        if parts[3] == "configure":
            return _configure_provider(parts[2], body)
        if parts[3] == "test":
            return _test_provider(parts[2])
        if parts[3] == "models":
            return _update_provider_models(parts[2], body)
        if parts[3] == "refresh":
            return _refresh_provider_models(parts[2])
        if parts[3] == "deactivate":
            return _deactivate_provider(parts[2])
        if parts[3] == "activate":
            return _activate_agent(parts[2])

    if len(parts) == 4 and parts[1] == "connectors":
        return _connectors_post(handler, parts, body)

    if len(parts) == 4 and parts[1] == "agents":
        if parts[3] == "activate":
            return _activate_agent(parts[2])
        if parts[3] == "model":
            model = body.get("model") if isinstance(body, dict) else None
            return _set_agent_model(parts[2], model)

    return 404, {"error": "Not found"}


def delete(handler, parts: list[str], query: dict) -> tuple[int, dict | None]:
    if len(parts) == 3 and parts[1] == "providers":
        return _delete_provider_data(parts[2])
    if len(parts) == 3 and parts[1] == "connectors":
        return _connectors_delete(handler, parts)
    return 404, {"error": "Not found"}
