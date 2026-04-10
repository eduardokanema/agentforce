"""Agent connectors — one per external CLI/provider."""
from .opencode import run as run_opencode
from .claude import run as run_claude
from .openrouter import run as run_openrouter
from .codex import run as run_codex
from .gemini import run as run_gemini

CONNECTORS = {
    "opencode": run_opencode,
    "claude": run_claude,
    "openrouter": run_openrouter,
    "codex": run_codex,
    "gemini": run_gemini,
}

__all__ = ["CONNECTORS", "run_opencode", "run_claude", "run_openrouter", "run_codex", "run_gemini"]
