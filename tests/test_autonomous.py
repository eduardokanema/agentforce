"""Tests for TokenLedger wiring and session caching in autonomous.py."""
import json
import pytest

from agentforce.core.token_ledger import TokenLedger


# ---------------------------------------------------------------------------
# Reviewer session caching tests
# ---------------------------------------------------------------------------

def test_reviewer_session_id_none_on_first_call():
    """Reviewer gets no session_id until a connector returns a real one."""
    from agentforce.autonomous import _get_or_create_session_id

    session_ids = {}
    sid = _get_or_create_session_id(session_ids, "task-1", "reviewer")
    assert sid is None


def test_reviewer_session_id_not_registered_before_first_result():
    """Reviewer session_id is not fabricated before a connector returns one."""
    from agentforce.autonomous import _get_or_create_session_id

    session_ids = {}
    sid = _get_or_create_session_id(session_ids, "task-1", "reviewer")
    assert sid is None
    assert "task-1_reviewer" not in session_ids


def test_reviewer_session_id_reused_across_calls():
    """Same stored reviewer session_id is returned on subsequent calls."""
    from agentforce.autonomous import _get_or_create_session_id

    session_ids = {"task-1_reviewer": "review-thread-123"}
    sid1 = _get_or_create_session_id(session_ids, "task-1", "reviewer")
    sid2 = _get_or_create_session_id(session_ids, "task-1", "reviewer")
    assert sid1 == sid2


def test_reviewer_session_ids_are_task_scoped():
    """Different tasks get different reviewer session_ids."""
    from agentforce.autonomous import _get_or_create_session_id

    session_ids = {
        "task-1_reviewer": "review-thread-123",
        "task-2_reviewer": "review-thread-456",
    }
    sid_a = _get_or_create_session_id(session_ids, "task-1", "reviewer")
    sid_b = _get_or_create_session_id(session_ids, "task-2", "reviewer")
    assert sid_a != sid_b


def test_worker_session_id_none_on_first_call():
    """Worker still gets None session_id when not yet in session_ids dict."""
    from agentforce.autonomous import _get_or_create_session_id

    session_ids = {}
    sid = _get_or_create_session_id(session_ids, "task-1", "worker")
    assert sid is None


def test_worker_session_id_reused_when_present():
    """Worker gets its stored session_id on subsequent calls."""
    from agentforce.autonomous import _get_or_create_session_id

    session_ids = {"task-1": "stored-worker-sid"}
    sid = _get_or_create_session_id(session_ids, "task-1", "worker")
    assert sid == "stored-worker-sid"


def _usage_line(tokens_in: int, tokens_out: int, cost_usd: float) -> str:
    return json.dumps({"type": "usage", "input_tokens": tokens_in, "output_tokens": tokens_out, "cost_usd": cost_usd})


def test_token_ledger_record_usage_parses_output():
    """_record_usage extracts usage lines from agent output and accumulates in ledger."""
    from agentforce.autonomous import _record_usage

    ledger = TokenLedger()
    output = "some output\nnoise line\n" + _usage_line(100, 50, 0.01)

    _record_usage(ledger, "task-1", output)

    totals = ledger.task_totals("task-1")
    assert totals["tokens_in"] == 100
    assert totals["tokens_out"] == 50
    assert totals["cost_usd"] == pytest.approx(0.01)


def test_token_ledger_record_usage_no_lines():
    """_record_usage with no usage lines leaves ledger at zero."""
    from agentforce.autonomous import _record_usage

    ledger = TokenLedger()
    _record_usage(ledger, "task-1", "no usage data here")

    totals = ledger.task_totals("task-1")
    assert totals["tokens_in"] == 0
    assert totals["tokens_out"] == 0
    assert totals["cost_usd"] == 0.0


def test_token_ledger_single_instance_accumulates():
    """A single ledger instance accumulates across multiple calls (not reset per task)."""
    from agentforce.autonomous import _record_usage

    ledger = TokenLedger()

    _record_usage(ledger, "task-1", _usage_line(10, 5, 0.001))
    _record_usage(ledger, "task-1", _usage_line(20, 10, 0.002))  # second call — same task, same ledger
    _record_usage(ledger, "task-2", _usage_line(30, 15, 0.003))

    t1 = ledger.task_totals("task-1")
    assert t1["tokens_in"] == 30  # accumulated across both calls
    assert t1["tokens_out"] == 15
    assert t1["cost_usd"] == pytest.approx(0.003)

    t2 = ledger.task_totals("task-2")
    assert t2["tokens_in"] == 30

    mt = ledger.mission_totals()
    assert mt["tokens_in"] == 60
    assert mt["cost_usd"] == pytest.approx(0.006)


def test_token_ledger_multiple_usage_lines_in_output():
    """Multiple usage lines in a single output are all parsed and summed."""
    from agentforce.autonomous import _record_usage

    ledger = TokenLedger()
    output = "\n".join([
        "line before",
        _usage_line(10, 5, 0.001),
        "middle line",
        _usage_line(20, 10, 0.002),
    ])

    _record_usage(ledger, "task-1", output)

    totals = ledger.task_totals("task-1")
    assert totals["tokens_in"] == 30
    assert totals["tokens_out"] == 15
    assert totals["cost_usd"] == pytest.approx(0.003)


def test_autonomous_prefers_resolved_delegation_model_over_cli_default(tmp_path, monkeypatch):
    """A resolved per-delegation model must win over the mission-global CLI model."""
    from agentforce.autonomous import run_autonomous
    from agentforce.core.engine import WorkerDelegation
    from agentforce.core.spec import ExecutionConfig, ExecutionProfile, MissionSpec, TaskSpec
    from agentforce.core.state import MissionState, TaskState

    mission_id = "mission-model-precedence"
    state_root = tmp_path / ".agentforce" / "state"
    memory_root = tmp_path / ".agentforce" / "memory"
    state_root.mkdir(parents=True, exist_ok=True)
    memory_root.mkdir(parents=True, exist_ok=True)

    spec = MissionSpec(
        name="Autonomous precedence",
        goal="Keep per-delegation model",
        definition_of_done=["done"],
        tasks=[
            TaskSpec(
                id="01",
                title="Task",
                description="Do it",
                acceptance_criteria=["done"],
                execution=ExecutionConfig(
                    worker=ExecutionProfile(agent="codex", model="task-model", thinking="high"),
                ),
            )
        ],
    )
    state = MissionState(mission_id=mission_id, spec=spec, working_dir=str(tmp_path))
    state.task_states["01"] = TaskState(task_id="01")
    state_file = state_root / f"{mission_id}.json"
    state.save(state_file)

    monkeypatch.setattr("agentforce.autonomous.Path.home", lambda: tmp_path)
    monkeypatch.setattr("agentforce.autonomous._ensure_pkg", lambda: tmp_path)
    monkeypatch.setattr("agentforce.autonomous._detect_agent", lambda: "codex")

    captured = {}

    def fake_run_agent(prompt, workdir, timeout=300, agent="auto", model=None, stream_path=None, variant=None, session_id=None):
        captured["agent"] = agent
        captured["model"] = model
        captured["variant"] = variant
        return True, "worker ok", "", "session-1", None

    monkeypatch.setattr("agentforce.autonomous._run_agent", fake_run_agent)

    def fake_apply_worker_result(self, task_id, success, output="", error=""):
        self.state.task_states[task_id].status = "review_approved"

    monkeypatch.setattr("agentforce.core.engine.MissionEngine.apply_worker_result", fake_apply_worker_result)

    run_autonomous(
        mission_id,
        workdir=str(tmp_path),
        agent="codex",
        model="cli-model",
        variant="cli-thinking",
        max_ticks=3,
    )

    assert captured["agent"] == "codex"
    assert captured["model"] == "task-model"
    assert captured["variant"] == "high"


# ---------------------------------------------------------------------------
# Hard-block tests (security / TDD per-criterion blocking)
# ---------------------------------------------------------------------------

def _make_task_state(retries: int = 0):
    from agentforce.core.state import TaskState
    ts = TaskState(task_id="t1")
    ts.retries = retries
    return ts


def test_hard_block_security_score_below_threshold():
    """Security score < 7 sets task status to NEEDS_HUMAN with HARD BLOCK message."""
    from agentforce.autonomous import _apply_hard_blocks
    from agentforce.core.spec import TaskStatus

    ts = _make_task_state(retries=2)
    review = {"approved": True, "score": 9, "scores": {"security": 5, "tdd": 8}}

    blocked = _apply_hard_blocks(review, ts)

    assert blocked is True
    assert ts.status == TaskStatus.NEEDS_HUMAN
    assert "HARD BLOCK" in ts.hard_block_reason
    assert "Security" in ts.hard_block_reason
    assert "5" in ts.hard_block_reason


def test_hard_block_security_does_not_consume_retry():
    """Hard-blocked tasks do not consume a retry slot (retries unchanged)."""
    from agentforce.autonomous import _apply_hard_blocks

    ts = _make_task_state(retries=3)
    review = {"approved": True, "score": 9, "scores": {"security": 6, "tdd": 8}}

    _apply_hard_blocks(review, ts)

    assert ts.retries == 3  # must remain unchanged


def test_hard_block_tdd_score_below_threshold():
    """TDD score < 7 sets task status to NEEDS_HUMAN with HARD BLOCK message."""
    from agentforce.autonomous import _apply_hard_blocks
    from agentforce.core.spec import TaskStatus

    ts = _make_task_state(retries=1)
    review = {"approved": True, "score": 9, "scores": {"security": 9, "tdd": 4}}

    blocked = _apply_hard_blocks(review, ts)

    assert blocked is True
    assert ts.status == TaskStatus.NEEDS_HUMAN
    assert "HARD BLOCK" in ts.hard_block_reason
    assert "TDD" in ts.hard_block_reason
    assert "4" in ts.hard_block_reason
    assert ts.retries == 1  # unchanged


def test_hard_block_not_triggered_at_threshold():
    """Scores exactly at 7 do NOT trigger a hard block."""
    from agentforce.autonomous import _apply_hard_blocks
    from agentforce.core.spec import TaskStatus

    ts = _make_task_state()
    review = {"approved": True, "score": 9, "scores": {"security": 7, "tdd": 7}}

    blocked = _apply_hard_blocks(review, ts)

    assert blocked is False
    assert ts.status == TaskStatus.PENDING
    assert ts.hard_block_reason is None


def test_hard_block_not_triggered_above_threshold():
    """Scores above 7 do NOT trigger a hard block."""
    from agentforce.autonomous import _apply_hard_blocks

    ts = _make_task_state()
    review = {"approved": False, "score": 6, "scores": {"security": 8, "tdd": 9}}

    blocked = _apply_hard_blocks(review, ts)

    assert blocked is False


def test_hard_block_defaults_to_10_on_missing_scores():
    """Missing 'scores' key defaults to 10 — no false-positive hard block."""
    from agentforce.autonomous import _apply_hard_blocks

    ts = _make_task_state()
    review = {"approved": True, "score": 9}  # no 'scores' key

    blocked = _apply_hard_blocks(review, ts)

    assert blocked is False


def test_hard_block_defaults_to_10_on_invalid_score_values():
    """Malformed score values default to 10 instead of hard-blocking or crashing."""
    from agentforce.autonomous import _apply_hard_blocks
    from agentforce.core.spec import TaskStatus

    ts = _make_task_state(retries=2)
    review = {
        "approved": True,
        "score": 9,
        "scores": {"security": "oops", "tdd": None},
    }

    blocked = _apply_hard_blocks(review, ts)

    assert blocked is False
    assert ts.status == TaskStatus.PENDING
    assert ts.hard_block_reason is None
    assert ts.retries == 2


def test_hard_block_security_fires_before_tdd():
    """When both dimensions are below threshold, security fires first."""
    from agentforce.autonomous import _apply_hard_blocks

    ts = _make_task_state()
    review = {"approved": True, "score": 9, "scores": {"security": 3, "tdd": 2}}

    _apply_hard_blocks(review, ts)

    assert "Security" in ts.hard_block_reason


def test_review_threshold_scores_above_7_proceed_normally():
    """When security and TDD are both >= 7, _apply_hard_blocks returns False."""
    from agentforce.autonomous import _apply_hard_blocks
    from agentforce.core.spec import TaskStatus

    ts = _make_task_state()
    review = {"approved": True, "score": 9, "scores": {"security": 7, "tdd": 10}}

    blocked = _apply_hard_blocks(review, ts)

    assert blocked is False
    assert ts.status == TaskStatus.PENDING
