"""HTTP handler and routing for the AgentForce dashboard."""
from __future__ import annotations

import json as _jsonlib
import os
import threading
import time as _time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import request as urllib_request

import ssl

import yaml

from .render import render_mission_list, render_mission_detail, render_task_detail
from . import ws

_STREAMS_DIR = Path.home() / ".agentforce" / "streams"
_SSE_TERMINAL = {"review_approved", "review_rejected", "failed", "blocked"}

AGENTFORCE_HOME = Path(os.path.expanduser("~/.agentforce"))
STATE_DIR = AGENTFORCE_HOME / "state"
_STATIC_DIR = Path(__file__).parent / "static"
_UI_DIST = Path(__file__).parent.parent.parent / "ui" / "dist"
_KNOWN_CONNECTORS = {
    "github": "GitHub",
    "slack": "Slack",
    "linear": "Linear",
    "sentry": "Sentry",
    "notion": "Notion",
    "anthropic": "Anthropic",
}

_PROVIDER_CATALOGUE: dict[str, dict] = {
    # ── API providers ─────────────────────────────────────────────────────
    "openrouter": {
        "display_name": "OpenRouter",
        "description": "Access hundreds of AI models (Claude, GPT-4, Gemini, Llama…) via a single API key with live pricing.",
        "type": "api",
        "requires_key": True,
        "models": [],  # Populated dynamically from openrouter.ai/api/v1/models
    },
    "ollama": {
        "display_name": "Ollama",
        "description": "Run AI models locally on your machine. Install models with `ollama pull`.",
        "type": "api",
        "requires_key": False,
        "models": [],  # Populated dynamically from localhost:11434/api/tags
    },
    # ── CLI executors ─────────────────────────────────────────────────────
    "opencode": {
        "display_name": "OpenCode",
        "description": "Open-source AI coding agent. Shares models from your configured OpenRouter key.",
        "type": "cli",
        "binary": "opencode",
        "requires_key": False,
        "models": [],  # Inherits from OpenRouter cached_models
    },
    "claude": {
        "display_name": "Claude Code",
        "description": "Anthropic's official coding CLI. Authenticated separately via the `claude` binary.",
        "type": "cli",
        "binary": "claude",
        "requires_key": False,
        "models": [],  # Populated dynamically via `claude models ls` or Anthropic API
    },
    "codex": {
        "display_name": "Codex CLI",
        "description": "OpenAI's coding assistant CLI. Authenticated separately via the `codex` binary.",
        "type": "cli",
        "binary": "codex",
        "requires_key": False,
        "models": [],  # Populated dynamically via `codex models` or OpenAI API
    },
}


def _ssl_context() -> ssl.SSLContext:
    """Return an SSL context using certifi CA bundle when available (fixes macOS urllib)."""
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


def _format_duration(started_at: str | None, completed_at: str | None = None) -> str:
    started = _parse_iso_datetime(started_at)
    if started is None:
        return "?"
    ended = _parse_iso_datetime(completed_at) if completed_at else datetime.now(timezone.utc)
    if ended is None:
        return "?"
    seconds = max(0, int((ended - started).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


def _connectors_path() -> Path:
    return AGENTFORCE_HOME / "connectors.json"


def _load_connectors_metadata() -> dict[str, dict[str, Any]]:
    path = _connectors_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("{}", encoding="utf-8")
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = _jsonlib.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_connectors_metadata(data: dict[str, dict[str, Any]]) -> None:
    path = _connectors_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        _jsonlib.dump(data, fh, indent=2)


def _providers_path() -> Path:
    return AGENTFORCE_HOME / "providers.json"


def _load_providers_metadata() -> dict[str, dict]:
    path = _providers_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = _jsonlib.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_providers_metadata(data: dict) -> None:
    path = _providers_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        _jsonlib.dump(data, fh, indent=2)


def _load_config() -> dict:
    config_path = AGENTFORCE_HOME / "config.yaml"
    if not config_path.exists():
        return {}
    try:
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
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(raw_path)
    qs = parse_qs(parsed.query)
    return {k: v[0] for k, v in qs.items() if v}


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
        for m in data.get("models", []) if m.get("name")
    ]


def _check_agent_binary(binary: str) -> bool:
    import shutil
    return shutil.which(binary) is not None


# ── Static model lists for CLI executors ──────────────────────────────────────
#
# Neither `claude` nor `codex` expose a model-listing CLI command.
#
# Claude Code:
#   - No model-list subcommand exists (confirmed: only agents/auth/mcp/update/…)
#   - Source of truth: https://docs.anthropic.com/en/docs/about-claude/models
#   - Update this list when Anthropic releases new production models.
#
# Codex:
#   - No model-list subcommand exists (confirmed: only exec/review/login/mcp/…)
#   - The Codex CLI maintains ~/.codex/models_cache.json with the live list.
#   - This static list is used only as a fallback when that file is absent.
#   - Source of truth for the static list: https://platform.openai.com/docs/models
#   - The cache file is refreshed automatically whenever the user runs codex.

_CLAUDE_CODE_MODELS: list[dict] = [
    # ── Claude 4.x ────────────────────────────────────────────────────────────
    {"id": "claude-opus-4-6",          "name": "Claude Opus 4.6",   "latency_label": "Powerful"},
    {"id": "claude-sonnet-4-6",        "name": "Claude Sonnet 4.6", "latency_label": "Standard"},
    # ── Claude 4.5 ────────────────────────────────────────────────────────────
    {"id": "claude-opus-4-5",          "name": "Claude Opus 4.5",   "latency_label": "Powerful"},
    {"id": "claude-sonnet-4-5",        "name": "Claude Sonnet 4.5", "latency_label": "Standard"},
    {"id": "claude-haiku-4-5-20251001","name": "Claude Haiku 4.5",  "latency_label": "Fast"},
]

_CODEX_MODELS_STATIC_FALLBACK: list[dict] = [
    # Used only when ~/.codex/models_cache.json is absent.
    # The cache file is the authoritative source — update it by running `codex` once.
    # ── GPT-5.x (current as of 2026-04) ──────────────────────────────────────
    {"id": "gpt-5.4",       "name": "GPT-5.4",        "latency_label": "Standard"},
    {"id": "gpt-5.4-mini",  "name": "GPT-5.4-Mini",   "latency_label": "Fast"},
    {"id": "gpt-5.3-codex", "name": "GPT-5.3-Codex",  "latency_label": "Standard"},
    {"id": "gpt-5.2",       "name": "GPT-5.2",         "latency_label": "Standard"},
]


def _fetch_claude_code_models() -> list[dict]:
    """Return the available Claude Code model list (static — see _CLAUDE_CODE_MODELS)."""
    return [{"cost_per_1k_input": 0.0, "cost_per_1k_output": 0.0, **m} for m in _CLAUDE_CODE_MODELS]


def _fetch_codex_models() -> list[dict]:
    """Return Codex models from ~/.codex/models_cache.json, falling back to _CODEX_MODELS_STATIC_FALLBACK.

    The cache file is written by the codex CLI whenever it refreshes model info.
    It uses ``slug`` as the model ID, ``display_name`` as the label, and
    ``visibility`` == "hide" to suppress internal/deprecated models.
    """
    def _norm(slug: str, name: str | None = None) -> dict:
        label = ("Powerful" if any(x in slug for x in ("max", "o3", "o1", "4-turbo"))
                 else "Fast" if "mini" in slug else "Standard")
        return {"id": slug, "name": name or slug,
                "cost_per_1k_input": 0.0, "cost_per_1k_output": 0.0, "latency_label": label}

    cache_path = Path.home() / ".codex" / "models_cache.json"
    if cache_path.exists():
        try:
            with open(cache_path, encoding="utf-8") as fh:
                data = _jsonlib.load(fh)
            models = [
                _norm(m["slug"], m.get("display_name"))
                for m in data.get("models", [])
                if isinstance(m, dict) and m.get("slug") and m.get("visibility") != "hide"
            ]
            if models:
                return models
        except Exception:
            pass

    return [{"cost_per_1k_input": 0.0, "cost_per_1k_output": 0.0, **m}
            for m in _CODEX_MODELS_STATIC_FALLBACK]


def _providers_list() -> list[dict]:
    """Build the full provider+CLI list with live availability checks."""
    try:
        import keyring as _keyring
    except Exception:
        _keyring = None  # type: ignore[assignment]

    metadata = _load_providers_metadata()
    agents_meta = metadata.get("_agents", {})
    default_agent = agents_meta.get("default_agent")

    result = []
    for provider_id, catalogue in _PROVIDER_CATALOGUE.items():
        meta = metadata.get(provider_id, {})
        enabled_models = meta.get("enabled_models")  # None = all
        provider_type = catalogue.get("type", "api")

        if provider_type == "cli":
            binary = catalogue.get("binary", provider_id)
            active = _check_agent_binary(binary)
            # OpenCode shares the OpenRouter model list
            if provider_id == "opencode":
                or_meta = metadata.get("openrouter", {})
                all_models: list[dict] = or_meta.get("cached_models", [])
            elif "cached_models" in meta:
                all_models = meta["cached_models"]
            elif provider_id == "claude":
                all_models = _fetch_claude_code_models()
                if all_models:
                    meta["cached_models"] = all_models
                    metadata[provider_id] = meta
                    _save_providers_metadata(metadata)
            elif provider_id == "codex":
                all_models = _fetch_codex_models()
                if all_models:
                    meta["cached_models"] = all_models
                    metadata[provider_id] = meta
                    _save_providers_metadata(metadata)
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


def _models_list() -> list[dict]:
    """Return enabled models from all active providers and CLIs."""
    try:
        import keyring as _keyring
    except Exception:
        _keyring = None  # type: ignore[assignment]

    metadata = _load_providers_metadata()
    models: list[dict] = []
    seen: set[str] = set()

    for provider_id, catalogue in _PROVIDER_CATALOGUE.items():
        meta = metadata.get(provider_id, {})
        enabled = meta.get("enabled_models")  # None = all
        provider_type = catalogue.get("type", "api")

        if provider_type == "cli":
            if not _check_agent_binary(catalogue.get("binary", provider_id)):
                continue
            if provider_id == "opencode":
                or_meta = metadata.get("openrouter", {})
                source: list[dict] = or_meta.get("cached_models", [])
            elif "cached_models" in meta:
                source = meta["cached_models"]
            elif provider_id == "claude":
                source = _fetch_claude_code_models()
                if source:
                    meta["cached_models"] = source
                    metadata[provider_id] = meta
                    _save_providers_metadata(metadata)
            elif provider_id == "codex":
                source = _fetch_codex_models()
                if source:
                    meta["cached_models"] = source
                    metadata[provider_id] = meta
                    _save_providers_metadata(metadata)
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


_CLI_PROVIDER_IDS = {pid for pid, cat in _PROVIDER_CATALOGUE.items() if cat.get("type") == "cli"}


def _activate_agent(agent_id: str) -> tuple[int, dict]:
    if agent_id and agent_id not in _CLI_PROVIDER_IDS:
        return 404, {"error": f"Unknown agent: {agent_id!r}"}
    metadata = _load_providers_metadata()
    agents_meta = metadata.setdefault("_agents", {})
    if agent_id:
        agents_meta["default_agent"] = agent_id
    else:
        agents_meta.pop("default_agent", None)  # clear default
    _save_providers_metadata(metadata)
    return 200, {"activated": bool(agent_id)}


def _set_agent_model(agent_id: str, model: str | None) -> tuple[int, dict]:
    if agent_id not in _CLI_PROVIDER_IDS:
        return 404, {"error": f"Unknown agent: {agent_id!r}"}
    metadata = _load_providers_metadata()
    agents_meta = metadata.setdefault("_agents", {})
    agent_meta = agents_meta.setdefault(agent_id, {})
    if model:
        agent_meta["model"] = model
    else:
        agent_meta.pop("model", None)
    _save_providers_metadata(metadata)
    return 200, {"updated": True}


def _get_global_default_model() -> dict:
    """Return the system-wide default model id, if set."""
    metadata = _load_providers_metadata()
    return {"model": metadata.get("_default_model")}


def _set_global_default_model(model_id: str | None) -> tuple[int, dict]:
    """Persist the system-wide default model."""
    metadata = _load_providers_metadata()
    if model_id:
        metadata["_default_model"] = model_id
    else:
        metadata.pop("_default_model", None)
    _save_providers_metadata(metadata)
    return 200, {"updated": True}


def _refresh_provider_models(provider_id: str) -> tuple[int, dict]:
    """Fetch and cache the live model list for a provider."""
    if provider_id not in _PROVIDER_CATALOGUE:
        return 404, {"error": f"Unknown provider: {provider_id!r}"}
    catalogue = _PROVIDER_CATALOGUE[provider_id]
    provider_type = catalogue.get("type", "api")

    if provider_type == "cli":
        if provider_id == "opencode":
            return 200, {"refreshed": True}  # OpenCode inherits from OpenRouter
        try:
            if provider_id == "claude":
                models = _fetch_claude_code_models()
            elif provider_id == "codex":
                models = _fetch_codex_models()
            else:
                return 400, {"error": f"No model fetcher for {provider_id!r}"}
        except Exception as exc:
            return 500, {"error": str(exc)}
        metadata = _load_providers_metadata()
        meta = metadata.get(provider_id, {})
        meta["cached_models"] = models
        meta["models_cached_at"] = _now_iso()
        metadata[provider_id] = meta
        _save_providers_metadata(metadata)
        return 200, {"refreshed": True, "count": len(models)}

    if provider_id == "ollama":
        return 200, {"refreshed": True}  # Ollama is always live
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
    metadata = _load_providers_metadata()
    meta = metadata.get(provider_id, {})
    meta["cached_models"] = models
    meta["models_cached_at"] = _now_iso()
    metadata[provider_id] = meta
    _save_providers_metadata(metadata)
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
        metadata = _load_providers_metadata()
        meta = metadata.get(provider_id, {})
        meta["last_configured"] = _now_iso()
        try:
            meta["cached_models"] = _fetch_openrouter_models(api_key)
            meta["models_cached_at"] = _now_iso()
        except Exception:
            pass
        metadata[provider_id] = meta
        _save_providers_metadata(metadata)
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
    metadata = _load_providers_metadata()
    meta = metadata.get(provider_id, {})
    meta["enabled_models"] = enabled_models
    if default_model is not None:
        meta["default_model"] = default_model
    metadata[provider_id] = meta
    _save_providers_metadata(metadata)
    return 200, {"updated": True}


def _deactivate_provider(provider_id: str) -> tuple[int, dict]:
    """Remove the API key from keyring (deactivates provider) but keep metadata/model list."""
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
    metadata = _load_providers_metadata()
    metadata.pop(provider_id, None)
    _save_providers_metadata(metadata)
    return 200, {"deleted": True}


def _task_status_value(task_state) -> str:
    status = getattr(task_state.status, "value", task_state.status)
    return str(status)


def _make_mission_state_from_spec(spec):
    from agentforce.core.state import MissionState, TaskState

    mission_id = spec.short_id()
    state = MissionState(mission_id=mission_id, spec=spec)
    state.working_dir = str(Path(spec.working_dir or f"./missions-{mission_id}").resolve())
    for task_spec in spec.tasks:
        state.task_states[task_spec.id] = TaskState(
            task_id=task_spec.id,
            spec_summary=f"{task_spec.title}"[:200],
        )
    return state


def _state_path(mission_id: str) -> Path:
    return STATE_DIR / f"{mission_id}.json"


def _inject_path(mission_id: str, task_id: str) -> Path:
    return AGENTFORCE_HOME / "state" / mission_id / f"{task_id}.inject"


def _broadcast_mission_refresh(state) -> None:
    try:
        ws.broadcast_mission(state.mission_id, state.to_dict())
        ws.broadcast_mission_list([mission.to_summary_dict() for mission in _load_all_missions()])
    except Exception:
        pass


def _broadcast_mission_list_refresh() -> None:
    try:
        ws.broadcast_mission_list([mission.to_summary_dict() for mission in _load_all_missions()])
    except Exception:
        pass


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


def _load_all_missions(state_dir: Path | None = None) -> list:
    state_root = Path(state_dir) if state_dir is not None else STATE_DIR
    if not state_root.exists():
        return []
    from agentforce.core.state import MissionState
    missions = []
    for sf in sorted(state_root.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            missions.append(MissionState.load(sf))
        except Exception:
            pass
    return missions


def _load_state(mission_id: str, state_dir: Path | None = None):
    from agentforce.core.state import MissionState
    state_root = Path(state_dir) if state_dir is not None else STATE_DIR
    if not state_root.exists():
        return None
    for sf in state_root.glob("*.json"):
        if sf.stem == mission_id or sf.stem.startswith(mission_id):
            try:
                return MissionState.load(sf)
            except Exception:
                return None
    return None


def _state_file_signature(state_dir: Path) -> dict[str, int]:
    if not state_dir.exists():
        return {}
    signature = {}
    for sf in state_dir.glob("*.json"):
        try:
            signature[sf.name] = sf.stat().st_mtime_ns
        except OSError:
            continue
    return signature


def _watch_state_dir(
    state_dir: Path | None = None,
    stop_event: threading.Event | None = None,
    poll_seconds: float = 3.0,
) -> None:
    state_root = Path(state_dir) if state_dir is not None else STATE_DIR
    last_signature = _state_file_signature(state_root)

    while stop_event is None or not stop_event.is_set():
        _time.sleep(poll_seconds)
        current_signature = _state_file_signature(state_root)
        if current_signature == last_signature:
            continue
        last_signature = current_signature
        try:
            ws.broadcast_mission_list(
                [mission.to_summary_dict() for mission in _load_all_missions(state_root)]
            )
        except Exception:
            pass


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.headers.get("Upgrade", "").lower() == "websocket":
            self._handle_websocket()
            return

        path = self.path.split("?")[0].rstrip("/") or "/"
        parts = [p for p in path.split("/") if p]

        if parts and parts[0] == "api":
            self._handle_api(parts)
            return

        # Serve static files (legacy)
        if parts and parts[0] == "static":
            self._serve_static("/".join(parts[1:]))
            return

        # Serve React SPA (ui/dist/) if built, otherwise fall back to server-rendered HTML
        if _UI_DIST.exists():
            self._serve_spa(parts)
            return

        try:
            if not parts:
                self._html(render_mission_list(_load_all_missions()))
            elif len(parts) == 2 and parts[0] == "mission":
                state = _load_state(parts[1])
                if state:
                    self._html(render_mission_detail(state))
                else:
                    self._err(404, f"Mission {parts[1]!r} not found")
            elif (len(parts) == 5 and parts[0] == "mission"
                  and parts[2] == "task" and parts[4] == "stream"):
                self._sse(parts[1], parts[3])
            elif len(parts) == 4 and parts[0] == "mission" and parts[2] == "task":
                state = _load_state(parts[1])
                if state:
                    self._html(render_task_detail(state, parts[3]))
                else:
                    self._err(404, f"Mission {parts[1]!r} not found")
            else:
                self._err(404, "Not found")
        except Exception as exc:
            self._err(500, str(exc))

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        parts = [p for p in path.split("/") if p]
        if not parts or parts[0] != "api":
            self._json({"error": "Not found"}, status=404)
            return

        try:
            body = self._read_json_body()
        except ValueError as exc:
            self._json({"error": str(exc)}, status=400)
            return

        try:
            if len(parts) == 2 and parts[1] == "missions":
                self._post_missions(body)
                return
            if len(parts) == 2 and parts[1] == "plan":
                self._post_plan(body)
                return
            if len(parts) == 4 and parts[1] == "mission" and parts[3] == "stop":
                self._post_mission_stop(parts[2])
                return
            if len(parts) == 4 and parts[1] == "mission" and parts[3] == "restart":
                self._post_mission_restart(parts[2])
                return
            if len(parts) == 6 and parts[1] == "mission" and parts[3] == "task":
                if parts[5] == "stop":
                    self._post_task_stop(parts[2], parts[4])
                    return
                if parts[5] == "retry":
                    self._post_task_retry(parts[2], parts[4])
                    return
                if parts[5] == "inject":
                    self._post_task_inject(parts[2], parts[4], body)
                    return
                if parts[5] == "resolve":
                    self._post_task_resolve(parts[2], parts[4], body)
                    return
            if len(parts) == 4 and parts[1] == "connectors":
                if parts[3] == "configure":
                    self._post_connector_configure(parts[2], body)
                    return
                if parts[3] == "test":
                    self._post_connector_test(parts[2])
                    return
            if len(parts) == 3 and parts[1] == "models" and parts[2] == "default":
                model_id = body.get("model") if isinstance(body, dict) else None
                status, payload = _set_global_default_model(model_id)
                self._json(payload, status=status)
                return
            if len(parts) == 4 and parts[1] == "providers":
                if parts[3] == "configure":
                    self._post_provider_configure(parts[2], body)
                    return
                if parts[3] == "test":
                    self._post_provider_test(parts[2])
                    return
                if parts[3] == "models":
                    self._post_provider_models(parts[2], body)
                    return
                if parts[3] == "refresh":
                    self._post_provider_refresh(parts[2])
                    return
                if parts[3] == "deactivate":
                    self._post_provider_deactivate(parts[2])
                    return
                if parts[3] == "activate":
                    self._post_provider_activate(parts[2])
                    return
            if len(parts) == 4 and parts[1] == "agents":
                if parts[3] == "activate":
                    self._post_agent_activate(parts[2])
                    return
                if parts[3] == "model":
                    self._post_agent_model(parts[2], body)
                    return
        except FileNotFoundError:
            self._json({"error": "Not found"}, status=404)
            return
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)
            return

        self._json({"error": "Not found"}, status=404)

    def do_DELETE(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        parts = [p for p in path.split("/") if p]
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "connectors":
            self._delete_connector(parts[2])
            return
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "providers":
            self._delete_provider(parts[2])
            return
        self._json({"error": "Not found"}, status=404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def _handle_websocket(self):
        if not ws.handshake(self):
            return

        conn = ws.WsConnection(self.connection)
        current_bucket = "*"
        ws.register(conn, current_bucket)

        try:
            while True:
                msg = conn.recv_text()
                if msg is None:
                    break

                try:
                    payload = _jsonlib.loads(msg)
                except _jsonlib.JSONDecodeError:
                    continue

                msg_type = payload.get("type")
                if msg_type == "subscribe_all":
                    ws.unregister(conn, current_bucket)
                    current_bucket = "*"
                    ws.register(conn, current_bucket)
                elif msg_type == "subscribe":
                    mission_id = payload.get("mission_id")
                    if not mission_id:
                        continue
                    ws.unregister(conn, current_bucket)
                    current_bucket = mission_id
                    ws.register(conn, current_bucket)
                elif msg_type == "ping":
                    conn.send_text(_jsonlib.dumps({"type": "pong"}))
        except OSError:
            pass
        finally:
            ws.unregister(conn)
            conn.close()

    def _handle_api(self, parts: list[str]):
        if len(parts) == 2 and parts[1] == "missions":
            missions = _load_all_missions()
            self._json([mission.to_summary_dict() for mission in missions])
            return

        if len(parts) == 2 and parts[1] == "models":
            self._json(_models_list())
            return

        if len(parts) == 3 and parts[1] == "models" and parts[2] == "default":
            self._json(_get_global_default_model())
            return

        if len(parts) == 2 and parts[1] == "providers":
            self._json(_providers_list())
            return

        if len(parts) == 2 and parts[1] == "agents":
            self._json(_agents_list())
            return

        if len(parts) == 2 and parts[1] == "config":
            config = _load_config()
            fs = config.get("filesystem", {})
            raw_paths = fs.get("allowed_base_paths", [])
            expanded = [str(Path(p).expanduser().resolve()) for p in raw_paths if p]
            self._json({"filesystem": {"allowed_base_paths": expanded}})
            return

        if len(parts) == 2 and parts[1] == "filesystem":
            params = _parse_query(self.path)
            requested = params.get("path", "")
            allowed = _get_allowed_base_paths()
            if not requested:
                requested = allowed[0] if allowed else str(Path.home())
            try:
                resolved = Path(requested).expanduser().resolve()
            except Exception:
                self._json({"error": "invalid path"}, status=400)
                return
            if allowed:
                if not any(str(resolved).startswith(ap) for ap in allowed):
                    self._json({"error": "path outside allowed directories"}, status=403)
                    return
            if not resolved.exists() or not resolved.is_dir():
                self._json({"error": "directory not found"}, status=404)
                return
            entries: list[dict] = []
            try:
                for entry in sorted(resolved.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
                    if entry.name.startswith("."):
                        continue
                    try:
                        entries.append({"name": entry.name, "path": str(entry), "is_dir": entry.is_dir()})
                    except PermissionError:
                        continue
            except PermissionError:
                self._json({"error": "permission denied"}, status=403)
                return
            parent: str | None = None
            if resolved.parent != resolved:
                parent_str = str(resolved.parent)
                if allowed:
                    if any(parent_str == ap or parent_str.startswith(ap + "/") for ap in allowed):
                        parent = parent_str
                else:
                    parent = parent_str
            self._json({"path": str(resolved), "entries": entries, "parent": parent})
            return

        if len(parts) == 2 and parts[1] == "connectors":
            metadata = _load_connectors_metadata()
            try:
                import keyring
            except Exception as exc:
                self._json({"error": str(exc)}, status=500)
                return
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
            self._json(connectors)
            return

        if len(parts) == 2 and parts[1] == "telemetry":
            missions = _load_all_missions()
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
                    "duration": _format_duration(state.started_at, state.completed_at),
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
            self._json({
                "total_missions": len(missions),
                "total_tasks": total_tasks,
                "total_cost_usd": total_cost,
                "total_tokens_in": total_tokens_in,
                "total_tokens_out": total_tokens_out,
                "missions_by_cost": missions_by_cost[:5],
                "tasks_by_cost": tasks_by_cost[:5],
                "retry_distribution": retry_distribution,
                "cost_over_time": cost_over_time,
            })
            return

        if len(parts) == 3 and parts[1] == "mission":
            state = _load_state(parts[2])
            if not state:
                self._json({"error": f"Mission {parts[2]!r} not found"}, status=404)
                return
            self._json(state.to_dict())
            return

        if len(parts) == 5 and parts[1] == "mission" and parts[3] == "task":
            state = _load_state(parts[2])
            if not state:
                self._json({"error": f"Mission {parts[2]!r} not found"}, status=404)
                return
            task_state = state.task_states.get(parts[4])
            if not task_state:
                self._json(
                    {"error": f"Task {parts[4]!r} not found in mission {parts[2]!r}"},
                    status=404,
                )
                return
            task_spec = next((task for task in state.spec.tasks if task.id == parts[4]), None)
            payload = task_state.to_dict()
            if task_spec:
                payload.update(task_spec.to_dict())
            self._json(payload)
            return

        if len(parts) == 6 and parts[1] == "mission" and parts[3] == "task" and parts[5] == "attempts":
            state = _load_state(parts[2])
            if not state:
                self._json({"error": f"Mission {parts[2]!r} not found"}, status=404)
                return
            task_state = state.task_states.get(parts[4])
            if not task_state:
                self._json(
                    {"error": f"Task {parts[4]!r} not found in mission {parts[2]!r}"},
                    status=404,
                )
                return
            history = getattr(task_state, "attempt_history", None)
            if not history:
                history = getattr(task_state, "attempts", None)
            if not history:
                self._json([{
                    "attempt_number": 1,
                    "output": task_state.worker_output,
                    "review": task_state.review_feedback or None,
                    "score": task_state.review_score,
                }])
                return
            records = []
            for idx, attempt in enumerate(history, start=1):
                if isinstance(attempt, dict):
                    records.append({
                        "attempt_number": attempt.get("attempt_number", attempt.get("attempt", idx)),
                        "output": attempt.get("output", ""),
                        "review": attempt.get("review"),
                        "score": attempt.get("score"),
                    })
                else:
                    records.append({
                        "attempt_number": idx,
                        "output": str(attempt),
                        "review": None,
                        "score": None,
                    })
            self._json(records)
            return

        self._json({"error": "Not found"}, status=404)

    def _serve_spa(self, parts: list[str]):
        """Serve the React SPA from ui/dist/. Static assets are served directly;
        all other paths return index.html so React Router handles routing."""
        _MIME = {
            ".js": "application/javascript",
            ".css": "text/css",
            ".html": "text/html; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
            ".woff2": "font/woff2",
            ".woff": "font/woff",
        }
        # Try to serve a real file from dist (assets, favicon, etc.)
        if parts:
            candidate = _UI_DIST / "/".join(parts)
            if candidate.exists() and candidate.is_file():
                data = candidate.read_bytes()
                mime = _MIME.get(candidate.suffix.lower(), "application/octet-stream")
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=31536000, immutable"
                                 if "/assets/" in self.path else "no-cache")
                self.end_headers()
                self.wfile.write(data)
                return
        # SPA fallback: all other routes → index.html
        index = _UI_DIST / "index.html"
        data = index.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, filename: str):
        filepath = _STATIC_DIR / filename
        if not filepath.exists() or not filepath.is_file():
            self._err(404, "Static file not found")
            return
        ext = filepath.suffix.lower()
        mime = {".css": "text/css", ".js": "application/javascript",
                ".png": "image/png", ".svg": "image/svg+xml"}.get(ext, "application/octet-stream")
        data = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _html(self, content: str):
        encoded = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _json(self, obj, status=200):
        encoded = _jsonlib.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _sse(self, mission_id: str, task_id: str):
        """Stream live agent output as Server-Sent Events."""
        stream_file = _STREAMS_DIR / f"{mission_id}_{task_id}.log"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def _send(line=None, event=None) -> bool:
            try:
                msg = b""
                if event:
                    msg += f"event: {event}\n".encode()
                if line is not None:
                    msg += f"data: {_jsonlib.dumps({'line': line})}\n\n".encode()
                elif event:
                    msg += b"data: {}\n\n"
                self.wfile.write(msg)
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                return False

        pos = 0
        idle = 0
        seq = 0
        try:
            while idle < 180:
                # Keepalive comment
                try:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return

                # Drain new content from stream file
                if stream_file.exists():
                    with open(stream_file, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(pos)
                        chunk = f.read()
                        pos = f.tell()
                    if chunk:
                        idle = 0
                        for ln in chunk.splitlines():
                            seq += 1
                            ws.broadcast_stream_line(mission_id, task_id, ln, seq)
                            if not _send(ln):
                                return
                    else:
                        idle += 1
                else:
                    idle += 1

                # Check if task reached a terminal status
                state = _load_state(mission_id)
                if state:
                    ts = state.task_states.get(task_id)
                    if ts and ts.status in _SSE_TERMINAL:
                        # Drain any remaining content
                        if stream_file.exists():
                            with open(stream_file, "r", encoding="utf-8", errors="replace") as f:
                                f.seek(pos)
                                for ln in f.read().splitlines():
                                    seq += 1
                                    ws.broadcast_stream_line(mission_id, task_id, ln, seq)
                                    _send(ln)
                        ws.broadcast_task_stream_done(mission_id, task_id)
                        _send(event="done")
                        return

                _time.sleep(1)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _err(self, code: int, msg: str):
        from .render import _page
        body = _page("Error", f'<p class="empty">{msg}</p>').encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        if not raw:
            return {}
        try:
            data = _jsonlib.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError("invalid JSON body") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _post_missions(self, body: dict) -> None:
        yaml_text = body.get("yaml")
        if not isinstance(yaml_text, str) or not yaml_text.strip():
            self._json({"error": "yaml is required"}, status=400)
            return
        try:
            from agentforce.core.spec import MissionSpec

            spec = MissionSpec.from_dict(yaml.safe_load(yaml_text))
        except Exception as exc:
            self._json({"error": f"invalid mission yaml: {str(exc)}"}, status=400)
            return

        state = _make_mission_state_from_spec(spec)
        state.log_event("mission_started", details="Started via API")
        _state_path(state.mission_id).parent.mkdir(parents=True, exist_ok=True)
        state.save(_state_path(state.mission_id))
        _broadcast_mission_refresh(state)

        def _runner():
            try:
                from agentforce.autonomous import run_autonomous

                run_autonomous(state.mission_id)
            except SystemExit:
                pass
            except Exception:
                pass

        threading.Thread(target=_runner, daemon=True, name=f"agentforce-mission-{state.mission_id}").start()
        self._json({"id": state.mission_id, "status": "started"})

    def _post_plan(self, body: dict) -> None:
        prompt = body.get("prompt")
        approved_models = body.get("approved_models") or []
        workspaces = body.get("workspaces") or ([body.get("workspace")] if body.get("workspace") else [])
        if not isinstance(prompt, str) or not prompt.strip():
            self._json({"error": "prompt is required"}, status=400)
            return

        # Resolve API key and provider: prefer OpenRouter, fall back to env Anthropic key
        openrouter_key = None
        anthropic_key = None
        try:
            import keyring
            try:
                openrouter_key = keyring.get_password("agentforce-provider", "openrouter")
            except Exception:
                pass
            if not openrouter_key:
                try:
                    anthropic_key = keyring.get_password("agentforce", "anthropic")
                except Exception:
                    pass
        except Exception:
            pass
        if not anthropic_key:
            anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

        if not openrouter_key and not anthropic_key:
            self._json({"error": "no AI provider configured — add an OpenRouter key in Models settings"}, status=400)
            return

        model = (approved_models[0] if isinstance(approved_models, list) and approved_models
                 else ("anthropic/claude-sonnet-4-6" if openrouter_key else "claude-sonnet-4-5"))
        system_prompt = (
            "You are AgentForce's mission planner. Output valid YAML only in the "
            "AgentForce mission format. Do not wrap the YAML in markdown fences, "
            "comments, or prose."
        )
        workspace_info = ", ".join(workspaces) if workspaces else "not specified"
        user_prompt = (
            f"Workspaces: {workspace_info}\n\n"
            f"Approved models: {approved_models}\n\n"
            f"User prompt:\n{prompt}\n"
        )

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        try:
            if openrouter_key:
                self._stream_openrouter(openrouter_key, model, system_prompt, user_prompt)
            else:
                from anthropic import Anthropic
                client = Anthropic(api_key=anthropic_key)
                with client.messages.stream(
                    model=model,
                    max_tokens=4096,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                ) as stream:
                    for chunk in stream.text_stream:
                        if not chunk:
                            continue
                        self.wfile.write(f"data: {chunk}\n\n".encode("utf-8"))
                        self.wfile.flush()
        except Exception as exc:
            try:
                self.wfile.write(f"data: {str(exc)}\n\n".encode("utf-8"))
                self.wfile.flush()
            except OSError:
                pass
        finally:
            try:
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except OSError:
                pass

    def _stream_openrouter(
        self, api_key: str, model: str, system_prompt: str, user_prompt: str
    ) -> None:
        payload = _jsonlib.dumps({
            "model": model,
            "stream": True,
            "max_tokens": 4096,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }).encode("utf-8")
        req = urllib_request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://agentforce.local",
                "X-Title": "AgentForce",
            },
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=120, context=_ssl_context()) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = _jsonlib.loads(data_str)
                    content = chunk["choices"][0].get("delta", {}).get("content", "")
                    if content:
                        self.wfile.write(f"data: {content}\n\n".encode("utf-8"))
                        self.wfile.flush()
                except Exception:
                    pass

    def _post_mission_stop(self, mission_id: str) -> None:
        state = _load_state(mission_id)
        if not state:
            self._json({"error": f"Mission {mission_id!r} not found"}, status=404)
            return
        changed = False
        for task_state in state.task_states.values():
            if _task_status_value(task_state) == "in_progress":
                task_state.status = "blocked"
                changed = True
        if changed:
            state.save(_state_path(mission_id))
            _broadcast_mission_refresh(state)
        self._json({"stopped": True})

    def _post_mission_restart(self, mission_id: str) -> None:
        state = _load_state(mission_id)
        if not state:
            self._json({"error": f"Mission {mission_id!r} not found"}, status=404)
            return
        requeued = 0
        for task_state in state.task_states.values():
            if _task_status_value(task_state) in {"failed", "blocked", "review_rejected"}:
                task_state.status = "pending"
                task_state.worker_output = ""
                requeued += 1
        state.save(_state_path(mission_id))
        _broadcast_mission_list_refresh()
        self._json({"requeued": requeued})

    def _post_task_stop(self, mission_id: str, task_id: str) -> None:
        state = _load_state(mission_id)
        if not state:
            self._json({"error": f"Mission {mission_id!r} not found"}, status=404)
            return
        task_state = state.task_states.get(task_id)
        if not task_state:
            self._json({"error": f"Task {task_id!r} not found in mission {mission_id!r}"}, status=404)
            return
        task_state.status = "blocked"
        state.save(_state_path(mission_id))
        _broadcast_mission_refresh(state)
        self._json({"stopped": True})

    def _post_task_retry(self, mission_id: str, task_id: str) -> None:
        state = _load_state(mission_id)
        if not state:
            self._json({"error": f"Mission {mission_id!r} not found"}, status=404)
            return
        task_state = state.task_states.get(task_id)
        if not task_state:
            self._json({"error": f"Task {task_id!r} not found in mission {mission_id!r}"}, status=404)
            return
        task_state.status = "pending"
        task_state.worker_output = ""
        task_state.retries += 1
        state.total_retries += 1
        state.save(_state_path(mission_id))
        _broadcast_mission_refresh(state)
        self._json({"retrying": True})

    def _post_task_inject(self, mission_id: str, task_id: str, body: dict) -> None:
        state = _load_state(mission_id)
        if not state:
            self._json({"error": f"Mission {mission_id!r} not found"}, status=404)
            return
        task_state = state.task_states.get(task_id)
        if not task_state:
            self._json({"error": f"Task {task_id!r} not found in mission {mission_id!r}"}, status=404)
            return
        if _task_status_value(task_state) != "in_progress":
            self._json({"error": "task not in_progress"}, status=409)
            return
        message = body.get("message")
        if not isinstance(message, str):
            self._json({"error": "message is required"}, status=400)
            return
        inject_path = _inject_path(mission_id, task_id)
        inject_path.parent.mkdir(parents=True, exist_ok=True)
        with open(inject_path, "w", encoding="utf-8") as fh:
            _jsonlib.dump({"message": message, "timestamp": _now_iso()}, fh)
        self._json({"delivered": True})

    def _post_task_resolve(self, mission_id: str, task_id: str, body: dict) -> None:
        state = _load_state(mission_id)
        if not state:
            self._json({"error": f"Mission {mission_id!r} not found"}, status=404)
            return
        task_state = state.task_states.get(task_id)
        if not task_state:
            self._json({"error": f"Task {task_id!r} not found in mission {mission_id!r}"}, status=404)
            return
        if _task_status_value(task_state) != "needs_human":
            self._json({"error": "task not needs_human"}, status=409)
            return
        if body.get("failed"):
            task_state.status = "failed"
            task_state.human_intervention_needed = False
            task_state.human_intervention_message = ""
            task_state.bump()
            state.save(_state_path(mission_id))
            _broadcast_mission_refresh(state)
            self._json({"failed": True})
            return
        message = body.get("message")
        if not isinstance(message, str):
            self._json({"error": "message is required"}, status=400)
            return
        task_state.status = "pending"
        task_state.worker_output = (task_state.worker_output + "\n" + message).strip()
        state.save(_state_path(mission_id))
        _broadcast_mission_refresh(state)
        self._json({"resolved": True})

    def _post_provider_configure(self, provider_id: str, body: dict) -> None:
        status, payload = _configure_provider(provider_id, body)
        self._json(payload, status=status)

    def _post_provider_test(self, provider_id: str) -> None:
        status, payload = _test_provider(provider_id)
        self._json(payload, status=status)

    def _post_provider_models(self, provider_id: str, body: dict) -> None:
        status, payload = _update_provider_models(provider_id, body)
        self._json(payload, status=status)

    def _post_provider_refresh(self, provider_id: str) -> None:
        status, payload = _refresh_provider_models(provider_id)
        self._json(payload, status=status)

    def _post_provider_deactivate(self, provider_id: str) -> None:
        status, payload = _deactivate_provider(provider_id)
        self._json(payload, status=status)

    def _post_provider_activate(self, provider_id: str) -> None:
        # Reuse _activate_agent — provider_id matches the agent key for CLI providers
        status, payload = _activate_agent(provider_id)
        self._json(payload, status=status)

    def _delete_provider(self, provider_id: str) -> None:
        status, payload = _delete_provider_data(provider_id)
        self._json(payload, status=status)

    def _post_agent_activate(self, agent_id: str) -> None:
        status, payload = _activate_agent(agent_id)
        self._json(payload, status=status)

    def _post_agent_model(self, agent_id: str, body: dict) -> None:
        model = body.get("model") if isinstance(body, dict) else None
        status, payload = _set_agent_model(agent_id, model)
        self._json(payload, status=status)

    def _post_connector_configure(self, name: str, body: dict) -> None:
        token = body.get("token")
        if not isinstance(token, str) or not token:
            self._json({"error": "token is required"}, status=400)
            return
        try:
            import keyring

            keyring.set_password("agentforce", name, token)
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)
            return
        metadata = _load_connectors_metadata()
        metadata[name] = {
            "active": True,
            "last_configured": _now_iso(),
        }
        _save_connectors_metadata(metadata)
        self._json({"configured": True})

    def _post_connector_test(self, name: str) -> None:
        try:
            import keyring

            token = keyring.get_password("agentforce", name)
            _connector_test_request(name, token or "")
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)})
            return
        self._json({"ok": True})

    def _delete_connector(self, name: str) -> None:
        try:
            import keyring

            try:
                keyring.delete_password("agentforce", name)
            except Exception:
                pass
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)
            return
        metadata = _load_connectors_metadata()
        metadata.pop(name, None)
        _save_connectors_metadata(metadata)
        self._json({"deleted": True})


def serve(port: int = 8080, state_dir: Path | None = None) -> None:
    global STATE_DIR
    if state_dir is not None:
        STATE_DIR = Path(state_dir)
    server = ThreadingHTTPServer(("localhost", port), DashboardHandler)
    watchdog = threading.Thread(
        target=_watch_state_dir,
        kwargs={"state_dir": STATE_DIR, "poll_seconds": 3.0},
        daemon=True,
        name="agentforce-state-watchdog",
    )
    watchdog.start()
    print(f"AgentForce Dashboard → http://localhost:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
