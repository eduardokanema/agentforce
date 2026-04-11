"""Tests for the spec model."""
import json
import pytest
import yaml
import sys
from pathlib import Path

# Ensure imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from agentforce.core.spec import (
    MissionSpec, TaskSpec, TDDSpec, Caps, MissionSpec, TaskStatus,
    ValidationError, QualityIssues,
)


class TestTDDSpec:
    def test_from_dict(self):
        tdd = TDDSpec.from_dict({
            "test_file": "tests/test_auth.py",
            "test_command": "pytest tests/ -v",
            "tests_must_pass": True,
            "coverage_threshold": 80.0,
        })
        assert tdd.test_file == "tests/test_auth.py"
        assert tdd.test_command == "pytest tests/ -v"
        assert tdd.coverage_threshold == 80.0

    def test_defaults(self):
        tdd = TDDSpec.from_dict({})
        assert tdd.test_file is None
        assert tdd.tests_must_pass is True


class TestTaskSpec:
    def test_worker_prompt_contains_requirements(self):
        spec = TaskSpec(
            id="01",
            title="Health endpoint",
            description="Create GET /health returning 200 OK",
            acceptance_criteria=["Returns 200", "Response has status field"],
        )
        prompt = spec.generate_worker_prompt()
        assert "01" in prompt
        assert "Health endpoint" in prompt
        assert "Returns 200" in prompt

    def test_worker_prompt_with_tdd(self):
        spec = TaskSpec(
            id="01",
            title="Health endpoint",
            description="Create GET /health",
            tdd=TDDSpec(test_file="tests/test_health.py", test_command="pytest tests/test_health.py -v"),
        )
        prompt = spec.generate_worker_prompt()
        assert "FAILING test" in prompt
        assert "tests/test_health.py" in prompt
        assert "pytest tests/test_health.py -v" in prompt

    def test_reviewer_prompt_acceptance_criteria(self):
        spec = TaskSpec(
            id="01",
            title="Tests",
            description="Write tests",
            acceptance_criteria=["All pass", "80% coverage"],
        )
        prompt = spec.generate_reviewer_prompt(
            worker_output="Created 5 tests",
            mission_name="Test mission",
            dod="Everything works"
        )
        assert "SPEC COMPLIANCE" in prompt
        assert "ACCEPTANCE" in prompt
        assert "All pass" in prompt
        assert "80% coverage" in prompt

    def test_worker_prompt_code_principles_present_in_order(self):
        spec = TaskSpec(
            id="01",
            title="Health endpoint",
            description="Create GET /health returning 200 OK",
            acceptance_criteria=["Returns 200"],
        )
        prompt = spec.generate_worker_prompt()
        for keyword in ["Safety First", "YAGNI", "Occam", "SOLID", "DRY", "Miller"]:
            assert keyword in prompt, f"Expected '{keyword}' in worker prompt"
        positions = [prompt.index(k) for k in ["Safety First", "YAGNI", "Occam", "SOLID", "DRY", "Miller"]]
        assert positions == sorted(positions), "Principles must appear in priority order"

    def test_worker_prompt_principles_before_task_context(self):
        spec = TaskSpec(
            id="01",
            title="Health endpoint",
            description="Create GET /health returning 200 OK",
            acceptance_criteria=["Returns 200"],
        )
        prompt = spec.generate_worker_prompt()
        principles_pos = prompt.index("Safety First")
        task_context_pos = prompt.index("TASK SPEC:")
        assert principles_pos < task_context_pos, "Principles section must appear before TASK SPEC block"

    def test_worker_prompt_principles_instruction_not_in_reviewer_prompt(self):
        """Worker CODE PRINCIPLES instruction header must not bleed into reviewer prompt."""
        spec = TaskSpec(
            id="01",
            title="Health endpoint",
            description="Create GET /health returning 200 OK",
            acceptance_criteria=["Returns 200"],
        )
        reviewer_prompt = spec.generate_reviewer_prompt(
            worker_output="done",
            mission_name="Test",
            dod="Works"
        )
        # The worker-instructions preamble must not appear; the 9th checklist dimension may.
        assert "apply in this priority order" not in reviewer_prompt, \
            "Worker CODE PRINCIPLES instruction header must not appear in reviewer prompt"

    def test_worker_prompt_existing_sections_unchanged(self):
        spec = TaskSpec(
            id="42",
            title="My Task",
            description="Do the thing",
            acceptance_criteria=["It works", "Tests pass"],
            tdd=TDDSpec(test_file="tests/test_foo.py", test_command="pytest tests/test_foo.py -v"),
        )
        prompt = spec.generate_worker_prompt()
        assert "TASK SPEC: 42 - My Task" in prompt
        assert "ACCEPTANCE CRITERIA" in prompt
        assert "It works" in prompt
        assert "Tests pass" in prompt
        assert "TDD REQUIREMENTS" in prompt
        assert "OUTPUT EXPECTED" in prompt

    def test_to_dict_roundtrip(self):
        spec = TaskSpec(
            id="01",
            title="Test task",
            description="Do something",
            acceptance_criteria=["It works"],
            dependencies=[],
            max_retries=5,
        )
        d = spec.to_dict()
        restored = TaskSpec.from_dict(d)
        assert restored.id == "01"
        assert restored.title == "Test task"
        assert restored.max_retries == 5


class TestCaps:
    def test_defaults(self):
        caps = Caps()
        assert caps.max_tokens_per_task == 100_000
        assert caps.max_retries_global == 3
        assert caps.max_concurrent_workers == 3

    def test_from_dict(self):
        caps = Caps.from_dict({"max_concurrent_workers": 5, "max_wall_time_minutes": 30})
        assert caps.max_concurrent_workers == 5
        assert caps.max_wall_time_minutes == 30


class TestMissionSpec:
    def test_load_minimal_json(self, tmp_path):
        spec_data = {
            "name": "Test",
            "goal": "Test goal",
            "definition_of_done": ["It works"],
            "tasks": [
                {"id": "01", "title": "Task 1", "description": "Do thing"}
            ]
        }
        f = tmp_path / "spec.json"
        f.write_text(json.dumps(spec_data))
        spec = MissionSpec.load_json(f)
        assert spec.name == "Test"
        assert len(spec.tasks) == 1
        assert spec.tasks[0].id == "01"

    def test_load_yaml(self, tmp_path):
        spec_data = {
            "mission": {
                "name": "YAML Test",
                "goal": "YAML goal",
                "definition_of_done": ["Works", "Tests pass"],
            },
            "tasks": [
                {
                    "id": "01",
                    "title": "YAML Task",
                    "description": "Do YAML thing",
                    "acceptance_criteria": ["Output exists"],
                }
            ]
        }
        f = tmp_path / "spec.yaml"
        f.write_text(json.dumps(spec_data))  # Just for testing; real YAML would be yaml.dump
        # Actually write proper YAML
        f.write_text(yaml.dump(spec_data))
        spec = MissionSpec.load_yaml(f)
        assert spec.name == "YAML Test"
        assert len(spec.tasks) == 1

    def test_validate_empty_name(self):
        spec = MissionSpec(name="", goal="g", definition_of_done=["d"], tasks=[])
        issues = spec.validate()
        assert any("name" in i for i in issues)

    def test_validate_missing_dod(self):
        spec = MissionSpec(
            name="Test",
            goal="goal",
            definition_of_done=[],
            tasks=[TaskSpec(id="01", title="t", description="d")]
        )
        issues = spec.validate()
        assert any("Definition of Done" in i for i in issues)

    def test_validate_duplicate_task_ids(self):
        spec = MissionSpec(
            name="Test",
            goal="goal",
            definition_of_done=["done"],
            tasks=[
                TaskSpec(id="01", title="t1", description="d"),
                TaskSpec(id="01", title="t2", description="d"),
            ]
        )
        issues = spec.validate()
        assert any("Duplicate" in i for i in issues)

    def test_short_id_is_consistent(self):
        spec = MissionSpec(
            name="Test",
            goal="goal",
            definition_of_done=["done"],
            tasks=[TaskSpec(id="01", title="t", description="d")]
        )
        id1 = spec.short_id()
        id2 = spec.short_id()
        assert id1 == id2
        assert len(id1) == 8

    def test_load_json_missing_required(self):
        with pytest.raises(TypeError):
            MissionSpec.from_dict({})  # Missing name, goal, etc.


class TestReviewerPromptBARSAndArtifacts:
    """Tests for BARS score anchors and artifact verification in reviewer prompt."""

    def _make_spec(self, output_artifacts=None):
        return TaskSpec(
            id="01",
            title="Test task",
            description="Do something",
            acceptance_criteria=["It works"],
            output_artifacts=output_artifacts or [],
        )

    def test_bars_anchor_8_good(self):
        prompt = self._make_spec().generate_reviewer_prompt(
            worker_output="done", mission_name="M", dod="D"
        )
        assert "8 = Good" in prompt

    def test_bars_anchor_9_excellent(self):
        prompt = self._make_spec().generate_reviewer_prompt(
            worker_output="done", mission_name="M", dod="D"
        )
        assert "9 = Excellent" in prompt

    def test_bars_anchor_10_perfect(self):
        prompt = self._make_spec().generate_reviewer_prompt(
            worker_output="done", mission_name="M", dod="D"
        )
        assert "10 = Perfect" in prompt

    def test_artifact_verification_checklist_present(self):
        spec = self._make_spec(output_artifacts=["agentforce/core/spec.py"])
        prompt = spec.generate_reviewer_prompt(
            worker_output="done", mission_name="M", dod="D"
        )
        assert "artifact" in prompt.lower()
        assert "agentforce/core/spec.py" in prompt

    def test_artifact_low_score_rule_present(self):
        prompt = self._make_spec().generate_reviewer_prompt(
            worker_output="done", mission_name="M", dod="D"
        )
        assert "< 7" in prompt

    def test_scope_guardrails_limit_review_to_current_task(self):
        prompt = self._make_spec().generate_reviewer_prompt(
            worker_output="done", mission_name="M", dod="D"
        )
        assert "Judge ONLY this task's description" in prompt
        assert "Do NOT reject this task for artifacts" in prompt
        assert "later dependent tasks" in prompt

    def test_all_8_existing_dimensions_present(self):
        prompt = self._make_spec().generate_reviewer_prompt(
            worker_output="done", mission_name="M", dod="D"
        )
        for dimension in [
            "SPEC COMPLIANCE", "ACCEPTANCE", "TDD", "QUALITY",
            "SECURITY", "EDGE CASES", "SCOPE CREEP", "CONTRADICTIONS",
        ]:
            assert dimension in prompt, f"Missing dimension: {dimension}"


class TestReviewerPromptCodePrinciples:
    """Tests for the 9th reviewer checklist dimension: Code Principles."""

    def _make_spec(self):
        return TaskSpec(
            id="01",
            title="Test task",
            description="Do something",
            acceptance_criteria=["It works"],
        )

    def test_reviewer_prompt_has_9th_dimension_heading(self):
        prompt = self._make_spec().generate_reviewer_prompt(
            worker_output="done", mission_name="M", dod="D"
        )
        assert "9." in prompt or "9)" in prompt, "Missing 9th dimension heading"

    def test_reviewer_prompt_code_principles_dimension_present(self):
        prompt = self._make_spec().generate_reviewer_prompt(
            worker_output="done", mission_name="M", dod="D"
        )
        assert "CODE PRINCIPLES" in prompt

    def test_reviewer_prompt_all_6_principles_present(self):
        prompt = self._make_spec().generate_reviewer_prompt(
            worker_output="done", mission_name="M", dod="D"
        )
        for principle in ["Safety First", "YAGNI", "Occam's Razor", "SOLID/SRP", "DRY", "Miller's Law"]:
            assert principle in prompt, f"Missing principle: {principle}"

    def test_reviewer_prompt_all_6_fail_examples_present(self):
        prompt = self._make_spec().generate_reviewer_prompt(
            worker_output="done", mission_name="M", dod="D"
        )
        # Each principle must have a FAIL example with a score anchor
        fail_examples = [
            "API key string literal",
            "Caching added with no criterion",
            "3 libraries used where stdlib",
            "handles both parsing AND writing",
            "fmt_duration reimplemented",
            "Function with 8 parameters",
        ]
        for example in fail_examples:
            assert example in prompt, f"Missing FAIL example: {example}"

    def test_reviewer_prompt_code_principles_after_8_dimensions(self):
        prompt = self._make_spec().generate_reviewer_prompt(
            worker_output="done", mission_name="M", dod="D"
        )
        contradictions_pos = prompt.index("CONTRADICTIONS")
        code_principles_pos = prompt.index("CODE PRINCIPLES")
        assert code_principles_pos > contradictions_pos, \
            "CODE PRINCIPLES must appear after CONTRADICTIONS (8th dimension)"

    def test_reviewer_prompt_8_dimensions_unmodified(self):
        prompt = self._make_spec().generate_reviewer_prompt(
            worker_output="done", mission_name="M", dod="D"
        )
        # Verify exact numbering of existing dimensions
        assert "1. [SPEC COMPLIANCE]" in prompt
        assert "2. [ACCEPTANCE]" in prompt
        assert "3. [TDD]" in prompt
        assert "4. [QUALITY]" in prompt
        assert "5. [SECURITY]" in prompt
        assert "6. [EDGE CASES]" in prompt
        assert "7. [SCOPE CREEP]" in prompt
        assert "8. [CONTRADICTIONS]" in prompt


class TestCriteriaValidation:
    """Tests for validate_quality() acceptance criteria vagueness checks."""

    def _make_mission(self, tasks):
        return MissionSpec(
            name="Test", goal="goal", definition_of_done=["done"], tasks=tasks
        )

    def test_criteria_validation_vague_criterion_reported(self):
        spec = self._make_mission([
            TaskSpec(id="01", title="t", description="d",
                     acceptance_criteria=["good error handling"])
        ])
        issues = spec.validate_quality()
        assert len(issues.criteria_errors) == 1
        assert issues.criteria_errors[0].task_id == "01"
        assert "vague" in issues.criteria_errors[0].reason.lower()

    def test_criteria_validation_empty_criteria_list_is_error(self):
        spec = self._make_mission([
            TaskSpec(id="01", title="t", description="d", acceptance_criteria=[])
        ])
        issues = spec.validate_quality()
        assert len(issues.criteria_errors) == 1
        assert issues.criteria_errors[0].task_id == "01"

    def test_criteria_validation_all_failures_reported_in_one_pass(self):
        spec = self._make_mission([
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

    def test_criteria_validation_testable_criteria_pass(self):
        spec = self._make_mission([
            TaskSpec(id="01", title="t", description="d", acceptance_criteria=[
                'Returns HTTP 400 with {"error": ...} for invalid input',
                "File /tmp/output.json exists and is non-empty",
                "Response time < 200ms",
                "pytest tests/ passes with 0 failures",
            ])
        ])
        issues = spec.validate_quality()
        assert issues.criteria_errors == []

    def test_criteria_validation_works_well_is_vague(self):
        spec = self._make_mission([
            TaskSpec(id="01", title="t", description="d",
                     acceptance_criteria=["works well"])
        ])
        issues = spec.validate_quality()
        assert len(issues.criteria_errors) == 1

    def test_criteria_validation_empty_and_vague_reported_together(self):
        spec = self._make_mission([
            TaskSpec(id="01", title="t1", description="d", acceptance_criteria=[]),
            TaskSpec(id="02", title="t2", description="d",
                     acceptance_criteria=["nice output"]),
        ])
        issues = spec.validate_quality()
        task_ids = [e.task_id for e in issues.criteria_errors]
        assert "01" in task_ids
        assert "02" in task_ids

    def test_criteria_validation_returns_quality_issues_type(self):
        spec = self._make_mission([
            TaskSpec(id="01", title="t", description="d",
                     acceptance_criteria=["Returns HTTP 200 on success"])
        ])
        issues = spec.validate_quality()
        assert isinstance(issues, QualityIssues)
        assert isinstance(issues.criteria_errors, list)

    def test_criteria_validation_error_has_criterion_text(self):
        spec = self._make_mission([
            TaskSpec(id="01", title="t", description="d",
                     acceptance_criteria=["works well"])
        ])
        issues = spec.validate_quality()
        assert issues.criteria_errors[0].criterion == "works well"
