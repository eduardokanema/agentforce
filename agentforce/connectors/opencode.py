"""opencode connector — runs prompts via the opencode CLI."""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path


def available() -> bool:
    try:
        r = subprocess.run(["opencode", "--version"], capture_output=True, text=True, timeout=10)
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
) -> tuple[bool, str, str, str | None]:
    """Run opencode CLI with a prompt.

    Uses JSON format to stream output and capture the session ID for reuse
    across retries (caching).

    Returns:
        (success, output, error, session_id)
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
        sf = open(stream_path, "a", encoding="utf-8") if stream_path else None
        try:
            for line in proc.stdout:
                if sf:
                    sf.write(line)
                    sf.flush()
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if returned_session_id is None:
                        returned_session_id = event.get("sessionID")
                    if event.get("type") == "text":
                        text_parts.append(event.get("part", {}).get("text", ""))
                except (json.JSONDecodeError, AttributeError):
                    text_parts.append(line)
            proc.wait()
        finally:
            timer.cancel()
            if sf:
                sf.close()

        if timed_out:
            return False, "".join(text_parts).strip(), "opencode timed out", returned_session_id

        error = proc.stderr.read().strip()
        output = "".join(text_parts).strip()
        success = proc.returncode == 0 and "error" not in (error or "").lower()
        return success, output, error, returned_session_id
    except Exception as e:
        return False, "".join(text_parts).strip(), str(e), returned_session_id
