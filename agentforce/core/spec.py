"""Spec-driven task model — formal specifications, acceptance criteria, and TDD enforcement."""
from __future__ import annotations

import re
import yaml
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional
import hashlib
import os
from datetime import datetime, timezone


DOD_VAGUE_PHRASES = frozenset([
    "it works", "works correctly", "works properly", "works well",
    "done", "complete", "completed", "finished", "implemented",
    "fully implemented", "properly implemented", "feature complete",
])

_MEASURABLE_PATTERNS = [
    re.compile(r'\b[1-5]\d{2}\b'),                                              # HTTP status codes
    re.compile(r'[<>]=?|=='),                                                   # comparison operators
    re.compile(r'["\']'),                                                       # quoted values
    re.compile(r'[\w./]+/[\w./]+'),                                             # file paths
    re.compile(r'\bpytest\b|\bbin\b|\bexit\s+code\b', re.IGNORECASE),          # commands
]


CRITERIA_VAGUE_WORDS = [
    "good", "well", "nice", "clean", "fast", "better", "improve",
    "properly", "correctly", "works", "appropriate", "reasonable",
    "efficient", "clear", "simple", "robust", "stable",
]

_CRITERIA_TESTABLE_PATTERNS = [
    re.compile(r'\b[1-5]\d{2}\b'),                                              # HTTP status codes
    re.compile(r'[<>]=?|==|!='),                                                # comparison operators
    re.compile(r'["\'].+["\']'),                                                # quoted values
    re.compile(r'[\w./]+/[\w./]+'),                                             # file paths
    re.compile(r'\b(pytest|npm test|make test|go test|cargo test|assert)\b'),  # test commands
]


@dataclass
class ValidationError:
    """A single acceptance-criteria quality violation."""
    task_id: str
    criterion: str
    reason: str


@dataclass
class QualityIssues:
    dod_errors: list[str] = field(default_factory=list)
    criteria_errors: list[ValidationError] = field(default_factory=list)


@dataclass
class CapsSuggestion:
    """Recommended cap adjustment for a mission spec."""
    field: str
    current: int | float
    suggested: int | float
    reason: str


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
class ExecutionProfile:
    """Runtime execution settings for one role."""
    agent: Optional[str] = None
    model: Optional[str] = None
    thinking: Optional[str] = None

    def configured(self) -> bool:
        return any([self.agent, self.model, self.thinking])

    def merged(self, defaults: Optional[ExecutionProfile]) -> ExecutionProfile:
        if defaults is None:
            return ExecutionProfile(agent=self.agent, model=self.model, thinking=self.thinking)
        return ExecutionProfile(
            agent=self.agent or defaults.agent,
            model=self.model or defaults.model,
            thinking=self.thinking or defaults.thinking,
        )

    def to_dict(self) -> dict:
        data = {}
        if self.agent is not None:
            data["agent"] = self.agent
        if self.model is not None:
            data["model"] = self.model
        if self.thinking is not None:
            data["thinking"] = self.thinking
        return data

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> Optional[ExecutionProfile]:
        if not d:
            return None
        fields = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        profile = cls(**fields)
        return profile if profile.configured() else None


@dataclass
class ExecutionConfig:
    """Worker/reviewer execution settings."""
    worker: Optional[ExecutionProfile] = None
    reviewer: Optional[ExecutionProfile] = None

    def to_dict(self) -> dict:
        data = {}
        if self.worker and self.worker.configured():
            data["worker"] = self.worker.to_dict()
        if self.reviewer and self.reviewer.configured():
            data["reviewer"] = self.reviewer.to_dict()
        return data

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> ExecutionConfig:
        if not d:
            return cls()
        return cls(
            worker=ExecutionProfile.from_dict(d.get("worker")),
            reviewer=ExecutionProfile.from_dict(d.get("reviewer")),
        )


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
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    model: Optional[str] = None

    def __post_init__(self) -> None:
        worker = self.execution.worker
        if self.model:
            if worker is None:
                worker = ExecutionProfile(model=self.model)
            elif not worker.model:
                worker.model = self.model
        if worker and worker.configured():
            self.execution.worker = worker
            self.model = worker.model
        else:
            self.execution.worker = None
            self.model = None

    def generate_worker_prompt(self) -> str:
        """Generate a structured prompt for the worker agent."""
        principles_section = """CODE PRINCIPLES (apply in this priority order):
  1. Safety First — no hardcoded credentials; explicit error handling
  2. YAGNI — implement only what the task requires; nothing speculative
  3. Occam's Razor — simplest solution that satisfies acceptance criteria
  4. SOLID/SRP — one reason to change; one concern per function/module
  5. DRY — no duplicated logic; reuse existing utilities
  6. Miller's Law — max 7 items per grouping; max 5 params per function

"""
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

        return principles_section + f"""TASK SPEC: {self.id} - {self.title}

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
        artifact_lines = (
            "\n".join(f"  \u25a1 {a} \u2014 exists / non-empty / parseable" for a in self.output_artifacts)
            if self.output_artifacts else "  (no output_artifacts specified)"
        )

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
9. [CODE PRINCIPLES] Are the 6 code principles followed?
   □ Safety First: No hardcoded credentials; secrets via env vars only
       FAIL example: API key string literal in task output → score < 7
   □ YAGNI: Implementation contains only what acceptance criteria require
       FAIL example: Caching added with no criterion requiring it → score < 8
   □ Occam's Razor: Simplest implementation that satisfies all criteria
       FAIL example: 3 libraries used where stdlib suffices → score < 8
   □ SOLID/SRP: Each function/class has one reason to change
       FAIL example: Function handles both parsing AND writing → score < 8
   □ DRY: No duplicated logic; reuses existing utilities
       FAIL example: fmt_duration reimplemented instead of imported → score < 8
   □ Miller's Law: Functions have ≤5 parameters; modules ≤7 public methods
       FAIL example: Function with 8 parameters → score < 8

SCORE ANCHORS:
  8 = Good: all 6 principles followed
  9 = Excellent: principles followed with notable care (e.g. extracted utility)
  10 = Perfect: exemplary adherence; could be used as a reference

ARTIFACT VERIFICATION:
{artifact_lines}
  If any artifact is missing or empty: score Quality dimension < 7.

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
        execution = self.execution.to_dict()
        if execution:
            d["execution"] = execution
        if self.tdd:
            d["tdd"] = self.tdd.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> TaskSpec:
        raw = dict(d)
        tdd = TDDSpec.from_dict(raw.pop("tdd", {})) if raw.get("tdd") else None
        execution = ExecutionConfig.from_dict(raw.get("execution"))
        # Pop fields we're extracting explicitly
        fields = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        if tdd:
            fields["tdd"] = tdd
        fields["execution"] = execution
        fields["model"] = raw.get("model")
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
    review: str = "enabled"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Caps) and self.to_dict() == other.to_dict()

    def to_dict(self) -> dict:
        return {
            "max_tokens_per_task": self.max_tokens_per_task,
            "max_retries_global": self.max_retries_global,
            "max_retries_per_task": self.max_retries_per_task,
            "max_wall_time_minutes": self.max_wall_time_minutes,
            "max_human_interventions": self.max_human_interventions,
            "max_cost_usd": self.max_cost_usd,
            "max_concurrent_workers": self.max_concurrent_workers,
            "review": self.review,
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
    execution_defaults: ExecutionConfig = field(default_factory=ExecutionConfig)
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
        execution_defaults_raw = mission_raw.pop("execution_defaults", {})
        
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
                "execution": ExecutionConfig.from_dict(td.get("execution")),
                "model": td.get("model"),
            }
            tasks.append(TaskSpec(**td_with_defaults))

        caps = Caps.from_dict(caps_raw)
        execution_defaults = ExecutionConfig.from_dict(execution_defaults_raw)
        
        spec_raw = {k: v for k, v in mission_raw.items() if k in cls.__dataclass_fields__}
        spec_raw["tasks"] = tasks
        spec_raw["caps"] = caps
        spec_raw["execution_defaults"] = execution_defaults
        
        return cls(**spec_raw)

    def to_dict(self) -> dict:
        data = {
            "name": self.name,
            "goal": self.goal,
            "definition_of_done": self.definition_of_done,
            "caps": self.caps.to_dict(),
            "working_dir": self.working_dir,
            "project_memory_file": self.project_memory_file,
            "tasks": [t.to_dict() for t in self.tasks],
        }
        execution_defaults = self.execution_defaults.to_dict()
        if execution_defaults:
            data["execution_defaults"] = execution_defaults
        return data

    def validate(
        self,
        stage: str = "launch",
        worker_model_override: Optional[str] = None,
        reviewer_model_override: Optional[str] = None,
    ) -> list[str]:
        """Validate the mission spec. Launch blocks incomplete execution profiles."""
        if stage != "launch":
            return []

        issues = []
        if not self.name.strip():
            issues.append("Mission name is required")
        if not self.goal.strip():
            issues.append("Mission goal is required")
        if not self.definition_of_done:
            issues.append("Definition of Done must have at least one criterion")
        for index, item in enumerate(self.definition_of_done, start=1):
            if not str(item).strip():
                issues.append(f"Definition of Done item {index} is required")
                break
        if not self.tasks:
            issues.append("At least one task is required")
        
        task_ids = set()
        for t in self.tasks:
            if t.id in task_ids:
                issues.append(f"Duplicate task ID: {t.id}")
            task_ids.add(t.id)
            if not t.title.strip():
                issues.append(f"task {t.id} title is required")
            if not t.description.strip():
                issues.append(f"task {t.id} description is required")
            if not t.acceptance_criteria:
                issues.append(f"task {t.id} acceptance criteria are required")
            for index, criterion in enumerate(t.acceptance_criteria, start=1):
                if not str(criterion).strip():
                    issues.append(f"task {t.id} acceptance criterion {index} is required")
                    break
            for dep in t.dependencies:
                if not str(dep).strip():
                    issues.append(f"Task {t.id} depends on unknown task: {dep}")
                    continue
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

        if stage == "launch":
            issues.extend(
                self._validate_execution_profiles(
                    worker_model_override=worker_model_override,
                    reviewer_model_override=reviewer_model_override,
                )
            )
        
        return issues

    def resolve_execution_profile(
        self,
        task: TaskSpec,
        role: str,
        mission_defaults: Optional[ExecutionConfig] = None,
        cli_default: Optional[ExecutionProfile] = None,
        runtime_fallback: Optional[ExecutionProfile] = None,
    ) -> Optional[ExecutionProfile]:
        default_config = mission_defaults or self.execution_defaults
        task_profile = getattr(task.execution, role)
        default_profile = getattr(default_config, role)
        if task_profile and task_profile.configured():
            resolved = task_profile.merged(default_profile)
        elif default_profile and default_profile.configured():
            resolved = default_profile
        else:
            resolved = None

        if cli_default and cli_default.configured():
            resolved = cli_default if resolved is None else resolved.merged(cli_default)
        if runtime_fallback and runtime_fallback.configured():
            resolved = runtime_fallback if resolved is None else resolved.merged(runtime_fallback)
        return resolved

    def effective_execution_profile(self, task: TaskSpec, role: str) -> Optional[ExecutionProfile]:
        return self.resolve_execution_profile(task, role)

    def _validate_execution_profiles(
        self,
        worker_model_override: Optional[str] = None,
        reviewer_model_override: Optional[str] = None,
    ) -> list[str]:
        issues: list[str] = []
        for task in self.tasks:
            raw_worker = task.execution.worker or self.execution_defaults.worker
            if raw_worker and raw_worker.configured():
                effective_worker = self.effective_execution_profile(task, "worker")
                if effective_worker and worker_model_override and not effective_worker.model:
                    effective_worker = ExecutionProfile(
                        agent=effective_worker.agent,
                        model=worker_model_override,
                        thinking=effective_worker.thinking,
                    )
                issues.extend(
                    self._validate_execution_profile(
                        effective_worker,
                        f"task {task.id} worker execution",
                    )
                )
            raw_reviewer = task.execution.reviewer or self.execution_defaults.reviewer
            if raw_reviewer and raw_reviewer.configured():
                effective_reviewer = self.effective_execution_profile(task, "reviewer")
                if effective_reviewer and reviewer_model_override and not effective_reviewer.model:
                    effective_reviewer = ExecutionProfile(
                        agent=effective_reviewer.agent,
                        model=reviewer_model_override,
                        thinking=effective_reviewer.thinking,
                    )
                issues.extend(
                    self._validate_execution_profile(
                        effective_reviewer,
                        f"task {task.id} reviewer execution",
                    )
                )
        return issues

    @staticmethod
    def _validate_execution_profile(profile: Optional[ExecutionProfile], label: str) -> list[str]:
        if not profile or not profile.configured():
            return []
        issues: list[str] = []
        if not profile.agent:
            issues.append(f"{label} is missing agent")
        if not profile.model:
            issues.append(f"{label} is missing model")
        return issues

    def validate_quality(self) -> QualityIssues:
        """Check DoD items and task criteria for vague language. Returns QualityIssues."""
        dod_errors: list[str] = []
        dod_items = self.definition_of_done
        if isinstance(dod_items, str):
            dod_items = [dod_items]

        for item in dod_items:
            normalized = re.sub(r'[^\w\s]', ' ', item).strip().lower()
            has_measurable_signal = any(pattern.search(item) for pattern in _MEASURABLE_PATTERNS)
            has_vague_phrase = any(
                re.search(rf"\b{re.escape(phrase)}\b", normalized)
                for phrase in DOD_VAGUE_PHRASES
            )
            if has_vague_phrase and not has_measurable_signal:
                dod_errors.append(item)
                continue

        criteria_errors: list[ValidationError] = []
        for task in self.tasks:
            if not task.acceptance_criteria:
                criteria_errors.append(ValidationError(
                    task_id=task.id,
                    criterion="",
                    reason="Empty acceptance_criteria list — must have at least one criterion",
                ))
                continue
            for criterion in task.acceptance_criteria:
                if not any(p.search(criterion) for p in _CRITERIA_TESTABLE_PATTERNS):
                    criteria_errors.append(ValidationError(
                        task_id=task.id,
                        criterion=criterion,
                        reason="Criterion is too vague — no testable signal (HTTP code, file path, comparison, quoted value, or test command)",
                    ))

        return QualityIssues(dod_errors=dod_errors, criteria_errors=criteria_errors)

    def short_id(self) -> str:
        return hashlib.md5(f"{self.name}-{self.goal}".encode()).hexdigest()[:8]


def suggest_caps(spec: MissionSpec) -> list[CapsSuggestion]:
    """Return advisory cap suggestions based on mission size and retry budget."""
    suggestions: list[CapsSuggestion] = []
    task_count = len(spec.tasks)

    if task_count >= 4 and spec.caps.max_concurrent_workers < 2:
        suggestions.append(CapsSuggestion(
            field="max_concurrent_workers",
            current=spec.caps.max_concurrent_workers,
            suggested=2,
            reason=f"{task_count} tasks: increase to 2 workers for parallel execution",
        ))
    if task_count <= 2 and spec.caps.max_concurrent_workers > 2:
        suggestions.append(CapsSuggestion(
            field="max_concurrent_workers",
            current=spec.caps.max_concurrent_workers,
            suggested=1,
            reason=f"Only {task_count} tasks: 1 worker is sufficient",
        ))

    min_wall_time = task_count * 8 * (spec.caps.max_retries_per_task + 1)
    if spec.caps.max_wall_time_minutes < min_wall_time:
        suggestions.append(CapsSuggestion(
            field="max_wall_time_minutes",
            current=spec.caps.max_wall_time_minutes,
            suggested=min_wall_time,
            reason=(
                f"{task_count} tasks × {spec.caps.max_retries_per_task + 1} passes × "
                f"8 min = {min_wall_time} min minimum"
            ),
        ))

    if spec.caps.max_retries_per_task == 0:
        suggestions.append(CapsSuggestion(
            field="max_retries_per_task",
            current=0,
            suggested=2,
            reason="0 retries means any single failure halts the task permanently",
        ))

    return suggestions
