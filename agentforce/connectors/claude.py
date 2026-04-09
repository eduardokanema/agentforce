"""claude connector — runs prompts via the Claude Code CLI."""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

from agentforce.core.token_event import TokenEvent


def available() -> bool:
    try:
        r = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=10)
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
) -> tuple[bool, str, str, None, TokenEvent]:
    """Run claude CLI non-interactively with stream-json output.

    Returns:
        (success, output, error, None, token_event)
        session_id is always None — claude handles state internally.
    """
    cmd = ["claude", "--dangerously-skip-permissions", "-p", "--output-format", "stream-json", "--verbose"]
    if model:
        cmd += ["--model", model]

    output_parts: list[str] = []
    tokens_in = 0
    tokens_out = 0
    cost_usd = 0.0
    timed_out = False
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

        def _kill():
            nonlocal timed_out
            timed_out = True
            proc.kill()

        timer = threading.Timer(timeout, _kill)
        timer.start()
        sf = open(stream_path, "a", encoding="utf-8") if stream_path else None
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    output_parts.append(line)
                    if sf:
                        sf.write(line + "\n")
                        sf.flush()
                    continue

                etype = event.get("type", "")
                text_chunk = ""

                # Claude Code CLI stream-json emits text in "assistant" events
                if etype == "assistant":
                    for block in event.get("message", {}).get("content", []):
                        if block.get("type") == "text":
                            text_chunk += block.get("text", "")
                    if text_chunk:
                        output_parts.append(text_chunk)
                # Also handle standard Anthropic API content_block_delta events
                elif etype == "content_block_delta":
                    delta = event.get("delta", {})
                    text_chunk = delta.get("text", "")
                    if text_chunk:
                        output_parts.append(text_chunk)

                # Write only extracted text to stream — never raw JSON
                if sf and text_chunk:
                    sf.write(text_chunk)
                    sf.flush()

                # usage: "result" event has final totals; also check assistant/message_start
                if etype == "result":
                    usage = event.get("usage", {})
                    tokens_in = usage.get("input_tokens", tokens_in)
                    tokens_out = usage.get("output_tokens", tokens_out)
                    cost_usd = event.get("total_cost_usd", 0.0)
                else:
                    usage = event.get("usage", {})
                    if not usage and etype in ("message_start", "assistant"):
                        usage = event.get("message", {}).get("usage", {})
                    tokens_in += usage.get("input_tokens", 0)
                    tokens_out += usage.get("output_tokens", 0)

            proc.wait()
        finally:
            timer.cancel()
            if sf:
                sf.close()

        token_event = TokenEvent(tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost_usd)
        if timed_out:
            return False, "".join(output_parts).strip(), "claude timed out", None, token_event
        stderr = proc.stderr.read()
        return proc.returncode == 0, "".join(output_parts).strip(), stderr.strip(), None, token_event
    except Exception as e:
        token_event = TokenEvent(tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost_usd)
        return False, "".join(output_parts).strip(), str(e), None, token_event
