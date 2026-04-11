from __future__ import annotations

import json
import os
import stat
import threading
from datetime import datetime, timedelta, timezone

from agentforce.server import plan_drafts


def _draft_payload_with_meta(name, goal):
    return {
        "status": "draft",
        "draft_spec": {
            "name": name,
            "goal": goal,
        },
        "turns": [],
        "validation": {},
        "activity_log": [],
        "approved_models": [],
        "workspace_paths": [],
        "companion_profile": {},
        "draft_notes": [],
    }


def test_list_all_empty(tmp_path):
    store = plan_drafts.PlanDraftStore(tmp_path / "drafts")
    assert store.list_all() == []


def test_list_all_excludes_terminal_drafts_by_default(tmp_path):
    store = plan_drafts.PlanDraftStore(tmp_path / "drafts")

    store.create("d1", **_draft_payload_with_meta("Draft 1", "Goal 1"))
    store.create("d2", **_draft_payload_with_meta("Draft 2", "Goal 2"))

    payload3 = _draft_payload_with_meta("Draft 3", "Goal 3")
    payload3["status"] = "finalized"
    store.create("d3", **payload3)

    payload4 = _draft_payload_with_meta("Draft 4", "Goal 4")
    payload4["status"] = "cancelled"
    store.create("d4", **payload4)

    drafts = store.list_all()
    assert {d.id for d in drafts} == {"d1", "d2"}


def test_list_all_includes_terminal_drafts_when_requested(tmp_path):
    store = plan_drafts.PlanDraftStore(tmp_path / "drafts")

    draft_payload = _draft_payload_with_meta("Draft", "Goal")
    store.create("draft", **draft_payload)

    finalized_payload = _draft_payload_with_meta("Finalized", "Done")
    finalized_payload["status"] = "finalized"
    store.create("finalized", **finalized_payload)

    cancelled_payload = _draft_payload_with_meta("Cancelled", "Stopped")
    cancelled_payload["status"] = "cancelled"
    store.create("cancelled", **cancelled_payload)

    drafts_all = store.list_all(include_terminal=True)
    assert {draft.id for draft in drafts_all} == {"draft", "finalized", "cancelled"}
    assert {draft.status for draft in drafts_all} == {"draft", "finalized", "cancelled"}


def test_list_all_sorting_by_activity_log(tmp_path):
    store = plan_drafts.PlanDraftStore(tmp_path / "drafts")

    d1 = store.create("d1", **_draft_payload_with_meta("D1", "G1"))
    store.create("d2", **_draft_payload_with_meta("D2", "G2"))

    now = plan_drafts._utc_now()
    newer_ts = (now + timedelta(minutes=10)).isoformat()
    d1_updated = d1.copy_with(activity_log=[{"timestamp": newer_ts}])
    store.save(d1_updated, expected_revision=1)

    drafts = store.list_all()
    assert len(drafts) == 2
    assert drafts[0].id == "d1"
    assert drafts[1].id == "d2"
    assert drafts[0].updated_at > drafts[1].updated_at


def test_list_all_extracts_name_and_goal_from_nested_draft_spec(tmp_path):
    drafts_dir = tmp_path / "drafts"
    drafts_dir.mkdir()
    store = plan_drafts.PlanDraftStore(drafts_dir)

    payload = {
        **_draft_payload_with_meta("Nested name", "Nested goal"),
        "id": "stale-top-level",
        "revision": 1,
        "name": "Stale top-level name",
        "goal": "Stale top-level goal",
        "updated_at": "2025-01-01T00:00:00+00:00",
        "activity_log": [{"timestamp": "2026-01-01T00:00:00+00:00"}],
    }

    path = drafts_dir / "stale-top-level.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    [draft] = store.list_all(include_terminal=True)
    assert draft.name == "Nested name"
    assert draft.goal == "Nested goal"


def test_list_all_uses_last_activity_timestamp_for_updated_at(tmp_path):
    drafts_dir = tmp_path / "drafts"
    drafts_dir.mkdir()
    store = plan_drafts.PlanDraftStore(drafts_dir)

    payload = {
        **_draft_payload_with_meta("Nested name", "Nested goal"),
        "id": "stale-top-level",
        "revision": 1,
        "updated_at": "2025-01-01T00:00:00+00:00",
        "activity_log": [
            {"timestamp": "2026-01-03T00:00:00+00:00"},
            {"timestamp": "2026-01-01T00:00:00+00:00"},
        ],
    }

    path = drafts_dir / "stale-top-level.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    [draft] = store.list_all(include_terminal=True)
    assert draft.updated_at == datetime.fromisoformat("2026-01-01T00:00:00+00:00")


def test_list_all_falls_back_to_mtime_when_activity_log_is_absent(tmp_path):
    drafts_dir = tmp_path / "drafts"
    drafts_dir.mkdir()
    store = plan_drafts.PlanDraftStore(drafts_dir)

    fallback_payload = {
        **_draft_payload_with_meta("Mtime name", "Mtime goal"),
        "id": "mtime-fallback",
        "revision": 1,
        "updated_at": "2025-01-01T00:00:00+00:00",
        "activity_log": [],
    }

    fallback_path = drafts_dir / "mtime-fallback.json"
    fallback_path.write_text(json.dumps(fallback_payload), encoding="utf-8")
    fallback_mtime = datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp()
    os.utime(fallback_path, (fallback_mtime, fallback_mtime))

    [draft] = store.list_all(include_terminal=True)
    assert draft.updated_at == datetime.fromtimestamp(fallback_mtime, tz=timezone.utc)


def _draft_payload() -> dict:
    return {
        "status": "draft",
        "draft_spec": {
            "name": "Planner mission",
            "goal": "Capture mission draft state",
        },
        "turns": [
            {
                "role": "user",
                "content": "Authorization: Bearer top-secret-token",
            },
            {
                "role": "assistant",
                "content": "Use sk-live-secret for deployment",
            },
        ],
        "validation": {
            "summary": "Initial validation complete",
        },
        "activity_log": [
            "Created draft",
        ],
        "approved_models": ["claude-sonnet-4-5"],
        "workspace_paths": ["/tmp/workspace"],
        "companion_profile": {
            "id": "planner",
            "label": "Planner",
        },
        "draft_notes": [
            {
                "kind": "author",
                "text": "Keep YAML derived from canonical draft state",
            },
        ],
    }


def test_plan_draft_store_save_load_conflict_and_redaction(tmp_path, monkeypatch):
    agentforce_home = tmp_path / ".agentforce"
    drafts_dir = agentforce_home / "drafts"
    store = plan_drafts.PlanDraftStore(drafts_dir)
    created = store.create("draft-001", **_draft_payload())

    assert created.revision == 1
    assert created.to_dict()["id"] == "draft-001"
    assert created.to_dict()["revision"] == 1
    assert set(created.to_dict()) == {
        "id",
        "revision",
        "status",
        "name",
        "goal",
        "created_at",
        "updated_at",
        "draft_spec",
        "turns",
        "validation",
        "activity_log",
        "approved_models",
        "workspace_paths",
        "companion_profile",
        "draft_notes",
    }
    assert created.draft_notes[0]["text"] == "Keep YAML derived from canonical draft state"

    save_result = store.save(
        created.copy_with(
            turns=created.turns + [{"role": "assistant", "content": "Second pass"}],
        ),
        expected_revision=1,
    )

    assert save_result.status == "saved"
    assert save_result.draft is not None
    assert save_result.draft.revision == 2

    conflict_result = store.save(
        created.copy_with(status="approved"),
        expected_revision=1,
    )

    assert conflict_result.status == "conflict"
    assert conflict_result.draft is not None
    assert conflict_result.draft.revision == 2
    assert conflict_result.draft.status == "draft"

    draft_path = agentforce_home / "drafts" / "draft-001.json"
    persisted = json.loads(draft_path.read_text(encoding="utf-8"))

    assert "Bearer " not in persisted["turns"][0]["content"]
    assert "sk-" not in persisted["turns"][1]["content"]

    file_mode = stat.S_IMODE(draft_path.stat().st_mode)
    assert file_mode & stat.S_IROTH == 0
    assert file_mode & stat.S_IWOTH == 0
    assert file_mode & stat.S_IXOTH == 0


def test_plan_draft_store_allows_only_one_concurrent_writer_per_revision(tmp_path):
    drafts_dir = tmp_path / ".agentforce" / "drafts"
    store = plan_drafts.PlanDraftStore(drafts_dir)
    created = store.create("draft-locked", **_draft_payload())
    barrier = threading.Barrier(2)
    results: list[plan_drafts.DraftSaveResult] = []

    def save_copy(status: str) -> None:
        draft = created.copy_with(status=status)
        barrier.wait()
        results.append(store.save(draft, expected_revision=1))

    first = threading.Thread(target=save_copy, args=("reviewing",))
    second = threading.Thread(target=save_copy, args=("approved",))
    first.start()
    second.start()
    first.join()
    second.join()

    statuses = sorted(result.status for result in results)
    assert statuses == ["conflict", "saved"]
    latest = store.load("draft-locked")
    assert latest is not None
    assert latest.revision == 2
    assert latest.status in {"reviewing", "approved"}


def test_plan_draft_store_prunes_old_terminal_drafts(tmp_path, monkeypatch):
    agentforce_home = tmp_path / ".agentforce"
    drafts_dir = agentforce_home / "drafts"
    store = plan_drafts.PlanDraftStore(drafts_dir)
    draft = store.create("draft-old", **_draft_payload())
    finalized = store.save(
        draft.copy_with(status="finalized"),
        expected_revision=1,
    ).draft
    assert finalized is not None

    draft_path = agentforce_home / "drafts" / "draft-old.json"
    payload = json.loads(draft_path.read_text(encoding="utf-8"))
    payload["activity_log"] = [
        {"message": "Finalized", "timestamp": "2026-01-01T00:00:00+00:00"},
    ]
    draft_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    pruned = store.prune_expired(now="2026-02-15T00:00:00+00:00")

    assert pruned == ["draft-old"]
    assert draft_path.exists() is False


def test_plan_draft_helpers_use_default_home_redaction_and_retention(tmp_path, monkeypatch):
    agentforce_home = tmp_path / ".agentforce"
    monkeypatch.setattr(plan_drafts.state_io, "AGENTFORCE_HOME", agentforce_home)

    store = plan_drafts.PlanDraftStore()
    created = store.create("draft-default", **_draft_payload())

    draft_path = agentforce_home / "drafts" / "draft-default.json"
    assert draft_path.exists()

    drafts_dir_mode = stat.S_IMODE(draft_path.parent.stat().st_mode)
    assert drafts_dir_mode & stat.S_IROTH == 0
    assert drafts_dir_mode & stat.S_IWOTH == 0
    assert drafts_dir_mode & stat.S_IXOTH == 0

    redacted = plan_drafts.redact_persisted_content(
        {
            "turns": [
                {"role": "assistant", "content": "Bearer helper-secret"},
                {"role": "assistant", "content": "use sk-helper-secret"},
            ],
        }
    )
    assert "Bearer " not in redacted["turns"][0]["content"]
    assert "sk-" not in redacted["turns"][1]["content"]

    expired = plan_drafts.is_draft_expired(
        created.copy_with(status="finalized"),
        last_activity_at="2026-01-01T00:00:00+00:00",
        now="2026-02-15T00:00:00+00:00",
    )
    assert expired is True
