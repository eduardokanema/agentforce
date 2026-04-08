"""Agent connectors — one per external CLI/provider."""
from .opencode import run as run_opencode
from .claude import run as run_claude
from .openrouter import run as run_openrouter

CONNECTORS = {
    "opencode": run_opencode,
    "claude": run_claude,
    "openrouter": run_openrouter,
}

__all__ = ["CONNECTORS", "run_opencode", "run_claude", "run_openrouter"]
