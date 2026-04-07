"""Tests for the spec model."""
import json
import pytest
import yaml
import sys
from pathlib import Path

# Ensure imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from agentforce.core.spec import (
    MissionSpec, TaskSpec, TDDSpec, Caps, MissionSpec, TaskStatus
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
