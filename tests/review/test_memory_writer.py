from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentforce.memory.memory import Memory
from agentforce.review import ReviewMemoryWriter
from agentforce.review.models import ActionItem, ReviewReport


def _item(
    item_id: str,
    action_type: str,
    *,
    approved: bool = False,
    memory_scope: str = "",
    memory_key: str = "",
    memory_value: str = "",
    memory_category: str = "",
    description: str = "",
) -> ActionItem:
    return ActionItem(
        id=item_id,
        action_type=action_type,
        approved=approved,
        memory_scope=memory_scope,
        memory_key=memory_key,
        memory_value=memory_value,
        memory_category=memory_category,
        description=description,
    )


def test_write_approved_items_skips_unapproved_items(tmp_path: Path) -> None:
    memory = Memory(tmp_path / "memory")
    writer = ReviewMemoryWriter(memory)
    report = ReviewReport(
        mission_id="mission-123",
        action_items=[
            _item(
                "item-1",
                "memory_entry",
                approved=False,
                memory_scope="global",
                memory_key="review:lesson",
                memory_value="Keep reviews focused.",
                memory_category="lesson",
            )
        ],
    )

    written = writer.write_approved_items(report)

    assert written == 0
    assert memory.global_get("review:lesson") is None
    assert memory.project_get("mission-123", "review:lesson") is None


def test_write_approved_items_memory_entry_global_writes_global_memory(tmp_path: Path) -> None:
    memory = Memory(tmp_path / "memory")
    writer = ReviewMemoryWriter(memory)
    report = ReviewReport(
        mission_id="mission-123",
        action_items=[
            _item(
                "item-1",
                "memory_entry",
                approved=True,
                memory_scope="global",
                memory_key="review:lesson",
                memory_value="Keep reviews focused.",
                memory_category="lesson",
            )
        ],
    )

    written = writer.write_approved_items(report)

    assert written == 1
    assert memory.global_get("review:lesson") == "Keep reviews focused."
    assert memory.project_get("mission-123", "review:lesson") is None


def test_write_approved_items_memory_entry_project_writes_project_memory(tmp_path: Path) -> None:
    memory = Memory(tmp_path / "memory")
    writer = ReviewMemoryWriter(memory)
    report = ReviewReport(
        mission_id="mission-123",
        action_items=[
            _item(
                "item-1",
                "memory_entry",
                approved=True,
                memory_scope="project",
                memory_key="review:project-lesson",
                memory_value="Keep reviews focused.",
                memory_category="lesson",
            )
        ],
    )

    written = writer.write_approved_items(report)

    assert written == 1
    assert memory.project_get("mission-123", "review:project-lesson") == "Keep reviews focused."
    assert memory.global_get("review:project-lesson") is None


def test_write_approved_items_process_improvement_writes_global_memory(tmp_path: Path) -> None:
    memory = Memory(tmp_path / "memory")
    writer = ReviewMemoryWriter(memory)
    report = ReviewReport(
        mission_id="mission-123",
        action_items=[
            _item(
                "item-7",
                "process_improvement",
                approved=True,
                description="Use stronger review checklists.",
            )
        ],
    )

    written = writer.write_approved_items(report)

    assert written == 1
    assert memory.global_get("process:mission-123:item-7") == "Use stronger review checklists."


def test_write_approved_items_roadmap_feature_writes_project_memory(tmp_path: Path) -> None:
    memory = Memory(tmp_path / "memory")
    writer = ReviewMemoryWriter(memory)
    report = ReviewReport(
        mission_id="mission-123",
        action_items=[
            _item(
                "item-9",
                "roadmap_feature",
                approved=True,
                description="Add a review summary export.",
            )
        ],
    )

    written = writer.write_approved_items(report)

    assert written == 1
    assert memory.project_get("mission-123", "roadmap:mission-123:item-9") == "Add a review summary export."


def test_write_approved_items_returns_correct_count(tmp_path: Path) -> None:
    memory = Memory(tmp_path / "memory")
    writer = ReviewMemoryWriter(memory)
    report = ReviewReport(
        mission_id="mission-123",
        action_items=[
            _item(
                "item-1",
                "memory_entry",
                approved=True,
                memory_scope="global",
                memory_key="review:lesson",
                memory_value="Keep reviews focused.",
                memory_category="lesson",
            ),
            _item(
                "item-2",
                "process_improvement",
                approved=False,
                description="Unapproved item should not be written.",
            ),
            _item(
                "item-3",
                "roadmap_feature",
                approved=True,
                description="Add a review summary export.",
            ),
        ],
    )

    written = writer.write_approved_items(report)

    assert written == 2
    assert memory.global_get("review:lesson") == "Keep reviews focused."
    assert memory.project_get("mission-123", "roadmap:mission-123:item-3") == "Add a review summary export."
    assert memory.global_get("process:mission-123:item-2") is None


def test_approve_item_returns_true_when_found_false_when_missing(tmp_path: Path) -> None:
    memory = Memory(tmp_path / "memory")
    writer = ReviewMemoryWriter(memory)
    report = ReviewReport(
        mission_id="mission-123",
        action_items=[
            _item("item-1", "memory_entry"),
            _item("item-2", "roadmap_feature"),
        ],
    )

    assert writer.approve_item(report, "item-2") is True
    assert report.action_items[1].approved is True
    assert writer.approve_item(report, "missing") is False


def test_approve_all_returns_count_of_all_action_items(tmp_path: Path) -> None:
    memory = Memory(tmp_path / "memory")
    writer = ReviewMemoryWriter(memory)
    report = ReviewReport(
        mission_id="mission-123",
        action_items=[
            _item("item-1", "memory_entry"),
            _item("item-2", "process_improvement"),
            _item("item-3", "roadmap_feature"),
        ],
    )

    approved = writer.approve_all(report)

    assert approved == 3
    assert all(item.approved for item in report.action_items)


def test_approve_all_then_write_approved_items_writes_everything(tmp_path: Path) -> None:
    memory = Memory(tmp_path / "memory")
    writer = ReviewMemoryWriter(memory)
    report = ReviewReport(
        mission_id="mission-123",
        action_items=[
            _item(
                "item-1",
                "memory_entry",
                memory_scope="global",
                memory_key="review:lesson",
                memory_value="Keep reviews focused.",
                memory_category="lesson",
            ),
            _item("item-2", "process_improvement", description="Use a checklist."),
            _item("item-3", "roadmap_feature", description="Add export support."),
        ],
    )

    assert writer.approve_all(report) == 3
    assert writer.write_approved_items(report) == 3
    assert memory.global_get("review:lesson") == "Keep reviews focused."
    assert memory.global_get("process:mission-123:item-2") == "Use a checklist."
    assert memory.project_get("mission-123", "roadmap:mission-123:item-3") == "Add export support."


def test_prune_baselines_keeps_only_most_recent_entries(tmp_path: Path) -> None:
    memory = Memory(tmp_path / "memory")
    writer = ReviewMemoryWriter(memory)
    project_id = "mission-123"

    memory.project_set(project_id, "review:metrics:2024-01-01T00:00:00+00:00", "old-1", category="review")
    memory.project_set(project_id, "review:metrics:2024-01-02T00:00:00+00:00", "old-2", category="review")
    memory.project_set(project_id, "review:metrics:2024-01-03T00:00:00+00:00", "keep-1", category="review")
    memory.project_set(project_id, "review:metrics:2024-01-04T00:00:00+00:00", "keep-2", category="review")
    memory.project_set(project_id, "review:metrics:2024-01-05T00:00:00+00:00", "keep-3", category="review")
    memory.project_set(project_id, "review:actions:last3", json.dumps(["a", "b"]), category="review")

    writer.prune_baselines(project_id, keep=3)

    project_dump = memory.project_dump(project_id)
    assert "review:metrics:2024-01-01T00:00:00+00:00" not in project_dump
    assert "review:metrics:2024-01-02T00:00:00+00:00" not in project_dump
    assert "review:metrics:2024-01-03T00:00:00+00:00" in project_dump
    assert "review:metrics:2024-01-04T00:00:00+00:00" in project_dump
    assert "review:metrics:2024-01-05T00:00:00+00:00" in project_dump
    assert "review:actions:last3" in project_dump
