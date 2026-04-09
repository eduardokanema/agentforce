"""Tests for MissionSpec validation, including DoD vagueness checks."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from agentforce.core.spec import MissionSpec, TaskSpec, Caps, ValidationError, QualityIssues


def _minimal_spec(dod: list[str]) -> MissionSpec:
    return MissionSpec(
        name="Test Mission",
        goal="Do something useful",
        definition_of_done=dod,
        tasks=[TaskSpec(id="01", title="Task 1", description="Do work")],
        caps=Caps(),
    )


# ---------------------------------------------------------------------------
# dod_validation tests  (named so -k 'dod_validation' selects them)
# ---------------------------------------------------------------------------

def test_dod_validation_it_works():
    spec = _minimal_spec(["it works"])
    result = spec.validate_quality()
    assert result.dod_errors == ["it works"]


def test_dod_validation_done():
    spec = _minimal_spec(["done"])
    result = spec.validate_quality()
    assert result.dod_errors == ["done"]


def test_dod_validation_completed():
    spec = _minimal_spec(["completed"])
    result = spec.validate_quality()
    assert result.dod_errors == ["completed"]


def test_dod_validation_works_correctly():
    spec = _minimal_spec(["works correctly"])
    result = spec.validate_quality()
    assert result.dod_errors == ["works correctly"]


def test_dod_validation_fully_implemented():
    spec = _minimal_spec(["fully implemented"])
    result = spec.validate_quality()
    assert result.dod_errors == ["fully implemented"]


def test_dod_validation_case_insensitive():
    spec = _minimal_spec(["It Works"])
    result = spec.validate_quality()
    assert result.dod_errors == ["It Works"]


def test_dod_validation_with_punctuation():
    spec = _minimal_spec(["done."])
    result = spec.validate_quality()
    assert result.dod_errors == ["done."]


def test_dod_validation_multiple_vague_items():
    spec = _minimal_spec(["it works", "complete", "finished"])
    result = spec.validate_quality()
    assert set(result.dod_errors) == {"it works", "complete", "finished"}


def test_dod_validation_concrete_http_status_passes():
    spec = _minimal_spec(['GET /health returns HTTP 200 with {"status": "ok"}'])
    result = spec.validate_quality()
    assert result.dod_errors == []


def test_dod_validation_concrete_pytest_passes():
    spec = _minimal_spec(["pytest tests/ passes with exit code 0"])
    result = spec.validate_quality()
    assert result.dod_errors == []


def test_dod_validation_concrete_comparison_passes():
    spec = _minimal_spec(["response_time < 200ms"])
    result = spec.validate_quality()
    assert result.dod_errors == []


def test_dod_validation_concrete_quoted_value_passes():
    spec = _minimal_spec(['response body contains {"status": "ok"}'])
    result = spec.validate_quality()
    assert result.dod_errors == []


def test_dod_validation_mix_vague_and_concrete():
    spec = _minimal_spec(["it works", "GET /health returns 200"])
    result = spec.validate_quality()
    assert result.dod_errors == ["it works"]


def test_dod_validation_all_concrete_no_errors():
    spec = _minimal_spec(["binary exists at /usr/local/bin/myapp", "exit code == 0"])
    result = spec.validate_quality()
    assert result.dod_errors == []


def test_dod_validation_single_string_definition_of_done():
    spec = MissionSpec(
        name="Test Mission",
        goal="Do something useful",
        definition_of_done="done",
        tasks=[TaskSpec(id="01", title="Task 1", description="Do work")],
        caps=Caps(),
    )
    result = spec.validate_quality()
    assert result.dod_errors == ["done"]


# ---------------------------------------------------------------------------
# reviewer_prompt tests  (named so -k 'reviewer_prompt' selects them)
# ---------------------------------------------------------------------------

def _reviewer_prompt() -> str:
    spec = TaskSpec(
        id="01",
        title="Test Task",
        description="Do something",
        acceptance_criteria=["criterion 1"],
    )
    return spec.generate_reviewer_prompt(
        worker_output="output here",
        mission_name="Test Mission",
        dod="All criteria met",
    )


def test_reviewer_prompt_has_9th_dimension():
    prompt = _reviewer_prompt()
    assert "9." in prompt or "9)" in prompt


def test_reviewer_prompt_code_principles_heading():
    prompt = _reviewer_prompt()
    assert "CODE PRINCIPLES" in prompt


def test_reviewer_prompt_safety_first_with_fail_example():
    prompt = _reviewer_prompt()
    assert "Safety First" in prompt
    assert "API key" in prompt or "string literal" in prompt or "hardcoded" in prompt


def test_reviewer_prompt_yagni_with_fail_example():
    prompt = _reviewer_prompt()
    assert "YAGNI" in prompt
    assert "Caching" in prompt or "criterion requiring it" in prompt


def test_reviewer_prompt_occams_razor_with_fail_example():
    prompt = _reviewer_prompt()
    assert "Occam" in prompt
    assert "stdlib" in prompt or "libraries" in prompt


def test_reviewer_prompt_solid_srp_with_fail_example():
    prompt = _reviewer_prompt()
    assert "SOLID" in prompt or "SRP" in prompt
    assert "parsing" in prompt or "one reason" in prompt


def test_reviewer_prompt_dry_with_fail_example():
    prompt = _reviewer_prompt()
    assert "DRY" in prompt
    assert "reimplemented" in prompt or "imported" in prompt


def test_reviewer_prompt_millers_law_with_fail_example():
    prompt = _reviewer_prompt()
    assert "Miller" in prompt
    assert "parameters" in prompt or "params" in prompt


def test_reviewer_prompt_existing_8_dimensions_present():
    prompt = _reviewer_prompt()
    for label in ["SPEC COMPLIANCE", "ACCEPTANCE", "TDD", "QUALITY", "SECURITY",
                  "EDGE CASES", "SCOPE CREEP", "CONTRADICTIONS"]:
        assert label in prompt, f"Missing dimension: {label}"


def test_reviewer_prompt_code_principles_after_8_dimensions():
    prompt = _reviewer_prompt()
    last_of_8 = prompt.rfind("CONTRADICTIONS")
    ninth = prompt.find("CODE PRINCIPLES")
    assert last_of_8 != -1 and ninth != -1
    assert ninth > last_of_8


def test_reviewer_prompt_code_principles_score_anchors():
    prompt = _reviewer_prompt()
    assert "8 = Good: all 6 principles followed" in prompt
    assert "9 = Excellent: principles followed with notable care" in prompt
    assert "10 = Perfect: exemplary adherence; could be used as a reference" in prompt


# ---------------------------------------------------------------------------
# criteria_validation tests  (named so -k 'criteria_validation' selects them)
# ---------------------------------------------------------------------------

def _mission_with_tasks(tasks: list[TaskSpec]) -> MissionSpec:
    return MissionSpec(
        name="Test Mission",
        goal="Do something useful",
        definition_of_done=['GET /health returns HTTP 200 with {"status": "ok"}'],
        tasks=tasks,
        caps=Caps(),
    )


def test_criteria_validation_vague_only_words_exits_1():
    """Criterion with only vague words ('good error handling') is reported."""
    spec = _mission_with_tasks([
        TaskSpec(id="01", title="t", description="d",
                 acceptance_criteria=["good error handling"])
    ])
    issues = spec.validate_quality()
    assert len(issues.criteria_errors) == 1
    assert issues.criteria_errors[0].task_id == "01"
    assert issues.criteria_errors[0].criterion == "good error handling"


def test_criteria_validation_works_well_is_vague():
    """'works well' has no testable signal and should be flagged."""
    spec = _mission_with_tasks([
        TaskSpec(id="01", title="t", description="d",
                 acceptance_criteria=["works well"])
    ])
    issues = spec.validate_quality()
    assert len(issues.criteria_errors) == 1


def test_criteria_validation_empty_criteria_list_is_error():
    """A task with zero acceptance_criteria items is an error."""
    spec = _mission_with_tasks([
        TaskSpec(id="01", title="t", description="d", acceptance_criteria=[])
    ])
    issues = spec.validate_quality()
    assert len(issues.criteria_errors) == 1
    assert issues.criteria_errors[0].task_id == "01"


def test_criteria_validation_all_failures_reported_in_one_pass():
    """All vague criteria across all tasks are collected before returning."""
    spec = _mission_with_tasks([
        TaskSpec(id="01", title="t1", description="d",
                 acceptance_criteria=["works well", "clean code"]),
        TaskSpec(id="02", title="t2", description="d",
                 acceptance_criteria=["properly handles errors"]),
    ])
    issues = spec.validate_quality()
    task_ids = [e.task_id for e in issues.criteria_errors]
    assert "01" in task_ids
    assert "02" in task_ids
    assert len(issues.criteria_errors) == 3


def test_criteria_validation_http_code_passes():
    """Criterion referencing an HTTP status code is testable."""
    spec = _mission_with_tasks([
        TaskSpec(id="01", title="t", description="d",
                 acceptance_criteria=['Returns HTTP 400 with {"error": ...} for invalid input'])
    ])
    issues = spec.validate_quality()
    assert issues.criteria_errors == []


def test_criteria_validation_file_path_passes():
    """Criterion referencing a file path is testable."""
    spec = _mission_with_tasks([
        TaskSpec(id="01", title="t", description="d",
                 acceptance_criteria=["File /tmp/output.json exists and is non-empty"])
    ])
    issues = spec.validate_quality()
    assert issues.criteria_errors == []


def test_criteria_validation_comparison_operator_passes():
    """Criterion with a comparison operator is testable."""
    spec = _mission_with_tasks([
        TaskSpec(id="01", title="t", description="d",
                 acceptance_criteria=["Response time < 200ms"])
    ])
    issues = spec.validate_quality()
    assert issues.criteria_errors == []


def test_criteria_validation_pytest_command_passes():
    """Criterion referencing a test command is testable."""
    spec = _mission_with_tasks([
        TaskSpec(id="01", title="t", description="d",
                 acceptance_criteria=["pytest tests/ passes with 0 failures"])
    ])
    issues = spec.validate_quality()
    assert issues.criteria_errors == []


def test_criteria_validation_returns_quality_issues_type():
    """validate_quality() always returns a QualityIssues instance."""
    spec = _mission_with_tasks([
        TaskSpec(id="01", title="t", description="d",
                 acceptance_criteria=["Returns HTTP 200"])
    ])
    issues = spec.validate_quality()
    assert isinstance(issues, QualityIssues)
    assert isinstance(issues.criteria_errors, list)


def test_criteria_validation_empty_and_vague_reported_together():
    """Empty criteria and vague criteria across tasks are all reported."""
    spec = _mission_with_tasks([
        TaskSpec(id="01", title="t1", description="d", acceptance_criteria=[]),
        TaskSpec(id="02", title="t2", description="d",
                 acceptance_criteria=["nice output"]),
    ])
    issues = spec.validate_quality()
    task_ids = [e.task_id for e in issues.criteria_errors]
    assert "01" in task_ids
    assert "02" in task_ids


# ---------------------------------------------------------------------------
# suggest_caps tests  (named so -k 'suggest_caps' selects them)
# ---------------------------------------------------------------------------

def _mission_with_caps(
    *,
    task_count: int,
    max_concurrent_workers: int,
    max_retries_per_task: int,
    max_wall_time_minutes: int,
) -> MissionSpec:
    tasks = [
        TaskSpec(
            id=f"{i + 1:02d}",
            title=f"Task {i + 1}",
            description="Do work",
            acceptance_criteria=[f"Task {i + 1} returns HTTP 200"],
        )
        for i in range(task_count)
    ]
    return MissionSpec(
        name="Caps Mission",
        goal="Exercise cap suggestions",
        definition_of_done=['GET /health returns HTTP 200 with {"status": "ok"}'],
        tasks=tasks,
        caps=Caps(
            max_concurrent_workers=max_concurrent_workers,
            max_retries_per_task=max_retries_per_task,
            max_wall_time_minutes=max_wall_time_minutes,
        ),
    )


def test_suggest_caps_returns_worker_advisory_for_four_plus_tasks():
    from agentforce.core.spec import suggest_caps

    spec = _mission_with_caps(
        task_count=4,
        max_concurrent_workers=1,
        max_retries_per_task=2,
        max_wall_time_minutes=96,
    )

    suggestions = suggest_caps(spec)

    assert suggestions
    assert suggestions[0].field == "max_concurrent_workers"
    assert suggestions[0].current == 1
    assert suggestions[0].suggested == 2
    assert "4 tasks" in suggestions[0].reason


def test_suggest_caps_returns_empty_when_caps_already_sufficient():
    from agentforce.core.spec import suggest_caps

    spec = _mission_with_caps(
        task_count=4,
        max_concurrent_workers=2,
        max_retries_per_task=2,
        max_wall_time_minutes=96,
    )

    assert suggest_caps(spec) == []


def test_suggest_caps_cli_prints_advisory_and_exits_zero(tmp_path: Path):
    mission_path = tmp_path / "mission.yaml"
    mission_path.write_text(
        """
name: Caps Mission
goal: Exercise cap suggestions
definition_of_done:
  - 'GET /health returns HTTP 200 with {"status": "ok"}'
tasks:
  - id: "01"
    title: "Task 1"
    description: "Do work"
    acceptance_criteria:
      - "Returns HTTP 200"
  - id: "02"
    title: "Task 2"
    description: "Do work"
    acceptance_criteria:
      - "Returns HTTP 200"
  - id: "03"
    title: "Task 3"
    description: "Do work"
    acceptance_criteria:
      - "Returns HTTP 200"
  - id: "04"
    title: "Task 4"
    description: "Do work"
    acceptance_criteria:
      - "Returns HTTP 200"
caps:
  max_concurrent_workers: 1
  max_retries_per_task: 2
  max_wall_time_minutes: 96
""".strip()
    )

    result = subprocess.run(
        [sys.executable, "-m", "agentforce.cli.cli", "start", str(mission_path)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "[CAPS ADVISORY]" in result.stderr
