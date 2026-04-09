"""Tests for prompt injection queue handling in autonomous missions."""

from __future__ import annotations

import json

from agentforce.autonomous import check_inject_queue


def _inject_path(tmp_path, mission_id: str, task_id: str):
    return tmp_path / ".agentforce" / "state" / mission_id / f"{task_id}.inject"


def test_check_inject_queue_returns_none_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    assert check_inject_queue("mission-1", "task-1") is None


def test_check_inject_queue_returns_message_and_deletes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = _inject_path(tmp_path, "mission-1", "task-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"message": "please retry the worker", "timestamp": "2026-04-08T00:00:00Z"}),
        encoding="utf-8",
    )

    result = check_inject_queue("mission-1", "task-1")

    assert result == "please retry the worker"
    assert not path.exists()


def test_check_inject_queue_returns_none_for_malformed_json(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = _inject_path(tmp_path, "mission-1", "task-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    assert check_inject_queue("mission-1", "task-1") is None
    assert path.exists()
