from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_project_harness_docs_tree_exists() -> None:
    required_paths = [
        ROOT / "ARCHITECTURE.md",
        ROOT / "docs" / "index.md",
        ROOT / "docs" / "product" / "project-harness-v1.md",
        ROOT / "docs" / "contracts" / "project-harness.md",
        ROOT / "docs" / "workflows" / "project-cycle.md",
        ROOT / "docs" / "quality" / "verification-catalog.md",
        ROOT / "docs" / "decisions" / "0001-project-harness-derived-first.md",
        ROOT / "docs" / "runbooks" / "project-harness-smoke.md",
        ROOT / "docs" / "status" / "implemented-vs-planned.md",
        ROOT / "docs" / "generated" / "README.md",
        ROOT / "plans" / "active" / "agentforce-project-harness-v1.md",
        ROOT / "specs" / "project-harness-v1.md",
    ]

    missing = [path.relative_to(ROOT).as_posix() for path in required_paths if not path.exists()]
    assert missing == []


def test_docs_index_links_point_to_real_files() -> None:
    index_text = (ROOT / "docs" / "index.md").read_text(encoding="utf-8")
    linked_paths = [
        "product/project-harness-v1.md",
        "contracts/project-harness.md",
        "workflows/project-cycle.md",
        "quality/verification-catalog.md",
        "decisions/0001-project-harness-derived-first.md",
        "runbooks/project-harness-smoke.md",
        "status/implemented-vs-planned.md",
        "generated/README.md",
    ]

    for relative_path in linked_paths:
        assert relative_path in index_text
        assert (ROOT / "docs" / relative_path).exists()
