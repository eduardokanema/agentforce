"""Benchmark: flat JSON Memory vs LanceDB VectorMemory with real embeddings.

200 inserts + 50 semantic queries (VectorMemory with query=)
vs  200 inserts + 50 exact lookups (flat Memory).

Prints a comparison table with: backend, insert_time_ms, query_time_ms, query_type
"""
from __future__ import annotations

import random
import string
import tempfile
import time

from agentforce.memory.memory import Memory
from agentforce.memory.vector_memory import VectorMemory

# ── Constants ─────────────────────────────────────────────────────────────────

N_ENTRIES = 200
N_QUERIES = 50

_TOPICS = [
    "authentication and security tokens",
    "database configuration and migrations",
    "API endpoint design patterns",
    "deployment pipeline configuration",
    "error handling and structured logging",
    "testing strategies and coverage targets",
    "performance optimisation techniques",
    "user interface component patterns",
    "data serialisation formats",
    "network protocols and timeout settings",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rand_str(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=n))


def _make_entries(n: int) -> list[dict]:
    categories = ["general", "convention", "lesson", "fact"]
    return [
        {
            "key": f"key_{i}_{_rand_str()}",
            "value": f"{_TOPICS[i % len(_TOPICS)]} — detail {_rand_str(12)}",
            "category": random.choice(categories),
        }
        for i in range(n)
    ]


# ── Benchmark runners ─────────────────────────────────────────────────────────

def bench_json(entries: list[dict], lookup_keys: list[str], tmp_dir: str) -> tuple[float, float]:
    """Flat Memory: 200 inserts + 50 exact key lookups."""
    mem = Memory(tmp_dir)

    t0 = time.perf_counter()
    for e in entries:
        mem.global_set(e["key"], e["value"], e["category"])
    insert_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    for k in lookup_keys:
        mem.global_get(k)
    query_ms = (time.perf_counter() - t0) * 1000

    return insert_ms, query_ms


def bench_vector(entries: list[dict], queries: list[str], tmp_dir: str) -> tuple[float, float]:
    """VectorMemory: 200 inserts (real embeddings) + 50 semantic queries."""
    vm = VectorMemory(tmp_dir)

    t0 = time.perf_counter()
    for e in entries:
        vm.global_set(e["key"], e["value"], e["category"])
    insert_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    for q in queries:
        vm.agent_context("benchmark", query=q, top_k=5)
    query_ms = (time.perf_counter() - t0) * 1000

    return insert_ms, query_ms


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    random.seed(42)
    entries = _make_entries(N_ENTRIES)
    lookup_keys = [e["key"] for e in random.sample(entries, N_QUERIES)]
    semantic_queries = [_TOPICS[i % len(_TOPICS)] for i in range(N_QUERIES)]

    print("Running benchmarks (embedding model may download on first run)…")

    with tempfile.TemporaryDirectory() as td_json:
        json_insert_ms, json_query_ms = bench_json(entries, lookup_keys, td_json)

    with tempfile.TemporaryDirectory() as td_vec:
        vec_insert_ms, vec_query_ms = bench_vector(entries, semantic_queries, td_vec)

    # ── Print comparison table ─────────────────────────────────────────────────
    b_w, t_w, q_w = 20, 16, 16
    row_fmt = f"{{:<{b_w}}} {{:>{t_w}}} {{:>{q_w}}} {{:<12}}"
    sep = "-" * (b_w + t_w + q_w + 14)

    print()
    print(row_fmt.format("backend", "insert_time_ms", "query_time_ms", "query_type"))
    print(sep)
    print(row_fmt.format("JSON Memory",   f"{json_insert_ms:.1f}", f"{json_query_ms:.1f}",  "exact"))
    print(row_fmt.format("VectorMemory",  f"{vec_insert_ms:.1f}",  f"{vec_query_ms:.1f}",   "semantic"))
    print()


if __name__ == "__main__":
    main()
