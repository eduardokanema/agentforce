"""opencode connector — runs prompts via the opencode CLI."""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

from agentforce.core.token_event import TokenEvent
from agentforce.streaming import StreamRecorder

_USAGE_TYPES = ("usage", "tokens", "stats")
_IN_KEYS = ("inputTokens", "promptTokens", "tokensIn")
_OUT_KEYS = ("outputTokens", "completionTokens", "tokensOut")
# opencode emits token data in step_finish under part.tokens with "input"/"output" keys
_STEP_FINISH_TYPE = "step_finish"


def available() -> bool:
    try:
        r = subprocess.run(["opencode", "--version"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _extract_tokens(event: dict) -> tuple[int, int]:
    """Return (tokens_in, tokens_out) from a usage event, or (0, 0) if none."""
    t = event.get("type", "")

    # opencode step_finish: tokens are in event["part"]["tokens"] with "input"/"output" keys
    if t == _STEP_FINISH_TYPE:
        part_tokens = event.get("part", {}).get("tokens", {})
        if part_tokens:
            return int(part_tokens.get("input", 0)), int(part_tokens.get("output", 0))

    # fallback: top-level usage-type events or events with token keys
    is_usage_type = t in _USAGE_TYPES
    has_token_keys = any(k in event for k in _IN_KEYS + _OUT_KEYS)
    if not (is_usage_type or has_token_keys):
        return 0, 0

    tokens_in = 0
    for k in _IN_KEYS:
        v = event.get(k)
        if v is not None:
            try:
                tokens_in = int(v)
            except (TypeError, ValueError):
                pass
            break

    tokens_out = 0
    for k in _OUT_KEYS:
        v = event.get(k)
        if v is not None:
            try:
                tokens_out = int(v)
            except (TypeError, ValueError):
                pass
            break

    return tokens_in, tokens_out


def run(
    prompt: str,
    workdir: str,
    timeout: int = 300,
    model: str = None,
    stream_path: Path = None,
    variant: str = None,
    session_id: str = None,
) -> tuple[bool, str, str, str | None, TokenEvent]:
    """Run opencode CLI with a prompt.

    Uses JSON format to stream output and capture the session ID for reuse
    across retries (caching). Also captures token usage events.

    Returns:
        (success, output, error, session_id, token_event)
    """
    cmd = ["opencode", "run", "--format", "json", prompt]
    if model:
        cmd += ["--model", model]
    if variant:
        cmd += ["--variant", variant]
    if session_id:
        cmd += ["--session", session_id, "--continue"]

    text_parts: list[str] = []
    returned_session_id: str | None = None
    timed_out = False
    total_in = 0
    total_out = 0

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=workdir,
            env=os.environ.copy(),
        )

        def _kill():
            nonlocal timed_out
            timed_out = True
            proc.kill()

        timer = threading.Timer(timeout, _kill)
        timer.start()
        recorder = StreamRecorder.from_raw_stream_path(stream_path, provider="opencode")
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if returned_session_id is None:
                        returned_session_id = event.get("sessionID")
                    text_chunk = ""
                    if event.get("type") == "text":
                        text_chunk = event.get("part", {}).get("text", "")
                        if text_chunk:
                            text_parts.append(text_chunk)
                    if recorder and text_chunk:
                        recorder.text_delta(text_chunk, role="assistant")
                    elif recorder:
                        recorder.raw_line(line, role="system", meta={"provider_event_type": event.get("type", "")})
                    t_in, t_out = _extract_tokens(event)
                    total_in += t_in
                    total_out += t_out
                    if recorder and (t_in or t_out):
                        recorder.usage(tokens_in=total_in, tokens_out=total_out, cost_usd=0.0)
                except (json.JSONDecodeError, AttributeError):
                    text_parts.append(line)
                    if recorder:
                        recorder.raw_line(line, role="system", meta={"provider_event_type": "non_json"})
            proc.wait()
        finally:
            timer.cancel()

        token_event = TokenEvent(tokens_in=total_in, tokens_out=total_out, cost_usd=0.0)

        if timed_out:
            if recorder:
                recorder.error("opencode timed out")
            return False, "".join(text_parts).strip(), "opencode timed out", returned_session_id, token_event

        error = proc.stderr.read().strip()
        if error and recorder:
            recorder.error(error)
        output = "".join(text_parts).strip()
        success = proc.returncode == 0 and "error" not in (error or "").lower()
        return success, output, error, returned_session_id, token_event
    except Exception as e:
        token_event = TokenEvent(tokens_in=total_in, tokens_out=total_out, cost_usd=0.0)
        return False, "".join(text_parts).strip(), str(e), returned_session_id, token_event
