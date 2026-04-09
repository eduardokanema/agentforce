"""Model API route."""
from __future__ import annotations

from . import providers


def get(handler, parts: list[str], query: dict):
    return providers.get(handler, parts, query)


def post(handler, parts: list[str], query: dict):
    return providers.post(handler, parts, query)
