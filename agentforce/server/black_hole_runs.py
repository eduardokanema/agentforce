"""Durable storage for black-hole planning campaigns and loop records."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from . import state_io
from .plan_drafts import redact_persisted_content

_OWNER_DIR_MODE = 0o700
_OWNER_FILE_MODE = 0o600
_TERMINAL_STATUSES = frozenset(
    {
        "succeeded",
        "max_loops_reached",
        "no_progress_limit",
        "launch_failed",
        "evaluation_failed",
        "cancelled",
    }
)
_ACTIVE_STATUSES = frozenset(
    {
        "preflight_pending",
        "evaluating_workspace",
        "candidate_locked",
        "child_mission_running",
        "reviewing_result",
        "waiting_human",
        "paused",
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_terminal_campaign_status(status: str) -> bool:
    return status in _TERMINAL_STATUSES


@dataclass(frozen=True)
class BlackHoleLoopRecord:
    campaign_id: str
    loop_no: int
    status: str
    created_at: str
    completed_at: str | None = None
    candidate_id: str = ""
    candidate_summary: str = ""
    candidate_payload: dict[str, Any] = field(default_factory=dict)
    metric_before: dict[str, Any] = field(default_factory=dict)
    metric_after: dict[str, Any] = field(default_factory=dict)
    normalized_delta: float = 0.0
    plan_run_id: str | None = None
    plan_version_id: str | None = None
    mission_id: str | None = None
    review_summary: str = ""
    gate_reason: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "loop_no": self.loop_no,
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "candidate_id": self.candidate_id,
            "candidate_summary": self.candidate_summary,
            "candidate_payload": self.candidate_payload,
            "metric_before": self.metric_before,
            "metric_after": self.metric_after,
            "normalized_delta": self.normalized_delta,
            "plan_run_id": self.plan_run_id,
            "plan_version_id": self.plan_version_id,
            "mission_id": self.mission_id,
            "review_summary": self.review_summary,
            "gate_reason": self.gate_reason,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BlackHoleLoopRecord:
        return cls(
            campaign_id=str(payload.get("campaign_id") or ""),
            loop_no=int(payload.get("loop_no") or 0),
            status=str(payload.get("status") or ""),
            created_at=str(payload.get("created_at") or _utc_now()),
            completed_at=payload.get("completed_at"),
            candidate_id=str(payload.get("candidate_id") or ""),
            candidate_summary=str(payload.get("candidate_summary") or ""),
            candidate_payload=dict(payload.get("candidate_payload") or {}),
            metric_before=dict(payload.get("metric_before") or {}),
            metric_after=dict(payload.get("metric_after") or {}),
            normalized_delta=float(payload.get("normalized_delta") or 0.0),
            plan_run_id=payload.get("plan_run_id"),
            plan_version_id=payload.get("plan_version_id"),
            mission_id=payload.get("mission_id"),
            review_summary=str(payload.get("review_summary") or ""),
            gate_reason=str(payload.get("gate_reason") or ""),
            tokens_in=int(payload.get("tokens_in") or 0),
            tokens_out=int(payload.get("tokens_out") or 0),
            cost_usd=float(payload.get("cost_usd") or 0.0),
        )

    def copy_with(self, **changes: Any) -> BlackHoleLoopRecord:
        payload = self.to_dict()
        payload.update(changes)
        return BlackHoleLoopRecord.from_dict(payload)


@dataclass(frozen=True)
class BlackHoleCampaignRecord:
    id: str
    draft_id: str
    status: str
    created_at: str
    updated_at: str
    current_loop: int = 0
    max_loops: int = 8
    max_no_progress: int = 2
    no_progress_count: int = 0
    active_child_mission_id: str | None = None
    active_plan_run_id: str | None = None
    last_metric: dict[str, Any] = field(default_factory=dict)
    last_delta: float = 0.0
    stop_reason: str = ""
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    lease_owner: str | None = None
    lease_acquired_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "draft_id": self.draft_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "current_loop": self.current_loop,
            "max_loops": self.max_loops,
            "max_no_progress": self.max_no_progress,
            "no_progress_count": self.no_progress_count,
            "active_child_mission_id": self.active_child_mission_id,
            "active_plan_run_id": self.active_plan_run_id,
            "last_metric": self.last_metric,
            "last_delta": self.last_delta,
            "stop_reason": self.stop_reason,
            "config_snapshot": self.config_snapshot,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
            "lease_owner": self.lease_owner,
            "lease_acquired_at": self.lease_acquired_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BlackHoleCampaignRecord:
        created_at = str(payload.get("created_at") or _utc_now())
        return cls(
            id=str(payload.get("id") or ""),
            draft_id=str(payload.get("draft_id") or ""),
            status=str(payload.get("status") or "evaluating_workspace"),
            created_at=created_at,
            updated_at=str(payload.get("updated_at") or created_at),
            current_loop=int(payload.get("current_loop") or 0),
            max_loops=int(payload.get("max_loops") or 8),
            max_no_progress=int(payload.get("max_no_progress") or 2),
            no_progress_count=int(payload.get("no_progress_count") or 0),
            active_child_mission_id=payload.get("active_child_mission_id"),
            active_plan_run_id=payload.get("active_plan_run_id"),
            last_metric=dict(payload.get("last_metric") or {}),
            last_delta=float(payload.get("last_delta") or 0.0),
            stop_reason=str(payload.get("stop_reason") or ""),
            config_snapshot=dict(payload.get("config_snapshot") or {}),
            tokens_in=int(payload.get("tokens_in") or 0),
            tokens_out=int(payload.get("tokens_out") or 0),
            cost_usd=float(payload.get("cost_usd") or 0.0),
            lease_owner=payload.get("lease_owner"),
            lease_acquired_at=payload.get("lease_acquired_at"),
        )

    def copy_with(self, **changes: Any) -> BlackHoleCampaignRecord:
        payload = self.to_dict()
        payload.update(changes)
        payload.setdefault("updated_at", _utc_now())
        return BlackHoleCampaignRecord.from_dict(payload)


class BlackHoleCampaignStore:
    """JSON-backed store for campaign state and loop provenance."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or (state_io.get_agentforce_home() / "black_hole")
        self._campaigns_dir = self._root / "campaigns"
        self._loops_dir = self._root / "loops"

    def create_campaign(
        self,
        campaign_id: str,
        *,
        draft_id: str,
        max_loops: int,
        max_no_progress: int,
        config_snapshot: dict[str, Any],
        status: str = "evaluating_workspace",
    ) -> BlackHoleCampaignRecord:
        existing = self.latest_for_draft(draft_id)
        if existing is not None and not is_terminal_campaign_status(existing.status):
            raise ValueError(f"Draft {draft_id!r} already has an active black-hole campaign")
        now = _utc_now()
        campaign = BlackHoleCampaignRecord(
            id=campaign_id,
            draft_id=draft_id,
            status=status,
            created_at=now,
            updated_at=now,
            max_loops=max_loops,
            max_no_progress=max_no_progress,
            config_snapshot=dict(config_snapshot or {}),
        )
        self.save_campaign(campaign)
        return campaign

    def load_campaign(self, campaign_id: str) -> BlackHoleCampaignRecord | None:
        path = self._campaigns_dir / f"{campaign_id}.json"
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as handle:
            return BlackHoleCampaignRecord.from_dict(json.load(handle))

    def save_campaign(self, campaign: BlackHoleCampaignRecord) -> None:
        payload = campaign.copy_with(updated_at=_utc_now()).to_dict()
        self._write_json(self._campaigns_dir / f"{campaign.id}.json", payload)

    def latest_for_draft(self, draft_id: str) -> BlackHoleCampaignRecord | None:
        campaigns = [campaign for campaign in self.list_campaigns() if campaign.draft_id == draft_id]
        if not campaigns:
            return None
        campaigns.sort(key=lambda item: item.updated_at, reverse=True)
        return campaigns[0]

    def find_by_active_child_mission(self, mission_id: str) -> BlackHoleCampaignRecord | None:
        for campaign in self.list_campaigns():
            if campaign.active_child_mission_id == mission_id and not is_terminal_campaign_status(campaign.status):
                return campaign
        return None

    def list_campaigns(self) -> list[BlackHoleCampaignRecord]:
        if not self._campaigns_dir.exists():
            return []
        campaigns: list[BlackHoleCampaignRecord] = []
        for path in sorted(self._campaigns_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                with path.open(encoding="utf-8") as handle:
                    campaigns.append(BlackHoleCampaignRecord.from_dict(json.load(handle)))
            except Exception:
                continue
        return campaigns

    def list_loops(self, campaign_id: str) -> list[BlackHoleLoopRecord]:
        if not self._loops_dir.exists():
            return []
        loops: list[BlackHoleLoopRecord] = []
        for path in sorted(self._loops_dir.glob(f"{campaign_id}--*.json")):
            try:
                with path.open(encoding="utf-8") as handle:
                    loops.append(BlackHoleLoopRecord.from_dict(json.load(handle)))
            except Exception:
                continue
        loops.sort(key=lambda item: item.loop_no)
        return loops

    def load_loop(self, campaign_id: str, loop_no: int) -> BlackHoleLoopRecord | None:
        path = self._loops_dir / f"{campaign_id}--{loop_no:04d}.json"
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as handle:
            return BlackHoleLoopRecord.from_dict(json.load(handle))

    def save_loop(self, loop: BlackHoleLoopRecord) -> None:
        self._write_json(self._loops_dir / f"{loop.campaign_id}--{loop.loop_no:04d}.json", loop.to_dict())

    def next_loop_number(self, campaign_id: str) -> int:
        loops = self.list_loops(campaign_id)
        if not loops:
            return 1
        return loops[-1].loop_no + 1

    def summarize(self, draft_id: str) -> dict[str, Any]:
        campaign = self.latest_for_draft(draft_id)
        return {
            "draft_id": draft_id,
            "campaign": campaign.to_dict() if campaign is not None else None,
            "loops": [loop.to_dict() for loop in self.list_loops(campaign.id)] if campaign is not None else [],
        }

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, _OWNER_DIR_MODE)
        sanitized = redact_persisted_content(payload)
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(json.dumps(sanitized, indent=2))
        os.chmod(temp_path, _OWNER_FILE_MODE)
        os.replace(temp_path, path)
        os.chmod(path, _OWNER_FILE_MODE)
