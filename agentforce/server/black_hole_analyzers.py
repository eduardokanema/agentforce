"""Deterministic analyzers for black-hole campaigns."""
from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class BlackHoleCandidate:
    id: str
    title: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class BlackHoleAnalyzerResult:
    analyzer: str
    metric_label: str
    success: bool
    summary: str
    metric: dict[str, Any]
    candidates: list[BlackHoleCandidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyzer": self.analyzer,
            "metric_label": self.metric_label,
            "success": self.success,
            "summary": self.summary,
            "metric": self.metric,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def _candidate_payload(path: Path, function_name: str, start_line: int, end_line: int, line_count: int, threshold: int) -> dict[str, Any]:
    overflow = max(0, line_count - threshold)
    return {
        "path": str(path),
        "function_name": function_name,
        "start_line": start_line,
        "end_line": end_line,
        "line_count": line_count,
        "threshold": threshold,
        "overflow": overflow,
    }


def _iter_python_function_candidates(root: Path, threshold: int) -> list[BlackHoleCandidate]:
    candidates: list[BlackHoleCandidate] = []
    for path in sorted(root.rglob("*.py")):
        if not path.is_file():
            continue
        try:
            source = path.read_text(encoding="utf-8")
            module = ast.parse(source, filename=str(path))
        except Exception:
            continue
        for node in ast.walk(module):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            start_line = int(getattr(node, "lineno", 0) or 0)
            end_line = int(getattr(node, "end_lineno", start_line) or start_line)
            line_count = max(1, end_line - start_line + 1)
            if line_count <= threshold:
                continue
            payload = _candidate_payload(path, node.name, start_line, end_line, line_count, threshold)
            candidates.append(
                BlackHoleCandidate(
                    id=f"{path}:{node.name}:{start_line}",
                    title=f"{node.name} in {path.name}",
                    summary=f"{path}:{start_line}-{end_line} spans {line_count} lines ({payload['overflow']} over limit)",
                    payload=payload,
                )
            )
    candidates.sort(
        key=lambda candidate: (
            -int(candidate.payload.get("overflow") or 0),
            -int(candidate.payload.get("line_count") or 0),
            str(candidate.payload.get("path") or ""),
            int(candidate.payload.get("start_line") or 0),
        )
    )
    return candidates


def analyze_python_fn_length(workspace_paths: list[str], config: dict[str, Any]) -> BlackHoleAnalyzerResult:
    loop_limits = dict(config.get("loop_limits") or {})
    threshold = int(loop_limits.get("function_line_limit") or 300)
    candidates: list[BlackHoleCandidate] = []
    for workspace in workspace_paths:
        root = Path(workspace)
        if not root.exists():
            continue
        candidates.extend(_iter_python_function_candidates(root, threshold))
    candidates.sort(
        key=lambda candidate: (
            -int(candidate.payload.get("overflow") or 0),
            -int(candidate.payload.get("line_count") or 0),
            str(candidate.payload.get("path") or ""),
            int(candidate.payload.get("start_line") or 0),
        )
    )
    overflow_total = sum(int(candidate.payload.get("overflow") or 0) for candidate in candidates)
    max_line_count = max((int(candidate.payload.get("line_count") or 0) for candidate in candidates), default=0)
    metric = {
        "threshold": threshold,
        "violations": len(candidates),
        "overflow_total": overflow_total,
        "max_line_count": max_line_count,
    }
    summary = (
        "All Python functions are within the configured line limit."
        if not candidates
        else f"Found {len(candidates)} Python functions above the {threshold}-line limit."
    )
    return BlackHoleAnalyzerResult(
        analyzer="python_fn_length",
        metric_label=f"Functions > {threshold} lines",
        success=not candidates,
        summary=summary,
        metric=metric,
        candidates=candidates,
    )


def _load_manifest(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8")
    if path.suffix in {".yaml", ".yml"}:
        payload = yaml.safe_load(raw)
    elif path.suffix == ".json":
        payload = json.loads(raw)
    else:
        payload = [line.strip() for line in raw.splitlines() if line.strip()]
    if isinstance(payload, dict):
        payload = payload.get("sections") or payload.get("required") or []
    if not isinstance(payload, list):
        raise ValueError("Documentation manifest must contain a list of required paths")
    return [str(item).strip() for item in payload if str(item).strip()]


def analyze_docs_section_coverage(workspace_paths: list[str], config: dict[str, Any]) -> BlackHoleAnalyzerResult:
    manifest_path_value = str(config.get("docs_manifest_path") or "").strip()
    if not manifest_path_value:
        raise ValueError("docs_section_coverage requires docs_manifest_path")
    manifest_path = Path(manifest_path_value)
    if not manifest_path.is_absolute() and workspace_paths:
        manifest_path = Path(workspace_paths[0]) / manifest_path
    if not manifest_path.exists():
        raise ValueError(f"Documentation manifest not found: {manifest_path}")
    required_paths = _load_manifest(manifest_path)
    workspace_root = Path(workspace_paths[0]) if workspace_paths else manifest_path.parent
    missing: list[BlackHoleCandidate] = []
    for relative_path in required_paths:
        target = Path(relative_path)
        if not target.is_absolute():
            target = workspace_root / relative_path
        if target.exists():
            continue
        missing.append(
            BlackHoleCandidate(
                id=f"missing-doc:{relative_path}",
                title=relative_path,
                summary=f"Required documentation path is missing: {relative_path}",
                payload={"path": relative_path},
            )
        )
    metric = {
        "required_paths": len(required_paths),
        "missing_paths": len(missing),
        "coverage_pct": 100.0 if not required_paths else round(((len(required_paths) - len(missing)) / len(required_paths)) * 100.0, 2),
    }
    summary = (
        "All manifest-required documentation paths exist."
        if not missing
        else f"{len(missing)} required documentation path(s) are missing."
    )
    return BlackHoleAnalyzerResult(
        analyzer="docs_section_coverage",
        metric_label="Documented manifest sections",
        success=not missing,
        summary=summary,
        metric=metric,
        candidates=missing,
    )


def evaluate_black_hole_analyzer(workspace_paths: list[str], config: dict[str, Any]) -> BlackHoleAnalyzerResult:
    analyzer = str(config.get("analyzer") or "python_fn_length").strip()
    if analyzer == "python_fn_length":
        return analyze_python_fn_length(workspace_paths, config)
    if analyzer == "docs_section_coverage":
        return analyze_docs_section_coverage(workspace_paths, config)
    raise ValueError(f"Unsupported black-hole analyzer: {analyzer}")


def normalized_progress_delta(before_metric: dict[str, Any], after_metric: dict[str, Any], analyzer: str) -> float:
    if analyzer == "python_fn_length":
        return float(before_metric.get("overflow_total") or 0) - float(after_metric.get("overflow_total") or 0)
    if analyzer == "docs_section_coverage":
        return float(before_metric.get("missing_paths") or 0) - float(after_metric.get("missing_paths") or 0)
    return 0.0
