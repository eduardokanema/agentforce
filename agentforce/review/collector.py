from __future__ import annotations

from datetime import datetime
from statistics import mean

from agentforce.core.spec import TaskStatus
from agentforce.review.models import GoodhartWarning, MetricsSnapshot
from agentforce.review.schemas import MissionReviewPayloadV1


class MetricsCollector:
    @staticmethod
    def _status_value(status: object) -> str:
        return status.value if hasattr(status, "value") else str(status)

    @staticmethod
    def _parse_iso(ts: str) -> datetime:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))

    @staticmethod
    def collect(payload: MissionReviewPayloadV1) -> MetricsSnapshot:
        """Extract metrics from the stable review payload."""
        total_tasks = len(payload.tasks)

        tasks_completed = sum(
            1 for task in payload.tasks if task.status == TaskStatus.REVIEW_APPROVED.value
        )
        first_pass = sum(
            1
            for task in payload.tasks
            if task.status == TaskStatus.REVIEW_APPROVED.value and task.retries == 0
        )

        review_scores = [
            task.review_score
            for task in payload.tasks
            if task.review_score > 0
            and task.status in {
                TaskStatus.REVIEW_APPROVED.value,
                TaskStatus.FAILED.value,
            }
        ]

        total_retries = payload.total_retries
        total_human_interventions = payload.total_human_interventions
        total_cost_usd = payload.total_cost_usd
        total_tokens_out = payload.total_tokens_out

        total_wall_time_s = 0.0
        wall_time_task_count = 0
        for task in payload.tasks:
            if not task.started_at or not task.completed_at:
                continue
            started = MetricsCollector._parse_iso(task.started_at)
            completed = MetricsCollector._parse_iso(task.completed_at)
            total_wall_time_s += (completed - started).total_seconds()
            wall_time_task_count += 1

        review_event_approved = sum(1 for event in payload.event_log if event.event_type == "review_approved")
        review_event_rejected = sum(1 for event in payload.event_log if event.event_type == "review_rejected")
        review_event_total = review_event_approved + review_event_rejected
        review_rejection_rate = (
            review_event_rejected / review_event_total if review_event_total > 0 else 0.0
        )

        data_quality_warnings: list[str] = []
        if len(review_scores) < 2:
            data_quality_warnings.append("fewer than two tasks have review scores")

        if total_tasks == 0 or tasks_completed == 0:
            snapshot = MetricsSnapshot(
                mission_id=payload.mission_id,
                token_efficiency=0.0,
                first_pass_rate=0.0,
                rework_rate=0.0,
                avg_review_score=0.0,
                human_escalation_rate=0.0,
                wall_time_per_task_s=0.0,
                cost_per_task_usd=0.0,
                review_rejection_rate=review_rejection_rate,
                quality_score=0.0,
                efficiency_gated=None,
                data_quality_warnings=data_quality_warnings,
                tasks_completed=tasks_completed,
                tasks_total=total_tasks,
                total_retries=total_retries,
                total_human_interventions=total_human_interventions,
                total_cost_usd=total_cost_usd,
                total_tokens_out=total_tokens_out,
                total_wall_time_s=total_wall_time_s,
            )
            snapshot.quality_score = 0.0
            snapshot.efficiency_gated = None
            return snapshot

        avg_review_score = mean(review_scores) if review_scores else 0.0
        first_pass_rate = first_pass / total_tasks if total_tasks > 0 else 0.0
        rework_rate = total_retries / total_tasks if total_tasks > 0 else 0.0
        human_escalation_rate = total_human_interventions / total_tasks if total_tasks > 0 else 0.0

        if wall_time_task_count > 0:
            wall_time_per_task_s = total_wall_time_s / tasks_completed
        else:
            wall_time_per_task_s = 0.0

        task_costs = sum(task.cost_usd for task in payload.tasks)
        if task_costs > 0:
            cost_per_task_usd = task_costs / tasks_completed
        else:
            cost_per_task_usd = payload.total_cost_usd / tasks_completed if tasks_completed > 0 else 0.0

        task_tokens = sum(task.tokens_out for task in payload.tasks)
        if task_tokens > 0:
            token_efficiency = task_tokens / tasks_completed
        else:
            token_efficiency = payload.total_tokens_out / tasks_completed if tasks_completed > 0 else 0.0
            data_quality_warnings.append("per-task token fields are zero; using mission-level fallback")

        quality_score = MetricsCollector.compute_quality_score(
            avg_review_score,
            first_pass_rate,
            human_escalation_rate,
        )
        efficiency_gated = MetricsCollector.gate_efficiency(token_efficiency, quality_score)

        return MetricsSnapshot(
            mission_id=payload.mission_id,
            token_efficiency=token_efficiency,
            first_pass_rate=first_pass_rate,
            rework_rate=rework_rate,
            avg_review_score=avg_review_score,
            human_escalation_rate=human_escalation_rate,
            wall_time_per_task_s=wall_time_per_task_s,
            cost_per_task_usd=cost_per_task_usd,
            review_rejection_rate=review_rejection_rate,
            quality_score=quality_score,
            efficiency_gated=efficiency_gated,
            data_quality_warnings=data_quality_warnings,
            tasks_completed=tasks_completed,
            tasks_total=total_tasks,
            total_retries=total_retries,
            total_human_interventions=total_human_interventions,
            total_cost_usd=total_cost_usd,
            total_tokens_out=total_tokens_out,
            total_wall_time_s=total_wall_time_s,
        )

    @staticmethod
    def compute_quality_score(
        avg_review_score: float,
        first_pass_rate: float,
        human_escalation_rate: float,
    ) -> float:
        """Composite quality score on a 0-10 scale."""
        return (
            ((avg_review_score / 10) * 0.4)
            + (first_pass_rate * 0.25)
            + ((1 - human_escalation_rate) * 0.3)
        ) * 10

    @staticmethod
    def gate_efficiency(token_efficiency: float, quality_score: float) -> float | None:
        """Return token_efficiency only if quality_score >= 7.0, else None."""
        return token_efficiency if quality_score >= 7.0 else None

    @staticmethod
    def _improved_downward(baseline: float, current: float, threshold: float = 0.02) -> bool:
        return baseline > 0 and current < baseline * (1 - threshold)

    @staticmethod
    def _improved_upward(baseline: float, current: float, threshold: float = 0.02) -> bool:
        return baseline > 0 and current > baseline * (1 + threshold)

    @staticmethod
    def detect_goodhart(
        current: MetricsSnapshot,
        baseline: MetricsSnapshot,
    ) -> list[GoodhartWarning]:
        """Compare current metrics against a baseline and emit Goodhart warnings."""
        warnings: list[GoodhartWarning] = []

        if MetricsCollector._improved_downward(baseline.token_efficiency, current.token_efficiency) and (
            current.quality_score < baseline.quality_score * 0.98
        ):
            warnings.append(
                GoodhartWarning(
                    metric_name="token_efficiency",
                    metric_direction="decreased",
                    quality_direction="decreased",
                    message="Token efficiency improved but quality dropped",
                    baseline_quality=baseline.quality_score,
                    current_quality=current.quality_score,
                    baseline_metric=baseline.token_efficiency,
                    current_metric=current.token_efficiency,
                )
            )

        if MetricsCollector._improved_downward(baseline.cost_per_task_usd, current.cost_per_task_usd) and (
            current.avg_review_score < baseline.avg_review_score * 0.98
        ):
            warnings.append(
                GoodhartWarning(
                    metric_name="cost_per_task_usd",
                    metric_direction="decreased",
                    quality_direction="decreased",
                    message="Cost per task improved but average review score dropped",
                    baseline_quality=baseline.avg_review_score,
                    current_quality=current.avg_review_score,
                    baseline_metric=baseline.cost_per_task_usd,
                    current_metric=current.cost_per_task_usd,
                )
            )

        if MetricsCollector._improved_upward(baseline.first_pass_rate, current.first_pass_rate) and (
            MetricsCollector._improved_upward(baseline.human_escalation_rate, current.human_escalation_rate)
        ):
            warnings.append(
                GoodhartWarning(
                    metric_name="first_pass_rate",
                    metric_direction="increased",
                    quality_direction="increased",
                    message="First pass rate improved but human escalation increased",
                    baseline_quality=baseline.human_escalation_rate,
                    current_quality=current.human_escalation_rate,
                    baseline_metric=baseline.first_pass_rate,
                    current_metric=current.first_pass_rate,
                )
            )

        if MetricsCollector._improved_downward(baseline.wall_time_per_task_s, current.wall_time_per_task_s) and (
            MetricsCollector._improved_upward(baseline.review_rejection_rate, current.review_rejection_rate)
        ):
            warnings.append(
                GoodhartWarning(
                    metric_name="wall_time_per_task_s",
                    metric_direction="decreased",
                    quality_direction="increased",
                    message="Wall time improved but review rejection rate increased",
                    baseline_quality=baseline.review_rejection_rate,
                    current_quality=current.review_rejection_rate,
                    baseline_metric=baseline.wall_time_per_task_s,
                    current_metric=current.wall_time_per_task_s,
                )
            )

        return warnings
