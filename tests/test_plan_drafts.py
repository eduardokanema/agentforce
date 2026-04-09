from __future__ import annotations

import json
import stat
import threading

from agentforce.server import plan_drafts


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
