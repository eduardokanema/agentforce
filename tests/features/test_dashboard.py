"""BDD tests for the AgentForce mission dashboard."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pytest_bdd import given, scenarios, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from agentforce.core.spec import Caps, MissionSpec, TaskSpec
from agentforce.core.state import EventLogEntry, MissionState, TaskState
from agentforce.server import render_mission_detail, render_mission_list, render_task_detail

scenarios("dashboard.feature")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _spec(name: str = "Test Mission", tasks: list | None = None) -> MissionSpec:
    tasks = tasks or [TaskSpec(id="t1", title="Task One", description="Do it")]
    return MissionSpec(
        name=name,
        goal="Test goal",
        definition_of_done=["All tasks approved"],
        tasks=tasks,
        caps=Caps(),
    )


def _state(
    mission_id: str = "abc123",
    spec: MissionSpec | None = None,
    task_states: dict | None = None,
    event_log: list | None = None,
) -> MissionState:
    return MissionState(
        mission_id=mission_id,
        spec=spec or _spec(),
        task_states=task_states or {},
        event_log=event_log or [],
        started_at="2024-01-01T10:00:00+00:00",
    )


def _task(task_id: str, status: str, **kwargs) -> TaskState:
    return TaskState(task_id=task_id, spec_summary=f"Summary of {task_id}", status=status, **kwargs)


# ── Scenario: Listing all missions ────────────────────────────────────────────

@given("two missions exist", target_fixture="missions")
def two_missions_exist():
    m1 = _state("alpha01", spec=_spec("Alpha Mission"), task_states={"t1": _task("t1", "review_approved")})
    m2 = _state("beta02", spec=_spec("Beta Mission"), task_states={"t1": _task("t1", "in_progress")})
    return [m1, m2]


@when("I render the mission list", target_fixture="page")
def render_list(missions):
    return render_mission_list(missions)


@then("the page contains both mission IDs")
def page_has_mission_ids(page):
    assert "alpha01" in page
    assert "beta02" in page


@then("the page contains each mission status badge")
def page_has_status_badges(page):
    assert "complete" in page   # alpha01 — all tasks approved
    assert "active" in page     # beta02 — in progress


# ── Scenario: Viewing a mission with tasks in various states ──────────────────

@given("a mission with tasks in pending, in_progress, and review_approved states", target_fixture="state")
def mission_with_mixed_tasks():
    tasks = [
        TaskSpec(id="t1", title="Task One", description="First"),
        TaskSpec(id="t2", title="Task Two", description="Second"),
        TaskSpec(id="t3", title="Task Three", description="Third"),
    ]
    spec = _spec("Mixed Mission", tasks=tasks)
    task_states = {
        "t1": _task("t1", "review_approved"),
        "t2": _task("t2", "in_progress"),
        "t3": _task("t3", "pending"),
    }
    events = [
        EventLogEntry(timestamp="2024-01-01T10:01:00+00:00", event_type="task_dispatched", task_id="t1", details="Worker dispatched"),
        EventLogEntry(timestamp="2024-01-01T10:05:00+00:00", event_type="review_approved", task_id="t1", details="Score: 9"),
    ]
    return _state("mix999", spec=spec, task_states=task_states, event_log=events)


@when("I render the mission detail page", target_fixture="page")
def render_detail(state):
    return render_mission_detail(state)


@then("I see each task listed with its status")
def page_has_all_tasks(page):
    assert "Task One" in page
    assert "Task Two" in page
    assert "Task Three" in page
    assert "review_approved" in page.replace("-", "_")
    assert "in_progress" in page.replace("-", "_")
    assert "pending" in page


@then("I see the progress stats showing 1 of 3 tasks approved")
def page_shows_progress(page):
    assert "1 / 3" in page


# ── Scenario: Viewing a reviewed and approved task ────────────────────────────

@given("a task has been reviewed and approved with score 8", target_fixture="state")
def task_approved_score_8():
    tasks = [TaskSpec(id="t1", title="Implement API", description="Build the endpoint")]
    spec = _spec("API Mission", tasks=tasks)
    task_states = {
        "t1": _task(
            "t1", "review_approved",
            worker_output="Created endpoint /health with status 200",
            review_feedback="Well implemented. Tests pass, coverage 95%.",
            review_score=8,
        )
    }
    return _state("api001", spec=spec, task_states=task_states)


@when("I render the task detail page", target_fixture="page")
def render_task(state):
    return render_task_detail(state, "t1")


@then("I see the review score 8")
def page_shows_score(page):
    assert "8/10" in page


@then("I see the reviewer feedback text")
def page_shows_feedback(page):
    assert "Tests pass, coverage 95%" in page


@then("I see the worker output")
def page_shows_worker_output(page):
    assert "Created endpoint /health" in page


# ── Scenario: Rejected task shows blocking issues ─────────────────────────────

@given("a task was rejected with blocking issues", target_fixture="state")
def task_rejected_with_issues():
    tasks = [TaskSpec(id="t1", title="Add auth", description="Implement JWT auth")]
    spec = _spec("Auth Mission", tasks=tasks)
    task_states = {
        "t1": _task(
            "t1", "review_rejected",
            review_feedback="Missing token expiry handling.",
            review_score=4,
            blocking_issues=["Token expiry not implemented", "No refresh token logic"],
        )
    }
    return _state("auth01", spec=spec, task_states=task_states)


@then("I see the review_rejected status")
def page_shows_rejected_status(page):
    assert "review" in page and "rejected" in page


@then("I see each blocking issue listed")
def page_shows_blocking_issues(page):
    assert "Token expiry not implemented" in page
    assert "No refresh token logic" in page


# ── Scenario: Mission progress fraction is visible ────────────────────────────

@given("a mission has 3 approved tasks and 2 pending tasks", target_fixture="state")
def mission_with_progress():
    tasks = [TaskSpec(id=f"t{i}", title=f"Task {i}", description="...") for i in range(1, 6)]
    spec = _spec("Progress Mission", tasks=tasks)
    task_states = {
        "t1": _task("t1", "review_approved"),
        "t2": _task("t2", "review_approved"),
        "t3": _task("t3", "review_approved"),
        "t4": _task("t4", "pending"),
        "t5": _task("t5", "pending"),
    }
    return _state("prog01", spec=spec, task_states=task_states)


@then("I see 3 of 5 tasks in the stats")
def page_shows_3_of_5(page):
    assert "3 / 5" in page
