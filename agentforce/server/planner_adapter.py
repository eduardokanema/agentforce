"""Planner adapter boundary for draft-oriented plan turns."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Iterable
from urllib import request as urllib_request

from agentforce.core.spec import MissionSpec
from agentforce.server.routes.providers import _ssl_context


@dataclass(frozen=True)
class PlannerEvent:
    phase: str
    status: str
    content: str = ""

    def to_dict(self) -> dict[str, str]:
        payload = {
            "type": "status" if not self.content else "assistant",
            "phase": self.phase,
            "status": self.status,
        }
        if self.content:
            payload["content"] = self.content
        return payload


@dataclass(frozen=True)
class PlannerTurnResult:
    events: list[PlannerEvent]
    assistant_message: str
    draft_spec: dict[str, Any]


class PlannerAdapter:
    def plan_turn(self, draft: dict[str, Any], user_message: str) -> PlannerTurnResult:
        raise NotImplementedError


class DeterministicPlannerAdapter(PlannerAdapter):
    """Deterministic helper used explicitly by tests."""

    def plan_turn(self, draft: dict[str, Any], user_message: str) -> PlannerTurnResult:
        draft_spec = dict(draft.get("draft_spec") or {})
        existing_goal = str(draft_spec.get("goal") or "").strip()
        base_goal = existing_goal or user_message.strip() or "Plan the mission"
        draft_spec["goal"] = base_goal
        draft_spec.setdefault("name", _title_from_goal(base_goal))
        draft_spec.setdefault("definition_of_done", ["Planner draft is ready for refinement"])
        draft_spec.setdefault("tasks", [])
        draft_spec.setdefault("caps", {})

        assistant_message = f"Updated planning draft from: {user_message.strip() or 'no message provided'}"
        return PlannerTurnResult(
            events=[
                PlannerEvent(phase="planning", status="started"),
                PlannerEvent(phase="planning", status="completed", content=assistant_message),
            ],
            assistant_message=assistant_message,
            draft_spec=draft_spec,
        )


class LivePlannerAdapter(PlannerAdapter):
    """Live provider-backed planner adapter.

    Preferred path: claude Code CLI connector (no API key required).
    Fallback: OpenRouter or Anthropic HTTP API.
    """

    def plan_turn(self, draft: dict[str, Any], user_message: str) -> PlannerTurnResult:
        from agentforce.connectors import claude as _claude_connector

        system_prompt = _build_system_prompt(draft)
        prompt = _build_user_prompt(draft, user_message)
        model = _select_model(draft, use_openrouter=False)

        if _claude_connector.available():
            response_text = _claude_cli_completion(model, system_prompt, prompt)
        else:
            openrouter_key, anthropic_key = _load_provider_keys()
            if not openrouter_key and not anthropic_key:
                raise RuntimeError(
                    "no AI provider configured — install claude CLI or add an API key in Models settings"
                )
            if openrouter_key:
                model = _select_model(draft, use_openrouter=True)
                response_text = _openrouter_completion(openrouter_key, model, system_prompt, prompt)
            else:
                response_text = _anthropic_completion(anthropic_key, model, system_prompt, prompt)

        assistant_message, draft_spec = _parse_planner_response(response_text)
        return PlannerTurnResult(
            events=[
                PlannerEvent(phase="planning", status="started"),
                PlannerEvent(phase="planning", status="completed", content=assistant_message),
            ],
            assistant_message=assistant_message,
            draft_spec=draft_spec,
        )


def get_planner_adapter() -> PlannerAdapter:
    return LivePlannerAdapter()


def iter_sse_payloads(events: Iterable[PlannerEvent]) -> Iterable[str]:
    for event in events:
        yield f"data: {json.dumps(event.to_dict())}\n\n"


def _load_provider_keys() -> tuple[str | None, str | None]:
    openrouter_key = None
    anthropic_key = None
    try:
        import keyring

        try:
            openrouter_key = keyring.get_password("agentforce-provider", "openrouter")
        except Exception:
            openrouter_key = None
        if not openrouter_key:
            try:
                anthropic_key = keyring.get_password("agentforce", "anthropic")
            except Exception:
                anthropic_key = None
    except Exception:
        pass
    if not anthropic_key:
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    return openrouter_key, anthropic_key


def _select_model(draft: dict[str, Any], *, use_openrouter: bool) -> str:
    approved_models = list(draft.get("approved_models") or [])
    if approved_models:
        return str(approved_models[0])
    return "anthropic/claude-sonnet-4-6" if use_openrouter else "claude-sonnet-4-6"


def _build_user_prompt(draft: dict[str, Any], user_message: str) -> str:
    workspace_paths = list(draft.get("workspace_paths") or [])
    workspace_info = ", ".join(workspace_paths) if workspace_paths else "not specified"
    current_spec = json.dumps(draft.get("draft_spec") or {}, indent=2, sort_keys=True)
    return (
        "Update the mission planning draft.\n"
        "Return valid JSON only with keys 'assistant_message' and 'draft_spec'.\n"
        "'draft_spec' must be a complete AgentForce MissionSpec-shaped object.\n\n"
        f"Workspaces: {workspace_info}\n\n"
        f"Current draft_spec JSON:\n{current_spec}\n\n"
        f"User message:\n{user_message}\n"
    )


def _build_system_prompt(draft: dict[str, Any]) -> str:
    draft_spec_json = json.dumps(draft.get("draft_spec") or {}, indent=2, sort_keys=True)
    return (
        "You are AgentForce's mission planner. "
        "Return JSON only with keys 'assistant_message' and 'draft_spec'. "
        "Do not wrap the JSON in markdown fences or add extra prose.\n\n"
        f"Current draft_spec:\n{draft_spec_json}"
    )


def _claude_cli_completion(model: str, system_prompt: str, prompt: str) -> str:
    """Run the planner turn via the Claude Code CLI connector."""
    from agentforce.connectors import claude as _claude_connector
    import tempfile, os

    full_prompt = f"{system_prompt}\n\n{prompt}"
    workdir = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        success, output, error, _, _ = _claude_connector.run(
            prompt=full_prompt,
            workdir=workdir,
            timeout=120,
            model=model,
        )
    if not success and not output:
        raise RuntimeError(f"claude CLI planner failed: {error[:200]}")
    # Strip markdown fences if claude wraps JSON in ```json ... ```
    text = output.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines
            if not line.startswith("```")
        ).strip()
    return text


def _openrouter_completion(api_key: str, model: str, system_prompt: str, prompt: str) -> str:
    payload = {
        "model": model,
        "stream": False,
        "max_tokens": 4096,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    }
    req = urllib_request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://agentforce.local",
            "X-Title": "AgentForce",
        },
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=120, context=_ssl_context()) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    return str(raw["choices"][0]["message"]["content"])


def _anthropic_completion(api_key: str, model: str, system_prompt: str, prompt: str) -> str:
    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": prompt}],
    )
    text_parts = [block.text for block in response.content if getattr(block, "type", "") == "text"]
    return "".join(text_parts)


def _parse_planner_response(response_text: str) -> tuple[str, dict[str, Any]]:
    try:
        payload = json.loads(response_text)
    except Exception as exc:
        raise RuntimeError("planner response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("planner response must be a JSON object")

    assistant_message = str(payload.get("assistant_message") or "").strip()
    draft_spec = payload.get("draft_spec")
    if not assistant_message:
        raise RuntimeError("planner response missing assistant_message")
    if not isinstance(draft_spec, dict):
        raise RuntimeError("planner response missing draft_spec object")

    mission_spec = MissionSpec.from_dict(draft_spec)
    issues = mission_spec.validate(stage="draft")
    if issues:
        raise RuntimeError(f"planner response draft_spec invalid: {issues[0]}")
    return assistant_message, mission_spec.to_dict()


def _title_from_goal(goal: str) -> str:
    words = [part for part in goal.strip().split() if part]
    if not words:
        return "Untitled Mission"
    return " ".join(words[:6]).strip().title()
