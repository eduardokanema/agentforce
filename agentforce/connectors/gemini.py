"""gemini connector — runs prompts via the Gemini CLI."""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

from agentforce.core.token_event import TokenEvent
from agentforce.streaming import StreamRecorder


_MODEL_ALIASES = {
    "pro": "gemini-2.5-pro",
    "flash": "gemini-2.5-flash",
    "flash-lite": "gemini-2.5-flash-lite",
}


def _normalize_model(model: str | None) -> tuple[str | None, str | None]:
    if not model or model == "auto":
        return None, None
    model = model.strip()
    if not model:
        return None, None
    normalized = _MODEL_ALIASES.get(model, model)
    if not normalized.startswith("gemini-"):
        return None, f"{model!r} is not a Gemini model. Change the task agent/provider or select a Gemini model."
    return normalized, None


def available() -> bool:
    try:
        r = subprocess.run(["gemini", "--version"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def run(
    prompt: str,
    workdir: str,
    timeout: int = 300,
    model: str = None,
    stream_path: Path = None,
    variant: str = None,
    session_id: str = None,
) -> tuple[bool, str, str, str | None, TokenEvent]:
    """Run gemini CLI non-interactively with stream-json output.

    Returns:
        (success, output, error, session_id, token_event)
    """
    normalized_model, model_error = _normalize_model(model)
    if model_error:
        return False, "", model_error, session_id, TokenEvent(tokens_in=0, tokens_out=0, cost_usd=0.0)

    cmd = ["gemini", "--yolo", "-p", prompt, "--output-format", "stream-json"]
    if normalized_model:
        cmd += ["--model", normalized_model]

    output_parts: list[str] = []
    tokens_in = 0
    tokens_out = 0
    cost_usd = 0.0
    timed_out = False
    new_session_id = session_id

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
        recorder = StreamRecorder.from_raw_stream_path(stream_path, provider="gemini")
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type", "")
                if etype == "init":
                    if not new_session_id:
                        new_session_id = event.get("session_id")
                elif etype == "message":
                    if event.get("role") == "assistant":
                        content = event.get("content", "")
                        if content:
                            output_parts.append(content)
                            if recorder:
                                recorder.text_delta(content, role="assistant")
                    elif recorder:
                        recorder.raw_line(line, role="system", meta={"provider_event_type": etype})
                elif etype == "result":
                    stats = event.get("stats", {})
                    tokens_in = stats.get("input_tokens", tokens_in)
                    tokens_out = stats.get("output_tokens", tokens_out)
                    cost_usd = stats.get("total_cost_usd", cost_usd)
                    if recorder:
                        recorder.usage(tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost_usd)
                elif recorder:
                    recorder.raw_line(line, role="system", meta={"provider_event_type": etype})

            proc.wait()
        finally:
            timer.cancel()

        token_event = TokenEvent(tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost_usd)
        if timed_out:
            if recorder:
                recorder.error("gemini timed out")
            return False, "".join(output_parts).strip(), "gemini timed out", new_session_id, token_event
        stderr = proc.stderr.read()
        if stderr.strip() and recorder:
            recorder.error(stderr.strip())
        return proc.returncode == 0, "".join(output_parts).strip(), stderr.strip(), new_session_id, token_event
    except Exception as e:
        token_event = TokenEvent(tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost_usd)
        return False, "".join(output_parts).strip(), str(e), new_session_id, token_event
