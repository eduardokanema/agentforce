"""Memory package."""
from __future__ import annotations

from .memory import Memory, MemoryEntry

__all__ = ["Memory", "MemoryEntry", "VectorMemory"]


def __getattr__(name: str):
    if name == "VectorMemory":
        from .vector_memory import VectorMemory

        return VectorMemory
    raise AttributeError(name)
