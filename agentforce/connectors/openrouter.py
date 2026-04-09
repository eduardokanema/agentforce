"""openrouter connector — runs prompts via opencode using an OpenRouter model ID.

OpenRouter models are accessed through opencode with the model ID format:
    openrouter/<provider>/<model>

This connector is a thin wrapper around the opencode connector that prefixes
the model with "openrouter/" when a bare provider/model string is given.
"""
from __future__ import annotations

from pathlib import Path
from . import opencode as _opencode
from agentforce.core.token_event import TokenEvent


def available() -> bool:
    return _opencode.available()


def run(
    prompt: str,
    workdir: str,
    timeout: int = 300,
    model: str = None,
    stream_path: Path = None,
    variant: str = None,
    session_id: str = None,
) -> tuple[bool, str, str, str | None, TokenEvent]:
    """Run a prompt through opencode using an OpenRouter model.

    If the model string doesn't already start with 'openrouter/', it is
    prefixed automatically.

    Returns:
        (success, output, error, session_id, token_event)
    """
    if model and not model.startswith("openrouter/"):
        model = f"openrouter/{model}"
    return _opencode.run(prompt, workdir, timeout, model, stream_path, variant, session_id)
