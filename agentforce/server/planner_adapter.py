"""Planner adapter boundary for draft-oriented plan turns."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Iterable
from urllib import request as urllib_request

from agentforce.core.spec import MissionSpec
from agentforce.server.routes.providers import _get_provider_models, _ssl_context


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
        from agentforce.connectors import codex as _codex_connector
        from agentforce.connectors import gemini as _gemini_connector

        system_prompt = _build_system_prompt(draft)
        prompt = _build_user_prompt(draft, user_message)
        preferred_agent = _preferred_planner_agent(draft)

        if preferred_agent == "codex" and _codex_connector.available():
            model = _select_model(draft, provider="codex", use_openrouter=False)
            response_text = _codex_cli_completion(model, system_prompt, prompt)
        elif preferred_agent == "claude" and _claude_connector.available():
            model = _select_model(draft, provider="claude", use_openrouter=False)
            response_text = _claude_cli_completion(model, system_prompt, prompt)
        elif preferred_agent == "gemini" and _gemini_connector.available():
            model = _select_model(draft, provider="gemini", use_openrouter=False)
            response_text = _gemini_cli_completion(model, system_prompt, prompt)
        elif _claude_connector.available():
            model = _select_model(draft, provider="claude", use_openrouter=False)
            response_text = _claude_cli_completion(model, system_prompt, prompt)
        elif _codex_connector.available():
            model = _select_model(draft, provider="codex", use_openrouter=False)
            response_text = _codex_cli_completion(model, system_prompt, prompt)
        elif _gemini_connector.available():
            model = _select_model(draft, provider="gemini", use_openrouter=False)
            response_text = _gemini_cli_completion(model, system_prompt, prompt)
        else:
            openrouter_key, anthropic_key = _load_provider_keys()
            if not openrouter_key and not anthropic_key:
                raise RuntimeError(
                    "no AI provider configured — install claude CLI or add an API key in Models settings"
                )
            if openrouter_key:
                model = _select_model(draft, provider="openrouter", use_openrouter=True)
                response_text = _openrouter_completion(openrouter_key, model, system_prompt, prompt)
            else:
                model = _select_model(draft, provider="anthropic", use_openrouter=False)
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


def _planning_profile(draft: dict[str, Any]) -> dict[str, Any]:
    validation = draft.get("validation")
    if not isinstance(validation, dict):
        return {}
    planning_profiles = validation.get("planning_profiles")
    if not isinstance(planning_profiles, dict):
        return {}
    planner = planning_profiles.get("planner")
    return planner if isinstance(planner, dict) else {}


def _preferred_planner_agent(draft: dict[str, Any]) -> str:
    planner = _planning_profile(draft)
    agent = str(planner.get("agent") or "").strip()
    return agent or "claude"


def _provider_model_ids(provider: str) -> set[str]:
    if provider not in {"claude", "codex", "gemini"}:
        return set()
    try:
        return {
            str(model.get("id") or "").strip()
            for model in _get_provider_models(provider)
            if isinstance(model, dict) and str(model.get("id") or "").strip()
        }
    except Exception:
        return set()


def _provider_default_model(provider: str, *, use_openrouter: bool) -> str | None:
    model_ids = _provider_model_ids(provider)
    if provider == "claude":
        return next(iter(model_ids), "claude-sonnet-4-6")
    if provider == "codex":
        return next(iter(model_ids), None)
    if provider == "gemini":
        return next(iter(model_ids), "auto")
    if provider == "openrouter":
        return "anthropic/claude-sonnet-4-6"
    if provider == "anthropic":
        return "claude-sonnet-4-6"
    return "anthropic/claude-sonnet-4-6" if use_openrouter else None


def _model_supported_by_provider(model: str, provider: str) -> bool:
    if not model:
        return False
    if provider in {"openrouter", "anthropic"}:
        return True
    return model in _provider_model_ids(provider)


def _select_model(draft: dict[str, Any], *, provider: str, use_openrouter: bool) -> str | None:
    planner = _planning_profile(draft)
    planner_model = str(planner.get("model") or "").strip()
    planner_agent = str(planner.get("agent") or "").strip()
    approved_models = list(draft.get("approved_models") or [])
    if planner_agent == provider and _model_supported_by_provider(planner_model, provider):
        return planner_model
    for model in approved_models:
        model_value = str(model or "").strip()
        if _model_supported_by_provider(model_value, provider):
            return model_value
    return _provider_default_model(provider, use_openrouter=use_openrouter)


def _is_unavailable_model_error(output: str, error: str) -> bool:
    text = f"{error}\n{output}".lower()
    return (
        "selected model" in text
        and ("may not exist" in text or "may not have access" in text or "pick a different model" in text)
    )


def _build_user_prompt(draft: dict[str, Any], user_message: str) -> str:
    workspace_paths = list(draft.get("workspace_paths") or [])
    workspace_info = ", ".join(workspace_paths) if workspace_paths else "not specified"
    current_spec = json.dumps(draft.get("draft_spec") or {}, indent=2, sort_keys=True)
    validation = dict(draft.get("validation") or {})
    preflight_answers = dict(validation.get("preflight_answers") or {})
    preflight_questions = list(validation.get("preflight_questions") or [])
    clarification_lines: list[str] = []
    for question in preflight_questions:
        if not isinstance(question, dict):
            continue
        question_id = str(question.get("id") or "")
        answer = preflight_answers.get(question_id)
        if not isinstance(answer, dict):
            continue
        selected = str(answer.get("selected_option") or "").strip()
        custom = str(answer.get("custom_answer") or "").strip()
        if selected or custom:
            rendered_answer = custom or selected
            clarification_lines.append(f"- {question.get('prompt')}: {rendered_answer}")
    clarifications = "\n".join(clarification_lines) if clarification_lines else "No preflight clarifications provided."
    return (
        "Update the mission planning draft.\n"
        "Return valid JSON only with keys 'assistant_message' and 'draft_spec'.\n"
        "'draft_spec' must be a complete AgentForce MissionSpec-shaped object.\n\n"
        f"Workspaces: {workspace_info}\n\n"
        f"Preflight clarifications:\n{clarifications}\n\n"
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


def _gemini_cli_completion(model: str, system_prompt: str, prompt: str) -> str:
    """Run the planner turn via the Gemini CLI connector."""
    from agentforce.connectors import gemini as _gemini_connector
    import os

    full_prompt = f"{system_prompt}\n\n{prompt}"
    workdir = os.getcwd()
    success, output, error, _, _ = _gemini_connector.run(
        prompt=full_prompt,
        workdir=workdir,
        timeout=120,
        model=model,
    )
    if not success and model and _is_unavailable_model_error(output, error):
        success, output, error, _, _ = _gemini_connector.run(
            prompt=full_prompt,
            workdir=workdir,
            timeout=120,
            model=None,
        )
    if not success and not output:
        raise RuntimeError(f"gemini CLI planner failed: {error[:200]}")
    # Strip markdown fences if gemini wraps JSON in ```json ... ```
    text = output.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines
            if not line.startswith("```")
        ).strip()
    return text


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
            timeout=180,
            model=model,
        )
        if not success and model and _is_unavailable_model_error(output, error):
            success, output, error, _, _ = _claude_connector.run(
                prompt=full_prompt,
                workdir=workdir,
                timeout=180,
                model=None,
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


def _codex_cli_completion(model: str | None, system_prompt: str, prompt: str) -> str:
    from agentforce.connectors import codex as _codex_connector
    import os

    full_prompt = f"{system_prompt}\n\n{prompt}"
    workdir = os.getcwd()
    success, output, error, _, _ = _codex_connector.run(
        prompt=full_prompt,
        workdir=workdir,
        timeout=180,
        model=model,
    )
    if not success and model and _is_unavailable_model_error(output, error):
        success, output, error, _, _ = _codex_connector.run(
            prompt=full_prompt,
            workdir=workdir,
            timeout=180,
            model=None,
        )
    if not success and not output:
        raise RuntimeError(f"codex CLI planner failed: {error[:200]}")
    return output.strip()


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
    text = response_text.strip()
    payload = None

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        pass

    if payload is None and "```json" in text:
        try:
            block = text.split("```json", 1)[1].split("```", 1)[0].strip()
            payload = json.loads(block)
        except (json.JSONDecodeError, IndexError):
            pass

    if payload is None:
        payload = _extract_planner_payload_candidate(text)

    if payload is None:
        preview = " ".join(text.split())
        if len(preview) > 240:
            preview = preview[:237] + "..."
        detail = f": {preview}" if preview else ""
        raise RuntimeError(f"planner response was not valid JSON{detail}")
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


def _extract_planner_payload_candidate(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []

    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            candidate, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            candidates.append(candidate)

    for candidate in reversed(candidates):
        if isinstance(candidate.get("assistant_message"), str) and isinstance(candidate.get("draft_spec"), dict):
            return candidate

    for candidate in reversed(candidates):
        if isinstance(candidate, dict):
            return candidate

    return None


def _title_from_goal(goal: str) -> str:
    words = [part for part in goal.strip().split() if part]
    if not words:
        return "Untitled Mission"
    return " ".join(words[:6]).strip().title()
