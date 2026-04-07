"""Spec-driven task model — formal specifications, acceptance criteria, and TDD enforcement."""
from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional
import hashlib
from datetime import datetime, timezone


class TaskStatus(str, Enum):
    PENDING = "pending"
    SPEC_WRITING = "spec_writing"
    TESTS_WRITTEN = "tests_written"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REVIEWING = "reviewing"
    REVIEW_APPROVED = "review_approved"
    REVIEW_REJECTED = "review_rejected"
    NEEDS_HUMAN = "needs_human"
    RETRY = "retry"
    FAILED = "failed"
    BLOCKED = "blocked"


class CapType(str, Enum):
    MAX_TOKENS = "max_tokens"
    MAX_RETRIES = "max_retries"
    MAX_WALL_TIME = "max_wall_time"
    MAX_INTERVENTIONS = "max_interventions"
    MAX_COST_USD = "max_cost_usd"


@dataclass
class TDDSpec:
    """Test-Driven Development requirements for a task."""
    test_file: Optional[str] = None          # e.g., "tests/test_health.py"
    test_command: Optional[str] = None       # e.g., "pytest tests/test_health.py -v"
    tests_must_pass: bool = True
    coverage_threshold: Optional[float] = None  # e.g., 80.0 for 80%

    def to_dict(self) -> dict:
        return {
            "test_file": self.test_file,
            "test_command": self.test_command,
            "tests_must_pass": self.tests_must_pass,
            "coverage_threshold": self.coverage_threshold,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TDDSpec:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class TaskSpec:
    """A single task's specification — the atomic unit of work."""
    id: str
    title: str
    description: str
    acceptance_criteria: list[str] = field(default_factory=list)
    tdd: Optional[TDDSpec] = None
    dependencies: list[str] = field(default_factory=list)  # task IDs that must complete first
    working_dir: Optional[str] = None        # Relative path within mission workdir
    max_retries: int = 3
    output_artifacts: list[str] = field(default_factory=list)  # Expected file paths

    def generate_worker_prompt(self) -> str:
        """Generate a structured prompt for the worker agent."""
        tdd_section = ""
        if self.tdd:
            tdd_section = f"""
TDD REQUIREMENTS (MUST FOLLOW):
1. First, write a FAILING test in {self.tdd.test_file}
2. Run: {self.tdd.test_command} (verify it FAILS)
3. Implement the minimum code to make tests pass
4. Run: {self.tdd.test_command} (verify it PASSES)
5. Refactor and re-run to confirm
"""
            if self.tdd.coverage_threshold:
                tdd_section += f"6. Ensure test coverage >= {self.tdd.coverage_threshold}%"

        deps = f"\nDEPENDENCIES: Complete tasks {', '.join(self.dependencies)} first and review their output." if self.dependencies else ""

        return f"""TASK SPEC: {self.id} - {self.title}

DESCRIPTION:
{self.description}

ACCEPTANCE CRITERIA (ALL must be met):
{chr(10).join(f'  - {c}' for c in self.acceptance_criteria)}
{tdd_section}{deps}

OUTPUT EXPECTED:
Report which files you created/modified and how each acceptance criterion was met.
"""

    def generate_reviewer_prompt(self, worker_output: str, mission_name: str, dod: str, project_memory: str = "") -> str:
        """Generate a structured prompt for the external reviewer."""
        proj_mem = f"\nPROJECT MEMORY:\n{project_memory}" if project_memory else ""

        return f"""EXTERNAL REVIEW — Task {self.id}: {self.title}

MISSION: {mission_name}
Definition of Done: {dod}
{proj_mem}

TASK SPECIFICATION:
{self.description}

ACCEPTANCE CRITERIA:
{chr(10).join(f'  - {c}' for c in self.acceptance_criteria)}

WORKER OUTPUT:
{worker_output}

REVIEW CHECKLIST:
1. [SPEC COMPLIANCE] Does the implementation match the task description?
2. [ACCEPTANCE] Are ALL acceptance criteria met? Verify each one.
3. [TDD] Were tests written? Do they pass? Is the test approach reasonable?
4. [QUALITY] Code quality, error handling, naming, style consistency?
5. [SECURITY] Any vulnerabilities, exposed secrets, unsafe patterns?
6. [EDGE CASES] Unhandled edge cases or missing input validation?
7. [SCOPE CREEP] Did the worker add things not in the spec?
8. [CONTRADICTIONS] Anything that contradicts the mission goal or DoD?

RESPOND WITH VALID JSON ONLY:
{{
  "approved": true/false,
  "score": 1-10,
  "feedback": "Detailed explanation",
  "criteria_results": {{
    "criterion_1_text": "met/partial/met/unclear",
    ...
  }},
  "blocking_issues": ["list of must-fix issues if rejected"],
  "suggestions": ["non-blocking improvements"]
}}
"""

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "acceptance_criteria": self.acceptance_criteria,
            "dependencies": self.dependencies,
            "working_dir": self.working_dir,
            "max_retries": self.max_retries,
            "output_artifacts": self.output_artifacts,
        }
        if self.tdd:
            d["tdd"] = self.tdd.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> TaskSpec:
        tdd = TDDSpec.from_dict(d.pop("tdd", {})) if d.get("tdd") else None
        # Pop fields we're extracting explicitly
        fields = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        if tdd:
            fields["tdd"] = tdd
        return cls(**fields)


@dataclass
class Caps:
    """Guard rails for the mission execution."""
    max_tokens_per_task: int = 100_000
    max_retries_global: int = 3
    max_retries_per_task: int = 3
    max_wall_time_minutes: int = 120
    max_human_interventions: int = 2
    max_cost_usd: Optional[float] = None
    max_concurrent_workers: int = 3

    def to_dict(self) -> dict:
        return {
            "max_tokens_per_task": self.max_tokens_per_task,
            "max_retries_global": self.max_retries_global,
            "max_retries_per_task": self.max_retries_per_task,
            "max_wall_time_minutes": self.max_wall_time_minutes,
            "max_human_interventions": self.max_human_interventions,
            "max_cost_usd": self.max_cost_usd,
            "max_concurrent_workers": self.max_concurrent_workers,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Caps:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class MissionSpec:
    """Complete mission specification — the input to the orchestrator."""
    name: str
    goal: str
    definition_of_done: list[str]
    tasks: list[TaskSpec]
    caps: Caps = field(default_factory=Caps)
    working_dir: Optional[str] = None         # Root working directory for the mission
    project_memory_file: Optional[str] = None # Path to project memory file

    @classmethod
    def load_yaml(cls, path: Path | str) -> MissionSpec:
        """Load mission spec from a YAML file."""
        path = Path(path)
        with open(path) as f:
            raw = yaml.safe_load(f)
        return cls.from_dict(raw)

    @classmethod
    def load_json(cls, path: Path | str) -> MissionSpec:
        """Load mission spec from a JSON file."""
        import json
        path = Path(path)
        with open(path) as f:
            raw = json.load(f)
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, d: dict) -> MissionSpec:
        mission_raw = d.get("mission", d)
        task_defs = d.get("tasks", mission_raw.pop("tasks", []))
        caps_raw = mission_raw.pop("caps", {})
        
        tasks = []
        for i, td in enumerate(task_defs):
            td_with_defaults = {
                "id": td.get("id", f"{i+1:02d}"),
                "title": td.get("title", f"Task {i+1}"),
                "description": td.get("description", ""),
                "acceptance_criteria": td.get("acceptance_criteria", []),
                "tdd": TDDSpec.from_dict(td.get("tdd", {})) if td.get("tdd") else None,
                "dependencies": td.get("dependencies", []),
                "working_dir": td.get("working_dir"),
                "max_retries": td.get("max_retries", 3),
                "output_artifacts": td.get("output_artifacts", []),
            }
            tasks.append(TaskSpec(**td_with_defaults))

        caps = Caps.from_dict(caps_raw)
        
        spec_raw = {k: v for k, v in mission_raw.items() if k in cls.__dataclass_fields__}
        spec_raw["tasks"] = tasks
        spec_raw["caps"] = caps
        
        return cls(**spec_raw)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "goal": self.goal,
            "definition_of_done": self.definition_of_done,
            "caps": self.caps.to_dict(),
            "working_dir": self.working_dir,
            "project_memory_file": self.project_memory_file,
            "tasks": [t.to_dict() for t in self.tasks],
        }

    def validate(self) -> list[str]:
        """Validate the mission spec. Returns list of issues (empty = valid)."""
        issues = []
        if not self.name:
            issues.append("Mission name is required")
        if not self.goal:
            issues.append("Mission goal is required")
        if not self.definition_of_done:
            issues.append("Definition of Done must have at least one criterion")
        if not self.tasks:
            issues.append("At least one task is required")
        
        task_ids = set()
        for t in self.tasks:
            if t.id in task_ids:
                issues.append(f"Duplicate task ID: {t.id}")
            task_ids.add(t.id)
            for dep in t.dependencies:
                if dep not in task_ids and not any(tid == dep for tid in [t.id for t in self.tasks]):
                    # Only warn if the dep doesn't exist anywhere
                    pass  # Will catch this in dependency validation
        
        # Validate dependency graph
        all_ids = {t.id for t in self.tasks}
        for t in self.tasks:
            for dep in t.dependencies:
                if dep not in all_ids:
                    issues.append(f"Task {t.id} depends on unknown task: {dep}")
        
        # Check for circular dependencies
        visited = set()
        in_stack = set()
        def has_cycle(tid):
            if tid in in_stack:
                return True
            if tid in visited:
                return False
            in_stack.add(tid)
            task_map = {t.id: t for t in self.tasks}
            if tid in task_map:
                for dep in task_map[tid].dependencies:
                    if has_cycle(dep):
                        return True
            in_stack.remove(tid)
            visited.add(tid)
            return False
        
        for t in self.tasks:
            if has_cycle(t.id):
                issues.append("Circular dependency detected in task graph")
                break
        
        return issues

    def short_id(self) -> str:
        return hashlib.md5(f"{self.name}-{self.goal}".encode()).hexdigest()[:8]
