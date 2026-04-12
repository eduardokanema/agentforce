"""Failing test — missions/benchmark_memory.py must exist and run cleanly."""
import subprocess
import sys
from pathlib import Path

import pytest


pytest.importorskip("lancedb", reason="lancedb not installed; install agentforce[vector]")
pytest.importorskip("fastembed", reason="fastembed not installed; install agentforce[vector]")


def test_benchmark_script_exists():
    assert Path("missions/benchmark_memory.py").exists(), (
        "missions/benchmark_memory.py does not exist"
    )


def test_benchmark_runs_without_errors():
    result = subprocess.run(
        [sys.executable, "missions/benchmark_memory.py"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Benchmark exited with code {result.returncode}\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )


def test_benchmark_prints_timing():
    result = subprocess.run(
        [sys.executable, "missions/benchmark_memory.py"],
        capture_output=True,
        text=True,
    )
    assert "ms" in result.stdout, "Expected timing output (ms) in stdout"
    assert "Memory" in result.stdout or "JSON" in result.stdout or "Vector" in result.stdout, (
        "Expected backend names in stdout"
    )


def test_lancedb_imports():
    result = subprocess.run(
        [sys.executable, "-c", "import lancedb; print('ok')"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"lancedb import failed: {result.stderr}"


def test_fastembed_imports():
    result = subprocess.run(
        [sys.executable, "-c", "import fastembed; print('ok')"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"fastembed import failed: {result.stderr}"
