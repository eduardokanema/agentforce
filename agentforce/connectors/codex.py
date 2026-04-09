"""codex connector — runs prompts via the OpenAI Codex CLI (`codex exec --json`)."""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

from agentforce.core.token_event import TokenEvent


def available() -> bool:
    try:
        r = subprocess.run(["codex", "--version"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _format_event(event: dict) -> str | None:
    """Convert a codex JSONL event into a human-readable stream line."""
    t = event.get("type", "")

    if t == "item.started":
        item = event.get("item", {})
        if item.get("type") == "command_execution":
            return f"▶ {item.get('command', '')}"

    elif t == "item.completed":
        item = event.get("item", {})
        kind = item.get("type", "")
        if kind == "agent_message":
            return item.get("text", "")
        if kind == "command_execution":
            cmd = item.get("command", "")
            code = item.get("exit_code")
            out = item.get("aggregated_output", "").strip()
            status = "✓" if code == 0 else f"✗ [exit={code}]"
            parts = [f"{status} {cmd}"]
            if out:
                # Limit noisy output to avoid flooding the stream
                lines = out.splitlines()
                parts.extend(f"  {l}" for l in lines[:30])
                if len(lines) > 30:
                    parts.append(f"  … ({len(lines) - 30} more lines)")
            return "\n".join(parts)

    return None


def _append_prompt_arg(cmd: list[str], prompt: str) -> list[str]:
    """Feed prompts via stdin to avoid CLI parsing edge cases."""
    cmd.append("-")
    return cmd


def run(
    prompt: str,
    workdir: str,
    timeout: int = 300,
    model: str = None,
    stream_path: Path = None,
    variant: str = None,
    session_id: str = None,
) -> tuple[bool, str, str, str | None, TokenEvent]:
    """Run codex non-interactively via `codex exec --json`.

    --json makes codex emit JSONL events to stdout instead of a TUI,
    enabling real-time streaming. The thread_id from the first event is
    returned as session_id so retries can resume the same session.

    Returns:
        (success, output, error, thread_id | None, token_event)
    """
    if session_id:
        cmd = [
            "codex",
            "exec",
            "-C",
            workdir,
            "resume",
            "--dangerously-bypass-approvals-and-sandbox",
            "--json",
        ]
        if model:
            cmd += ["-m", model]
        cmd.append(session_id)
        _append_prompt_arg(cmd, prompt)
    else:
        cmd = ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "--json", "-C", workdir]
        if model:
            cmd += ["-m", model]
        _append_prompt_arg(cmd, prompt)

    text_parts: list[str] = []
    returned_thread_id: str | None = None
    timed_out = False
    tokens_in = 0
    tokens_out = 0

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=workdir,
            env=os.environ.copy(),
        )

        if proc.stdin is not None:
            proc.stdin.write(prompt)
            proc.stdin.close()

        def _kill():
            nonlocal timed_out
            timed_out = True
            proc.kill()

        timer = threading.Timer(timeout, _kill)
        timer.start()
        sf = open(stream_path, "a", encoding="utf-8") if stream_path else None
        try:
            for raw in proc.stdout:
                raw_stripped = raw.strip()
                if not raw_stripped:
                    continue
                try:
                    event = json.loads(raw_stripped)
                    # Capture thread_id from the first event
                    if returned_thread_id is None:
                        returned_thread_id = event.get("thread_id")
                    # Extract token counts from turn.completed — don't add to output
                    if event.get("type") == "turn.completed":
                        usage = event.get("usage", {})
                        tokens_in += usage.get("input_tokens", 0)
                        tokens_out += usage.get("output_tokens", 0)
                    else:
                        formatted = _format_event(event)
                        if formatted is not None:
                            text_parts.append(formatted)
                            if sf:
                                sf.write(formatted + "\n")
                                sf.flush()
                except (json.JSONDecodeError, AttributeError):
                    # Non-JSON line (banner, error) — pass through as-is
                    text_parts.append(raw_stripped)
                    if sf:
                        sf.write(raw_stripped + "\n")
                        sf.flush()
            proc.wait()
        finally:
            timer.cancel()
            if sf:
                sf.close()

        token_event = TokenEvent(tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=0.0)
        if timed_out:
            return False, "\n".join(text_parts).strip(), "codex timed out", returned_thread_id, token_event

        error = proc.stderr.read().strip()
        success = proc.returncode == 0
        return success, "\n".join(text_parts).strip(), error, returned_thread_id, token_event

    except Exception as e:
        token_event = TokenEvent(tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=0.0)
        return False, "\n".join(text_parts).strip(), str(e), returned_thread_id, token_event
